"""Correlator: จัด Exchange เข้า Interaction ตามสาเหตุ (คลิก, Navigation หรือเกิดเองเบื้องหลัง)

สอนแนวคิด: state ใน object — Correlator จำว่าแต่ละแท็บมี Interaction ไหนเปิดอยู่และหมดเวลาเมื่อไร
แล้วใช้ state นั้นตัดสินว่า Exchange ใหม่ควรอยู่กลุ่มไหน ไม่ยุ่งกับ store หรือ UI เลย
"""

from dataclasses import dataclass

from inspector.models import ClickEvent, Interaction, InteractionKind

NAVIGATION_WINDOW_MS = 5000.0


@dataclass
class OpenInteraction:
    """Interaction ที่ยังรับ Exchange ได้ถึงเวลา `until` (epoch ms)"""

    interaction: Interaction
    until: float


@dataclass
class TabState:
    """สิ่งที่ Correlator จำไว้ของแต่ละแท็บ"""

    caused: OpenInteraction | None = None  # Click หรือ Page-load interaction ล่าสุด
    background: Interaction | None = None


@dataclass(frozen=True)
class Change:
    """ผลลัพธ์ของการตัดสินใจหนึ่งครั้ง

    `announce` เป็น False เมื่อการ์ดคลิก/โหลดหน้าแค่ได้ Exchange เพิ่ม เพราะ `exchange.new` บอก UI อยู่แล้ว
    """

    interaction: Interaction
    is_new: bool
    announce: bool = True


class Correlator:
    """ตัดสินว่า Exchange แต่ละตัวเป็นผลของอะไร ตามกฎ Correlation window ใน CONTEXT.md"""

    def __init__(self, window_ms: float = 1500.0) -> None:
        self._window_ms = window_ms
        self._tabs: dict[str, TabState] = {}
        self._next_id = 0

    def click(self, click: ClickEvent) -> Change:
        """คลิกใหม่เปิด Click interaction เสมอ และปิดกลุ่มเดิมของแท็บนั้น"""
        tab = self._tab(click.tab_id)
        tab.background = None
        interaction = self._new("click", click.tab_id, click.page_url, click.ts, click=click)
        tab.caused = OpenInteraction(interaction, until=click.ts + self._window_ms)
        return Change(interaction, is_new=True)

    def navigation(self, tab_id: str, url: str, ts: float) -> Change:
        """Navigation ที่มาจากคลิกขยายการ์ดคลิกเดิม ถ้าไม่มีคลิกนำหน้าจะเปิด Page-load interaction"""
        tab = self._tab(tab_id)
        tab.background = None
        current = tab.caused
        if current is not None and current.interaction.kind == "click" and ts <= current.until:
            current.interaction = current.interaction.model_copy(update={"navigated_to": url})
            current.until = ts + NAVIGATION_WINDOW_MS
            return Change(current.interaction, is_new=False)
        interaction = self._new("page_load", tab_id, url, ts)
        tab.caused = OpenInteraction(interaction, until=ts + NAVIGATION_WINDOW_MS)
        return Change(interaction, is_new=True)

    def exchange(self, exchange_id: str, tab_id: str, page_url: str, ts: float) -> Change:
        """จัด Exchange เข้ากลุ่มของคลิก/Navigation ที่ยังไม่หมดเวลา ถ้าไม่มีให้เข้า Background interaction"""
        tab = self._tab(tab_id)
        current = tab.caused
        if current is not None and ts <= current.until:
            current.interaction = self._with_exchange(current.interaction, exchange_id)
            return Change(current.interaction, is_new=False, announce=False)
        if tab.background is None:
            tab.background = self._with_exchange(self._new("background", tab_id, page_url, ts), exchange_id)
            return Change(tab.background, is_new=True)
        tab.background = self._with_exchange(tab.background, exchange_id)
        return Change(tab.background, is_new=False)

    def reset(self) -> None:
        """ลืมทุกกลุ่มที่เปิดอยู่ (ใช้ตอน Clear หรือ Resume)"""
        self._tabs.clear()

    def _tab(self, tab_id: str) -> TabState:
        return self._tabs.setdefault(tab_id, TabState())

    def _new(self, kind: InteractionKind, tab_id: str, page_url: str, ts: float, click: ClickEvent | None = None) -> Interaction:
        self._next_id += 1
        return Interaction(
            id=f"int_{self._next_id:04d}", kind=kind, click=click, tab_id=tab_id, page_url=page_url, started_at=ts
        )

    @staticmethod
    def _with_exchange(interaction: Interaction, exchange_id: str) -> Interaction:
        return interaction.model_copy(update={"exchange_ids": [*interaction.exchange_ids, exchange_id]})
