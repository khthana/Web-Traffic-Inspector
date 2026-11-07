"""ฟังก์ชันช่วยแยกส่วนประกอบของ HTTP (URL, ชนิดของ body)"""

from urllib.parse import parse_qs, urlsplit

from inspector.models import BodyKind


def split_url(url: str) -> tuple[str, str, dict[str, list[str]]]:
    """แยก URL เป็น (host, path, query) — query หนึ่ง key มีได้หลายค่า"""
    parts = urlsplit(url)
    return parts.hostname or "", parts.path or "/", parse_qs(parts.query, keep_blank_values=True)


def body_kind(headers: dict[str, str], body: str | None) -> BodyKind:
    """เดาชนิดของ body จาก header content-type"""
    if not body:
        return "none"
    content_type = header(headers, "content-type").lower()
    if "json" in content_type:
        return "json"
    if "x-www-form-urlencoded" in content_type:
        return "form"
    if content_type.startswith("text/") or "xml" in content_type or "javascript" in content_type:
        return "text"
    if not content_type:
        return "text"
    return "binary"


def header(headers: dict[str, str], name: str) -> str:
    """อ่าน header โดยไม่สนตัวพิมพ์เล็ก/ใหญ่ ถ้าไม่มีคืน string ว่าง"""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""
