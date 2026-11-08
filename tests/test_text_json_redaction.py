"""Redaction ของ body ชนิด text ที่จริงๆ เป็น JSON (เช่น navigator.sendBeacon ส่ง JSON เป็น text/plain)
และรหัสติดตามผู้ใช้ (_fbp, _ga, gclid ฯลฯ) ซึ่งพบหลุดตอนทดสอบกับเว็บจริง (#18)"""

import json

import pytest
from conftest import Harness, build_harness

from inspector.capture_events import RequestStarted, ResponseReceived
from inspector.models import HttpExchange, Recording
from inspector.redactor import is_sensitive_key

FBP = "fb.2.1794106032950.123456789"
PASSWORD = "hunter2-p@ss"
BEACON = json.dumps({"event": "page_view", "fb.fbp": FBP, "user": {"password": PASSWORD}, "items": [1, 2]})


def beacon(body: str = BEACON) -> RequestStarted:
    return RequestStarted(
        request_key="r1", tab_id="tab-1", page_url="https://shop.example/", ts=1000.0, method="POST",
        url="https://collect.example/events", resource_type="fetch",
        headers={"Content-Type": "text/plain;charset=UTF-8"}, post_data=body,
    )


def test_json_sent_as_text_is_redacted_and_marked_scanned(harness: Harness) -> None:
    harness.feed(beacon())
    exchange = harness.get("/api/exchanges/ex_0001")
    request = exchange["request"]
    assert json.loads(request["body"]) == {
        "event": "page_view", "fb.fbp": "••••", "user": {"password": "••••"}, "items": [1, 2],
    }
    assert request["body_unscanned"] is False
    assert exchange["has_redactions"] is True


def test_secrets_in_text_json_never_reach_any_output(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(beacon())
        broadcast = json.dumps(harness.receive(ws), ensure_ascii=False)
    outputs = [
        broadcast,
        json.dumps(harness.get("/api/interactions"), ensure_ascii=False),
        json.dumps(harness.get("/api/exchanges/ex_0001"), ensure_ascii=False),
        json.dumps(harness.get("/api/exchanges/ex_0001/code"), ensure_ascii=False),
        json.dumps(harness.get("/api/export"), ensure_ascii=False),
    ]
    for output in outputs:
        assert FBP not in output
        assert PASSWORD not in output


def test_text_json_without_secrets_is_kept_as_sent(harness: Harness) -> None:
    body = '{"event":"scroll",  "depth": 50}'  # รูปแบบเดิม (ช่องว่าง) คงไว้เมื่อไม่มีอะไรต้องซ่อน
    harness.feed(beacon(body))
    exchange = harness.get("/api/exchanges/ex_0001")
    assert exchange["request"]["body"] == body
    assert exchange["request"]["body_unscanned"] is False
    assert exchange["has_redactions"] is False


@pytest.mark.parametrize(
    "body",
    [
        "hello token=abc",  # ข้อความธรรมดา
        '{"password": "oops"',  # JSON ที่ถูกตัด (เช่นที่ 64 KB)
        '"just a string"',  # JSON แต่ไม่ใช่ object หรือ array
        "42",
    ],
)
def test_text_that_is_not_a_json_object_or_array_stays_unscanned(harness: Harness, body: str) -> None:
    harness.feed(beacon(body))
    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert request["body"] == body
    assert request["body_unscanned"] is True


def test_text_json_response_is_redacted_too(harness: Harness) -> None:
    harness.feed(
        beacon(),
        ResponseReceived(
            request_key="r1", ts=1050.0, status=200, status_text="OK",
            headers={"Content-Type": "text/html"}, body=json.dumps({"session": "s3cr3t", "_fbp": FBP, "ok": True}),
        ),
    )
    response = harness.get("/api/exchanges/ex_0001")["response"]
    assert json.loads(response["body"]) == {"session": "••••", "_fbp": "••••", "ok": True}
    assert response["body_unscanned"] is False


def test_recording_with_unscanned_text_json_is_redacted_when_opened(harness: Harness) -> None:
    # Recording รุ่นก่อนเก็บ JSON ที่ส่งเป็น text ไว้โดยไม่ได้ตรวจ: Open Recording ต้องซ่อนให้
    harness.feed(beacon('{"event":"x"}'))
    recording = Recording.model_validate(harness.get("/api/export"))
    stored = recording.exchanges[0]
    old: HttpExchange = stored.model_copy(
        update={
            "has_redactions": False,
            "request": stored.request.model_copy(update={"body": BEACON, "body_unscanned": True}),
        }
    )
    with build_harness(recording=recording.model_copy(update={"exchanges": [old]}), recording_file="old.json") as opened:
        exchange = opened.get(f"/api/exchanges/{old.id}")
    assert FBP not in exchange["request"]["body"] and PASSWORD not in exchange["request"]["body"]
    assert exchange["request"]["body_unscanned"] is False
    assert exchange["has_redactions"] is True


@pytest.mark.parametrize(
    "key",
    [
        "fb.fbp", "_fbp", "fbp", "_fbc", "fbc", "_ga", "_ga_ABC123", "ga", "gclid", "fbclid", "_gcl_au_gclid",
        "fbpValue", "gaClientId", "FBP", "_gcl_au", "msclkid", "ttclid",  # camelCase, ตัวใหญ่ และ click id อื่น
    ],
)
def test_tracking_ids_are_sensitive(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["fb_page", "fbpage", "language", "gallery", "tag", "mega", "MEGA", "saga", "fbcode", "page", "Gallery"])
def test_words_that_only_contain_tracking_letters_are_kept(key: str) -> None:
    assert not is_sensitive_key(key)


def test_tracking_ids_are_hidden_in_query_and_form(harness: Harness) -> None:
    harness.feed(
        RequestStarted(
            request_key="r1", tab_id="tab-1", page_url="https://shop.example/", ts=1000.0, method="POST",
            url="https://shop.example/landing?fbclid=IwAR0abc&gclid=Cj0xyz&page=2", resource_type="fetch",
            headers={"Content-Type": "application/x-www-form-urlencoded"}, post_data="_ga=GA1.2.999&qty=1",
        )
    )
    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert request["url"] == "https://shop.example/landing?fbclid=••••&gclid=••••&page=2"
    assert request["body"] == "_ga=••••&qty=1"
