"""Summarizer: สร้างประโยคสรุป Exchange เป็นภาษาไทยจาก template (ไม่ใช้ AI)

รูปแบบ: เบราว์เซอร์{กริยา} "{ส่วนท้ายของ path}" → เซิร์ฟเวอร์ตอบ {status} {ความหมาย} ใน {ms} ms
"""

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
# status ที่ไม่มีในตาราง ใช้ความหมายตามกลุ่ม (หลักร้อย)
CLASS_MEANINGS = {1: "ข้อมูลระหว่างทาง", 2: "สำเร็จ", 3: "ย้ายที่", 4: "คำขอผิด", 5: "เซิร์ฟเวอร์พัง"}


def path_tail(path: str) -> str:
    """สองส่วนสุดท้ายของ path เช่น /_advice-api/api/v1.0.0/cart/get → cart/get"""
    parts = [part for part in path.split("/") if part]
    return "/".join(parts[-2:]) or "/"


def status_meaning(status: int) -> str:
    return MEANINGS.get(status) or CLASS_MEANINGS.get(status // 100, "")


class Summarizer:
    """แปลง Exchange เป็นประโยคที่นักศึกษาอ่านเข้าใจ

    สอนแนวคิด: single responsibility — รู้แค่เรื่อง "เล่าเป็นภาษาคน" ไม่รู้เรื่องการเก็บหรือส่งข้อมูล
    ข้อมูลที่เปลี่ยนได้ (กริยา, ความหมายของ status) อยู่ในตาราง ไม่ได้ซ่อนอยู่ใน if
    """

    def summarize(self, exchange: HttpExchange) -> str:
        method = exchange.request.method.upper()
        verb = VERBS.get(method, f"ส่งคำขอ {method} ไป")
        asked = f'เบราว์เซอร์{verb} "{path_tail(exchange.request.path)}"'
        ms = f"{exchange.duration_ms:.0f} ms" if exchange.duration_ms is not None else ""
        if exchange.state == "failed":
            return f"{asked} → ไม่ได้คำตอบ ({exchange.failure or 'ล้มเหลว'})" + (f" หลัง {ms}" if ms else "")
        if exchange.response is None:
            return f"{asked} → รอคำตอบจากเซิร์ฟเวอร์…"
        answer = " ".join(part for part in (str(exchange.response.status), status_meaning(exchange.response.status)) if part)
        return f"{asked} → เซิร์ฟเวอร์ตอบ {answer} ใน {ms}"
