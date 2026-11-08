"""สคริปต์ดับเบิลคลิกและ README ต้องตรงกับโค้ด: flag ของ Chrome ชุดเดียวกับ --launch-chrome และตาราง CLI ครบทุก option"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from inspector.__main__ import build_parser
from inspector.chrome import DEFAULT_CDP_PORT, PROFILE_NAME_POSIX, PROFILE_NAME_WINDOWS, START_URL, debug_flags

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
