"""Flow strip ใน Chrome จริง: แอนิเมชัน ผู้ใช้ → เบราว์เซอร์ → เซิร์ฟเวอร์ ด้านบนของ Detail (`pytest -m chrome`)"""

from collections.abc import Iterator
from typing import Any

import pytest
from chrome_support import in_chrome, serve
from pipeline_factory import new_pipeline
from playwright.async_api import Browser, Page

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import ClickCaptured, RequestStarted, ResponseReceived
from inspector.models import ElementInfo
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

T0 = 1_700_000_000_000.0
PAGE = "https://shop.example/"

# แอนิเมชันทุกตัวใน Flow strip: จังหวะไหน จบที่กี่ ms และกำลังเล่นอยู่ไหม
FLOW_ANIMATIONS = """() => document.getAnimations()
  .filter((a) => a.effect.target.closest('#flow-strip'))
  .map((a) => ({
    step: a.effect.target.closest('[data-step]').dataset.step,
    end: a.effect.getComputedTiming().endTime,
    state: a.playState,
  }))"""


@pytest.fixture
def inspector() -> Iterator[str]:
    """คลิก "ใส่ตะกร้า" (POST ได้ 200), request เบื้องหลังที่ไม่มีคลิก และ POST ที่ยังรอคำตอบ (ตอบได้ทาง /test/respond)"""
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = new_pipeline(store, broadcaster)
    element = ElementInfo(tag="button", text="ใส่ตะกร้า", selector="button.buy")
    for event in (
        RequestStarted(
            request_key="poll", tab_id="tab-1", page_url=PAGE, ts=T0 - 60_000, method="GET",
            url="https://shop.example/api/notifications", resource_type="xhr",
        ),
        ResponseReceived(request_key="poll", ts=T0 - 59_950, status=200, status_text="OK", body="[]"),
        ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=T0, element=element),
        RequestStarted(
            request_key="cart", tab_id="tab-1", page_url=PAGE, ts=T0 + 10, method="POST",
            url="https://shop.example/api/cart/add?from=home", resource_type="fetch",
        ),
        ResponseReceived(request_key="cart", ts=T0 + 192, status=200, status_text="OK", body="{}"),
        RequestStarted(
            request_key="slow", tab_id="tab-1", page_url=PAGE, ts=T0 + 20, method="POST",
            url="https://shop.example/api/slow", resource_type="fetch",
        ),
    ):
        pipeline.handle(event)
    app = create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)

    @app.post("/test/respond")
    async def respond() -> None:
        pipeline.handle(ResponseReceived(request_key="slow", ts=T0 + 5_020, status=503, status_text="Service Unavailable"))

    with serve(app) as origin:
        yield origin


async def animations(page: Page) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = await page.evaluate(FLOW_ANIMATIONS)
    return result


async def total_ms(page: Page) -> float:
    return float(max(a["end"] for a in await animations(page)))


async def select(page: Page, path: str) -> None:
    await page.click(f'.exchange:has-text("{path}")')
    await page.wait_for_selector("#flow-strip", state="visible")


def test_three_steps_play_in_about_two_seconds_with_labels_from_the_exchange(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page()
        await page.goto(inspector + "/")
        assert not await page.is_visible("#flow-strip")  # ยังไม่ได้เลือก Exchange
        await select(page, "/api/cart/add")

        strip = page.locator("#flow-strip")
        assert await strip.locator('[data-step="click"] .flow-label').inner_text() == "click"
        request = await strip.locator('[data-step="request"] .flow-label').text_content() or ""
        assert request.replace(chr(0x200E), "") == "POST /api/cart/add"  # LRM ที่ใช้ตัด path จากซ้าย
        response = strip.locator('[data-step="response"] .flow-label')
        assert await response.inner_text() == "200 · 182 ms"
        assert await response.locator(".badge.status-2xx").count() == 1  # สีตาม status แบบเดียวกับ Timeline
        assert "shop.example" in await strip.locator('[data-node="server"]').inner_text()

        steps = await animations(page)
        assert {a["step"] for a in steps} == {"click", "request", "response"}
        assert 1800 <= await total_ms(page) <= 2200
        await page.wait_for_timeout(2300)
        assert all(a["state"] == "finished" for a in await animations(page))

        # ปุ่มเล่นซ้ำ: เล่นแอนิเมชันใหม่ (ไม่ได้ส่ง request ใดๆ)
        await page.click("#flow-again")
        assert any(a["state"] == "running" for a in await animations(page))

        # ช้าลง 4 เท่า และจำค่าไว้หลังโหลดหน้าใหม่
        await page.click('#flow-strip [data-speed="0.25"]')
        assert await page.get_attribute('#flow-strip [data-speed="0.25"]', "aria-pressed") == "true"
        assert 7200 <= await total_ms(page) <= 8800
        await page.reload()
        await select(page, "/api/cart/add")
        assert await page.get_attribute('#flow-strip [data-speed="0.25"]', "aria-pressed") == "true"
        assert 7200 <= await total_ms(page) <= 8800

    in_chrome(scenario)


def test_exchange_without_a_click_skips_the_first_step(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page()
        await page.goto(inspector + "/")
        await select(page, "/api/notifications")

        assert await page.get_attribute("#flow-strip", "data-from-click") == "false"
        assert await page.inner_text('#flow-strip [data-step="click"] .flow-label') == "ไม่มีคลิก"
        assert {a["step"] for a in await animations(page)} == {"request", "response"}
        assert 1300 <= await total_ms(page) <= 1600

        # เลือก Exchange ที่มาจากคลิก: จังหวะแรกกลับมา
        await select(page, "/api/cart/add")
        assert await page.get_attribute("#flow-strip", "data-from-click") == "true"
        assert "click" in {a["step"] for a in await animations(page)}

    in_chrome(scenario)


def test_waiting_exchange_plays_the_response_step_when_the_answer_arrives(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page()
        await page.goto(inspector + "/")
        await select(page, "/api/slow")
        response = page.locator('#flow-strip [data-step="response"] .flow-label')
        assert await response.inner_text() == "รอคำตอบ…"
        assert "response" not in {a["step"] for a in await animations(page)}

        await page.request.post(inspector + "/test/respond")
        await response.locator(".badge.status-5xx").wait_for()
        assert await response.inner_text() == "503 · 5000 ms"
        assert {a["step"] for a in await animations(page) if a["state"] == "running"} == {"response"}

    in_chrome(scenario)


def test_reduced_motion_shows_every_step_without_moving(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page(reduced_motion="reduce")
        await page.goto(inspector + "/")
        await select(page, "/api/cart/add")

        assert await animations(page) == []
        for step in ("click", "request", "response"):
            label = page.locator(f'#flow-strip [data-step="{step}"] .flow-label')
            assert await label.evaluate("(e) => getComputedStyle(e).opacity") == "1"
        await page.click("#flow-again")
        assert await animations(page) == []

    in_chrome(scenario)
