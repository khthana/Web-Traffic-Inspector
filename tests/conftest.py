"""Test harness ของ seam หลัก: ป้อน Capture event ปลอม แล้วสังเกตผลผ่าน REST และ WebSocket"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import anyio
import pytest
from chrome_support import ChromeProcess, find_chrome
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture_events import CaptureEvent
from inspector.chrome import chrome_launch_command
from inspector.correlator import Correlator
from inspector.filters import PRESETS_DIR, FilterSettings, load_presets
from inspector.pipeline import InspectorPipeline
from inspector.redactor import Redactor
from inspector.store import EventStore


class Harness:
    """ประกอบ Inspector ทั้งตัว (ยกเว้นส่วนที่ต้องใช้ Chrome) ให้ test ใช้"""

    def __init__(self, client: TestClient, pipeline: InspectorPipeline) -> None:
        self.client = client
        self.pipeline = pipeline

    def feed(self, *events: CaptureEvent) -> None:
        """ส่ง Capture event เข้า pipeline บน event loop เดียวกับ app"""
        assert self.client.portal is not None
        for event in events:
            self.client.portal.call(self.pipeline.handle, event)

    def call(self, func: Callable[..., object], *args: object) -> None:
        """เรียกเมธอดของ pipeline บน event loop เดียวกับ app"""
        assert self.client.portal is not None
        self.client.portal.call(func, *args)

    @staticmethod
    def receive(ws: WebSocketTestSession, timeout: float = 2.0) -> Any:
        """อ่านข้อความ JSON ถัดไปจาก /ws ถ้าไม่มีข้อความภายใน timeout ให้ test fail แทนที่จะค้าง"""

        async def next_message() -> Any:
            with anyio.fail_after(timeout):
                return await ws._send_rx.receive()

        message = ws.portal.call(next_message)
        return json.loads(message["text"])

    def get(self, path: str) -> Any:
        response = self.client.get(path)
        assert response.status_code == 200, response.text
        return response.json()


@contextmanager
def build_harness(max_exchanges: int = 500, preset: str = "all") -> Iterator[Harness]:
    """ประกอบ Inspector ทั้งตัวด้วยค่าที่เลือกได้ (เหมือน CLI `--max-exchanges` และ `--preset`)"""
    store = EventStore(max_exchanges=max_exchanges)
    broadcaster = Broadcaster()
    pipeline = InspectorPipeline(
        store=store,
        broadcaster=broadcaster,
        redactor=Redactor(),
        correlator=Correlator(window_ms=1500),
        filters=FilterSettings(load_presets(PRESETS_DIR), selected=preset),
        chrome_launch_command=chrome_launch_command("http://127.0.0.1:9222"),
    )
    app = create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)
    with TestClient(app) as client:
        yield Harness(client, pipeline)


@pytest.fixture
def harness() -> Iterator[Harness]:
    with build_harness() as built:
        yield built


@pytest.fixture
def chrome() -> Iterator[ChromeProcess]:
    """Chrome แบบ headless ของจริง (เฉพาะ test ที่ mark `chrome`) ถ้าไม่มี Chrome ในเครื่องจะข้าม test"""
    executable = find_chrome()
    if executable is None:
        pytest.skip("ไม่พบ Chrome ในเครื่องนี้")
    process = ChromeProcess(executable)
    yield process
    process.cleanup()
