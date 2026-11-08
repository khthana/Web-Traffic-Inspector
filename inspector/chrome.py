"""ChromeConnector: เชื่อม Chrome ผ่าน CDP และเชื่อมใหม่เองเมื่อหลุด

สอนแนวคิด: encapsulation — ซ่อนรายละเอียดของ Playwright ไว้ข้างใน
ส่วนอื่นของโปรแกรมรู้แค่ว่า "เชื่อมแล้ว / หลุดแล้ว" และ "นี่คือ context ของ Chrome"
"""

import asyncio
import logging
import platform
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

log = logging.getLogger(__name__)

ContextHandler = Callable[[BrowserContext], Awaitable[None]]
StatusHandler = Callable[[bool], None]
PlaywrightFactory = Callable[[], AbstractAsyncContextManager[Playwright]]


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
        flags = debug_flags(port, rf'"$env:LOCALAPPDATA\{PROFILE_NAME_WINDOWS}"')
        return " ".join([executable, *flags, START_URL])
    if system == "Darwin":
        executable = '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"'
    else:
        executable = "google-chrome"
    # nohup ... &: ปิดหน้าต่าง Terminal แล้ว Chrome ไม่ปิดตาม (แบบเดียวกับ scripts/start_chrome.command)
    flags = debug_flags(port, f'"$HOME/{PROFILE_NAME_POSIX}"')
    return " ".join(["nohup", executable, *flags, START_URL, ">/dev/null", "2>&1", "&"])


def watch_for_driver_crash(playwright: Playwright) -> asyncio.Event:
    """Event ที่ถูก set เมื่อ driver ของ Playwright ตายเอง (ไม่ใช่เพราะเราสั่งหยุด)

    Playwright 1.64 มีบั๊ก: ถ้า Chrome ส่งข้อความของ context ที่ถูกทิ้งไปแล้ว (จังหวะเชื่อม Chrome ใหม่)
    ตัวกระจายข้อความจะตายด้วย KeyError แต่ไม่บอกคำสั่งที่รออยู่ ทุกคำสั่งจึงรอคำตอบไปตลอด
    ตรงนี้ทำให้คำสั่งที่รออยู่ล้มทันทีแทน และบอก ChromeConnector ให้เริ่ม Playwright ใหม่
    (แตะส่วนภายในของ Playwright: ถ้ารุ่นอื่นไม่มีส่วนนี้ ก็แค่ไม่มีตัวเฝ้า)
    """
    crashed = asyncio.Event()
    transport = getattr(getattr(getattr(playwright, "_impl_obj", None), "_connection", None), "_transport", None)
    stopped = getattr(transport, "_stopped_future", None)
    errors = getattr(transport, "on_error_future", None)
    if not isinstance(stopped, asyncio.Future) or not isinstance(errors, asyncio.Future):
        return crashed

    def on_stopped(_: asyncio.Future[None]) -> None:
        if getattr(transport, "_stopped", False):
            return  # เราสั่งหยุดเอง (ออกจาก async with)
        crashed.set()
        if not errors.done():
            errors.set_exception(PlaywrightError("Playwright driver หยุดทำงาน จะเริ่มใหม่"))
            errors.exception()  # ทำเครื่องหมายว่ารับรู้แล้ว ไม่ให้ asyncio เตือนเมื่อไม่มีใครรอ

    stopped.add_done_callback(on_stopped)
    return crashed


async def first_of(*events: asyncio.Event) -> None:
    """รอจนกว่า event ใด event หนึ่งจะถูก set"""
    waiters = [asyncio.ensure_future(event.wait()) for event in events]
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()


class ChromeConnector:
    """วนเชื่อม Chrome ทุก `retry_s` วินาที จนกว่าจะถูกยกเลิก

    สอนแนวคิด: callback — แจ้งสถานะผ่าน `on_status` และส่ง context ให้ `on_context` โดยไม่ต้องรู้ว่าใครใช้
    และ fault isolation — เริ่ม Playwright ใหม่ทุกครั้งที่เชื่อม Chrome รอบใหม่ ตัวที่พังจึงไม่ลากรอบถัดไปพังตาม
    """

    def __init__(
        self,
        cdp_url: str,
        on_context: ContextHandler,
        on_status: StatusHandler,
        retry_s: float = 2.0,
        playwright_factory: PlaywrightFactory = async_playwright,
    ) -> None:
        self._cdp_url = cdp_url
        self._on_context = on_context
        self._on_status = on_status
        self._retry_s = retry_s
        self._playwright_factory = playwright_factory

    async def run(self) -> None:
        while True:
            async with self._playwright_factory() as playwright:
                await self._connect_and_serve(playwright, watch_for_driver_crash(playwright))
            await asyncio.sleep(self._retry_s)

    async def _connect_and_serve(self, playwright: Playwright, crashed: asyncio.Event) -> None:
        """ลองเชื่อม Chrome จนได้ แล้วใช้งานจนหลุด (จบเร็วถ้า driver ของ Playwright ตาย)"""
        while not crashed.is_set():
            browser = await self._try_connect(playwright)
            if browser is not None:
                await self._serve(browser, crashed)
                return
            await asyncio.sleep(self._retry_s)

    async def _try_connect(self, playwright: Playwright) -> Browser | None:
        try:
            return await playwright.chromium.connect_over_cdp(self._cdp_url, timeout=self._retry_s * 1000)
        except Exception:  # Chrome ยังไม่เปิด หรือพอร์ตผิด: ลองใหม่รอบหน้า
            return None

    async def _serve(self, browser: Browser, crashed: asyncio.Event) -> None:
        """ใช้งาน browser จนกว่าจะหลุด หรือ driver ของ Playwright ตาย"""
        disconnected = asyncio.Event()
        browser.on("disconnected", lambda _: disconnected.set())
        try:
            if not browser.contexts:
                log.warning("Chrome ไม่มีหน้าต่างที่ใช้โปรไฟล์ปกติ จะลองใหม่")
                return
            self._on_status(True)
            await self._on_context(browser.contexts[0])
            await first_of(disconnected, crashed)
            if crashed.is_set():
                log.warning("Playwright หยุดทำงานกลางคัน จะเชื่อม Chrome ใหม่")
        except Exception:
            log.exception("ตั้งค่าการดัก traffic ไม่สำเร็จ จะลองเชื่อม Chrome ใหม่")
        finally:
            self._on_status(False)
            # ตัดการเชื่อมรอบนี้ให้ขาด (ไม่ได้ปิด Chrome) กันไม่ให้ listener ชุดเก่าดัก request ซ้ำ
            try:
                await browser.close()
            except Exception:
                pass  # หลุดไปแล้ว
