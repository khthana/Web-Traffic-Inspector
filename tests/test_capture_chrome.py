"""Integration test กับ Chrome จริง (รันด้วย `pytest -m chrome`)

เปิด Chrome แบบ headless + หน้า fixture ที่ยิง fetch/XHR หลายแบบ
แล้วตรวจผลผ่านข้อมูลเดียวกับที่ REST/WebSocket ส่งให้ UI
"""

import asyncio
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from inspector.broadcaster import Broadcaster
from inspector.capture import TrafficCapture
from inspector.chrome import ChromeConnector
from inspector.correlator import Correlator
from inspector.pipeline import InspectorPipeline
from inspector.redactor import Redactor
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]

FIXTURE_PAGE = """<!doctype html>
<html><body>
<img src="/img.png">
<script>
  fetch('/api/json').then(r => r.json());
  fetch('/api/form', {method: 'POST', headers: {'content-type': 'application/x-www-form-urlencoded'},
                      body: 'user=somchai&password=hunter2'});
  fetch('/api/binary');
  fetch('/api/big');
  const xhr = new XMLHttpRequest(); xhr.open('GET', '/api/xhr'); xhr.send();
  fetch('/api/tis620');
  fetch('http://127.0.0.1:1/nothing').catch(() => {});
  fetch('http://127.0.0.1:9/inspector-api').catch(() => {});  // origin ของ Inspector เอง
</script>
</body></html>"""

BIG_TEXT = "ก" * 40_000  # ตัวไทย 3 byte: ตัดที่ 64 KB จะตกกลางตัวอักษร
BIG_BYTES = len(BIG_TEXT.encode("utf-8"))
KEPT_BYTES = (64 * 1024 // 3) * 3
INSPECTOR_ORIGIN = "http://127.0.0.1:9"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def fixture_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def page() -> HTMLResponse:
        return HTMLResponse(FIXTURE_PAGE)

    @app.get("/img.png")
    def image() -> Response:
        return Response(b"\x89PNG\r\n", media_type="image/png")

    @app.get("/api/json")
    def json_api() -> JSONResponse:
        return JSONResponse({"status": "SUCCESS", "data": [1, 2, 3]})

    @app.post("/api/form")
    async def form_api(request: Request) -> JSONResponse:
        await request.body()
        return JSONResponse({"ok": True})

    @app.get("/api/binary")
    def binary_api() -> Response:
        return Response(bytes(range(256)) * 13, media_type="application/x-protobuf")

    @app.get("/api/big")
    def big_api() -> PlainTextResponse:
        return PlainTextResponse(BIG_TEXT)

    @app.get("/api/tis620")
    def tis620_api() -> Response:
        return Response("สวัสดี".encode("cp874"), media_type="text/plain; charset=windows-874")

    @app.get("/api/xhr")
    def xhr_api() -> JSONResponse:
        return JSONResponse({"via": "xhr"})

    return app


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(fixture_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


class ChromeProcess:
    """Chrome แบบ headless ที่เปิดพอร์ต CDP บนโปรไฟล์ชั่วคราว"""

    def __init__(self, executable: str) -> None:
        self.executable = executable
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="wti-chrome-")
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.process = subprocess.Popen(
            [
                self.executable, "--headless=new", f"--remote-debugging-port={self.port}",
                "--remote-debugging-address=127.0.0.1", f"--user-data-dir={self.profile}",
                "--no-first-run", "--no-default-browser-check", "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.wait(timeout=10)
            self.process = None

    def open_tab(self, url: str) -> None:
        request = urllib.request.Request(f"{self.cdp_url}/json/new?{url}", method="PUT")
        urllib.request.urlopen(request, timeout=5).read()


@pytest.fixture
def chrome() -> Iterator[ChromeProcess]:
    executable = next((c for c in CHROME_CANDIDATES if c and Path(c).exists()), None)
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")
    process = ChromeProcess(executable)
    yield process
    process.stop()
    shutil.rmtree(process.profile, ignore_errors=True)


class LiveInspector:
    """Inspector ทั้งตัว (ไม่มี FastAPI) ที่ต่อกับ Chrome จริง"""

    def __init__(self, cdp_url: str, inspector_origins: tuple[str, ...] = (INSPECTOR_ORIGIN,)) -> None:
        self.pipeline = InspectorPipeline(
            store=EventStore(), broadcaster=Broadcaster(), redactor=Redactor(), correlator=Correlator(window_ms=1500)
        )
        capture = TrafficCapture(sink=self.pipeline.handle, inspector_origins=inspector_origins)
        self.connector = ChromeConnector(
            cdp_url, on_context=capture.attach, on_status=self.pipeline.set_chrome_connected, retry_s=0.5
        )

    def exchanges(self) -> list[dict[str, Any]]:
        return list(self.pipeline.snapshot()["exchanges"])

    def status(self) -> dict[str, Any]:
        return dict(self.pipeline.snapshot()["status"])


async def wait_until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("รอนานเกินไป")
        await asyncio.sleep(0.1)


def run_live(cdp_url: str, scenario: Callable[[LiveInspector], Awaitable[None]], **kwargs: Any) -> None:
    async def main() -> None:
        inspector = LiveInspector(cdp_url, **kwargs)
        task = asyncio.create_task(inspector.connector.run())
        try:
            await scenario(inspector)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(main())


def test_fetch_and_xhr_from_a_new_tab_are_captured(chrome: ChromeProcess, site: str) -> None:
    chrome.start()

    async def scenario(inspector: LiveInspector) -> None:
        await wait_until(lambda: inspector.status()["chrome"] == "connected")
        chrome.open_tab(site + "/")  # แท็บเปิดใหม่ระหว่างใช้งาน
        await wait_until(lambda: len([e for e in inspector.exchanges() if e["state"] != "pending"]) >= 7)

        by_path = {e["request"]["path"]: e for e in inspector.exchanges()}
        assert set(by_path) == {
            "/api/json", "/api/form", "/api/binary", "/api/big", "/api/xhr", "/api/tis620", "/nothing"
        }  # ไม่มีรูปภาพ และไม่มี request ไปหา Inspector

        assert by_path["/api/json"]["response"]["body_kind"] == "json"
        assert by_path["/api/xhr"]["resource_type"] == "xhr"
        assert by_path["/api/form"]["request"]["body"] == "user=somchai&password=••••"
        assert by_path["/api/binary"]["response"]["body"] is None
        assert by_path["/api/binary"]["response"]["body_error"].startswith("เป็นไฟล์ binary (application/x-protobuf")
        assert by_path["/api/big"]["response"]["body"] == BIG_TEXT[: KEPT_BYTES // 3]
        assert by_path["/api/big"]["response"]["body_truncated_bytes"] == BIG_BYTES - KEPT_BYTES
        assert by_path["/api/tis620"]["response"]["body"] == "สวัสดี"
        assert by_path["/nothing"]["state"] == "failed"
        assert by_path["/nothing"]["failure"]
        assert [t["url"] for t in inspector.status()["tabs"]] == [site + "/"]

    run_live(chrome.cdp_url, scenario)


def test_inspector_own_tab_is_not_watched(chrome: ChromeProcess, site: str) -> None:
    chrome.start()

    async def scenario(inspector: LiveInspector) -> None:
        await wait_until(lambda: inspector.status()["chrome"] == "connected")
        chrome.open_tab(site + "/")
        await asyncio.sleep(2.0)

        assert inspector.exchanges() == []
        assert inspector.status()["tabs"] == []

    run_live(chrome.cdp_url, scenario, inspector_origins=(site + "/",))  # origin เดียวกัน แม้เขียนต่างกัน


def test_reconnects_after_chrome_restarts(chrome: ChromeProcess, site: str) -> None:
    async def scenario(inspector: LiveInspector) -> None:
        await asyncio.sleep(1.0)
        assert inspector.status()["chrome"] == "disconnected"  # เปิด Inspector ก่อน Chrome

        chrome.start()
        await wait_until(lambda: inspector.status()["chrome"] == "connected", timeout=5.0)

        chrome.stop()
        await wait_until(lambda: inspector.status()["chrome"] == "disconnected", timeout=5.0)

        chrome.start()
        await wait_until(lambda: inspector.status()["chrome"] == "connected", timeout=5.0)

    run_live(chrome.cdp_url, scenario)
