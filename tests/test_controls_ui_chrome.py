"""ปุ่มและคีย์ลัดควบคุมการเก็บใน Chrome จริง: หยุด/เริ่มต่อ, ล้าง, Space, C และ ↑/↓ เลือก Exchange (`pytest -m chrome`)"""

import asyncio
from collections.abc import Iterator

import pytest
from chrome_support import find_chrome, serve
from pipeline_factory import new_pipeline
from playwright.async_api import Page, async_playwright

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import ClickCaptured, RequestStarted
from inspector.models import ElementInfo
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

T0 = 1_700_000_000_000.0
PAGE = "https://shop.example/"
PAUSED_BANNER = "หยุดเก็บชั่วคราว — กด Space เพื่อเริ่มต่อ"


def request(key: str, method: str, url: str, ts: float) -> RequestStarted:
    return RequestStarted(request_key=key, tab_id="tab-1", page_url=PAGE, ts=ts, method=method, url=url, resource_type="fetch")


@pytest.fixture
def inspector() -> Iterator[str]:
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = new_pipeline(store, broadcaster)
    element = ElementInfo(tag="button", text="ใส่ตะกร้า", selector="button.buy")
    for event in (
        ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=T0, element=element),
        request("a", "POST", "https://shop.example/api/cart", T0 + 10),
        request("b", "GET", "https://shop.example/api/list", T0 + 20),
        request("c", "POST", "https://www.clarity.ms/collect", T0 + 30),  # ซ่อนอยู่: ↑/↓ ข้ามไป
    ):
        pipeline.handle(event)
    app = create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)

    @app.post("/test/chrome/connected")
    async def chrome_connected() -> None:
        """route สำหรับ test เท่านั้น: ทำเหมือน Chrome เพิ่งเชื่อมได้ (บน event loop ของ server)"""
        pipeline.set_chrome_connected(True)

    with serve(app) as origin:
        yield origin


async def key(page: Page, selector: str, key: str, code: str, repeat: bool = False) -> None:
    """ส่ง keydown ที่กำหนด key/code เองได้ (เช่นแป้นภาษาไทย: ปุ่ม C ได้ key เป็น "แ")"""
    await page.eval_on_selector(
        selector,
        "(el, [key, code, repeat]) => el.dispatchEvent(new KeyboardEvent('keydown', {key, code, repeat, bubbles: true}))",
        [key, code, repeat],
    )


async def selected(page: Page) -> str:
    return await page.locator(".exchange[aria-selected=true] .path").text_content() or ""


def test_buttons_and_shortcuts_control_capture(inspector: str) -> None:
    executable = find_chrome()
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")

    async def scenario() -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            await page.goto(inspector + "/")
            await page.wait_for_selector(".exchange")

            # ↑/↓ เลือก Exchange ที่มองเห็นตามลำดับบนจอ
            await page.keyboard.press("ArrowDown")
            assert "/api/cart" in await selected(page)
            await page.keyboard.press("ArrowDown")
            assert "/api/list" in await selected(page)
            await page.keyboard.press("ArrowDown")  # ตัวสุดท้ายที่มองเห็นแล้ว (tracking ซ่อนอยู่)
            assert "/api/list" in await selected(page)
            await page.keyboard.press("ArrowUp")
            assert "/api/cart" in await selected(page)
            assert "/api/cart" in (await page.text_content(".detail-url") or "")
            await key(page, "#detail", "ArrowDown", "ArrowDown")  # ลูกศรในแผง Detail ใช้เลื่อนอ่าน ไม่เปลี่ยนแถว
            assert "/api/cart" in await selected(page)

            # ปุ่มหยุด: แถบเหลืองและสถานะบอกว่าหยุดอยู่
            assert not await page.is_visible("#paused-banner")
            await page.click("#pause-toggle")
            await page.wait_for_selector("#paused-banner", state="visible")
            assert (await page.text_content("#paused-banner") or "").strip() == PAUSED_BANNER
            assert await page.text_content("#pause-toggle") == "เริ่มต่อ"
            assert await page.text_content("#chrome-status .label") == "ไม่พบ Chrome"  # Chrome หลุดสำคัญกว่า
            await page.request.post(inspector + "/test/chrome/connected")
            await page.wait_for_function("document.querySelector('#chrome-status .label').textContent === 'หยุดชั่วคราว'")

            # Space บน checkbox เป็นของ checkbox ไม่ใช่คีย์ลัด
            await page.focus("#follow-clicks")
            await page.keyboard.press("Space")
            assert not await page.is_checked("#follow-clicks")
            assert await page.is_visible("#paused-banner")

            # Space = เริ่มต่อ
            await page.locator(".exchange").first.focus()
            await page.keyboard.press("Space")
            await page.wait_for_selector("#paused-banner", state="hidden")
            assert await page.text_content("#pause-toggle") == "หยุด"
            await key(page, "body", " ", "Space", repeat=True)  # กด Space ค้าง: ไม่สลับไปมา
            await page.wait_for_timeout(300)
            assert not await page.is_visible("#paused-banner")

            # C = ล้าง แม้เปิดแป้นภาษาไทยอยู่: Timeline, Detail และ Hidden count ว่าง
            await key(page, "body", "แ", "KeyC")
            await page.wait_for_selector(".exchange", state="detached")
            assert await page.is_visible("#timeline-empty")
            assert await page.text_content("#hidden-toggle") == "ซ่อน 0 รายการ"
            assert await page.locator(".detail-head").count() == 0

            # ปุ่มล้างใช้ได้เหมือนกัน (ล้างซ้ำตอนว่างก็ไม่พัง)
            await page.click("#clear")
            assert await page.is_visible("#timeline-empty")

            # โฟกัสค้างที่ปุ่ม: Space กดปุ่มนั้น (หยุด) ส่วน C ยังเป็นคีย์ลัด
            await page.focus("#pause-toggle")
            await page.keyboard.press("Space")
            await page.wait_for_selector("#paused-banner", state="visible")
            await page.focus("#hidden-toggle")
            await page.keyboard.press("Space")  # กดปุ่ม "ซ่อน N รายการ" ไม่ใช่เริ่มต่อ
            assert await page.is_visible("#paused-banner")
            assert await page.get_attribute("#hidden-toggle", "aria-pressed") == "true"
            await browser.close()

    asyncio.run(scenario())
