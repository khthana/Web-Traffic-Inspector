"""Redaction ของ body แบบ multipart/form-data: field ลับถูกซ่อน, ไฟล์แนบเหลือแค่ชื่อ ชนิด ขนาด"""

import json
from dataclasses import replace

from conftest import Harness

from inspector.capture_events import RequestStarted, ResponseReceived
from inspector.http_parts import body_kind
from inspector.redactor import Redactor

BOUNDARY = "----WebKitFormBoundaryX7f3"
CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"
PASSWORD = "hunter2-p@ss"
PHONE = "0812345678"
FILE_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4  # ไม่ใช่ UTF-8: แบบเดียวกับไฟล์รูปจริง
FILE_TEXT = FILE_BYTES.decode("utf-8", "surrogateescape")  # แบบที่ capture ส่งมาเมื่อ body มี byte ที่ไม่ใช่ UTF-8


def form(*parts: tuple[str, str], boundary: str = BOUNDARY, closed: bool = True) -> str:
    """ประกอบ body multipart จาก (header ของ part, เนื้อ) ด้วย CRLF แบบที่เบราว์เซอร์ส่ง"""
    body = "".join(f"--{boundary}\r\n{headers}\r\n\r\n{content}\r\n" for headers, content in parts)
    return body + (f"--{boundary}--\r\n" if closed else "")


def field(name: str, value: str) -> tuple[str, str]:
    return f'Content-Disposition: form-data; name="{name}"', value


def upload(name: str, filename: str, content_type: str, content: str) -> tuple[str, str]:
    return f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {content_type}', content


SIGNUP = form(
    field("username", "somchai"),
    field("password", PASSWORD),
    field("mobile_phone", PHONE),
    field("bio", "ชอบเขียนโปรแกรม"),
    upload("avatar", "รูปฉัน.png", "image/png", FILE_TEXT),
)


def signup(body: str = SIGNUP, content_type: str = CONTENT_TYPE) -> RequestStarted:
    return RequestStarted(
        request_key="r1", tab_id="tab-1", page_url="https://shop.example/register", ts=1000.0, method="POST",
        url="https://shop.example/api/register", resource_type="fetch",
        headers={"Content-Type": content_type}, post_data=body,
    )


def test_multipart_is_its_own_body_kind() -> None:
    assert body_kind({"content-type": CONTENT_TYPE}, SIGNUP) == "multipart"


def test_secret_fields_and_file_contents_never_reach_rest_or_websocket(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(signup())
        broadcast = json.dumps(harness.receive(ws), ensure_ascii=False)
    stored = json.dumps(harness.get("/api/exchanges/ex_0001"), ensure_ascii=False)
    for leaked in (PASSWORD, PHONE, "PNG"):
        assert leaked not in broadcast
        assert leaked not in stored


def test_each_part_is_shown_by_its_kind(harness: Harness) -> None:
    harness.feed(signup())
    exchange = harness.get("/api/exchanges/ex_0001")
    request = exchange["request"]
    assert request["body_kind"] == "multipart"
    assert request["body"] == form(
        field("username", "somchai"),  # ข้อความธรรมดาแสดงตามเดิม
        field("password", "••••"),
        field("mobile_phone", "••••"),
        field("bio", "ชอบเขียนโปรแกรม"),
        upload("avatar", "รูปฉัน.png", "image/png", "[ไฟล์: รูปฉัน.png, image/png, 1.0 KB]"),
    )
    assert request["body_unscanned"] is False  # ตรวจแล้ว: ไม่มีป้าย "ไม่ได้ตรวจหาข้อมูลลับ"
    assert exchange["has_redactions"] is True


def test_file_alone_is_not_a_hidden_secret(harness: Harness) -> None:
    # ไฟล์แนบถูกย่อเป็นคำอธิบาย แต่ไม่ใช่ค่าลับ จึงไม่ขึ้นกุญแจ
    harness.feed(signup(form(field("title", "ใบเสร็จ"), upload("scan", "a.txt", "text/plain", "hello"))))
    exchange = harness.get("/api/exchanges/ex_0001")
    assert "[ไฟล์: a.txt, text/plain, 5 B]" in exchange["request"]["body"]
    assert exchange["has_redactions"] is False


def test_response_body_is_redacted_too(harness: Harness) -> None:
    harness.feed(signup(form(field("q", "x"))))
    harness.feed(
        ResponseReceived(
            request_key="r1", ts=1100.0, status=200, status_text="OK",
            headers={"content-type": CONTENT_TYPE}, body=form(field("session_token", "tok-123"), field("ok", "1")),
        )
    )
    exchange = harness.get("/api/exchanges/ex_0001")
    response = exchange["response"]
    assert "tok-123" not in response["body"]
    assert response["body"] == form(field("session_token", "••••"), field("ok", "1"))
    assert response["body_unscanned"] is False and exchange["has_redactions"] is True


def test_preset_keys_apply_to_multipart_fields() -> None:
    redacted = Redactor(("nickname",)).body(form(field("nickname", "แมว")), "multipart", CONTENT_TYPE)
    assert redacted.text == form(field("nickname", "••••")) and redacted.redacted


def test_broken_or_truncated_multipart_falls_back_to_unscanned(harness: Harness) -> None:
    broken = [
        signup(content_type="multipart/form-data"),  # ไม่มี boundary
        signup(content_type="multipart/form-data; boundary=other-boundary"),  # boundary ไม่ตรงกับ body
        signup(form(field("password", PASSWORD), closed=False)),  # ถูกตัดก่อนปิด (เช่นตัดที่ 64 KB)
        signup(f"--{BOUNDARY}\r\nno blank line between headers and content\r\n--{BOUNDARY}--\r\n"),
        signup(form(("Content-Disposition: form-data", "ไม่มีชื่อ field"))),
    ]
    for number, event in enumerate(broken, start=1):
        harness.feed(replace(event, request_key=f"r{number}"))
        request = harness.get(f"/api/exchanges/ex_{number:04d}")["request"]
        assert request["body_unscanned"] is True, event.headers


def test_unscanned_fallback_never_carries_undecodable_bytes(harness: Harness) -> None:
    # body ที่ parse ไม่ได้แต่มี byte ที่ไม่ใช่ UTF-8: ส่งเป็น JSON ได้ ไม่ crash
    harness.feed(signup(form(upload("f", "a.png", "image/png", FILE_TEXT), closed=False)))
    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert request["body_unscanned"] is True and "�" in request["body"]


def test_recording_with_raw_multipart_is_redacted_on_load() -> None:
    redactor = Redactor()
    assert redactor.body(SIGNUP, "multipart", CONTENT_TYPE).text == redactor.body(
        redactor.body(SIGNUP, "multipart", CONTENT_TYPE).text, "multipart", CONTENT_TYPE
    ).text  # ซ่อนซ้ำแล้วได้ผลเดิม (Recording ที่ซ่อนไว้แล้วไม่เปลี่ยน)
