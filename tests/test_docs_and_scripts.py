"""สคริปต์ดับเบิลคลิกและ README ต้องตรงกับโค้ด: flag ของ Chrome ชุดเดียวกับ --launch-chrome และตาราง CLI ครบทุก option"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from inspector.__main__ import build_parser
from inspector.chrome import (
    DEFAULT_CDP_PORT,
    PROFILE_NAME_POSIX,
    PROFILE_NAME_WINDOWS,
    START_URL,
    chrome_launch_command,
    debug_flags,
)

ROOT = Path(__file__).resolve().parent.parent
WINDOWS_SCRIPT = ROOT / "scripts" / "start_chrome.bat"
MAC_SCRIPT = ROOT / "scripts" / "start_chrome.command"
README = ROOT / "README.md"


def words(script: Path) -> list[str]:
    """คำทั้งหมดในสคริปต์ (ตัดเครื่องหมายต่อบรรทัด ^ และ \\ ออก)"""
    return script.read_text(encoding="utf-8").replace("^", " ").replace("\\\n", " ").split()


@pytest.mark.parametrize(
    ("script", "profile"),
    [
        (WINDOWS_SCRIPT, rf'"%LOCALAPPDATA%\{PROFILE_NAME_WINDOWS}"'),
        (MAC_SCRIPT, f'"$HOME/{PROFILE_NAME_POSIX}"'),
    ],
)
def test_scripts_open_chrome_with_the_same_flags_as_launch_chrome(script: Path, profile: str) -> None:
    script_words = words(script)
    flags = debug_flags(DEFAULT_CDP_PORT, profile)
    start = script_words.index(flags[0])
    assert script_words[start : start + len(flags) + 1] == [*flags, START_URL]


def test_windows_script_has_windows_line_endings() -> None:
    # cmd.exe อ่าน .bat ที่ขึ้นบรรทัดแบบ LF ผิดได้ ส่วน .gitattributes คุมไม่ให้ git แปลงกลับ
    data = WINDOWS_SCRIPT.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n") > 0


def test_mac_script_is_executable_shell() -> None:
    assert MAC_SCRIPT.read_bytes().startswith(b"#!/bin/sh\n")
    assert b"\r" not in MAC_SCRIPT.read_bytes()
    assert "nohup" in words(MAC_SCRIPT)  # ปิดหน้าต่าง Terminal แล้ว Chrome ไม่ปิดตาม
    mode = subprocess.run(
        ["git", "ls-files", "--stage", str(MAC_SCRIPT)], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert mode.startswith("100755"), "ต้องมี executable bit ใน git (git update-index --chmod=+x) ไม่อย่างนั้น Finder เปิดไม่ได้"
    sh = shutil.which("sh")
    if sh is not None:
        subprocess.run([sh, "-n", str(MAC_SCRIPT)], check=True)


def test_readme_cli_table_lists_every_option() -> None:
    table = {row.group(1) for row in re.finditer(r"^\| `(--[a-z-]+)", README.read_text(encoding="utf-8"), re.M)}
    options = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }
    assert table == options


def test_readme_covers_what_a_new_student_needs() -> None:
    readme = README.read_text(encoding="utf-8")
    for must in (
        "pip install -r requirements.txt",
        "playwright install",  # บอกว่าไม่ต้องรัน
        "scripts/start_chrome.bat",
        "scripts/start_chrome.command",
        "9222",
        "127.0.0.1",
        "1500",  # correlation window: จับคู่ด้วยเวลา
        "--replay-file",
        "Export",  # ชื่อปุ่มบนหน้าจอจริง
        "ExecutionPolicy",  # PowerShell มักบล็อก Activate.ps1 บนเครื่องใหม่
    ):
        assert must in readme, must
    assert readme.count("- [ ]") >= 10  # checklist ทดสอบกับเว็บจริง (SPEC 9.2)


def run_mac_script(home: Path) -> subprocess.CompletedProcess[str]:
    """รันสคริปต์ macOS ด้วย sh โดยให้ HOME ชี้ไปที่โฟลเดอร์ทดสอบ (ไม่แตะโปรไฟล์จริงของเครื่อง)"""
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("ไม่มี sh ในเครื่องนี้")
    if Path("/Applications/Google Chrome.app").exists():
        pytest.skip("เครื่องนี้มี Chrome ใน /Applications: สคริปต์จะเปิด Chrome จริงแทนตัวปลอม")
    env = {"HOME": home.as_posix(), "PATH": os.environ.get("PATH", "")}  # macOS เก็บ nohup ไว้ที่ /usr/bin
    return subprocess.run([sh, MAC_SCRIPT.as_posix()], env=env, capture_output=True, encoding="utf-8", timeout=10)


def test_mac_script_starts_chrome_from_home_applications_with_debug_flags(tmp_path: Path) -> None:
    # ติดตั้ง Chrome ปลอมใน ~/Applications ที่จดอาร์กิวเมนต์ที่ได้รับไว้
    received = tmp_path / "received.txt"
    chrome = tmp_path / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    chrome.parent.mkdir(parents=True)
    chrome.write_text(f'#!/bin/sh\nfor arg in "$@"; do echo "$arg"; done > "{received.as_posix()}"\n', newline="\n")
    chrome.chmod(0o755)

    result = run_mac_script(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "python3 -m inspector" in result.stdout
    deadline = time.monotonic() + 5  # Chrome ถูกเปิดแบบ nohup ... & จึงอาจเขียนไฟล์หลังสคริปต์จบ
    while not (received.exists() and received.read_text(encoding="utf-8").endswith(START_URL + "\n")):
        assert time.monotonic() < deadline, "Chrome ปลอมไม่ถูกเรียกภายใน 5 วินาที (สคริปต์หา nohup หรือ Chrome ไม่เจอ?)"
        time.sleep(0.05)
    args = received.read_text(encoding="utf-8").splitlines()
    profiles = [arg for arg in args if arg.startswith("--user-data-dir=")]
    # sh บน Windows (Git Bash) เขียน HOME เป็น /tmp/... จึงเทียบแค่ท้าย path ของโปรไฟล์
    assert len(profiles) == 1 and profiles[0].endswith(f"/{tmp_path.name}/{PROFILE_NAME_POSIX}")
    expected = [*debug_flags(DEFAULT_CDP_PORT, "PROFILE"), START_URL]
    assert [arg for arg in args if arg not in profiles] == [arg for arg in expected if "PROFILE" not in arg]


def test_mac_script_explains_when_chrome_is_not_installed(tmp_path: Path) -> None:
    result = run_mac_script(tmp_path)
    assert result.returncode == 1
    assert "ไม่พบ Google Chrome" in result.stdout


def test_mac_command_shown_by_inspector_matches_the_script() -> None:
    # คำสั่งที่ขึ้นใน "ไม่พบ Chrome" ต้องทำแบบเดียวกับสคริปต์: nohup ... & ปิด Terminal แล้ว Chrome ไม่ปิดตาม
    script_words = words(MAC_SCRIPT)
    in_script = script_words[script_words.index("nohup") : script_words.index("&") + 1]
    shown = chrome_launch_command(f"http://127.0.0.1:{DEFAULT_CDP_PORT}", "Darwin")
    mac_chrome = '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"'
    assert mac_chrome in shown
    assert shown.replace(mac_chrome, '"$CHROME"').split() == in_script
