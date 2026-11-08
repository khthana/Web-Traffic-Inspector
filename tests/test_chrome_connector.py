"""ChromeConnector โดยไม่ใช้ Chrome: ถ้าเริ่ม Playwright ไม่สำเร็จ ต้องลองใหม่ ไม่หยุดเงียบๆ"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

from playwright.async_api import BrowserContext, Playwright

from inspector.chrome import ChromeConnector


async def no_context(_: BrowserContext) -> None:
    return None


def test_keeps_retrying_when_playwright_fails_to_start() -> None:
    attempts: list[int] = []

    async def refuse(*_: Any, **__: Any) -> None:
        raise ConnectionError("Chrome ยังไม่เปิด")

    @asynccontextmanager
    async def flaky_playwright() -> AsyncIterator[Playwright]:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RuntimeError("driver ของ Playwright เริ่มไม่สำเร็จ")
        yield cast(Playwright, SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=refuse)))

    def factory() -> AbstractAsyncContextManager[Playwright]:
        return flaky_playwright()

    async def scenario() -> None:
        connector = ChromeConnector(
            "http://127.0.0.1:9", on_context=no_context, on_status=lambda _: None, retry_s=0.01,
            playwright_factory=factory,
        )
        task = asyncio.create_task(connector.run())
        for _ in range(200):
            if len(attempts) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert len(attempts) >= 2
