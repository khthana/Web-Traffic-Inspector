"""Redactor: ซ่อนข้อมูลลับก่อนที่ Exchange จะถูกเก็บ (ปิดไม่ได้)

ค่าจริงไม่เคยถูกเก็บหรือส่งออกไป หน้า Inspector, export และ curl จึงเห็นแต่ `••••`
"""

import json
import re
from typing import Any, NamedTuple
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from inspector.http_parts import describe_size, header
from inspector.models import BodyKind, HttpExchange, Interaction
from inspector.multipart import FormPart, parse_multipart

REDACTED = "••••"
SENSITIVE_KEY = re.compile(r"pass|token|secret|session|otp|card|phone|mobile|email|address|citizen|id_card", re.I)
SENSITIVE_HEADER_NAMES = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization"})
SENSITIVE_HEADER_PART = re.compile(r"token|session|auth|csrf|key|secret", re.I)
URL_HEADER_NAMES = frozenset({"referer", "location", "content-location"})


FILE_SUMMARY = "[ไฟล์: "


def to_valid_text(text: str) -> str:
    """แทน byte ที่ไม่ใช่ UTF-8 (เก็บมาเป็น surrogate) ด้วย � ข้อความจึงส่งเป็น JSON ได้เสมอ"""
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


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
    redacted: bool = False  # True = มีค่าลับใน body ถูกซ่อน (ย่อไฟล์แนบไม่นับ)


class Redactor:
    """ซ่อนค่าลับใน headers, URL, query, JSON body และ form body

    สอนแนวคิด: single responsibility — class นี้มีหน้าที่เดียวคือ "ทำให้ข้อมูลปลอดภัย"
    ทุกเมธอดรับค่าเดิมแล้วคืนค่าใหม่ ไม่แก้ของเดิม จึงทดสอบง่าย
    และ immutable object — เพิ่ม key ที่ต้องซ่อนได้ด้วย `with_extra_keys` ซึ่งคืน Redactor ตัวใหม่
    รายการพื้นฐานจึงลดไม่ได้
    """

    def __init__(self, extra_keys: tuple[str, ...] = ()) -> None:
        self.extra_keys = tuple(key for key in extra_keys if key.strip())
        pattern = "|".join(re.escape(key.strip()) for key in self.extra_keys)
        self._extra = re.compile(pattern, re.I) if pattern else None

    def with_extra_keys(self, keys: list[str] | tuple[str, ...]) -> "Redactor":
        """Redactor ตัวใหม่ที่ซ่อน key เพิ่มจาก Preset (ไม่แตะ Exchange ที่เก็บไปแล้ว)"""
        return Redactor(tuple(dict.fromkeys([*self.extra_keys, *keys])))

    def is_sensitive_key(self, key: str) -> bool:
        return is_sensitive_key(key) or (self._extra is not None and self._extra.search(key) is not None)

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
        return {key: [REDACTED] * len(values) if self.is_sensitive_key(key) else values for key, values in query.items()}

    def body(self, body: str | None, kind: BodyKind, content_type: str = "") -> RedactedBody:
        """ซ่อนค่าใน body ตามชนิดของมัน (multipart ต้องรู้ boundary จาก content-type)"""
        if body is None or kind == "none":
            return RedactedBody(body, unscanned=False)
        if kind == "form":
            text = self._pairs(body)
            return RedactedBody(text, unscanned=False, redacted=text != body)
        if kind == "json":
            return self._json_body(body)
        if kind == "multipart":
            return self._multipart_body(body, content_type)
        return RedactedBody(body, unscanned=True)  # text หรือ binary: เดารูปแบบไม่ได้

    def exchange(self, exchange: HttpExchange) -> HttpExchange:
        """ซ่อนค่าลับใน Exchange ทั้งตัว (ใช้กับ Exchange จากไฟล์ Recording) ค่าที่ซ่อนไว้แล้วคงเดิม"""
        request = exchange.request
        request_body = self.body(request.body, request.body_kind, header(request.headers, "content-type"))
        response = exchange.response
        if response is not None:
            response_body = self.body(response.body, response.body_kind, header(response.headers, "content-type"))
            response = response.model_copy(
                update={
                    "headers": self.headers(response.headers),
                    "body": response_body.text,
                    "body_unscanned": response_body.unscanned,
                }
            )
        return exchange.model_copy(
            update={
                "page_url": self.url(exchange.page_url),
                "request": request.model_copy(
                    update={
                        "url": self.url(request.url),
                        "query": self.query(request.query),
                        "headers": self.headers(request.headers),
                        "body": request_body.text,
                        "body_unscanned": request_body.unscanned,
                    }
                ),
                "response": response,
            }
        )

    def interaction(self, interaction: Interaction) -> Interaction:
        """ซ่อนค่าลับใน URL ทุกตัวของ Interaction (หน้า, ปลายทางที่เปิด, href ของ element ที่คลิก)"""
        click = interaction.click
        if click is not None:
            href = click.element.href
            element = click.element.model_copy(update={"href": None if href is None else self.url(href)})
            click = click.model_copy(update={"page_url": self.url(click.page_url), "element": element})
        navigated_to = interaction.navigated_to
        return interaction.model_copy(
            update={
                "page_url": self.url(interaction.page_url),
                "navigated_to": None if navigated_to is None else self.url(navigated_to),
                "click": click,
            }
        )

    def _json_body(self, body: str) -> RedactedBody:
        try:
            data = json.loads(body)
        except ValueError:
            return RedactedBody(body, unscanned=True)  # parse ไม่ได้: ส่งผ่านไป แต่บอกว่ายังไม่ได้ตรวจ
        if not self._has_sensitive_key(data):
            return RedactedBody(body, unscanned=False)  # ไม่มีอะไรต้องซ่อน: คงรูปแบบเดิมไว้
        # เขียนใหม่จากค่าที่ parse แล้วเสมอ key ซ้ำในต้นฉบับจึงลักลอบส่งค่าจริงออกไปไม่ได้
        return RedactedBody(json.dumps(self._json(data), ensure_ascii=False), unscanned=False, redacted=True)

    def _multipart_body(self, body: str, content_type: str) -> RedactedBody:
        form = parse_multipart(body, content_type)
        if form is None:
            # parse ไม่ได้ (ผิดรูปหรือถูกตัดที่ 64 KB): บอกว่ายังไม่ได้ตรวจ และไม่ส่ง byte ที่ไม่ใช่ UTF-8 ต่อไป
            return RedactedBody(to_valid_text(body), unscanned=True)
        secret = any(self.is_sensitive_key(part.name) for part in form.parts)
        return RedactedBody(form.map_content(self._form_part), unscanned=False, redacted=secret)

    def _form_part(self, part: FormPart) -> str:
        """เนื้อของ part ที่แสดงได้: field ลับเป็น ••••, ไฟล์แนบเหลือแค่ชื่อ ชนิด และขนาด"""
        if self.is_sensitive_key(part.name):
            return REDACTED
        if part.filename is None or part.content.startswith(FILE_SUMMARY):  # ย่อไว้แล้ว (เช่นมาจาก Recording)
            return part.content
        size = len(part.content.encode("utf-8", "surrogateescape"))
        return f"{FILE_SUMMARY}{part.filename}, {part.content_type}, {describe_size(size)}]"

    def _header_value(self, name: str, value: str) -> str:
        lowered = name.lower()
        if lowered == "cookie":
            return "; ".join(self._cookie(part.strip()) for part in value.split(";") if part.strip())
        if lowered == "set-cookie":
            return "\n".join(self._set_cookie(line) for line in value.split("\n"))
        if lowered in URL_HEADER_NAMES:
            return self.url(value)
        if is_sensitive_header(name) or self.is_sensitive_key(name):
            if value.startswith(REDACTED):
                return value  # ซ่อนไว้แล้ว (เช่นมาจาก Recording): ไม่ซ่อนซ้ำ จำนวนตัวอักษรจะได้ยังเป็นของค่าจริง
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

    def _pairs(self, text: str) -> str:
        """ซ่อนค่าใน `a=1&b=2` (query หรือ form) โดยคง encoding เดิมของส่วนที่ไม่ได้ซ่อน"""
        pieces = []
        for piece in text.split("&"):
            raw_key, has_value, _ = piece.partition("=")
            if has_value and self.is_sensitive_key(unquote_plus(raw_key)):
                piece = f"{raw_key}={REDACTED}"
            pieces.append(piece)
        return "&".join(pieces)

    def _json(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: REDACTED if self.is_sensitive_key(k) else self._json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json(item) for item in value]
        return value

    def _has_sensitive_key(self, value: Any) -> bool:
        if isinstance(value, dict):
            return any(self.is_sensitive_key(k) or self._has_sensitive_key(v) for k, v in value.items())
        if isinstance(value, list):
            return any(self._has_sensitive_key(item) for item in value)
        return False
