"""`--launch-chrome`: หา Chrome ตาม OS แล้วเปิดโหมด debug บนโปรไฟล์แยก bind 127.0.0.1 (SPEC 7)

จำลอง OS, ตัวแปรแวดล้อม และไฟล์ที่มีในเครื่องผ่าน dependency injection จึงทดสอบ Windows/macOS ได้บนทุกเครื่อง
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from inspector.__main__ import build_parser, launch_chrome_for, main
from inspector.chrome_launcher import ChromeLauncher

WINDOWS_ENV = {
    "PROGRAMFILES": r"C:\Program Files",
    "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
    "LOCALAPPDATA": r"C:\Users\student\AppData\Local",
}
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Spawned:
    """จด command ที่ถูกสั่งเปิดแทนการเปิดโปรแกรมจริง"""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> None:
        self.commands.append(list(command))


def launcher(system: str, installed: set[str], env: dict[str, str] | None = None, home: str = "/Users/student") -> ChromeLauncher:
    return ChromeLauncher(
        system=system,
        env=env or {},
        home=Path(home),
        exists=lambda path: path in {Path(name) for name in installed},
        which=lambda name: None,
        spawn=Spawned(),
    )


def found(launcher: ChromeLauncher) -> Path | None:
    """path ของ Chrome ที่หาเจอ (เทียบเป็น Path เพราะตัวคั่นต่างกันตาม OS ที่รัน test)"""
    executable = launcher.find_executable()
    return None if executable is None else Path(executable)


def test_finds_chrome_in_any_windows_install_location() -> None:
    per_user = r"C:\Users\student\AppData\Local\Google\Chrome\Application\chrome.exe"
    x86 = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    assert found(launcher("Windows", {per_user}, WINDOWS_ENV)) == Path(per_user)
    assert found(launcher("Windows", {x86, per_user}, WINDOWS_ENV)) == Path(x86)
    assert launcher("Windows", set(), WINDOWS_ENV).find_executable() is None


def test_finds_chrome_on_macos_including_the_users_own_applications_folder() -> None:
    own = "/Users/student/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert found(launcher("Darwin", {MAC_CHROME})) == Path(MAC_CHROME)
    assert found(launcher("Darwin", {own})) == Path(own)


def test_finds_chrome_on_linux_from_path() -> None:
    linux = ChromeLauncher(
        system="Linux", env={}, home=Path("/home/student"), exists=lambda path: True,
        which=lambda name: f"/usr/bin/{name}" if name == "chromium" else None, spawn=Spawned(),
    )
    assert found(linux) == Path("/usr/bin/chromium")


def test_command_uses_a_separate_profile_and_binds_cdp_to_localhost_only() -> None:
    mac = launcher("Darwin", {MAC_CHROME})
    assert mac.command(MAC_CHROME, "http://127.0.0.1:9333") == [
        MAC_CHROME,
        "--remote-debugging-port=9333",
        "--remote-debugging-address=127.0.0.1",
        "--user-data-dir=" + str(Path("/Users/student/.traffic-inspector-profile")),
        "--no-first-run",
        "https://www.advice.co.th",
    ]
    windows = launcher("Windows", set(), WINDOWS_ENV)
    profile = windows.command("chrome.exe", "http://127.0.0.1:9222")[3]
    assert profile == "--user-data-dir=" + str(Path(r"C:\Users\student\AppData\Local") / "TrafficInspectorProfile")


def test_launch_spawns_chrome_and_reports_when_it_is_missing() -> None:
    mac = launcher("Darwin", {MAC_CHROME})
    executable = mac.launch("http://127.0.0.1:9222")
    assert executable is not None and Path(executable) == Path(MAC_CHROME)
    assert isinstance(mac.spawn, Spawned) and mac.spawn.commands[0][0] == executable

    missing = launcher("Darwin", set())
    assert missing.launch("http://127.0.0.1:9222") is None
    assert isinstance(missing.spawn, Spawned) and missing.spawn.commands == []


def test_cli_explains_what_happened(capsys: pytest.CaptureFixture[str]) -> None:
    launch_chrome_for("http://127.0.0.1:9222", launcher("Darwin", {MAC_CHROME}))
    assert "เปิด Chrome" in capsys.readouterr().out

    launch_chrome_for("http://127.0.0.1:9222", launcher("Darwin", set()))
    out = capsys.readouterr().out
    assert "ไม่พบ Chrome" in out
    assert "--remote-debugging-port=9222" in out  # บอกคำสั่งให้เปิดเอง


def test_cli_refuses_to_launch_chrome_for_a_remote_cdp_url() -> None:
    with pytest.raises(SystemExit, match="127.0.0.1"):
        launch_chrome_for("http://192.168.1.20:9222", launcher("Darwin", {MAC_CHROME}))


@pytest.mark.parametrize("other", [["--demo"], ["--replay-file", "lab.json"]])
def test_launch_chrome_cannot_be_combined_with_modes_that_do_not_use_chrome(other: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--launch-chrome", *other])
    assert build_parser().parse_args(["--launch-chrome"]).launch_chrome


def test_manual_command_is_for_the_same_os_and_port() -> None:
    windows = launcher("Windows", set(), WINDOWS_ENV)
    assert windows.manual_command("http://127.0.0.1:9333").startswith("& ")  # PowerShell
    assert "--remote-debugging-port=9333" in windows.manual_command("http://127.0.0.1:9333")


def test_bad_arguments_stop_the_program_before_chrome_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = launcher("Darwin", {MAC_CHROME})
    monkeypatch.setattr("inspector.__main__.ChromeLauncher", lambda *args: opened)
    with pytest.raises(SystemExit):
        main(["--launch-chrome", "--preset", "ไม่มี-preset-นี้"])
    assert isinstance(opened.spawn, Spawned) and opened.spawn.commands == []
