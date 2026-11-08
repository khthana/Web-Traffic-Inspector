"""กฎของ Redaction: ชื่อไหนนับว่าอ่อนไหว (test แบบตาราง)"""

import pytest

from inspector.redactor import is_sensitive_header, is_sensitive_key


@pytest.mark.parametrize(
    "key",
    [
        "password", "Passwd", "new_password", "access_token", "refreshToken", "client_secret",
        "sessionId", "otp", "otp_code", "card_number", "creditCard", "phone", "mobileNo",
        "email", "E-Mail_Address", "address", "shipping_address", "citizen_id", "id_card",
        "passenger",  # ซ่อนเกินได้ ตามที่ตกลงไว้
    ],
)
def test_sensitive_keys_are_detected(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["id", "sku", "qty", "page", "lang", "status", "data", "price", "name"])
def test_ordinary_keys_are_kept(key: str) -> None:
    assert not is_sensitive_key(key)


@pytest.mark.parametrize(
    "name",
    [
        "Cookie", "set-cookie", "Authorization", "proxy-authorization", "X-CSRF-Token",
        "x-api-key", "X-Session-Id", "x-auth-user", "x-client-secret", "x-xsrf-token",
    ],
)
def test_sensitive_headers_are_detected(name: str) -> None:
    assert is_sensitive_header(name)


@pytest.mark.parametrize("name", ["content-type", "accept", "user-agent", "cache-control", "keep-alive"])
def test_ordinary_headers_are_kept(name: str) -> None:
    assert not is_sensitive_header(name)
