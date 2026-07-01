"""옴니솔 기본정보(이름·부서·사용자유형) best-effort 추출.

★ 셀렉터는 더존 UI 변경 시 깨질 수 있는 표면이다(js_lib.PROFILE_JS). 추출 실패해도 예외를
  던지지 않고 **빈 값**으로 반환한다 — 로그인/식별은 userid(권위)로 가능해야 하기 때문.
"""

from __future__ import annotations

import logging
from typing import Any

from nbkit.browser.actions import safe_evaluate
from nbkit.omnisol import js_lib

logger = logging.getLogger("nbkit.omnisol.profile")


async def read_profile(page: Any) -> dict:
    """로그인된 page 에서 ``{display_name, department, user_types}`` 추출(항상 dict).

    우상단 아바타를 눌러 사용자 패널을 연 뒤(부서/사용자유형 노출) best-effort 로 긁는다.
    패널을 못 열거나 셀렉터가 바뀌어도 빈 값으로 진행한다.

    JS `.click()` 은 Kendo 열기 핸들러를 못 깨워 패널이 안 열리는 경우가 있어(= 부서 빈값의
    원인), ninebell-bak `erp/graph.py:_open_user_panel` 처럼 실제 page.click 을 먼저 시도하고
    실패 시에만 JS 로 폴백한다.
    """
    try:
        await page.click("img[src*=profile_circle]", timeout=4_000)
    except Exception:  # noqa: BLE001 — 실제 클릭 실패 시 JS 폴백
        try:
            await page.evaluate(js_lib.AVATAR_CLICK_JS)
        except Exception:  # noqa: BLE001 — 패널 못 열어도 읽기는 시도
            pass
    try:
        await page.wait_for_timeout(1_500)
    except Exception:  # noqa: BLE001
        pass
    raw = await safe_evaluate(page, js_lib.PROFILE_JS, default={})
    if not raw:
        logger.warning("프로필 추출 실패 — 빈 값으로 진행(셀렉터 변경 가능성)")
        raw = {}
    return {
        "display_name": (raw.get("display_name") or "").strip(),
        "department": (raw.get("department") or "").strip(),
        "user_types": raw.get("user_types") or [],
    }
