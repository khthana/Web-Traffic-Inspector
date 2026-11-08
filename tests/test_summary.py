"""ประโยคสรุปภาษาคนของ Exchange (SPEC ข้อ 4.5) ตรวจผ่าน seam หลักแบบตาราง"""

from typing import Any

import pytest
from conftest import Harness

from inspector.capture_events import RequestFailed, RequestStarted, ResponseReceived

T0 = 1_000_000.0
URL = "https://www.advice.co.th/_advice-api/api/v1.0.0/cart/get?page=1"


def exchange_after(harness: Harness, *events: Any) -> dict[str, Any]:
    harness.feed(*events)
    return dict(harness.get("/api/interactions")["exchanges"][-1])


def started(method: str = "POST", url: str = URL) -> RequestStarted:
    return RequestStarted(
        request_key="k", tab_id="tab-1", page_url="https://www.advice.co.th/", ts=T0,
        method=method, url=url, resource_type="fetch",
    )


def answered(status: int, ms: float = 182.4) -> ResponseReceived:
    return ResponseReceived(request_key="k", ts=T0 + ms, status=status, status_text="", headers={})


@pytest.mark.parametrize(
    ("method", "verb"),
    [("GET", "ขอดู"), ("POST", "ส่งข้อมูลไป"), ("PUT", "ขอแก้"), ("PATCH", "ขอแก้"), ("DELETE", "ขอลบ"),
     ("OPTIONS", "ส่งคำขอ OPTIONS ไป")],
)
def test_every_method_has_a_verb(harness: Harness, method: str, verb: str) -> None:
    exchange = exchange_after(harness, started(method), answered(200))
    assert exchange["summary"] == f'เบราว์เซอร์{verb} "cart/get" → เซิร์ฟเวอร์ตอบ 200 สำเร็จ ใน 182 ms'


@pytest.mark.parametrize(
    ("status", "meaning"),
    [
        (200, "สำเร็จ"), (201, "สร้างแล้ว"), (204, "สำเร็จไม่มีเนื้อหา"), (206, "สำเร็จ"),
        (301, "ย้ายที่"), (302, "ย้ายที่"), (307, "ย้ายที่"), (304, "ใช้ของเดิม"),
        (400, "คำขอผิด"), (401, "ยังไม่ได้ล็อกอิน"), (403, "ไม่มีสิทธิ์"), (404, "ไม่พบ"),
        (422, "ข้อมูลไม่ผ่าน validation"), (429, "ถี่เกินไป"),
        (500, "เซิร์ฟเวอร์พัง"), (502, "เซิร์ฟเวอร์พัง"), (503, "เซิร์ฟเวอร์พัง"),
    ],
)
def test_every_status_has_a_meaning(harness: Harness, status: int, meaning: str) -> None:
    exchange = exchange_after(harness, started(), answered(status))
    assert exchange["summary"] == f'เบราว์เซอร์ส่งข้อมูลไป "cart/get" → เซิร์ฟเวอร์ตอบ {status} {meaning} ใน 182 ms'


@pytest.mark.parametrize("status", [405, 408, 409, 410, 101])
def test_status_without_a_known_meaning_shows_only_the_number(harness: Harness, status: int) -> None:
    """405/408/410 ไม่ได้แปลว่า "คำขอผิด" เสมอ: ไม่รู้ความหมายก็ไม่เดา จะได้ไม่สอนผิด"""
    exchange = exchange_after(harness, started(), answered(status))
    assert exchange["summary"] == f'เบราว์เซอร์ส่งข้อมูลไป "cart/get" → เซิร์ฟเวอร์ตอบ {status} ใน 182 ms'


@pytest.mark.parametrize(
    ("url", "tail"),
    [
        ("https://shop.example/", "/"),
        ("https://shop.example/api", "api"),
        ("https://shop.example/api/items/", "api/items"),
        ("https://shop.example/a/b/c/d", "c/d"),
    ],
)
def test_summary_names_the_last_part_of_the_path(harness: Harness, url: str, tail: str) -> None:
    exchange = exchange_after(harness, started("GET", url), answered(200, ms=5))
    assert exchange["summary"] == f'เบราว์เซอร์ขอดู "{tail}" → เซิร์ฟเวอร์ตอบ 200 สำเร็จ ใน 5 ms'


def test_pending_and_failed_exchanges_are_summarized_too(harness: Harness) -> None:
    pending = exchange_after(harness, started("GET"))
    assert pending["summary"] == 'เบราว์เซอร์ขอดู "cart/get" → รอคำตอบจากเซิร์ฟเวอร์…'

    failed = exchange_after(harness, RequestFailed(request_key="k", ts=T0 + 30, failure="net::ERR_CONNECTION_REFUSED"))
    assert failed["summary"] == 'เบราว์เซอร์ขอดู "cart/get" → ไม่ได้คำตอบ (net::ERR_CONNECTION_REFUSED) หลัง 30 ms'


def test_summary_is_sent_with_the_live_update(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(started(), answered(201, ms=99.6))
        messages = [harness.receive(ws) for _ in range(3)]

    update = next(m for m in messages if m["type"] == "exchange.update")
    assert update["data"]["summary"] == 'เบราว์เซอร์ส่งข้อมูลไป "cart/get" → เซิร์ฟเวอร์ตอบ 201 สร้างแล้ว ใน 100 ms'
