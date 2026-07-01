"""디버그/관찰 프리미티브 — 스크린샷(dataURL)·콘솔 캡처.

라이브 미리보기 프레임은 헤드리스 화면을 jpeg 로 캡처해 ``data:`` URL 로 만든다
(graph.py ``_shot`` 패턴). 실패는 조용히 삼킨다 — 미리보기 실패가 본 작업을 막으면 안 된다.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("nbkit.browser.debug")

DEFAULT_SCREENSHOT_QUALITY = 45


async def screenshot_data_url(
    page: Any, *, quality: int = DEFAULT_SCREENSHOT_QUALITY
) -> Optional[str]:
    """현재 화면을 jpeg 로 캡처해 ``data:image/jpeg;base64,...`` 문자열 반환(실패 시 None).

    라이브 세션 미리보기용. 저용량(quality~45) 단일 프레임. CDP 연속 스크린캐스트는
    엔진(P2) 소관이며, 이 함수는 단발 캡처 프리미티브다.
    """
    try:
        buf = await page.screenshot(type="jpeg", quality=quality)
    except Exception:  # noqa: BLE001 — 캡처 실패는 무시(본 작업 우선)
        logger.debug("screenshot 실패 — 프레임 생략")
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def attach_console_logger(page: Any, sink: Optional[Callable[[str, str], None]] = None) -> None:
    """페이지 콘솔 메시지를 ``sink(level, text)`` 로 전달(없으면 logger.debug).

    디버깅 시 in-page 오류를 파이썬 로그로 끌어오는 용도. 라이브 Page 에만 의미가 있다.
    """
    emit = sink or (lambda level, text: logger.debug("console[%s]: %s", level, text))

    def _on_console(msg: Any) -> None:
        try:
            emit(getattr(msg, "type", "log"), getattr(msg, "text", str(msg)))
        except Exception:  # noqa: BLE001
            pass

    try:
        page.on("console", _on_console)
    except Exception:  # noqa: BLE001 — 느슨한 Page(스텁)면 무시
        logger.debug("attach_console_logger: page.on 미지원(스텁 Page)")
