"""Pydantic models ที่ใช้ทั้งใน store, REST API และ WebSocket

สอนแนวคิด: data class / schema — แยก "ข้อมูล" ออกจาก "พฤติกรรม"
เวลาทุกตัวเป็น epoch milliseconds (float)
"""

from typing import Literal

from pydantic import BaseModel

BodyKind = Literal["json", "form", "text", "binary", "none"]
InteractionKind = Literal["click", "page_load", "background"]


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
    """ขาออก (Request) — ต้องผ่าน Redaction ก่อนเก็บ (ticket #3)"""

    method: str
    url: str
    host: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: str | None
    body_kind: BodyKind
    body_unscanned: bool = True  # True = ยังไม่ได้ตรวจหาข้อมูลลับ (ค่าเริ่มต้นแบบปลอดภัยไว้ก่อน)


class HttpResponse(BaseModel):
    """ขาเข้า (Response) — ต้องผ่าน Redaction ก่อนเก็บ (ticket #3)"""

    status: int
    status_text: str
    headers: dict[str, str]
    body: str | None
    body_kind: BodyKind
    body_truncated_bytes: int = 0
    body_error: str | None = None
    body_unscanned: bool = True


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
    has_redactions: bool = False  # True = มีค่าลับอย่างน้อยหนึ่งจุดถูกซ่อนไว้
    hidden: bool = False
    hidden_reason: str | None = None
    summary: str = ""
    interaction_id: str | None = None


class Interaction(BaseModel):
    """กลุ่มของ Exchange ที่มีสาเหตุร่วมกัน"""

    id: str
    kind: InteractionKind
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
    hidden_count: int = 0  # Hidden exchange ทั้งหมดตั้งแต่ Clear (รวมตัวที่หลุดจาก buffer แล้ว)
    preset: str = "all"
    tabs: list[TabInfo] = []
    chrome_launch_command: str = ""  # คำสั่งเปิด Chrome โหมด debug ตาม OS ของเครื่องนี้
    correlation_window_ms: float = 1500  # UI ใช้รอก่อนบอกว่าคลิกนี้ "ไม่มี API call"
    mode: Literal["live", "playback"] = "live"
    recording_file: str | None = None


class FilterRules(BaseModel):
    """กฎการกรองของ Preset หนึ่งชุด (Blocklist พื้นฐานไม่อยู่ในนี้ เพราะถอดออกไม่ได้)

    host เขียนแบบ `example.com` (นับ subdomain ด้วย) หรือ `*.run.app`
    """

    focus_hosts: list[str] = []  # Focus rule: แสดงเฉพาะ host เหล่านี้
    focus_path_prefixes: list[str] = []  # Focus rule: แสดงเฉพาะ path ที่ขึ้นต้นแบบนี้
    focus_resource_types: list[Literal["fetch", "xhr"]] = []
    block_hosts: list[str] = []  # Blocklist เพิ่มเติม
    block_path_prefixes: list[str] = []
    redact_keys: list[str] = []  # key ที่ต้องซ่อนค่าเพิ่ม (เพิ่มได้อย่างเดียว)


class Preset(FilterRules):
    """ชุดกฎการกรองที่มีชื่อ เช่น `all`, `advice` หรือ `custom` (อยู่ในหน่วยความจำเท่านั้น)"""

    name: str
    label: str


class PresetChoice(BaseModel):
    """ตัวเลือกหนึ่งตัวใน dropdown"""

    name: str
    label: str


class FilterView(BaseModel):
    """คำตอบของ `GET /api/filters`"""

    selected: str
    choices: list[PresetChoice]
    rules: FilterRules
    base_blocklist: list[str]


class FilterUpdate(BaseModel):
    """body ของ `PUT /api/filters`: เลือก Preset และ (เฉพาะ `custom`) แก้กฎ"""

    selected: str
    rules: FilterRules | None = None
