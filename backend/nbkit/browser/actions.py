"""브라우저 조작 프리미티브 — 재시도+백오프가 붙은 안전한 click/fill/evaluate.

옴니솔(더존 OmniEsol) 화면은 로딩이 간헐적으로 지연되므로(experience 문서 §"화면/그리드
로딩 간헐 지연"), 단발 조작은 자주 빗나간다. 이 모듈은 모든 상위 계층(omnisol/*, patterns/*)
이 공유하는 **재시도 가능한 원자 조작**을 제공한다.

Playwright ``Page`` 는 느슨하게(``Any``) 받는다 — 라이브 브라우저 없이도 import 가능해야
하기 때문이다(순수 로직 단위테스트/스캐폴드 단계).

★ 실클릭 원칙: 옴니솔 Kendo/RealGrid 는 JS 합성 이벤트(element.click())로 변경 핸들러가
  안 깨어나는 경우가 많다. 좌표 실클릭이 필요한 곳은 :func:`mouse_click` 을 쓴다
  (사용자유형 전환·캔버스 돋보기 등). 자세한 배경은 ``OMNISOL_NOTES.md`` 참고.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("nbkit.browser.actions")

DEFAULT_TIMEOUT_MS = 10_000
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_MS = 500


async def _backoff(attempt: int, base_ms: int = DEFAULT_BACKOFF_MS) -> None:
    """지수 백오프(attempt 1→base, 2→2×base, …). 상한 4초."""
    delay_ms = min(base_ms * (2 ** (attempt - 1)), 4_000)
    await asyncio.sleep(delay_ms / 1000)


async def safe_click(
    page: Any,
    selector: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    retries: int = DEFAULT_RETRIES,
    backoff_ms: int = DEFAULT_BACKOFF_MS,
) -> bool:
    """``selector`` 를 Playwright 클릭. 실패 시 백오프 후 재시도. 성공 여부 반환.

    최종 실패해도 예외를 던지지 않고 ``False`` 를 돌려준다 — 호출자가 폴백/명확한
    도메인 오류(MenuError 등)로 승격하도록.
    """
    for attempt in range(1, retries + 1):
        try:
            await page.click(selector, timeout=timeout_ms)
            return True
        except Exception as exc:  # noqa: BLE001 — 재시도 대상
            logger.debug("safe_click 실패(%s/%s) selector=%s: %s", attempt, retries, selector, exc)
            if attempt < retries:
                await _backoff(attempt, backoff_ms)
    return False


async def safe_fill(
    page: Any,
    selector: str,
    value: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    retries: int = DEFAULT_RETRIES,
    backoff_ms: int = DEFAULT_BACKOFF_MS,
) -> bool:
    """``selector`` 입력칸에 ``value`` 를 채운다. 재시도+백오프. 성공 여부 반환."""
    for attempt in range(1, retries + 1):
        try:
            await page.fill(selector, value, timeout=timeout_ms)
            return True
        except Exception as exc:  # noqa: BLE001 — 재시도 대상
            logger.debug("safe_fill 실패(%s/%s) selector=%s: %s", attempt, retries, selector, exc)
            if attempt < retries:
                await _backoff(attempt, backoff_ms)
    return False


async def safe_evaluate(
    page: Any,
    script: str,
    arg: Any = None,
    *,
    retries: int = 2,
    backoff_ms: int = DEFAULT_BACKOFF_MS,
    default: Any = None,
) -> Any:
    """``page.evaluate(script, arg)`` 를 재시도와 함께 실행. 실패 시 ``default`` 반환.

    옴니솔 화면 전환 직후 evaluate 가 순간적으로 실패(컨텍스트 파괴)할 수 있어 소수 재시도.
    """
    for attempt in range(1, retries + 1):
        try:
            if arg is None:
                return await page.evaluate(script)
            return await page.evaluate(script, arg)
        except Exception as exc:  # noqa: BLE001 — 재시도 대상
            logger.debug("safe_evaluate 실패(%s/%s): %s", attempt, retries, exc)
            if attempt < retries:
                await _backoff(attempt, backoff_ms)
    return default


async def js_click(page: Any, selector: str) -> bool:
    """``document.querySelector(selector)?.click()`` — JS 합성 클릭.

    조회/추가 같은 일반 툴바 버튼은 JS click 으로 충분히 반응한다(graph.py 검증).
    Kendo/RealGrid 변경 핸들러가 필요한 곳(사용자유형·캔버스)에는 쓰지 말 것 →
    :func:`mouse_click` 사용.
    """
    ok = await safe_evaluate(
        page,
        "(sel) => { const el = document.querySelector(sel); if (!el) return false; el.click(); return true; }",
        selector,
        default=False,
    )
    return bool(ok)


async def mouse_click(page: Any, x: int, y: int) -> None:
    """좌표 실클릭(trusted). 캔버스(RealGrid) 돋보기·사용자유형 드롭다운 등에 필수.

    ``page.mouse.click`` 은 실제 포인터 이벤트를 발생시켜 옴니솔 변경 핸들러를 깨운다
    (JS ``element.click()`` 은 못 깨우는 경우가 있음 — OMNISOL_NOTES 참고).
    """
    await page.mouse.click(x, y)
