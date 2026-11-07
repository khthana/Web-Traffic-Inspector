"""Integration test กับ Chrome จริง (รันด้วย `pytest -m chrome`)

เปิด Chrome แบบ headless + หน้า fixture ที่ยิง fetch/XHR หลายแบบ
แล้วตรวจผลผ่านข้อมูลเดียวกับที่ REST/WebSocket ส่งให้ UI
"""

import asyncio
from collections.abc import Iterator

import pytest
from chrome_support import INSPECTOR_ORIGIN, ChromeProcess, LiveInspector, run_live, serve, wait_until
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

pytestmark = pytest.mark.chrome

FIXTURE_PAGE = """<!doctype html>
<html><body>
<img src="/img.png">
<script>
  fetch('/api/json').then(r => r.json());
  fetch('/api/form', {method: 'POST', headers: {'content-type': 'application/x-www-form-urlencoded'},
                      body: 'user=somchai&password=hunter2'});
  fetch('/api/binary');
  fetch('/api/big');
  const xhr = new XMLHttpRequest(); xhr.open('GET', '/api/xhr'); xhr.send();
  fetch('/api/tis620');
  fetch('http://127.0.0.1:1/nothing').catch(() => {});
  fetch('http://127.0.0.1:9/inspector-api').catch(() => {});  // origin ของ Inspector เอง
</script>
</body></html>"""

BIG_TEXT = "ก" * 40_000  # ตัวไทย 3 byte: ตัดที่ 64 KB จะตกกลางตัวอักษร
BIG_BYTES = len(BIG_TEXT.encode("utf-8"))
KEPT_BYTES = (64 * 1024 // 3) * 3


def fixture_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def page() -> HTMLResponse:
        return HTMLResponse(FIXTURE_PAGE)

    @app.get("/img.png")
    def image() -> Response:
        return Response(b"\x89PNG\r\n", media_type="image/png")

    @app.get("/api/json")
    def json_api() -> JSONResponse:
        return JSONResponse({"status": "SUCCESS", "data": [1, 2, 3]})

    @app.post("/api/form")
    async def form_api(request: Request) -> JSONResponse:
        await request.body()
        return JSONResponse({"ok": True})

    @app.get("/api/binary")
    def binary_api() -> Response:
        return Response(bytes(range(256)) * 13, media_type="application/x-protobuf")

    @app.get("/api/big")
    def big_api() -> PlainTextResponse:
        return PlainTextResponse(BIG_TEXT)

    @app.get("/api/tis620")
    def tis620_api() -> Response:
        return Response("สวัสดี".encode("cp874"), media_type="text/plain; charset=windows-874")

    @app.get("/api/xhr")
    def xhr_api() -> JSONResponse:
        return JSONResponse({"via": "xhr"})

    return app


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    with serve(fixture_app()) as origin:
        yield origin


def test_fetch_and_xhr_from_a_new_tab_are_captured(chrome: ChromeProcess, site: str) -> None:
    chrome.start()

    async def scenario(inspector: LiveInspector) -> None:
        await wait_until(lambda: inspector.status()["chrome"] == "connected")
        chrome.open_tab(site + "/")  # แท็บเปิดใหม่ระหว่างใช้งาน
        await wait_until(lambda: len([e for e in inspector.exchanges() if e["state"] != "pending"]) >= 7)

        by_path = {e["request"]["path"]: e for e in inspector.exchanges()}
        assert set(by_path) == {
            "/api/json", "/api/form", "/api/binary", "/api/big", "/api/xhr", "/api/tis620", "/nothing"
        }  # ไม่มีรูปภาพ และไม่มี request ไปหา Inspector

        assert by_path["/api/json"]["response"]["body_kind"] == "json"
        assert by_path["/api/xhr"]["resource_type"] == "xhr"
        assert by_path["/api/form"]["request"]["body"] == "user=somchai&password=••••"
        assert by_path["/api/binary"]["response"]["body"] is None
        assert by_path["/api/binary"]["response"]["body_error"].startswith("เป็นไฟล์ binary (application/x-protobuf")
        assert by_path["/api/big"]["response"]["body"] == BIG_TEXT[: KEPT_BYTES // 3]
        assert by_path["/api/big"]["response"]["body_truncated_bytes"] == BIG_BYTES - KEPT_BYTES
        assert by_path["/api/tis620"]["response"]["body"] == "สวัสดี"
        assert by_path["/nothing"]["state"] == "failed"
        assert by_path["/nothing"]["failure"]
        assert [t["url"] for t in inspector.status()["tabs"]] == [site + "/"]

    run_live(chrome.cdp_url, scenario)


def test_inspector_own_tab_is_not_watched(chrome: ChromeProcess, site: str) -> None:
    chrome.start()

    async def scenario(inspector: LiveInspector) -> None:
        await wait_until(lambda: inspector.status()["chrome"] == "connected")
        chrome.open_tab(site + "/")
        await asyncio.sleep(2.0)

        assert inspector.exchanges() == []
        assert inspector.status()["tabs"] == []

    run_live(chrome.cdp_url, scenario, inspector_origins=(site + "/",))  # origin เดียวกัน แม้เขียนต่างกัน


def test_reconnects_after_chrome_restarts(chrome: ChromeProcess, site: str) -> None:
    async def scenario(inspector: LiveInspector) -> None:
        await asyncio.sleep(1.0)
        assert inspector.status()["chrome"] == "disconnected"  # เปิด Inspector ก่อน Chrome

        chrome.start()
        await wait_until(lambda: inspector.status()["chrome"] == "connected", timeout=5.0)

        chrome.stop()
        await wait_until(lambda: inspector.status()["chrome"] == "disconnected", timeout=5.0)

        chrome.start()
        await wait_until(lambda: inspector.status()["chrome"] == "connected", timeout=5.0)

    run_live(chrome.cdp_url, scenario)
