"""จุดเริ่มโปรแกรม: `python -m inspector`

อ่าน CLI args → ประกอบทุก object → รัน uvicorn และงานเบื้องหลังบน event loop เดียวกัน
bind เฉพาะ 127.0.0.1 เสมอ (ไม่เปิดให้เครื่องอื่นเข้าถึง)
"""

import argparse
import asyncio
import webbrowser

import uvicorn

from inspector.app import create_app
from inspector.broadcaster import Broadcaster
from inspector.capture import TrafficCapture
from inspector.chrome import ChromeConnector, chrome_launch_command
from inspector.correlator import Correlator
from inspector.demo import feed_demo_events
from inspector.pipeline import InspectorPipeline
from inspector.redactor import Redactor
from inspector.store import EventStore

HOST = "127.0.0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m inspector", description="Web Traffic Inspector")
    parser.add_argument("--port", type=int, default=8000, help="พอร์ตของหน้า Inspector (ค่าเริ่มต้น 8000)")
    parser.add_argument("--max-exchanges", type=int, default=500, help="จำนวน Exchange สูงสุดที่เก็บในหน่วยความจำ")
    parser.add_argument(
        "--window-ms", type=float, default=1500, help="Correlation window: ช่วงเวลาหลังคลิกที่นับ Exchange เป็นผลของคลิก (ms)"
    )
    parser.add_argument("--no-open", action="store_true", help="ไม่ต้องเปิดหน้า Inspector ในเบราว์เซอร์ให้อัตโนมัติ")
    parser.add_argument(
        "--cdp-url", default="http://127.0.0.1:9222", help="ที่อยู่ CDP ของ Chrome (ค่าเริ่มต้น http://127.0.0.1:9222)"
    )
    parser.add_argument("--demo", action="store_true", help="ป้อนข้อมูลตัวอย่างแทน Chrome (ใช้ลอง UI)")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    store = EventStore(max_exchanges=args.max_exchanges)
    broadcaster = Broadcaster()
    pipeline = InspectorPipeline(
        store=store,
        broadcaster=broadcaster,
        redactor=Redactor(),
        correlator=Correlator(window_ms=args.window_ms),
        chrome_launch_command="" if args.demo else chrome_launch_command(args.cdp_url),
    )
    app = create_app(pipeline=pipeline, store=store, broadcaster=broadcaster)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=args.port, log_level="warning"))

    background: list[asyncio.Task[None]] = []
    if args.demo:
        background.append(asyncio.create_task(feed_demo_events(pipeline)))
    else:
        # หน้า Inspector เองไม่ใช่ Watched tab (กันไม่ให้ดัก traffic ของตัวเอง)
        own_origins = tuple(f"http://{host}:{args.port}" for host in ("127.0.0.1", "localhost", "[::1]"))
        capture = TrafficCapture(sink=pipeline.handle, inspector_origins=own_origins)
        connector = ChromeConnector(args.cdp_url, on_context=capture.attach, on_status=pipeline.set_chrome_connected)
        background.append(asyncio.create_task(connector.run()))

    url = f"http://{HOST}:{args.port}"
    print(f"Web Traffic Inspector พร้อมแล้วที่ {url}  (กด Ctrl+C เพื่อปิด)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        await server.serve()
    finally:
        for task in background:
            task.cancel()


def main() -> None:
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
