"""차단 모달(Kendo .k-window) 일괄 해제 — 확인/예 계열 클릭 폴링.

card_collect 에서 승격(2026-07-05) — 모든 옴니솔 에이전트 공용. 로직은 card_collect
실전 검증본 그대로(동작 불변)이며, in-page JS 는 :mod:`nbkit.omnisol.js_lib` 단일 소스
(MODALS_SNAPSHOT_JS/MODAL_BTN_BOX_JS)를 쓴다.
"""

from __future__ import annotations

from typing import Any

from nbkit.omnisol import js_lib

__all__ = ["dismiss_blocking_modals", "dismiss_notice_popup"]


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


async def dismiss_notice_popup(page: Any, *, appear_cap_ms: int = 2_000, interval: int = 300) -> bool:
    """로그인 직후 뜨는 '공지' 레이어 팝업을 '하루동안 보지 않기' 체크 후 '닫기'로 닫는다.

    전 에이전트 공통(2026-07-21 프로브 실측): 이 팝업은 로그인 직후 ~1.5s 뒤 렌더되며 Kendo
    백드롭(.k-overlay)으로 **화면 전체를 차단**한다 → 로그인 성공 직후·다른 어떤 조작(아바타
    클릭·메뉴 진입)보다 **먼저** 닫아야 한다. 영속은 브라우저 localStorage 단독이라 새 브라우저
    로 시작하는 헤드리스 세션에선 **매번 재현**된다.

    고유 앵커 #close-today-chk 로만 판정(``dismiss_blocking_modals`` 는 '확인/예' 확정 전용이라
    '닫기' 버튼을 못 눌러 이 팝업을 못 닫는다). 팝업이 없으면(오늘 이미 닫힘/공지 없음) no-op.
    자체 방어(evaluate 실패 등은 삼켜 로그인 자체를 막지 않는다). 반환 True=닫음 / False=없음.
    """
    boxes = None
    waited = 0
    # appear_cap_ms=0 이면 대기 없이 1회만 확인(just-in-time 재확인용 — 피커 클릭 직전 등).
    while True:
        try:
            boxes = await page.evaluate(js_lib.NOTICE_POPUP_BOXES_JS)
        except Exception:  # noqa: BLE001 — best-effort, 로그인 진행 우선.
            return False
        if boxes or waited >= appear_cap_ms:
            break
        await page.wait_for_timeout(interval)
        waited += interval
    if not boxes:
        return False
    try:
        if not boxes.get("checked"):  # '하루동안 보지 않기' 체크(이미 체크면 스킵)
            await page.mouse.click(boxes["checkbox"]["x"], boxes["checkbox"]["y"])
            await page.wait_for_timeout(200)
        # 체크 후 레이아웃 안정 뒤 '닫기' 좌표 재평가(없으면 기존값).
        again = await page.evaluate(js_lib.NOTICE_POPUP_BOXES_JS)
        close = (again or boxes)["close"]
        await page.mouse.click(close["x"], close["y"])
        await page.wait_for_timeout(400)
    except Exception:  # noqa: BLE001 — 닫기 실패해도 로그인 자체는 진행.
        return False
    return True
