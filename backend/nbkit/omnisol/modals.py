"""차단 모달(Kendo .k-window) 일괄 해제 — 확인/예 계열 클릭 폴링.

card_collect 에서 승격(2026-07-05) — 모든 옴니솔 에이전트 공용. 로직은 card_collect
실전 검증본 그대로(동작 불변)이며, in-page JS 는 :mod:`nbkit.omnisol.js_lib` 단일 소스
(MODALS_SNAPSHOT_JS/MODAL_BTN_BOX_JS)를 쓴다.
"""

from __future__ import annotations

from typing import Any

from nbkit.omnisol import js_lib

__all__ = ["dismiss_blocking_modals"]


async def dismiss_blocking_modals(page: Any, *, rounds: int = 6) -> list[dict]:
    """화면을 막는 잔여 확인 모달('예산현황' 등)을 '확인'/'예'로 닫는다.

    실전 실측(2026-07-02 2차 런): 카드팝업 '적용' 후 팝업 닫힘보다 **늦게** '예산현황'
    모달이 떠서, 다음 단계(F3·증빙 코드피커)가 막혀 TypeError 로 실패했다. 확인 계열만
    클릭(취소/아니오 금지). 닫은 모달 스냅샷 목록 반환.

    속도: 첫 체크는 대기 없이 즉시, 이후 400ms 폴링. **2초 연속 조용**하면 종료(지연 모달
    관찰 창 유지, 기존 최소 3s → 2s). 상한 = rounds×1.5s(기존 시그니처 호환).
    """
    seen: list[dict] = []
    cap_ms = rounds * 1_500
    interval = 400
    quiet_needed = 2_000  # 이 시간 동안 모달이 안 뜨면 종료(지연 출현 관찰 창)
    waited = 0
    quiet = 0
    while True:
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)  # 첫 체크 즉시(고정 1.5s 선대기 제거)
        if modals:
            quiet = 0
            seen.extend(modals)
            for label in ("확인", "예"):
                btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    break
        elif quiet >= quiet_needed:
            break
        if waited >= cap_ms:
            break
        await page.wait_for_timeout(interval)
        waited += interval
        if not modals:
            quiet += interval
    return seen
