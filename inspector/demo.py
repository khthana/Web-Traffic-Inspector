"""ตัวป้อน Capture event ปลอม (`--demo`) ใช้ลองหน้า Inspector โดยไม่ต้องมี Chrome"""

import asyncio
import itertools
import json
import time

from inspector.capture_events import RequestStarted, ResponseReceived
from inspector.pipeline import InspectorPipeline

_ENDPOINTS = [
    ("POST", "cart/get", 200, {"status": "SUCCESS", "statusCode": "200", "data": [], "message": ""}),
    ("POST", "product/category/data", 200, {"status": "SUCCESS", "data": [{"sku": "NB-001", "price": 18990}]}),
    ("GET", "get-category", 200, {"categories": ["notebooks", "monitors"]}),
    ("POST", "product/get", 404, {"status": "NOT_FOUND"}),
]


async def feed_demo_events(pipeline: InspectorPipeline, interval_s: float = 2.0) -> None:
    """ส่ง request → response ปลอมเข้า pipeline ทุก `interval_s` วินาที"""
    for n in itertools.count(1):
        method, name, status, body = _ENDPOINTS[n % len(_ENDPOINTS)]
        key = f"demo-{n}"
        started = time.time() * 1000
        pipeline.handle(
            RequestStarted(
                request_key=key,
                tab_id="demo-tab",
                page_url="https://www.advice.co.th/product/notebooks",
                ts=started,
                method=method,
                url=f"https://www.advice.co.th/_advice-api/api/v1.0.0/{name}",
                resource_type="fetch",
                headers={"content-type": "application/json"},
                post_data='{"page": 1}' if method == "POST" else None,
            )
        )
        await asyncio.sleep(0.6)  # ให้เห็นสถานะ "รอคำตอบ…" สักครู่
        pipeline.handle(
            ResponseReceived(
                request_key=key,
                ts=time.time() * 1000,
                status=status,
                status_text="OK" if status == 200 else "Not Found",
                headers={"content-type": "application/json"},
                body=json.dumps(body, ensure_ascii=False),
            )
        )
        await asyncio.sleep(interval_s)
