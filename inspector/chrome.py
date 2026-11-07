"""ChromeConnector: เชื่อม Chrome ผ่าน CDP และเชื่อมใหม่เองเมื่อหลุด

สอนแนวคิด: encapsulation — ซ่อนรายละเอียดของ Playwright ไว้ข้างใน
ส่วนอื่นของโปรแกรมรู้แค่ว่า "เชื่อมแล้ว / หลุดแล้ว" และ "นี่คือ context ของ Chrome"
"""

import asyncio
import platform
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

ContextHandler = Callable[[BrowserContext], Awaitable[None]]
StatusHandler = Callable[[bool], None]


def chrome_launch_command(cdp_url: str, system: str | None = None) -> str:
    """คำสั่งเปิด Chrome โหมด debug ตาม OS (ใช้โปรไฟล์แยก เพราะ Chrome 136+ บังคับ)"""
    port = urlsplit(cdp_url).port or 9222
    flags = f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1 --no-first-run"
    system = system or platform.system()
    if system == "Windows":
        return (
            r'"C:\Program Files\Google\Chrome\Application\chrome.exe" '
            rf'{flags} --user-data-dir="%LOCALAPPDATA%\TrafficInspectorProfile" https://www.advice.co.th'
        )
    if system == "Darwin":
        return (
            '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" '
            f'{flags} --user-data-dir="$HOME/.traffic-inspector-profile" https://www.advice.co.th &'
        )
    return f'google-chrome {flags} --user-data-dir="$HOME/.traffic-inspector-profile" https://www.advice.co.th &'


class ChromeConnector:
    """วนเชื่อม Chrome ทุก `retry_s` วินาที จนกว่าจะถูกยกเลิก"""

    def __init__(
        self,
        cdp_url: str,
        on_context: ContextHandler,
        on_status: StatusHandler,
        retry_s: float = 2.0,
    ) -> None:
        self._cdp_url = cdp_url
        self._on_context = on_context
        self._on_status = on_status
        self._retry_s = retry_s

    async def run(self) -> None:
        async with async_playwright() as playwright:
            while True:
                browser = await self._try_connect(playwright)
                if browser is not None:
                    await self._serve(browser)
                await asyncio.sleep(self._retry_s)

    async def _try_connect(self, playwright: Playwright) -> Browser | None:
        try:
            return await playwright.chromium.connect_over_cdp(self._cdp_url, timeout=self._retry_s * 1000)
        except Exception:  # Chrome ยังไม่เปิด หรือพอร์ตผิด: ลองใหม่รอบหน้า
            return None

    async def _serve(self, browser: Browser) -> None:
        """ใช้งาน browser จนกว่าจะหลุด"""
        disconnected = asyncio.Event()
        browser.on("disconnected", lambda _: disconnected.set())
        try:
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            self._on_status(True)
            await self._on_context(context)
            await disconnected.wait()
        except Exception:
            pass  # หลุดระหว่างตั้งค่า: ถือว่าหลุด แล้วลองใหม่
        finally:
            self._on_status(False)
