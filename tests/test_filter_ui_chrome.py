"""หน้า Inspector แสดงการกรองถูกต้องใน Chrome จริง: ซ่อน Hidden exchange, ปุ่ม "ซ่อน N รายการ" และการ์ดที่มีแต่ tracking (`pytest -m chrome`)"""

import asyncio
from collections.abc import Iterator

import pytest
from chrome_support import find_chrome, serve
from playwright.async_api import async_playwright

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import ClickCaptured, NavigationOccurred, RequestStarted
from inspector.correlator import Correlator
from inspector.filters import PRESETS_DIR, FilterSettings, load_presets
from inspector.models import ElementInfo
from inspector.pipeline import InspectorPipeline
from inspector.redactor import Redactor
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

T0 = 1_700_000_000_000.0
PAGE = "https://www.advice.co.th/"


def request(key: str, url: str, ts: float) -> RequestStarted:
    return RequestStarted(
        request_key=key, tab_id="tab-1", page_url=PAGE, ts=ts, method="POST", url=url, resource_type="fetch"
    )


@pytest.fixture
def inspector() -> Iterator[str]:
    """Inspector ที่มีประวัติอยู่แล้ว (ป้อนก่อนมี client จึงไม่ต้องข้าม thread)"""
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = InspectorPipeline(
        store=store,
        broadcaster=broadcaster,
        redactor=Redactor(),
        correlator=Correlator(window_ms=1500),
        filters=FilterSettings(load_presets(PRESETS_DIR)),
    )
    element = ElementInfo(tag="button", text="ดูรูปถัดไป", selector="button#gallery")
    for event in (
        ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=T0, element=element),
        request("r1", "https://www.clarity.ms/collect", T0 + 50),  # คลิกนี้ไม่มี API call แต่ถูก track
        NavigationOccurred(tab_id="tab-1", url=PAGE, ts=T0 + 3000),
        request("r2", "https://www.advice.co.th/api/cart/get", T0 + 3100),
        request("r3", "https://region1.google-analytics.com/g/collect", T0 + 3200),
        request("r4", "https://www.clarity.ms/collect?beat=1", T0 + 20_000),  # Background ที่มีแต่ tracking
    ):
        pipeline.handle(event)
    with serve(create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)) as origin:
        yield origin



def test_hidden_exchanges_stay_out_of_the_timeline_until_toggled(inspector: str) -> None:
    executable = find_chrome()
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")

    async def scenario() -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            await page.goto(inspector + "/")
            await page.wait_for_selector(".card.kind-click")

            assert await page.text_content("#hidden-toggle") == "ซ่อน 3 รายการ"
            assert not await page.is_visible(".card.kind-background")  # มีแต่ tracking: ไม่ต้องรก Timeline
            assert await page.is_visible(".card.kind-page_load")
            assert not await page.is_visible(".exchange.is-hidden")
            assert await page.is_visible(".card.kind-click .no-calls")
            assert await page.text_content(".card.kind-click .hidden-note") == "(มี tracking 1 รายการที่ซ่อนอยู่)"

            await page.click("#hidden-toggle")
            assert await page.is_visible(".card.kind-background")
            assert await page.locator(".exchange.is-hidden").count() == 3
            reasons = await page.locator(".exchange.is-hidden .hidden-reason").all_text_contents()
            assert sorted(reasons) == [
                "tracking: region1.google-analytics.com", "tracking: www.clarity.ms", "tracking: www.clarity.ms",
            ]

            await page.select_option("#preset", "advice")  # เปลี่ยน Preset: server ส่ง snapshot ใหม่
            await page.wait_for_function("document.querySelector('#preset').value === 'advice'")
            assert await page.text_content("#hidden-toggle") == "ซ่อน 3 รายการ"
            await browser.close()

    asyncio.run(scenario())
