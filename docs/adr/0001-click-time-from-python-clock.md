# 0001 — ประทับเวลาคลิกและ Navigation ด้วยนาฬิกาฝั่ง Python

**สถานะ:** ใช้อยู่ (ticket #6) — แทนข้อความใน SPEC §4 ที่ให้ส่งเวลา `performance.timeOrigin + performance.now()` จากหน้าเว็บ

## บริบท

Correlator ตัดสินว่า Exchange เป็นของคลิกไหนจากการเทียบเวลา (`started_at <= ts <= until`) เวลาของ Exchange มาจาก `time.time()` ฝั่ง Python
ส่วน `performance.timeOrigin + performance.now()` ในหน้าเว็บเป็นนาฬิกา monotonic ที่เริ่มนับตอนโหลดหน้า ถ้าแท็บเปิดค้างนานหรือเครื่อง sleep
มันจะเคลื่อนห่างจากนาฬิกาของเครื่องได้หลายวินาที ซึ่งมากกว่า Correlation window (1500 ms) และหน้าเว็บยังปลอมค่าเวลาที่ส่งมาได้

## การตัดสินใจ

สคริปต์ในหน้าเว็บไม่ส่งเวลาแล้ว ClickTracker ประทับเวลาด้วยนาฬิกาเดียวกับ Exchange (`now_ms()`) ตอนที่ binding ถูกเรียก
binding ถูกเรียกใน listener ช่วง capture ก่อน handler ของเว็บจะยิง fetch จึงมาถึง Python ก่อน request ของคลิกนั้น

ดักคลิกและ Navigation เฉพาะ main frame ของ Watched tab คลิกใน iframe (เช่น widget ที่ฝังมา) ไม่นับ เพื่อให้ตรงกับนิยาม Navigation
และไม่ต้องจัดการ origin ของ iframe หลายแหล่ง

## ผลที่ตามมา

- เวลาคลิกช้ากว่าเวลาจริงราวไม่กี่มิลลิวินาที (เวลาเดินทางผ่าน CDP) ไม่มีผลกับการสอน
- หน้าที่สคริปต์ไม่ได้รัน (เช่น PDF viewer, หน้า error ของ Chrome) จะไม่มี Navigation — Exchange ของหน้านั้นจะเป็น Background
