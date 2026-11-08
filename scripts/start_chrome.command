#!/bin/sh
# เปิด Chrome โหมด debug สำหรับ Web Traffic Inspector (macOS: ดับเบิลคลิกใน Finder)
# ใช้โปรไฟล์แยก จึงไม่กระทบ Chrome ปกติ และเปิดพอร์ต 9222 ให้เฉพาะเครื่องนี้ (127.0.0.1)

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  CHROME="$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi
if [ ! -x "$CHROME" ]; then
  echo "ไม่พบ Google Chrome ใน /Applications หรือ ~/Applications"
  exit 1
fi

# nohup: ปิดหน้าต่าง Terminal นี้แล้ว Chrome ยังเปิดอยู่
nohup "$CHROME" \
  --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$HOME/.traffic-inspector-profile" \
  --no-first-run https://www.advice.co.th >/dev/null 2>&1 &
echo "เปิด Chrome โหมด debug แล้ว ต่อไปรัน: python3 -m inspector"
