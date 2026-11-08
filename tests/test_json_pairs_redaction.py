"""Redaction ของ JSON แบบคู่ชื่อ/ค่า (`{"name": "_fbp", "value": ...}`) และ JSON ที่ซ้อนเป็น string ใน JSON (#19)"""

import json
from typing import Any

import pytest
from conftest import Harness, build_harness

from inspector.capture_events import RequestStarted, ResponseReceived
from inspector.models import HttpExchange, Recording
from inspector.redactor import REDACTED, Redactor

SECRET = "X-real-secret-42"
FBP = "fb.2.1794106032950.123456789"


def post(body: str, content_type: str = "application/json") -> RequestStarted:
    return RequestStarted(
        request_key="r1", tab_id="tab-1", page_url="https://shop.example/", ts=1000.0, method="POST",
        url="https://collect.example/events", resource_type="fetch",
        headers={"Content-Type": content_type}, post_data=body,
    )


def redacted(data: Any) -> Any:
    result = Redactor().body(json.dumps(data), "json", "application/json")
    assert result.text is not None and not result.unscanned
    return json.loads(result.text)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ([{"name": "_fbp", "value": FBP}], [{"name": "_fbp", "value": REDACTED}]),
        ({"field": "password", "value": SECRET}, {"field": "password", "value": REDACTED}),
        ({"key": "access_token", "val": SECRET}, {"key": "access_token", "val": REDACTED}),
        ({"id": "email", "content": SECRET}, {"id": "email", "content": REDACTED}),
        ({"Name": "Phone", "Values": [SECRET]}, {"Name": "Phone", "Values": REDACTED}),  # ไม่สนตัวพิมพ์
    ],
)
def test_value_paired_with_a_sensitive_name_is_hidden(data: Any, expected: Any) -> None:
    assert redacted(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        {"name": "color", "value": "red"},  # ชื่อไม่อ่อนไหว
        {"name": "_fbp", "label": "ไม่ใช่ key บอกค่า"},  # ไม่มี key บอกค่าคู่กัน
        {"title": "password", "value": "ok"},  # title ไม่ใช่ key บอกชื่อ
    ],
)
def test_ordinary_pairs_are_kept(data: Any) -> None:
    body = json.dumps(data)
    result = Redactor().body(body, "json", "application/json")
    assert result.text == body and not result.redacted


def test_json_nested_in_a_string_is_redacted_and_stays_a_string() -> None:
    data = {"payload": json.dumps({"password": SECRET, "page": 2}), "event": "login"}
    result = redacted(data)
    assert isinstance(result["payload"], str)
    assert json.loads(result["payload"]) == {"password": REDACTED, "page": 2}
    assert result["event"] == "login"


def test_json_nested_several_times_is_redacted() -> None:
    inner = json.dumps([{"name": "_fbp", "value": FBP}])
    data = {"data": json.dumps({"beacon": inner})}
    result = redacted(data)
    assert FBP not in json.dumps(result)
    assert json.loads(json.loads(result["data"])["beacon"]) == [{"name": "_fbp", "value": REDACTED}]


@pytest.mark.parametrize("value", ["hello {world}", "[not json", "42", '"quoted"', "{}", "[1, 2]"])
def test_strings_without_secrets_are_kept_exactly(value: str) -> None:
    body = json.dumps({"note": value})
    result = Redactor().body(body, "json", "application/json")
    assert result.text == body and not result.redacted and not result.unscanned


def test_nesting_beyond_the_limit_is_flagged_unscanned() -> None:
    value: Any = {"password": SECRET}
    for _ in range(20):
        value = {"wrapped": json.dumps(value)}
    result = Redactor().body(json.dumps(value), "json", "application/json")
    assert result.unscanned is True


def test_deeply_nested_json_does_not_crash() -> None:
    body = "[" * 100_000 + "]" * 100_000  # json.loads ลึกขนาดนี้ไม่ได้ (RecursionError)
    for kind in ("json", "text"):
        result = Redactor().body(body, kind, "application/json")
        assert result.unscanned is True


def test_pairs_and_nested_json_never_reach_any_output(harness: Harness) -> None:
    body = json.dumps({"cookies": [{"name": "_fbp", "value": FBP}], "payload": json.dumps({"password": SECRET})})
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(
            post(body, "text/plain;charset=UTF-8"),  # sendBeacon: JSON ส่งเป็น text (#18)
            ResponseReceived(
                request_key="r1", ts=1050.0, status=200, status_text="OK",
                headers={"Content-Type": "application/json"}, body=json.dumps([{"key": "token", "val": SECRET}]),
            ),
        )
        broadcasts = json.dumps([harness.receive(ws), harness.receive(ws)], ensure_ascii=False)
    exchange = harness.get("/api/exchanges/ex_0001")
    outputs = [
        broadcasts,
        json.dumps(exchange, ensure_ascii=False),
        json.dumps(harness.get("/api/interactions"), ensure_ascii=False),
        json.dumps(harness.get("/api/exchanges/ex_0001/code"), ensure_ascii=False),
        json.dumps(harness.get("/api/export"), ensure_ascii=False),
    ]
    for output in outputs:
        assert FBP not in output
        assert SECRET not in output
    assert exchange["has_redactions"] is True
    assert exchange["request"]["body_unscanned"] is False
    assert exchange["response"]["body_unscanned"] is False


def test_recording_with_raw_pairs_is_redacted_when_opened(harness: Harness) -> None:
    harness.feed(post('{"event":"x"}'))
    recording = Recording.model_validate(harness.get("/api/export"))
    stored = recording.exchanges[0]
    raw = json.dumps([{"name": "_fbp", "value": FBP}])
    old: HttpExchange = stored.model_copy(
        update={"has_redactions": False, "request": stored.request.model_copy(update={"body": raw})}
    )
    with build_harness(recording=recording.model_copy(update={"exchanges": [old]}), recording_file="old.json") as opened:
        exchange = opened.get(f"/api/exchanges/{old.id}")
    assert FBP not in exchange["request"]["body"]
    assert exchange["has_redactions"] is True
