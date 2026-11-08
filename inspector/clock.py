"""นาฬิกาของโปรแกรม: เวลาเป็น epoch milliseconds (float) เหมือนทุกเวลาใน models (ดู ADR 0001)"""

import time
from collections.abc import Callable

Clock = Callable[[], float]


def now_ms() -> float:
    return time.time() * 1000
