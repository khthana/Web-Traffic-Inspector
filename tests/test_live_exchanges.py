"""Exchange ที่ดักได้ต้องไปถึง UI แบบ real-time ผ่าน /ws และอ่านได้ผ่าน REST"""

from conftest import Harness

from inspector.capture_events import RequestFailed, RequestStarted, ResponseReceived

CART_GET = RequestStarted(
    request_key="r1",
    tab_id="tab-1",
    page_url="https://www.advice.co.th/product/notebooks",
    ts=1_000_000.0,
    method="POST",
    url="https://www.advice.co.th/_advice-api/api/v1.0.0/cart/get?lang=th&lang=en",
    resource_type="fetch",
    headers={"content-type": "application/json"},
    post_data='{"page": 1}',
)


def test_new_ws_client_receives_empty_snapshot(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        message = harness.receive(ws)

    assert message["type"] == "snapshot"
    assert message["data"]["interactions"] == []
    assert message["data"]["exchanges"] == []
    assert message["data"]["status"]["chrome"] == "disconnected"


def test_request_started_is_broadcast_as_pending_exchange(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(CART_GET)
        harness.receive(ws)  # interaction.new (Background interaction ของแท็บ)
        message = harness.receive(ws)

    assert message["type"] == "exchange.new"
    exchange = message["data"]
    assert exchange["state"] == "pending"
    assert exchange["tab_id"] == "tab-1"
    assert exchange["started_at"] == 1_000_000.0
    assert exchange["response"] is None
    request = exchange["request"]
    assert request["method"] == "POST"
    assert request["host"] == "www.advice.co.th"
    assert request["path"] == "/_advice-api/api/v1.0.0/cart/get"
    assert request["query"] == {"lang": ["th", "en"]}
    assert request["body"] == '{"page": 1}'
    assert request["body_kind"] == "json"


def test_response_completes_the_pending_exchange(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(
            CART_GET,
            ResponseReceived(
                request_key="r1",
                ts=1_000_182.0,
                status=200,
                status_text="OK",
                headers={"Content-Type": "application/json; charset=utf-8"},
                body='{"status":"SUCCESS","data":[]}',
            ),
        )
        harness.receive(ws)  # interaction.new (Background interaction ของแท็บ)
        new = harness.receive(ws)
        update = harness.receive(ws)

    assert update["type"] == "exchange.update"
    exchange = update["data"]
    assert exchange["id"] == new["data"]["id"]
    assert exchange["state"] == "done"
    assert exchange["duration_ms"] == 182.0
    assert exchange["response"]["status"] == 200
    assert exchange["response"]["status_text"] == "OK"
    assert exchange["response"]["body"] == '{"status":"SUCCESS","data":[]}'
    assert exchange["response"]["body_kind"] == "json"


def test_failed_request_is_marked_failed_with_reason(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(CART_GET, RequestFailed(request_key="r1", ts=1_000_050.0, failure="net::ERR_ABORTED"))
        harness.receive(ws)  # interaction.new (Background interaction ของแท็บ)
        harness.receive(ws)  # exchange.new
        update = harness.receive(ws)

    assert update["type"] == "exchange.update"
    assert update["data"]["state"] == "failed"
    assert update["data"]["failure"] == "net::ERR_ABORTED"
    assert update["data"]["duration_ms"] == 50.0
    assert update["data"]["response"] is None


def test_unreadable_body_keeps_reason_and_truncation(harness: Harness) -> None:
    harness.feed(
        CART_GET,
        ResponseReceived(
            request_key="r1",
            ts=1_000_100.0,
            status=200,
            status_text="OK",
            headers={"content-type": "application/x-protobuf"},
            body=None,
            body_error="เป็นไฟล์ binary (application/x-protobuf, 3.2 KB)",
        ),
    )

    exchange = harness.get("/api/exchanges/ex_0001")
    assert exchange["response"]["body"] is None
    assert exchange["response"]["body_kind"] == "none"
    assert exchange["response"]["body_error"] == "เป็นไฟล์ binary (application/x-protobuf, 3.2 KB)"


def test_late_ws_client_gets_existing_exchanges_in_snapshot(harness: Harness) -> None:
    harness.feed(CART_GET)

    with harness.client.websocket_connect("/ws") as ws:
        snapshot = harness.receive(ws)

    assert [e["request"]["path"] for e in snapshot["data"]["exchanges"]] == ["/_advice-api/api/v1.0.0/cart/get"]


def test_history_and_status_are_available_over_rest(harness: Harness) -> None:
    harness.feed(CART_GET)

    history = harness.get("/api/interactions")
    status = harness.get("/api/status")

    assert [e["id"] for e in history["exchanges"]] == ["ex_0001"]
    assert status.pop("chrome_launch_command")  # ทดสอบละเอียดใน test_chrome_status.py
    assert status == {
        "chrome": "disconnected",
        "paused": False,
        "hidden_count": 0,
        "tabs": [],
        "mode": "live",
        "recording_file": None,
    }


def test_unknown_exchange_is_404(harness: Harness) -> None:
    response = harness.client.get("/api/exchanges/ex_9999")

    assert response.status_code == 404


def test_response_for_unknown_request_is_ignored(harness: Harness) -> None:
    harness.feed(ResponseReceived(request_key="nope", ts=1.0, status=200, status_text="OK"))

    assert harness.get("/api/interactions")["exchanges"] == []


def test_inspector_page_and_api_docs_are_served(harness: Harness) -> None:
    page = harness.client.get("/")
    docs = harness.client.get("/docs")

    assert page.status_code == 200
    assert "Web Traffic Inspector" in page.text
    assert docs.status_code == 200
