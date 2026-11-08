"""แยก body แบบ multipart/form-data เป็น part ทีละส่วน (RFC 7578) เพื่อให้ Redactor ซ่อนค่าได้ทีละ field

parse แบบเข้มงวด: ถ้ารูปแบบไม่ครบ (ไม่มี boundary, ถูกตัดก่อนปิด, part ไม่มีชื่อ) คืน None
ให้ผู้เรียก fallback เป็น "ไม่ได้ตรวจหาข้อมูลลับ" แทนการเดา
"""

import re
from collections.abc import Callable
from typing import NamedTuple

BOUNDARY = re.compile(r';\s*boundary=(?:"([^"]+)"|([^;\s]+))', re.I)
NAME = re.compile(r';\s*name="([^"]*)"', re.I)
FILENAME = re.compile(r';\s*filename="([^"]*)"', re.I)
PART_CONTENT_TYPE = re.compile(r"^content-type:\s*(.+?)\s*$", re.I | re.M)
LINE_BREAK = re.compile(r"\r?\n")
HEADER_END = re.compile(r"\r?\n\r?\n")


class FormPart(NamedTuple):
    """part หนึ่งส่วนของฟอร์ม: เก็บข้อความรอบเนื้อไว้ครบ จึงประกอบกลับเป็น body เดิมได้ทุกตัวอักษร

    สอนแนวคิด: immutable value object — NamedTuple แก้ค่าไม่ได้ เปลี่ยนเนื้อด้วย `_replace` ซึ่งคืน part ตัวใหม่
    """

    head: str  # ตั้งแต่ขึ้นบรรทัดหลัง boundary จนถึงบรรทัดว่างหลัง header
    content: str
    tail: str  # ขึ้นบรรทัดก่อน boundary ตัวถัดไป
    name: str
    filename: str | None
    content_type: str


class MultipartBody(NamedTuple):
    """body ทั้งก้อนที่แยกเป็น part แล้ว

    สอนแนวคิด: parse, don't validate — ถ้าสร้าง object นี้ได้ แปลว่ารูปแบบถูกต้องครบ ผู้ใช้ไม่ต้องเช็กซ้ำ
    """

    delimiter: str
    preamble: str
    parts: tuple[FormPart, ...]
    closing: str  # "--" ปิดท้ายและทุกอย่างหลังจากนั้น

    def map_content(self, change: Callable[[FormPart], str]) -> str:
        """ประกอบ body ใหม่โดยเปลี่ยนเนื้อของแต่ละ part ตาม `change` ส่วนอื่นคงเดิม"""
        pieces = [part.head + change(part) + part.tail for part in self.parts]
        return self.delimiter.join([self.preamble, *pieces, self.closing])


def boundary_of(content_type: str) -> str | None:
    match = BOUNDARY.search(content_type)
    return None if match is None else match.group(1) or match.group(2)


def parse_multipart(body: str, content_type: str) -> MultipartBody | None:
    """แยก body เป็น part ถ้ารูปแบบไม่ถูกต้องหรือไม่ครบคืน None"""
    boundary = boundary_of(content_type)
    if boundary is None:
        return None
    delimiter = f"--{boundary}"
    preamble, *segments = body.split(delimiter)
    if not segments or not segments[-1].startswith("--"):
        return None  # ไม่มี boundary ปิดท้าย: ถูกตัดหรือผิดรูป
    *middle, closing = segments
    parts = [_part(segment) for segment in middle]
    if not parts or any(part is None for part in parts):
        return None
    return MultipartBody(delimiter, preamble, tuple(part for part in parts if part is not None), closing)


def _part(segment: str) -> FormPart | None:
    opening = LINE_BREAK.match(segment)
    header_end = HEADER_END.search(segment)
    closing = re.search(r"\r?\n\Z", segment)
    if opening is None or header_end is None or closing is None or header_end.end() > closing.start():
        return None
    headers = segment[opening.end() : header_end.start()]
    disposition = next((line for line in LINE_BREAK.split(headers) if line.lower().startswith("content-disposition:")), "")
    name = NAME.search(disposition)
    if name is None:
        return None
    filename = FILENAME.search(disposition)
    content_type = PART_CONTENT_TYPE.search(headers)
    return FormPart(
        head=segment[: header_end.end()],
        content=segment[header_end.end() : closing.start()],
        tail=segment[closing.start() :],
        name=name.group(1),
        filename=None if filename is None else filename.group(1),
        content_type="ไม่ทราบชนิด" if content_type is None else content_type.group(1),
    )
