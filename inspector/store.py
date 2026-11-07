"""EventStore: เก็บ Exchange และ Interaction ไว้ในหน่วยความจำแบบมีเพดาน

สอนแนวคิด: dunder methods (`__len__`, `__iter__`) ทำให้ object ใช้กับ `len()` และ `for` ได้
ไม่เขียนอะไรลงดิสก์
"""

from collections import deque
from collections.abc import Iterator

from inspector.models import HttpExchange, Interaction


class EventStore:
    """ที่เก็บ Exchange (เก่าสุดออกก่อนเมื่อเกินเพดาน) และ Interaction"""

    def __init__(self, max_exchanges: int = 500) -> None:
        self._order: deque[str] = deque()
        self._exchanges: dict[str, HttpExchange] = {}
        self._interactions: dict[str, Interaction] = {}
        self._max = max_exchanges

    def add_exchange(self, exchange: HttpExchange) -> None:
        """เพิ่ม Exchange ใหม่ ถ้าเกินเพดานให้ตัดตัวเก่าสุดทิ้ง"""
        self._order.append(exchange.id)
        self._exchanges[exchange.id] = exchange
        while len(self._order) > self._max:
            del self._exchanges[self._order.popleft()]

    def replace_exchange(self, exchange: HttpExchange) -> None:
        """แทนที่ Exchange เดิม (เช่น ได้ response แล้ว) ถ้าถูกตัดทิ้งไปแล้วก็ไม่ทำอะไร"""
        if exchange.id in self._exchanges:
            self._exchanges[exchange.id] = exchange

    def get_exchange(self, exchange_id: str) -> HttpExchange | None:
        return self._exchanges.get(exchange_id)

    def interactions(self) -> list[Interaction]:
        return list(self._interactions.values())

    def __len__(self) -> int:
        return len(self._order)

    def __iter__(self) -> Iterator[HttpExchange]:
        return (self._exchanges[i] for i in self._order)
