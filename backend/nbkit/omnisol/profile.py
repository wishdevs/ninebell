"""옴니솔 기본정보(이름·부서·사용자유형) best-effort 추출.

★ 셀렉터는 더존 UI 변경 시 깨질 수 있는 표면이다(js_lib.PROFILE_JS). 추출 실패해도 예외를
  던지지 않고 **빈 값**으로 반환한다 — 로그인/식별은 userid(권위)로 가능해야 하기 때문.
"""

from __future__ import annotations

import logging
from typing import Any

from nbkit.browser.actions import safe_evaluate
from nbkit.omnisol import js_lib
from nbkit.omnisol.auth import open_user_panel

logger = logging.getLogger("nbkit.omnisol.profile")


async def read_profile(page: Any) -> dict:
    """로그인된 page 에서 ``{display_name, department, user_types}`` 추출(항상 dict).

    우상단 아바타를 눌러 사용자 패널을 연 뒤(부서/사용자유형 노출) best-effort 로 긁는다.
    패널을 못 열거나 셀렉터가 바뀌어도 빈 값으로 진행한다.

    아바타 클릭 경로는 :func:`nbkit.omnisol.auth.open_user_panel` 하나로 통합한다 —
    selectors.AVATAR(``a.user-pic``) 실클릭 + JS 폴백. ⚠ 이미지 src 기반 자체 클릭은
    프로필 사진 업로드 계정에서 매칭이 아예 안 돼(2026-07-27 라이브 장애,
    selectors.AVATAR 주석 참조) 다시 쓰지 말 것.
    """
    try:
        await open_user_panel(page)
    except Exception:  # noqa: BLE001 — 패널 못 열어도 읽기는 시도
        pass
    # 패널 렌더를 폴링(고정 1.5s 대체) — 데이터가 잡히는 즉시 진행, 상한 ~2.4s(내성 유지).
    raw: dict = {}
    for _ in range(12):
        try:
            await page.wait_for_timeout(200)
        except Exception:  # noqa: BLE001
            break
        raw = await safe_evaluate(page, js_lib.PROFILE_JS, default={}) or {}
        if raw.get("display_name") or raw.get("department"):
            break
    if not raw:
        logger.warning("프로필 추출 실패 — 빈 값으로 진행(셀렉터 변경 가능성)")
        raw = {}
    return {
        "display_name": (raw.get("display_name") or "").strip(),
        "department": (raw.get("department") or "").strip(),
        "user_types": raw.get("user_types") or [],
    }
