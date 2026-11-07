"""Redactor: ซ่อนข้อมูลลับก่อนที่ Exchange จะถูกเก็บ (ปิดไม่ได้)

ค่าจริงไม่เคยถูกเก็บหรือส่งออกไป หน้า Inspector, export และ curl จึงเห็นแต่ `••••`
"""

import json
import re
from typing import Any, NamedTuple
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from inspector.models import BodyKind

REDACTED = "••••"
SENSITIVE_KEY = re.compile(r"pass|token|secret|session|otp|card|phone|mobile|email|address|citizen|id_card", re.I)
SENSITIVE_HEADER_NAMES = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization"})
SENSITIVE_HEADER_PART = re.compile(r"token|session|auth|csrf|key|secret", re.I)
URL_HEADER_NAMES = frozenset({"referer", "location", "content-location"})


def is_sensitive_key(key: str) -> bool:
    """key ใน JSON, form หรือ query ที่ต้องซ่อนค่า"""
    return SENSITIVE_KEY.search(key) is not None


def is_sensitive_header(name: str) -> bool:
    """header ที่ต้องซ่อนค่าทั้งก้อน (ชื่อที่ตรงกฎของ key ก็นับด้วย เช่น `X-Password`)"""
    return (
        name.lower() in SENSITIVE_HEADER_NAMES
        or SENSITIVE_HEADER_PART.search(name) is not None
        or is_sensitive_key(name)
    )


class RedactedBody(NamedTuple):
    """ผลของการซ่อนค่าใน body"""

    text: str | None
    unscanned: bool  # True = เดารูปแบบไม่ได้ จึงไม่ได้ตรวจหาข้อมูลลับ


class Redactor:
    """ซ่อนค่าลับใน headers, URL, query, JSON body และ form body

    สอนแนวคิด: single responsibility — class นี้มีหน้าที่เดียวคือ "ทำให้ข้อมูลปลอดภัย"
    ทุกเมธอดรับค่าเดิมแล้วคืนค่าใหม่ ไม่แก้ของเดิม จึงทดสอบง่าย
    """

    def headers(self, headers: dict[str, str]) -> dict[str, str]:
        """ซ่อนค่าของ header ที่อ่อนไหว (cookie เหลือชื่อไว้ header ที่เป็น URL ซ่อนเฉพาะ query)"""
        return {name: self._header_value(name, value) for name, value in headers.items()}

    def url(self, url: str) -> str:
        """ซ่อนค่าใน query, fragment และรหัสผ่านแบบ `user:pass@host`"""
        parts = urlsplit(url)
        netloc = parts.netloc
        if parts.password is not None:
            userinfo, _, host = netloc.rpartition("@")
            netloc = f"{userinfo.partition(':')[0]}:{REDACTED}@{host}"
        return urlunsplit(
            parts._replace(netloc=netloc, query=self._pairs(parts.query), fragment=self._fragment(parts.fragment))
        )

    def query(self, query: dict[str, list[str]]) -> dict[str, list[str]]:
        """ซ่อนค่าใน query ที่แยกเป็น dict แล้ว"""
        return {key: [REDACTED] * len(values) if is_sensitive_key(key) else values for key, values in query.items()}

    def body(self, body: str | None, kind: BodyKind) -> RedactedBody:
        """ซ่อนค่าใน body ตามชนิดของมัน"""
        if body is None or kind == "none":
            return RedactedBody(body, unscanned=False)
        if kind == "form":
            return RedactedBody(self._pairs(body), unscanned=False)
        if kind == "json":
            return self._json_body(body)
        return RedactedBody(body, unscanned=True)  # text หรือ binary: เดารูปแบบไม่ได้

    def _json_body(self, body: str) -> RedactedBody:
        try:
            data = json.loads(body)
        except ValueError:
            return RedactedBody(body, unscanned=True)  # parse ไม่ได้: ส่งผ่านไป แต่บอกว่ายังไม่ได้ตรวจ
        if not self._has_sensitive_key(data):
            return RedactedBody(body, unscanned=False)  # ไม่มีอะไรต้องซ่อน: คงรูปแบบเดิมไว้
        # เขียนใหม่จากค่าที่ parse แล้วเสมอ key ซ้ำในต้นฉบับจึงลักลอบส่งค่าจริงออกไปไม่ได้
        return RedactedBody(json.dumps(self._json(data), ensure_ascii=False), unscanned=False)

    def _header_value(self, name: str, value: str) -> str:
        lowered = name.lower()
        if lowered == "cookie":
            return "; ".join(self._cookie(part.strip()) for part in value.split(";") if part.strip())
        if lowered == "set-cookie":
            return "\n".join(self._set_cookie(line) for line in value.split("\n"))
        if lowered in URL_HEADER_NAMES:
            return self.url(value)
        if is_sensitive_header(name):
            return f"{REDACTED} (ซ่อนไว้, {len(value)} ตัวอักษร)"
        return value

    @staticmethod
    def _cookie(pair: str) -> str:
        return f"{pair.partition('=')[0]}={REDACTED}"

    def _set_cookie(self, line: str) -> str:
        first, separator, attributes = line.partition(";")
        return self._cookie(first.strip()) + separator + attributes

    def _fragment(self, fragment: str) -> str:
        """fragment อาจเป็น `a=1&b=2` (OAuth) หรือ `/route?a=1` (SPA)"""
        route, separator, query = fragment.rpartition("?")
        if separator:
            return f"{route}?{self._pairs(query)}"
        return self._pairs(fragment)

    @staticmethod
    def _pairs(text: str) -> str:
        """ซ่อนค่าใน `a=1&b=2` (query หรือ form) โดยคง encoding เดิมของส่วนที่ไม่ได้ซ่อน"""
        pieces = []
        for piece in text.split("&"):
            raw_key, has_value, _ = piece.partition("=")
            if has_value and is_sensitive_key(unquote_plus(raw_key)):
                piece = f"{raw_key}={REDACTED}"
            pieces.append(piece)
        return "&".join(pieces)

    def _json(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: REDACTED if is_sensitive_key(k) else self._json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json(item) for item in value]
        return value

    def _has_sensitive_key(self, value: Any) -> bool:
        if isinstance(value, dict):
            return any(is_sensitive_key(k) or self._has_sensitive_key(v) for k, v in value.items())
        if isinstance(value, list):
            return any(self._has_sensitive_key(item) for item in value)
        return False
