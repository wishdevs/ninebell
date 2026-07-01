"""대기 프리미티브 — networkidle(폴백 포함)·selector 대기·조건 폴링.

옴니솔은 ``networkidle`` 을 못 잡는 경우가 잦아(백그라운드 폴링·keepalive), 대기 함수는
타임아웃을 **삼키고 계속 진행**한다(graph.py 의 로그인/메뉴 대기 패턴과 동일). 실제 성공
판정은 URL 이 아니라 **요소/그리드 상태**로 하는 :mod:`nbkit.browser.detection` 에 맡긴다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("nbkit.browser.waits")

DEFAULT_NETWORKIDLE_MS = 20_000


async def wait_networkidle(page: Any, *, timeout_ms: int = DEFAULT_NETWORKIDLE_MS) -> bool:
    """``networkidle`` 을 기다리되, 못 잡아도 예외 없이 ``False`` 로 계속 진행.

    성공(idle 도달) 시 ``True``. 옴니솔에서는 흔히 못 잡으므로 반환값에 의존하지 말고
    후속 조건 폴링으로 성공을 판정할 것.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001 — idle 못 잡아도 계속
        return False


async def wait_for_selector(page: Any, selector: str, *, timeout_ms: int = 10_000) -> bool:
    """``selector`` 가 나타날 때까지 대기. 나타나면 ``True``, 타임아웃이면 ``False``."""
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


async def poll_until(
    page: Any,
    script: str,
    *,
    arg: Any = None,
    tries: int = 10,
    interval_ms: int = 1_000,
    predicate: Optional[Callable[[Any], bool]] = None,
) -> Any:
    """``script`` 를 ``interval_ms`` 간격으로 최대 ``tries`` 회 평가, 조건 충족 시 그 값 반환.

    ``predicate`` 가 주어지면 ``predicate(value)`` 가 참일 때 성공. 없으면 truthy 값이면 성공.
    끝까지 실패하면 마지막 평가값(없으면 ``None``)을 반환한다. 조회 재시도·그리드 로딩
    폴링·메뉴 상태 폴링의 공통 골격이다.
    """
    check = predicate or (lambda v: bool(v))
    last: Any = None
    for i in range(tries):
        try:
            last = await page.evaluate(script, arg) if arg is not None else await page.evaluate(script)
        except Exception as exc:  # noqa: BLE001 — 화면 전환 순간 실패 가능
            logger.debug("poll_until evaluate 실패(%s/%s): %s", i + 1, tries, exc)
            last = None
        if check(last):
            return last
        await asyncio.sleep(interval_ms / 1000)
    return last


async def wait_for_condition(
    page: Any,
    script: str,
    *,
    arg: Any = None,
    tries: int = 10,
    interval_ms: int = 1_000,
    predicate: Optional[Callable[[Any], bool]] = None,
) -> bool:
    """:func:`poll_until` 의 불리언 판정 버전 — 조건 충족 시 ``True``."""
    check = predicate or (lambda v: bool(v))
    value = await poll_until(
        page, script, arg=arg, tries=tries, interval_ms=interval_ms, predicate=predicate
    )
    return bool(check(value))
