"""ส่วนของการดักคลิกที่ทดสอบได้โดยไม่ต้องเปิด Chrome"""

import re
from typing import Any, cast

from playwright.async_api import Page

from inspector.capture import TrafficCapture
from inspector.capture_events import CaptureEvent
from inspector.click_tracker import hook_script


class ClosedPage:
    """แท็บที่ถูกปิดไปแล้ว แต่หน้าเว็บยังส่งคลิกค้างท่อมา"""

    url = "https://shop.example/"

    def is_closed(self) -> bool:
        return True

    def on(self, event: str, handler: Any) -> None:
        raise AssertionError("ไม่ควรฟัง event ของแท็บที่ปิดแล้ว")


def test_hook_script_has_every_placeholder_filled() -> None:
    script = hook_script(("http://127.0.0.1:8000",), report_document=True)
    assert re.findall(r"__[A-Z_]+__", script) == []
    assert '"http://127.0.0.1:8000"' in script


def test_hook_script_ignores_inspector_origin_written_with_a_path() -> None:
    script = hook_script(("http://127.0.0.1:8000/",), report_document=False)
    assert '["http://127.0.0.1:8000"]' in script


def test_a_click_from_a_closed_tab_is_dropped() -> None:
    events: list[CaptureEvent] = []
    capture = TrafficCapture(sink=events.append, inspector_origins=())
    assert capture.watched_tab_id(cast(Page, ClosedPage())) is None
    assert events == []
