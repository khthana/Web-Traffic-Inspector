"""FastAPI app: เสิร์ฟหน้า UI, REST API และ WebSocket `/ws`

สอนแนวคิด: app factory — `create_app(...)` รับ object ทั้งหมดจากข้างนอก ไม่มี global state
เปิด `/docs` เพื่อดูตัวอย่าง REST API ที่ FastAPI สร้างให้อัตโนมัติ
"""

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from inspector.broadcaster import Broadcaster
from inspector.code_snippets import code_snippets
from inspector.models import CodeSnippet, FilterUpdate, FilterView, HttpExchange, InspectorStatus, Recording
from inspector.pipeline import InspectorPipeline
from inspector.recording import download_name
from inspector.store import EventStore

STATIC_DIR = Path(__file__).parent / "static"


def create_app(pipeline: InspectorPipeline, store: EventStore, broadcaster: Broadcaster) -> FastAPI:
    """สร้าง FastAPI app จาก object ที่ประกอบไว้แล้ว"""
    app = FastAPI(title="Web Traffic Inspector", description="ดู traffic ของ Chrome เพื่อการเรียนรู้")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def get_status() -> InspectorStatus:
        """สถานะการเชื่อมต่อ Chrome และการเก็บข้อมูล"""
        return pipeline.status

    @app.get("/api/interactions")
    def get_interactions() -> dict[str, Any]:
        """ประวัติทั้งหมด (Interaction + Exchange)"""
        return pipeline.snapshot()

    @app.get("/api/exchanges/{exchange_id}")
    def get_exchange(exchange_id: str) -> HttpExchange:
        """รายละเอียดของ Exchange เดียว"""
        exchange = store.get_exchange(exchange_id)
        if exchange is None:
            raise HTTPException(status_code=404, detail="ไม่พบ Exchange นี้ (อาจถูกล้างไปแล้ว)")
        return exchange

    @app.get("/api/exchanges/{exchange_id}/code")
    def get_code(exchange_id: str) -> list[CodeSnippet]:
        """แท็บ "โค้ด": Copy as curl / Python requests / JavaScript fetch (ไม่มี header และค่าที่ถูกซ่อน)"""
        return code_snippets(get_exchange(exchange_id))

    @app.get("/api/export", response_model=Recording)
    def export(interaction_id: str | None = None) -> JSONResponse:
        """ดาวน์โหลด Recording (JSON ที่ผ่าน Redaction แล้ว) ของทั้ง session หรือ Interaction เดียว"""
        try:
            recording = pipeline.recording(interaction_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="ไม่พบ Interaction นี้ (อาจถูกล้างไปแล้ว)") from error
        file_name = download_name(recording, interaction_id)
        return JSONResponse(
            recording.model_dump(mode="json"),
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    def refuse_while_playing() -> None:
        """Recording playback ไม่มี traffic ใหม่ให้หยุด และล้างแล้วโหลดไฟล์กลับไม่ได้ (UI ซ่อนปุ่มอยู่แล้ว)"""
        if pipeline.status.mode == "playback":
            raise HTTPException(status_code=409, detail="กำลังเปิด Recording อยู่: หยุดหรือล้างไม่ได้")

    @app.post("/api/pause")
    def pause() -> InspectorStatus:
        """หยุดเก็บชั่วคราว (request และคลิกใหม่ถูกทิ้ง ไม่ได้บล็อกเว็บ)"""
        refuse_while_playing()
        return pipeline.pause()

    @app.post("/api/resume")
    def resume() -> InspectorStatus:
        """เริ่มเก็บต่อ"""
        refuse_while_playing()
        return pipeline.resume()

    @app.post("/api/clear")
    def clear() -> InspectorStatus:
        """ล้างประวัติทั้งหมดและ Hidden count"""
        refuse_while_playing()
        return pipeline.clear()

    @app.get("/api/filters")
    def get_filters() -> FilterView:
        """Preset ที่เลือกได้ ตัวที่เลือกอยู่ กฎของมัน และ Blocklist พื้นฐาน (ถอดออกไม่ได้)"""
        return pipeline.filter_view()

    @app.put("/api/filters")
    def put_filters(update: FilterUpdate) -> FilterView:
        """เลือก Preset หรือแก้กฎของ `custom` (อยู่ในหน่วยความจำเท่านั้น key ที่ต้องซ่อนเพิ่มได้อย่างเดียว)"""
        try:
            return pipeline.change_filters(update)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        """ส่งข้อมูลทางเดียว: server → client"""
        await ws.accept()
        subscription = broadcaster.subscribe({"type": "snapshot", "data": pipeline.snapshot()})

        async def write() -> None:
            while True:
                await ws.send_json(await subscription.next())

        writer = asyncio.create_task(write())
        try:
            while True:
                await ws.receive_text()  # รอจน client ปิดการเชื่อมต่อ
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unsubscribe(subscription)
            writer.cancel()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
