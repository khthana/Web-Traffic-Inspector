"""อ่านไฟล์ Recording และตั้งชื่อไฟล์ตอน export

Recording playback แค่อ่านไฟล์ที่ผู้สอนเลือกเอง ไม่ส่ง request ใดๆ ออกไป และไม่เขียนอะไรลงดิสก์
"""

from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from inspector.models import Recording


def read_recording(path: Path) -> Recording:
    """โหลด Recording จากไฟล์ อ่านไม่ได้ → ValueError ที่บอกชื่อไฟล์และสาเหตุเป็นภาษาไทย"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ValueError(f"ไม่พบไฟล์ Recording: {path}") from error
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"อ่านไฟล์ {path.name} ไม่ได้: {error}") from error
    try:
        return Recording.model_validate_json(text)
    except ValidationError as error:
        raise ValueError(
            f"{path.name} ไม่ใช่ Recording ของ Web Traffic Inspector ({error.error_count()} จุดที่ไม่ตรงรูปแบบ)"
        ) from error


def download_name(recording: Recording, interaction_id: str | None) -> str:
    """ชื่อไฟล์ตอนดาวน์โหลด เช่น recording-20261107-143205.json หรือ recording-it_0003-20261107-143205.json"""
    stamp = datetime.fromtimestamp(recording.exported_at / 1000).strftime("%Y%m%d-%H%M%S")
    scope = f"{interaction_id}-" if interaction_id else ""
    return f"recording-{scope}{stamp}.json"
