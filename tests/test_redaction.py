"""Redaction: ค่าลับจริงต้องไม่ไปถึง store, REST หรือ WebSocket เลย"""

import json

from conftest import Harness

from inspector.capture_events import RequestStarted, ResponseReceived

SESSION = "s3cr3t-session-value-abc123"
BEARER = "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
CSRF = "csrf-ZZZ-999"
PASSWORD = "hunter2-p@ss"
QUERY_TOKEN = "qtok-777"
PHONE = "0812345678"


def login_request(**overrides: object) -> RequestStarted:
    fields: dict[str, object] = dict(
        request_key="r1",
        tab_id="tab-1",
        page_url=f"https://shop.example/account?session={SESSION}",
        ts=1000.0,
        method="POST",
        url=f"https://shop.example/api/login?token={QUERY_TOKEN}&lang=th",
        resource_type="fetch",
        headers={
            "Content-Type": "application/json",
            "Cookie": f"PHPSESSID={SESSION}; theme=dark",
            "Authorization": BEARER,
            "X-CSRF-Token": CSRF,
            "Accept": "application/json",
        },
        post_data=json.dumps(
            {"user": {"login": "somchai", "password": PASSWORD, "contact": {"phone": PHONE}}, "remember": True}
        ),
    )
    fields.update(overrides)
    return RequestStarted(**fields)  # type: ignore[arg-type]


def test_no_secret_reaches_rest_or_websocket(harness: Harness) -> None:
    with harness.client.websocket_connect("/ws") as ws:
        harness.receive(ws)  # snapshot
        harness.feed(login_request())
        broadcast = json.dumps([harness.receive(ws), harness.receive(ws)], ensure_ascii=False)
    stored = json.dumps(harness.get("/api/exchanges/ex_0001"), ensure_ascii=False)

    for secret in [SESSION, BEARER, CSRF, PASSWORD, QUERY_TOKEN, PHONE]:
        assert secret not in broadcast
        assert secret not in stored


def test_request_parts_are_redacted_but_still_readable(harness: Harness) -> None:
    harness.feed(login_request())

    request = harness.get("/api/exchanges/ex_0001")["request"]
    headers = request["headers"]
    assert headers["Authorization"] == f"•••• (ซ่อนไว้, {len(BEARER)} ตัวอักษร)"
    assert headers["X-CSRF-Token"] == f"•••• (ซ่อนไว้, {len(CSRF)} ตัวอักษร)"
    assert headers["Cookie"] == "PHPSESSID=••••; theme=••••"  # เห็นชื่อ cookie ไว้สอนเรื่อง session
    assert headers["Accept"] == "application/json"
    assert request["query"] == {"token": ["••••"], "lang": ["th"]}
    assert request["url"] == "https://shop.example/api/login?token=••••&lang=th"
    assert json.loads(request["body"]) == {
        "user": {"login": "somchai", "password": "••••", "contact": {"phone": "••••"}},
        "remember": True,
    }
    assert request["body_unscanned"] is False


def test_page_url_is_redacted(harness: Harness) -> None:
    harness.feed(login_request())

    assert harness.get("/api/exchanges/ex_0001")["page_url"] == "https://shop.example/account?session=••••"


def test_sensitive_key_hides_whole_nested_value(harness: Harness) -> None:
    harness.feed(login_request(post_data=json.dumps({"address": {"line1": "99 ถนนพหลโยธิน", "zip": "10900"}})))

    body = harness.get("/api/exchanges/ex_0001")["request"]["body"]
    assert json.loads(body) == {"address": "••••"}


def test_form_body_is_redacted(harness: Harness) -> None:
    harness.feed(
        login_request(
            headers={"content-type": "application/x-www-form-urlencoded"},
            post_data=f"username=somchai&password={PASSWORD}&otp=123456",
        )
    )

    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert request["body"] == "username=somchai&password=••••&otp=••••"
    assert request["body_unscanned"] is False


def test_response_secrets_are_redacted(harness: Harness) -> None:
    harness.feed(
        login_request(),
        ResponseReceived(
            request_key="r1",
            ts=1100.0,
            status=200,
            status_text="OK",
            headers={
                "content-type": "application/json",
                "set-cookie": f"PHPSESSID={SESSION}; Path=/; HttpOnly\nlang=th; Path=/",
            },
            body=json.dumps({"access_token": "at-123", "profile": {"email": "a@b.co", "name": "สมชาย"}}),
        ),
    )

    response = harness.get("/api/exchanges/ex_0001")["response"]
    assert response["headers"]["set-cookie"] == "PHPSESSID=••••; Path=/; HttpOnly\nlang=••••; Path=/"
    assert json.loads(response["body"]) == {"access_token": "••••", "profile": {"email": "••••", "name": "สมชาย"}}
    assert response["body_unscanned"] is False


def test_plain_text_body_passes_through_flagged_unscanned(harness: Harness) -> None:
    harness.feed(login_request(headers={"content-type": "text/plain"}, post_data="hello token=abc"))

    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert request["body"] == "hello token=abc"
    assert request["body_unscanned"] is True


def test_broken_json_does_not_crash_and_is_flagged_unscanned(harness: Harness) -> None:
    harness.feed(login_request(post_data='{"password": "oops"'))

    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert request["body_unscanned"] is True


def test_request_without_body_counts_as_scanned(harness: Harness) -> None:
    harness.feed(login_request(method="GET", post_data=None))

    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert request["body"] is None
    assert request["body_unscanned"] is False


def test_credentials_in_url_are_redacted(harness: Harness) -> None:
    harness.feed(login_request(url="https://admin:pa55word@shop.example/api/ping"))

    request = harness.get("/api/exchanges/ex_0001")["request"]
    assert "pa55word" not in request["url"]
    assert request["url"] == "https://admin:••••@shop.example/api/ping"


def test_urls_inside_referer_and_location_headers_are_redacted(harness: Harness) -> None:
    harness.feed(
        login_request(headers={"Referer": f"https://shop.example/account?session={SESSION}&tab=1"}),
        ResponseReceived(
            request_key="r1", ts=1100.0, status=302, status_text="Found",
            headers={"Location": f"/callback?access_token={QUERY_TOKEN}"},
        ),
    )

    exchange = harness.get("/api/exchanges/ex_0001")
    assert exchange["request"]["headers"]["Referer"] == "https://shop.example/account?session=••••&tab=1"
    assert exchange["response"]["headers"]["Location"] == "/callback?access_token=••••"


def test_url_fragment_is_redacted(harness: Harness) -> None:
    harness.feed(
        login_request(
            url=f"https://shop.example/cb#access_token={QUERY_TOKEN}&state=xyz",
            page_url=f"https://shop.example/#/login?token={QUERY_TOKEN}",
        )
    )

    exchange = harness.get("/api/exchanges/ex_0001")
    assert exchange["request"]["url"] == "https://shop.example/cb#access_token=••••&state=xyz"
    assert exchange["page_url"] == "https://shop.example/#/login?token=••••"


def test_duplicate_json_keys_cannot_smuggle_a_secret(harness: Harness) -> None:
    harness.feed(login_request(post_data=f'{{"password": "{PASSWORD}", "password": "••••"}}'))

    assert PASSWORD not in harness.get("/api/exchanges/ex_0001")["request"]["body"]


def test_header_names_matching_sensitive_keys_are_redacted(harness: Harness) -> None:
    harness.feed(login_request(headers={"X-Password": PASSWORD, "X-User-Email": "a@b.co"}))

    headers = harness.get("/api/exchanges/ex_0001")["request"]["headers"]
    assert PASSWORD not in json.dumps(headers)
    assert "a@b.co" not in json.dumps(headers)


def test_exchange_reports_whether_anything_was_redacted(harness: Harness) -> None:
    harness.feed(
        login_request(),
        login_request(
            request_key="r2", headers={"accept": "application/json"}, post_data=None,
            url="https://shop.example/api/ping", page_url="https://shop.example/",
        ),
    )

    assert harness.get("/api/exchanges/ex_0001")["has_redactions"] is True
    assert harness.get("/api/exchanges/ex_0002")["has_redactions"] is False
