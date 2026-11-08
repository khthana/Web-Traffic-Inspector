"""ประกอบ InspectorPipeline ของจริงสำหรับ test ไว้ที่เดียว: เพิ่ม dependency ใหม่แก้ที่นี่ที่เดียว"""

from inspector.broadcaster import Broadcaster
from inspector.correlator import Correlator
from inspector.filters import PRESETS_DIR, FilterSettings, load_presets
from inspector.pipeline import InspectorPipeline
from inspector.redactor import Redactor
from inspector.store import EventStore
from inspector.summarizer import Summarizer


def new_pipeline(
    store: EventStore, broadcaster: Broadcaster, preset: str = "all", chrome_launch_command: str = ""
) -> InspectorPipeline:
    return InspectorPipeline(
        store=store,
        broadcaster=broadcaster,
        redactor=Redactor(),
        correlator=Correlator(window_ms=1500),
        filters=FilterSettings(load_presets(PRESETS_DIR), selected=preset),
        summarizer=Summarizer(),
        chrome_launch_command=chrome_launch_command,
    )
