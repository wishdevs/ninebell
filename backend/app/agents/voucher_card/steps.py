"""미지급금 법인카드(voucher-card) 고유 스텝 프리미티브 — 프로브 이식.

공유 백본(voucher_receivable.steps: set_query 8필드·run_query·read_row_key·checkRow·결제창
열기/렌더/닫기·D7)은 그대로 재사용하고, 여기에는 카드 고유 3대 확장의 브라우저 조작만 둔다:
  Phase B  결의서조회승인(GLDDOC00400) **다중 메뉴 탭** — 결의구분=카드 일괄 조회 →
           ABDOCU_NO→GWDOCU_NO 맵 수집 → 전표조회승인 탭 복귀.
  Phase C  결제창(EAP React) 안 **참조문서 선택** sub-flow(문서번호=GWDOCU_NO 검색→선택→아래버튼).

⚠ 절대 안전: 이 모듈에는 결제창 상신·참조문서 확인을 **무조건** 클릭하는 함수가 없다.
   click_refdoc_confirm 은 존재하되(미래용 프리미티브), 호출은 reference_doc 훅의
   allow_confirm 게이트(기본 False) 뒤에서만 일어난다. F7/F6 없음.
"""

from __future__ import annotations

import calendar
import logging
from typing import Any

from nbkit.browser.actions import js_click, mouse_click
from nbkit.omnisol import js_lib, selectors
from nbkit.omnisol.modals import dismiss_blocking_modals, dismiss_notice_popup

from app.agents.voucher_receivable import js as vr_js
from app.agents.voucher_receivable import steps as vr_steps

from . import js

logger = logging.getLogger(__name__)

# 전표유형(SYSDEF_NM) — 카드는 '일반'(SYSDEF_CD=11). 나머지 조회조건은 공유 set_query 와 동일.
DOCU_TYPES_CARD = ("일반",)

# 결의구분 native select(#ABDOCU_FG_CD) 대상 — '카드'(ABDOCU_FG_CD=52).
GUBUN_SELECT = "#ABDOCU_FG_CD"
GUBUN_CARD_TEXT = "카드"

# 참조문서 조회 결과 조건 폴링(대량 리스트 렌더 vs '없음' 메시지 편차 — 고정대기 금지).
REFDOC_POLL_TRIES = 8
REFDOC_POLL_INTERVAL_MS = 500
# React controlled input 클리어 — Ctrl/Cmd+A 미수신 케이스가 있어 End 후 Backspace 다회.
REFDOC_CLEAR_BACKSPACES = 40


# ══════════════════════════════════════════════════════════════════════════════
# Phase B — 결의서조회승인(GLDDOC00400) 다중 메뉴 탭 + 결의구분=카드 조회 + 맵 수집
# ══════════════════════════════════════════════════════════════════════════════
async def open_collect_tab(page: Any) -> bool:
    """사이드바 결의서조회승인 링크를 실클릭해 **새 메뉴 탭**을 연다(페이지 캐시 — 전표조회승인
    탭 유지). ⚠ 공지 팝업(비동기 지연 로드)이 클릭을 가로채는 레이스가 있어 클릭 직전 공유
    dismiss 를 확인하고, 1차 실패 시 모달 재정리 후 1회 재시도(프로브 확정 패턴).
    """
    await dismiss_notice_popup(page, appear_cap_ms=0)
    await dismiss_blocking_modals(page, rounds=1)
    try:
        await page.click(js.NAV_LINK_SELECTOR, timeout=8_000)
    except Exception:  # noqa: BLE001 — 모달 레이스 진단 후 1회 재시도.
        await dismiss_notice_popup(page, appear_cap_ms=0)
        await dismiss_blocking_modals(page, rounds=1)
        await page.click(js.NAV_LINK_SELECTOR, timeout=8_000)
    await page.wait_for_timeout(2_000)
    return True


async def set_collect_dept_all(page: Any) -> bool:
    """결의부서 = 전체선택(돋보기 → 팝업 checkAll → 적용). 공유 _open_picker/POPUP_CHECK_ALL 재사용
    (라벨만 '결의부서'). best-effort — 실패해도 조회는 진행(폼 기본값)."""
    if not await vr_steps._open_picker(page, "결의부서"):
        return False
    res = await page.evaluate(vr_js.POPUP_CHECK_ALL_JS)
    if not (isinstance(res, dict) and res.get("ok")):
        return False
    return await vr_steps._apply_popup(page)


async def clear_collect_writer(page: Any) -> bool:
    """결의자(#WRT_EMP_NO_C) 비움 — 로그인 계정 소속으로 결과가 좁혀지지 않게. 반환 bool."""
    ok = await page.evaluate(js.CLEAR_WRT_EMP_JS)
    await page.wait_for_timeout(300)
    return bool(ok)


async def set_collect_period(page: Any, accounting_ym: str | None = None) -> bool:
    """회계일 세팅 — accounting_ym(YYYYMM) override 시 그 월의 1일~말일로, None 이면 미조작
    (폼 기본값=당월, 프로브 확정 경로). best-effort(실패해도 폼 기본값으로 진행). 반환 bool.

    ⚠ 프로브 확정 조회는 이 필드를 건드리지 않았다(폼 기본 당월으로 카드 결과 정상 수집).
      override 경로(특정월)는 미검증이므로 실패해도 조용히 폼 기본값에 맡긴다.
    """
    if not accounting_ym:
        return True  # 폼 기본값(당월) 유지 — 프로브 확정 경로.
    y, m = int(accounting_ym[:4]), int(accounting_ym[4:6])
    last = calendar.monthrange(y, m)[1]
    start = f"{y:04d}{m:02d}01"
    end = f"{y:04d}{m:02d}{last:02d}"
    ok = await page.evaluate(js.SET_PERIOD_RANGE_JS, {"start": start, "end": end})
    await page.wait_for_timeout(300)
    return bool(ok)


async def set_collect_gubun_card(page: Any) -> bool:
    """결의구분 = 카드 — native dews dropdownlist(#ABDOCU_FG_CD, KENDO_SET_DROPDOWN_BY_TEXT_JS 재사용)."""
    r = await page.evaluate(
        js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": GUBUN_SELECT, "text": GUBUN_CARD_TEXT}
    )
    await page.wait_for_timeout(500)
    return bool(isinstance(r, dict) and r.get("ok"))


async def run_collect_query(page: Any) -> bool:
    """결의서조회승인 조회 실행 — **가시** 조회버튼(다중탭이라 여럿) 실클릭. 폴백=BTN_LOOKUP."""
    rect = await page.evaluate(js.VISIBLE_LOOKUP_BTN_RECT_JS)
    if rect:
        await mouse_click(page, rect["x"], rect["y"])
    else:
        await js_click(page, selectors.BTN_LOOKUP)
    await page.wait_for_timeout(2_000)
    return True


async def read_payment_map(page: Any, limit: int = 500) -> dict:
    """가시 마스터 그리드에서 ABDOCU_NO→GWDOCU_NO(결재번호) 맵을 만든다. 반환
    {ok, n, map:{ABDOCU_NO: GWDOCU_NO}}. ABDOCU_NO/GWDOCU_NO 둘 다 있는 행만 담는다."""
    dump = await page.evaluate(js.VISIBLE_MASTER_ROWS_JS, limit)
    if not (isinstance(dump, dict) and dump.get("ok")):
        return {"ok": False, "reason": (dump or {}).get("reason", "no-grid"), "map": {}}
    mapping: dict[str, str] = {}
    for row in dump.get("rows", []):
        ab = row.get("ABDOCU_NO")
        gw = row.get("GWDOCU_NO")
        if ab and gw:
            mapping[str(ab)] = str(gw)
    return {"ok": True, "n": dump.get("n", 0), "map": mapping}


async def switch_back_to_voucher_tab(page: Any) -> bool:
    """캐시된 전표조회승인 탭으로 복귀(상태 유지). 반환 bool."""
    try:
        await page.click(js.TAB_BACK_VOUCHER_SELECTOR, timeout=5_000)
        await page.wait_for_timeout(1_000)
        return True
    except Exception:  # noqa: BLE001 — 탭 전환 실패는 호출자가 error 로 처리.
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Phase C — 결제창(EAP React) 안 참조문서 선택 sub-flow(child Page 대상)
# ⚠ '확인'/'상신' 무조건 클릭 없음 — click_refdoc_confirm 은 게이트 뒤에서만.
# ══════════════════════════════════════════════════════════════════════════════
async def open_refdoc_dialog(child: Any) -> bool:
    """결제창 하단 '참조문서 선택' 버튼(뷰포트 밖 가능) → scrollIntoView 후 좌표 재계산 클릭.
    반환 = dialog 오픈 시도 여부(버튼 못 찾으면 False)."""
    await child.evaluate(js.REFDOC_SELECT_BTN_SCROLL_JS)
    await child.wait_for_timeout(500)  # smooth-scroll 정착.
    rect = await child.evaluate(js.REFDOC_SELECT_BTN_RECT_JS)
    if not rect:
        return False
    await child.mouse.click(rect["x"], rect["y"])
    await child.wait_for_timeout(1_500)
    return True


async def expand_refdoc_filter(child: Any) -> bool:
    """참조문서 dialog 필터 확장(문서번호·조회 노출). best-effort."""
    try:
        await child.click(js.REFDOC_FILTER_EXPAND_SELECTOR, timeout=5_000)
        await child.wait_for_timeout(800)
        return True
    except Exception:  # noqa: BLE001
        return False


async def fill_refdoc_docno(child: Any, value: str) -> bool:
    """문서번호(=GWDOCU_NO) 입력 — React controlled input 이라 클릭+End+Backspace 다회로 클리어
    후 키보드 타이핑(setValue/value= 직접조작 금지). readback 불일치 시 1회 재시도. 반환 = 값 일치."""
    rect = await child.evaluate(js.REFDOC_DOCNO_INPUT_RECT_JS)
    if not rect:
        return False
    for _attempt in range(2):
        await child.mouse.click(rect["x"], rect["y"])
        await child.keyboard.press("End")
        for _ in range(REFDOC_CLEAR_BACKSPACES):
            await child.keyboard.press("Backspace")
        if value:
            await child.keyboard.type(value)
        await child.wait_for_timeout(300)
        actual = await child.evaluate(js.REFDOC_DOCNO_VALUE_JS)
        if actual == value:
            return True
    return False


async def run_refdoc_search(child: Any) -> bool:
    """필터 확장 상태의 '조회' 버튼 클릭. 반환 = 클릭 시도 여부."""
    rect = await child.evaluate(js.REFDOC_SEARCH_BTN_RECT_JS)
    if not rect:
        return False
    await child.mouse.click(rect["x"], rect["y"])
    return True


async def poll_refdoc_matches(child: Any) -> dict:
    """참조문서 목록에서 문서번호 매치/'없음' 메시지를 조건 폴링(대량 리스트 렌더 지연 대응).
    반환 {docNoMatches:[...], noDataText}. 하나라도 뜨면 즉시 반환."""
    result: dict = {"docNoMatches": [], "noDataText": None}
    for _ in range(REFDOC_POLL_TRIES):
        result = await child.evaluate(js.REFDOC_MATCHES_JS)
        if result.get("docNoMatches") or result.get("noDataText"):
            return result
        await child.wait_for_timeout(REFDOC_POLL_INTERVAL_MS)
    return result


async def select_refdoc_row(child: Any, gwdocu_no: str) -> bool:
    """참조문서목록에서 gwdocu_no 를 포함한 행 클릭(선택). 비영속(확인 전까지). 반환 bool."""
    return bool(await child.evaluate(js.REFDOC_SELECT_ROW_JS, gwdocu_no))


async def move_refdoc_down(child: Any) -> bool:
    """선택 행을 '선택된 문서 목록'으로 이동하는 아래(↓) 버튼 클릭(rect 탐색 실패 시 폴백 좌표).
    비영속(확인 전까지). 반환 = 클릭 시도 여부."""
    rect = await child.evaluate(js.REFDOC_DOWN_BTN_RECT_JS)
    pt = rect or js.REFDOC_DOWN_BTN_FALLBACK
    await child.mouse.click(pt["x"], pt["y"])
    await child.wait_for_timeout(500)
    return True


async def click_refdoc_confirm(child: Any) -> bool:
    """⚠ 게이트 전용 — 참조문서 '확인'(파란 OBTButton) 클릭. reference_doc 훅의 allow_confirm
    (기본 False) 뒤에서만 호출된다. 기본 실행 경로에서는 절대 도달하지 않는다(절대 안전)."""
    rect = await child.evaluate(js.REFDOC_CONFIRM_BTN_RECT_JS)
    if not rect:
        return False
    await child.mouse.click(rect["x"], rect["y"])
    await child.wait_for_timeout(500)
    return True


async def close_refdoc_dialog(child: Any) -> bool:
    """참조문서 dialog 닫기(X) — 확인/선택 미클릭 상태로 취소(비영속 유지). best-effort."""
    rect = await child.evaluate(js.REFDOC_CLOSE_BTN_RECT_JS)
    if not rect:
        return False
    await child.mouse.click(rect["x"], rect["y"])
    await child.wait_for_timeout(500)
    return True
