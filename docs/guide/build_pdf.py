"""สร้าง docs/คู่มือการใช้งาน.pdf จาก docs/guide/guide.html ด้วย Chrome ในเครื่อง

รันจากโฟลเดอร์โปรเจกต์: python docs/guide/build_pdf.py
ต้องต่อเน็ตเพื่อโหลดฟอนต์ Sarabun จาก Google Fonts (ไม่มีเน็ตจะใช้ฟอนต์ไทยของเครื่องแทน)
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "guide.html"
OUTPUT = HERE.parent / "คู่มือการใช้งาน.pdf"


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome")
        page = await browser.new_page()
        await page.goto(SOURCE.as_uri(), wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        await page.pdf(path=str(OUTPUT), prefer_css_page_size=True, print_background=True)
        await browser.close()
    print(f"สร้างแล้ว: {OUTPUT}")


asyncio.run(main())
