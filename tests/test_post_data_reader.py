"""PostDataReader กับ CDP session ปลอม: ขอ body ที่ Chrome ไม่ได้แนบมากับ request (เช่นฟอร์มที่มีไฟล์)"""

import asyncio
import base64
from collections.abc import Callable
from typing import Any

from inspector.post_data import PostDataReader

FORM = b'--b\r\nContent-Disposition: form-data; name="avatar"; filename="a.png"\r\n\r\n\x89P\xff\xfe\r\n--b--\r\n'


class FakeSession:
    """CDP session ปลอม: จำคำสั่งที่ถูกส่ง และให้ test ยิง event เองได้"""

    def __init__(self, bodies: dict[str, dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.sent: list[tuple[str, dict[str, Any] | None]] = []
        self._handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._bodies = bodies or {}
        self._fail = fail

    def on(self, event: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.sent.append((method, params))
        if method == "Network.getRequestPostData":
            if self._fail:
                raise RuntimeError("No post data available for the request")
            assert params is not None
            return self._bodies[params["requestId"]]
        return {}

    def emit(self, request_id: str, method: str, url: str, has_post_data: bool = True, post_data: str | None = None) -> None:
        request: dict[str, Any] = {"method": method, "url": url, "hasPostData": has_post_data}
        if post_data is not None:
            request["postData"] = post_data
        for handler in self._handlers.get("Network.requestWillBeSent", []):
            handler({"requestId": request_id, "request": request})


def encoded(raw: bytes) -> dict[str, Any]:
    return {"postData": base64.b64encode(raw).decode(), "base64Encoded": True}


async def started(session: FakeSession, wait_seconds: float = 1.0) -> PostDataReader:
    reader = PostDataReader(session, wait_seconds=wait_seconds)
    await reader.start()
    return reader


def test_start_turns_on_network_events() -> None:
    session = FakeSession()
    asyncio.run(started(session))
    assert session.sent == [("Network.enable", None)]


def test_reads_body_chrome_left_out_of_the_request() -> None:
    session = FakeSession({"7.1": encoded(FORM)})

    async def scenario() -> bytes | None:
        reader = await started(session)
        session.emit("7.1", "POST", "https://shop.example/api/upload")
        return await reader.read("POST", "https://shop.example/api/upload")

    assert asyncio.run(scenario()) == FORM
    assert session.sent[-1] == ("Network.getRequestPostData", {"requestId": "7.1"})


def test_waits_for_the_cdp_event_that_arrives_after_playwright_event() -> None:
    session = FakeSession({"7.1": encoded(FORM)})

    async def scenario() -> bytes | None:
        reader = await started(session)
        reading = asyncio.ensure_future(reader.read("POST", "https://shop.example/api/upload"))
        await asyncio.sleep(0.05)
        session.emit("7.1", "POST", "https://shop.example/api/upload")
        return await reading

    assert asyncio.run(scenario()) == FORM


def test_plain_text_post_data_is_returned_as_utf8() -> None:
    session = FakeSession({"7.1": {"postData": '{"name": "สมชาย"}', "base64Encoded": False}})

    async def scenario() -> bytes | None:
        reader = await started(session)
        session.emit("7.1", "POST", "https://shop.example/api/json")
        return await reader.read("POST", "https://shop.example/api/json")

    assert asyncio.run(scenario()) == '{"name": "สมชาย"}'.encode()


def test_requests_to_the_same_url_are_matched_in_order() -> None:
    session = FakeSession({"7.1": encoded(b"first"), "7.2": encoded(b"second")})

    async def scenario() -> list[bytes | None]:
        reader = await started(session)
        session.emit("7.1", "POST", "https://shop.example/api/upload")
        session.emit("7.2", "POST", "https://shop.example/api/upload")
        return [await reader.read("POST", "https://shop.example/api/upload") for _ in range(2)]

    assert asyncio.run(scenario()) == [b"first", b"second"]


def test_requests_that_already_carry_their_body_are_not_fetched_again() -> None:
    session = FakeSession()

    async def scenario() -> bytes | None:
        reader = await started(session, wait_seconds=0.05)
        session.emit("7.1", "POST", "https://shop.example/api/json", post_data='{"a": 1}')
        session.emit("7.2", "GET", "https://shop.example/api/json", has_post_data=False)
        return await reader.read("POST", "https://shop.example/api/json")

    assert asyncio.run(scenario()) is None
    assert [method for method, _ in session.sent] == ["Network.enable"]


def test_gives_up_when_no_matching_request_arrives() -> None:
    async def scenario() -> bytes | None:
        reader = await started(FakeSession(), wait_seconds=0.05)
        return await reader.read("POST", "https://shop.example/api/upload")

    assert asyncio.run(scenario()) is None


def test_gives_up_when_chrome_refuses_to_give_the_body() -> None:
    session = FakeSession(fail=True)

    async def scenario() -> bytes | None:
        reader = await started(session)
        session.emit("7.1", "POST", "https://shop.example/api/upload")
        return await reader.read("POST", "https://shop.example/api/upload")

    assert asyncio.run(scenario()) is None


def test_forgets_old_unread_requests_so_memory_stays_bounded() -> None:
    session = FakeSession()

    async def scenario() -> int:
        reader = await started(session)
        for number in range(1000):
            session.emit(f"7.{number}", "POST", f"https://shop.example/api/{number}")
        return reader.remembered()

    assert asyncio.run(scenario()) <= 200
