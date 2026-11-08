"""EventStore: เก็บ Exchange และ Interaction ไว้ในหน่วยความจำแบบมีเพดาน

สอนแนวคิด: dunder methods (`__len__`, `__iter__`) ทำให้ object ใช้กับ `len()` และ `for` ได้
ไม่เขียนอะไรลงดิสก์
"""

from collections import deque
from collections.abc import Callable, Iterator

from inspector.filters import is_tracking
from inspector.models import HttpExchange, Interaction

Refilter = Callable[[HttpExchange], HttpExchange]


class EventStore:
    """ที่เก็บ Exchange และ Interaction (เก่าสุดออกก่อนเมื่อเกินเพดาน)

    Exchange ที่มองเห็นกับ Hidden exchange อยู่คนละ buffer แต่ละ buffer มีเพดานเท่ากัน
    traffic tracking จำนวนมากจึงไม่ดัน Exchange ที่มองเห็นออกจากหน่วยความจำ
    การเปลี่ยน Preset แค่ย้าย Exchange ข้าม buffer ไม่ลบอะไร (buffer จึงล้นเพดานชั่วคราวได้
    แล้วค่อยๆ ลดลงทีละตัวเมื่อมี Exchange ใหม่เข้ามา รวมสอง buffer ไม่เกินสองเท่าของเพดานเสมอ)
    """

    def __init__(self, max_exchanges: int = 500) -> None:
        self._visible: deque[str] = deque()
        self._hidden: deque[str] = deque()
        self._exchanges: dict[str, HttpExchange] = {}
        self._arrival: dict[str, int] = {}  # exchange id → ลำดับที่เข้ามา ใช้เรียงสอง buffer รวมกัน
        self._interactions: dict[str, Interaction] = {}  # dict จำลำดับที่ใส่เข้าไป: เก่าสุดอยู่หน้า
        # Hidden exchange ที่หลุดจาก buffer ไปแล้ว (ยังนับใน Hidden count) แยกตามเหตุผล:
        # tracking ไม่ขึ้นกับ Preset จึงนับต่อไปจนกว่าจะ Clear ส่วนนอกโฟกัสนับเฉพาะของ Preset ปัจจุบัน
        self._dropped_tracking = 0
        self._dropped_out_of_focus = 0
        self._next_arrival = 0
        self._max = max_exchanges

    @property
    def hidden_count(self) -> int:
        """Hidden exchange ทั้งหมดตั้งแต่ Clear ครั้งล่าสุด รวมตัวที่หลุดจาก buffer ไปแล้ว"""
        return len(self._hidden) + self._dropped_tracking + self._dropped_out_of_focus

    def add_exchange(self, exchange: HttpExchange) -> None:
        """เพิ่ม Exchange ใหม่เข้า buffer ตามสถานะซ่อน ถ้าเกินเพดานให้ตัดตัวเก่าสุดของ buffer นั้นทิ้ง"""
        self._next_arrival += 1
        self._arrival[exchange.id] = self._next_arrival
        self._exchanges[exchange.id] = exchange
        buffer = self._buffer_for(exchange)
        buffer.append(exchange.id)
        if len(buffer) > self._max:
            self._drop(buffer.popleft())

    def replace_exchange(self, exchange: HttpExchange) -> None:
        """แทนที่ Exchange เดิม (เช่น ได้ response แล้ว) ถ้าถูกตัดทิ้งไปแล้วก็ไม่ทำอะไร"""
        if exchange.id in self._exchanges:
            self._exchanges[exchange.id] = exchange

    def get_exchange(self, exchange_id: str) -> HttpExchange | None:
        return self._exchanges.get(exchange_id)

    def refilter(self, refilter: Refilter) -> None:
        """คำนวณสถานะซ่อนของทุก Exchange ใหม่ (เมื่อเปลี่ยน Preset) แล้วย้ายระหว่าง buffer โดยไม่ลบอะไร"""
        self._visible.clear()
        self._hidden.clear()
        self._dropped_out_of_focus = 0  # ไม่รู้แล้วว่าตัวที่หลุดไปจะตรง Preset ใหม่ไหม
        for exchange_id in sorted(self._exchanges, key=self._arrival.__getitem__):
            exchange = refilter(self._exchanges[exchange_id])
            self._exchanges[exchange_id] = exchange
            self._buffer_for(exchange).append(exchange_id)

    def add_interaction(self, interaction: Interaction) -> list[str]:
        """เพิ่ม Interaction ใหม่ ถ้าเกินเพดานให้ตัดตัวเก่าสุดทิ้ง คืน id ของตัวที่ถูกตัด"""
        self._interactions[interaction.id] = interaction
        evicted: list[str] = []
        while len(self._interactions) > self._max:
            oldest = next(iter(self._interactions))
            del self._interactions[oldest]
            evicted.append(oldest)
        return evicted

    def replace_interaction(self, interaction: Interaction) -> None:
        """แทนที่ Interaction เดิมโดยไม่เปลี่ยนลำดับ ถ้าถูกตัดทิ้งไปแล้วก็ไม่ทำอะไร"""
        if interaction.id in self._interactions:
            self._interactions[interaction.id] = interaction

    def interactions(self) -> list[Interaction]:
        return list(self._interactions.values())

    def get_interaction(self, interaction_id: str) -> Interaction | None:
        return self._interactions.get(interaction_id)

    def exchanges_of(self, interaction: Interaction) -> list[HttpExchange]:
        """Exchange ของ Interaction นี้ที่ยังอยู่ใน store เรียงตามลำดับที่เข้ามา"""
        wanted = set(interaction.exchange_ids)
        return [exchange for exchange in self if exchange.id in wanted]

    def clear(self) -> None:
        """ล้างทุกอย่าง รวม Hidden count (ลำดับการเข้ามายังนับต่อ ไม่มีผลกับการเรียง)"""
        self._visible.clear()
        self._hidden.clear()
        self._exchanges.clear()
        self._arrival.clear()
        self._interactions.clear()
        self._dropped_tracking = 0
        self._dropped_out_of_focus = 0

    def _buffer_for(self, exchange: HttpExchange) -> deque[str]:
        return self._hidden if exchange.hidden else self._visible

    def _drop(self, exchange_id: str) -> None:
        exchange = self._exchanges.pop(exchange_id)
        del self._arrival[exchange_id]
        if is_tracking(exchange):
            self._dropped_tracking += 1
        elif exchange.hidden:
            self._dropped_out_of_focus += 1

    def __len__(self) -> int:
        return len(self._exchanges)

    def __iter__(self) -> Iterator[HttpExchange]:
        """ทุก Exchange (ทั้งที่มองเห็นและที่ซ่อน) เรียงตามลำดับที่เข้ามา"""
        ordered = sorted(self._exchanges, key=self._arrival.__getitem__)
        return (self._exchanges[i] for i in ordered)
