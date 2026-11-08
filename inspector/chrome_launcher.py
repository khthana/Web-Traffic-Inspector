"""`--launch-chrome`: หา Chrome ที่ติดตั้งไว้ตาม OS แล้วเปิดโหมด debug ให้ (SPEC 7)

ใช้โปรไฟล์แยก (Chrome 136+ ไม่ยอมเปิดพอร์ต debug บนโปรไฟล์ปกติ และไม่ปนกับบัญชีส่วนตัว)
และเปิดพอร์ต CDP ให้เฉพาะเครื่องนี้ (127.0.0.1) เท่านั้น
"""

import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from inspector.chrome import (
    PROFILE_NAME_POSIX,
    PROFILE_NAME_WINDOWS,
    START_URL,
    cdp_port,
    chrome_launch_command,
    debug_flags,
)

Spawn = Callable[[Sequence[str]], object]

MAC_APP = "Google Chrome.app/Contents/MacOS/Google Chrome"
LINUX_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


def spawn_detached(command: Sequence[str]) -> subprocess.Popen[bytes]:
    """เปิด Chrome เป็นโปรเซสแยก: กด Ctrl+C ปิด Inspector แล้ว Chrome ยังเปิดอยู่"""
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


class ChromeLauncher:
    """หาไฟล์ Chrome, ประกอบคำสั่ง และเปิด Chrome โหมด debug

    สอนแนวคิด: dependency injection — OS, ตัวแปรแวดล้อม, การเช็กว่ามีไฟล์ และการเปิดโปรเซส ส่งเข้ามาทาง constructor
    test จึงจำลองเครื่อง Windows หรือ macOS ได้บนทุกเครื่อง โดยไม่ต้องเปิด Chrome จริง
    """

    def __init__(
        self,
        system: str,
        env: Mapping[str, str],
        home: Path,
        exists: Callable[[Path], bool] = Path.exists,
        which: Callable[[str], str | None] = shutil.which,
        spawn: Spawn = spawn_detached,
    ) -> None:
        self.system = system
        self.env = env
        self.home = home
        self.exists = exists
        self.which = which
        self.spawn = spawn

    def candidates(self) -> list[Path]:
        """ที่ที่ Chrome มักติดตั้งไว้ เรียงตามที่ควรลองก่อน"""
        if self.system == "Windows":
            roots = [self.env.get(name) for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
            return [Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe" for root in roots if root]
        if self.system == "Darwin":
            return [Path("/Applications") / MAC_APP, self.home / "Applications" / MAC_APP]
        return [Path(found) for found in map(self.which, LINUX_NAMES) if found]

    def find_executable(self) -> str | None:
        return next((str(path) for path in self.candidates() if self.exists(path)), None)

    def profile_dir(self) -> Path:
        if self.system == "Windows":
            return Path(self.env.get("LOCALAPPDATA", str(self.home))) / PROFILE_NAME_WINDOWS
        return self.home / PROFILE_NAME_POSIX

    def command(self, executable: str, cdp_url: str) -> list[str]:
        return [executable, *debug_flags(cdp_port(cdp_url), str(self.profile_dir())), START_URL]

    def manual_command(self, cdp_url: str) -> str:
        """คำสั่งให้ผู้ใช้คัดลอกไปเปิดเองใน terminal ของ OS นี้ (ใช้เมื่อหา Chrome ไม่เจอ)"""
        return chrome_launch_command(cdp_url, self.system)

    def launch(self, cdp_url: str) -> str | None:
        """เปิด Chrome แล้วคืน path ของ Chrome ที่เปิด หรือ None ถ้าไม่พบ Chrome ในเครื่อง"""
        executable = self.find_executable()
        if executable is not None:
            self.spawn(self.command(executable, cdp_url))
        return executable
