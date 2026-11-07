"""Export เป็น Recording และ Recording playback (`--replay-file`) ผ่าน seam หลัก"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from chrome_support import free_port
from conftest import Harness, build_harness

from inspector.capture_events import ClickCaptured, RequestStarted, ResponseReceived
from inspector.models import ElementInfo, Recording
from inspector.recording import read_recording

T0 = 1_700_000_000_000.0
PAGE = "https://shop.example/"
SECRET = "sess-1234567890"


def shopping(harness: Harness) -> None:
    """คลิก "ใส่ตะกร้า" แล้วมี request หลักพร้อมคำตอบ + tracking ที่ถูกซ่อน + request เบื้องหลัง"""
    element = ElementInfo(tag="button", text="ใส่ตะกร้า", selector="button.buy")
    harness.feed(
        ClickCaptured(tab_id="tab-1", page_url=PAGE, ts=T0, element=element),
        RequestStarted(
            request_key="cart", tab_id="tab-1", page_url=PAGE, ts=T0 + 10, method="POST",
            url="https://shop.example/api/cart/add", resource_type="fetch",
            headers={"cookie": f"session={SECRET}", "content-type": "application/json"},
            post_data='{"sku": "NB-01", "qty": 1}',
        ),
        RequestStarted(
            request_key="t", tab_id="tab-1", page_url=PAGE, ts=T0 + 20, method="POST",
            url="https://www.clarity.ms/collect", resource_type="fetch",
        ),
        ResponseReceived(
            request_key="cart", ts=T0 + 190, status=200, status_text="OK",
            headers={"content-type": "application/json", "set-cookie": f"session={SECRET}"},
            body='{"status": "SUCCESS"}',
        ),
        RequestStarted(
            request_key="poll", tab_id="tab-1", page_url=PAGE, ts=T0 + 30_000, method="GET",
            url="https://shop.example/api/notifications", resource_type="xhr",
        ),
    )


def history(harness: Harness) -> dict[str, Any]:
    data = harness.get("/api/interactions")
    return {"interactions": data["interactions"], "exchanges": data["exchanges"]}


def test_export_downloads_the_whole_session_as_a_redacted_recording(harness: Harness) -> None:
    shopping(harness)

    response = harness.client.get("/api/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    assert ".json" in response.headers["content-disposition"]
    recording = response.json()
    assert {"interactions": recording["interactions"], "exchanges": recording["exchanges"]} == history(harness)
    assert len(recording["exchanges"]) == 3  # Hidden exchange ไปด้วย (เปิดกลับมาแล้วยังกดดูที่ซ่อนได้)
    assert SECRET not in response.text  # ผ่าน Redaction แล้ว


def test_export_of_one_interaction_has_only_its_exchanges(harness: Harness) -> None:
    shopping(harness)
    click = next(i for i in history(harness)["interactions"] if i["kind"] == "click")

    recording = harness.get(f"/api/export?interaction_id={click['id']}")

    assert [i["id"] for i in recording["interactions"]] == [click["id"]]
    assert sorted(e["id"] for e in recording["exchanges"]) == sorted(click["exchange_ids"])
    assert harness.client.get("/api/export?interaction_id=it_9999").status_code == 404


def test_exported_recording_opens_again_with_the_same_interactions_and_exchanges(tmp_path: Path) -> None:
    with build_harness() as live:
        shopping(live)
        original = history(live)
        exported = live.client.get("/api/export").text
    path = tmp_path / "lab-01.json"
    path.write_text(exported, encoding="utf-8")

    with build_harness(recording=read_recording(path), recording_file=path.name) as playback:
        assert history(playback) == original
        status = playback.get("/api/status")
        assert status["mode"] == "playback"
        assert status["recording_file"] == "lab-01.json"
        assert status["hidden_count"] == 1
        with playback.client.websocket_connect("/ws") as ws:
            snapshot = playback.receive(ws)["data"]
            assert snapshot["exchanges"] == original["exchanges"]


def test_recording_playback_follows_the_chosen_preset(tmp_path: Path) -> None:
    with build_harness() as live:
        shopping(live)
        exported = Recording.model_validate_json(live.client.get("/api/export").text)

    with build_harness(preset="advice", recording=exported, recording_file="x.json") as playback:
        assert all(e["hidden"] for e in history(playback)["exchanges"])  # shop.example ไม่อยู่ใน Focus ของ advice


def test_unreadable_recording_explains_what_is_wrong(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"interactions": "ไม่ใช่ list"}', encoding="utf-8")
    with pytest.raises(ValueError, match="broken.json"):
        read_recording(broken)
    with pytest.raises(ValueError, match="ไม่พบไฟล์"):
        read_recording(tmp_path / "missing.json")


def test_replay_file_starts_without_ever_contacting_chrome(tmp_path: Path) -> None:
    """เปิดโปรแกรมจริงด้วย --replay-file โดยชี้ --cdp-url ไปที่พอร์ตที่เราเฝ้าดู: ต้องไม่มีใครมาเชื่อมเลย"""
    with build_harness() as live:
        shopping(live)
        path = tmp_path / "lab-01.json"
        path.write_text(live.client.get("/api/export").text, encoding="utf-8")

    watched = socket.socket()
    watched.bind(("127.0.0.1", 0))
    watched.listen()
    watched.settimeout(0.2)
    cdp_url = f"http://127.0.0.1:{watched.getsockname()[1]}"
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "inspector", "--replay-file", str(path), "--port", str(port), "--no-open", "--cdp-url", cdp_url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        status = wait_for_status(f"http://127.0.0.1:{port}/api/status")
        assert status["mode"] == "playback"
        assert status["recording_file"] == "lab-01.json"
        deadline = time.time() + 3  # ChromeConnector ลองเชื่อมทุก 2 วินาที: รอให้เกินรอบหนึ่ง
        while time.time() < deadline:
            with pytest.raises(TimeoutError):
                watched.accept()
    finally:
        process.terminate()
        process.wait(timeout=10)
        watched.close()


def wait_for_status(url: str) -> Any:
    deadline = time.time() + 15
    while True:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return json.loads(response.read())
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.2)
