@echo off
chcp 65001 >nul
rem เปิด Chrome โหมด debug สำหรับ Web Traffic Inspector (Windows: ดับเบิลคลิก)
rem ใช้โปรไฟล์แยก จึงไม่กระทบ Chrome ปกติ และเปิดพอร์ต 9222 ให้เฉพาะเครื่องนี้ (127.0.0.1)

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo ไม่พบ Google Chrome ในเครื่อง
  pause
  exit /b 1
)

start "" "%CHROME%" ^
  --remote-debugging-port=9222 ^
  --remote-debugging-address=127.0.0.1 ^
  --user-data-dir="%LOCALAPPDATA%\TrafficInspectorProfile" ^
  --no-first-run https://www.advice.co.th
