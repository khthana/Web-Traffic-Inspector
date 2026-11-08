"""สถานะการเชื่อม Chrome และ Watched tab ที่ UI เห็นผ่าน /ws และ /api/status"""

from conftest import Harness

from inspector.capture_events import RequestStarted, TabChanged


def tab(tab_id: str, url: str, open: bool = True) -> TabChanged:
    return TabChanged(tab_id=tab_id, url=url, ts=1.0, open=open)


def test_status_starts_disconnected_with_launch_command(harness: Harness) -> None:
    status = harness.get("/api/status")

    assert status["chrome"] == "disconnected"
    assert "--remote-debugging-port=9222" in status["chrome_launch_command"]
    assert "--user-data-dir=" in status["chrome_launch_command"]


def test_connecting_chrome_is_broadcast(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.call(harness.pipeline.set_chrome_connected, True)
        message = harness.receive(ws)

    assert message["type"] == "status"
    assert message["data"]["chrome"] == "connected"


def test_watched_tabs_are_listed_and_removed(harness: Harness) -> None:
    harness.call(harness.pipeline.set_chrome_connected, True)
    harness.feed(
        tab("tab-1", "https://www.advice.co.th/"),
        tab("tab-2", "https://example.com/"),
        tab("tab-1", "https://www.advice.co.th/product/notebooks"),  # แท็บเดิมเปลี่ยน URL
        tab("tab-2", "https://example.com/", open=False),
    )

    status = harness.get("/api/status")
    assert status["tabs"] == [{"tab_id": "tab-1", "url": "https://www.advice.co.th/product/notebooks"}]


def test_tab_urls_in_status_are_redacted(harness: Harness) -> None:
    harness.feed(tab("tab-1", "https://shop.example/?token=SECRET"))

    assert harness.get("/api/status")["tabs"][0]["url"] == "https://shop.example/?token=••••"


def test_chrome_disconnect_keeps_data_and_fails_pending_exchanges(harness: Harness) -> None:
    harness.call(harness.pipeline.set_chrome_connected, True)
    harness.feed(
        tab("tab-1", "https://www.advice.co.th/"),
        RequestStarted(
            request_key="r1", tab_id="tab-1", page_url="https://www.advice.co.th/", ts=1000.0,
            method="GET", url="https://www.advice.co.th/api/get-category", resource_type="fetch",
        ),
    )

    harness.call(harness.pipeline.set_chrome_connected, False)

    status = harness.get("/api/status")
    exchange = harness.get("/api/exchanges/ex_0001")
    assert status["chrome"] == "disconnected"
    assert status["tabs"] == []
    assert exchange["state"] == "failed"
    assert exchange["failure"] == "Chrome หลุดก่อนได้คำตอบ"
