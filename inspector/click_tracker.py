"""ClickTracker: ฉีด click_hook.js เข้าหน้าเว็บ แล้วแปลงข้อมูลที่ส่งกลับมาเป็น Capture event

ข้อมูลที่มาจากหน้าเว็บเชื่อถือไม่ได้ (เว็บไหนก็เรียก binding นี้เองได้) จึงตรวจชนิดและตัดความยาวทุกช่อง
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

from inspector.capture_events import CaptureEvent, ClickCaptured, NavigationOccurred
from inspector.models import ElementInfo

HOOK_SOURCE = (Path(__file__).parent / "click_hook.js").read_text(encoding="utf-8")
CLICK_BINDING = "__wtiReportClick"
NAVIGATION_BINDING = "__wtiReportNavigation"
MAX_TEXT = 40
MAX_FIELD = 300
MAX_URL = 4096

EventSink = Callable[[CaptureEvent], None]
TabLookup = Callable[[Page], str | None]


def hook_script(inspector_origins: tuple[str, ...], report_document: bool) -> str:
    """สร้างสคริปต์ที่จะฉีด: ใส่รายการ origin ของ Inspector (ไม่ฉีดหน้าตัวเอง)"""
    return HOOK_SOURCE.replace("__IGNORED_ORIGINS__", json.dumps(list(inspector_origins))).replace(
        "__REPORT_DOCUMENT__", "true" if report_document else "false"
    )


def clean_text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def clean_optional(value: Any, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def clean_ts(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and value > 0 else None


class ClickTracker:
    """รับคลิกและ Navigation จากสคริปต์ในหน้าเว็บ แล้วส่ง Capture event ให้ `sink`

    สอนแนวคิด: callback — Playwright เรียกเมธอดของเราเมื่อสคริปต์ในหน้าเว็บเรียก binding
    """

    def __init__(self, sink: EventSink, inspector_origins: tuple[str, ...], tab_of: TabLookup) -> None:
        self._sink = sink
        self._origins = tuple(origin.rstrip("/") for origin in inspector_origins)
        self._tab_of = tab_of

    async def attach(self, context: BrowserContext) -> None:
        """ติดตั้ง binding และสคริปต์ให้ทุกหน้าใหม่ แล้วฉีดซ้ำเข้าหน้าที่เปิดอยู่แล้ว"""
        await context.expose_binding(CLICK_BINDING, self._on_click)
        await context.expose_binding(NAVIGATION_BINDING, self._on_navigation)
        await context.add_init_script(hook_script(self._origins, report_document=True))
        for page in context.pages:
            try:
                await page.evaluate(hook_script(self._origins, report_document=False))
            except PlaywrightError:
                pass  # หน้าที่ฉีดไม่ได้ เช่น chrome:// หรือกำลังปิด

    def _on_click(self, source: dict[str, Any], report: Any) -> None:
        tab_id = self._watched_tab(source)
        if tab_id is None or not isinstance(report, dict):
            return
        ts = clean_ts(report.get("ts"))
        page_url = clean_text(report.get("page_url"), MAX_URL)
        if ts is None or not page_url:
            return
        classes = report.get("classes")
        element = ElementInfo(
            tag=clean_text(report.get("tag"), MAX_TEXT) or "?",
            text=clean_text(report.get("text"), MAX_TEXT),
            aria_label=clean_optional(report.get("aria_label"), MAX_FIELD),
            element_id=clean_optional(report.get("element_id"), MAX_FIELD),
            classes=[clean_text(c, MAX_FIELD) for c in classes[:3]] if isinstance(classes, list) else [],
            href=clean_optional(report.get("href"), MAX_URL),
            selector=clean_text(report.get("selector"), MAX_FIELD),
        )
        self._sink(ClickCaptured(tab_id=tab_id, page_url=page_url, ts=ts, element=element))

    def _on_navigation(self, source: dict[str, Any], report: Any) -> None:
        tab_id = self._watched_tab(source)
        if tab_id is None or not isinstance(report, dict):
            return
        ts = clean_ts(report.get("ts"))
        url = clean_text(report.get("url"), MAX_URL)
        if ts is not None and url:
            self._sink(NavigationOccurred(tab_id=tab_id, url=url, ts=ts))

    def _watched_tab(self, source: dict[str, Any]) -> str | None:
        """แท็บที่ส่งข้อมูลมา ถ้าไม่ได้มาจาก main frame ของ Watched tab คืน None"""
        page = source.get("page")
        frame = source.get("frame")
        if not isinstance(page, Page) or frame != page.main_frame:
            return None
        return self._tab_of(page)
