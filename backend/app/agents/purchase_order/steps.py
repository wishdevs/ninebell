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

🔁 도움창 검색 시퀀스(2026-08-14 재실측 — 물리 Enter 가 '검색'에서 '창 닫기(적용류)'로
   바뀌어 전면 재확립): 열기 → 그리드 준비 폴 → **실타이핑**(오픈 직후 #keyword 가
   포커스+전체선택이라 프리필을 교체) → **합성 Enter**(SEARCH_KEY_EVENT_JS) → 결과 변화
   감지. 물리 Enter·JS 세터+합성 Enter 조합은 팝업이 죽는다(실측). 팝업당 검색 1회,
   결과 미확보 시 재오픈 재시도(상한 POPUP_RETRIES).
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
POPUP_BOOT_CAP_MS = 8_000  # 출현 후 내부 그리드 준비(부팅) 상한 — 준비 전 입력이 팝업을 죽인다
POPUP_INIT_SETTLE_MS = 1_000  # 그리드 준비 후 정착(프리필 자동검색·포커스 안정화, 프로브 실측)
SEARCH_SETTLE_CAP_MS = 6_000  # 합성 Enter 후 결과 변화/소멸 판정 상한(응답 실측 ~1s)
VANISH_CONFIRM_POLLS = 2  # 팝업 소멸 판정에 필요한 연속 빈 폴 수(일시 숨김 오판 방지)
TYPE_DELAY_MS = 40  # 실타이핑 키 간격(실시간) — 프로브 검증값
APPLY_CLOSE_CAP_MS = 5_000  # '적용' 후 팝업 닫힘 상한
FIELD_REFLECT_CAP_MS = 5_000  # 적용 후 메인 필드 반영 상한
BOM_LOAD_CAP_MS = 40_000  # 조회(F2) 후 트리그리드 로드 상한(리프 337 스케일 실측 대비)
CHECKBOX_SETTLE_MS = 500  # 체크박스 클릭 후 상태 재확인 간격
CHECKBOX_RETRIES = 3  # 체크박스 클릭 재시도 상한 — F2 직후 클릭 간헐 유실(wbs 프로브 실측)
POLL_MS = 300  # 관찰 폴 간격(실시간)
MAX_SEARCH_RESULTS = 30  # 개입 카드 options 상한

PROJECT_FIELD_LABEL = "프로젝트"
CHECKBOX_PURCHASE = "구매요청"
CHECKBOX_MOVE = "이동요청"

# D3 상단 고정값 — (필드 id, 라벨, 코드, 표시). 진입 시 ERP 자동 기본값과 같은 값이다.
FIXED_HEADER: tuple[tuple[str, str, str, str], ...] = (
    ("i_purgrp_cd", "구매그룹", "1000", "나인벨"),
    ("i_purorg_cd", "구매조직", "1000", "나인벨"),
)
# 상단 구매사유 — **비운다**(구매사유는 발주단위별로 계획서에서 받는다, D3/D6).
PURCHASE_REASON_FIELD = "i_rmk_dc"
HEADER_SETTLE_MS = 400  # 세팅 후 독립 확인 전 정착


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


async def _type_keyword(page: Any, keyword: str) -> bool:
    """#keyword 를 실타이핑으로 교체하고 값 반영을 검증한다.

    1차: 오픈 직후 자동 포커스+전체선택 상태를 믿고 바로 타이핑(프로브 실측 경로).
    2차: 값 불일치 시 트리플클릭(입력 전체선택) 후 재타이핑.
    """
    for tries in range(2):
        if tries == 1:
            kwbox = await page.evaluate(js.KEYWORD_BOX_JS)
            if not kwbox:
                return False
            await page.mouse.click(kwbox["x"], kwbox["y"], click_count=3)
        await page.keyboard.type(keyword, delay=TYPE_DELAY_MS)
        val = await page.evaluate(js.KEYWORD_VALUE_JS)
        if str(val).strip() == keyword:
            return True
    return False


async def open_and_search_once(page: Any, keyword: str, *, retries: int = POPUP_RETRIES) -> dict:
    """프로젝트 도움창 열기 → 검색 1회 → 결과 읽기. 실패 시 재오픈 재시도(상한 retries).

    시퀀스(2026-08-14 재실측 확정 — 프로브 po_trigger_matrix):
      열기 → 그리드 준비 폴(부팅 전 입력 금지) → 정착 → 프리필 자동검색 잔상 스냅샷
      → 실타이핑 교체 → 합성 Enter(물리 Enter 는 창을 닫는다) → **결과 변화** 감지.
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
        # 부팅 준비 — 셸(.k-window)이 아니라 내부 그리드 존재까지. 준비 전 입력은 팝업을 죽인다.
        booted = await _poll(
            page,
            js.READ_POPUP_GRID_JS,
            lambda g: isinstance(g, dict) and g.get("ok"),
            POPUP_BOOT_CAP_MS,
            MAX_SEARCH_RESULTS,
        )
        if not booted:
            logger.debug("open_and_search_once: 그리드 미준비(attempt=%d)", attempt)
            await close_popup(page)
            continue
        await verify.DEFAULT_SLEEP(POPUP_INIT_SETTLE_MS / 1000)
        # 프리필 자동검색 잔상 스냅샷 — 오픈 시 메인 필드 텍스트로 자동 검색이 돌아 있다.
        pre = await page.evaluate(js.READ_POPUP_GRID_JS, MAX_SEARCH_RESULTS)
        pre_ids = tuple(r.get("PJT_NO") for r in (pre.get("rows") or [])) if pre.get("ok") else ()

        if not await _type_keyword(page, keyword):
            logger.debug("open_and_search_once: 검색어 타이핑 실패(attempt=%d)", attempt)
            await close_popup(page)
            continue
        await page.evaluate(js.SEARCH_KEY_EVENT_JS)

        # 수락 = 결과가 잔상과 달라짐(응답 도착). 상한 도달 시 그리드가 살아 있으면 현재 결과
        # 수락(프리필 검색어 = 요청 검색어라 결과가 동일한 정당 케이스). 소멸은 연속 2폴 확정.
        waited = 0
        cap = latency.budget_ms(SEARCH_SETTLE_CAP_MS)
        empty_polls = 0
        last_rows: list | None = None
        while True:
            wins = await page.evaluate(js.WIN_STATE_JS)
            if not wins:
                empty_polls += 1
                if empty_polls >= VANISH_CONFIRM_POLLS:
                    break  # 팝업 소멸 확정 — 재오픈 재시도
            else:
                empty_polls = 0
                grid = await page.evaluate(js.READ_POPUP_GRID_JS, MAX_SEARCH_RESULTS)
                if grid.get("ok"):
                    last_rows = grid.get("rows") or []
                    ids = tuple(r.get("PJT_NO") for r in last_rows)
                    if ids != pre_ids:
                        return {"ok": True, "attempt": attempt, "rows": last_rows}
            if waited >= cap:
                if last_rows is not None:
                    return {"ok": True, "attempt": attempt, "rows": last_rows}
                break
            await verify.DEFAULT_SLEEP(POLL_MS / 1000)
            waited += POLL_MS
    return {"ok": False, "reason": "프로젝트 도움창 검색이 계속 실패했습니다(재시도 상한 도달)."}


async def close_popup(page: Any) -> None:
    """도움창 정리(best-effort) — ESC. 적용 없이 닫으므로 폼 미반영(프로브 검증)."""
    try:
        wins = await page.evaluate(js.WIN_STATE_JS)
        if wins:
            await page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001 — teardown 실패는 무해.
        logger.debug("close_popup 실패(무시)", exc_info=True)


async def apply_project(
    page: Any, keyword: str, pjt_no: str, *, retries: int = POPUP_RETRIES
) -> dict:
    """도움창 재검색(팝업당 1회+재오픈 상한) → 행 선택 → '적용' → 닫힘·필드 반영 확인.

    행 선택: pjt_no 가 있으면 그 행(정확 선택), 없으면 **검색 결과가 정확히 1건일 때만**
    그 행을 쓴다(직접 입력 폼의 번호 생략 경로 — 0건/복수는 추측하지 않고 실패).

    ⚠ 프리필 불신(D11): 메인 필드에 이미 같은 값이 보여도 항상 이 명시 사이클로 재선택한다.
    반환 {"ok", "name"?, "pjt_no"?, "field_value"?, "reason"?}.
    """
    search = await open_and_search_once(page, keyword, retries=retries)
    if not search.get("ok"):
        return {"ok": False, "reason": search.get("reason") or "도움창 검색 실패"}

    rows = search.get("rows") or []
    if not pjt_no:
        if len(rows) != 1:
            await close_popup(page)
            return {
                "ok": False,
                "reason": (
                    f"'{keyword}' 검색 결과가 {len(rows)}건입니다 — 프로젝트를 특정할 수 "
                    "없어 프로젝트 번호가 필요합니다."
                ),
            }
        pjt_no = str(rows[0].get("PJT_NO") or "")

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
    return {"ok": True, "name": name, "pjt_no": pjt_no, "field_value": field_val}


async def ensure_fixed_header(page: Any) -> dict:
    """D3 고정값 보장 — 구매그룹·구매조직 = 나인벨(1000), 상단 구매사유 비움.

    **확인이 본업이고 세팅은 어긋났을 때만 한다.** 정상 경로에선 ERP 가 진입 시 자동 기본값을
    채우고 프로젝트 적용·조회(F2) 후에도 유지된다(프로브 3지점 실측 2026-08-14). 그래도 D11
    프리필 불신과 같은 이유로 매 실행 확인한다 — 세션/계정에 따라 비어 있을 수 있고, 잘못된
    구매그룹으로 구매요청이 저장되면(Phase B) 되돌리기 어렵다.

    세팅은 **코드+표시 동시**다 — 코드만 넣으면 표시가 해석되지 않는다(프로브 실측 (a) 실패
    → (b) 성공, 복구 후 조회(F2) 257행 정상). 세팅 후 **독립 재확인**으로 판정한다.

    ⚠ Phase B 선행조건: 이 복구는 폼 값(제출값 code + 표시)만 맞춘다. 코드피커 **위젯 내부
      모델**까지 동기화되는지는 저장 경로가 없어 미검증이다 — 저장 게이트를 열기 전에
      '복구 후 저장' 을 반드시 실측할 것(정상 경로는 ERP 기본값이라 영향 없음).

    반환 {"ok": True, "repaired": [라벨…]} | {"ok": False, "reason": …}
    """
    ids = [f[0] for f in FIXED_HEADER]
    st = await page.evaluate(js.HEADER_STATE_JS, [ids, PURCHASE_REASON_FIELD])
    fields = st.get("fields") or {}
    repaired: list[str] = []

    for fid, label, code, text in FIXED_HEADER:
        cur = fields.get(fid) or {}
        if cur.get("code") is None:
            return {"ok": False, "reason": f"'{label}' 필드를 화면에서 찾지 못했습니다."}
        if cur.get("code") == code and cur.get("text") == text:
            continue
        await page.evaluate(js.SET_INPUT_JS, [fid, code])
        await page.evaluate(js.SET_INPUT_JS, [f"{fid}_text", text])
        repaired.append(label)

    if st.get("reason") is None:
        return {"ok": False, "reason": "상단 구매사유 필드를 화면에서 찾지 못했습니다."}
    if str(st["reason"]).strip():
        await page.evaluate(js.SET_INPUT_JS, [PURCHASE_REASON_FIELD, ""])
        repaired.append("구매사유(비움)")

    if not repaired:
        return {"ok": True, "repaired": []}

    # 세팅→독립 확인(voucher 무결성 규율) — 세팅 반환값이 아니라 화면을 다시 읽어 판정한다.
    await verify.DEFAULT_SLEEP(HEADER_SETTLE_MS / 1000)
    st2 = await page.evaluate(js.HEADER_STATE_JS, [ids, PURCHASE_REASON_FIELD])
    f2 = st2.get("fields") or {}
    for fid, label, code, text in FIXED_HEADER:
        cur = f2.get(fid) or {}
        if cur.get("code") != code or cur.get("text") != text:
            return {
                "ok": False,
                "reason": (
                    f"'{label}' 을 {text}({code}) 로 맞추지 못했습니다 "
                    f"— 현재 코드 {cur.get('code')!r} / 표시 {cur.get('text')!r}."
                ),
            }
    if str(st2.get("reason") or "").strip():
        return {"ok": False, "reason": "상단 구매사유를 비우지 못했습니다."}
    return {"ok": True, "repaired": repaired}


async def set_checkbox(page: Any, label: str, want_checked: bool) -> dict:
    """체크박스를 want_checked 로 보장(label[for] 직결) — 다르면 클릭 후 재확인.

    클릭은 CHECKBOX_RETRIES 회까지 재시도 — 그리드 로드 직후 클릭이 간헐 유실된다
    (2026-08-13 wbs 프로브 실측 1회: F2 직후 첫 클릭 미반영). 매 시도 전 상태를 다시 읽어
    이미 원하는 상태면 즉시 수락한다(더블 토글 방지).
    """
    rect = await page.evaluate(js.CHECKBOX_RECT_JS, label)
    if not rect:
        return {"ok": False, "reason": f"'{label}' 체크박스를 찾지 못했습니다."}
    if rect["checked"] == want_checked:
        return {"ok": True, "unchanged": True, "id": rect.get("id")}
    for _ in range(CHECKBOX_RETRIES):
        await page.mouse.click(rect["x"], rect["y"])
        await verify.DEFAULT_SLEEP(CHECKBOX_SETTLE_MS / 1000)
        rect2 = await page.evaluate(js.CHECKBOX_RECT_JS, label)
        if rect2 and rect2["checked"] == want_checked:
            return {"ok": True, "id": rect2.get("id")}
        if rect2:
            rect = rect2  # 리플로우로 좌표가 바뀌었을 수 있어 갱신 후 재클릭.
    return {"ok": False, "reason": f"'{label}' 체크박스를 {'체크' if want_checked else '해제'}하지 못했습니다."}


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
