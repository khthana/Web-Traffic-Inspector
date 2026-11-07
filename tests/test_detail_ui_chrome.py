"""Detail view ใน Chrome จริง: หัว Detail, แท็บที่จำไว้, JSON viewer, ตาราง form และเหตุผลของ body ที่อ่านไม่ได้
(`pytest -m chrome`)"""

import asyncio
import json
from collections.abc import Iterator

import pytest
from chrome_support import find_chrome, serve
from playwright.async_api import Page, async_playwright

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import ClickCaptured, RequestStarted, ResponseReceived
from inspector.correlator import Correlator
from inspector.filters import PRESETS_DIR, FilterSettings, load_presets
from inspector.models import ElementInfo
from inspector.pipeline import InspectorPipeline
from inspector.redactor import Redactor
from inspector.store import EventStore
from inspector.summarizer import Summarizer

pytestmark = pytest.mark.chrome

T0 = 1_700_000_000_000.0
PAGE = "https://shop.example/"
API = "https://shop.example/api/v1"
ORDER = {
    "user": {"name": "สมชาย", "password": "hunter2", "delivery": {"city": "กรุงเทพ"}},
    "items": list(range(24)),
    "paid": True,
    "coupon": None,
}


@pytest.fixture
def inspector() -> Iterator[str]:
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = InspectorPipeline(
        store=store,
        broadcaster=broadcaster,
        redactor=Redactor(),
        correlator=Correlator(window_ms=1500),
        filters=FilterSettings(load_presets(PRESETS_DIR)),
        summarizer=Summarizer(),
    )
    element = ElementInfo(tag="button", text="สั่งซื้อ", selector="button#buy")
    json_headers = {"content-type": "application/json"}
    for event in (
        ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=T0, element=element),
        RequestStarted(
            request_key="order", tab_id="tab-1", page_url=PAGE, ts=T0 + 10, method="POST",
            url=f"{API}/orders?ref=home&ref=ad", resource_type="fetch",
            headers={**json_headers, "authorization": "Bearer abc"}, post_data=json.dumps(ORDER, ensure_ascii=False),
        ),
        ResponseReceived(
            request_key="order", ts=T0 + 192, status=201, status_text="Created", headers=json_headers,
            body='{"id": 7, "price": 18990.5}',
        ),
        RequestStarted(
            request_key="login", tab_id="tab-1", page_url=PAGE, ts=T0 + 20, method="POST", url=f"{API}/login",
            resource_type="fetch", headers={"content-type": "application/x-www-form-urlencoded"},
            post_data="q=%E0%B9%82%E0%B8%99%E0%B9%89%E0%B8%95+15&password=secret",
        ),
        ResponseReceived(
            request_key="login", ts=T0 + 60, status=200, status_text="OK",
            headers={"content-type": "application/x-protobuf"},
            body_error="เป็นไฟล์ binary (application/x-protobuf, 3.2 KB)",
        ),
    ):
        pipeline.handle(event)
    with serve(create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)) as origin:
        yield origin


async def texts(page: Page, selector: str) -> list[str]:
    return [text.strip() for text in await page.locator(selector).all_text_contents()]


def test_selecting_an_exchange_shows_its_details(inspector: str) -> None:
    executable = find_chrome()
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")

    async def scenario() -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            await page.goto(inspector + "/")
            order = page.locator(".exchange", has_text="/api/v1/orders")
            await order.wait_for()

            # บรรทัดที่สองของแถว: สรุปภาษาคน
            assert await order.locator(".summary").text_content() == (
                'เบราว์เซอร์ส่งข้อมูลไป "v1/orders" → เซิร์ฟเวอร์ตอบ 201 สร้างแล้ว ใน 182 ms'
            )

            await order.click()
            head = page.locator(".detail-head")
            assert await head.locator(".badge").first.text_content() == "POST"
            assert await head.locator(".detail-url").text_content() == f"{API}/orders?ref=home&ref=ad"
            assert await head.locator(".badge.status-2xx").text_content() == "201"
            assert "182 ms" in (await head.text_content() or "")
            assert "สร้างแล้ว" in (await head.locator(".detail-summary").text_content() or "")
            assert await order.get_attribute("aria-selected") == "true"

            # ภาพรวม: query เป็นตาราง, JSON tree เปิด 2 ชั้นแรก
            assert await texts(page, ".tab[aria-selected=true]") == ["ภาพรวม"]
            assert await texts(page, ".side-request .query-table td") == ["ref", "home", "ref", "ad"]
            tree = page.locator(".side-request .json-viewer")
            assert await tree.locator("details[open]").count() == 3  # root, user, items (ชั้น 1 และ 2)
            assert await tree.locator("summary", has_text="delivery").locator("..").get_attribute("open") is None
            assert await tree.locator(".json-redacted").all_text_contents() == ["ซ่อนไว้"]
            assert "[24 รายการ]" in await texts(page, ".side-request .json-count")
            items = tree.locator("details", has_text="[24 รายการ]").last
            assert await items.locator(":scope > .json-children > li").count() == 11  # 10 รายการแรก + "อีก 14"
            assert await items.locator(".json-more").text_content() == "…อีก 14 รายการ"
            assert await tree.locator(".json-boolean").all_text_contents() == ["true"]
            assert await tree.locator(".json-null").all_text_contents() == ["null"]
            assert await page.locator(".side-response .json-number").all_text_contents() == ["7", "18990.5"]

            await page.locator(".side-request .raw-toggle").click()
            assert '"password": "••••"' in (await page.locator(".side-request pre.raw-body").text_content() or "")

            # แท็บขาออก: request line + headers (ค่าที่ซ่อนมีกุญแจ)
            await page.click(".tab >> text=ขาออก (Request)")
            assert await page.locator(".request-line").text_content() == "POST /api/v1/orders?ref=home&ref=ad HTTP/1.1"
            assert await page.locator(".headers-table th", has_text="authorization").count() == 1
            assert await page.locator(".headers-table tr", has_text="authorization").locator(".flag-lock").count() == 1

            # เปลี่ยน Exchange แล้วยังอยู่แท็บเดิม: form เป็นตาราง
            await page.locator(".exchange", has_text="/api/v1/login").click()
            assert await texts(page, ".tab[aria-selected=true]") == ["ขาออก (Request)"]
            assert await texts(page, ".form-table td") == ["q", "โน้ต 15", "password", "ซ่อนไว้"]

            await page.click(".tab >> text=ขาเข้า (Response)")
            assert await page.locator(".status-line").text_content() == "HTTP/1.1 200 OK"
            assert await page.locator(".body-note").text_content() == "เป็นไฟล์ binary (application/x-protobuf, 3.2 KB)"

            await page.click(".tab >> text=ดิบ (Raw)")
            raw = await texts(page, "pre.raw-http")
            assert raw[0].startswith("POST /api/v1/login HTTP/1.1\ncontent-type: application/x-www-form-urlencoded\n\nq=")
            assert raw[1].startswith("HTTP/1.1 200 OK\ncontent-type: application/x-protobuf")
            await browser.close()

    asyncio.run(scenario())
