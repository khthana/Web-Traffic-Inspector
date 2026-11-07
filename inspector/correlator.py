"""Correlator: ตัดสินว่า Exchange แต่ละตัวเป็นผลของอะไร (คลิก, Navigation หรือเกิดเองเบื้องหลัง)

ไม่ยุ่งกับ store หรือ UI เลย แค่บอกว่า Exchange ควรอยู่ใน Interaction ไหน
"""

from dataclasses import dataclass

from inspector.models import ClickEvent, Interaction, InteractionKind

NAVIGATION_WINDOW_MS = 5000.0


@dataclass
class OpenInteraction:
    """Click หรือ Page-load interaction ที่ยังรับ Exchange ได้จนถึงเวลา `until` (epoch ms)

    สอนแนวคิด: dataclass — class ที่มีไว้เก็บข้อมูลเป็นหลัก Python เขียน `__init__` ให้เอง
    """

    interaction: Interaction
    until: float


@dataclass
class TabState:
    """สิ่งที่ Correlator จำไว้ของแต่ละแท็บ

    สอนแนวคิด: composition — Correlator ประกอบด้วย TabState หลายอัน (แท็บละอัน)
    """

    caused_by_user: OpenInteraction | None = None  # Click หรือ Page-load interaction ล่าสุด
    background: Interaction | None = None


@dataclass(frozen=True)
class Correlation:
    """ผลการตัดสินหนึ่งครั้ง: Interaction หลังเปลี่ยนแปลง และเพิ่งเปิดใหม่หรือไม่

    สอนแนวคิด: immutable value object — สร้างแล้วแก้ไม่ได้ ส่งต่อได้อย่างปลอดภัย
    """

    interaction: Interaction
    is_new: bool


class Correlator:
    """จัด Exchange เข้า Interaction ตามกฎ Correlation window ใน CONTEXT.md

    สอนแนวคิด: state ใน object — จำว่าแต่ละแท็บมี Interaction ไหนเปิดอยู่และหมดเวลาเมื่อไร
    แล้วใช้ state นั้นตัดสินว่า Exchange ใหม่เป็นผลของอะไร
    """

    def __init__(self, window_ms: float) -> None:
        self.window_ms = window_ms
        self._tabs: dict[str, TabState] = {}
        self._next_id = 0

    def click(self, click: ClickEvent) -> Correlation:
        """คลิกใหม่เปิด Click interaction เสมอ และปิด Interaction เดิมของแท็บนั้น"""
        tab = self._tab(click.tab_id)
        tab.background = None
        interaction = self._new("click", click.tab_id, click.page_url, click.ts, click=click)
        tab.caused_by_user = OpenInteraction(interaction, until=click.ts + self.window_ms)
        return Correlation(interaction, is_new=True)

    def navigation(self, tab_id: str, url: str, ts: float) -> Correlation:
        """Navigation ภายใน Correlation window ของคลิกเป็นผลของคลิกนั้น ไม่งั้นเปิด Page-load interaction"""
        tab = self._tab(tab_id)
        tab.background = None
        current = tab.caused_by_user
        click = None if current is None else current.interaction.click
        if current is not None and click is not None and ts <= click.ts + self.window_ms:
            current.interaction = current.interaction.model_copy(update={"navigated_to": url})
            current.until = ts + NAVIGATION_WINDOW_MS
            return Correlation(current.interaction, is_new=False)
        interaction = self._new("page_load", tab_id, url, ts)
        tab.caused_by_user = OpenInteraction(interaction, until=ts + NAVIGATION_WINDOW_MS)
        return Correlation(interaction, is_new=True)

    def exchange(self, exchange_id: str, tab_id: str, page_url: str, ts: float) -> Correlation:
        """Exchange ที่เริ่มระหว่างคลิก/Navigation กับเวลาหมด window เป็นผลของมัน ไม่งั้นเป็นเบื้องหลัง"""
        tab = self._tab(tab_id)
        current = tab.caused_by_user
        if current is not None and current.interaction.started_at <= ts <= current.until:
            current.interaction = self._with_exchange(current.interaction, exchange_id)
            return Correlation(current.interaction, is_new=False)
        if tab.background is None:
            tab.background = self._with_exchange(self._new("background", tab_id, page_url, ts), exchange_id)
            return Correlation(tab.background, is_new=True)
        tab.background = self._with_exchange(tab.background, exchange_id)
        return Correlation(tab.background, is_new=False)

    def forget(self, interaction_id: str) -> None:
        """เลิกจำ Interaction นี้ (store ตัดทิ้งไปแล้ว) Exchange ถัดไปจะได้ Interaction ใหม่แทน"""
        for tab in self._tabs.values():
            if tab.background is not None and tab.background.id == interaction_id:
                tab.background = None
            if tab.caused_by_user is not None and tab.caused_by_user.interaction.id == interaction_id:
                tab.caused_by_user = None

    def _tab(self, tab_id: str) -> TabState:
        return self._tabs.setdefault(tab_id, TabState())

    def _new(
        self, kind: InteractionKind, tab_id: str, page_url: str, ts: float, click: ClickEvent | None = None
    ) -> Interaction:
        self._next_id += 1
        return Interaction(
            id=f"int_{self._next_id:04d}", kind=kind, click=click, tab_id=tab_id, page_url=page_url, started_at=ts
        )

    @staticmethod
    def _with_exchange(interaction: Interaction, exchange_id: str) -> Interaction:
        return interaction.model_copy(update={"exchange_ids": [*interaction.exchange_ids, exchange_id]})
