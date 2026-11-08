"""ChromeConnector: เชื่อม Chrome ผ่าน CDP และเชื่อมใหม่เองเมื่อหลุด

สอนแนวคิด: encapsulation — ซ่อนรายละเอียดของ Playwright ไว้ข้างใน
ส่วนอื่นของโปรแกรมรู้แค่ว่า "เชื่อมแล้ว / หลุดแล้ว" และ "นี่คือ context ของ Chrome"
"""

import asyncio
import logging
import platform
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

log = logging.getLogger(__name__)

ContextHandler = Callable[[BrowserContext], Awaitable[None]]
StatusHandler = Callable[[bool], None]


DEFAULT_CDP_PORT = 9222
DEBUG_ADDRESS = "127.0.0.1"  # เปิดพอร์ต CDP ให้เฉพาะเครื่องนี้ เครื่องอื่นในแลบสั่ง Chrome ของผู้สอนไม่ได้
START_URL = "https://www.advice.co.th"
PROFILE_NAME_WINDOWS = "TrafficInspectorProfile"  # อยู่ใน %LOCALAPPDATA%
PROFILE_NAME_POSIX = ".traffic-inspector-profile"  # อยู่ใน $HOME


def cdp_port(cdp_url: str) -> int:
    """พอร์ตใน --cdp-url (ไม่ระบุ → 9222)"""
    return urlsplit(cdp_url).port or DEFAULT_CDP_PORT


def debug_flags(port: int, profile: str) -> list[str]:
    """flag ของ Chrome โหมด debug (SPEC 7) ใช้ร่วมกันทั้งคำสั่งที่แสดงบนจอ, --launch-chrome และสคริปต์ใน scripts/"""
    return [
        f"--remote-debugging-port={port}",
        f"--remote-debugging-address={DEBUG_ADDRESS}",
        f"--user-data-dir={profile}",
        "--no-first-run",
    ]


def chrome_launch_command(cdp_url: str, system: str | None = None) -> str:
    """คำสั่งเปิด Chrome โหมด debug ตาม OS ให้ผู้สอนคัดลอกไปวางใน terminal (ใช้โปรไฟล์แยก เพราะ Chrome 136+ บังคับ)

    Windows ใช้รูปแบบของ PowerShell ซึ่งเป็น terminal เริ่มต้นของ Windows 11
    """
    port = cdp_port(cdp_url)
    system = system or platform.system()
    if system == "Windows":
        executable = r'& "C:\Program Files\Google\Chrome\Application\chrome.exe"'
        profile, background = rf'"$env:LOCALAPPDATA\{PROFILE_NAME_WINDOWS}"', ""
    elif system == "Darwin":
        executable = '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"'
        profile, background = f'"$HOME/{PROFILE_NAME_POSIX}"', " &"
    else:
        executable = "google-chrome"
        profile, background = f'"$HOME/{PROFILE_NAME_POSIX}"', " &"
    return " ".join([executable, *debug_flags(port, profile), START_URL]) + background


class ChromeConnector:
    """วนเชื่อม Chrome ทุก `retry_s` วินาที จนกว่าจะถูกยกเลิก

    สอนแนวคิด: callback — แจ้งสถานะผ่าน `on_status` และส่ง context ให้ `on_context` โดยไม่ต้องรู้ว่าใครใช้
    """

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
            if not browser.contexts:
                log.warning("Chrome ไม่มีหน้าต่างที่ใช้โปรไฟล์ปกติ จะลองใหม่")
                return
            self._on_status(True)
            await self._on_context(browser.contexts[0])
            await disconnected.wait()
        except Exception:
            log.exception("ตั้งค่าการดัก traffic ไม่สำเร็จ จะลองเชื่อม Chrome ใหม่")
        finally:
            self._on_status(False)
            # ตัดการเชื่อมรอบนี้ให้ขาด (ไม่ได้ปิด Chrome) กันไม่ให้ listener ชุดเก่าดัก request ซ้ำ
            try:
                await browser.close()
            except Exception:
                pass  # หลุดไปแล้ว
