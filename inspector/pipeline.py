"""InspectorPipeline: รับ Capture event แล้วส่งต่อจนถึง store และ UI

สอนแนวคิด: dependency injection — รับ object ที่ต้องใช้ผ่าน `__init__` จึงสลับของปลอมตอนทดสอบได้
"""

from typing import Any

from inspector.broadcaster import Broadcaster
from inspector.capture_events import (
    CaptureEvent,
    ClickCaptured,
    NavigationOccurred,
    RequestFailed,
    RequestStarted,
    ResponseReceived,
    TabChanged,
)
from inspector.correlator import Correlation, Correlator
from inspector.filters import CUSTOM, FilterSettings
from inspector.http_parts import body_kind, split_url
from inspector.models import (
    ClickEvent,
    FilterUpdate,
    FilterView,
    HttpExchange,
    HttpRequest,
    HttpResponse,
    InspectorStatus,
    TabInfo,
)
from inspector.redactor import Redactor
from inspector.store import EventStore


class InspectorPipeline:
    """ต่อส่วนต่างๆ เข้าด้วยกัน: capture → redact → filter → correlate → store → broadcast

    กรองหลัง Redaction ได้ผลเท่ากัน เพราะกฎการกรองดูแค่ host, path และชนิด ซึ่ง Redaction ไม่แตะ
    """

    def __init__(
        self,
        store: EventStore,
        broadcaster: Broadcaster,
        redactor: Redactor,
        correlator: Correlator,
        filters: FilterSettings,
        chrome_launch_command: str = "",
    ) -> None:
        self._store = store
        self._filters = filters
        self._chain = filters.chain()
        # key ที่ Preset เพิ่มมาสะสมไว้ตลอด (เปลี่ยน Preset แล้วก็ไม่ลด): ซ่อนเกินได้ แต่ห้ามซ่อนขาด
        self._redactor = redactor.with_extra_keys(filters.current.redact_keys)
        self._correlator = correlator
        self._broadcaster = broadcaster
        self._next_id = 0
        self._next_click = 0
        self._pending: dict[str, str] = {}  # request_key → exchange id
        self._tabs: dict[str, TabInfo] = {}
        self.status = InspectorStatus(
            chrome_launch_command=chrome_launch_command,
            correlation_window_ms=correlator.window_ms,
            preset=filters.current.name,
        )

    def handle(self, event: CaptureEvent) -> None:
        """รับ Capture event หนึ่งตัว (ต้องเรียกบน event loop ของ app)"""
        if isinstance(event, RequestStarted):
            self._on_request(event)
        elif isinstance(event, ResponseReceived):
            self._on_response(event)
        elif isinstance(event, RequestFailed):
            self._on_failure(event)
        elif isinstance(event, ClickCaptured):
            self._on_click(event)
        elif isinstance(event, NavigationOccurred):
            self._on_navigation(event)
        elif isinstance(event, TabChanged):
            self._on_tab(event)

    def set_chrome_connected(self, connected: bool) -> None:
        """ChromeConnector แจ้งว่าเชื่อมได้หรือหลุดแล้ว (ข้อมูลเดิมยังอยู่ครบ)"""
        if not connected:
            self._tabs.clear()
            for request_key in list(self._pending):
                exchange = self._take_pending(request_key)
                if exchange is not None:
                    self._finish(exchange.model_copy(update={"state": "failed", "failure": "Chrome หลุดก่อนได้คำตอบ"}))
        self._publish_status(chrome="connected" if connected else "disconnected")

    def filter_view(self) -> FilterView:
        return self._filters.view()

    def change_filters(self, update: FilterUpdate) -> FilterView:
        """เลือก Preset (หรือแก้ `custom`) แล้วคำนวณการซ่อนของทุก Exchange ใหม่ และส่ง snapshot ให้ทุก client

        ชื่อไม่รู้จัก หรือส่งกฎมากับ Preset ที่ไม่ใช่ `custom` → ValueError (ไม่เปลี่ยนอะไร)
        """
        if update.rules is not None and update.selected != CUSTOM:
            raise ValueError("แก้กฎได้เฉพาะ preset custom (Preset จากไฟล์แก้จากหน้าเว็บไม่ได้)")
        if update.rules is None:
            self._filters.select(update.selected)
        else:
            self._filters.edit_custom(update.rules)
        self._chain = self._filters.chain()
        self._redactor = self._redactor.with_extra_keys(self._filters.current.redact_keys)
        self._store.refilter(self._chain.apply)
        self.status = self.status.model_copy(
            update={
                "preset": self._filters.current.name,
                "hidden_count": self._store.hidden_count,
                "filters_version": self.status.filters_version + 1,
            }
        )
        self._broadcaster.publish("snapshot", self.snapshot())
        return self._filters.view()

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
        exchange_id = self._new_id()
        correlation = self._correlator.exchange(exchange_id, event.tab_id, page_url, event.ts)
        # Click/Page-load interaction ที่ได้ Exchange เพิ่มไม่ต้องประกาศ เพราะ exchange.new มี interaction_id อยู่แล้ว
        self._save_interaction(correlation, announce=correlation.is_new or correlation.interaction.kind == "background")
        exchange = HttpExchange(
            id=exchange_id,
            interaction_id=correlation.interaction.id,
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
        exchange = self._chain.apply(exchange)
        self._pending[event.request_key] = exchange.id
        self._store.add_exchange(exchange)
        self._broadcaster.publish("exchange.new", exchange.model_dump())
        if exchange.hidden:
            self._publish_status(hidden_count=self._store.hidden_count)

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

    def _on_click(self, event: ClickCaptured) -> None:
        self._next_click += 1
        page_url = self._redactor.url(event.page_url)
        href = None if event.element.href is None else self._redactor.url(event.element.href)
        click = ClickEvent(
            id=f"click_{self._next_click:04d}",
            tab_id=event.tab_id,
            page_url=page_url,
            ts=event.ts,
            element=event.element.model_copy(update={"href": href}),
        )
        self._save_interaction(self._correlator.click(click))

    def _on_navigation(self, event: NavigationOccurred) -> None:
        self._save_interaction(self._correlator.navigation(event.tab_id, self._redactor.url(event.url), event.ts))

    def _save_interaction(self, correlation: Correlation, announce: bool = True) -> None:
        if correlation.is_new:
            for evicted_id in self._store.add_interaction(correlation.interaction):
                self._correlator.forget(evicted_id)  # จะได้ไม่มี Exchange ใหม่ไปเข้า Interaction ที่ไม่มีแล้ว
        else:
            self._store.replace_interaction(correlation.interaction)
        if announce:
            message = "interaction.new" if correlation.is_new else "interaction.update"
            self._broadcaster.publish(message, correlation.interaction.model_dump())

    def _on_tab(self, event: TabChanged) -> None:
        if event.open:
            self._tabs[event.tab_id] = TabInfo(tab_id=event.tab_id, url=self._redactor.url(event.url))
        else:
            self._tabs.pop(event.tab_id, None)
        self._publish_status()

    def _publish_status(self, **changes: object) -> None:
        self.status = self.status.model_copy(update={**changes, "tabs": list(self._tabs.values())})
        self._broadcaster.publish("status", self.status.model_dump())

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
