"""Summarizer: สร้างประโยคสรุป Exchange เป็นภาษาไทยจาก template (ไม่ใช้ AI)

รูปแบบ: เบราว์เซอร์{กริยา} "{ส่วนท้ายของ path}" → เซิร์ฟเวอร์ตอบ {status} {ความหมาย} ใน {ms} ms
"""

import math

from inspector.models import HttpExchange

VERBS = {"GET": "ขอดู", "POST": "ส่งข้อมูลไป", "PUT": "ขอแก้", "PATCH": "ขอแก้", "DELETE": "ขอลบ"}
MEANINGS = {
    200: "สำเร็จ",
    201: "สร้างแล้ว",
    204: "สำเร็จไม่มีเนื้อหา",
    301: "ย้ายที่",
    302: "ย้ายที่",
    304: "ใช้ของเดิม",
    400: "คำขอผิด",
    401: "ยังไม่ได้ล็อกอิน",
    403: "ไม่มีสิทธิ์",
    404: "ไม่พบ",
    422: "ข้อมูลไม่ผ่าน validation",
    429: "ถี่เกินไป",
}
# status ที่ไม่มีในตาราง ใช้ความหมายตามกลุ่ม (หลักร้อย) เฉพาะกลุ่มที่ความหมายไม่ผิดแน่ๆ
# 4xx อื่นๆ (405, 408, 410…) ไม่ได้แปลว่า "คำขอผิด" เสมอ จึงแสดงแค่เลข ไม่เดา
CLASS_MEANINGS = {2: "สำเร็จ", 3: "ย้ายที่", 5: "เซิร์ฟเวอร์พัง"}


def path_tail(path: str) -> str:
    """สองส่วนสุดท้ายของ path เช่น /_advice-api/api/v1.0.0/cart/get → cart/get"""
    parts = [part for part in path.split("/") if part]
    return "/".join(parts[-2:]) or "/"


def milliseconds(duration_ms: float) -> str:
    """ปัดครึ่งขึ้นแบบเดียวกับ Math.round ของหน้าเว็บ (round() ของ Python ปัดครึ่งไปหาเลขคู่)"""
    return f"{math.floor(duration_ms + 0.5)} ms"


def status_meaning(status: int) -> str:
    return MEANINGS.get(status) or CLASS_MEANINGS.get(status // 100, "")


class Summarizer:
    """แปลง Exchange เป็นประโยคที่นักศึกษาอ่านเข้าใจ

    สอนแนวคิด: ทดสอบง่าย (pure method) — summarize() ได้ผลจาก exchange ที่ส่งเข้ามาอย่างเดียว
    ไม่อ่านนาฬิกา ไม่แก้ state ใดๆ ใส่ค่าเดิมได้ผลเดิมเสมอ จึงทดสอบเป็นตารางได้
    ข้อมูลที่เปลี่ยนได้ (กริยา, ความหมายของ status) อยู่ในตาราง ไม่ได้ซ่อนอยู่ใน if
    """

    def summarize(self, exchange: HttpExchange) -> str:
        method = exchange.request.method.upper()
        verb = VERBS.get(method, f"ส่งคำขอ {method} ไป")
        browser_part = f'เบราว์เซอร์{verb} "{path_tail(exchange.request.path)}"'
        took = "" if exchange.duration_ms is None else milliseconds(exchange.duration_ms)
        if exchange.state == "failed":
            return f"{browser_part} → ไม่ได้คำตอบ ({exchange.failure or 'ล้มเหลว'})" + (f" หลัง {took}" if took else "")
        if exchange.response is None:
            return f"{browser_part} → รอคำตอบจากเซิร์ฟเวอร์…"
        status = exchange.response.status
        answer = " ".join(part for part in (str(status), status_meaning(status), took and f"ใน {took}") if part)
        return f"{browser_part} → เซิร์ฟเวอร์ตอบ {answer}"
