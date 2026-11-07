"""Broadcaster: ส่งข้อความไปหา WebSocket client ทุกตัว

สอนแนวคิด: observer pattern — ผู้ส่ง (pipeline) ไม่ต้องรู้ว่ามีผู้ฟังกี่คน
client แต่ละตัวมีคิวของตัวเอง ข้อความจึงออกไปตามลำดับเสมอ และ client ที่ช้าไม่ทำให้ตัวอื่นช้าตาม
"""

import asyncio
from typing import Any

Message = dict[str, Any]


class Subscription:
    """คิวข้อความของ client หนึ่งตัว

    สอนแนวคิด: encapsulation — ซ่อน asyncio.Queue ไว้ ผู้ใช้เห็นแค่ push/next
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Message] = asyncio.Queue()

    def push(self, message: Message) -> None:
        self._queue.put_nowait(message)

    async def next(self) -> Message:
        return await self._queue.get()


class Broadcaster:
    """เก็บรายชื่อ client และกระจายข้อความ `{"type": ..., "data": ...}` ให้ทุกตัว"""

    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    def subscribe(self, first_message: Message) -> Subscription:
        """ลงทะเบียน client ใหม่ โดยใส่ข้อความแรก (snapshot) ไว้หน้าคิว

        ทำทั้งสองอย่างในจังหวะเดียว ไม่มี await คั่น จึงไม่มีข้อความใดหลุดหรือแซงหน้า snapshot
        """
        subscription = Subscription()
        subscription.push(first_message)
        self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscriptions.discard(subscription)

    def publish(self, type_: str, data: Any) -> None:
        message: Message = {"type": type_, "data": data}
        for subscription in self._subscriptions:
            subscription.push(message)

    def __len__(self) -> int:
        return len(self._subscriptions)
