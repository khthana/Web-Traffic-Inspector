"""Capture event: ข้อมูลล้วนที่ฝั่ง capture ส่งให้ InspectorPipeline

นี่คือ "seam" ระหว่าง Chrome/Playwright กับส่วนอื่นของโปรแกรม
ทุกอย่างหลังจากจุดนี้จึงทดสอบได้โดยไม่ต้องมี Chrome

สอนแนวคิด: immutable value object (frozen dataclass)
เวลาทุกตัวเป็น epoch milliseconds และมาพร้อม event เสมอ pipeline ไม่อ่านนาฬิกาเอง
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from inspector.models import ElementInfo


@dataclass(frozen=True)
class RequestStarted:
    """เบราว์เซอร์ส่ง request ออกไป (ยังไม่มีคำตอบ)"""

    request_key: str  # รหัสที่ฝั่ง capture ใช้จับคู่ request กับ response
    tab_id: str
    page_url: str
    ts: float
    method: str
    url: str
    resource_type: Literal["fetch", "xhr"]
    headers: dict[str, str] = field(default_factory=dict)
    post_data: str | None = None
    body_error: str | None = None  # เหตุผลที่ไม่มี body ทั้งที่ request ส่ง body ไป


@dataclass(frozen=True)
class ResponseReceived:
    """ได้คำตอบกลับมาแล้ว (body ถูกตัดที่ 64 KB โดยฝั่ง capture)"""

    request_key: str
    ts: float
    status: int
    status_text: str
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    body_truncated_bytes: int = 0
    body_error: str | None = None


@dataclass(frozen=True)
class RequestFailed:
    """request ล้มเหลว (network error, CORS, abort)"""

    request_key: str
    ts: float
    failure: str


@dataclass(frozen=True)
class ClickCaptured:
    """ผู้ใช้คลิก element ในหน้าเว็บ"""

    tab_id: str
    page_url: str
    ts: float
    element: ElementInfo


@dataclass(frozen=True)
class NavigationOccurred:
    """main frame โหลด document ใหม่ (ไม่รวม pushState)"""

    tab_id: str
    url: str
    ts: float


@dataclass(frozen=True)
class TabChanged:
    """Watched tab เปิดหรือปิด"""

    tab_id: str
    url: str
    ts: float
    open: bool


CaptureEvent = (
    RequestStarted | ResponseReceived | RequestFailed | ClickCaptured | NavigationOccurred | TabChanged
)

EventSink = Callable[[CaptureEvent], None]
"""ปลายทางที่รับ Capture event (ปกติคือ InspectorPipeline.handle)"""
