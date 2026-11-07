"""TrafficCapture: แปลง event ของ Playwright เป็น Capture event

สอนแนวคิด: adapter — แปลงภาษาของ Playwright (Request, Response, Page)
ให้เป็นข้อมูลล้วนที่ส่วนอื่นของโปรแกรมเข้าใจ ถ้าวันหนึ่งเปลี่ยนไปใช้เครื่องมืออื่น ก็แก้แค่ไฟล์นี้
"""

import asyncio
import time
from collections.abc import Callable
from typing import Literal, cast

from playwright.async_api import BrowserContext, Page, Request, Response

from inspector.capture_events import (
    CaptureEvent,
    NavigationOccurred,
    RequestFailed,
    RequestStarted,
    ResponseReceived,
    TabChanged,
)
from inspector.http_parts import header

MAX_BODY_BYTES = 64 * 1024
CAPTURED_TYPES = ("fetch", "xhr")
IGNORED_SCHEMES = ("about:", "chrome:", "chrome-extension:", "devtools:", "chrome-untrusted:", "edge:")
TEXT_HINTS = ("json", "text/", "xml", "javascript", "x-www-form-urlencoded", "graphql")

EventSink = Callable[[CaptureEvent], None]


def now_ms() -> float:
    return time.time() * 1000


def is_watchable(url: str, inspector_origins: tuple[str, ...]) -> bool:
    """แท็บนี้เป็น Watched tab ได้ไหม (ไม่ดักหน้า Inspector เอง และหน้าภายในของ Chrome)"""
    if url.startswith(IGNORED_SCHEMES):
        return False
    return not any(url == origin or url.startswith(origin + "/") for origin in inspector_origins)


def describe_size(size: int) -> str:
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"


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
    truncated = max(0, len(raw) - MAX_BODY_BYTES)
    return raw[:MAX_BODY_BYTES].decode("utf-8", errors="replace"), truncated, None


class TrafficCapture:
    """ฟัง request/response ของทุก Watched tab ใน context แล้วส่ง Capture event ให้ `sink`"""

    def __init__(self, sink: EventSink, inspector_origins: tuple[str, ...]) -> None:
        self._sink = sink
        self._origins = inspector_origins
        self._tab_ids: dict[Page, str] = {}
        self._started: dict[Request, asyncio.Task[str | None]] = {}
        self._next_tab = 0
        self._next_request = 0

    async def attach(self, context: BrowserContext) -> None:
        """เริ่มฟัง context นี้ รวมถึงแท็บที่จะเปิดใหม่ภายหลัง"""
        self._tab_ids.clear()
        self._started.clear()
        context.on("page", self._watch_page)
        context.on("request", self._on_request)
        context.on("requestfinished", self._on_finished)
        context.on("requestfailed", self._on_failed)
        for page in context.pages:
            self._watch_page(page)

    def _watch_page(self, page: Page) -> None:
        self._next_tab += 1
        tab_id = f"tab-{self._next_tab}"
        self._tab_ids[page] = tab_id
        self._announce_tab(page)
        page.on("framenavigated", lambda frame: self._on_navigated(page) if frame == page.main_frame else None)
        page.on("close", lambda _: self._on_closed(page))

    def _announce_tab(self, page: Page) -> None:
        tab_id = self._tab_ids[page]
        self._sink(TabChanged(tab_id=tab_id, url=page.url, ts=now_ms(), open=is_watchable(page.url, self._origins)))

    def _on_navigated(self, page: Page) -> None:
        if page not in self._tab_ids:
            return
        self._announce_tab(page)
        if is_watchable(page.url, self._origins):
            self._sink(NavigationOccurred(tab_id=self._tab_ids[page], url=page.url, ts=now_ms()))

    def _on_closed(self, page: Page) -> None:
        tab_id = self._tab_ids.pop(page, None)
        if tab_id is not None:
            self._sink(TabChanged(tab_id=tab_id, url=page.url, ts=now_ms(), open=False))

    def _on_request(self, request: Request) -> None:
        if request.resource_type not in CAPTURED_TYPES:
            return
        self._started[request] = asyncio.ensure_future(self._start(request, now_ms()))

    async def _start(self, request: Request, ts: float) -> str | None:
        """ส่ง RequestStarted คืน request_key (หรือ None ถ้าไม่ได้ดักแท็บนี้)"""
        page = self._page_of(request)
        if page is None or page not in self._tab_ids or not is_watchable(page.url, self._origins):
            return None
        try:
            headers = await request.all_headers()
        except Exception:
            headers = request.headers
        self._next_request += 1
        key = f"req-{self._next_request}"
        self._sink(
            RequestStarted(
                request_key=key,
                tab_id=self._tab_ids[page],
                page_url=page.url,
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
        response = await request.response()
        if response is None:
            self._sink(RequestFailed(request_key=key, ts=ts, failure="ไม่มี response"))
            return
        self._sink(await self._response_event(key, ts, response))

    async def _on_failed(self, request: Request) -> None:
        key = await self._take_key(request)
        if key is not None:
            self._sink(RequestFailed(request_key=key, ts=now_ms(), failure=request.failure or "ล้มเหลว"))

    async def _take_key(self, request: Request) -> str | None:
        """รอให้ RequestStarted ของ request นี้ถูกส่งไปก่อน เพื่อให้ลำดับ event ถูกต้องเสมอ"""
        task = self._started.pop(request, None)
        return None if task is None else await task

    @staticmethod
    async def _response_event(key: str, ts: float, response: Response) -> ResponseReceived:
        try:
            headers = await response.all_headers()
        except Exception:
            headers = response.headers
        body: str | None = None
        truncated = 0
        error: str | None = None
        if 300 <= response.status < 400:
            error = "เป็นการ redirect จึงไม่มี body ให้อ่าน"
        else:
            try:
                body, truncated, error = decode_body(header(headers, "content-type"), await response.body())
            except Exception as exc:  # body หายไปแล้ว หรือเป็น stream
                error = f"อ่าน body ไม่ได้ ({type(exc).__name__})"
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
        except Exception:  # request จาก service worker ไม่มี frame
            return None

    @staticmethod
    def _post_data(request: Request) -> str | None:
        try:
            return request.post_data
        except Exception:  # body เป็น binary ที่ decode เป็นข้อความไม่ได้
            return None
