"""Redactor: ซ่อนข้อมูลลับก่อนที่ Exchange จะถูกเก็บ (ปิดไม่ได้)

สอนแนวคิด: single responsibility — class นี้มีหน้าที่เดียว คือ "ทำให้ข้อมูลปลอดภัย"
ส่วนอื่นของโปรแกรมจึงไม่ต้องกังวลเรื่องนี้เลย
"""

import json
import re
from typing import Any
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from inspector.models import BodyKind

SENSITIVE_KEY = re.compile(r"pass|token|secret|session|otp|card|phone|mobile|email|address|citizen|id_card", re.I)
SENSITIVE_HEADER_NAMES = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization"})
SENSITIVE_HEADER_PART = re.compile(r"token|session|auth|csrf|key|secret", re.I)


def is_sensitive_key(key: str) -> bool:
    """key ใน JSON, form หรือ query ที่ต้องซ่อนค่า"""
    return SENSITIVE_KEY.search(key) is not None


def is_sensitive_header(name: str) -> bool:
    """header ที่ต้องซ่อนค่า"""
    return name.lower() in SENSITIVE_HEADER_NAMES or SENSITIVE_HEADER_PART.search(name) is not None


MASK = "••••"


class Redactor:
    """ซ่อนค่าลับใน headers, URL, query, JSON body และ form body

    ทุกเมธอดเป็น pure function: รับค่าเดิม คืนค่าใหม่ ไม่แก้ของเดิม
    """

    def headers(self, headers: dict[str, str]) -> dict[str, str]:
        """ซ่อนค่าของ header ที่อ่อนไหว (cookie เหลือชื่อไว้)"""
        return {name: self._header_value(name, value) for name, value in headers.items()}

    def url(self, url: str) -> str:
        """ซ่อนค่าใน query และรหัสผ่านใน URL แบบ `user:pass@host`"""
        parts = urlsplit(url)
        netloc = parts.netloc
        if parts.password is not None:
            userinfo, _, host = netloc.rpartition("@")
            netloc = f"{userinfo.partition(':')[0]}:{MASK}@{host}"
        return urlunsplit(parts._replace(netloc=netloc, query=self._pairs(parts.query)))

    def query(self, query: dict[str, list[str]]) -> dict[str, list[str]]:
        return {key: [MASK] * len(values) if is_sensitive_key(key) else values for key, values in query.items()}

    def body(self, body: str | None, kind: BodyKind) -> tuple[str | None, bool]:
        """ซ่อนค่าใน body คืน (body ใหม่, ยังไม่ได้ตรวจหรือไม่)"""
        if body is None or kind == "none":
            return body, False
        if kind == "form":
            return self._pairs(body), False
        if kind == "json":
            try:
                data = json.loads(body)
            except ValueError:
                return body, True  # parse ไม่ได้ ส่งผ่านไปแต่บอกว่ายังไม่ได้ตรวจ
            masked = self._json(data)
            return (body if masked == data else json.dumps(masked, ensure_ascii=False)), False
        return body, True  # text หรือ binary: เดารูปแบบไม่ได้

    def _header_value(self, name: str, value: str) -> str:
        lowered = name.lower()
        if lowered == "cookie":
            return "; ".join(self._cookie(part.strip()) for part in value.split(";") if part.strip())
        if lowered == "set-cookie":
            return "\n".join(self._set_cookie(line) for line in value.split("\n"))
        if is_sensitive_header(name):
            return f"{MASK} (ซ่อนไว้, {len(value)} ตัวอักษร)"
        return value

    @staticmethod
    def _cookie(pair: str) -> str:
        return f"{pair.partition('=')[0]}={MASK}"

    def _set_cookie(self, line: str) -> str:
        first, separator, attributes = line.partition(";")
        return self._cookie(first.strip()) + separator + attributes

    @staticmethod
    def _pairs(text: str) -> str:
        """ซ่อนค่าใน `a=1&b=2` (query หรือ form) โดยคง encoding เดิมของส่วนที่ไม่ได้ซ่อน"""
        pieces = []
        for piece in text.split("&"):
            raw_key, has_value, _ = piece.partition("=")
            if has_value and is_sensitive_key(unquote_plus(raw_key)):
                piece = f"{raw_key}={MASK}"
            pieces.append(piece)
        return "&".join(pieces)

    def _json(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: MASK if is_sensitive_key(k) else self._json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json(item) for item in value]
        return value
