"""Redaction ของ body แบบ multipart/form-data: field ลับถูกซ่อน, ไฟล์แนบเหลือแค่ชื่อ ชนิด ขนาด"""

import json
from dataclasses import replace

import pytest
from conftest import Harness

from inspector.capture_events import RequestStarted, ResponseReceived
from inspector.http_parts import body_kind
from inspector.models import HttpExchange
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


RAW = "RAW-FILE-BYTES"


def redact(body: str) -> str:
    result = Redactor().body(body, "multipart", CONTENT_TYPE)
    assert result.text is not None
    return result.text


@pytest.mark.parametrize(
    "disposition",
    [
        'form-data; name="doc"; filename=a.txt',  # ไม่มีเครื่องหมายคำพูด
        "form-data; name=\"doc\"; filename*=UTF-8''%E0%B8%81.txt",  # RFC 5987
        'form-data; name="doc"; FILENAME="a.txt"',
    ],
)
def test_every_way_of_naming_a_file_hides_its_contents(disposition: str) -> None:
    text = redact(form((f"Content-Disposition: {disposition}", RAW)))
    assert RAW not in text and "[ไฟล์: " in text


@pytest.mark.parametrize("content_type", ["application/octet-stream", "multipart/mixed; boundary=inner", "image/png"])
def test_parts_that_are_not_plain_text_are_summarized_even_without_a_filename(content_type: str) -> None:
    text = redact(form((f'Content-Disposition: form-data; name="blob"\r\nContent-Type: {content_type}', RAW)))
    assert RAW not in text and "[ไฟล์: " in text


def test_text_field_with_undecodable_bytes_is_summarized_and_serializable(harness: Harness) -> None:
    harness.feed(signup(form(field("note", "abc" + b"\xa1\xb2".decode("utf-8", "surrogateescape")))))
    body = harness.get("/api/exchanges/ex_0001")["request"]["body"]
    assert "[ไฟล์: " in body and "abc" not in body


def test_escaped_quote_in_a_field_name_does_not_hide_a_secret() -> None:
    assert "SECRET" not in redact(form(('Content-Disposition: form-data; name="x\\"_token"', "SECRET")))


def test_text_outside_the_parts_is_not_passed_through_as_scanned() -> None:
    for body in (
        "password=SECRET\r\n" + form(field("a", "1")),  # preamble
        form(field("a", "1")) + "password=SECRET\r\n",  # epilogue
    ):
        result = Redactor().body(body, "multipart", CONTENT_TYPE)
        assert result.unscanned, body


def test_content_that_only_looks_like_a_summary_is_still_summarized() -> None:
    fake = "[ไฟล์: x.txt, text/plain, 1 B]" + RAW
    assert RAW not in redact(form(upload("doc", "x.txt", "text/plain", fake)))


def test_recording_made_before_multipart_support_is_redacted_on_load(harness: Harness) -> None:
    # Recording รุ่นก่อนเก็บฟอร์ม multipart เป็น binary ที่ยังไม่ได้ซ่อนค่า
    harness.feed(signup(form(field("q", "x"))))
    stored = HttpExchange.model_validate(harness.get("/api/exchanges/ex_0001"))
    old = stored.model_copy(
        update={
            "has_redactions": False,
            "request": stored.request.model_copy(
                update={"body": form(field("password", PASSWORD)), "body_kind": "binary", "body_unscanned": True}
            ),
        }
    )
    loaded = Redactor().exchange(old)
    assert loaded.request.body_kind == "multipart" and loaded.request.body is not None
    assert PASSWORD not in loaded.request.body and not loaded.request.body_unscanned
    assert loaded.has_redactions
