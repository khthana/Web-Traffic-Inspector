# Web Traffic Inspector

เครื่องมือสอนที่แสดงว่า **การคลิกหนึ่งครั้งบนเว็บ ทำให้เบราว์เซอร์ส่ง request อะไร และเซิร์ฟเวอร์ตอบอะไรกลับมา**
Inspector ต่อเข้ากับ Chrome ของผู้สอนผ่าน Chrome DevTools Protocol (CDP) แบบดูอย่างเดียว แล้วแสดงผลเป็น Timeline ของการคลิก
พร้อม Detail ของแต่ละ Exchange (request/response หนึ่งคู่) ที่หน้า `http://127.0.0.1:8000`

- ดูอย่างเดียว: ไม่แก้ ไม่บล็อก และไม่ส่ง request ซ้ำ
- ซ่อนค่าลับ (cookie, token, password ฯลฯ) เป็น `••••` ก่อนเก็บเสมอ ปิดไม่ได้
- ไม่เขียนอะไรลงดิสก์เอง ไฟล์ Recording จะมีก็ต่อเมื่อกดปุ่ม Export เท่านั้น

> ใช้ดู traffic ของตัวเองเพื่อการเรียนรู้เท่านั้น อย่านำ API ของเว็บอื่นไปเรียกซ้ำหรือดึงข้อมูลจำนวนมาก

## ติดตั้ง (ครั้งเดียว)

ต้องมี **Python 3.11 ขึ้นไป** และ **Google Chrome** ใช้ได้ทั้ง Windows และ macOS

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

ถ้า PowerShell ขึ้นว่า running scripts is disabled ตอนรัน `Activate.ps1` ให้รันคำสั่งนี้ครั้งเดียวแล้วลองใหม่

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

macOS (Terminal):

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

ไม่ต้องรัน `playwright install` เพราะ Inspector ใช้ Chrome ที่ติดตั้งอยู่ในเครื่อง ไม่ได้ดาวน์โหลดเบราว์เซอร์เพิ่ม

## วิธีใช้

**ขั้นที่ 1: เปิด Chrome โหมด debug** เลือกวิธีใดวิธีหนึ่ง

- ดับเบิลคลิกสคริปต์: Windows ใช้ `scripts/start_chrome.bat` ส่วน macOS ใช้ `scripts/start_chrome.command`
  (ถ้า macOS ไม่ยอมเปิด ให้คลิกขวา → Open ครั้งแรก หรือรัน `chmod +x scripts/start_chrome.command`)
- หรือให้ Inspector เปิดให้: `python -m inspector --launch-chrome` (รวมขั้นที่ 1 และ 2 ไว้ในคำสั่งเดียว)

Chrome ที่เปิดขึ้นมาใช้ **โปรไฟล์แยก** (`%LOCALAPPDATA%\TrafficInspectorProfile` บน Windows หรือ `~/.traffic-inspector-profile` บน macOS)
จึงไม่ปนกับ Chrome และบัญชีส่วนตัว และเปิดพร้อมกับ Chrome ปกติได้ (Chrome 136 ขึ้นไปไม่ยอมเปิดพอร์ต debug บนโปรไฟล์ปกติอยู่แล้ว)

**ขั้นที่ 2: รัน Inspector**

```sh
python -m inspector                  # เชื่อม Chrome ที่เปิดไว้แล้ว
python -m inspector --preset advice  # เริ่มด้วย preset ของ advice.co.th
```

โปรแกรมเปิดหน้า `http://127.0.0.1:8000` ในเบราว์เซอร์ให้อัตโนมัติ (ปิดได้ด้วย `--no-open`) กด `Ctrl+C` ใน terminal เพื่อปิด
ถ้ารัน Inspector ก่อนเปิด Chrome หน้า Inspector จะขึ้นว่า "ไม่พบ Chrome" พร้อมคำสั่งให้คัดลอก และเชื่อมต่อเองเมื่อ Chrome เปิดขึ้นมา

**ขั้นที่ 3: คลิกบนเว็บใน Chrome ตัวนั้น** แล้วดูใน Inspector

- Timeline (ซ้าย): แต่ละคลิกเป็นหนึ่งก้อน พร้อม Exchange ที่เกิดจากคลิกนั้น
- Detail (ขวา): Flow strip ด้านบนเล่นแอนิเมชัน คลิก → request → response แล้วมีแท็บ ภาพรวม, ขาออก, ขาเข้า, คลิก, ดิบ และโค้ด (คัดลอกเป็น curl, Python หรือ fetch)
- แถบด้านบน: เลือก Preset, หยุดเก็บชั่วคราว (Space), ล้าง (C), สลับแสดง Exchange ที่ถูกซ่อน, ปรับขนาดตัวอักษร (A− / A+), สลับธีม และปุ่ม Export สำหรับดาวน์โหลด Recording

แนะนำให้วางหน้าต่าง Chrome กับ Inspector ซ้าย-ขวาบนจอโปรเจกเตอร์

## ตัวเลือก command line

| Option | ค่าเริ่มต้น | ความหมาย |
| :---- | :---- | :---- |
| `--cdp-url` | `http://127.0.0.1:9222` | ที่อยู่ Chrome DevTools Protocol ของ Chrome ที่จะดู |
| `--port` | `8000` | พอร์ตของหน้า Inspector (เปิดเฉพาะ 127.0.0.1) |
| `--preset` | `all` | Preset การกรองตอนเริ่ม เช่น `advice` (ไฟล์ใน `presets/`) |
| `--window-ms` | `1500` | Correlation window: ช่วงเวลาหลังคลิก (ms) ที่นับ Exchange เป็นผลของคลิกนั้น |
| `--max-exchanges` | `500` | จำนวน Exchange สูงสุดที่เก็บในหน่วยความจำ เกินแล้วตัวเก่าสุดหลุดออก |
| `--no-open` | ปิด | ไม่ต้องเปิดหน้า Inspector ในเบราว์เซอร์ให้อัตโนมัติ |
| `--demo` | ปิด | ป้อนข้อมูลตัวอย่างแทน Chrome ใช้ลองหน้าจอโดยไม่ต้องเปิด Chrome |
| `--replay-file` | ไม่มี | เปิดไฟล์ Recording ที่ดาวน์โหลดไว้ดู โดยไม่ต่อ Chrome และไม่ส่ง request ใดๆ ออกไป |
| `--launch-chrome` | ปิด | หา Chrome ในเครื่องแล้วเปิดโหมด debug ให้ (โปรไฟล์แยก, พอร์ต CDP เปิดเฉพาะ 127.0.0.1) |

`--demo`, `--replay-file` และ `--launch-chrome` ใช้พร้อมกันไม่ได้

## ⚠️ คำเตือนเรื่องพอร์ต 9222

**ใครก็ตามที่เข้าถึงพอร์ต debug 9222 ได้ ควบคุม Chrome ตัวนั้นได้ทั้งหมด** ทั้งอ่าน cookie, เปิดหน้าเว็บ และกดปุ่มแทนเรา

- เปิด Chrome ด้วย `--remote-debugging-address=127.0.0.1` เสมอ (สคริปต์และ `--launch-chrome` ใส่ให้แล้ว) เพื่อให้เข้าได้จากเครื่องนี้เท่านั้น ห้ามเปลี่ยนเป็น `0.0.0.0`
- อย่าเปิดพอร์ตนี้ใน firewall และอย่าใช้ Chrome ตัวนี้ล็อกอินบัญชีส่วนตัว
- ปิด Chrome ตัวนี้เมื่อสอนเสร็จ
- หน้า Inspector เองก็เปิดเฉพาะ `127.0.0.1` นักศึกษาเครื่องอื่นในแลบเข้าไม่ได้ ถ้าจะให้ทุกคนดูให้ฉายจอแทน

## ข้อจำกัด: จับคู่คลิกกับ request ด้วยเวลา

Chrome ไม่ได้บอกตรงๆ ว่า request ไหนเกิดจากคลิกไหน Inspector จึงเดาจากเวลา: Exchange ที่เริ่มภายใน **1500 ms** หลังคลิก (ปรับได้ด้วย `--window-ms`)
ในแท็บเดียวกันนับเป็นผลของคลิกนั้น ถ้าคลิกพาไปหน้าใหม่ ช่วงนี้ขยายต่ออีก 5 วินาทีนับจากตอนเปลี่ยนหน้า ผลคือ

- request เบื้องหลัง (เช่น analytics หรือ polling) ที่บังเอิญเกิดในช่วงนั้น จะถูกนับเป็นผลของคลิกด้วย
- request ที่เริ่มช้ากว่าช่วงเวลา (เช่น โหลดตามหลังแอนิเมชันยาวๆ) จะไปอยู่ใน Background แทน
- คลิกถี่ๆ ติดกัน request ของคลิกแรกที่มาช้าอาจไปอยู่กับคลิกถัดไป

ตอนสาธิตให้คลิกทีละครั้งแล้วรอให้ Timeline นิ่งก่อน และใช้ Preset (เช่น `advice`) ซ่อน tracking ที่ไม่เกี่ยวข้อง

## ข้อแนะนำตอนสาธิตในห้อง

- ใช้โปรไฟล์ Chrome แยก (สคริปต์ทำให้แล้ว) ไม่ล็อกอินบัญชีส่วนตัว ถ้าต้องล็อกอินให้ใช้บัญชีสำหรับสาธิต
- หยุดก่อนขั้นชำระเงินเสมอ และลบสินค้าออกจากตะกร้าหลังสาธิต (การลบก็เป็น request ที่น่าสอนอีกตัว)
- เตรียมไฟล์ Recording ของรอบซ้อมไว้ เผื่อเน็ตในห้องมีปัญหา แล้วเปิดดูด้วย `python -m inspector --replay-file รอบซ้อม.json`
- กด Space หยุดเก็บชั่วคราวระหว่างอธิบาย และกด A+ ให้คนท้ายห้องอ่านได้

## Checklist ทดสอบกับเว็บจริง (preset `advice`)

รัน `python -m inspector --preset advice` แล้วไล่ทีละข้อ

- [ ] 1. เปิด Inspector ก่อน Chrome: แสดงสถานะ "ไม่พบ Chrome" พร้อมคำสั่ง และเชื่อมต่อเองภายใน 5 วินาทีหลังเปิด Chrome
- [ ] 2. เปิดหน้าแรก: มี "โหลดหน้า" ที่มี `get-popup-home` และ `cart/get` และตัวนับ "ซ่อน" มากกว่า 0
- [ ] 3. คลิกเมนูไปหมวดโน้ตบุ๊ก: มีคลิกที่บอกข้อความปุ่มถูกต้อง และมี `product/category/data` ที่ response เป็น JSON กดดูได้
- [ ] 4. เข้าหน้าสินค้าแล้วกดเพิ่มลงตะกร้า: Detail เลือก request หลักให้อัตโนมัติ แสดง body ขาออก (เช่นรหัสสินค้า, จำนวน) และ response ขาเข้า ตามด้วย `cart/get` ที่ `data` ไม่ว่างแล้ว
- [ ] 5. เปิดแท็บขาออก: ไม่มีค่า cookie หรือ token จริงปรากฏที่ใด (รวมถึงไฟล์ Recording และ curl ที่คัดลอก)
- [ ] 6. เปิด toggle "ซ่อน": เห็น request ไป google-analytics.com, clarity.ms พร้อมเหตุผล
- [ ] 7. เปิดแท็บใหม่ใน Chrome: คลิกในแท็บใหม่ถูกดักด้วย
- [ ] 8. ปิด Chrome แล้วเปิดใหม่: Inspector ไม่ crash แสดงแถบหลุดแล้วกลับมาเชื่อมต่อ
- [ ] 9. กด A+ จนสุด (20 px) บนจอ 1366×768: ไม่มี scroll แนวนอนทั้งหน้า อ่านได้จากท้ายห้อง
- [ ] 10. การดักไม่ทำให้เว็บทำงานผิดปกติ (ปุ่มทุกปุ่มทำงานเหมือนไม่มี Inspector)

## สำหรับผู้พัฒนา

```sh
pip install -r requirements-dev.txt
python -m pytest -q            # unit test (ไม่ต้องใช้ Chrome)
python -m pytest -q -m chrome  # test ที่เปิด Chrome จริงแบบ headless
python -m mypy                 # ตรวจ type แบบ strict
```

สเปกฉบับเต็มอยู่ที่ `docs/SPEC.md` และศัพท์ของโปรเจกต์อยู่ที่ `CONTEXT.md`
