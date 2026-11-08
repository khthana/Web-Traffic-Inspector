# Web Traffic Inspector

เครื่องมือสอนที่ดู traffic ของ Chrome ผู้สอนแบบอ่านอย่างเดียว แล้วแสดงว่าการคลิกหนึ่งครั้งทำให้เกิด request อะไรและ server ตอบอะไรกลับมา

## Language

**Exchange**:
คู่ request/response หนึ่งคู่ของ fetch หรือ XHR ที่ดักได้ (หรือ request ที่ล้มเหลว)
_Avoid_: request (เมื่อหมายถึงทั้งคู่), call, transaction

**Interaction**:
กลุ่มของ Exchange ที่มีสาเหตุร่วมกัน มีสามแบบ: Click interaction, Page-load interaction และ Background interaction
_Avoid_: group, session, card (การ์ดคือสิ่งที่ UI ใช้แสดง Interaction)

**Click interaction**:
Interaction ที่เปิดเมื่อผู้ใช้คลิก รับ Exchange ที่เริ่มภายใน Correlation window ในแท็บเดียวกัน ถ้าคลิกนั้นทำให้เกิด Navigation ก็รับ Exchange ของหน้าใหม่ด้วย

**Page-load interaction**:
Interaction ของ Navigation ที่ไม่มีคลิกนำหน้า เช่น พิมพ์ URL เอง, refresh หรือกด back

**Background interaction**:
Interaction ของ Exchange ที่ไม่ได้มาจากคลิกหรือ Navigation ใดเลย เช่น timer หรือ polling แต่ละแท็บมีได้ครั้งละหนึ่งอัน รับ Exchange เบื้องหลังต่อไปเรื่อยๆ จนกว่าจะมีคลิกหรือ Navigation ในแท็บนั้น

**Watched tab**:
แท็บใน Chrome ที่ Inspector ดัก traffic และคลิก ไม่รวมแท็บที่เปิดหน้า Inspector เอง และแท็บ `chrome://`, `devtools://` หรือ `chrome-extension://`
_Avoid_: page (ใช้เฉพาะเมื่อพูดถึง object ของ Playwright)

**Navigation**:
การโหลด document ใหม่ของ main frame ในแท็บ การเปลี่ยน URL แบบ SPA (`pushState`) ไม่นับเป็น Navigation

**Correlation window**:
ช่วงเวลาหลังคลิก (ค่าเริ่มต้น 1500 ms) ที่ Exchange ที่เริ่มในช่วงนั้นถูกนับเป็นผลของคลิก ถ้าคลิกทำให้เกิด Navigation ช่วงนี้จะขยายไปอีก 5 วินาทีนับจาก Navigation

**Hidden exchange**:
Exchange ที่ถูกกรองออกจากมุมมองปกติ แต่ยังเก็บไว้พร้อมเหตุผลที่ซ่อน และอยู่ใน buffer แยกจาก Exchange ที่แสดง
_Avoid_: blocked, filtered-out request, junk

**Hidden reason**:
ข้อความบอกว่าทำไม Exchange ถูกซ่อน มีสองแบบ: `tracking: <host>` (ติด Blocklist) และ `นอกโฟกัส: preset <ชื่อ>` (ไม่ตรง Focus rule) ถ้าติดทั้งสองแบบให้ใช้แบบ tracking

**Blocklist**:
รายการ host/path ของ analytics, ads และ tracking ที่ถูกซ่อนเสมอ ไม่ว่าจะเลือก Preset ไหน

**Focus rule**:
เงื่อนไขในทางบวกของ Preset ถ้า Preset มี Focus rule จะแสดงเฉพาะ Exchange ที่ตรงเงื่อนไข ตัวที่ไม่ตรงจะกลายเป็น Hidden exchange

**Preset**:
ชุดกฎการกรองที่มีชื่อ (เช่น `all`, `advice`) ผู้สอนเลือกได้ครั้งละหนึ่งชุด

**Redaction**:
การแทนค่าลับด้วย `••••` ก่อนที่ Exchange จะถูกเก็บ ครอบคลุม headers, query, URL ทุกตัว, JSON (รวม body ชนิด text ที่เป็น JSON object หรือ array), form และ multipart body (ไฟล์แนบเหลือแค่ชื่อ ชนิด และขนาด) ทั้งฝั่ง request และ response ปิดไม่ได้ ค่าที่ซ่อนมีทั้งข้อมูลส่วนตัว ข้อมูลยืนยันตัวตน และรหัสติดตามผู้ใช้ (เช่น `_fbp`, `_ga`, `gclid`)
_Avoid_: masking, sanitizing, censoring

**Recording**:
ไฟล์ JSON ที่ export ออกมาจาก session หรือจาก Interaction เดียว ผ่าน Redaction มาแล้ว

**Recording playback**:
โหมดที่โหลด Recording เข้า Inspector เพื่อดูโดยไม่ต่อ Chrome (flag `--replay-file`) ไม่มีการส่ง request ใดๆ ออกไป
_Avoid_: replay (ใน spec คำนี้หมายถึงการส่ง request ซ้ำ ซึ่งเป็นสิ่งที่ห้ามทำ)

**Hidden count**:
จำนวน Hidden exchange ทั้งหมดตั้งแต่ Clear ครั้งล่าสุด รวมรายการที่หลุดออกจาก buffer ไปแล้ว
