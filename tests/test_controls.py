"""การควบคุมการเก็บ: Pause / Resume / Clear และเพดาน `--max-exchanges` ผ่าน seam หลัก"""

from typing import Any

from conftest import Harness, build_harness

from inspector.capture_events import ClickCaptured, RequestStarted, ResponseReceived
from inspector.models import ElementInfo

T0 = 1_000_000.0
PAGE = "https://shop.example/"
API = "https://shop.example/api"
TRACKING = "https://www.clarity.ms/collect"


def request(key: str, url: str, ts: float, method: str = "POST") -> RequestStarted:
    return RequestStarted(request_key=key, tab_id="tab-1", page_url=PAGE, ts=ts, method=method, url=url, resource_type="fetch")


def click(ts: float, text: str = "ใส่ตะกร้า") -> ClickCaptured:
    element = ElementInfo(tag="button", text=text, selector="button.buy")
    return ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=ts, element=element)


def answered(key: str, ts: float) -> ResponseReceived:
    return ResponseReceived(request_key=key, ts=ts, status=200, status_text="OK")


def post(harness: Harness, path: str) -> Any:
    response = harness.client.post(path)
    assert response.status_code == 200, response.text
    return response.json()


def history(harness: Harness) -> dict[str, Any]:
    return dict(harness.get("/api/interactions"))


def urls(harness: Harness) -> list[str]:
    return [exchange["request"]["url"] for exchange in history(harness)["exchanges"]]


def test_pause_drops_new_requests_and_clicks_but_finishes_pending_ones(harness: Harness) -> None:
    harness.feed(request("before", f"{API}/before", T0))

    status = post(harness, "/api/pause")
    assert status["paused"] is True
    harness.feed(
        click(T0 + 100),
        request("during", f"{API}/during", T0 + 120),
        request("tracking", TRACKING, T0 + 130),
        answered("before", T0 + 200),
    )

    assert urls(harness) == [f"{API}/before"]
    assert history(harness)["exchanges"][0]["state"] == "done"  # Exchange ที่ค้างอยู่ยังได้คำตอบ
    assert not any(interaction["kind"] == "click" for interaction in history(harness)["interactions"])
    assert harness.get("/api/status")["hidden_count"] == 0  # ของที่ทิ้งระหว่าง Pause ไม่นับ


def test_pause_and_resume_are_broadcast_as_status(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        post(harness, "/api/pause")
        assert harness.receive(ws) == {"type": "status", "data": {**harness.get("/api/status"), "paused": True}}
        post(harness, "/api/resume")
        message = harness.receive(ws)
        assert message["type"] == "status"
        assert message["data"]["paused"] is False


def test_click_before_pause_does_not_claim_requests_after_resume(harness: Harness) -> None:
    harness.feed(click(T0))
    post(harness, "/api/pause")
    post(harness, "/api/resume")
    harness.feed(request("after", f"{API}/after", T0 + 200))  # ยังอยู่ใน Correlation window ของคลิกเดิม

    interactions = history(harness)["interactions"]
    owner = next(i for i in interactions if i["exchange_ids"])
    assert owner["kind"] == "background"
    assert next(i for i in interactions if i["kind"] == "click")["exchange_ids"] == []


def test_clear_empties_history_and_hidden_count_then_announces_it(harness: Harness) -> None:
    harness.feed(click(T0), request("cart", f"{API}/cart", T0 + 10), request("t", TRACKING, T0 + 20))
    assert harness.get("/api/status")["hidden_count"] == 1

    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        post(harness, "/api/clear")
        assert harness.receive(ws) == {"type": "cleared", "data": {}}
        assert harness.receive(ws)["data"]["hidden_count"] == 0

    assert history(harness)["interactions"] == []
    assert history(harness)["exchanges"] == []
    assert harness.get("/api/status")["hidden_count"] == 0


def test_after_clear_new_traffic_starts_fresh(harness: Harness) -> None:
    harness.feed(click(T0), request("old", f"{API}/old", T0 + 10))
    post(harness, "/api/clear")
    harness.feed(
        answered("old", T0 + 50),  # คำตอบของ Exchange ที่ล้างไปแล้ว: ไม่ทำให้มันกลับมา
        request("new", f"{API}/new", T0 + 100),  # ยังอยู่ใน window ของคลิกที่ล้างไปแล้ว
    )

    assert urls(harness) == [f"{API}/new"]
    assert [interaction["kind"] for interaction in history(harness)["interactions"]] == ["background"]


def test_clear_while_paused_stays_paused(harness: Harness) -> None:
    post(harness, "/api/pause")
    assert post(harness, "/api/clear")["paused"] is True


def test_max_exchanges_drops_the_oldest_first() -> None:
    with build_harness(max_exchanges=3) as harness:
        harness.feed(*(request(f"r{n}", f"{API}/item/{n}", T0 + n * 10_000) for n in range(5)))

        assert urls(harness) == [f"{API}/item/2", f"{API}/item/3", f"{API}/item/4"]
        assert harness.client.get("/api/exchanges/ex_0001").status_code == 404
