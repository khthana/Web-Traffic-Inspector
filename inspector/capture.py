"""TrafficCapture: แปลง event ของ Playwright เป็น Capture event

สอนแนวคิด: adapter — แปลงภาษาของ Playwright (Request, Response, Page)
ให้เป็นข้อมูลล้วนที่ส่วนอื่นของโปรแกรมเข้าใจ ถ้าวันหนึ่งเปลี่ยนไปใช้เครื่องมืออื่น ก็แก้แค่ไฟล์นี้
"""

import asyncio
import codecs
import time
from email.message import Message
from typing import Literal, cast

from playwright.async_api import BrowserContext, Page, Request, Response
from playwright.async_api import Error as PlaywrightError

from inspector.capture_events import (
    EventSink,
    RequestFailed,
    RequestStarted,
    ResponseReceived,
    TabChanged,
)
from inspector.click_tracker import ClickTracker
from inspector.http_parts import header, origin_of

MAX_BODY_BYTES = 64 * 1024
CAPTURED_TYPES = ("fetch", "xhr")
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
IGNORED_SCHEMES = ("about:", "chrome:", "chrome-extension:", "devtools:", "chrome-untrusted:", "edge:")
TEXT_HINTS = ("json", "text/", "xml", "javascript", "x-www-form-urlencoded", "graphql")

def now_ms() -> float:
    return time.time() * 1000


def is_inspector_url(url: str, inspector_origins: tuple[str, ...]) -> bool:
    """URL นี้เป็นของ Inspector เองไหม (เทียบแค่ origin)"""
    return origin_of(url) in {origin_of(origin) for origin in inspector_origins}


def is_watchable(url: str, inspector_origins: tuple[str, ...]) -> bool:
    """แท็บนี้เป็น Watched tab ได้ไหม (ไม่ดักหน้า Inspector เอง และหน้าภายในของ Chrome)"""
    return not url.startswith(IGNORED_SCHEMES) and not is_inspector_url(url, inspector_origins)


def describe_size(size: int) -> str:
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"


def charset_of(content_type: str) -> str:
    """อ่าน charset จาก Content-Type (เว็บไทยเก่าบางเว็บใช้ windows-874) ถ้าไม่บอกหรือไม่รู้จักใช้ UTF-8"""
    message = Message()
    message["content-type"] = content_type or "text/plain"
    charset = message.get_content_charset() or "utf-8"
    try:
        return codecs.lookup(charset).name
    except LookupError:
        return "utf-8"


def decode_body(content_type: str, raw: bytes) -> tuple[str | None, int, str | None]:
    """แปลง body เป็นข้อความ คืน (ข้อความ, จำนวน byte ที่ตัดทิ้ง, เหตุผลที่อ่านไม่ได้)"""
    if not raw:
        return None, 0, None
    textual = any(hint in content_type.lower() for hint in TEXT_HINTS)
    if not textual:
        if content_type:
            return None, 0, f"เป็นไฟล์ binary ({content_type.split(';')[0]}, {describe_size(len(raw))})"
        try:
            raw.decode("utf-8")  # ไม่บอกชนิดมา: ถ้าเป็น UTF-8 ล้วนก็ถือว่าเป็นข้อความ
        except UnicodeDecodeError:
            return None, 0, f"เป็นไฟล์ binary (ไม่ทราบชนิด, {describe_size(len(raw))})"
    # decoder แบบทีละช่วง: ถ้าตัดที่ 64 KB แล้วตกกลางตัวอักษร (เช่นภาษาไทย 3 byte)
    # มันจะเก็บ byte ที่ไม่ครบตัวไว้ แทนที่จะได้ตัวเพี้ยนท้ายข้อความ
    head = raw[:MAX_BODY_BYTES]
    decoder = codecs.getincrementaldecoder(charset_of(content_type))(errors="replace")
    text = decoder.decode(head, final=len(raw) <= MAX_BODY_BYTES)
    kept = len(head) - len(decoder.getstate()[0])
    return text, len(raw) - kept, None


async def all_headers(source: Request | Response) -> dict[str, str]:
    """header ครบทุกตัว (รวม cookie) ถ้าอ่านไม่ได้ใช้ชุดย่อที่ Playwright มีอยู่แล้ว"""
    try:
        return await source.all_headers()
    except PlaywrightError:
        return source.headers


class TrafficCapture:
    """ฟัง request/response ของทุก Watched tab ใน context แล้วส่ง Capture event ให้ `sink`

    สอนแนวคิด: dependency injection — class นี้ไม่รู้ว่าใครรับ event ต่อ รู้แค่ว่าต้องเรียก `sink`
    และ composition — มี ClickTracker อยู่ข้างในเพื่อดักคลิกของแท็บเดียวกัน
    """

    def __init__(self, sink: EventSink, inspector_origins: tuple[str, ...]) -> None:
        self._sink = sink
        self._origins = inspector_origins
        self._tab_ids: dict[Page, str] = {}
        self._started: dict[Request, asyncio.Task[str]] = {}
        self._next_tab = 0
        self._next_request = 0
        self._clicks = ClickTracker(sink, inspector_origins, tab_of=self.watched_tab_id, clock=now_ms)

    async def attach(self, context: BrowserContext) -> None:
        """เริ่มฟัง context นี้ รวมถึงแท็บที่จะเปิดใหม่ภายหลัง"""
        for task in self._started.values():  # งานค้างจากการเชื่อมรอบก่อน: ทิ้งไป
            task.cancel()
        self._tab_ids.clear()
        self._started.clear()
        context.on("page", self._track_page)
        context.on("request", self._on_request)
        context.on("requestfinished", self._on_finished)
        context.on("requestfailed", self._on_failed)
        for page in context.pages:
            self._track_page(page)
        await self._clicks.attach(context)

    def watched_tab_id(self, page: Page) -> str | None:
        """tab_id ของแท็บนี้ ถ้าตอนนี้ไม่ใช่ Watched tab คืน None"""
        self._track_page(page)  # หน้าในแท็บใหม่อาจส่งคลิกมาก่อน event "page" ของ Playwright
        tab_id = self._tab_ids.get(page)  # แท็บปิดไปแล้ว แต่คลิกที่ค้างท่อยังมาถึง
        return tab_id if tab_id is not None and is_watchable(page.url, self._origins) else None

    def _track_page(self, page: Page) -> None:
        """จำทุกแท็บไว้ (แม้ยังไม่ใช่ Watched tab) เพราะแท็บอาจ navigate มาเป็น Watched tab ทีหลัง"""
        if page in self._tab_ids or page.is_closed():
            return
        self._next_tab += 1
        self._tab_ids[page] = f"tab-{self._next_tab}"
        self._announce_tab(page)
        page.on("framenavigated", lambda frame: self._on_navigated(page) if frame == page.main_frame else None)
        page.on("close", lambda _: self._on_closed(page))

    def _announce_tab(self, page: Page) -> None:
        tab_id = self._tab_ids[page]
        self._sink(TabChanged(tab_id=tab_id, url=page.url, ts=now_ms(), open=is_watchable(page.url, self._origins)))

    def _on_navigated(self, page: Page) -> None:
        """อัปเดต URL ของแท็บ (Navigation จริงส่งมาจาก ClickTracker เพราะ event นี้นับ pushState ด้วย)"""
        if page in self._tab_ids:
            self._announce_tab(page)

    def _on_closed(self, page: Page) -> None:
        tab_id = self._tab_ids.pop(page, None)
        if tab_id is not None:
            self._sink(TabChanged(tab_id=tab_id, url=page.url, ts=now_ms(), open=False))

    def _on_request(self, request: Request) -> None:
        if request.resource_type not in CAPTURED_TYPES or is_inspector_url(request.url, self._origins):
            return
        page = self._page_of(request)  # request จาก service worker ไม่มีแท็บ จึงไม่ดัก
        if page is None or page not in self._tab_ids:
            return
        page_url = page.url  # จำ URL ตอนยิง request ไว้ก่อน เผื่อแท็บ navigate ไปหน้าอื่นระหว่างรอ
        if is_watchable(page_url, self._origins):
            self._started[request] = asyncio.ensure_future(self._start(request, page, page_url, now_ms()))

    async def _start(self, request: Request, page: Page, page_url: str, ts: float) -> str:
        """ส่ง RequestStarted แล้วคืน request_key"""
        headers = await all_headers(request)
        self._next_request += 1
        key = f"req-{self._next_request}"
        self._sink(
            RequestStarted(
                request_key=key,
                tab_id=self._tab_ids.get(page, "tab-?"),
                page_url=page_url,
                ts=ts,
                method=request.method,
                url=request.url,
                resource_type=cast(Literal["fetch", "xhr"], request.resource_type),
                headers=headers,
                post_data=self._post_data(request),
            )
        )
        return key

    async def _on_finished(self, request: Request) -> None:
        key = await self._take_key(request)
        if key is None:
            return
        ts = now_ms()
        try:
            response = await request.response()
        except PlaywrightError:
            response = None  # Chrome หลุดระหว่างอ่านคำตอบ
        if response is None:
            self._sink(RequestFailed(request_key=key, ts=ts, failure="อ่านคำตอบจาก Chrome ไม่ได้"))
            return
        self._sink(await self._response_event(key, ts, response))

    async def _on_failed(self, request: Request) -> None:
        key = await self._take_key(request)
        if key is not None:
            self._sink(RequestFailed(request_key=key, ts=now_ms(), failure=request.failure or "ล้มเหลว"))

    async def _take_key(self, request: Request) -> str | None:
        """รอให้ RequestStarted ของ request นี้ถูกส่งไปก่อน เพื่อให้ลำดับ event ถูกต้องเสมอ"""
        task = self._started.pop(request, None)
        if task is None:
            return None
        try:
            return await task
        except asyncio.CancelledError:  # ถูกทิ้งเพราะเชื่อม Chrome ใหม่
            return None

    @staticmethod
    async def _response_event(key: str, ts: float, response: Response) -> ResponseReceived:
        headers = await all_headers(response)
        body: str | None = None
        truncated = 0
        error: str | None = None
        if response.status in REDIRECT_STATUSES:
            error = "เป็นการ redirect จึงไม่มี body ให้อ่าน"
        elif response.status == 304:
            error = "304 Not Modified: เบราว์เซอร์ใช้ข้อมูลเดิมใน cache จึงไม่มี body ใหม่"
        else:
            try:
                body, truncated, error = decode_body(header(headers, "content-type"), await response.body())
            except PlaywrightError as exc:  # body หายไปแล้ว หรือเป็น stream
                error = f"อ่าน body ไม่ได้ ({exc.message.splitlines()[0][:80]})"
        return ResponseReceived(
            request_key=key,
            ts=ts,
            status=response.status,
            status_text=response.status_text,
            headers=headers,
            body=body,
            body_truncated_bytes=truncated,
            body_error=error,
        )

    @staticmethod
    def _page_of(request: Request) -> Page | None:
        try:
            return request.frame.page
        except PlaywrightError:  # request จาก service worker ไม่มี frame
            return None

    @staticmethod
    def _post_data(request: Request) -> str | None:
        try:
            return request.post_data
        except (PlaywrightError, UnicodeDecodeError):  # body เป็น binary ที่ decode เป็นข้อความไม่ได้
            return None
