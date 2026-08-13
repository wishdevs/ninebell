"""구매발주 화면 ① — 순수 브라우저 스텝(이벤트 방출 없음).

`e2e/purchase_order_{project_apply,checkbox_filter}_probe.py`(2026-08-13 라이브 검증 PASS,
부작용 0)의 브라우저 조작부를 이식했다. 스텝은 {"ok": bool, ...} 만 돌려주고, 진행 이벤트·
HITL·실패 문구는 nodes/ 가 담당한다.

⚠⚠ 절대 안전(Phase A) ⚠⚠
  - 이 모듈이 클릭하는 것은 프로젝트 도움창 열기/행선택/'적용'·체크박스·조회(F2) 뿐이다 —
    전부 **조회조건 확정** 동작(데이터 생성 아님). 저장(F7)·결재·행 데이터 변경 코드는 없다.

⏱ 시간축 규율(2026-08-07): 관찰 폴 대기는 항상 실시간(`verify.DEFAULT_SLEEP`), 상한만
   `latency.budget_ms` 로 확대 — 명목 카운터(page.wait_for_timeout 누산)는 delay_scale 로
   관찰창이 붕괴한다.

🔁 팝업 불안정 완화책(프로브 표준 채택): 같은 도움창 인스턴스에서 2회째 검색 시 간헐 소멸
   (비결정적) — **팝업당 검색 1회**, 결과 미확보 시 재오픈 재시도(상한 POPUP_RETRIES=2).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from nbkit.omnisol import js_lib, latency, verify

from . import js

logger = logging.getLogger(__name__)

POPUP_RETRIES = 2  # 도움창 재오픈 재시도 상한(팝업당 검색 1회 완화책)
POPUP_OPEN_CAP_MS = 5_000  # 도움창 출현 상한
SEARCH_SETTLE_CAP_MS = 6_000  # 검색 후 결과/소멸 판정 상한
MIN_SEARCH_SETTLE_MS = 1_200  # 검색 후 결과 수락 최소 정착(프로브 1.5s 실측 — 이전 결과 스냅샷 오독 방지)
APPLY_CLOSE_CAP_MS = 5_000  # '적용' 후 팝업 닫힘 상한
FIELD_REFLECT_CAP_MS = 5_000  # 적용 후 메인 필드 반영 상한
BOM_LOAD_CAP_MS = 40_000  # 조회(F2) 후 트리그리드 로드 상한(리프 337 스케일 실측 대비)
CHECKBOX_SETTLE_MS = 500  # 체크박스 클릭 후 상태 재확인 간격
POLL_MS = 300  # 관찰 폴 간격(실시간)
MAX_SEARCH_RESULTS = 30  # 개입 카드 options 상한

PROJECT_FIELD_LABEL = "프로젝트"
CHECKBOX_PURCHASE = "구매요청"
CHECKBOX_MOVE = "이동요청"


async def _poll(page: Any, script: str, pred, cap_ms: int, arg: Any = None):
    """script 평가 결과가 pred 를 만족할 때까지 실시간 폴링. 만족 값 또는 None(상한 도달)."""
    waited = 0
    cap = latency.budget_ms(cap_ms)
    while True:
        val = await (page.evaluate(script, arg) if arg is not None else page.evaluate(script))
        if pred(val):
            return val
        if waited >= cap:
            return None
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS


async def open_and_search_once(page: Any, keyword: str, *, retries: int = POPUP_RETRIES) -> dict:
    """프로젝트 도움창 열기 → 검색 1회 → 결과 읽기. 팝업 소멸 시 재오픈 재시도(상한 retries).

    반환 {"ok", "rows": [{PJT_NO,PJT_NM,START_DT,END_DT,RSPNBER_EMP_NM,PJT_ST_NM}], "attempt"}.
    rows 는 상위 MAX_SEARCH_RESULTS 행. 0건 검색도 ok(빈 rows) — 팝업은 열린 채 유지된다.
    """
    for attempt in range(1, retries + 1):
        box = await page.evaluate(js_lib.PROJECT_PICKER_BOX_JS)
        if not box:
            return {"ok": False, "reason": "프로젝트 돋보기 버튼을 찾지 못했습니다."}
        await page.mouse.click(box["x"], box["y"])
        opened = await _poll(page, js.WIN_STATE_JS, lambda w: bool(w), POPUP_OPEN_CAP_MS)
        if not opened:
            logger.debug("open_and_search_once: 도움창 미출현(attempt=%d)", attempt)
            continue
        if not await page.evaluate(js.SET_KEYWORD_JS, keyword):
            logger.debug("open_and_search_once: #keyword 미발견(attempt=%d)", attempt)
            continue
        await page.keyboard.press("Enter")
        # 검색 후 판정: 그리드 읽힘(ok) 또는 팝업 소멸(재시도). 결과 0건도 유효한 응답이다.
        waited = 0
        cap = latency.budget_ms(SEARCH_SETTLE_CAP_MS)
        while True:
            wins = await page.evaluate(js.WIN_STATE_JS)
            if not wins:
                break  # 팝업 소멸 — 재오픈 재시도
            grid = await page.evaluate(js.READ_POPUP_GRID_JS, MAX_SEARCH_RESULTS)
            if grid.get("ok") and waited >= MIN_SEARCH_SETTLE_MS:
                # 최소 정착 대기 후 읽음 — Enter 직후 이전 결과 스냅샷 오독 방지.
                return {"ok": True, "attempt": attempt, "rows": grid.get("rows") or []}
            if waited >= cap:
                if grid.get("ok"):
                    return {"ok": True, "attempt": attempt, "rows": grid.get("rows") or []}
                break
            await verify.DEFAULT_SLEEP(POLL_MS / 1000)
            waited += POLL_MS
    return {"ok": False, "reason": "프로젝트 도움창이 검색 후 계속 소멸했습니다(재시도 상한 도달)."}


async def close_popup(page: Any) -> None:
    """도움창 정리(best-effort) — ESC. 적용 없이 닫으므로 폼 미반영(프로브 검증)."""
    try:
        wins = await page.evaluate(js.WIN_STATE_JS)
        if wins:
            await page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001 — teardown 실패는 무해.
        logger.debug("close_popup 실패(무시)", exc_info=True)


async def apply_project(page: Any, keyword: str, pjt_no: str) -> dict:
    """도움창 재검색(팝업당 1회+재오픈 상한) → PJT_NO 행 선택 → '적용' → 닫힘·필드 반영 확인.

    ⚠ 프리필 불신(D11): 메인 필드에 이미 같은 값이 보여도 항상 이 명시 사이클로 재선택한다.
    반환 {"ok", "name"?, "field_value"?, "reason"?}.
    """
    search = await open_and_search_once(page, keyword)
    if not search.get("ok"):
        return {"ok": False, "reason": search.get("reason") or "도움창 검색 실패"}

    sel = await page.evaluate(js.SELECT_ROW_JS, pjt_no)
    if not sel.get("ok"):
        await close_popup(page)
        return {"ok": False, "reason": f"도움창 결과에서 프로젝트 코드 {pjt_no} 행을 찾지 못했습니다."}

    apply_box = await page.evaluate(js.APPLY_BTN_JS)
    if not apply_box:
        await close_popup(page)
        return {"ok": False, "reason": "도움창 '적용' 버튼을 찾지 못했습니다."}
    await page.mouse.click(apply_box["x"], apply_box["y"])

    closed = await _poll(page, js.WIN_STATE_JS, lambda w: not w, APPLY_CLOSE_CAP_MS)
    if closed is None:
        return {"ok": False, "reason": "'적용' 후 도움창이 닫히지 않았습니다."}

    # 적용이 폼에 실제 반영됐는지 — 표시값 확인이 판정의 끝(팝업 내부 선택만으론 불충분).
    name = str(sel.get("name") or "")
    probe = name.split(",")[0].strip() if name else str(pjt_no)
    field_val = await _poll(
        page,
        js_lib.FIELD_DISPLAY_JS,
        lambda v: bool(v) and probe in str(v),
        FIELD_REFLECT_CAP_MS,
        PROJECT_FIELD_LABEL,
    )
    if field_val is None:
        return {"ok": False, "reason": f"적용 후 프로젝트 필드에 '{probe}' 반영을 확인하지 못했습니다."}
    return {"ok": True, "name": name, "field_value": field_val}


async def set_checkbox(page: Any, label: str, want_checked: bool) -> dict:
    """체크박스를 want_checked 로 보장(label[for] 직결) — 다르면 클릭 후 재확인."""
    rect = await page.evaluate(js.CHECKBOX_RECT_JS, label)
    if not rect:
        return {"ok": False, "reason": f"'{label}' 체크박스를 찾지 못했습니다."}
    if rect["checked"] == want_checked:
        return {"ok": True, "unchanged": True, "id": rect.get("id")}
    await page.mouse.click(rect["x"], rect["y"])
    await verify.DEFAULT_SLEEP(CHECKBOX_SETTLE_MS / 1000)
    rect2 = await page.evaluate(js.CHECKBOX_RECT_JS, label)
    if not (rect2 and rect2["checked"] == want_checked):
        return {"ok": False, "reason": f"'{label}' 체크박스를 {'체크' if want_checked else '해제'}하지 못했습니다."}
    return {"ok": True, "id": rect2.get("id")}


async def click_lookup(page: Any) -> dict:
    """조회(F2) 실행 — 버튼 좌표 클릭(미발견 시 F2 키 폴백). 확인 다이얼로그 없음(실측)."""
    box = await page.evaluate(js.LOOKUP_BTN_JS)
    if box:
        await page.mouse.click(box["x"], box["y"])
    else:
        await page.keyboard.press("F2")
    return {"ok": True, "via": "button" if box else "key"}


async def wait_bom_loaded(page: Any, *, cap_ms: int = BOM_LOAD_CAP_MS) -> int:
    """조회 후 트리그리드 행이 나타날 때까지 실시간 폴링. 행수(>0) 또는 -1(상한 도달)."""
    t0 = time.monotonic()
    n = await _poll(page, js.TREEGRID_COUNT_JS, lambda v: isinstance(v, int) and v > 0, cap_ms)
    logger.debug("wait_bom_loaded: rows=%s (%.1fs)", n, time.monotonic() - t0)
    return n if isinstance(n, int) else -1


async def read_bom_signature(page: Any) -> dict | None:
    """트리그리드 시그니처 {count, mvY(MV_FG='Y' 행수)} — 그리드 미존재/예외 None."""
    sig = await page.evaluate(js.TREEGRID_MV_SIG_JS)
    return sig if isinstance(sig, dict) else None


async def wait_bom_filtered(page: Any, prev: dict | None, *, cap_ms: int = BOM_LOAD_CAP_MS) -> int:
    """'구매요청만' 조회(F2) 후 **필터가 반영된** 그리드를 독립 확인 — 행수 또는 -1.

    stale-grid 레이스 방지(2026-08-13 스모크 실측: 직전 무필터 410행이 'rows>0' 을 즉시
    충족해 필터 재조회 완료 전에 읽힘). 조회 전 시그니처(prev)를 받아
      수락 = count>0 ∧ mvY==0 ∧ (prev 와 다름 ∨ prev 도 이미 mvY==0)
             ∧ 연속 2회 폴 동일(부분 로드 스냅샷 오독 방지).
    행수가 우연히 같아도 mvY(내용)로 구별한다 — voucher 세팅→독립확인 규율과 동일.
    """
    t0 = time.monotonic()
    waited = 0
    cap = latency.budget_ms(cap_ms)
    stable: dict | None = None
    while True:
        sig = await read_bom_signature(page)
        accept = (
            sig is not None
            and isinstance(sig.get("count"), int)
            and sig["count"] > 0
            and sig.get("mvY") == 0
            and (prev is None or sig != prev or prev.get("mvY") == 0)
        )
        if accept:
            if stable == sig:
                logger.debug(
                    "wait_bom_filtered: rows=%s (%.1fs)", sig["count"], time.monotonic() - t0
                )
                return int(sig["count"])
            stable = sig
        else:
            stable = None
        if waited >= cap:
            logger.debug(
                "wait_bom_filtered: 상한 도달 sig=%s prev=%s (%.1fs)",
                sig,
                prev,
                time.monotonic() - t0,
            )
            return -1
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS


async def read_bom_rows(page: Any, fields: list[str]) -> dict:
    """트리그리드 전량 읽기(getLevel+getValue 루프 — getJsonRows 는 트리에서 null).

    반환 {"ok", "count", "rows": [{"i","level", <fields...>}]} — 읽기 전용.
    """
    return await page.evaluate(js.TREEGRID_READ_JS, fields)
