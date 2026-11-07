"""InspectorPipeline: รับ Capture event แล้วส่งต่อจนถึง store และ UI

สอนแนวคิด: dependency injection — รับ object ที่ต้องใช้ผ่าน `__init__` จึงสลับของปลอมตอนทดสอบได้
"""

from typing import Any

from inspector.broadcaster import Broadcaster
from inspector.capture_events import CaptureEvent, RequestFailed, RequestStarted, ResponseReceived
from inspector.http_parts import body_kind, split_url
from inspector.models import HttpExchange, HttpRequest, HttpResponse, InspectorStatus
from inspector.redactor import Redactor
from inspector.store import EventStore


class InspectorPipeline:
    """ต่อส่วนต่างๆ เข้าด้วยกัน: capture → redact → store → broadcast"""

    def __init__(self, store: EventStore, broadcaster: Broadcaster, redactor: Redactor) -> None:
        self._store = store
        self._redactor = redactor
        self._broadcaster = broadcaster
        self._next_id = 0
        self._pending: dict[str, str] = {}  # request_key → exchange id
        self.status = InspectorStatus()

    def handle(self, event: CaptureEvent) -> None:
        """รับ Capture event หนึ่งตัว (ต้องเรียกบน event loop ของ app)"""
        if isinstance(event, RequestStarted):
            self._on_request(event)
        elif isinstance(event, ResponseReceived):
            self._on_response(event)
        elif isinstance(event, RequestFailed):
            self._on_failure(event)

    def snapshot(self) -> dict[str, Any]:
        """ข้อมูลทั้งหมดที่ client ใหม่ต้องรู้"""
        return {
            "interactions": [i.model_dump() for i in self._store.interactions()],
            "exchanges": [e.model_dump() for e in self._store],
            "status": self.status.model_dump(),
        }

    def _on_request(self, event: RequestStarted) -> None:
        # Redaction ทำตรงนี้ ก่อนสร้าง Exchange ค่าจริงจึงไม่เคยถูกเก็บหรือส่งออกไป
        host, path, query = split_url(event.url)
        kind = body_kind(event.headers, event.post_data)
        body = self._redactor.body(event.post_data, kind)
        page_url = self._redactor.url(event.page_url)
        request = HttpRequest(
            method=event.method,
            url=self._redactor.url(event.url),
            host=host,
            path=path,
            query=self._redactor.query(query),
            headers=self._redactor.headers(event.headers),
            body=body.text,
            body_kind=kind,
            body_unscanned=body.unscanned,
        )
        exchange = HttpExchange(
            id=self._new_id(),
            tab_id=event.tab_id,
            page_url=page_url,
            resource_type=event.resource_type,
            started_at=event.ts,
            request=request,
            has_redactions=(
                page_url != event.page_url
                or request.url != event.url
                or request.headers != event.headers
                or request.body != event.post_data
            ),
        )
        self._pending[event.request_key] = exchange.id
        self._store.add_exchange(exchange)
        self._broadcaster.publish("exchange.new", exchange.model_dump())

    def _on_response(self, event: ResponseReceived) -> None:
        exchange = self._take_pending(event.request_key)
        if exchange is None:
            return
        kind = body_kind(event.headers, event.body)
        body = self._redactor.body(event.body, kind)
        response = HttpResponse(
            status=event.status,
            status_text=event.status_text,
            headers=self._redactor.headers(event.headers),
            body=body.text,
            body_kind=kind,
            body_unscanned=body.unscanned,
            body_truncated_bytes=event.body_truncated_bytes,
            body_error=event.body_error,
        )
        self._finish(
            exchange.model_copy(
                update={
                    "state": "done",
                    "response": response,
                    "duration_ms": event.ts - exchange.started_at,
                    "has_redactions": exchange.has_redactions
                    or response.headers != event.headers
                    or response.body != event.body,
                }
            )
        )

    def _on_failure(self, event: RequestFailed) -> None:
        exchange = self._take_pending(event.request_key)
        if exchange is None:
            return
        self._finish(
            exchange.model_copy(
                update={"state": "failed", "failure": event.failure, "duration_ms": event.ts - exchange.started_at}
            )
        )

    def _take_pending(self, request_key: str) -> HttpExchange | None:
        """หา Exchange ที่รอคำตอบอยู่ ถ้าไม่รู้จักหรือถูกตัดออกจาก store ไปแล้วคืน None"""
        exchange_id = self._pending.pop(request_key, None)
        return None if exchange_id is None else self._store.get_exchange(exchange_id)

    def _finish(self, exchange: HttpExchange) -> None:
        self._store.replace_exchange(exchange)
        self._broadcaster.publish("exchange.update", exchange.model_dump())

    def _new_id(self) -> str:
        self._next_id += 1
        return f"ex_{self._next_id:04d}"
