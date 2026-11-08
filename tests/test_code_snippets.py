"""แท็บ "โค้ด": Copy as curl / Python `requests` / JavaScript `fetch` ผ่าน seam หลัก

นอกจากตรวจว่าไม่มีค่าลับหลุด ยังรันโค้ดที่ได้จริงกับเซิร์ฟเวอร์จำลอง เพื่อยืนยันว่านักศึกษาคัดลอกไปใช้ได้เลย
"""

import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, NamedTuple

import pytest
from conftest import Harness

from inspector.capture_events import RequestStarted

SECRET = "sess-1234567890"
API_KEY = "key-abcdef"


class Received(NamedTuple):
    """request ที่เซิร์ฟเวอร์จำลองได้รับ"""

    method: str
    path: str
    headers: dict[str, str]
    body: str


@pytest.fixture
def echo_server() -> Iterator[tuple[str, list[Received]]]:
    """เซิร์ฟเวอร์จำลองบน 127.0.0.1 จด request ที่ได้รับไว้ แล้วตอบ {"ok": true}"""
    received: list[Received] = []

    class Handler(BaseHTTPRequestHandler):
        def handle_any(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length).decode("utf-8")
            received.append(Received(self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            payload = b'{"ok": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_DELETE = handle_any

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", received
    finally:
        server.shutdown()
        server.server_close()


def add_to_cart(harness: Harness, origin: str = "https://shop.example", note: str = "it's ไทย") -> str:
    """POST JSON ที่มี cookie, API key, token ใน query และรหัสผ่านใน body แล้วคืน id ของ Exchange"""
    harness.feed(
        RequestStarted(
            request_key="cart", tab_id="tab-1", page_url="https://shop.example/", ts=1.0, method="POST",
            url=f"{origin}/api/cart/add?token={SECRET}&lang=th", resource_type="fetch",
            headers={
                ":authority": "shop.example",
                "content-type": "application/json",
                "content-length": "52",
                "accept": "application/json",
                "cookie": f"session={SECRET}",
                "x-api-key": API_KEY,
                "x-note": "it's \"quoted\"",
            },
            post_data=json.dumps({"sku": "NB-01", "qty": 1, "password": SECRET, "note": note}),
        )
    )
    [exchange] = harness.get("/api/interactions")["exchanges"]
    return str(exchange["id"])


def snippets(harness: Harness, exchange_id: str) -> dict[str, str]:
    return {s["language"]: s["code"] for s in harness.get(f"/api/exchanges/{exchange_id}/code")}


def test_code_tab_offers_curl_python_requests_and_javascript_fetch(harness: Harness) -> None:
    samples = harness.get(f"/api/exchanges/{add_to_cart(harness)}/code")

    assert [(s["language"], s["label"]) for s in samples] == [
        ("curl", "Copy as curl"),
        ("python", "Copy as Python requests"),
        ("fetch", "Copy as JavaScript fetch"),
    ]
    assert harness.client.get("/api/exchanges/ex_9999/code").status_code == 404


def test_hidden_headers_and_hidden_values_never_reach_the_code(harness: Harness) -> None:
    for language, code in snippets(harness, add_to_cart(harness)).items():
        assert SECRET not in code, language
        assert API_KEY not in code, language
        lines = [line.strip().lower() for line in code.splitlines() if not line.lstrip().startswith(("#", "//"))]
        assert not any("cookie" in line or "x-api-key" in line for line in lines), language  # header ที่ถูกซ่อนไม่อยู่ในโค้ดเลย
        assert "cookie, x-api-key" in code, language  # แต่บอกไว้ใน comment ว่าตัดอะไรออก


def test_headers_the_http_client_sets_itself_are_left_out(harness: Harness) -> None:
    for language, code in snippets(harness, add_to_cart(harness)).items():
        assert ":authority" not in code, language
        assert "content-length" not in code, language


def test_get_without_body_is_a_plain_one_liner_in_curl(harness: Harness) -> None:
    harness.feed(
        RequestStarted(
            request_key="list", tab_id="tab-1", page_url="https://shop.example/", ts=1.0, method="GET",
            url="https://shop.example/api/items?page=2", resource_type="fetch",
        )
    )
    [exchange] = harness.get("/api/interactions")["exchanges"]
    code = snippets(harness, exchange["id"])

    assert code["curl"] == "curl 'https://shop.example/api/items?page=2'"
    assert "method" not in code["fetch"]  # fetch ใช้ GET อยู่แล้ว


def test_binary_body_is_explained_instead_of_copied(harness: Harness) -> None:
    harness.feed(
        RequestStarted(
            request_key="up", tab_id="tab-1", page_url="https://shop.example/", ts=1.0, method="POST",
            url="https://shop.example/api/upload", resource_type="fetch",
            headers={"content-type": "image/png"}, post_data="\x89PNG...",
        )
    )
    [exchange] = harness.get("/api/interactions")["exchanges"]
    for language, code in snippets(harness, exchange["id"]).items():
        assert "PNG" not in code, language
        assert "body เป็น binary" in code, language


def test_copied_python_requests_code_runs_and_sends_the_same_request(
    harness: Harness, echo_server: tuple[str, list[Received]]
) -> None:
    origin, received = echo_server
    code = snippets(harness, add_to_cart(harness, origin))["python"]

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=20)

    assert result.returncode == 0, result.stderr
    assert '{"ok": true}' in result.stdout
    assert_same_request(received)


@pytest.mark.parametrize("note", ["it's ไทย", "it's ASCII"])  # มีภาษาไทยส่ง body ทาง stdin ไม่มีใช้ --data-raw
def test_copied_curl_command_runs_and_sends_the_same_request(
    harness: Harness, echo_server: tuple[str, list[Received]], tmp_path: Path, note: str
) -> None:
    bash, curl = shutil.which("bash"), shutil.which("curl")
    if bash is None or curl is None:
        pytest.skip("ไม่มี bash หรือ curl ในเครื่องนี้")
    origin, received = echo_server
    code = snippets(harness, add_to_cart(harness, origin, note))["curl"]

    script = tmp_path / "copied.sh"  # เหมือนวางลง terminal: ส่งผ่าน argv บน Windows ภาษาไทยจะเพี้ยนตาม code page
    script.write_text(code, encoding="utf-8")

    result = subprocess.run([bash, str(script)], capture_output=True, encoding="utf-8", timeout=20)

    assert result.returncode == 0, result.stderr
    assert_same_request(received, note)


def assert_same_request(received: list[Received], note: str = "it's ไทย") -> None:
    [request] = received
    assert request.method == "POST"
    assert request.path == "/api/cart/add?token=%E2%80%A2%E2%80%A2%E2%80%A2%E2%80%A2&lang=th"  # •••• แทน token จริง
    assert request.headers["content-type"] == "application/json"
    assert request.headers["x-note"] == "it's \"quoted\""
    assert "cookie" not in request.headers
    assert json.loads(request.body) == {"sku": "NB-01", "qty": 1, "password": "••••", "note": note}
