"""ตัวป้อน Capture event ปลอม (`--demo`) ใช้ลองหน้า Inspector โดยไม่ต้องมี Chrome

วนเล่นฉากสั้นๆ ซ้ำไปเรื่อยๆ: เปิดหน้า → คลิกใส่ตะกร้า → คลิกที่ไม่มี API call → polling เบื้องหลัง
→ คลิกลิงก์ที่เปลี่ยนหน้า
"""

import asyncio
import itertools
import json
from typing import Any

from inspector.capture_events import ClickCaptured, NavigationOccurred, RequestStarted, ResponseReceived
from inspector.clock import now_ms
from inspector.models import ElementInfo
from inspector.pipeline import InspectorPipeline

TAB = "demo-tab"
SITE = "https://www.advice.co.th"
API = f"{SITE}/_advice-api/api/v1.0.0"



class DemoScript:
    """เล่นฉากตัวอย่างผ่าน pipeline เหมือนมี Chrome จริง

    สอนแนวคิด: encapsulation — เก็บตัวนับ request และหน้าปัจจุบันไว้ใน object ไม่ใช้ตัวแปร global
    """

    def __init__(self, pipeline: InspectorPipeline) -> None:
        self._pipeline = pipeline
        self._keys = itertools.count(1)
        self._page = f"{SITE}/"

    async def run_forever(self) -> None:
        while True:
            await self.navigate(f"{SITE}/")
            await self.call("GET", "get-category", 200, {"categories": ["notebooks", "monitors"]})
            await self.call("POST", "cart/get", 200, {"status": "SUCCESS", "data": []})
            await self.call("POST", "collect", 204, {}, url="https://region1.google-analytics.com/g/collect")
            await asyncio.sleep(3)

            await self.click("button", "ใส่ตะกร้า")
            await self.call("POST", "cart/add", 200, {"status": "SUCCESS", "cart_count": 1})
            await self.call("POST", "cart/get", 200, {"status": "SUCCESS", "data": [{"sku": "NB-001"}]})
            await asyncio.sleep(3)

            await self.click("button", "ดูรูปถัดไป")  # ทำงานในเบราว์เซอร์อย่างเดียว ไม่มี API call
            await self.call("POST", "collect", 204, {}, url="https://www.clarity.ms/collect")  # แต่ยังถูก track
            await asyncio.sleep(5)

            await self.call("GET", "notification/count", 200, {"unread": 0})  # polling เบื้องหลัง
            await asyncio.sleep(3)

            await self.click("a", "โน้ตบุ๊ก", href=f"{SITE}/product/notebooks")
            await asyncio.sleep(0.3)
            await self.navigate(f"{SITE}/product/notebooks")  # เกิดหลังคลิกไม่นาน จึงรวมเข้า Click interaction
            await self.call("POST", "product/category/data", 200, {"status": "SUCCESS", "data": [{"price": 18990}]})
            await self.call("POST", "product/get", 404, {"status": "NOT_FOUND"})
            await asyncio.sleep(5)

    async def click(self, tag: str, text: str, href: str | None = None) -> None:
        element = ElementInfo(tag=tag, text=text, selector=f"{tag}.demo", href=href)
        self._pipeline.handle(ClickCaptured(tab_id=TAB, page_url=self._page, ts=now_ms(), element=element))
        await asyncio.sleep(0.2)

    async def navigate(self, url: str) -> None:
        self._page = url
        self._pipeline.handle(NavigationOccurred(tab_id=TAB, url=url, ts=now_ms()))

    async def call(self, method: str, name: str, status: int, body: dict[str, Any], url: str | None = None) -> None:
        key = f"demo-{next(self._keys)}"
        self._pipeline.handle(
            RequestStarted(
                request_key=key,
                tab_id=TAB,
                page_url=self._page,
                ts=now_ms(),
                method=method,
                url=url or f"{API}/{name}",
                resource_type="fetch",
                headers={"content-type": "application/json", "cookie": "PHPSESSID=demo-session-value"},
                post_data='{"page": 1}' if method == "POST" else None,
            )
        )
        await asyncio.sleep(0.4)  # ให้เห็นสถานะ "รอคำตอบ…" สักครู่
        self._pipeline.handle(
            ResponseReceived(
                request_key=key,
                ts=now_ms(),
                status=status,
                status_text="OK" if status == 200 else "Not Found",
                headers={"content-type": "application/json"},
                body=json.dumps(body, ensure_ascii=False),
            )
        )


async def feed_demo_events(pipeline: InspectorPipeline) -> None:
    """ป้อนฉากตัวอย่างเข้า pipeline ไปเรื่อยๆ จนกว่าจะถูกยกเลิก"""
    await DemoScript(pipeline).run_forever()
