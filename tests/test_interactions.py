"""การจัด Exchange เข้า Interaction ตามสาเหตุ (คลิก, Navigation, เบื้องหลัง) ผ่าน seam หลัก"""

from typing import Any

from conftest import Harness

from inspector.capture_events import ClickCaptured, NavigationOccurred, RequestStarted
from inspector.models import ElementInfo

T0 = 1_000_000.0
PAGE = "https://www.advice.co.th/"


def click(ts: float, tab_id: str = "tab-1", text: str = "ใส่ตะกร้า", tag: str = "button", href: str | None = None) -> ClickCaptured:
    element = ElementInfo(tag=tag, text=text, selector=f"{tag}.btn", href=href)
    return ClickCaptured(tab_id=tab_id, page_url=PAGE, ts=ts, element=element)


def navigation(ts: float, url: str, tab_id: str = "tab-1") -> NavigationOccurred:
    return NavigationOccurred(tab_id=tab_id, url=url, ts=ts)


_keys = iter(range(1, 10_000))


def request(ts: float, path: str = "/api/cart/add", tab_id: str = "tab-1") -> RequestStarted:
    return RequestStarted(
        request_key=f"r{next(_keys)}", tab_id=tab_id, page_url=PAGE, ts=ts,
        method="POST", url=f"https://www.advice.co.th{path}", resource_type="fetch",
    )


def interactions(harness: Harness) -> list[dict[str, Any]]:
    return list(harness.get("/api/interactions")["interactions"])


def grouping(harness: Harness) -> list[tuple[str, list[str]]]:
    """(ชนิด, path ของ Exchange) ของทุก Interaction เรียงตามเวลาที่เกิด"""
    paths = {e["id"]: e["request"]["path"] for e in harness.get("/api/interactions")["exchanges"]}
    return [(i["kind"], [paths[x] for x in i["exchange_ids"]]) for i in interactions(harness)]


def test_click_opens_interaction_before_its_exchanges_arrive(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(click(T0), request(T0 + 120))
        opened = harness.receive(ws)
        exchange = harness.receive(ws)

    assert opened["type"] == "interaction.new"
    assert opened["data"]["kind"] == "click"
    assert opened["data"]["click"]["element"]["text"] == "ใส่ตะกร้า"
    assert opened["data"]["page_url"] == PAGE
    assert exchange["type"] == "exchange.new"
    assert exchange["data"]["interaction_id"] == opened["data"]["id"]


def test_exchanges_inside_correlation_window_join_the_click(harness: Harness) -> None:
    harness.feed(click(T0), request(T0 + 10, "/api/a"), request(T0 + 1500, "/api/b"), request(T0 + 1501, "/api/poll"))

    assert grouping(harness) == [("click", ["/api/a", "/api/b"]), ("background", ["/api/poll"])]


def test_new_click_opens_a_new_interaction_even_inside_the_window(harness: Harness) -> None:
    harness.feed(click(T0, text="ใส่ตะกร้า"), request(T0 + 100, "/api/a"), click(T0 + 300, text="ชำระเงิน"), request(T0 + 400, "/api/b"))

    assert grouping(harness) == [("click", ["/api/a"]), ("click", ["/api/b"])]
    assert [i["click"]["element"]["text"] for i in interactions(harness)] == ["ใส่ตะกร้า", "ชำระเงิน"]


def test_clicks_are_correlated_per_tab(harness: Harness) -> None:
    harness.feed(click(T0, tab_id="tab-1"), request(T0 + 100, "/api/other-tab", tab_id="tab-2"))

    assert grouping(harness) == [("click", []), ("background", ["/api/other-tab"])]
    assert interactions(harness)[1]["tab_id"] == "tab-2"


def test_click_without_exchanges_is_kept_as_empty_interaction(harness: Harness) -> None:
    harness.feed(click(T0))

    assert grouping(harness) == [("click", [])]


def test_navigation_from_a_click_extends_the_same_interaction(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(click(T0, tag="a", text="โน้ตบุ๊ก", href="https://www.advice.co.th/product/notebooks"))
        harness.receive(ws)  # interaction.new
        harness.feed(navigation(T0 + 800, "https://www.advice.co.th/product/notebooks?token=SECRET"))
        updated = harness.receive(ws)

    assert updated["type"] == "interaction.update"
    assert updated["data"]["navigated_to"] == "https://www.advice.co.th/product/notebooks?token=••••"

    harness.feed(request(T0 + 800 + 5000, "/api/category"), request(T0 + 800 + 5001, "/api/poll"))
    assert grouping(harness) == [("click", ["/api/category"]), ("background", ["/api/poll"])]


def test_navigation_without_click_opens_page_load(harness: Harness) -> None:
    harness.feed(
        click(T0),
        navigation(T0 + 1501, "https://www.advice.co.th/product/notebooks"),  # เลย window ของคลิกแล้ว
        request(T0 + 1501 + 5000, "/api/category"),
        request(T0 + 1501 + 5001, "/api/poll"),
    )

    assert grouping(harness) == [("click", []), ("page_load", ["/api/category"]), ("background", ["/api/poll"])]
    assert interactions(harness)[1]["page_url"] == "https://www.advice.co.th/product/notebooks"


def test_background_interaction_collects_until_click_or_navigation(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(request(T0, "/api/poll-1"))
        assert harness.receive(ws)["type"] == "interaction.new"
        assert harness.receive(ws)["type"] == "exchange.new"
        harness.feed(request(T0 + 30_000, "/api/poll-2"))
        updated = harness.receive(ws)
        assert harness.receive(ws)["type"] == "exchange.new"

    assert updated["type"] == "interaction.update"
    assert updated["data"]["kind"] == "background"
    assert len(updated["data"]["exchange_ids"]) == 2

    harness.feed(
        request(T0 + 1000, "/api/other-tab", tab_id="tab-2"),
        click(T0 + 60_000),
        request(T0 + 70_000, "/api/poll-3"),
        navigation(T0 + 80_000, PAGE),
        request(T0 + 90_000, "/api/poll-4"),
    )
    assert grouping(harness) == [
        ("background", ["/api/poll-1", "/api/poll-2"]),
        ("background", ["/api/other-tab"]),
        ("click", []),
        ("background", ["/api/poll-3"]),
        ("page_load", []),
        ("background", ["/api/poll-4"]),
    ]


def test_click_urls_are_redacted(harness: Harness) -> None:
    harness.feed(
        ClickCaptured(
            tab_id="tab-1", page_url="https://shop.example/?session=SECRET", ts=T0,
            element=ElementInfo(tag="a", text="ถัดไป", selector="a", href="https://shop.example/next?token=SECRET"),
        )
    )

    interaction = interactions(harness)[0]
    assert interaction["page_url"] == "https://shop.example/?session=••••"
    assert interaction["click"]["page_url"] == "https://shop.example/?session=••••"
    assert interaction["click"]["element"]["href"] == "https://shop.example/next?token=••••"


def test_correlation_window_edges(harness: Harness) -> None:
    harness.feed(
        click(T0),
        request(T0 - 1, "/api/before-click"),  # มาถึงหลังคลิก แต่เริ่มก่อนคลิก จึงไม่ใช่ผลของคลิก
        request(T0 + 1500, "/api/edge"),
        navigation(T0 + 1500 + 1, "https://www.advice.co.th/late"),  # เลย window ของคลิกแล้ว
    )

    assert grouping(harness) == [("click", ["/api/edge"]), ("background", ["/api/before-click"]), ("page_load", [])]


def test_refresh_after_click_navigation_opens_page_load(harness: Harness) -> None:
    harness.feed(
        click(T0, tag="a", text="โน้ตบุ๊ก"),
        navigation(T0 + 500, "https://www.advice.co.th/product/notebooks"),
        navigation(T0 + 3000, "https://www.advice.co.th/product/notebooks"),  # กด refresh เอง
        request(T0 + 3100, "/api/category"),
    )

    assert grouping(harness) == [("click", []), ("page_load", ["/api/category"])]
    assert interactions(harness)[0]["navigated_to"] == "https://www.advice.co.th/product/notebooks"


def test_evicted_background_interaction_is_replaced_not_revived(harness: Harness) -> None:
    harness.feed(request(T0, "/api/poll-1", tab_id="tab-1"))
    harness.feed(*[click(T0 + n, tab_id="tab-2") for n in range(1, 501)])  # ดัน Background ของ tab-1 ออกจาก store

    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(request(T0 + 1000, "/api/poll-2", tab_id="tab-1"))
        opened = harness.receive(ws)
        exchange = harness.receive(ws)

    assert opened["type"] == "interaction.new"  # UI ได้การ์ดใหม่ ไม่ใช่อัปเดตการ์ดที่ไม่มีอยู่แล้ว
    assert exchange["data"]["interaction_id"] == opened["data"]["id"]
    assert len(interactions(harness)) == 500
    assert grouping(harness)[-1] == ("background", ["/api/poll-2"])


def test_status_tells_ui_the_correlation_window(harness: Harness) -> None:
    assert harness.get("/api/status")["correlation_window_ms"] == 1500
