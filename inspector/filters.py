"""การกรอง: ตัดสินว่า Exchange ไหนเป็น Hidden exchange และเพราะอะไร

ตรวจสองชั้นตามลำดับ: Blocklist (ซ่อนเสมอ เหตุผล `tracking: <host>`)
แล้วค่อย Focus rule ของ Preset (ซ่อนสิ่งที่ไม่ตรง เหตุผล `นอกโฟกัส: preset <ชื่อ>`)
Preset อยู่ในไฟล์ `presets/<ชื่อ>.json` ส่วน Preset `custom` อยู่ในหน่วยความจำเท่านั้น
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from inspector.models import FilterRules, FilterView, HttpExchange, Preset, PresetChoice

PRESETS_DIR = Path(__file__).parent.parent / "presets"
CUSTOM = "custom"
CUSTOM_LABEL = "กำหนดเอง…"

# Blocklist พื้นฐาน (SPEC ข้อ 4.3) ฝังในโค้ด ถอดออกไม่ได้
BASE_BLOCK_HOSTS = (
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "doubleclick.net",
    "clarity.ms",
    "facebook.com",
    "facebook.net",
    "analytics.tiktok.com",
    "analytics.ahrefs.com",
)
BASE_BLOCK_PATHS = (("*.run.app", "/events"), ("", "/cdn-cgi/"))  # (host, path prefix) host ว่าง = ทุก host


def host_matches(host: str, pattern: str) -> bool:
    """`example.com` ตรงกับ example.com และ subdomain ทุกตัว `*.run.app` ตรงกับ subdomain ของ run.app"""
    host, pattern = host.lower(), pattern.lower().strip()
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    return host == pattern or host.endswith("." + pattern)


class FilterRule(ABC):
    """กฎการกรองหนึ่งข้อ

    สอนแนวคิด: abstract base class + template method — `matches` เขียนไว้ที่นี่ที่เดียว
    subclass แค่บอกว่า Exchange นี้ "ตรงกฎ" ไหมผ่าน `covers`
    กฎแบบ Blocklist ซ่อนตัวที่ตรง ส่วนกฎแบบ Focus (มี `focus_preset`) ซ่อนตัวที่ไม่ตรง
    """

    def __init__(self, focus_preset: str | None = None) -> None:
        self.focus_preset = focus_preset

    def matches(self, exchange: HttpExchange) -> str | None:
        """คืน Hidden reason ถ้ากฎนี้ทำให้ Exchange ถูกซ่อน ไม่อย่างนั้นคืน None"""
        covered = self.covers(exchange)
        if self.focus_preset is None:
            return f"tracking: {exchange.request.host}" if covered else None
        return None if covered else f"นอกโฟกัส: preset {self.focus_preset}"

    @abstractmethod
    def covers(self, exchange: HttpExchange) -> bool:
        """Exchange นี้ตรงกับกฎไหม"""


class HostBlockRule(FilterRule):
    """ตรงเมื่อ host อยู่ในรายการ (นับ subdomain ด้วย)

    สอนแนวคิด: inheritance — ได้ `matches` มาจาก FilterRule เขียนเองแค่ `covers`
    """

    def __init__(self, hosts: Sequence[str], focus_preset: str | None = None) -> None:
        super().__init__(focus_preset)
        self.hosts = tuple(hosts)

    def covers(self, exchange: HttpExchange) -> bool:
        return any(host_matches(exchange.request.host, pattern) for pattern in self.hosts)


class PathPrefixRule(FilterRule):
    """ตรงเมื่อ path ขึ้นต้นด้วย prefix ตัวใดตัวหนึ่ง (และถ้าระบุ host ต้องเป็น host นั้นด้วย)

    สอนแนวคิด: inheritance — กฎเดียวกันใช้ได้ทั้งเป็น Blocklist (`/cdn-cgi/`) และ Focus rule (`/api/`)
    """

    def __init__(
        self, prefixes: Sequence[str], hosts: Sequence[str] = (), focus_preset: str | None = None
    ) -> None:
        super().__init__(focus_preset)
        self.prefixes = tuple(prefixes)
        self.hosts = tuple(hosts)

    def covers(self, exchange: HttpExchange) -> bool:
        if self.hosts and not any(host_matches(exchange.request.host, pattern) for pattern in self.hosts):
            return False
        return exchange.request.path.startswith(self.prefixes)


class ResourceTypeRule(FilterRule):
    """ตรงเมื่อชนิดของ request (fetch หรือ xhr) อยู่ในรายการ

    สอนแนวคิด: polymorphism — FilterChain เรียก `matches` เหมือนกันทุกกฎ ไม่ต้องรู้ว่าเป็นกฎชนิดไหน
    """

    def __init__(self, resource_types: Sequence[str], focus_preset: str | None = None) -> None:
        super().__init__(focus_preset)
        self.resource_types = tuple(resource_types)

    def covers(self, exchange: HttpExchange) -> bool:
        return exchange.resource_type in self.resource_types


class FilterChain:
    """รวมกฎหลายข้อ: Blocklist ทุกข้อก่อน แล้วค่อย Focus rule เหตุผลแรกที่เจอชนะ

    สอนแนวคิด: composition — ประกอบจาก FilterRule หลายตัว แทนการเขียน if ยาวๆ
    """

    def __init__(self, blocklist: list[FilterRule], focus: list[FilterRule]) -> None:
        self._rules = [*blocklist, *focus]

    @classmethod
    def from_preset(cls, preset: Preset) -> "FilterChain":
        """Blocklist พื้นฐาน + Blocklist และ Focus rule ของ Preset"""
        blocklist: list[FilterRule] = [HostBlockRule(BASE_BLOCK_HOSTS)]
        blocklist += [PathPrefixRule([prefix], [host] if host else []) for host, prefix in BASE_BLOCK_PATHS]
        if preset.block_hosts:
            blocklist.append(HostBlockRule(preset.block_hosts))
        if preset.block_path_prefixes:
            blocklist.append(PathPrefixRule(preset.block_path_prefixes))
        focus: list[FilterRule] = []
        if preset.focus_hosts or preset.focus_path_prefixes:
            focus.append(PathPrefixRule(preset.focus_path_prefixes or ["/"], preset.focus_hosts, focus_preset=preset.name))
        if preset.focus_resource_types:
            focus.append(ResourceTypeRule(preset.focus_resource_types, focus_preset=preset.name))
        return cls(blocklist, focus)

    def hidden_reason(self, exchange: HttpExchange) -> str | None:
        """Hidden reason ของ Exchange นี้ ถ้าไม่ถูกซ่อนคืน None"""
        return next((reason for rule in self._rules if (reason := rule.matches(exchange)) is not None), None)


def load_presets(directory: Path) -> dict[str, Preset]:
    """อ่าน `presets/*.json` ชื่อไฟล์คือชื่อ Preset (`all` มาก่อนเสมอ)"""
    paths = sorted(directory.glob("*.json"), key=lambda path: (path.stem != "all", path.stem))
    return {
        path.stem: Preset.model_validate({**json.loads(path.read_text(encoding="utf-8")), "name": path.stem})
        for path in paths
    }


class FilterSettings:
    """Preset ทั้งหมด, ตัวที่เลือกอยู่ และ Preset `custom` ที่อยู่ในหน่วยความจำ

    สอนแนวคิด: encapsulation — ภายนอกเปลี่ยน Preset ได้ผ่าน `select`/`edit_custom` เท่านั้น
    กฎ "key ที่ต้องซ่อนเพิ่มได้อย่างเดียว" จึงถูกบังคับไว้ในที่เดียว
    """

    def __init__(self, presets: dict[str, Preset], selected: str = "all") -> None:
        self._presets = dict(presets)
        self._custom: Preset | None = None
        self._selected = next(iter(self._presets))
        self.select(selected)

    @property
    def current(self) -> Preset:
        if self._selected == CUSTOM and self._custom is not None:
            return self._custom
        return self._presets[self._selected]

    def chain(self) -> FilterChain:
        return FilterChain.from_preset(self.current)

    def select(self, name: str) -> None:
        """เลือก Preset ถ้าเลือก `custom` ครั้งแรกจะคัดลอกจาก Preset ที่เลือกอยู่ (ไม่รู้จักชื่อ → ValueError)"""
        if name == CUSTOM:
            if self._custom is None:
                self._custom = self.current.model_copy(update={"name": CUSTOM, "label": CUSTOM_LABEL})
        elif name not in self._presets:
            raise ValueError(f"ไม่รู้จัก preset '{name}' (มี {', '.join([*self._presets, CUSTOM])})")
        self._selected = name

    def edit_custom(self, rules: FilterRules) -> None:
        """แทนกฎของ `custom` ด้วยกฎใหม่ (key ที่ต้องซ่อนรวมกับของเดิมเสมอ ลดไม่ได้)"""
        self.select(CUSTOM)
        old_keys = self.current.redact_keys
        keys = list(dict.fromkeys([*old_keys, *rules.redact_keys]))
        self._custom = Preset.model_validate({**rules.model_dump(), "redact_keys": keys, "name": CUSTOM, "label": CUSTOM_LABEL})

    def view(self) -> FilterView:
        choices = [PresetChoice(name=p.name, label=p.label) for p in self._presets.values()]
        return FilterView(
            selected=self._selected,
            choices=[*choices, PresetChoice(name=CUSTOM, label=CUSTOM_LABEL)],
            rules=FilterRules.model_validate(self.current.model_dump()),
            base_blocklist=[*BASE_BLOCK_HOSTS, *(host + prefix for host, prefix in BASE_BLOCK_PATHS)],
        )
