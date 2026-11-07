"""ปุ่ม Export และหน้าจอโหมด Recording playback ใน Chrome จริง (`pytest -m chrome`)"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from chrome_support import in_chrome, serve
from pipeline_factory import new_pipeline
from playwright.async_api import Browser

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import ClickCaptured, RequestStarted
from inspector.models import ElementInfo
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

T0 = 1_700_000_000_000.0
PAGE = "https://shop.example/"


@pytest.fixture
def playback() -> Iterator[str]:
    """Inspector โหมด Recording playback ที่เปิด Recording ของ session ที่มีสองคลิก"""
    live = new_pipeline(EventStore(), Broadcaster())
    for n, ts in ((1, T0), (2, T0 + 10_000)):
        element = ElementInfo(tag="button", text=f"ปุ่มที่ {n}", selector="button.buy")
        live.handle(ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=ts, element=element))
        live.handle(
            RequestStarted(
                request_key=f"r{n}", tab_id="tab-1", page_url=PAGE, ts=ts + 10, method="POST",
                url=f"https://shop.example/api/item/{n}", resource_type="fetch",
            )
        )

    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = new_pipeline(store, broadcaster, chrome_launch_command="chrome --remote-debugging-port=9222")
    pipeline.play(live.recording(), "lab-01.json")
    with serve(create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)) as origin:
        yield origin


def test_playback_mode_and_export_buttons(playback: str, tmp_path: Path) -> None:
    async def scenario(browser: Browser) -> None:
        page = await browser.new_page(accept_downloads=True)
        await page.goto(playback + "/")
        await page.wait_for_selector('.card:has-text("ปุ่มที่ 2")')

        # ไม่ต่อ Chrome โดยตั้งใจ: ไม่สอนวิธีเปิด Chrome ไม่เตือนว่าหลุด และไม่มีปุ่มหยุด
        assert await page.text_content("#chrome-status .label") == "โหมดเล่นซ้ำ: lab-01.json"
        assert not await page.is_visible("#chrome-setup")
        assert not await page.is_visible("#chrome-banner")
        assert not await page.is_visible("#pause-toggle")
        await page.keyboard.press("Space")  # คีย์ลัดหยุดก็ไม่ทำอะไร
        await page.wait_for_timeout(300)
        assert not await page.is_visible("#paused-banner")

        async with page.expect_download() as session_download:
            await page.click("#export")
        download = await session_download.value
        assert download.suggested_filename.startswith("recording-")
        saved = tmp_path / "session.json"
        await download.save_as(saved)
        session = json.loads(saved.read_text(encoding="utf-8"))
        assert len(session["interactions"]) == 2

        # Export เฉพาะ Interaction ของ Exchange ที่เปิดดูอยู่
        await page.click('.exchange:has-text("/api/item/1")')
        async with page.expect_download() as one_download:
            await page.click(".export-one")
        saved_one = tmp_path / "one.json"
        await (await one_download.value).save_as(saved_one)
        one = json.loads(saved_one.read_text(encoding="utf-8"))
        assert [e["request"]["url"] for e in one["exchanges"]] == ["https://shop.example/api/item/1"]

    in_chrome(scenario)
