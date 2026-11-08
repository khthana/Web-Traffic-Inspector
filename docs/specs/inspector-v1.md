# Web Traffic Inspector v1 (P0 + P1) — Spec

Nov 7, 2026 · GitHub issue: [#1](https://github.com/khthana/Web-Traffic-Inspector/issues/1)

> spec ฉบับเต็ม (UI, data model, API) อยู่ที่ `docs/SPEC.md` ส่วนคำศัพท์อยู่ที่ `CONTEXT.md` issue นี้สรุป spec นั้น และเพิ่มข้อตกลงที่ได้จากการ grilling (ดูหัวข้อ Implementation Decisions) ถ้าขัดกับ `docs/SPEC.md` ให้ยึด issue นี้

## Problem Statement

ผู้สอนวิชา OOP ที่ใช้ Web เป็น frontend และ FastAPI เป็น backend ต้องการให้นักศึกษาเห็นว่า "กดปุ่มหนึ่งครั้ง → เบราว์เซอร์ส่ง HTTP request อะไร → server ตอบอะไร" บนเว็บจริงอย่าง advice.co.th

ตอนนี้ทางเดียวที่ทำได้คือเปิด Chrome DevTools ซึ่งมีปัญหาหลายข้อ
- ตัวหนังสือเล็ก คนท้ายห้องอ่านบนจอโปรเจกเตอร์ไม่ออก
- ไม่ได้ผูก request เข้ากับคลิกที่เป็นต้นเหตุ
- แสดง traffic ของ analytics และ ads ปนกับ API จริง (หน้าเดียวมีขยะ 20 ตัวขึ้นไป แต่มี API จริงแค่ 5–6 ตัว)
- โชว์ cookie และ token จริงบนจอหน้าห้อง
- นักศึกษาอ่านโค้ดของ DevTools เพื่อเรียนรู้ไม่ได้

## Solution

โปรแกรม Python ตัวเดียว (`python -m inspector`) ที่ต่อเข้ากับ Chrome ตัวจริงของผู้สอนผ่าน CDP ทำงานแบบอ่านอย่างเดียว แล้วแสดงหน้า Inspector แบบ real-time ที่ `127.0.0.1:8000`

- จัด Exchange เป็น Interaction ตามคลิกที่เป็นต้นเหตุ
- ซ่อนขยะ tracking อัตโนมัติ แต่ยังกดดูได้
- ทำ Redaction ข้อมูลลับก่อนเก็บทุกครั้ง
- สรุป Exchange แต่ละตัวเป็นภาษาไทยที่อ่านเข้าใจ
- UI ออกแบบมาเพื่อจอโปรเจกเตอร์

ตัวโปรแกรมเองก็เป็นตัวอย่าง OOP + FastAPI + WebSocket ที่นักศึกษาปี 2 เปิดอ่านได้

## User Stories

**การเชื่อมต่อ Chrome**

1. ในฐานะผู้สอน ฉันอยากให้ Inspector ต่อเข้ากับ Chrome ที่เปิดโหมด debug อยู่แล้ว เพื่อให้เว็บเห็นฉันเป็นผู้ใช้ปกติ ไม่โดน Cloudflare บล็อก
2. ในฐานะผู้สอน ฉันอยากเห็นคำสั่งเปิด Chrome ที่ตรงกับ OS พร้อมปุ่มคัดลอก ตอนที่ยังไม่พบ Chrome เพื่อจะได้แก้ปัญหาหน้าห้องได้ทันที
3. ในฐานะผู้สอน ฉันอยากให้ Inspector ลองเชื่อมใหม่ทุก 2 วินาที และเชื่อมได้ภายใน 5 วินาทีหลังเปิด Chrome เพื่อจะได้ไม่ต้องรีสตาร์ตโปรแกรม
4. ในฐานะผู้สอน ฉันอยากให้ Inspector ไม่ crash เมื่อปิด Chrome ไป แต่แสดงแถบเหลืองและเชื่อมใหม่เอง โดยข้อมูลเดิมยังอยู่
5. ในฐานะผู้สอน ฉันอยากให้แท็บที่เปิดใหม่ระหว่างใช้งานกลายเป็น Watched tab อัตโนมัติ เพื่อจะได้สาธิตหลายแท็บได้
6. ในฐานะผู้สอน ฉันอยากให้แท็บที่เปิดหน้า Inspector เอง และแท็บ `chrome://` / `devtools://` / `chrome-extension://` ไม่ถูกดัก เพื่อไม่ให้ traffic ของ Inspector วนกลับมาท่วม Timeline
7. ในฐานะผู้สอน ฉันอยากเห็นจำนวน Watched tab ที่ top bar เพื่อให้มั่นใจว่ากำลังดักแท็บที่ถูกต้อง
8. ในฐานะผู้สอน ฉันอยากใช้ `--launch-chrome` ให้ Inspector หาและเปิด Chrome ด้วย flag ที่ถูกต้องให้ เพื่อจะได้ไม่ต้องจำคำสั่ง
9. ในฐานะนักศึกษาในแลบ ฉันอยากมีสคริปต์ดับเบิลคลิกเปิด Chrome บน Windows และ macOS เพื่อให้เริ่มใช้งานได้ง่าย

**การดักและจัดกลุ่ม**

10. ในฐานะผู้สอน ฉันอยากให้ดักเฉพาะ fetch/XHR เพื่อไม่ให้มีรูป CSS ฟอนต์ และ script ปนเข้ามา
11. ในฐานะนักศึกษา ฉันอยากเห็นทุกคลิกเป็นการ์ดที่บอก tag และข้อความของปุ่ม เช่น `คลิก <button> "ใส่ตะกร้า"` เพื่อจะได้รู้ว่า request ไหนมาจากปุ่มไหน
12. ในฐานะนักศึกษา ฉันอยากให้ Exchange ที่เริ่มภายใน Correlation window หลังคลิก อยู่ใต้การ์ดของคลิกนั้น เพื่อจะได้เห็นว่า event หนึ่งครั้งทำให้เกิด request อะไรบ้าง
13. ในฐานะผู้สอน ฉันอยากให้คลิกใหม่ที่เกิดก่อนหมด Correlation window เปิด Click interaction ใหม่ เพื่อไม่ให้ request ของสองปุ่มปนกัน
14. ในฐานะผู้สอน ฉันอยากให้การจับคู่แยกตามแท็บ เพื่อไม่ให้คลิกในแท็บหนึ่งไปดูด request ของอีกแท็บ
15. ในฐานะนักศึกษา ฉันอยากให้คลิกลิงก์ที่ทำให้เกิด Navigation แสดงเป็นการ์ดเดียวว่า `คลิก <a> "โน้ตบุ๊ก" → เปลี่ยนหน้าไป /product/notebooks` โดยมี Exchange ของหน้าใหม่ (ภายใน 5 วินาทีหลัง Navigation) อยู่ในการ์ดเดียวกัน
16. ในฐานะนักศึกษา ฉันอยากเห็น Page-load interaction เมื่อมีการพิมพ์ URL เอง กด refresh หรือกด back เพื่อแยกออกจาก Exchange ที่เกิดจากคลิก
17. ในฐานะผู้สอน ฉันอยากให้การเปลี่ยน URL แบบ SPA (`pushState`) ไม่ถูกนับเป็น Navigation เพื่อให้ request ของ SPA ยังอยู่ในการ์ดคลิก
18. ในฐานะนักศึกษา ฉันอยากเห็น Exchange ที่เกิดเองโดยไม่มีคลิก รวมอยู่ใน Background interaction เดียวของแท็บนั้น สีจาง เพื่อให้เข้าใจว่ามี timer หรือ polling ทำงานอยู่
19. ในฐานะผู้สอน ฉันอยากให้การ์ด Background interaction ที่ได้ Exchange ใหม่อยู่ที่เดิม ไม่กระโดดขึ้นบนสุด เพื่อให้คนดูบนจอโปรเจกเตอร์ตามทัน
20. ในฐานะนักศึกษา ฉันอยากเห็นข้อความ "ไม่มี API call — ปุ่มนี้ทำงานในเบราว์เซอร์อย่างเดียว" เมื่อคลิกแล้วไม่มี Exchange ที่มองเห็น พร้อมจำนวน tracking ที่ซ่อนอยู่ เพื่อเรียนรู้ว่าไม่ใช่ทุกปุ่มจะเรียก API แต่เกือบทุกปุ่มถูก track
21. ในฐานะผู้สอน ฉันอยากให้การดักคลิกไม่ทำให้เว็บทำงานผิดปกติ (ไม่เรียก `preventDefault` หรือ `stopPropagation`) เพื่อให้สาธิตได้ราบรื่น
22. ในฐานะผู้ใช้ ฉันอยากให้ค่าที่พิมพ์ในช่อง input ไม่ถูกส่งออกมาจากสคริปต์ดักคลิกเลย เพื่อความเป็นส่วนตัว
23. ในฐานะนักศึกษา ฉันอยากเห็น Exchange ที่ยังไม่ได้คำตอบในสถานะ "รอคำตอบ…" แล้วค่อยอัปเดตเมื่อ response มาถึง เพื่อให้เข้าใจเรื่อง async
24. ในฐานะนักศึกษา ฉันอยากเห็น request ที่ล้มเหลว (network error, CORS, abort) เป็นสถานะ failed พร้อมเหตุผล
25. ในฐานะนักศึกษา ฉันอยากเห็นเหตุผลเมื่ออ่าน body ไม่ได้ เช่น "เป็นไฟล์ binary (application/x-protobuf, 3.2 KB)" เพื่อไม่ให้สับสนว่าทำไม body ว่าง
26. ในฐานะผู้สอน ฉันอยากให้ response body ที่ยาวเกิน 64 KB ถูกตัด พร้อมบอกว่าตัดไปเท่าไร เพื่อให้หน้าเว็บไม่ค้าง

**การกรอง**

27. ในฐานะผู้สอน ฉันอยากให้ Blocklist พื้นฐาน (analytics, ads, `/cdn-cgi/`) ซ่อน traffic ขยะเสมอ เพื่อให้ Timeline มีแต่ API จริง
28. ในฐานะผู้สอน ฉันอยากเลือก Preset `advice` จาก dropdown เพื่อดูเฉพาะ `/_advice-api/` และ `/api/` ของ www.advice.co.th
29. ในฐานะผู้สอน ฉันอยากให้ Exchange ที่ไม่ตรง Focus rule เป็น Hidden exchange ด้วย Hidden reason `นอกโฟกัส: preset advice` เพื่อให้กดดูได้ว่าตัดอะไรทิ้งไป
30. ในฐานะนักศึกษา ฉันอยากกดปุ่ม "ซ่อน 42 รายการ" แล้วเห็น Hidden exchange แบบจางพร้อม Hidden reason เช่น `tracking: clarity.ms` เพื่อเรียนเรื่อง tracking
31. ในฐานะผู้สอน ฉันอยากให้ Hidden count นับทั้งหมดตั้งแต่กด Clear ครั้งล่าสุด แม้ตัวเก่าจะหลุดจาก buffer ไปแล้ว เพื่อให้ตัวเลขสะท้อนปริมาณ tracking จริง
32. ในฐานะผู้สอน ฉันอยากให้ Hidden exchange ไม่ไปดัน Exchange ที่มองเห็นออกจากหน่วยความจำ เพื่อย้อนดู request จริงได้ตลอดการสาธิต
33. ในฐานะผู้สอน ฉันอยากให้เปลี่ยน Preset แล้ว Exchange ที่เก็บไว้ถูกคำนวณสถานะซ่อน/แสดงใหม่ทันที
34. ในฐานะผู้สอน ฉันอยากเลือก "กำหนดเอง…" เพื่อแก้กฎการกรองระหว่างสอน (Preset `custom` ที่อยู่ในหน่วยความจำเท่านั้น)
35. ในฐานะผู้สอน ฉันอยากให้ Page-load และ Background interaction ที่มีแต่ Hidden exchange ไม่แสดงการ์ด (ยกเว้นตอนเปิด toggle "ซ่อน") เพื่อไม่ให้ beacon ท่วม Timeline

**Redaction**

36. ในฐานะผู้สอน ฉันอยากให้ค่า cookie, set-cookie, authorization และ header ที่ชื่อมี token/session/auth/csrf/key/secret ถูกซ่อน โดยบอกความยาวไว้ เพื่อสาธิตหน้าห้องได้อย่างปลอดภัย
37. ในฐานะนักศึกษา ฉันอยากเห็นชื่อ cookie (เช่น `PHPSESSID=••••`) เพื่อเรียนเรื่อง session โดยไม่เห็นค่าจริง
38. ในฐานะผู้สอน ฉันอยากให้ key อ่อนไหวใน JSON body, form body และ query string ถูกซ่อนแบบ recursive ทั้ง request และ response เพื่อไม่ให้รหัสผ่าน token อีเมล หรือเบอร์โทรขึ้นจอ
39. ในฐานะผู้สอน ฉันอยากให้ URL ทุกตัว (URL ของ request, URL ของหน้า, `href` ของ element ที่คลิก) ผ่าน Redaction ด้วย เพื่อไม่ให้ `?token=` หลุดไปใน Raw, curl หรือ export
40. ในฐานะผู้สอน ฉันอยากเห็นป้าย "ไม่ได้ตรวจหาข้อมูลลับ" บน text body ที่ไม่ใช่ JSON หรือ form เพื่อให้รู้ว่าต้องระวังเอง
41. ในฐานะผู้สอน ฉันอยากให้ Redaction ปิดไม่ได้ และทำก่อนเก็บ เพื่อให้ไม่มีค่าจริงหลุดไปถึง UI, export หรือ curl ได้เลย
42. ในฐานะผู้สอน ฉันอยากเพิ่ม key ที่ต้องซ่อนผ่าน Preset ได้ (เพิ่มได้อย่างเดียว ลดไม่ได้) เพื่อรองรับเว็บที่ใช้ชื่อ field แปลกๆ

**Timeline และ Detail**

43. ในฐานะนักศึกษา ฉันอยากเห็นประโยคสรุปภาษาไทยใต้ Exchange แต่ละตัว เช่น `เบราว์เซอร์ส่งข้อมูลไป "cart/get" → เซิร์ฟเวอร์ตอบ 200 สำเร็จ ใน 182 ms`
44. ในฐานะนักศึกษา ฉันอยากเห็น badge method และ status ที่มีทั้งสีและตัวอักษรกำกับ เพื่อให้คนตาบอดสีก็อ่านได้
45. ในฐานะผู้สอน ฉันอยากให้ Detail เปิด Exchange หลัก (action เช่นใส่ตะกร้า แม้เว็บจะใช้ POST ทุก API) ของคลิกล่าสุดให้อัตโนมัติ (ปิดได้ด้วย "ตามคลิกล่าสุด") เพื่อจะได้ไม่ต้องสลับหน้าต่าง
46. ในฐานะผู้สอน ฉันอยากให้ Timeline ไม่เลื่อนเองตอนฉันกำลังดูของเก่า แต่แสดงปุ่มลอย "มี N รายการใหม่ ↑"
47. ในฐานะนักศึกษา ฉันอยากเห็นแท็บ ภาพรวม / ขาออก / ขาเข้า / ดิบ / คลิก / โค้ด เพื่อดู Exchange จากหลายมุม
48. ในฐานะนักศึกษา ฉันอยากเห็นแท็บ "ดิบ" ที่แสดง HTTP เป็นข้อความธรรมดา เพื่อให้เข้าใจว่า HTTP เป็นแค่ข้อความ
49. ในฐานะนักศึกษา ฉันอยากเห็นเวลาจากคลิกถึงตอนที่ request ออกไปในแท็บ "คลิก"
50. ในฐานะนักศึกษา ฉันอยากเห็น JSON เป็น tree ที่ย่อ/ขยายได้ มีสีตามชนิด และ array ยาวที่แสดง "[24 รายการ]" เพื่ออ่านโครงสร้างของ response ได้ง่าย
51. ในฐานะผู้สอน ฉันอยากปรับขนาดตัวอักษรได้ 3 ระดับ (จำค่าไว้) และสลับธีมสว่าง/มืดได้ เพื่อให้เหมาะกับโปรเจกเตอร์แต่ละห้อง
52. ในฐานะผู้สอน ฉันอยากใช้คีย์ลัด ↑/↓ (เลือก), Space (หยุด/เริ่มต่อ) และ C (ล้าง) เพื่อควบคุมได้โดยไม่ต้องใช้เมาส์
53. ในฐานะนักศึกษาที่ใช้จอแคบ ฉันอยากให้ Timeline และ Detail ซ้อนกันเมื่อจอแคบกว่า 900 px
54. ในฐานะผู้สอน ฉันอยากเห็นแถบเตือนเรื่องจริยธรรมตอนเปิดครั้งแรก (ปิดได้)
55. ในฐานะผู้สอน ฉันอยากให้ UI เชื่อม WebSocket ใหม่เองแบบ backoff แล้วได้ snapshot ใหม่ เมื่อการเชื่อมต่อหลุด

**การควบคุม**

56. ในฐานะผู้สอน ฉันอยากกด Pause เพื่อหยุดรับ request และคลิกใหม่ชั่วคราวระหว่างอธิบาย โดย Exchange ที่ค้างรอคำตอบอยู่ยังอัปเดตได้
57. ในฐานะผู้สอน ฉันอยากให้หลัง Resume ไม่มีการจับคู่ request ใหม่เข้ากับคลิกที่เกิดก่อน Pause
58. ในฐานะผู้สอน ฉันอยากกด Clear เพื่อล้างทุกอย่าง รวมถึง Hidden count
59. ในฐานะผู้สอน ฉันอยากให้เก็บในหน่วยความจำสูงสุด 500 Exchange ที่มองเห็น (เก่าสุดออกก่อน) และไม่เขียนอะไรลงดิสก์เอง

**P1: Export, โค้ด, Flow strip และ Recording playback**

60. ในฐานะผู้สอน ฉันอยาก export ทั้ง session หรือ Interaction เดียวเป็น Recording เพื่อใช้ทำโจทย์แลบ
61. ในฐานะนักศึกษา ฉันอยากกด Copy as curl / Python `requests` / JavaScript `fetch` (ไม่รวม header ที่ถูกซ่อน) เพื่อเอาไปเทียบกับโค้ด FastAPI ของตัวเอง
62. ในฐานะนักศึกษา ฉันอยากเห็นแอนิเมชัน ผู้ใช้ → เบราว์เซอร์ → เซิร์ฟเวอร์ ที่เล่นซ้ำและปรับความเร็วได้ และเคารพ `prefers-reduced-motion`
63. ในฐานะผู้สอน ฉันอยากเปิด Recording ของรอบซ้อมด้วย `--replay-file` (Recording playback) โดยไม่ต้องต่อ Chrome เผื่อเน็ตในห้องมีปัญหา
64. ในฐานะผู้สอน ฉันอยากเห็นที่ top bar ว่ากำลังอยู่ในโหมด Recording playback พร้อมชื่อไฟล์

**ตัวโปรแกรมในฐานะสื่อการสอน**

65. ในฐานะนักศึกษา ฉันอยากเปิด `/docs` ของ Inspector เพื่อดูตัวอย่าง REST API ที่เขียนด้วย FastAPI
66. ในฐานะนักศึกษา ฉันอยากอ่านโค้ดที่แต่ละ class มีหน้าที่เดียว มี type hints และมี docstring ภาษาไทยบอกว่าสอนแนวคิด OOP อะไร
67. ในฐานะนักศึกษา ฉันอยากอ่าน frontend ที่เป็น vanilla JS ไม่มี build step และแบ่ง class ล้อกับฝั่ง Python
68. ในฐานะนักศึกษา ฉันอยากได้ README ภาษาไทยที่อธิบายวิธีติดตั้ง วิธีใช้ และคำเตือนเรื่องพอร์ต 9222

## Implementation Decisions

**สถาปัตยกรรม** (ตาม `docs/SPEC.md` ข้อ 3)

- เป็น Python process เดียว รัน Playwright (`connect_over_cdp`) และ FastAPI/uvicorn บน asyncio loop เดียวกัน bind เฉพาะ `127.0.0.1` ไม่ใช้ proxy และไม่ใช้ headless browser
- ต้องใช้ Python 3.11 ขึ้นไป library ที่ใช้คือ fastapi, uvicorn[standard], playwright และ pydantic v2 ไม่ต้องรัน `playwright install`
- ทุก model เป็น Pydantic v2 ตามข้อ 5 ของ spec และเพิ่มฟิลด์ดังนี้
  - `Interaction` มี `navigated_to: str | None`
  - Exchange ต้องบอกได้ว่า text body ตัวไหนยังไม่ได้ผ่านการตรวจหาข้อมูลลับ

**Capture event: seam ระหว่าง Chrome กับ pipeline**

- ฝั่ง capture (ChromeConnector, TrafficCapture, ClickTracker) แปลง event ของ Playwright เป็น Capture event ที่เป็นข้อมูลล้วน ไม่มี object ของ Playwright ติดไป มี 6 ชนิด: request เริ่ม, response มาถึง (มี body หรือเหตุผลที่อ่านไม่ได้), request ล้มเหลว, คลิก, Navigation ของ main frame, และแท็บเปิด/ปิด
- Capture event ทุกตัวมี timestamp มาด้วย pipeline ไม่อ่านนาฬิกาเอง
- `InspectorPipeline` รับ Capture event แล้วส่งต่อตามลำดับ filter → redact → correlate → summarize → store → broadcast และรับคำสั่ง pause/resume/clear/เปลี่ยน preset
- `create_app(...)` รับ pipeline, store และ broadcaster ผ่าน argument ไม่มี global state

**Store**

- Exchange ที่มองเห็น กับ Hidden exchange อยู่ใน buffer แยกกัน (`deque`) แต่ละ buffer มีเพดานเท่ากับ `--max-exchanges` (ค่าเริ่มต้น 500)
- Hidden count เป็นตัวนับสะสม รีเซ็ตเฉพาะตอน Clear
- เมื่อเปลี่ยน Preset จะคำนวณสถานะซ่อน/แสดงของ Exchange ทุกตัวใหม่ และย้ายระหว่าง buffer จากนั้นส่ง `snapshot` ใหม่ไปให้ client

**การกรอง**

- Blocklist พื้นฐาน (ตาม spec ข้อ 4.3 บวก origin ของ Inspector เอง) ฝังในโค้ด ถอดออกไม่ได้
- Preset อยู่ในไฟล์ `presets/<ชื่อ>.json` แต่ละไฟล์มี Focus rule, Blocklist เพิ่มเติม และ key ที่ต้องซ่อนเพิ่มเติม **ไม่มีไฟล์ `filters.json`**
- Preset `custom` อยู่ในหน่วยความจำเท่านั้น สร้างโดยคัดลอกจาก Preset ที่เลือกอยู่ แก้ผ่าน `PUT /api/filters` และไม่เขียนลงดิสก์
- ลำดับการตรวจ: Blocklist ก่อน (Hidden reason `tracking: <host>`) แล้วค่อย Focus rule (Hidden reason `นอกโฟกัส: preset <ชื่อ>`)
- class ที่ใช้: `FilterRule` (abstract) มี `matches(exchange) -> str | None` subclass คือ `HostBlockRule`, `PathPrefixRule`, `ResourceTypeRule` และมี `FilterChain` รวมไว้

**Redaction**

- ทำก่อนเก็บ ปิดไม่ได้ ครอบคลุม
  - headers ตามข้อ 4.4 (cookie ให้เหลือชื่อไว้)
  - query
  - URL ทุกตัว (`url`, `page_url`, `href`) โดยสร้าง URL ใหม่จาก query ที่ซ่อนค่าแล้ว
  - JSON body และ form body ทั้ง request และ response ด้วย regex key `pass|token|secret|session|otp|card|phone|mobile|email|address|citizen|id_card` แบบไม่สนตัวพิมพ์ และทำแบบ recursive
- text body ที่ไม่ใช่ JSON หรือ form ส่งผ่านไปตามเดิมพร้อม flag "ไม่ได้ตรวจหาข้อมูลลับ"
- ยอมให้ซ่อนเกินได้ เช่น `passenger` และ `ip_address`
- key ที่เพิ่มผ่าน Preset ใช้กับ Exchange ที่เข้ามาใหม่เท่านั้น

**Correlator**

- Click interaction รับ Exchange ที่เริ่มภายใน Correlation window (ค่าเริ่มต้น 1500 ms) ในแท็บเดียวกัน ถ้ามีคลิกใหม่ ให้ปิดอันเดิมและเปิดอันใหม่
- ถ้าเกิด Navigation ภายใน Correlation window ของคลิก จะไม่เปิด Page-load interaction แต่ตั้ง `navigated_to` และขยาย window ไปอีก 5 วินาทีนับจาก Navigation
- Navigation ที่ไม่มีคลิกนำหน้าจะเปิด Page-load interaction ที่รับ Exchange ภายใน 5 วินาที
- แต่ละแท็บมี Background interaction ที่เปิดอยู่ได้หนึ่งอัน ปิดเมื่อมีคลิกหรือ Navigation ในแท็บนั้น การ์ดไม่ย้ายตำแหน่งเมื่อได้ Exchange ใหม่
- Exchange ที่ถูกซ่อนยังถูกจัดเข้า Interaction ตามปกติ การซ่อนการ์ดที่ไม่มี Exchange ที่มองเห็นเป็นหน้าที่ของ UI

**Pause**

- request ใหม่และคลิกที่เกิดระหว่าง pause ถูกทิ้ง ไม่นับใน Hidden count
- response หรือ failure ของ Exchange ที่ `pending` อยู่ยังอัปเดตได้
- เมื่อ Resume จะเริ่มสถานะของ Correlator ใหม่

**Watched tab**

- ไม่ attach และไม่ฉีดสคริปต์ในแท็บที่ origin เป็น Inspector (`127.0.0.1` / `localhost` ที่พอร์ตของ Inspector) หรือ `chrome://`, `devtools://`, `chrome-extension://`
- แท็บที่ navigate เข้าหรือออกจากหน้าเหล่านี้ จะเปลี่ยนสถานะ watched ตามไปด้วย

**API** (ตามข้อ 5 ของ spec)

- WebSocket `/ws` ส่งได้ทางเดียวจาก server: `snapshot`, `interaction.new`, `exchange.new`, `exchange.update`, `status`, `cleared` และเพิ่ม `interaction.update` (สำหรับ `navigated_to` และการ์ดเบื้องหลังที่ได้ Exchange เพิ่ม)
- `status` มี `mode: "live" | "playback"` และชื่อไฟล์ Recording
- REST: `/api/status`, `/api/interactions`, `/api/exchanges/{id}`, `/api/pause|resume|clear`, `GET|PUT /api/filters`, `/api/export?interaction_id=`

**Recording playback (P1)**

- `--replay-file <path>` โหลด Recording เข้า store แล้วไม่ต่อ Chrome เลย
- flag ใช้ชื่อตาม spec แต่ในโค้ดเรียกโหมดนี้ว่า Recording playback (ไม่ใช่ "replay" ซึ่งหมายถึงการส่ง request ซ้ำที่ห้ามทำ)

**Frontend**

- vanilla JS ไม่มี build step แบ่งเป็น class `InspectorSocket`, `TimelineView`, `DetailView`, `JsonViewer`, `FlowStrip`
- ไม่โหลดไฟล์จาก CDN ยกเว้นฟอนต์ที่มี fallback

**ลำดับงาน** ตามข้อ 10.3 ของ spec: core + tests → broadcaster/app → capture/main → UI (P0 แล้ว P1) → scripts/README

## Testing Decisions

- **test ที่ดีต้องตรวจพฤติกรรมที่มองเห็นจากภายนอก** ไม่ผูกกับโครงสร้างภายใน ถ้าแยกหรือรวม class ข้างในใหม่ test ต้องยังผ่าน
- **seam หลักมีจุดเดียว:** ป้อน Capture event ปลอม (กำหนด timestamp เอง) เข้า `InspectorPipeline` แล้วตรวจผลผ่าน FastAPI `TestClient` ทั้ง REST และ WebSocket ใช้ seam นี้ครอบคลุม
  - การจับคู่คลิก (window, คลิกซ้อน, แยกแท็บ, Navigation ที่มาจากคลิก, Page-load, Background)
  - การกรอง (Blocklist, Focus rule, Hidden reason, buffer แยก, Hidden count, เปลี่ยน preset)
  - Redaction ตั้งแต่ต้นจนจบ (ไม่มีค่าจริงใน `/api/exchanges/{id}`, export, ข้อความ WS)
  - pause/resume/clear, เพดาน 500
  - ลำดับข้อความ WS (`snapshot` ตอนเชื่อม, `exchange.new` แล้วตามด้วย `exchange.update`)
  - Recording playback
- **test แบบตาราง แยกตามหน่วย** (เฉพาะ pure function ที่มีกรณีเยอะ)
  - Summarizer: ครบทุก method × status ตามข้อ 4.5
  - กฎ key ของ Redactor: ครอบคลุม header, JSON ซ้อนหลายชั้น, form, cookie ที่เหลือแต่ชื่อ, และ body ที่ไม่ใช่ JSON ไม่ crash
- **integration test ที่ใช้ Chrome จริง** (`@pytest.mark.chrome` ไม่บังคับ): เปิดหน้า HTML fixture ที่มีปุ่มเรียก fetch ไปยัง FastAPI จำลอง แล้วตรวจผ่าน seam เดียวกันว่าได้ Interaction ที่ถูกต้อง
- ยังไม่มี test เดิมใน repo (repo ว่าง) test ชุดนี้จะเป็น prior art ชุดแรก
- รัน pytest หลังจบแต่ละขั้น และทำ checklist ทดสอบด้วยมือตามข้อ 9.2 ของ spec ตอนท้าย

## Out of Scope

- แก้, บล็อก หรือส่ง request ซ้ำ ไม่ว่ารูปแบบใด
- P2 ทั้งหมด: slow-motion, WebSocket frames, Server-Sent Events
- แอปมือถือ, แอปเดสก์ท็อป และเบราว์เซอร์อื่นนอกจาก Chrome
- การเขียนข้อมูลลงดิสก์โดยอัตโนมัติ (รวมถึงการบันทึก Preset `custom`)
- การตรวจหาข้อมูลลับใน text body ที่ไม่ใช่ JSON หรือ form และใน binary body
- request จาก Service Worker (ข้อจำกัดที่ทราบแล้ว)

## Further Notes

- Chrome 136 ขึ้นไปต้องใช้ `--user-data-dir` แยก ผู้สอนจึงต้องล็อกอินเว็บใหม่ในโปรไฟล์สาธิต
- การจับคู่ด้วยเวลาอาจผิดพลาดได้ ถ้ามี polling เกิดขึ้นพอดีในช่วงเดียวกับคลิก ข้อนี้รับได้และควรบอกไว้ใน README
- ข้อมูลจริงของ advice.co.th ที่ใช้ทำ acceptance test อยู่ในข้อ 9.1 ของ spec (ตรวจเมื่อ 5 พ.ย. 2569 เว็บอาจเปลี่ยนไปแล้ว)
- งานทำบน branch `feat/inspector-v1` และ commit หลังจบแต่ละขั้นที่ test ผ่าน
