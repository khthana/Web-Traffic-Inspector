"""หน้าจอโหมด `--demo` ใน Chrome จริง: บอกว่าเป็นข้อมูลตัวอย่าง ไม่ใช่ "ไม่พบ Chrome" (`pytest -m chrome`)"""

import pytest
from chrome_support import in_chrome, serve
from pipeline_factory import new_pipeline
from playwright.async_api import Browser

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.store import EventStore

pytestmark = pytest.mark.chrome


def test_demo_mode_is_labelled_as_sample_data() -> None:
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = new_pipeline(store, broadcaster)
    pipeline.start_demo()

    async def scenario(browser: Browser) -> None:
        page = await browser.new_page()
        await page.goto(origin + "/")
        await page.wait_for_function("document.querySelector('#chrome-status .label').textContent !== ''")
        assert await page.text_content("#chrome-status .label") == "โหมดตัวอย่าง (--demo)"
        assert await page.get_attribute("#chrome-status", "data-mode") == "demo"
        assert not await page.is_visible("#chrome-setup")
        assert not await page.is_visible("#chrome-banner")

    with serve(create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)) as origin:
        in_chrome(scenario)
