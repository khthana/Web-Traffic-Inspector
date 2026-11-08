# Web Traffic Inspector — Spec

Nov 5, 2026 · @Thana Hongsuwan

## 1\. ภาพรวมและเป้าหมาย

Web Traffic Inspector คือโปรแกรม Python ที่เชื่อมเข้ากับ Chrome ของผู้สอน แล้วแสดงบนหน้าเว็บของตัวเองว่า **ผู้ใช้คลิกอะไร → เบราว์เซอร์ส่ง request อะไรออกไป → server ตอบอะไรกลับมา** ใช้กับเว็บจริงอย่าง advice.co.th ได้ โดยไม่ต้องเปิด Chrome DevTools

เป้าหมายการสอน (วิชา OOP ที่ใช้ Web เป็น frontend และ FastAPI เป็น backend):

1. ให้นักศึกษาเห็นว่าการกดปุ่มหนึ่งครั้งคือ event ที่ทำให้เกิด HTTP request ไปยัง API  
2. ให้เห็นโครงสร้างจริงของ request (method, URL, headers, body) และ response (status code, headers, JSON)  
3. ให้เห็นว่าเว็บจริงใช้ JSON API แบบเดียวกับที่นักศึกษาจะเขียนด้วย FastAPI  
4. ให้เห็นว่าหน้าเว็บจริงมี traffic อื่นปนอยู่มาก (analytics, ads) และต้องรู้จักกรอง  
5. ตัวโปรแกรมเองเป็นตัวอย่างของ OOP \+ FastAPI \+ WebSocket ที่นักศึกษาอ่านโค้ดได้

ผู้ใช้หลักคือผู้สอนที่สาธิตหน้าห้องบนจอโปรเจกเตอร์ ผู้ใช้รองคือนักศึกษาที่รันเองในแลบ

## 2\. ขอบเขตและข้อจำกัด

โปรแกรมนี้ **ดูอย่างเดียว (read-only)** ไม่แก้ ไม่ส่งซ้ำ และไม่บล็อก request ใดๆ ทั้งสิ้น ระดับความสำคัญ: P0 \= ต้องมีในเวอร์ชันแรก, P1 \= ควรมี, P2 \= ทำทีหลังได้

| หัวข้อ | อยู่ในขอบเขต | หมายเหตุ |
| :---- | :---- | :---- |
| ดัก fetch/XHR จากทุกแท็บใน Chrome ที่เชื่อมต่อ | P0 | รวมแท็บที่เปิดใหม่ระหว่างใช้งาน |
| ดักการคลิกและจับคู่กับ request ที่ตามมา | P0 | จับคู่ด้วยช่วงเวลา (หัวข้อ 4.2) |
| กรอง traffic ขยะ (analytics, ads, รูป, CSS) | P0 | ดูสิ่งที่ซ่อนได้ด้วยปุ่มเดียว |
| ซ่อน cookie, token และข้อมูลส่วนตัวอัตโนมัติ | P0 | ปิดไม่ได้จาก UI |
| หน้า Inspector แบบ real-time ผ่าน WebSocket | P0 |  |
| สรุปภาษาคนต่อ request | P0 | หัวข้อ 4.5 |
| Export เป็น JSON, Copy as curl | P1 | curl ที่ได้ต้องตัด cookie ออกแล้ว |
| แผนภาพ Browser → Server แบบเคลื่อนไหว | P1 | หัวข้อ 6 |
| เปิด Chrome ให้อัตโนมัติ (`--launch-chrome`) | P1 |  |
| โหมด slow-motion (หน่วง request) | P2 | เปลี่ยนเฉพาะจังหวะ ไม่แก้เนื้อหา |
| WebSocket frames, Server-Sent Events | P2 |  |
| แก้ไขหรือส่ง request ซ้ำ (replay) | ไม่ทำ | เหตุผลด้านจริยธรรม หัวข้อ 10 |
| แอปมือถือ, แอปเดสก์ท็อป, เบราว์เซอร์อื่น | ไม่ทำ |  |

**ข้อจำกัดที่ทราบแล้ว**

- Chrome 136 ขึ้นไปไม่ยอมเปิด remote debugging บนโปรไฟล์หลัก ต้องใช้โปรไฟล์แยก (`--user-data-dir`) ผลคือต้องล็อกอินเว็บใหม่ในโปรไฟล์นั้น ซึ่งดีต่อการสาธิตเพราะแยกจากบัญชีส่วนตัว  
- การจับคู่คลิกกับ request ใช้เวลาเป็นหลัก request จาก timer หรือ polling ที่บังเอิญเกิดในช่วงเดียวกันจะถูกจับคู่ผิดได้  
- request จาก Service Worker อาจไม่ถูกดัก  
- body บางตัวอ่านไม่ได้ (redirect, streaming, binary เช่น protobuf) ให้แสดงเป็น "อ่าน body ไม่ได้" พร้อมเหตุผล  
- เว็บที่ใช้ Cloudflare (รวมถึง advice.co.th) ไม่มีปัญหา เพราะใช้ Chrome ตัวจริง ไม่ใช่ headless browser

## 3\. สถาปัตยกรรมระบบ

ทั้งระบบเป็น Python process เดียว ที่รัน Playwright และ FastAPI บน asyncio event loop เดียวกัน และ bind เฉพาะ `127.0.0.1`

| ส่วนประกอบ | เทคโนโลยี | หน้าที่ |
| :---- | :---- | :---- |
| Chrome ตัวจริง | Chrome \+ `--remote-debugging-port=9222` | ผู้สอนใช้เว็บตามปกติ |
| Capture engine | Playwright for Python, `connect_over_cdp("http://127.0.0.1:9222")` | ฟัง event request/response ทุกแท็บ และฉีด click listener |
| Click hook | `context.add_init_script()` \+ `context.expose_binding()` | สคริปต์เล็กๆ ในหน้าเว็บส่งข้อมูลการคลิกกลับมา Python |
| Pipeline | Python classes (หัวข้อ 8\) | กรอง → ซ่อนข้อมูลลับ → จับคู่กับคลิก → เก็บในหน่วยความจำ |
| Inspector server | FastAPI \+ uvicorn ที่ `http://127.0.0.1:8000` | เสิร์ฟหน้า UI, REST API, WebSocket `/ws` |
| Inspector UI | HTML \+ CSS \+ vanilla JavaScript (ไม่ใช้ framework, ไม่ต้อง build) | แสดงผล real-time |

เหตุผลที่เลือกแบบนี้: เชื่อม Chrome ตัวจริงผ่าน CDP เว็บจึงเห็นเป็นผู้ใช้ปกติ ไม่โดน bot detection ไม่ต้องติดตั้ง certificate แบบ proxy และไม่ต้องรัน `playwright install` เพราะไม่ได้ใช้เบราว์เซอร์ที่ Playwright ดาวน์โหลดมา

```
[เว็บไซต์จริง www.advice.co.th]
        ^  HTTPS (ไป-กลับ)
        v
[Chrome ของผู้สอน: แท็บเว็บ + click_hook.js, พอร์ต 9222 (CDP)]
        |  CDP events (request/response + คลิก)
        v
+-- Python process (python -m inspector) ---------------------------+
|  Capture + ClickTracker -> FilterChain -> Redactor (ซ่อนข้อมูลลับ)    |
|  -> Correlator + Summarizer -> EventStore (500) -> Broadcaster     |
|                                                    |              |
|                                   FastAPI + uvicorn (REST /api/*,  |
|                                   WebSocket /ws)                   |
+--------------------------------------------------------------------+
        |  WebSocket: ส่งข้อมูลทันที
        v
[หน้า Inspector 127.0.0.1:8000 (HTML + vanilla JS)]
```

ทุก request ผ่าน Redactor ก่อนเข้า EventStore ดังนั้นหน้า Inspector และไฟล์ export ไม่เคยเห็น cookie หรือ token จริง

## 4\. Functional requirements

### 4.1 การดัก request/response (P0)

- เชื่อมต่อกับ `browser.contexts[0]` และ attach ทุก page ที่มีอยู่ รวมถึง page ใหม่ผ่าน `context.on("page")`  
- ฟัง `request`, `response`, `requestfinished`, `requestfailed` เก็บเฉพาะ `resource_type` เป็น `fetch` หรือ `xhr` (รูป, CSS, ฟอนต์, script ไม่เก็บเลย)  
- บันทึก: method, URL แยก host/path/query, request headers, request body (`post_data`), status, status text, response headers, response body, เวลาเริ่ม และเวลาที่ใช้ (ms), tab ที่เกิด, URL ของหน้าเว็บขณะนั้น  
- อ่าน response body เฉพาะ content-type ที่เป็น text (JSON, text, form, XML) ตัดที่ 64 KB แล้วบอกว่าตัดไปเท่าไร อ่าน body ไม่ได้ให้เก็บเหตุผลไว้ ไม่ crash  
- request ที่ล้มเหลว (network error, CORS, abort) แสดงเป็นสถานะ `failed` พร้อม `failure` text

### 4.2 การดักคลิกและจับคู่ (P0)

- ฉีดสคริปต์ผ่าน `add_init_script` ให้ฟัง `click` บน `document` แบบ **capture phase** (ทำงานก่อน handler ของเว็บ และไม่เรียก `preventDefault`/`stopPropagation`) และฉีดซ้ำเข้าหน้าที่เปิดอยู่แล้วด้วย `page.evaluate`  
- หา element ที่มีความหมายด้วย `target.closest('button, a, [role=button], input, [onclick]')` ถ้าไม่เจอใช้ target เดิม  
- ส่งกลับมา Python: tag, ข้อความที่มองเห็น (ตัด 40 ตัวอักษร), `aria-label`, `id`, class 3 ตัวแรก, `href` (ถ้ามี), CSS selector สั้นๆ, เวลา (`performance.timeOrigin + performance.now()`), URL หน้า  
- **ห้ามส่งค่าใน input** เช่น รหัสผ่านหรือเบอร์โทร  
- การจับคู่: request ที่เริ่มภายใน `correlation_window_ms` (ค่าเริ่มต้น 1500\) หลังคลิก และอยู่ในแท็บเดียวกัน จัดเข้ากลุ่ม (Interaction) ของคลิกนั้น ถ้ามีคลิกใหม่ก่อนหมดเวลา ให้เปิดกลุ่มใหม่  
- request ที่ไม่ตามหลังคลิกจัดเข้ากลุ่มพิเศษ: "โหลดหน้า" (เกิดภายใน 5 วินาทีหลัง navigation) หรือ "เบื้องหลัง" (กรณีอื่น)  
- คลิกที่ทำให้เปลี่ยนหน้า (ลิงก์ปกติ) ให้แสดงในกลุ่มว่า "เปลี่ยนหน้าไป \<URL\>" แทนการปล่อยว่าง

### 4.3 การกรอง (P0)

กรองเป็น 2 ชั้น กำหนดใน `filters.json` และแก้จาก UI ได้:

1. **Blocklist** ซ่อนเสมอ: `google-analytics.com`, `googletagmanager.com`, `googlesyndication.com`, `doubleclick.net`, `clarity.ms`, `facebook.com`, `facebook.net`, `analytics.tiktok.com`, `analytics.ahrefs.com`, `*.run.app/events`, path `/cdn-cgi/`  
2. **Focus rules** (เลือกได้) ถ้าตั้งไว้จะแสดงเฉพาะที่ตรงเงื่อนไข เช่น preset "advice.co.th" \= host `www.advice.co.th` \+ path ขึ้นต้น `/_advice-api/` หรือ `/api/`

สิ่งที่ถูกซ่อนยังเก็บไว้ และ UI แสดงจำนวนที่ซ่อน กดดูได้ (ใช้สอนเรื่อง tracking)

### 4.4 การซ่อนข้อมูลลับ (P0, ปิดไม่ได้)

ทำที่ฝั่ง Python **ก่อน** เก็บลง store ดังนั้นค่าจริงไม่เคยออกไปถึง UI หรือ export:

- Headers: `cookie`, `set-cookie`, `authorization`, `proxy-authorization` และ header ที่ชื่อมี `token`, `session`, `auth`, `csrf`, `key`, `secret` → แทนด้วย `"•••• (ซ่อนไว้, 142 ตัวอักษร)"`  
- สำหรับ cookie ให้แสดงชื่อ cookie ได้ แต่ซ่อนค่า เช่น `PHPSESSID=••••` เพื่อใช้สอนเรื่อง session ได้  
- JSON body และ query string: key ที่ตรง regex `pass|token|secret|session|otp|card|phone|mobile|email|address|citizen|id_card` (ไม่สนตัวพิมพ์) → ซ่อนค่า ทำแบบ recursive  
- รหัสติดตามผู้ใช้: key ที่มีคำ `fbp`, `fbc`, `fbclid`, `gclid`, `gcl`, `ga`, `msclkid`, `ttclid` เป็นคำทั้งคำ (แยกคำที่ตัวที่ไม่ใช่ตัวอักษรและที่ camelCase เช่น `_fbp`, `fb.fbp`, `_ga_ABC`, `gaClientId` แต่ไม่ใช่ `language`, `mega`) → ซ่อนค่าเช่นกัน  
- body ชนิด text ที่ parse เป็น JSON object หรือ array ได้ (เช่น `navigator.sendBeacon` ส่ง JSON เป็น `text/plain`) ตรวจด้วยกฎของ JSON ส่วน text อื่นแสดงป้าย "ไม่ได้ตรวจหาข้อมูลลับ"  
- JSON แบบคู่ชื่อ/ค่า: object ที่ค่าของ `name`, `key`, `field` หรือ `id` เป็นชื่อที่อ่อนไหว (เช่น `{"name": "_fbp", "value": …}`) → ซ่อนค่าของ `value`, `val`, `values`, `content` ที่อยู่คู่กัน  
- string ใน JSON ที่เป็น JSON object หรือ array อีกชั้น ตรวจด้วยกฎเดียวกันแล้วใส่กลับเป็น string (ซ้อนได้ไม่เกิน 5 ชั้น เกินนั้นแสดงป้าย "ไม่ได้ตรวจหาข้อมูลลับ")  
- รายการ key เพิ่มเติมกำหนดได้ใน `filters.json` (เพิ่มได้อย่างเดียว ลดรายการพื้นฐานไม่ได้)

### 4.5 สรุปภาษาคน (P0)

ทุก request มีประโยคสรุปที่สร้างจาก template (ไม่ใช้ AI):

- รูปแบบ: `เบราว์เซอร์ {กริยา} "{ส่วนท้ายของ path}" → เซิร์ฟเวอร์ตอบ {status} {ความหมาย} ใน {ms} ms`  
- กริยาตาม method: GET \= ขอดู, POST \= ส่งข้อมูลไป, PUT/PATCH \= ขอแก้, DELETE \= ขอลบ  
- ความหมาย status: 200 สำเร็จ, 201 สร้างแล้ว, 204 สำเร็จไม่มีเนื้อหา, 301/302 ย้ายที่, 304 ใช้ของเดิม, 400 คำขอผิด, 401 ยังไม่ได้ล็อกอิน, 403 ไม่มีสิทธิ์, 404 ไม่พบ, 422 ข้อมูลไม่ผ่าน validation, 429 ถี่เกินไป, 5xx เซิร์ฟเวอร์พัง  
- ตัวอย่าง: `เบราว์เซอร์ส่งข้อมูลไป "cart/get" → เซิร์ฟเวอร์ตอบ 200 สำเร็จ ใน 182 ms`

### 4.6 การควบคุมและ export

- Pause/Resume การเก็บ (P0), Clear (P0)  
- เก็บในหน่วยความจำสูงสุด 500 exchange (เก่าสุดออกก่อน) ไม่เขียนลงดิสก์เอง (P0)  
- Export JSON ของทั้ง session หรือ interaction เดียว (P1) เพื่อใช้เป็นสื่อสอนหรือโจทย์แลบ  
- Copy as curl / Copy as Python `requests` (P1) ไม่รวม header ที่ถูกซ่อน

## 5\. Data model และ API

ทุก model เป็น Pydantic v2 เวลาเป็น epoch milliseconds (float) ทั้งหมด id เป็น string สั้น (เช่น `ex_0042`)

```py
class ElementInfo(BaseModel):
    tag: str                 # "button"
    text: str                # "ใส่ตะกร้า" (ตัด 40 ตัวอักษร)
    aria_label: str | None
    element_id: str | None
    classes: list[str]       # สูงสุด 3
    href: str | None
    selector: str            # "div.product-card > button.btn-cart"

class ClickEvent(BaseModel):
    id: str
    tab_id: str
    page_url: str
    ts: float
    element: ElementInfo

class HttpRequest(BaseModel):
    method: str
    url: str
    host: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]          # ผ่าน Redactor แล้ว
    body: str | None                 # ผ่าน Redactor แล้ว
    body_kind: Literal["json", "form", "text", "binary", "none"]

class HttpResponse(BaseModel):
    status: int
    status_text: str
    headers: dict[str, str]
    body: str | None
    body_kind: Literal["json", "form", "text", "binary", "none"]
    body_truncated_bytes: int = 0
    body_error: str | None = None    # เหตุผลที่อ่านไม่ได้

class HttpExchange(BaseModel):
    id: str
    tab_id: str
    page_url: str
    resource_type: Literal["fetch", "xhr"]
    started_at: float
    duration_ms: float | None
    state: Literal["pending", "done", "failed"]
    failure: str | None = None
    request: HttpRequest
    response: HttpResponse | None = None
    hidden: bool = False             # ถูกกรองออก
    hidden_reason: str | None = None # "blocklist: clarity.ms"
    summary: str                     # สรุปภาษาคน

class Interaction(BaseModel):
    id: str
    kind: Literal["click", "page_load", "background"]
    click: ClickEvent | None
    page_url: str
    started_at: float
    exchange_ids: list[str]
```

**WebSocket `/ws`** (server → client เท่านั้น) ส่งข้อความ JSON รูปแบบ `{"type": ..., "data": ...}`

| type | เกิดเมื่อ | data |
| :---- | :---- | :---- |
| `snapshot` | client เชื่อมต่อหรือเชื่อมต่อใหม่ | interactions \+ exchanges ทั้งหมด \+ status |
| `interaction.new` | มีคลิกหรือเปิดกลุ่มใหม่ | `Interaction` |
| `exchange.new` | request ออกไป (ยังไม่มี response) | `HttpExchange` (state \= pending) \+ interaction\_id |
| `exchange.update` | ได้ response หรือล้มเหลว | `HttpExchange` |
| `status` | Chrome เชื่อม/หลุด, pause, จำนวนที่ซ่อน | `{chrome: "connected"|"disconnected", paused: bool, hidden_count: int, tabs: [...]}` |
| `cleared` | กด Clear | `{}` |

การส่ง `exchange.new` แยกจาก `exchange.update` ทำให้ UI แสดง request ที่กำลังรอคำตอบได้ ซึ่งช่วยสอนเรื่อง async

**REST API**

| Method \+ path | หน้าที่ |
| :---- | :---- |
| `GET /` | หน้า UI |
| `GET /api/status` | สถานะการเชื่อมต่อ |
| `GET /api/interactions` | ประวัติทั้งหมด |
| `GET /api/exchanges/{id}` | รายละเอียด exchange เดียว |
| `POST /api/pause`, `POST /api/resume`, `POST /api/clear` | ควบคุมการเก็บ |
| `GET /api/filters`, `PUT /api/filters` | อ่าน/แก้กฎการกรอง (ไม่รวมกฎการซ่อนข้อมูลพื้นฐาน) |
| `GET /api/export?interaction_id=` | ดาวน์โหลด JSON |

ตัว Inspector เองถูกออกแบบให้เป็นตัวอย่าง REST \+ WebSocket ที่นักศึกษาเปิด `/docs` ดูได้

## 6\. UI Spec

UI ออกแบบมาเพื่อจอโปรเจกเตอร์ก่อน คนท้ายห้องต้องอ่านออก: ตัวอักษรใหญ่ สีมีความหมายน้อย และคำอธิบายภาษาไทยคู่กับศัพท์เทคนิคภาษาอังกฤษ (เช่น "ขาออก (Request)")

### 6.1 โครงหน้า

หน้าเดียว แบ่งเป็น 4 ส่วน (ดู wireframe ด้านล่าง):

1. **Top bar** สูง 56 px  
2. **Timeline** คอลัมน์ซ้าย กว้าง 40% (ต่ำสุด 360 px) เลื่อนได้อิสระ  
3. **Detail** คอลัมน์ขวา แสดง exchange ที่เลือก  
4. **Flow strip** แถบบนสุดของ Detail สูง 120 px แสดง Browser ⇄ Server ของ exchange ที่เลือก (P1)

จอกว้างน้อยกว่า 900 px: Timeline และ Detail ซ้อนกัน กด exchange แล้วเปิด Detail เต็มจอ มีปุ่มย้อนกลับ

```
+--------------------------------------------------------------------------------------+
| Web Traffic Inspector   (●) เชื่อมต่อแล้ว · 3 แท็บ   [advice ▾][ซ่อน 42][หยุด][ล้าง][Export][A− A+] |
+------------------------------+-------------------------------------------------------+
| TIMELINE · ใหม่สุดอยู่บน          | [POST] /_advice-api/api/v1.0.0/cart/add*   200 OK · 182 ms |
| +--------------------------+ | เบราว์เซอร์ส่งข้อมูลไป "cart/add*" → ตอบ 200 สำเร็จ ใน 182 ms   |
| | คลิก <button> "ใส่ตะกร้า"  14:32:05 | | ภาพรวม | ขาออก | ขาเข้า | ดิบ | คลิก | โค้ด                |
| | >[POST] …/cart/add* 200 182ms | | +----------------------+ +-------------------------+ |
| |  ส่งข้อมูลไป cart/add* → 200    | | | ขาออก (Request)       | | ขาเข้า (Response)          | |
| |  [POST] …/cart/get  200  95ms | | | POST …/cart/add*      | | 200 · application/json  | |
| +--------------------------+ | | { "รหัสสินค้า": …,      | | { "status": "SUCCESS",  | |
| | เปิดหน้า /product/notebooks   | | |   "จำนวน": 1 }        | |   "data": [ … ] }       | |
| |  [POST] …/category/data 200 | | +----------------------+ +-------------------------+ |
| +--------------------------+ | Flow strip (P1):                                      |
| : เบื้องหลัง · ไม่มีคลิก (จาง)     : | [ผู้ใช้] --click--> [เบราว์เซอร์] --request--> [เซิร์ฟเวอร์] |
| :  [GET] /api/get-category 200: |                          <---200-----              |
| ↑/↓ เลือก · Space หยุด · C ล้าง    |                                                       |
+------------------------------+-------------------------------------------------------+
* ชื่อ endpoint ใส่ตะกร้าเป็นชื่อสมมติ ตัวเลขเวลาเป็นตัวอย่าง
```

กดปุ่มในเว็บแล้วการ์ดใหม่ปรากฏด้านบนซ้าย ส่วนด้านขวาเปิด request หลักของคลิกนั้นให้เอง ผู้สอนไม่ต้องสลับหน้าต่าง

### 6.2 Top bar

จากซ้ายไปขวา:

- ชื่อโปรแกรม "Web Traffic Inspector"  
- **สถานะ Chrome**: จุดสี \+ ข้อความ "เชื่อมต่อแล้ว · 3 แท็บ" (เขียว) / "ไม่พบ Chrome" (แดง) / "หยุดชั่วคราว" (เหลือง)  
- **ตัวเลือก preset การกรอง**: dropdown "ทุกเว็บ / advice.co.th / กำหนดเอง…"  
- **ปุ่มซ่อนอยู่**: "ซ่อน 42 รายการ" เป็น toggle เปิดแล้วแสดงรายการที่ซ่อนแบบจางลง พร้อมป้ายเหตุผล (เช่น "tracking: clarity.ms")  
- ปุ่ม **หยุด / เริ่มต่อ**, **ล้าง**, **Export**  
- **ขนาดตัวอักษร** A− / A+ (3 ระดับ: 14, 17, 20 px) จำค่าไว้ใน `localStorage` ค่าเริ่มต้น 17 px  
- สลับธีมสว่าง/มืด (ค่าเริ่มต้นสว่าง เพราะโปรเจกเตอร์อ่านง่ายกว่า)

### 6.3 Timeline (คอลัมน์ซ้าย)

เรียง Interaction **ใหม่สุดอยู่บน** แต่ละ Interaction เป็นการ์ด:

- **หัวการ์ด**:  
  - คลิก: ไอคอนเมาส์ \+ `คลิก <button> "ใส่ตะกร้า"` \+ เวลา `14:32:05` \+ host ของหน้า  
  - โหลดหน้า: ไอคอนหน้าเอกสาร \+ `เปิดหน้า /product/notebooks`  
  - เบื้องหลัง: ไอคอนนาฬิกา \+ `เกิดเองโดยไม่มีคลิก` (สีอ่อนกว่าการ์ดอื่น)  
- **แถว exchange** ใต้หัวการ์ด แถวละ 1 request:  
  - badge method (GET ฟ้า, POST เขียว, PUT/PATCH ส้ม, DELETE แดง) · path ตัดให้สั้นจากซ้าย (เช่น `…/v1.0.0/cart/get`) · badge status · เวลา ms  
  - สี status: 2xx เขียว, 3xx เทา, 4xx ส้ม, 5xx แดง, failed แดงเส้นประ, pending จุดหมุน \+ "รอคำตอบ…"  
  - บรรทัดที่สอง: สรุปภาษาคน (หัวข้อ 4.5) สีเทา  
- การ์ดใหม่เลื่อนเข้ามาด้านบนพร้อมไฮไลต์ 1.5 วินาที ถ้าผู้ใช้เลื่อนลงไปดูของเก่าอยู่ ไม่เลื่อนอัตโนมัติ แต่แสดงปุ่มลอย "มี 3 รายการใหม่ ↑"  
- **เลือก exchange อัตโนมัติ**: เมื่อมีคลิกใหม่ ให้เลือก exchange หลักของคลิกนั้น: ไม่ใช่ GET และ path บอก action (add, delete, update, login ฯลฯ) ก่อน ถัดมาคือไม่ใช่ GET ทั่วไป แล้วจึงเป็นไม่ใช่ GET ที่ path บอกว่าแค่อ่าน (get, list, search ฯลฯ เพราะบางเว็บใช้ POST ทุก API) สุดท้ายคือ GET คะแนนเท่ากันเลือกตัวที่มาก่อน ตัวที่มาทีหลังแย่งได้เมื่อคะแนนสูงกว่าเท่านั้น ผู้สอนไม่ต้องสลับหน้าต่างมากด ปิดได้ด้วย checkbox "ตามคลิกล่าสุด"  
- คีย์บอร์ด: ↑/↓ เลือก exchange, Space \= หยุด/เริ่มต่อ, C \= ล้าง (ไม่ใช้ Ctrl+L เพราะชนกับเบราว์เซอร์)

### 6.4 Detail (คอลัมน์ขวา)

**หัว Detail**: badge method \+ URL เต็ม (ตัดบรรทัดได้) \+ status \+ เวลา และสรุปภาษาคนตัวใหญ่

แท็บด้านล่าง (จำแท็บที่เลือกไว้เมื่อเปลี่ยน exchange):

| แท็บ | เนื้อหา |
| :---- | :---- |
| ภาพรวม (ค่าเริ่มต้น) | สองกล่องเคียงกัน: ซ้าย "ขาออก (Request)" \= method, path, query เป็นตาราง, body แบบ JSON tree / ขวา "ขาเข้า (Response)" \= status, content-type, body แบบ JSON tree; จอแคบเรียงบน-ล่าง |
| ขาออก (Request) | request line เต็ม, headers เป็นตาราง (key ตัวหนา, ค่าที่ซ่อนมีไอคอนกุญแจ), body |
| ขาเข้า (Response) | status line, headers, body |
| ดิบ (Raw) | ข้อความ HTTP แบบที่ส่งจริง (`POST /path HTTP/1.1` \+ headers \+ บรรทัดว่าง \+ body) ทั้งสองขา ใช้สอนว่า HTTP คือข้อความธรรมดา |
| คลิก (Event) | ข้อมูล element ที่ถูกคลิก (tag, ข้อความ, selector) \+ เวลาจากคลิกถึง request ออก (ms) |
| โค้ด (P1) | Copy as curl, Copy as Python `requests`, Copy as JavaScript `fetch` |

**JSON viewer**: ย่อ/ขยายได้, เปิด 2 ชั้นแรกไว้, สีตามชนิด (string, number, boolean, null), array ยาวแสดง "\[24 รายการ\]" และแสดง 10 รายการแรก, มีปุ่มสลับเป็นข้อความดิบ ค่าที่ถูกซ่อนแสดงเป็น chip สีเทา "ซ่อนไว้"

**form-urlencoded** แสดงเป็นตาราง key/value; body ที่อ่านไม่ได้แสดงเหตุผล เช่น "เป็นไฟล์ binary (application/x-protobuf, 3.2 KB)"

### 6.5 Flow strip (P1)

แถบแนวนอน: กล่อง "ผู้ใช้" → "เบราว์เซอร์ (JavaScript)" → "เซิร์ฟเวอร์ ([www\.advice.co.th](http://www.advice.co.th))" เมื่อเลือก exchange จะเล่นแอนิเมชัน 3 จังหวะ (รวมประมาณ 2 วินาที):

1. จุดวิ่งจากผู้ใช้ → เบราว์เซอร์ ป้าย "click"  
2. ซองจดหมายวิ่งเบราว์เซอร์ → เซิร์ฟเวอร์ ป้าย "POST /cart/get"  
3. ซองวิ่งกลับ ป้าย "200 · 182 ms" สีตาม status

มีปุ่ม "เล่นซ้ำ" และตัวเลือกความเร็ว (1x, 0.5x, 0.25x) เคารพ `prefers-reduced-motion`

### 6.6 สถานะพิเศษ

| สถานะ | สิ่งที่แสดง |
| :---- | :---- |
| ยังไม่พบ Chrome | กลางจอ: "ไม่พบ Chrome ที่พอร์ต 9222" \+ คำสั่งเปิด Chrome ตาม OS ที่ตรวจพบ พร้อมปุ่มคัดลอก และลองเชื่อมใหม่ทุก 2 วินาที |
| เชื่อมแล้ว ยังไม่มีข้อมูล | "พร้อมแล้ว — ลองเปิดเว็บใน Chrome แล้วกดปุ่มสักปุ่ม" |
| Chrome หลุดระหว่างใช้ | แถบเหลืองใต้ top bar ข้อมูลเดิมยังอยู่ เชื่อมใหม่อัตโนมัติ |
| WebSocket ของ UI หลุด | แถบเทา "กำลังเชื่อมต่อ Inspector ใหม่…" reconnect แบบ backoff 1–5 วินาที แล้วขอ `snapshot` |
| หยุดชั่วคราว | แถบเหลือง "หยุดเก็บชั่วคราว — กด Space เพื่อเริ่มต่อ" |
| คลิกแต่ไม่มี request | การ์ดคลิกแสดง "ไม่มี API call — ปุ่มนี้ทำงานในเบราว์เซอร์อย่างเดียว" (เป็นจุดสอนที่ดี) |

### 6.7 แนวทางภาพ

- ฟอนต์: "IBM Plex Sans Thai" หรือ "Sarabun" จาก Google Fonts (fallback ฟอนต์ระบบ) โค้ด/JSON ใช้ "JetBrains Mono" หรือ `ui-monospace`  
- สีกำหนดเป็น CSS variables ที่ `:root` และมีชุดธีมมืด สี method/status ต้องมี contrast ต่อพื้นหลังอย่างน้อย 4.5:1 และมีตัวอักษรกำกับเสมอ (ไม่พึ่งสีอย่างเดียว)  
- ไอคอนใช้ inline SVG ไม่ใช้ emoji  
- ไม่มีไฟล์จาก CDN อื่น ใช้งานได้แม้ไม่มีอินเทอร์เน็ต (ยกเว้นฟอนต์ที่ fallback ได้)

## 7\. การติดตั้งและใช้งาน

ต้องมี Python 3.11+ และ Google Chrome ทำงานได้ทั้ง Windows และ macOS

**ติดตั้งครั้งเดียว**

```sh
pip install -r requirements.txt
# fastapi, uvicorn[standard], playwright, pydantic>=2
# ไม่ต้องรัน playwright install เพราะใช้ Chrome ที่มีอยู่
```

**ขั้นที่ 1: เปิด Chrome โหมด debug** (โปรเจกต์มีสคริปต์ให้ดับเบิลคลิก) ต้องปิด Chrome ที่ใช้โปรไฟล์เดียวกันก่อน โปรไฟล์แยกนี้ไม่กระทบ Chrome ปกติ

`scripts/start_chrome.bat` (Windows):

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --remote-debugging-address=127.0.0.1 ^
  --user-data-dir="%LOCALAPPDATA%\TrafficInspectorProfile" ^
  --no-first-run https://www.advice.co.th
```

`scripts/start_chrome.command` (macOS: executable bit อยู่ใน git แล้ว ถ้าดาวน์โหลดเป็น ZIP อาจติด Gatekeeper ดู README):

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$HOME/.traffic-inspector-profile" \
  --no-first-run https://www.advice.co.th >/dev/null 2>&1 &  # สคริปต์จริงขึ้นต้นด้วย nohup
```

**ขั้นที่ 2: รัน Inspector**

```sh
python -m inspector            # เชื่อม Chrome ที่เปิดอยู่
python -m inspector --launch-chrome   # (P1) เปิด Chrome ให้ด้วย
```

โปรแกรมเปิด `http://127.0.0.1:8000` ให้อัตโนมัติ (ปิดได้ด้วย `--no-open`) แนะนำให้วางหน้าต่าง Chrome และ Inspector ซ้าย-ขวาบนจอโปรเจกเตอร์

**ตัวเลือก command line**

| Option | ค่าเริ่มต้น | ความหมาย |
| :---- | :---- | :---- |
| `--cdp-url` | `http://127.0.0.1:9222` | ที่อยู่ Chrome DevTools Protocol |
| `--port` | `8000` | พอร์ตของหน้า Inspector |
| `--preset` | `all` | ชื่อ preset การกรอง เช่น `advice` |
| `--window-ms` | `1500` | ช่วงเวลาจับคู่คลิกกับ request |
| `--max-exchanges` | `500` | จำนวนสูงสุดที่เก็บในหน่วยความจำ |
| `--launch-chrome` | ปิด | (P1) หา Chrome ตาม OS แล้วเปิดด้วย flag ด้านบน |

## 8\. โครงสร้างโปรเจกต์และ class design

โค้ดต้องอ่านง่ายในระดับนักศึกษาปี 2: แต่ละ class มีหน้าที่เดียว, มี type hints ครบ, docstring ภาษาไทยสั้นๆ บอกว่า class นี้สอนแนวคิด OOP อะไร

```
web-traffic-inspector/
├─ inspector/
│  ├─ __main__.py        # อ่าน CLI args, ประกอบทุก object, รัน uvicorn + capture บน loop เดียว
│  ├─ models.py          # Pydantic models (หัวข้อ 5)
│  ├─ capture_events.py  # Capture event: ข้อมูลล้วนที่ฝั่ง capture ส่งให้ pipeline
│  ├─ chrome.py          # ChromeConnector + คำสั่งเปิด Chrome ตาม OS
│  ├─ chrome_launcher.py # --launch-chrome: หา Chrome ในเครื่องแล้วเปิดโหมด debug
│  ├─ capture.py         # TrafficCapture
│  ├─ post_data.py       # PostDataReader: ขอ body ที่ Chrome ไม่แนบมา (ฟอร์มที่มีไฟล์)
│  ├─ click_tracker.py   # ClickTracker
│  ├─ click_hook.js      # สคริปต์ที่ฉีดเข้าหน้าเว็บ
│  ├─ filters.py         # FilterRule + subclasses, FilterChain, Preset
│  ├─ redactor.py        # Redactor
│  ├─ multipart.py       # แยก body multipart/form-data ให้ Redactor
│  ├─ http_parts.py      # ฟังก์ชันช่วยแยก URL และชนิดของ body
│  ├─ correlator.py      # Correlator
│  ├─ summarizer.py      # Summarizer (สรุปภาษาคน)
│  ├─ code_snippets.py   # แท็บโค้ด: curl / Python requests / fetch
│  ├─ pipeline.py        # InspectorPipeline: capture → filter → redact → correlate → store → broadcast
│  ├─ store.py           # EventStore
│  ├─ broadcaster.py     # Broadcaster (จัดการ WebSocket clients)
│  ├─ recording.py       # อ่านไฟล์ Recording, ตั้งชื่อไฟล์ export
│  ├─ demo.py            # --demo: ป้อน Capture event ตัวอย่าง
│  ├─ clock.py           # นาฬิกา epoch ms (ADR 0001)
│  ├─ app.py             # FastAPI app factory: create_app(pipeline, store, broadcaster)
│  └─ static/            # index.html, app.js, style.css
├─ presets/
│  ├─ all.json
│  └─ advice.json
├─ scripts/start_chrome.bat, start_chrome.command
├─ tests/               # pytest (`-m chrome` = test ที่เปิด Chrome จริง)
├─ docs/                # SPEC.md, adr/, specs/, คู่มือการใช้งาน.pdf (ต้นฉบับใน guide/)
├─ CONTEXT.md           # ศัพท์ของโปรเจกต์
├─ requirements.txt, requirements-dev.txt, pyproject.toml
└─ README.md            # ภาษาไทย
```

| Class | หน้าที่ | แนวคิด OOP ที่ใช้สอน |
| :---- | :---- | :---- |
| `ChromeConnector` | เชื่อม/เชื่อมใหม่ CDP, แจ้ง page ใหม่ | encapsulation (ซ่อนรายละเอียด Playwright) |
| `TrafficCapture` | แปลง event ของ Playwright เป็น `HttpExchange` | adapter |
| `ClickTracker` | ฉีด `click_hook.js` และรับ `ClickEvent` | callback / event |
| `FilterRule` (abstract) | `matches(exchange) -> str | None` (คืนเหตุผลที่ซ่อน) | abstract base class |
| `HostBlockRule`, `PathPrefixRule`, `ResourceTypeRule` | กฎการกรองแต่ละแบบ | inheritance \+ polymorphism |
| `FilterChain` | รวมหลาย rule, โหลดจาก preset JSON | composition |
| `Redactor` | ซ่อนข้อมูลลับใน headers, query, body | single responsibility |
| `Correlator` | จัด exchange เข้า `Interaction` | state ใน object |
| `Summarizer` | สร้างประโยคสรุป | ทดสอบง่าย (pure method) |
| `EventStore` | เก็บในหน่วยความจำแบบมีเพดาน (`collections.deque`) | `__len__`, `__iter__` (dunder methods) |
| `Broadcaster` | เก็บ WebSocket clients และส่งข้อความ | observer pattern |
| `InspectorPipeline` | ต่อส่วนต่างๆ: capture → filter → redact → correlate → summarize → store → broadcast | dependency injection ผ่าน `__init__` |

**กฎการเขียนโค้ด**

- แต่ละ class สร้างและทดสอบได้โดยไม่ต้องมี Chrome (ยกเว้น `ChromeConnector`, `TrafficCapture`, `ClickTracker`)  
- ไม่มี global state; `app.py` รับ object ผ่าน `create_app(...)`  
- ไม่ใช้ framework ฝั่ง frontend และไม่มี build step เพื่อให้นักศึกษาเปิด `app.js` อ่านได้ตรงๆ  
- `app.js` แยกเป็น class เล็กๆ เช่น `InspectorSocket`, `TimelineView`, `DetailView`, `JsonViewer`, `FlowStrip` ให้ล้อกับฝั่ง Python

## 9\. Acceptance criteria และแผนทดสอบ

### 9.1 ข้อมูลจริงจาก advice.co.th

ตรวจด้วยเบราว์เซอร์จริงเมื่อ 5 พ.ย. 2569 (เว็บอาจเปลี่ยนได้):

- API ของเว็บเป็น `POST https://www.advice.co.th/_advice-api/api/v1.0.0/...` เช่น `get-popup-home`, `cart/get`, `product/get`, `product/compare`, `product/category/data` และมี `GET /api/get-category`, `/api/get-content/where-to-buy`  
- ตัวอย่าง response ของ `cart/get` ตอนตะกร้าว่าง: `{"status":"SUCCESS","statusCode":"200","data":[],"message":"","message_m":""}`  
- หน้า `/product/notebooks` หน้าเดียวมี fetch/XHR ไป analytics/ads ราว 20+ ตัว (Google Analytics, googlesyndication, clarity.ms, ahrefs, `*.run.app/events`) ปนกับ API จริง 5–6 ตัว  
- เว็บมี Cloudflare challenge script (`/cdn-cgi/challenge-platform/...`)  
- หน้ารวมสินค้ามีปุ่ม "ซื้อเลย" ส่วน endpoint สำหรับเพิ่มลงตะกร้ายังไม่ได้ตรวจ (จะเห็นตอนทดสอบขั้นที่ 4\)

### 9.2 ขั้นทดสอบกับเว็บจริง (preset `advice`)

- [ ] 1\. เปิด Inspector ก่อน Chrome: แสดงสถานะ "ไม่พบ Chrome" พร้อมคำสั่ง และเชื่อมต่อเองภายใน 5 วินาทีหลังเปิด Chrome  
- [ ] 2\. เปิดหน้าแรก: มีการ์ด "โหลดหน้า" ที่มี `get-popup-home` และ `cart/get` และตัวนับ "ซ่อน" มากกว่า 0  
- [ ] 3\. คลิกเมนูไปหมวดโน้ตบุ๊ก: มีการ์ดคลิกที่บอกข้อความปุ่มถูกต้อง และมี `product/category/data` ที่ response เป็น JSON กดดูได้  
- [ ] 4\. เข้าหน้าสินค้าแล้วกดเพิ่มลงตะกร้า: Detail เลือก request หลักให้อัตโนมัติ แสดง body ขาออก (เช่นรหัสสินค้า, จำนวน) และ response ขาเข้า ตามด้วย `cart/get` ที่ `data` ไม่ว่างแล้ว  
- [ ] 5\. เปิดแท็บขาออก: ไม่มีค่า cookie หรือ token จริงปรากฏที่ใด (รวมถึงไฟล์ export และ curl ที่คัดลอก)  
- [ ] 6\. เปิด toggle "ซ่อน": เห็น request ไป google-analytics.com, clarity.ms พร้อมเหตุผล  
- [ ] 7\. เปิดแท็บใหม่ใน Chrome: คลิกในแท็บใหม่ถูกดักด้วย  
- [ ] 8\. ปิด Chrome แล้วเปิดใหม่: Inspector ไม่ crash แสดงแถบหลุดแล้วกลับมาเชื่อมต่อ  
- [ ] 9\. กด A+ จนสุด (20 px) บนจอ 1366×768: ไม่มี scroll แนวนอนทั้งหน้า อ่านได้จากท้ายห้อง  
- [ ] 10\. การดักไม่ทำให้เว็บทำงานผิดปกติ (ปุ่มทุกปุ่มทำงานเหมือนไม่มี Inspector)

### 9.3 Unit tests (pytest, ไม่ต้องใช้ Chrome)

- `Redactor`: header อ่อนไหวถูกซ่อน, JSON ซ้อนหลายชั้นถูกซ่อน, cookie เหลือแต่ชื่อ, body ที่ไม่ใช่ JSON ไม่ crash  
- `FilterChain`: blocklist, focus rule, เหตุผลที่ซ่อนถูกต้อง, โหลด preset ได้  
- `Correlator`: request ในช่วง 1500 ms เข้ากลุ่มคลิก, เกินเวลาเป็น background, คลิกซ้อนเปิดกลุ่มใหม่, แยกตาม tab  
- `Summarizer`: ครบทุก method และ status ในหัวข้อ 4.5  
- `EventStore`: ตัดที่ 500 รายการ  
- `app.py`: ทดสอบ REST และ WebSocket ด้วย `TestClient` (ได้ `snapshot` ตอนเชื่อม, ได้ `exchange.new` เมื่อ pipeline รับข้อมูลปลอม)  
- Integration test (เลือกได้, mark `@pytest.mark.chrome`): เปิดหน้า HTML ทดสอบใน `tests/fixtures/` ที่มีปุ่มเรียก fetch ไป FastAPI จำลอง แล้วตรวจว่าได้ Interaction ที่ถูกต้อง

## 10\. จริยธรรม ความปลอดภัย และการส่งต่อให้ Claude Code

### 10.1 กฎที่ต้องฝังในโปรแกรม

- ดูอย่างเดียว: ไม่มีฟีเจอร์แก้ บล็อก หรือส่ง request ซ้ำ (ยกเว้น slow-motion P2 ที่หน่วงเวลาอย่างเดียว)  
- Inspector server และพอร์ต CDP bind เฉพาะ `127.0.0.1` เท่านั้น เพราะใครเข้าถึงพอร์ต 9222 ได้ ควบคุม Chrome ได้ทั้งตัว ให้ README เตือนเรื่องนี้ชัดเจน  
- การซ่อนข้อมูลลับทำก่อนเก็บ ปิดไม่ได้ และไม่เขียนอะไรลงดิสก์เอง  
- หน้า Inspector แสดงแถบเตือนครั้งแรก (ปิดได้): "ใช้ดู traffic ของตัวเองเพื่อการเรียนรู้เท่านั้น อย่านำ API ของเว็บอื่นไปเรียกซ้ำหรือดึงข้อมูลจำนวนมาก"

### 10.2 ข้อแนะนำตอนสาธิตในห้อง

- ใช้โปรไฟล์ Chrome แยก ไม่ล็อกอินบัญชีส่วนตัว หากต้องล็อกอินให้ใช้บัญชีสำหรับสาธิต  
- หยุดก่อนขั้นชำระเงินเสมอ และลบสินค้าออกจากตะกร้าหลังสาธิต (การลบก็เป็น request ที่น่าสอนอีกตัว)  
- เตรียมไฟล์ export ของรอบซ้อมไว้ กรณีเน็ตในห้องมีปัญหา (P1: เปิดไฟล์ export ดูใน Inspector ได้ด้วย `--replay-file`)

### 10.3 Prompt สำหรับ Claude Code

Export doc นี้เป็น Markdown วางไว้ที่ `docs/SPEC.md` ในโฟลเดอร์โปรเจกต์ แล้วใช้ prompt นี้:

```
อ่าน docs/SPEC.md ทั้งหมดก่อนเริ่ม แล้วสร้างโปรแกรม Web Traffic Inspector ตาม spec

ลำดับการทำงาน:
1. สรุปแผนสั้นๆ และถามฉันถ้ามีส่วนไหนใน spec ไม่ชัด
2. ทำ models.py, filters.py, redactor.py, correlator.py, summarizer.py, store.py พร้อม unit tests ตามหัวข้อ 9.3 ให้ผ่านก่อน
3. ทำ broadcaster.py และ app.py (REST + WebSocket) พร้อม test ด้วย TestClient
4. ทำ chrome.py, capture.py, click_hook.js, __main__.py
5. ทำ UI ใน static/ ตามหัวข้อ 6 (P0 ก่อน แล้วค่อย P1)
6. ทำ scripts/ และ README.md ภาษาไทย

ข้อกำหนด:
- ทำ P0 ให้ครบและทดสอบก่อน ค่อยทำ P1 ห้ามทำสิ่งที่หัวข้อ 2 บอกว่า "ไม่ทำ"
- รักษากฎในหัวข้อ 10.1 เคร่งครัด โดยเฉพาะ redaction และ bind 127.0.0.1
- โค้ดต้องอ่านง่ายสำหรับนักศึกษาปี 2 ตามหัวข้อ 8 มี type hints และ docstring ภาษาไทย
- frontend เป็น vanilla JS ไม่มี build step
- หลังแต่ละขั้น รัน pytest และสรุปสิ่งที่ทำ
- สุดท้าย บอกวิธีทดสอบด้วยมือตาม checklist หัวข้อ 9.2
```

