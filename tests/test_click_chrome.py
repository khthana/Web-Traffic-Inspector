"""ดักคลิกใน Chrome จริง: คลิกปุ่มบนหน้า fixture แล้วต้องได้ Click interaction ที่ถูกต้อง (`pytest -m chrome`)

ใช้ Playwright อีกตัวเป็น "มือผู้สอน" ที่คลิกผ่าน CDP แยกจาก Inspector
"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from chrome_support import ChromeProcess, LiveInspector, run_live, serve, wait_until
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from playwright.async_api import Page, async_playwright

pytestmark = pytest.mark.chrome

SHOP_PAGE = """<!doctype html>
<html><body>
<div class="product-card">
  <button id="add" class="btn btn-cart primary extra" onclick="addToCart()">ใส่ตะกร้า</button>
</div>
<input id="pw" type="password" value="hunter2-secret">
<div id="draft" contenteditable="true">secret-draft ที่กำลังพิมพ์</div>
<button id="gallery">ดูรูปถัดไป</button>
<button id="spa" onclick="goSpa()">ไปหน้า SPA</button>
<a id="next" href="/next?token=SECRET">ถัดไป</a>
<script>
  function addToCart() {
    document.body.dataset.added = "yes";  // handler ของเว็บต้องยังทำงานตามปกติ
    fetch('/api/cart/add', {method: 'POST', body: '{"sku": "NB-001"}', headers: {'content-type': 'application/json'}});
  }
  function goSpa() {
    history.pushState({}, '', '/spa');
    fetch('/api/spa-data');
  }
</script>
</body></html>"""

NEXT_PAGE = """<!doctype html>
<html><body><h1>หน้าถัดไป</h1><script>fetch('/api/next-data');</script></body></html>"""


def shop_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def shop() -> HTMLResponse:
        return HTMLResponse(SHOP_PAGE)

    @app.get("/next")
    def next_page() -> HTMLResponse:
        return HTMLResponse(NEXT_PAGE)

    @app.post("/api/cart/add")
    def cart_add() -> JSONResponse:
        return JSONResponse({"status": "SUCCESS"})

    @app.get("/api/spa-data")
    def spa_data() -> JSONResponse:
        return JSONResponse({"items": []})

    @app.get("/api/next-data")
    def next_data() -> JSONResponse:
        return JSONResponse({"items": [1]})

    return app


@pytest.fixture(scope="module")
def shop() -> Iterator[str]:
    with serve(shop_app()) as origin:
        yield origin


def clicks(inspector: LiveInspector) -> list[dict[str, Any]]:
    return [i for i in inspector.interactions() if i["kind"] == "click"]


def paths_of(inspector: LiveInspector, interaction: dict[str, Any]) -> list[str]:
    paths = {e["id"]: e["request"]["path"] for e in inspector.exchanges()}
    return [paths[x] for x in interaction["exchange_ids"] if x in paths]


def page_at(pages: list[Page], url: str) -> Page:
    return next(p for p in pages if p.url == url)


def test_clicks_on_a_real_page_become_click_interactions(chrome: ChromeProcess, shop: str) -> None:
    chrome.start(shop + "/")  # แท็บนี้เปิดอยู่ก่อน Inspector เชื่อม: ต้องฉีดสคริปต์ซ้ำให้

    async def scenario(inspector: LiveInspector) -> None:
        await wait_until(lambda: [t["url"] for t in inspector.status()["tabs"]] == [shop + "/"])
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(chrome.cdp_url)
            page = page_at(browser.contexts[0].pages, shop + "/")

            await page.click("#add")
            await wait_until(lambda: any(paths_of(inspector, c) == ["/api/cart/add"] for c in clicks(inspector)))
            assert await page.evaluate("document.body.dataset.added") == "yes"

            await page.click("#pw")
            await page.click("#draft")
            await page.click("#gallery")
            await page.click("#spa")
            await wait_until(lambda: any(paths_of(inspector, c) == ["/api/spa-data"] for c in clicks(inspector)))

            await page.click("#next")
            await wait_until(lambda: any(paths_of(inspector, c) == ["/api/next-data"] for c in clicks(inspector)))

            new_tab = await browser.contexts[0].new_page()  # แท็บใหม่ระหว่างใช้งาน
            await new_tab.goto(shop + "/")
            await new_tab.click("#add")
            await wait_until(lambda: len(clicks(inspector)) == 7 and paths_of(inspector, clicks(inspector)[-1]) != [])
            await browser.close()

        add, password, draft, gallery, spa, link, add_in_new_tab = clicks(inspector)

        assert add["click"]["element"] == {
            "tag": "button", "text": "ใส่ตะกร้า", "aria_label": None, "element_id": "add",
            "classes": ["btn", "btn-cart", "primary"], "href": None, "selector": "button#add",
        }
        assert add["page_url"] == shop + "/"

        assert password["click"]["element"]["tag"] == "input"
        assert password["click"]["element"]["text"] == ""
        assert draft["click"]["element"]["text"] == ""  # กล่องพิมพ์ข้อความแบบ rich text ก็เป็นค่าที่ผู้ใช้พิมพ์
        snapshot = json.dumps(inspector.pipeline.snapshot(), ensure_ascii=False)
        assert "hunter2" not in snapshot and "secret-draft" not in snapshot  # ไม่ส่งค่าที่พิมพ์เด็ดขาด

        assert gallery["exchange_ids"] == []
        assert gallery["click"]["element"]["selector"] == "button#gallery"

        assert spa["navigated_to"] is None  # pushState ไม่นับเป็น Navigation
        assert paths_of(inspector, spa) == ["/api/spa-data"]

        assert link["click"]["element"]["tag"] == "a"
        assert link["click"]["element"]["href"] == shop + "/next?token=••••"
        assert link["navigated_to"] == shop + "/next?token=••••"
        assert paths_of(inspector, link) == ["/api/next-data"]

        assert add_in_new_tab["tab_id"] != add["tab_id"]
        assert paths_of(inspector, add_in_new_tab) == ["/api/cart/add"]
        page_loads = [i for i in inspector.interactions() if i["kind"] == "page_load"]
        assert [i["tab_id"] for i in page_loads] == [add_in_new_tab["tab_id"]]  # มีแค่ตอนแท็บใหม่โหลดหน้า

    run_live(chrome.cdp_url, scenario)
