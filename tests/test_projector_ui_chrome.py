"""UI สำหรับจอโปรเจกเตอร์ใน Chrome จริง: ขนาดตัวอักษร, ธีม, แถบเตือนจริยธรรม, จอแคบ, ปุ่ม "มี N รายการใหม่"
และ WebSocket หลุดแล้วเชื่อมใหม่ (`pytest -m chrome`)"""

import time
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from chrome_support import in_chrome, serve
from pipeline_factory import new_pipeline
from playwright.async_api import Browser, Page, WebSocketRoute

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import ClickCaptured, RequestStarted
from inspector.models import ElementInfo
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

T0 = 1_700_000_000_000.0
PAGE = "https://shop.example/"
READY = "พร้อมแล้ว — ลองเปิดเว็บใน Chrome แล้วกดปุ่มสักปุ่ม"
ETHICS = "ใช้ดู traffic ของตัวเองเพื่อการเรียนรู้เท่านั้น อย่านำ API ของเว็บอื่นไปเรียกซ้ำหรือดึงข้อมูลจำนวนมาก"
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}  # ฟอนต์ fallback ได้ จึงยอมให้โหลดจากที่นี่ที่เดียว


@pytest.fixture
def inspector() -> Iterator[str]:
    """Inspector ที่เชื่อม Chrome แล้วแต่ยังไม่มีข้อมูล ป้อนคลิกเพิ่มได้ทาง POST /test/feed/{count}
    และ tracking เบื้องหลังที่ถูกซ่อนทาง POST /test/tracking"""
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = new_pipeline(store, broadcaster)
    pipeline.set_chrome_connected(True)
    app = create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)
    clicks = 0

    @app.post("/test/feed/{count}")
    async def feed(count: int) -> None:
        """route สำหรับ test เท่านั้น: คลิกใหม่ count ครั้ง แต่ละคลิกมี request หนึ่งตัว (บน event loop ของ server)"""
        nonlocal clicks
        for _ in range(count):
            clicks += 1
            ts = T0 + clicks * 10_000
            element = ElementInfo(tag="button", text=f"ปุ่มที่ {clicks}", selector="button.buy")
            pipeline.handle(ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=ts, element=element))
            pipeline.handle(
                RequestStarted(
                    request_key=f"r{clicks}", tab_id="tab-1", page_url=PAGE, ts=ts + 10,
                    method="POST", url=f"https://shop.example/api/item/{clicks}", resource_type="fetch",
                )
            )

    @app.post("/test/tracking")
    async def tracking() -> None:
        """route สำหรับ test เท่านั้น: request เบื้องหลังที่ไม่มีคลิก และถูกซ่อนเพราะเป็น tracking"""
        pipeline.handle(
            RequestStarted(
                request_key=f"t{clicks}", tab_id="tab-1", page_url=PAGE, ts=T0 + clicks * 10_000 + 5_000,
                method="POST", url="https://www.clarity.ms/collect", resource_type="fetch",
            )
        )

    with serve(app) as origin:
        yield origin


async def no_horizontal_scroll(page: Page) -> bool:
    return bool(await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"))


async def font_size(page: Page) -> str:
    return str(await page.evaluate("getComputedStyle(document.body).fontSize"))


def test_font_size_theme_and_ethics_notice_are_remembered(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        # OS ตั้งธีมมืดไว้ แต่ค่าเริ่มต้นยังเป็นสว่าง เพราะโปรเจกเตอร์อ่านง่ายกว่า
        page = await browser.new_page(viewport={"width": 1366, "height": 768}, color_scheme="dark")
        hosts: set[str] = set()
        page.on("request", lambda request: hosts.add(urlsplit(request.url).hostname or ""))
        await page.goto(inspector + "/")

        assert (await page.text_content("#timeline-empty") or "").strip() == READY
        assert await page.is_visible("#timeline-empty")
        assert ETHICS in (await page.text_content("#ethics-banner") or "")
        assert await font_size(page) == "17px"
        assert await page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)"

        # A+ สองครั้ง: 17 → 20 แล้วสุดทาง (ครั้งที่สองกดไม่ได้) ที่ 1366×768 ต้องไม่มี scroll แนวนอน
        await page.click("#font-bigger")
        await page.click("#font-bigger", force=True)
        assert await font_size(page) == "20px"
        assert await page.is_disabled("#font-bigger")
        assert await no_horizontal_scroll(page)
        right_edges = await page.eval_on_selector_all(
            ".topbar button, .topbar select, .topbar label", "els => els.map(e => e.getBoundingClientRect().right)"
        )
        assert max(right_edges) <= 1366

        await page.click("#theme-toggle")
        assert await page.get_attribute("html", "data-theme") == "dark"
        await page.click("#ethics-close")
        assert not await page.is_visible("#ethics-banner")

        # เปิดใหม่: จำขนาด ธีม และการปิดแถบเตือนไว้ใน localStorage
        await page.reload()
        await page.wait_for_selector("#timeline-empty")
        assert await font_size(page) == "20px"
        assert await page.get_attribute("html", "data-theme") == "dark"
        assert await page.evaluate("getComputedStyle(document.body).backgroundColor") != "rgb(255, 255, 255)"
        assert not await page.is_visible("#ethics-banner")

        for _ in range(3):
            if await page.is_enabled("#font-smaller"):
                await page.click("#font-smaller")
        assert await font_size(page) == "14px"
        assert await page.is_disabled("#font-smaller")

        # ฟอนต์มี fallback และไม่โหลดอะไรจาก CDN อื่น
        assert "ui-monospace" in await page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--mono')")
        assert "sans-serif" in await page.evaluate("getComputedStyle(document.body).fontFamily")
        assert hosts <= {"127.0.0.1"} | FONT_HOSTS, hosts

    in_chrome(scenario)


def test_new_cards_do_not_scroll_away_what_the_user_is_reading(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page(viewport={"width": 1366, "height": 768})
        await page.goto(inspector + "/")
        await page.request.post(inspector + "/test/feed/15")
        await page.wait_for_selector('.card:has-text("ปุ่มที่ 15")')

        # ผู้สอนเลื่อนลงไปดูการ์ดเก่า
        reading = page.locator('.card:has-text("ปุ่มที่ 3")')
        await reading.scroll_into_view_if_needed()
        await page.evaluate("document.querySelector('.timeline').scrollTop += 1")  # ไม่อยู่บนสุดแน่ๆ
        top_before = (await reading.bounding_box() or {"y": 0})["y"]

        await page.request.post(inspector + "/test/tracking")  # การ์ดเบื้องหลังที่ถูกซ่อน: ไม่นับเป็นรายการใหม่
        await page.request.post(inspector + "/test/feed/2")
        await page.wait_for_selector('.card:has-text("ปุ่มที่ 17")', state="attached")
        await page.wait_for_selector("#new-items", state="visible")
        assert (await page.text_content("#new-items") or "").strip() == "มี 2 รายการใหม่ ↑"
        top_after = (await reading.bounding_box() or {"y": 0})["y"]
        assert abs(top_after - top_before) < 2  # ไม่เลื่อนหนีจากการ์ดที่อ่านอยู่

        await page.click("#new-items")
        await page.wait_for_function("document.querySelector('.timeline').scrollTop === 0")
        assert not await page.is_visible("#new-items")

        # อยู่บนสุดอยู่แล้ว: การ์ดใหม่ขึ้นให้เห็นเลย ไม่ต้องมีปุ่ม
        await page.request.post(inspector + "/test/feed/1")
        await page.wait_for_selector('.card:has-text("ปุ่มที่ 18")')
        assert "ปุ่มที่ 18" in (await page.locator(".card").first.text_content() or "")
        assert not await page.is_visible("#new-items")

    in_chrome(scenario)


def test_narrow_screen_stacks_timeline_and_detail_with_a_back_button(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page(viewport={"width": 800, "height": 700})
        await page.goto(inspector + "/")
        await page.request.post(inspector + "/test/feed/2")
        await page.wait_for_selector('.card:has-text("ปุ่มที่ 2")')

        # ตามคลิกล่าสุดเลือกให้เอง แต่ไม่เปิด Detail เต็มจอแย่งหน้า Timeline
        await page.wait_for_selector(".exchange[aria-selected=true]")
        assert await page.is_visible("#timeline")
        assert not await page.is_visible("#detail")

        await page.click('.exchange:has-text("/api/item/1")')
        await page.wait_for_selector("#detail-back", state="visible")
        assert await page.is_visible(".detail-head")
        assert not await page.is_visible("#timeline")
        assert "/api/item/1" in (await page.text_content(".detail-url") or "")

        await page.click("#detail-back")
        assert await page.is_visible("#timeline")
        assert not await page.is_visible("#detail")
        assert await page.evaluate("document.activeElement.matches('.exchange[aria-selected=true]')")

        # ↑/↓ เปิด Detail แล้วยังไล่ Exchange ต่อได้ แม้ Timeline ถูกซ่อนอยู่
        await page.keyboard.press("ArrowUp")
        await page.wait_for_selector("#detail-back", state="visible")
        assert "/api/item/2" in (await page.text_content(".detail-url") or "")
        await page.keyboard.press("ArrowDown")
        assert "/api/item/1" in (await page.text_content(".detail-url") or "")
        await page.click("#detail-back")

        await page.click("#font-bigger")
        await page.click("#font-bigger", force=True)
        assert await no_horizontal_scroll(page)

    in_chrome(scenario)


def test_lost_websocket_shows_grey_banner_and_reconnects_with_a_new_snapshot(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page()
        sockets: list[WebSocketRoute] = []
        connected_at: list[float] = []

        def route(ws: WebSocketRoute) -> None:
            ws.connect_to_server()
            sockets.append(ws)
            connected_at.append(time.monotonic())

        await page.route_web_socket("**/ws", route)
        await page.goto(inspector + "/")
        await page.wait_for_selector("#timeline-empty")
        assert not await page.is_visible("#socket-banner")

        await sockets[-1].close()
        closed_at = time.monotonic()
        await page.wait_for_selector("#socket-banner", state="visible")
        assert (await page.text_content("#socket-banner") or "").strip() == "กำลังเชื่อมต่อ Inspector ใหม่…"
        await page.request.post(inspector + "/test/feed/1")  # เกิดระหว่างหลุด: ได้มาจาก snapshot ใหม่

        await page.wait_for_selector("#socket-banner", state="hidden", timeout=7000)
        await page.wait_for_selector('.card:has-text("ปุ่มที่ 1")')
        assert 0.9 <= connected_at[-1] - closed_at <= 5.5  # backoff 1–5 วินาที

    in_chrome(scenario)


def test_page_still_works_when_the_browser_blocks_storage(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page()
        await page.add_init_script(
            "Object.defineProperty(window, 'localStorage', "
            "{get() { throw new DOMException('blocked', 'SecurityError'); }})"
        )
        await page.goto(inspector + "/")
        await page.wait_for_selector("#timeline-empty")
        assert await page.is_visible("#ethics-banner")  # จำไม่ได้ว่าเคยปิด จึงเตือนทุกครั้ง
        await page.click("#font-bigger")
        assert await font_size(page) == "20px"
        await page.request.post(inspector + "/test/feed/1")
        await page.wait_for_selector('.card:has-text("ปุ่มที่ 1")')

    in_chrome(scenario)
