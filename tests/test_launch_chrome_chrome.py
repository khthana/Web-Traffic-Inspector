"""`--launch-chrome` กับ Chrome จริง: เปิดแล้วพอร์ต CDP ตอบที่ 127.0.0.1 (`pytest -m chrome`)

ใช้ home/LOCALAPPDATA ชั่วคราว จึงไม่แตะโปรไฟล์จริงของเครื่อง และเติม --headless=new ไม่ให้มีหน้าต่างเด้ง
"""

import json
import os
import platform
import subprocess
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import pytest
from chrome_support import free_port

from inspector.chrome_launcher import ChromeLauncher

pytestmark = pytest.mark.chrome


def cdp_version(port: int, timeout_s: float = 15) -> dict[str, str]:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                version: dict[str, str] = json.load(response)
                return version
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def test_launch_chrome_opens_a_debuggable_chrome_on_a_separate_profile(tmp_path: Path) -> None:
    started: list[subprocess.Popen[bytes]] = []

    def spawn_headless(command: Sequence[str]) -> None:
        started.append(subprocess.Popen([*command, "--headless=new"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    env = {**os.environ, "LOCALAPPDATA": str(tmp_path)}
    launcher = ChromeLauncher(platform.system(), env, tmp_path, spawn=spawn_headless)
    if launcher.find_executable() is None:
        pytest.skip("ไม่พบ Chrome ในเครื่อง")

    port = free_port()
    try:
        launcher.launch(f"http://127.0.0.1:{port}")
        assert "Chrome" in cdp_version(port)["Browser"]
        assert launcher.profile_dir().is_dir()  # Chrome สร้างโปรไฟล์แยกไว้ในที่ชั่วคราว
    finally:
        for process in started:
            process.kill()
            process.wait(timeout=10)
