"""ฟอร์ม multipart/form-data จาก Chrome จริง: ค่าลับและเนื้อไฟล์ไม่หลุดไปถึง Exchange (`pytest -m chrome`)"""

from collections.abc import Iterator

import pytest
from chrome_support import ChromeProcess, LiveInspector, run_live, serve, wait_until
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

pytestmark = pytest.mark.chrome

PASSWORD = "hunter2-p@ss"
BOUNDARY = "server-boundary-42"

PAGE = """<!doctype html>
<html><body><script>
  const form = new FormData();
  form.append('username', 'สมชาย');
  form.append('password', '%s');
  fetch('/api/register', {method: 'POST', body: form});
  // ฟอร์มที่แนบไฟล์: Chrome ไม่แนบ body มากับ event ต้องขอทีหลัง
  const upload = new FormData();
  upload.append('password', '%s');
  upload.append('avatar', new Blob([new Uint8Array([0x89, 0x50, 0xff, 0xfe])], {type: 'image/png'}), 'avatar.png');
  // รอให้ Inspector เปิด CDP session ของแท็บใหม่ก่อน (ผู้ใช้จริงกดอัปโหลดหลังหน้าโหลดเสร็จอยู่แล้ว)
  setTimeout(() => fetch('/api/upload', {method: 'POST', body: upload}), 500);
  fetch('/api/multipart-answer');
</script></body></html>""" % (PASSWORD, PASSWORD)

ANSWER = (
    f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"session_token\"\r\n\r\ntok-SECRET\r\n"
    f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"status\"\r\n\r\nok\r\n"
    f"--{BOUNDARY}--\r\n"
)


def fixture_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def page() -> HTMLResponse:
        return HTMLResponse(PAGE)

    @app.post("/api/register")
    @app.post("/api/upload")
    async def register(request: Request) -> JSONResponse:
        await request.body()
        return JSONResponse({"ok": True})

    @app.get("/api/multipart-answer")
    def answer() -> Response:
        return Response(ANSWER.encode(), media_type=f"multipart/form-data; boundary={BOUNDARY}")

    return app


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    with serve(fixture_app()) as origin:
        yield origin


def test_form_fields_are_redacted_part_by_part(chrome: ChromeProcess, site: str) -> None:
    chrome.start()

    async def scenario(inspector: LiveInspector) -> None:
        await wait_until(lambda: inspector.status()["chrome"] == "connected")
        chrome.open_tab(site + "/")
        await wait_until(lambda: len([e for e in inspector.exchanges() if e["state"] == "done"]) >= 3)
        by_path = {e["request"]["path"]: e for e in inspector.exchanges()}

        register = by_path["/api/register"]
        body = register["request"]["body"]
        assert register["request"]["body_kind"] == "multipart"
        assert register["request"]["body_unscanned"] is False
        assert PASSWORD not in body and "••••" in body
        assert "สมชาย" in body
        assert register["has_redactions"] is True

        # ฟอร์มที่แนบไฟล์: Chrome ไม่แนบ body มากับ request แต่ขอทีหลังได้ (Network.getRequestPostData)
        upload = by_path["/api/upload"]["request"]
        assert upload["body_error"] is None and upload["body_kind"] == "multipart"
        assert "[ไฟล์: avatar.png, image/png, 4 B]" in upload["body"]
        assert 'name="password"\r\n\r\n••••' in upload["body"] and PASSWORD not in upload["body"]
        assert by_path["/api/upload"]["has_redactions"] is True
        assert PASSWORD not in str(by_path["/api/upload"])

        answer = by_path["/api/multipart-answer"]["response"]
        assert answer["body_kind"] == "multipart" and answer["body_unscanned"] is False
        assert "tok-SECRET" not in answer["body"] and "\r\n\r\nok\r\n" in answer["body"]

    run_live(chrome.cdp_url, scenario)
