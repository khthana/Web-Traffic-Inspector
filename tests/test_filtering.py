"""การกรอง: Blocklist, Focus rule ของ Preset, Hidden exchange และ `GET/PUT /api/filters` ผ่าน seam หลัก"""

import json
from typing import Any

from conftest import Harness, build_harness

from inspector.capture_events import ClickCaptured, RequestStarted
from inspector.filters import PRESETS_DIR, load_presets
from inspector.models import ElementInfo

T0 = 1_000_000.0
PAGE = "https://www.advice.co.th/"
_keys = iter(range(1, 10_000))


def request(url: str, ts: float = T0, body: str | None = None) -> RequestStarted:
    return RequestStarted(
        request_key=f"f{next(_keys)}", tab_id="tab-1", page_url=PAGE, ts=ts, method="POST", url=url,
        resource_type="fetch", headers={"content-type": "application/json"} if body else {}, post_data=body,
    )


def exchanges(harness: Harness) -> dict[str, dict[str, Any]]:
    """path → Exchange (ทั้งที่มองเห็นและที่ซ่อน)"""
    return {e["request"]["url"]: e for e in harness.get("/api/interactions")["exchanges"]}


def hidden_reasons(harness: Harness) -> dict[str, str | None]:
    return {url: e["hidden_reason"] for url, e in exchanges(harness).items()}


def put_filters(harness: Harness, body: dict[str, Any], expected: int = 200) -> Any:
    response = harness.client.put("/api/filters", json=body)
    assert response.status_code == expected, response.text
    return response.json()


ANALYTICS = "https://region1.google-analytics.com/g/collect?v=2"
CART = "https://www.advice.co.th/_advice-api/cart/add"
SEARCH = "https://www.advice.co.th/api/search"
ADVICE_PAGE_DATA = "https://www.advice.co.th/product/data"
OTHER_API = "https://api.other.example/items"


def test_blocklist_hides_tracking_with_its_host_as_the_reason(harness: Harness) -> None:
    harness.feed(
        request(ANALYTICS),
        request("https://www.clarity.ms/collect"),
        request("https://www.advice.co.th/cdn-cgi/rum"),
        request("https://beacon-x1.a.run.app/events"),
        request("https://shop-x1.a.run.app/api/items"),
        request(CART),
    )

    assert hidden_reasons(harness) == {
        ANALYTICS: "tracking: region1.google-analytics.com",
        "https://www.clarity.ms/collect": "tracking: www.clarity.ms",
        "https://www.advice.co.th/cdn-cgi/rum": "tracking: www.advice.co.th",
        "https://beacon-x1.a.run.app/events": "tracking: beacon-x1.a.run.app",
        "https://shop-x1.a.run.app/api/items": None,
        CART: None,
    }
    assert exchanges(harness)[ANALYTICS]["hidden"] is True
    assert exchanges(harness)[CART]["hidden"] is False
    assert harness.get("/api/status")["hidden_count"] == 4


def test_hidden_exchange_is_announced_with_new_hidden_count(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(request(ANALYTICS))
        messages = [harness.receive(ws) for _ in range(3)]

    exchange = next(m for m in messages if m["type"] == "exchange.new")
    status = next(m for m in messages if m["type"] == "status")
    assert exchange["data"]["hidden_reason"] == "tracking: region1.google-analytics.com"
    assert status["data"]["hidden_count"] == 1


def test_hidden_exchange_still_joins_the_click_interaction(harness: Harness) -> None:
    element = ElementInfo(tag="button", text="ใส่ตะกร้า", selector="button#add")
    harness.feed(ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=T0, element=element), request(ANALYTICS, ts=T0 + 50))

    [interaction] = harness.get("/api/interactions")["interactions"]
    assert interaction["exchange_ids"] == [exchanges(harness)[ANALYTICS]["id"]]


def test_focus_rule_of_advice_preset_hides_everything_else(harness: Harness) -> None:
    put_filters(harness, {"selected": "advice"})
    harness.feed(request(CART), request(SEARCH), request(ADVICE_PAGE_DATA), request(OTHER_API), request(ANALYTICS))

    assert hidden_reasons(harness) == {
        CART: None,
        SEARCH: None,
        ADVICE_PAGE_DATA: "นอกโฟกัส: preset advice",
        OTHER_API: "นอกโฟกัส: preset advice",
        ANALYTICS: "tracking: region1.google-analytics.com",  # ติดทั้งสองแบบ: ใช้ tracking
    }


def test_changing_preset_recomputes_every_exchange_and_sends_a_snapshot(harness: Harness) -> None:
    harness.feed(request(CART), request(OTHER_API), request(ANALYTICS))
    assert harness.get("/api/status")["hidden_count"] == 1

    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot ตอนเชื่อม
        put_filters(harness, {"selected": "advice"})
        snapshot = harness.receive(ws)

    assert snapshot["type"] == "snapshot"
    assert snapshot["data"]["status"]["preset"] == "advice"
    assert snapshot["data"]["status"]["hidden_count"] == 2
    assert {e["request"]["url"]: e["hidden"] for e in snapshot["data"]["exchanges"]} == {
        CART: False, OTHER_API: True, ANALYTICS: True,
    }

    put_filters(harness, {"selected": "all"})
    assert hidden_reasons(harness)[OTHER_API] is None
    assert harness.get("/api/status")["hidden_count"] == 1


def test_hidden_exchanges_never_push_visible_ones_out_of_memory() -> None:
    with build_harness(max_exchanges=2) as harness:
        harness.feed(request(CART), request(SEARCH))
        harness.feed(*(request(f"https://www.clarity.ms/collect?n={n}") for n in range(5)))

        urls = list(exchanges(harness))
        assert urls[:2] == [CART, SEARCH]
        assert len(urls) == 4  # buffer ละ 2
        assert harness.get("/api/status")["hidden_count"] == 5  # รวมตัวที่หลุดจาก buffer ไปแล้ว


def test_preset_from_command_line_is_selected_at_start() -> None:
    with build_harness(preset="advice") as harness:
        assert harness.get("/api/status")["preset"] == "advice"
        harness.feed(request(OTHER_API))
        assert hidden_reasons(harness)[OTHER_API] == "นอกโฟกัส: preset advice"


def test_get_filters_lists_presets_for_the_dropdown(harness: Harness) -> None:
    filters = harness.get("/api/filters")

    assert filters["selected"] == "all"
    assert filters["choices"] == [
        {"name": "all", "label": "ทุกเว็บ"},
        {"name": "advice", "label": "advice.co.th"},
        {"name": "custom", "label": "กำหนดเอง…"},
    ]
    assert filters["rules"]["focus_hosts"] == []
    assert "google-analytics.com" in filters["base_blocklist"]


def test_custom_preset_starts_as_a_copy_of_the_selected_one(harness: Harness) -> None:
    put_filters(harness, {"selected": "advice"})
    filters = put_filters(harness, {"selected": "custom"})

    assert filters["selected"] == "custom"
    assert filters["rules"]["focus_hosts"] == ["www.advice.co.th"]
    harness.feed(request(OTHER_API))
    assert hidden_reasons(harness)[OTHER_API] == "นอกโฟกัส: preset custom"


def test_editing_custom_rules_refilters_in_memory(harness: Harness) -> None:
    harness.feed(request(CART), request(OTHER_API))
    rules = {"focus_hosts": ["api.other.example"], "block_path_prefixes": ["/items/secret-beacon"]}
    filters = put_filters(harness, {"selected": "custom", "rules": rules})

    assert filters["rules"]["focus_hosts"] == ["api.other.example"]
    assert hidden_reasons(harness) == {CART: "นอกโฟกัส: preset custom", OTHER_API: None}
    harness.feed(request("https://api.other.example/items/secret-beacon"))
    assert hidden_reasons(harness)["https://api.other.example/items/secret-beacon"] == "tracking: api.other.example"
    assert not any(PRESETS_DIR.glob("custom*"))  # ไม่เขียนลงดิสก์


def test_extra_redaction_keys_can_only_be_added(harness: Harness) -> None:
    harness.feed(request(CART, body='{"sku": "NB-001"}'))
    put_filters(harness, {"selected": "custom", "rules": {"redact_keys": ["sku"]}})
    harness.feed(request(SEARCH, body='{"sku": "NB-002"}'))

    assert json.loads(exchanges(harness)[CART]["request"]["body"]) == {"sku": "NB-001"}  # ใช้กับของใหม่เท่านั้น
    assert json.loads(exchanges(harness)[SEARCH]["request"]["body"]) == {"sku": "••••"}

    filters = put_filters(harness, {"selected": "custom", "rules": {"redact_keys": []}})
    assert filters["rules"]["redact_keys"] == ["sku"]  # ลดไม่ได้


def test_invalid_filter_changes_are_rejected(harness: Harness) -> None:
    put_filters(harness, {"selected": "nope"}, expected=422)
    put_filters(harness, {"selected": "advice", "rules": {"focus_hosts": ["x"]}}, expected=422)
    assert harness.get("/api/filters")["selected"] == "all"


def test_presets_live_in_json_files_and_there_is_no_filters_json() -> None:
    presets = load_presets(PRESETS_DIR)
    assert set(presets) == {"all", "advice"}
    assert presets["advice"].focus_path_prefixes == ["/_advice-api/", "/api/"]
    assert not (PRESETS_DIR.parent / "filters.json").exists()


def test_blocklist_host_must_match_whole_labels(harness: Harness) -> None:
    harness.feed(request("https://notclarity.ms/api"), request("https://facebook.com.example/api"))
    assert set(hidden_reasons(harness).values()) == {None}


def test_changing_preset_never_drops_stored_exchanges() -> None:
    with build_harness(max_exchanges=2, preset="advice") as harness:
        harness.feed(request(CART), request(SEARCH), request(OTHER_API), request(ADVICE_PAGE_DATA))
        put_filters(harness, {"selected": "all"})  # ตัวที่เคยซ่อนย้ายมาฝั่งที่มองเห็น: buffer ล้นชั่วคราวได้

        assert list(exchanges(harness)) == [CART, SEARCH, OTHER_API, ADVICE_PAGE_DATA]
        put_filters(harness, {"selected": "advice"})
        assert list(exchanges(harness)) == [CART, SEARCH, OTHER_API, ADVICE_PAGE_DATA]


def test_dropped_tracking_stays_in_hidden_count_but_dropped_out_of_focus_follows_the_preset() -> None:
    with build_harness(max_exchanges=2, preset="advice") as harness:
        harness.feed(*(request(f"{OTHER_API}?n={n}") for n in range(3)))
        harness.feed(*(request(f"https://www.clarity.ms/collect?n={n}") for n in range(3)))
        assert harness.get("/api/status")["hidden_count"] == 6

        put_filters(harness, {"selected": "all"})
        assert harness.get("/api/status")["hidden_count"] == 3  # tracking 2 ตัวใน buffer + 1 ตัวที่หลุดไปแล้ว


def test_other_clients_learn_that_custom_rules_changed(harness: Harness) -> None:
    put_filters(harness, {"selected": "custom"})
    before = harness.get("/api/status")["filters_version"]
    put_filters(harness, {"selected": "custom", "rules": {"focus_hosts": ["api.other.example"]}})
    assert harness.get("/api/status")["filters_version"] > before
