"""สีของ badge ต้องอ่านออกบนโปรเจกเตอร์: contrast อย่างน้อย 4.5:1 (WCAG AA) ทั้งธีมสว่างและมืด"""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).parent.parent / "inspector" / "static" / "style.css").read_text(encoding="utf-8")

# (สีตัวอักษร, สีพื้น) ของ badge และข้อความเล็กที่ต้องอ่านออก
PAIRS = [
    ("--badge-fg", "--get"), ("--badge-fg", "--post"), ("--badge-fg", "--put"), ("--badge-fg", "--delete"),
    ("--badge-fg", "--other-method"),
    ("--badge-fg", "--ok"), ("--badge-fg", "--neutral"), ("--badge-fg", "--warn"), ("--badge-fg", "--bad"),
    ("--bad", "--bg"), ("--muted", "--bg"), ("--muted", "--surface"),
    ("--json-string", "--bg"), ("--json-number", "--bg"), ("--json-boolean", "--bg"), ("--json-null", "--bg"),
    ("--json-key", "--bg"),
]


def theme(selector: str) -> dict[str, str]:
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert block is not None, selector
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", block.group(1)))


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


LIGHT = theme(":root")
DARK = {**LIGHT, **theme(':root[data-theme="dark"]')}


@pytest.mark.parametrize("colors", [LIGHT, DARK], ids=["light", "dark"])
@pytest.mark.parametrize(("fg", "bg"), PAIRS)
def test_badges_and_small_text_reach_4_5_to_1(colors: dict[str, str], fg: str, bg: str) -> None:
    assert contrast(colors[fg], colors[bg]) >= 4.5, f"{fg} บน {bg}"

