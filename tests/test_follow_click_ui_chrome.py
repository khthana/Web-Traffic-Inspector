"""Detail ตามคลิกล่าสุดใน Chrome จริง: เลือก Exchange หลักของคลิกให้เอง, แท็บ "คลิก (Event)" และปิดได้ด้วย checkbox
(`pytest -m chrome`)"""

import asyncio
from collections.abc import Iterator

import pytest
from chrome_support import find_chrome, serve
from pipeline_factory import new_pipeline
from playwright.async_api import Page, async_playwright

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import CaptureEvent, ClickCaptured, NavigationOccurred, RequestStarted
from inspector.models import ElementInfo
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

T0 = 1_700_000_000_000.0
PAGE = "https://shop.example/"
API = "https://shop.example/api"


def request(key: str, method: str, url: str, ts: float) -> RequestStarted:
    return RequestStarted(request_key=key, tab_id="tab-1", page_url=PAGE, ts=ts, method=method, url=url, resource_type="fetch")


def click(text: str, ts: float) -> ClickCaptured:
    element = ElementInfo(tag="button", text=text, selector="main > button.buy")
    return ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=ts, element=element)


T1, T2, T3, T4, T5 = T0 + 10_000, T0 + 20_000, T0 + 30_000, T0 + 40_000, T0 + 50_000
T6, T7, T8, T9, T10 = T0 + 60_000, T0 + 70_000, T0 + 80_000, T0 + 90_000, T0 + 100_000
STEPS: dict[str, list[CaptureEvent]] = {
    "buy": [
        click("ใส่ตะกร้า", T1),
        request("b1", "GET", f"{API}/cart/get", T1 + 20),
        request("b2", "POST", "https://www.clarity.ms/collect", T1 + 30),  # tracking ถูกซ่อน: ไม่นับ
        request("b3", "POST", f"{API}/cart/add", T1 + 45),
    ],
    "buy-more": [request("b4", "POST", f"{API}/cart/count", T1 + 300)],
    "browse": [
        click("ดูสินค้า", T2),
        request("w1", "GET", f"{API}/products", T2 + 30),
        request("w2", "GET", f"{API}/banner", T2 + 40),
    ],
    "wish": [click("ถูกใจ", T3), request("h1", "POST", f"{API}/wish", T3 + 10)],
    "track-only": [click("ดูรูปถัดไป", T4), request("t1", "POST", "https://www.clarity.ms/collect", T4 + 10)],
    "late-buy": [click("ซื้อเลย", T5), request("l1", "POST", f"{API}/buy", T5 + 10)],
    # เว็บแบบ advice.co.th ใช้ POST ทุก API: Exchange หลักคือ action (cart/add) ไม่ใช่ POST ตัวแรก
    "post-everything": [
        click("เพิ่มลงตะกร้า", T6),
        request("a1", "POST", f"{API}/product/propair", T6 + 10),
        request("a2", "POST", f"{API}/product/online-propair", T6 + 20),
        request("a3", "POST", f"{API}/v1.0.0/cart/add", T6 + 30),
        request("a4", "POST", f"{API}/v1.0.0/cart/get", T6 + 40),
    ],
    # คะแนนเท่ากัน: ตัวที่มาถึงก่อนชนะ ตัวหลังไม่แย่ง แม้เวลาเริ่มของตัวหลังจะเร็วกว่า
    "tie": [
        click("กดไลก์", T7),
        request("e1", "POST", f"{API}/like", T7 + 20),
        request("e2", "POST", f"{API}/follow", T7 + 10),
    ],
    # ระหว่างยังตามอยู่ (ยังไม่ได้คะแนนสูงสุด): ตัวที่คะแนนต่ำกว่าไม่แย่ง
    "lower-later": [
        click("โหวต", T8),
        request("v1", "POST", f"{API}/vote", T8 + 10),
        request("v2", "POST", f"{API}/stock/list", T8 + 20),
    ],
    "promo": [click("ดูโปร", T9), request("m1", "POST", f"{API}/promo", T9 + 10)],
    "promo-add": [request("m2", "POST", f"{API}/coupon/add", T9 + 30)],
    "draft": [click("ส่งฟอร์ม", T10), request("d1", "POST", f"{API}/draft", T10 + 10)],
    "draft-submit": [request("d2", "POST", f"{API}/send/submit", T10 + 30)],
}


@pytest.fixture
def inspector() -> Iterator[str]:
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = new_pipeline(store, broadcaster)
    pipeline.handle(NavigationOccurred(tab_id="tab-1", url=PAGE, ts=T0))
    pipeline.handle(request("p1", "GET", f"{API}/home", T0 + 50))
    app = create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)

    @app.post("/test/feed/{step}")
    async def feed(step: str) -> None:
        """route สำหรับ test เท่านั้น: ป้อน event บน event loop ของ server ระหว่างที่หน้าเว็บเปิดอยู่"""
        for event in STEPS[step]:
            pipeline.handle(event)

    with serve(app) as origin:
        yield origin


async def selected_path(page: Page, path: str) -> None:
    # attached: แถวที่เลือกอาจถูกซ่อนตาม Preset อยู่ แต่ยังเป็นตัวที่เลือก
    await page.wait_for_selector(f'.exchange[aria-selected=true]:has-text("{path}")', state="attached")


def test_detail_follows_the_latest_click(inspector: str) -> None:
    executable = find_chrome()
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")

    async def scenario() -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            await page.goto(inspector + "/")
            await page.wait_for_selector(".exchange")
            assert await page.is_checked("#follow-clicks")

            # Exchange ที่ไม่ได้เกิดจากคลิก: แท็บคลิกบอกเหตุผล
            await page.locator(".exchange", has_text="/api/home").click()
            await page.click(".tab >> text=คลิก (Event)")
            assert "ไม่ได้เกิดจากคลิก" in (await page.text_content(".tab-panel") or "")

            # คลิกใหม่: เลือก Exchange ที่มองเห็นและไม่ใช่ GET ตัวแรก (ข้าม GET และ tracking ที่ซ่อนอยู่)
            await page.request.post(inspector + "/test/feed/buy")
            await selected_path(page, "/api/cart/add")
            assert await page.text_content(".click-tag") == "<button>"
            assert await page.text_content(".click-text") == "ใส่ตะกร้า"
            assert await page.text_content(".click-selector") == "main > button.buy"
            assert await page.text_content(".click-delay") == "45 ms"

            # ผู้สอนเลือกเองแล้ว: Exchange ที่มาทีหลังของคลิกเดิมไม่แย่งไป
            await page.locator(".exchange", has_text="/api/cart/get").click()
            await page.request.post(inspector + "/test/feed/buy-more")
            await page.wait_for_selector('.exchange:has-text("/api/cart/count")')
            await selected_path(page, "/api/cart/get")

            # คลิกที่มีแต่ GET: เลือกตัวแรก
            await page.request.post(inspector + "/test/feed/browse")
            await selected_path(page, "/api/products")
            assert await page.text_content(".click-delay") == "30 ms"

            # คลิกที่มีแต่ tracking (ซ่อนอยู่): ไม่เลือกอะไรที่ผู้ชมมองไม่เห็น Detail คงเดิม
            await page.request.post(inspector + "/test/feed/track-only")
            await page.wait_for_selector('.card:has-text("ดูรูปถัดไป") .exchange.is-hidden', state="attached")
            await selected_path(page, "/api/products")

            # Preset advice ซ่อน shop.example: คลิกนี้ยังไม่มีอะไรให้เลือก
            # เปลี่ยนกลับเป็น "ทุกเว็บ" (snapshot ใหม่) แล้ว POST ที่เพิ่งมองเห็นต้องถูกเลือก
            await page.select_option("#preset", "advice")
            await page.wait_for_selector('.exchange.is-hidden:has-text("/api/products")', state="attached")
            await page.request.post(inspector + "/test/feed/late-buy")
            await page.wait_for_selector('.exchange.is-hidden:has-text("/api/buy")', state="attached")
            await selected_path(page, "/api/products")
            await page.select_option("#preset", "all")
            await selected_path(page, "/api/buy")

            # POST ทุกตัว: Exchange ที่มาทีหลังแต่เป็น action แย่งการเลือกได้ ส่วน cart/get ที่ตามมาไม่แย่ง
            await page.request.post(inspector + "/test/feed/post-everything")
            await selected_path(page, "/cart/add")
            await page.wait_for_selector('.exchange:has-text("/cart/get")')
            await selected_path(page, "/cart/add")

            await page.request.post(inspector + "/test/feed/tie")
            await page.wait_for_selector('.exchange:has-text("/api/follow")')
            await selected_path(page, "/api/like")

            await page.request.post(inspector + "/test/feed/lower-later")
            await page.wait_for_selector('.exchange:has-text("/api/stock/list")')
            await selected_path(page, "/api/vote")

            # ผู้สอนเลือกเองระหว่างที่ยังตามอยู่: action ที่มาทีหลังไม่แย่ง
            await page.request.post(inspector + "/test/feed/promo")
            await selected_path(page, "/api/promo")
            await page.locator(".exchange", has_text="/api/vote").click()
            await page.request.post(inspector + "/test/feed/promo-add")
            await page.wait_for_selector('.exchange:has-text("/api/coupon/add")')
            await selected_path(page, "/api/vote")

            # ปิด "ตามคลิกล่าสุด" ระหว่างที่ยังตามอยู่: action ที่มาทีหลังและคลิกใหม่ไม่เปลี่ยน Exchange ที่เลือก
            await page.request.post(inspector + "/test/feed/draft")
            await selected_path(page, "/api/draft")
            await page.uncheck("#follow-clicks")
            await page.request.post(inspector + "/test/feed/draft-submit")
            await page.wait_for_selector('.exchange:has-text("/api/send/submit")')
            await page.request.post(inspector + "/test/feed/wish")
            await page.wait_for_selector('.exchange:has-text("/api/wish")')
            await selected_path(page, "/api/draft")
            await browser.close()

    asyncio.run(scenario())


SHOP = "https://shop.example"
SCORES = [
    ("POST", f"{SHOP}/_advice-api/api/v1.0.0/cart/add", 3),
    ("POST", f"{SHOP}/api/addToCart", 3),  # camelCase แยกเป็นคำ
    ("POST", f"{SHOP}/api/ADDToCart", 3),  # ตัวใหญ่ติดกันก่อน camelCase
    ("PUT", f"{SHOP}/api/updates", 3),  # พหูพจน์
    ("POST", f"{SHOP}/api/payment", 3),
    ("POST", f"{SHOP}/api/addresses", 2),  # "addresses" ไม่ใช่ "add"
    ("POST", "/api/cart/add#top", 3),  # URL ที่อ่านไม่ได้: ใช้ทั้งข้อความจนถึง ? หรือ #
    ("POST", "/api/stats?do=add", 2),
    ("DELETE", f"{SHOP}/api/items/42", 2),
    ("POST", f"{SHOP}/api/wish", 2),
    ("POST", f"{SHOP}/product/propair", 2),  # "pair" อยู่ในคำอื่น ไม่ใช่คำบอก action
    ("POST", f"{SHOP}/api/get-popup-home", 1),
    ("POST", f"{SHOP}/api/product/category/data", 1),
    ("POST", f"{SHOP}/api/search?q=add", 1),  # query ไม่นับ
    ("GET", f"{SHOP}/api/products", 0),
    ("GET", f"{SHOP}/logout", 0),  # GET อ่านอย่างเดียวตามมาตรฐาน ต่ำสุดเสมอ
]


def test_main_exchange_score(inspector: str) -> None:
    executable = find_chrome()
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")

    async def scenario() -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            await page.goto(inspector + "/")
            for method, url, expected in SCORES:
                # app.js เป็น script ธรรมดา (ไม่ใช่ module) function ระดับบนสุดจึงเรียกจาก page ได้
                score = await page.evaluate("([method, url]) => mainExchangeScore({request: {method, url}})", [method, url])
                assert score == expected, (method, url)
            await browser.close()

    asyncio.run(scenario())
