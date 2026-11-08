"""PostDataReader: ขอ body ของ request ที่ Chrome ไม่ได้แนบมาให้ (เช่น FormData ที่มี Blob/File)

Chrome ไม่ใส่ body ที่มีไฟล์ไว้ใน event `Network.requestWillBeSent` แต่บอก `hasPostData`
แล้วให้ขอทีหลังด้วย `Network.getRequestPostData` ซึ่งเป็นคำสั่งอ่านอย่างเดียว ไม่ส่งอะไรไปที่เว็บไซต์
"""

import asyncio
import base64
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Any, Protocol

MAX_REMEMBERED = 200  # request ที่รอให้ขอ body แต่ไม่มีใครขอ (เช่น ฟอร์มที่ไม่ใช่ fetch/xhr) ทิ้งตัวเก่าไป
DEFAULT_WAIT_SECONDS = 1.0

RequestKey = tuple[str, str]  # (method, url): Playwright ไม่บอก requestId ของ CDP จึงจับคู่ด้วยค่านี้


class CdpSession(Protocol):
    """ส่วนที่ใช้ของ CDP session (Playwright CDPSession ก็มีรูปแบบนี้)"""

    def on(self, event: str, f: Callable[[dict[str, Any]], None]) -> None: ...

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


class PostDataReader:
    """จำ requestId ของ request ที่ไม่มี body ติดมา แล้วขอ body จาก Chrome เมื่อมีคนต้องการ

    สอนแนวคิด: protocol (structural typing) — รับอะไรก็ได้ที่มี `on` กับ `send`
    test จึงใช้ session ปลอมแทน Chrome จริงได้ และ producer/consumer ที่รอกันด้วย Future:
    event ของ CDP กับ event ของ Playwright มาถึงก่อนหลังกันได้ทั้งสองแบบ
    """

    def __init__(self, session: CdpSession, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> None:
        self._session = session
        self._wait_seconds = wait_seconds
        self._ready: OrderedDict[RequestKey, deque[str]] = OrderedDict()
        self._waiting: dict[RequestKey, deque[asyncio.Future[str]]] = {}

    async def start(self) -> None:
        """เริ่มฟัง event ของ network ใน session นี้ (request ที่ส่งก่อนหน้านี้จะขอ body ไม่ได้)"""
        self._session.on("Network.requestWillBeSent", self._on_request)
        await self._session.send("Network.enable")

    async def read(self, method: str, url: str) -> bytes | None:
        """body ของ request นี้ หรือ None ถ้า Chrome ไม่ได้บอกว่ามี body ค้างอยู่ หรือให้ body ไม่ได้"""
        request_id = await self._request_id((method, url))
        if request_id is None:
            return None
        try:
            reply = await self._session.send("Network.getRequestPostData", {"requestId": request_id})
        except Exception:  # Chrome ทิ้ง body ไปแล้ว หรือแท็บปิด/หลุดระหว่างขอ
            return None
        data = reply.get("postData")
        if not isinstance(data, str):
            return None
        return base64.b64decode(data) if reply.get("base64Encoded") else data.encode("utf-8")

    def remembered(self) -> int:
        """จำนวน request ที่จำไว้รอให้ขอ body (มีเพดานเพื่อไม่ให้หน่วยความจำโตไม่หยุด)"""
        return sum(len(ids) for ids in self._ready.values())

    def _on_request(self, event: dict[str, Any]) -> None:
        request = event.get("request", {})
        if not request.get("hasPostData") or "postData" in request:
            return  # ไม่มี body หรือ Chrome แนบมาให้แล้ว
        key: RequestKey = (str(request.get("method")), str(request.get("url")))
        waiters = self._waiting.get(key)
        while waiters:
            waiter = waiters.popleft()
            if not waiter.done():
                waiter.set_result(str(event.get("requestId")))
                return
        self._ready.setdefault(key, deque()).append(str(event.get("requestId")))
        self._ready.move_to_end(key)
        while self.remembered() > MAX_REMEMBERED:
            oldest = next(iter(self._ready))
            self._ready[oldest].popleft()
            if not self._ready[oldest]:
                del self._ready[oldest]

    async def _request_id(self, key: RequestKey) -> str | None:
        ids = self._ready.get(key)
        if ids:
            request_id = ids.popleft()
            if not ids:
                del self._ready[key]
            return request_id
        waiter: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._waiting.setdefault(key, deque()).append(waiter)
        try:
            return await asyncio.wait_for(waiter, self._wait_seconds)
        except TimeoutError:
            return None
        finally:
            waiters = self._waiting.get(key)
            if waiters is not None:
                if waiter in waiters:
                    waiters.remove(waiter)
                if not waiters:
                    del self._waiting[key]
