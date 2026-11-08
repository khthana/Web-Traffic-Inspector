"""แยก body แบบ multipart/form-data เป็น part ทีละส่วน (RFC 7578) เพื่อให้ Redactor ซ่อนค่าได้ทีละ field

parse แบบเข้มงวด: ถ้ารูปแบบไม่ครบ (ไม่มี boundary, ถูกตัดก่อนปิด, part ไม่มีชื่อ, มีข้อความนอก part)
คืน None ให้ผู้เรียก fallback เป็น "ไม่ได้ตรวจหาข้อมูลลับ" แทนการเดา
header ของ part อ่านด้วย `email.message` ของ Python ซึ่งรู้จักทุกรูปแบบตาม RFC
(ไม่มีเครื่องหมายคำพูด, `filename*=UTF-8''...`, `\\"` ในชื่อ)
"""

import re
from collections.abc import Callable
from email.message import Message
from email.parser import HeaderParser
from email.utils import collapse_rfc2231_value
from typing import NamedTuple

LINE_BREAK = re.compile(r"\r?\n")
HEADER_END = re.compile(r"\r?\n\r?\n")
SEGMENT_END = re.compile(r"\r?\n\Z")


class FormPart(NamedTuple):
    """part หนึ่งส่วนของฟอร์ม: เก็บข้อความรอบเนื้อไว้ครบ จึงประกอบกลับเป็น body เดิมได้ทุกตัวอักษร

    สอนแนวคิด: immutable value object — NamedTuple แก้ค่าไม่ได้ ค่าเดียวกันก็เท่ากันเสมอ
    """

    head: str  # ตั้งแต่ขึ้นบรรทัดหลัง boundary จนถึงบรรทัดว่างหลัง header
    content: str
    tail: str  # ขึ้นบรรทัดก่อน boundary ตัวถัดไป
    name: str
    filename: str | None
    content_type: str | None  # None = part ไม่ได้บอกชนิด (ตามมาตรฐานคือข้อความธรรมดา)

    @property
    def is_plain_text(self) -> bool:
        """field ข้อความธรรมดาที่แสดงได้: ไม่ใช่ไฟล์, ไม่บอกชนิดอื่น และไม่มี byte ที่ไม่ใช่ UTF-8"""
        plain = self.content_type is None or self.content_type.lower().startswith("text/plain")
        return self.filename is None and plain and not has_undecodable_bytes(self.content)


class MultipartBody(NamedTuple):
    """body ทั้งก้อนที่แยกเป็น part แล้ว

    สอนแนวคิด: factory function — สร้างผ่าน `parse_multipart` เท่านั้น ซึ่งคืน None ถ้ารูปแบบไม่ถูกต้อง
    ผู้ใช้ที่ได้ object นี้ไปจึงไม่ต้องเช็กรูปแบบซ้ำ
    """

    delimiter: str
    parts: tuple[FormPart, ...]
    closing: str  # "--" ปิดท้ายและบรรทัดว่างหลังจากนั้น

    def map_content(self, change: Callable[[FormPart], str]) -> str:
        """ประกอบ body ใหม่โดยเปลี่ยนเนื้อของแต่ละ part ตาม `change` ส่วนอื่นคงเดิม"""
        pieces = [part.head + change(part) + part.tail for part in self.parts]
        return self.delimiter.join(["", *pieces, self.closing])


def has_undecodable_bytes(text: str) -> bool:
    """มี byte ที่ไม่ใช่ UTF-8 ซึ่ง capture เก็บไว้เป็น surrogate (เช่นเนื้อไฟล์รูป)"""
    return any("\udc80" <= char <= "\udcff" for char in text)


def boundary_of(content_type: str) -> str | None:
    message = Message()
    message["content-type"] = content_type
    boundary = message.get_boundary()
    return boundary or None


def parse_multipart(body: str, content_type: str) -> MultipartBody | None:
    """แยก body เป็น part ถ้ารูปแบบไม่ถูกต้องหรือไม่ครบคืน None"""
    boundary = boundary_of(content_type)
    if boundary is None:
        return None
    delimiter = f"--{boundary}"
    preamble, *segments = body.split(delimiter)
    if preamble or not segments:
        return None  # มีข้อความก่อน part แรก: เบราว์เซอร์ไม่ส่งแบบนี้ ไม่รู้ว่าซ่อนอะไรไว้
    *middle, closing = segments
    if closing.rstrip("\r\n") != "--":
        return None  # ไม่มี boundary ปิดท้าย (ถูกตัด) หรือมีข้อความต่อท้าย
    parts = [_part(segment) for segment in middle]
    if not parts or any(part is None for part in parts):
        return None
    return MultipartBody(delimiter, tuple(part for part in parts if part is not None), closing)


def _part(segment: str) -> FormPart | None:
    opening = LINE_BREAK.match(segment)
    header_end = HEADER_END.search(segment)
    segment_end = SEGMENT_END.search(segment)
    if opening is None or header_end is None or segment_end is None or header_end.end() > segment_end.start():
        return None
    headers = HeaderParser().parsestr(segment[opening.end() : header_end.start()] + "\n")
    if headers.get_content_disposition() != "form-data":
        return None
    name = headers.get_param("name", header="content-disposition")
    if name is None:
        return None
    return FormPart(
        head=segment[: header_end.end()],
        content=segment[header_end.end() : segment_end.start()],
        tail=segment[segment_end.start() :],
        name=collapse_rfc2231_value(name),
        filename=headers.get_filename(),
        content_type=headers["content-type"],
    )
