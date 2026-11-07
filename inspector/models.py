"""Pydantic models ที่ใช้ทั้งใน store, REST API และ WebSocket

สอนแนวคิด: data class / schema — แยก "ข้อมูล" ออกจาก "พฤติกรรม"
เวลาทุกตัวเป็น epoch milliseconds (float)
"""

from typing import Literal

from pydantic import BaseModel

BodyKind = Literal["json", "form", "text", "binary", "none"]


class ElementInfo(BaseModel):
    """ข้อมูลของ element ที่ถูกคลิก (ไม่มีค่าใน input เด็ดขาด)"""

    tag: str
    text: str
    aria_label: str | None = None
    element_id: str | None = None
    classes: list[str] = []
    href: str | None = None
    selector: str


class ClickEvent(BaseModel):
    """การคลิกหนึ่งครั้งในหน้าเว็บ"""

    id: str
    tab_id: str
    page_url: str
    ts: float
    element: ElementInfo


class HttpRequest(BaseModel):
    """ขาออก (Request) — ผ่าน Redaction แล้ว"""

    method: str
    url: str
    host: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: str | None
    body_kind: BodyKind
    body_unscanned: bool = False  # True = body เป็น text ที่ไม่ได้ตรวจหาข้อมูลลับ


class HttpResponse(BaseModel):
    """ขาเข้า (Response) — ผ่าน Redaction แล้ว"""

    status: int
    status_text: str
    headers: dict[str, str]
    body: str | None
    body_kind: BodyKind
    body_truncated_bytes: int = 0
    body_error: str | None = None
    body_unscanned: bool = False


class HttpExchange(BaseModel):
    """Exchange: คู่ request/response หนึ่งคู่ของ fetch หรือ XHR"""

    id: str
    tab_id: str
    page_url: str
    resource_type: Literal["fetch", "xhr"]
    started_at: float
    duration_ms: float | None = None
    state: Literal["pending", "done", "failed"] = "pending"
    failure: str | None = None
    request: HttpRequest
    response: HttpResponse | None = None
    hidden: bool = False
    hidden_reason: str | None = None
    summary: str = ""
    interaction_id: str | None = None


class Interaction(BaseModel):
    """กลุ่มของ Exchange ที่มีสาเหตุร่วมกัน"""

    id: str
    kind: Literal["click", "page_load", "background"]
    click: ClickEvent | None = None
    tab_id: str
    page_url: str
    started_at: float
    exchange_ids: list[str] = []
    navigated_to: str | None = None


class TabInfo(BaseModel):
    """Watched tab หนึ่งแท็บ"""

    tab_id: str
    url: str


class InspectorStatus(BaseModel):
    """สถานะรวมของ Inspector ที่ส่งไปให้ UI"""

    chrome: Literal["connected", "disconnected"] = "disconnected"
    paused: bool = False
    hidden_count: int = 0
    tabs: list[TabInfo] = []
    mode: Literal["live", "playback"] = "live"
    recording_file: str | None = None
