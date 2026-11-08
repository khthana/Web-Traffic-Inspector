"""แท็บ "โค้ด" ใน Chrome จริง: ปุ่ม Copy as … คัดลอกโค้ดลง clipboard และโค้ด fetch ที่ได้รันได้จริง (`pytest -m chrome`)"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from chrome_support import in_chrome, serve
from fastapi import Request
from pipeline_factory import new_pipeline
from playwright.async_api import Browser

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import RequestStarted
from inspector.store import EventStore

pytestmark = pytest.mark.chrome

SECRET = "sess-1234567890"


@pytest.fixture
def inspector() -> Iterator[str]:
    """Inspector ที่มี route ทดสอบ: /test/echo ตอบสิ่งที่ได้รับกลับไป และ /test/feed ป้อน Exchange ที่ยิงไปหา /test/echo"""
    store = EventStore()
    broadcaster = Broadcaster()
    pipeline = new_pipeline(store, broadcaster)
    app = create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)

    @app.post("/test/echo")
    async def echo(request: Request) -> dict[str, Any]:
        return {"headers": dict(request.headers), "body": json.loads(await request.body())}

    @app.post("/test/feed")
    async def feed(request: Request) -> None:
        pipeline.handle(
            RequestStarted(
                request_key="cart", tab_id="tab-1", page_url=str(request.base_url), ts=1.0, method="POST",
                url=f"{request.base_url}test/echo?token={SECRET}", resource_type="fetch",
                headers={"content-type": "application/json", "cookie": f"session={SECRET}", "x-shop": "demo"},
                post_data=json.dumps({"sku": "NB-01", "qty": 1, "password": SECRET}),
            )
        )

    with serve(app) as origin:
        yield origin


def test_code_tab_copies_runnable_fetch_without_hidden_values(inspector: str) -> None:
    async def scenario(browser: Browser) -> None:
        context = await browser.new_context(permissions=["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        await page.goto(inspector + "/")
        await page.wait_for_selector("#chrome-status .label")
        await page.request.post(inspector + "/test/feed")
        await page.click('.exchange:has-text("/test/echo")')
        await page.click('.tab:has-text("โค้ด")')

        buttons = page.locator(".code-block .copy-code")
        await buttons.first.wait_for()
        assert await buttons.all_text_contents() == [
            "Copy as curl", "Copy as Python requests", "Copy as JavaScript fetch",
        ]
        assert SECRET not in await page.inner_text(".tab-panel")
        assert "Git Bash" in await page.inner_text('.code-block:has(.code-snippet[data-language="curl"]) .code-hint')

        await page.click('.copy-code:has-text("Copy as JavaScript fetch")')
        await page.wait_for_selector('.copy-code:has-text("คัดลอกแล้ว")')
        copied = (await page.evaluate("navigator.clipboard.readText()")).replace("\r\n", "\n")  # clipboard ของ Windows ใช้ CRLF
        assert SECRET not in copied
        assert copied == await page.text_content('.code-snippet[data-language="fetch"]')

        # วางลง Console แล้วรันได้เลย: ส่ง request เดิม (ยกเว้น cookie ที่ถูกซ่อน) ไปที่เซิร์ฟเวอร์
        logged = await page.evaluate(
            "async (code) => { const lines = []; const console = { log: (...args) => lines.push(args.join(' ')) };"
            " await eval(`(async () => { ${code} })()`); return lines; }",
            copied,
        )
        status, _, reply = logged[0].partition(" ")
        assert status == "200"
        echoed = json.loads(reply)
        assert echoed["body"] == {"sku": "NB-01", "qty": 1, "password": "••••"}
        assert echoed["headers"]["x-shop"] == "demo"
        assert SECRET not in json.dumps(echoed)

        # เปลี่ยนไปแท็บอื่นแล้วกลับมา: แท็บโค้ดยังโหลดได้ และปุ่มกลับเป็นข้อความเดิม
        await page.click('.tab:has-text("ภาพรวม")')
        await page.click('.tab:has-text("โค้ด")')
        await page.wait_for_selector('.copy-code:has-text("Copy as JavaScript fetch")')

    in_chrome(scenario)
