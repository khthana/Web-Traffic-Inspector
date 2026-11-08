"""เครื่องมือสำหรับ integration test ที่ใช้ Chrome จริง (`pytest -m chrome`)

มี Chrome แบบ headless บนโปรไฟล์ชั่วคราว, เว็บจำลองด้วย FastAPI และ Inspector ทั้งตัวที่ไม่มีหน้าเว็บ
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
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from playwright.async_api import Browser, async_playwright

import uvicorn
from pipeline_factory import new_pipeline

from inspector.broadcaster import Broadcaster
from inspector.capture import TrafficCapture
from inspector.chrome import ChromeConnector, PlaywrightFactory
from inspector.store import EventStore

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]
INSPECTOR_ORIGIN = "http://127.0.0.1:9"  # origin สมมติของหน้า Inspector ใน test


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def find_chrome() -> str | None:
    return next((c for c in CHROME_CANDIDATES if c and Path(c).exists()), None)


def in_chrome(scenario: Callable[[Browser], Awaitable[None]]) -> None:
    """เปิด Chrome headless ให้ scenario ใช้แล้วปิดให้เสมอ (ไม่พบ Chrome ในเครื่อง → skip)"""
    executable = find_chrome()
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")

    async def run() -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=executable, headless=True)
            try:
                await scenario(browser)
            finally:
                await browser.close()

    asyncio.run(run())


@contextmanager
def serve(app: FastAPI) -> Iterator[str]:
    """รันเว็บจำลองใน thread แยก คืน origin เช่น http://127.0.0.1:54321"""
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("เว็บจำลองไม่ start ภายใน 10 วินาที")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
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

    def start(self, url: str = "about:blank") -> None:
        self.process = subprocess.Popen(
            [
                self.executable, "--headless=new", f"--remote-debugging-port={self.port}",
                "--remote-debugging-address=127.0.0.1", f"--user-data-dir={self.profile}",
                "--no-first-run", "--no-default-browser-check", url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.wait(timeout=10)
            self.process = None

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.profile, ignore_errors=True)

    def open_tab(self, url: str) -> None:
        request = urllib.request.Request(f"{self.cdp_url}/json/new?{url}", method="PUT")
        urllib.request.urlopen(request, timeout=5).read()


class LiveInspector:
    """Inspector ทั้งตัว (ไม่มี FastAPI) ที่ต่อกับ Chrome จริง"""

    def __init__(
        self,
        cdp_url: str,
        inspector_origins: tuple[str, ...] = (INSPECTOR_ORIGIN,),
        playwright_factory: PlaywrightFactory = async_playwright,
    ) -> None:
        self.pipeline = new_pipeline(EventStore(), Broadcaster())
        capture = TrafficCapture(sink=self.pipeline.handle, inspector_origins=inspector_origins)
        self.connector = ChromeConnector(
            cdp_url,
            on_context=capture.attach,
            on_status=self.pipeline.set_chrome_connected,
            retry_s=0.5,
            playwright_factory=playwright_factory,
        )

    def exchanges(self) -> list[dict[str, Any]]:
        return list(self.pipeline.snapshot()["exchanges"])

    def interactions(self) -> list[dict[str, Any]]:
        return list(self.pipeline.snapshot()["interactions"])

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
