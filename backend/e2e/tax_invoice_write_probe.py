"""HEADLESS 쓰기 프로브 — 세금계산서 결의서입력 F7 실저장 게이트 사이클(단계 3).

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7 실저장 → **독립 재조회 검증**(별도 브라우저 세션) → F6 삭제 → 잔존 0 확인이 한 사이클.
  - 삭제 3중 가드(결의자=이트라이브2 + 결의구분=세금계산서(51) + 미결 DOCU_NO 공백) 완화 금지.
    검증·삭제는 `e2e.product_cycle.erp_verify_and_delete` 그대로 재사용(hakjagum/gyeongjo 동일 계약).
  - 상신(결재) 절대 금지 — F7·F6 만.
  - 분할처리 팝업의 '적용' 이후는 F7 저장과 동일한 비가역 지점 — 신중히 진행하고 실패 시 즉시
    Escape 로 닫는다(split_probe.py 관례 유지, 이번엔 팝업이 열리면 끝까지 사이클을 돈다).

Case A(발행 전 22, 우선) — 완전 사이클: F3 → 증빙 22 적용("아니요") → 거래처(코웨이) → 적요 →
예산단위 → 공급가액 → 프로젝트(WBS 800) → 자금과목(일반경비) → 결제방법(당월결제) →
자금예정일/회계일(그리드 API) → F7 → 독립검증 → F6 삭제 → 잔존 0.

Case B(원증빙 11+비용분할 가설, A 완료 후) — 가설: 이전 split_probe(2026-08-19)는 거래처·
프로젝트를 채우지 않고 비용분할을 클릭해 무반응이었다(원인분류: 필드부재 가설 미검증). 이번엔
거래처+프로젝트까지 채운 뒤 재시도하고, 콘솔 로그/pageerror 를 캡처한다. 그래도 무반응이면
증빙 13 으로 재시도. 열리면 team-lead 지시대로 분할 2행 생성→채움→차액반영→적용→F7→검증→삭제.

재사용(신규 아님):
  - `app.agents.card_collect.steps.save_document` — F7 + 확인모달 + 검증토스트/오류모달 판정(카드 관례).
  - `e2e.product_cycle.erp_verify_and_delete` — 별도세션 조회+3중가드+상세대조+F6+잔존0.
  - `app.agents.trip_domestic.steps` — `_open_detail_cell_picker`/`_fill_partner_cell`/`fill_project`/
    `type_amount`/`set_row_note`(NOTE_DC setValue, 트리거 없는 inert 필드).
  - `e2e.mgmt_item_panel_probe` — 관리항목 tb1 DOM 테이블(ROW_SCROLL_JS/ROW_BUTTON_JS/ROW_VALUES_JS/
    TABLE_DUMP_JS) — 자금과목·결제조건은 FUND_CD/END_DT 가 hidden 백킹필드(대응 NM 컬럼 없음, 읽기
    프로브 실측)라 캔버스 셀이 아니라 이 DOM 패널이 실제 위젯이다(SKILL.md 함정 #2).
  - `e2e.tax_invoice_split_probe` — INVOICE_POPUP_DUMP_JS(팝업 구조 범용 덤프)·
    DISTRIBUTION_GRID_DUMP_JS·BUTTON_BY_TEXT_JS.
  - `nbkit.omnisol.js_lib.SET_ACCT_DATE_JS` — 회계일(ACTG_DT, 마스터) 그리드 API 세팅(기 검증).

신규(이 문서 고유): END_DT(자금예정일) 그리드 API 세팅(SET_DETAIL_CELL_JS 재사용+READ_DETAIL_DATE_JS
재독, set_invoice_date 패턴 이식) · 관리항목 팝업 범용 텍스트매칭 행선택(_pick_row_by_text, 필드명
불명 팝업 대응) · 분할처리 그리드 셀 에디터 오픈(OPEN_DIST_CELL_EDITOR_JS, id 기반).

Usage: cd backend && .venv/bin/python e2e/tax_invoice_write_probe.py
env: TAX_INVOICE_CASE=A|B|AB(기본 AB) · E2E_USERID/E2E_PASSWORD(기본 이트라이브2/1111) ·
     E2E_HEADLESS(기본 1) · E2E_DELAY_SCALE(기본 0.4)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.card_collect.steps import save_document  # noqa: E402  (재사용: F7 게이트)
from app.agents.trip_domestic import js as tj_js  # noqa: E402  (재사용: SET_DETAIL_CELL_JS/READ_DETAIL_DATE_JS)
from app.agents.trip_domestic.steps import (  # noqa: E402  (재사용)
    _fill_partner_cell,
    _open_detail_cell_picker,
    fill_project,
    set_row_note,
    type_amount,
)
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from e2e.mgmt_item_panel_probe import (  # noqa: E402  (재사용: 관리항목 tb1 DOM 패널)
    ROW_BUTTON_JS,
    ROW_SCROLL_JS,
    ROW_VALUES_JS,
    TABLE_DUMP_JS,
)
from e2e.product_cycle import erp_verify_and_delete  # noqa: E402  (재사용: 독립검증+F6+잔존0)
from e2e.tax_invoice_split_probe import (  # noqa: E402  (재사용)
    BUTTON_BY_TEXT_JS,
    INVOICE_POPUP_DUMP_JS,
)
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors, verify  # noqa: E402
from nbkit.omnisol.codepicker import _picker_search  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
RUN_CASES = os.environ.get("TAX_INVOICE_CASE", "AB").upper()
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

GUBUN_LABEL = "세금계산서"
FG_CODE = "51"  # D3 확정(read_probe 2026-08-19)
PARTNER_SEARCH = "코웨이"  # preissue 녹화 실사용 거래처 검색어
PARTNER_NAME = "코웨이(주)"  # 실측(2026-08-19 쓰기프로브 attempt 1): 정확 등록명은 "(주)" 포함
PROJECT_WBS = "800"
BUDGET_SEARCH_KEYWORDS = ("일반", "공통", "관리")  # split_probe 2026-08-19 실측: "일반"→임원실(1000)
FUND_SEARCH = "일반경비"  # D8 기본값
STLM_SEARCH = "당월결제"  # D8 기본값
TODAY_COMPACT = date.today().strftime("%Y%m%d")

CASE_A_EVDN = "22"
CASE_A_AMOUNT = 37000  # 임의 식별 가능 금액(라운드 아님 — 테스트 데이터 티가 나게)
CASE_A_NOTE = "옴니솔프로브테스트A"

CASE_B_EVDN_PRIMARY = "11"
CASE_B_EVDN_FALLBACK = "13"
CASE_B_AMOUNT = 84000
CASE_B_NOTE = "옴니솔프로브테스트B"

# ── 신규 작성분(이 문서 고유) ─────────────────────────────────────────────────────
# END_DT(자금예정일) — FUND_CD 와 동형(hidden 백킹필드, 대응 NM 컬럼 없음, 읽기프로브 실측) —
# set_invoice_date(START_DT) 패턴을 그대로 이식해 그리드 API 로 세팅한다.
async def _set_settlement_date(page: Page, ymd_compact: str) -> dict:
    w = await page.evaluate(tj_js.SET_DETAIL_CELL_JS, {"field": "END_DT", "value": ymd_compact})
    if not w.get("ok"):
        return {"ok": False, "reason": w.get("reason") or "자금예정일 세팅 실패"}
    r = await page.evaluate(tj_js.READ_DETAIL_DATE_JS, "END_DT")
    got = str(r.get("compact") or "") if r.get("ok") else ""
    if got != ymd_compact:
        return {"ok": False, "reason": f"자금예정일 반영 불일치(기대 {ymd_compact}·실제 {r})"}
    return {"ok": True, "after": r.get("raw")}


# ⚠ 수정(attempt 1 실측, 2026-08-19): e2e.tax_invoice_split_probe.DISTRIBUTION_GRID_DUMP_JS 는
# `document.getElementById('GLDDOC00300_DISTRIBUTION_grid')` 를 dewsControl 요소로 가정하는데
# 실측 결과 그 id 는 wrapper 이고 `.dews-ui-grid` 는 그 **자손**이다("Cannot read properties of
# undefined (reading '_grid')" — jQuery(el).data('dewsControl') 가 undefined). "분할처리" 타이틀로
# 팝업(.k-window)을 찾고 그 안의 `.dews-ui-grid` 를 잡는 방식(INVOICE_POPUP_DUMP_JS 와 동일 패턴)
# 으로 교체 — 컬럼 덤프는 INVOICE_POPUP_DUMP_JS(재사용, 정상 동작 확인됨)로 대체하고, 이 함수는
# 셀 에디터 오픈(금액 인라인 입력) 전용 신규 프리미티브.
OPEN_DIST_CELL_EDITOR_JS = """({ rowIndex, fieldName }) => {
  try {
    const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
    if (!dlg) return { ok: false, reason: 'no-분할처리-popup' };
    const gridEl = dlg.querySelector('.dews-ui-grid');
    if (!gridEl) return { ok: false, reason: 'no-grid-el' };
    const g = window.jQuery(gridEl).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    if (n < 1) return { ok: false, reason: 'no-rows' };
    const idx = (rowIndex == null) ? Math.max(0, n - 1) : rowIndex;
    if (idx < 0 || idx >= n) return { ok: false, reason: 'row-out-of-range(' + idx + '/' + n + ')' };
    g.setCurrent({ itemIndex: idx, fieldName });
    g.showEditor();
    return { ok: true, idx, rows: n };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 150) }; }
}"""

# 분할행 코드피커(CC_NM/PJT_NM) 셀의 돋보기 오버레이 — NOTE_DC/SPPRC_AMT2 와 동일 id 재사용
# (RealGrid 는 필드타입별 오버레이 1개를 재사용하는 관례, `_grid_line`=텍스트/피커 공용).
DIST_EDITOR_MAGNIFIER_JS = """() => {
  const inp = document.getElementById('GLDDOC00300_DISTRIBUTION_grid_line');
  if (!inp || inp.offsetParent === null) return null;
  const r = inp.getBoundingClientRect();
  return { x: Math.round(r.right + 8), y: Math.round(r.top + r.height / 2), id: inp.id };
}"""

# 분할처리 팝업 그리드 rowIndex 의 **체크박스 열** 좌표(좌측 끝, 녹화 L147 x=28 관례) — 행 삭제
# 전 "행 체크"용. DIST_ROW_RECT_JS(일반 셀 클릭, x+150)와 x 오프셋만 다르다.
DIST_ROW_CHECKBOX_RECT_JS = """(rowIndex) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
  if (!dlg) return null;
  const gridEl = dlg.querySelector('.dews-ui-grid');
  if (!gridEl) return null;
  const gr = gridEl.getBoundingClientRect();
  return { x: Math.round(gr.x + 15), y: Math.round(gr.y + 30 + rowIndex * 32 + 16) };
}"""

# 분할처리 팝업 그리드 행수 — attempt 2 실측: '추가' 클릭이 새 행을 만들지 못하고 기존 0행을
# 재사용하는 사례가 있었다(2회 모두 idx=0/rows=1). 클릭 성공 판정을 "행수 증가"로 확정하기 위한
# 전용 리더(SKILL.md 함정 #3 "성공 신호=행수 증가" 패턴, 분할처리 팝업 스코프로 이식).
DIST_ROWCOUNT_JS = """() => {
  try {
    const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
    if (!dlg) return -2;
    const gridEl = dlg.querySelector('.dews-ui-grid');
    if (!gridEl) return -3;
    return window.jQuery(gridEl).data('dewsControl')._grid.getDataSource().getRowCount();
  } catch (e) { return -1; }
}"""

# 분할처리 팝업 그리드 rowIndex 의 화면 좌표(mgmt_item_panel_probe.POPUP_ROW_RECT_JS 와 동일 관례:
# header≈30px + rowIndex×≈32px). attempt 4 가설: 차액반영은 JS setCurrent 가 아니라 **실제 마우스
# 클릭으로 선택된(trusted) 행**을 대상으로 한다 — OMNISOL_NOTES §3 KEYBOARD_FALLBACK 과 동종 패턴
# (합성 이벤트로는 트리거 미발화, 실클릭만 인식).
DIST_ROW_RECT_JS = """(rowIndex) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
  if (!dlg) return null;
  const gridEl = dlg.querySelector('.dews-ui-grid');
  if (!gridEl) return null;
  const gr = gridEl.getBoundingClientRect();
  return { x: Math.round(gr.x + 150), y: Math.round(gr.y + 30 + rowIndex * 32 + 16) };
}"""

# ⚠ 신규(이 라운드 고유) — PROCESS.md 갱신분 검증: 분할 F7 반려 원인은 **메인 detail 그리드**
# (분할처리 팝업 아님)의 FEOTH_ACCT_NM("계정과목" 상대계정) 컬럼이 배부비용행에 비어있는 것.
# nbkit.omnisol.js_lib.OPEN_DETAIL_CELL_EDITOR_JS 는 항상 마지막 행만 열어(rowIndex 파라미터
# 없음) 분할행 각각(마지막 행이 아닌 중간 행 포함)을 못 연다 — rowIndex 파라미터화한 버전.
OPEN_MAIN_DETAIL_CELL_EDITOR_BY_INDEX_JS = """({ rowIndex, fieldName }) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    if (rowIndex < 0 || rowIndex >= n) return { ok: false, reason: 'row-out-of-range(' + rowIndex + '/' + n + ')' };
    g.setCurrent({ itemIndex: rowIndex, fieldName });
    g.showEditor();
    return { ok: true, idx: rowIndex, rows: n };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 150) }; }
}"""


def _pick_row_by_text(rows: list[dict], text: str) -> tuple[int | None, dict | None]:
    """팝업 그리드 행에서 **필드명과 무관하게** 문자열 값 중 text 를 포함하는 첫 행 인덱스.

    자금과목(기표)/결제조건 팝업은 필드명이 미상(❓)이라 code/name 컬럼을 가정할 수 없다 —
    행의 모든 문자열 값을 훑어 매칭한다(범용, 필드명 불명 팝업 전용 대응).
    """
    for i, r in enumerate(rows):
        for v in r.values():
            if isinstance(v, str) and text and text in v:
                return i, r
    return None, None


async def _fill_mgmt_item_picker(page: Page, row_label: str, search_kw: str) -> dict:
    """관리항목(tb1) 행 라벨로 피커를 열고 search_kw 텍스트 매칭 행을 적용 + 반영 확인.

    반환 {ok, row_dump_before, popup_dump, picked, readback} | {ok:False, reason, ...}.
    """
    out: dict = {"row_label": row_label, "search_kw": search_kw}
    scrolled = await page.evaluate(ROW_SCROLL_JS, row_label)
    out["scrolled"] = scrolled
    if not scrolled:
        return {**out, "ok": False, "reason": f"관리항목 행 '{row_label}' 을 찾지 못함(패널 미렌더?)"}
    await page.wait_for_timeout(200)
    box = await page.evaluate(ROW_BUTTON_JS, row_label)
    out["button_box"] = box
    if not box:
        return {**out, "ok": False, "reason": f"관리항목 행 '{row_label}' 코드피커 버튼 없음"}
    before = await page.evaluate(js_lib.POPUP_COUNT_JS)
    await mouse_click(page, box["x"], box["y"])
    opened = await verify.confirm_popup_count(page, more_than=before, timing=verify.ASYNC)
    if not opened:
        return {**out, "ok": False, "reason": f"'{row_label}' 팝업이 열리지 않음 — {opened.reason if hasattr(opened, 'reason') else opened}"}
    dump0 = await page.evaluate(INVOICE_POPUP_DUMP_JS, 30)
    out["popup_dump_before_search"] = dump0
    await _picker_search(page, search_kw)
    dump1 = {"ok": False}
    for _ in range(15):
        dump1 = await page.evaluate(INVOICE_POPUP_DUMP_JS, 30)
        if dump1.get("grid") and not dump1["grid"].get("err"):
            break
        await page.wait_for_timeout(300)
    out["popup_dump_after_search"] = dump1
    rows = (dump1.get("grid") or {}).get("rows") or []
    idx, row = _pick_row_by_text(rows, search_kw)
    if idx is None:
        # 검색결과가 0/무매칭이면 0행이라도 폴백 시도(단건으로 좁혀졌을 가능성) — 실패시 그대로 보고.
        if len(rows) == 1:
            idx, row = 0, rows[0]
        else:
            await page.evaluate(js_lib.PICKER_CLOSE_JS)
            return {**out, "ok": False, "reason": f"'{search_kw}' 텍스트 매칭 행을 찾지 못함(후보 {len(rows)}건)"}
    out["picked_row"] = {"index": idx, "row": row}
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, idx)
    out["select"] = sel
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        return {**out, "ok": False, "reason": "'적용' 버튼을 찾지 못함"}
    await mouse_click(page, apply_box["x"], apply_box["y"])
    await page.wait_for_timeout(1_000)
    # 부수 확인 다이얼로그("확인") 처리 — preissue/exempt 녹화 관례.
    confirm_box = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
    if confirm_box:
        await mouse_click(page, confirm_box["x"], confirm_box["y"])
        await page.wait_for_timeout(500)
    await page.evaluate(ROW_SCROLL_JS, row_label)
    await page.wait_for_timeout(200)
    readback = await page.evaluate(ROW_VALUES_JS, row_label)
    out["readback"] = readback
    out["ok"] = bool(readback.get("found") and (readback.get("code") or readback.get("name")))
    if not out["ok"]:
        out["reason"] = f"'{row_label}' 적용 후 readback 이 비어있음 — {readback}"
    return out


def _attach_console_capture(raw_page: Page) -> list[dict]:
    log: list[dict] = []

    def _on_console(msg) -> None:
        try:
            log.append({"kind": "console", "type": msg.type, "text": msg.text[:300]})
        except Exception:  # noqa: BLE001
            pass

    def _on_pageerror(err) -> None:
        log.append({"kind": "pageerror", "text": str(err)[:300]})

    raw_page.on("console", _on_console)
    raw_page.on("pageerror", _on_pageerror)
    return log


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"tax_invoice_write_probe_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"tax_invoice_write_probe_{name}.png")
        await page.screenshot(path=p)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _entry(page: Page) -> None:
    base = get_settings().erp_base
    await ensure_logged_in(page, USERID, PASSWORD, base)
    await ensure_user_type(page, "회계")
    await navigate_schema(page, EXPENSE_CARD, base)
    for _ in range(20):
        if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
            break
        await page.wait_for_timeout(500)
    r = await page.evaluate(
        js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": GUBUN_LABEL},
    )
    if not r.get("ok"):
        raise RuntimeError(f"결의구분 '{GUBUN_LABEL}' 설정 실패 — {r}")
    await page.wait_for_timeout(1_800)
    await js_click(page, selectors.BTN_ADD)
    drc = -1
    for _ in range(33):
        await page.wait_for_timeout(300)
        drc = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
        if isinstance(drc, int) and drc > 0:
            break
    if not (isinstance(drc, int) and drc > 0):
        raise RuntimeError("F3 후 detail 행 생성 실패")


async def _select_evdn(page: Page, code: str) -> dict:
    """증빙유형 코드 선택 + 적용 + 뒤따르는 다이얼로그 관찰(문구 그대로 반환, 자동응답)."""
    ev: dict = {"code": code, "opened": False}
    for _attempt in range(3):
        shown = await page.evaluate(js_lib.OPEN_EVDN_EDITOR_JS)
        if not shown:
            continue
        rect = None
        waited = 0
        while waited < 1_500:
            await page.wait_for_timeout(150)
            waited += 150
            rect = await page.evaluate(js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS)
            if rect:
                break
        if not rect:
            continue
        await mouse_click(page, rect["x"], rect["y"])
        for _ in range(20):
            await page.wait_for_timeout(300)
            if await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS):
                ev["opened"] = True
                break
        if ev["opened"]:
            break
    if not ev["opened"]:
        return {**ev, "ok": False, "reason": "증빙유형 팝업이 열리지 않음"}
    sel = {"ok": False}
    for _ in range(20):
        sel = await page.evaluate(js_lib.EVDN_SELECT_BY_CODE_JS, code)
        if sel.get("ok"):
            break
        await page.wait_for_timeout(300)
    ev["select"] = sel
    if not sel.get("ok"):
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        return {**ev, "ok": False, "reason": f"증빙 {code} 선택 실패: {sel}"}
    box = await page.evaluate(js_lib.EVDN_APPLY_BOX_JS)
    if box:
        await mouse_click(page, box["x"], box["y"])
    # ⚠ attempt 1(2026-08-19) 실측: 고정 1200ms 뒤 1회 스냅샷은 22/11 둘 다 다이얼로그를
    # 놓쳤다(녹화에선 확실히 떴다) — 헤드리스가 렌더까지 더 걸릴 수 있어 최대 4.5s 폴링으로 교체.
    modals: list = []
    waited = 0
    while waited < 4_500:
        await page.wait_for_timeout(300)
        waited += 300
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        if modals:
            break
    ev["modals_after_apply"] = modals
    ev["modal_wait_ms"] = waited
    dialog_texts: list[str] = []
    for m in modals:
        dialog_texts.append(m.get("text") or m.get("title") or "")
    ev["dialog_texts"] = dialog_texts
    # 관례: 카드류 다이얼로그는 "예"를 눌러 계산서조회로 이어가거나 원증빙 확인을 수락한다.
    # 발행 전(22/23/24)은 "아니요"(계산서조회 스킵)가 관례 — 코드별 분기.
    answer = "아니요" if code in ("22", "23", "24") else "예"
    if modals:
        btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, answer)
        if not btn:
            btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "예" if answer == "아니요" else "아니요")
            answer = "예" if answer == "아니요" else "아니요"
        if btn:
            await mouse_click(page, btn["x"], btn["y"])
            ev["dialog_answer_clicked"] = answer
            await page.wait_for_timeout(800)
    ev["cell_after"] = await page.evaluate(js_lib.DETAIL_EVDN_CELL_JS)
    ev["ok"] = True
    return ev


async def _read_summary(page: Page) -> dict:
    fields = [
        "EVDN_TP_NM", "PARTNER_NM", "NOTE_DC", "BG_NM", "BGACCT_NM", "SPPRC_AMT2", "SPPRC_AMT",
        "TOTAL_AMT", "PJT_NM", "FUND_CD", "STLM_WAY_CD", "END_DT", "START_DT", "REASON_NM",
    ]
    return await page.evaluate(js_lib.GRID_CELL_VALUE_JS, {"index": 1, "field": None, "fields": fields})


# ═══════════════════════════════════════════════════════════════════════════════
# Case A — 발행 전(22) 완전 사이클
# ═══════════════════════════════════════════════════════════════════════════════
async def case_a() -> dict:
    results: dict = {"case": "A", "evdn": CASE_A_EVDN, "amount": CASE_A_AMOUNT}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    console_log = _attach_console_capture(raw_page)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    try:
        print("\n===== CASE A: 진입(login+회계+GLDDOC00300+gubun+F3) =====", flush=True)
        await _entry(page)
        await _shot(page, "a_entry")

        print("===== CASE A: 증빙유형 22 적용 + 다이얼로그 =====", flush=True)
        ev = await _select_evdn(page, CASE_A_EVDN)
        results["evdn"] = ev
        print(f"[A][evdn] {ev}", flush=True)
        if not ev.get("ok"):
            results["ok"] = False
            results["reason"] = f"증빙유형 {CASE_A_EVDN} 적용 실패: {ev.get('reason')}"
            await _shot(page, "a_evdn_fail")
            return results

        print(f"===== CASE A: 거래처({PARTNER_NAME}) =====", flush=True)
        partner = await _fill_partner_cell(page, "PARTNER_NM", PARTNER_SEARCH, PARTNER_NAME, None, "거래처")
        results["partner"] = partner
        print(f"[A][partner] {partner}", flush=True)
        if not partner.get("ok"):
            results["ok"] = False
            results["reason"] = f"거래처 채움 실패: {partner.get('reason')}"
            await _shot(page, "a_partner_fail")
            return results

        print(f"===== CASE A: 적요({CASE_A_NOTE}) =====", flush=True)
        note = await set_row_note(page, CASE_A_NOTE)
        results["note"] = note
        print(f"[A][note] {note}", flush=True)

        print("===== CASE A: 예산단위 =====", flush=True)
        bg: dict = {}
        op = await _open_detail_cell_picker(page, "BG_NM", "예산단위")
        bg["open"] = op
        if op.get("ok"):
            for kw in BUDGET_SEARCH_KEYWORDS:
                await _picker_search(page, kw)
                read = await page.evaluate(js_lib.PICKER_READ_JS, ["BG_CD", "BG_NM", 5])
                opts = read.get("options") or []
                if opts:
                    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, opts[0]["i"])
                    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
                    if apply_box:
                        await mouse_click(page, apply_box["x"], apply_box["y"])
                        await page.wait_for_timeout(1_000)
                        confirm_box = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                        if confirm_box:
                            await mouse_click(page, confirm_box["x"], confirm_box["y"])
                            await page.wait_for_timeout(500)
                    bg["picked"] = {"kw": kw, "chosen": opts[0], "select": sel}
                    break
            else:
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                bg["ok"] = False
                bg["reason"] = "예산단위 검색어 전량 무매칭"
        else:
            bg["ok"] = False
        bg.setdefault("ok", bool(bg.get("picked")))
        results["budget"] = bg
        print(f"[A][budget] ok={bg.get('ok')} picked={bg.get('picked')}", flush=True)
        await _shot(page, "a_budget")
        if not bg.get("ok"):
            results["ok"] = False
            results["reason"] = f"예산단위 채움 실패: {bg}"
            return results

        print(f"===== CASE A: 공급가액 실타이핑({CASE_A_AMOUNT}) =====", flush=True)
        amt = await type_amount(page, CASE_A_AMOUNT)
        results["amount_typed"] = amt
        print(f"[A][amount] {amt}", flush=True)
        if not amt.get("ok"):
            results["ok"] = False
            results["reason"] = f"공급가액 타이핑 실패: {amt.get('reason')}"
            await _shot(page, "a_amount_fail")
            return results

        print(f"===== CASE A: 프로젝트(WBS {PROJECT_WBS}) =====", flush=True)
        proj = await fill_project(page, {"wbsNo": PROJECT_WBS, "name": ""})
        results["project"] = proj
        print(f"[A][project] {proj}", flush=True)
        if not proj.get("ok"):
            results["ok"] = False
            results["reason"] = f"프로젝트 채움 실패: {proj.get('reason')}"
            await _shot(page, "a_project_fail")
            return results

        print(f"===== CASE A: 자금과목({FUND_SEARCH}) — 관리항목 패널 =====", flush=True)
        fund = await _fill_mgmt_item_picker(page, "자금과목", FUND_SEARCH)
        results["fund"] = fund
        print(f"[A][fund] ok={fund.get('ok')} readback={fund.get('readback')}", flush=True)
        await _shot(page, "a_fund")

        print(f"===== CASE A: 결제방법({STLM_SEARCH}) — 관리항목 패널(행라벨 '결제조건') =====", flush=True)
        stlm = await _fill_mgmt_item_picker(page, "결제조건", STLM_SEARCH)
        results["settlement_method"] = stlm
        print(f"[A][stlm] ok={stlm.get('ok')} readback={stlm.get('readback')}", flush=True)
        await _shot(page, "a_settlement_method")

        print(f"===== CASE A: 자금예정일/회계일(그리드 API, {TODAY_COMPACT}) =====", flush=True)
        settle_date = await _set_settlement_date(page, TODAY_COMPACT)
        acct_date = await page.evaluate(js_lib.SET_ACCT_DATE_JS, TODAY_COMPACT)
        results["settlement_date"] = settle_date
        results["acct_date"] = acct_date
        print(f"[A][dates] settlement={settle_date} acct={acct_date}", flush=True)

        results["pre_save_summary"] = await _read_summary(page)
        await _dump("case_a_results", results)
        await _shot(page, "a_pre_save")

        print("===== CASE A: F7 저장(게이트) =====", flush=True)
        save = await save_document(page, confirm=True)
        results["save"] = save
        print(f"[A][save] {save}", flush=True)
        await _shot(page, "a_after_save")
        results["ok"] = bool(save.get("ok"))
        if not save.get("ok"):
            results["reason"] = save.get("reason")
    except Exception as exc:  # noqa: BLE001
        results["ok"] = False
        results["error"] = f"case_a exception: {exc!r}"
        print(f"[A][ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "a_exception")
    finally:
        results["console_log"] = console_log[-40:]
        await browser.close()
        await pw.stop()
    await _dump("case_a_results", results)

    print("\n===== CASE A: 독립 재조회 검증 + F6 삭제 + 잔존 0 확인 =====", flush=True)
    vd = await erp_verify_and_delete(
        gubun_label=GUBUN_LABEL, fg_code=FG_CODE, tag="tax_invoice_writeprobe_caseA",
        pick_master=lambda rows: len(rows) - 1, want_detail=True,
    )
    results["verify_delete"] = vd
    print(f"[A][verify_delete] before={vd.get('before')} deleted={vd.get('deleted')} after={vd.get('after')} error={vd.get('error')}", flush=True)
    await _dump("case_a_results", results)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Case B — 원증빙(11) 가설 검증 + 비용분할 팝업
# ═══════════════════════════════════════════════════════════════════════════════
async def _case_b_attempt(evdn_code: str) -> dict:
    results: dict = {"case": "B", "evdn": evdn_code, "amount": CASE_B_AMOUNT}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    console_log = _attach_console_capture(raw_page)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    saved = False
    try:
        print(f"\n===== CASE B({evdn_code}): 진입 =====", flush=True)
        await _entry(page)

        print(f"===== CASE B({evdn_code}): 증빙유형 적용 + 다이얼로그 =====", flush=True)
        ev = await _select_evdn(page, evdn_code)
        results["evdn"] = ev
        print(f"[B][evdn] {ev}", flush=True)
        if not ev.get("ok"):
            results["ok"] = False
            results["reason"] = f"증빙유형 {evdn_code} 적용 실패: {ev.get('reason')}"
            return results

        print(f"===== CASE B({evdn_code}): 거래처({PARTNER_NAME}) — 신규 가설(이전 프로브 미시도) =====", flush=True)
        partner = await _fill_partner_cell(page, "PARTNER_NM", PARTNER_SEARCH, PARTNER_NAME, None, "거래처")
        results["partner"] = partner
        print(f"[B][partner] ok={partner.get('ok')} reason={partner.get('reason')}", flush=True)
        # 거래처가 이 증빙에서 아예 없는 필드일 수 있음(D5 발행후 흐름은 팝업이 채움) — 실패해도
        # 하드 중단하지 않고 계속 진행(원인 기록만).

        print(f"===== CASE B({evdn_code}): 예산단위 =====", flush=True)
        bg: dict = {}
        op = await _open_detail_cell_picker(page, "BG_NM", "예산단위")
        bg["open"] = op
        if op.get("ok"):
            for kw in BUDGET_SEARCH_KEYWORDS:
                await _picker_search(page, kw)
                read = await page.evaluate(js_lib.PICKER_READ_JS, ["BG_CD", "BG_NM", 5])
                opts = read.get("options") or []
                if opts:
                    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, opts[0]["i"])
                    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
                    if apply_box:
                        await mouse_click(page, apply_box["x"], apply_box["y"])
                        await page.wait_for_timeout(1_000)
                        confirm_box = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                        if confirm_box:
                            await mouse_click(page, confirm_box["x"], confirm_box["y"])
                            await page.wait_for_timeout(500)
                    bg["picked"] = {"kw": kw, "chosen": opts[0], "select": sel}
                    break
            else:
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
        results["budget"] = bg
        print(f"[B][budget] picked={bg.get('picked')}", flush=True)

        print(f"===== CASE B({evdn_code}): 공급가액 실타이핑({CASE_B_AMOUNT}) =====", flush=True)
        amt = await type_amount(page, CASE_B_AMOUNT)
        results["amount_typed"] = amt
        print(f"[B][amount] ok={amt.get('ok')}", flush=True)

        print(f"===== CASE B({evdn_code}): 프로젝트(WBS {PROJECT_WBS}) — 신규 가설 =====", flush=True)
        proj = await fill_project(page, {"wbsNo": PROJECT_WBS, "name": ""})
        results["project"] = proj
        print(f"[B][project] ok={proj.get('ok')} reason={proj.get('reason')}", flush=True)

        results["pre_split_summary"] = await _read_summary(page)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(800)
        await _shot(page, f"b_{evdn_code}_pre_split")

        print(f"===== CASE B({evdn_code}): '비용분할' 클릭 =====", flush=True)
        split_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "비용분할")
        results["split_button"] = split_btn
        console_before = len(console_log)
        popup_opened = False
        if split_btn and not split_btn[0].get("disabled"):
            b = (await page.evaluate(BUTTON_BY_TEXT_JS, "비용분할")) or split_btn
            b = b[0]
            await mouse_click(page, b["x"], b["y"])
            await page.wait_for_timeout(300)
            early_toasts = await page.evaluate(js_lib.VALIDATION_TOAST_JS)
            results["split_early_toasts"] = early_toasts
            for _ in range(20):
                await page.wait_for_timeout(300)
                wins = await page.evaluate(
                    "() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
                    ".map(w => (w.querySelector('.k-window-title')||{}).innerText || '')"
                )
                if any("분할처리" in w for w in wins):
                    popup_opened = True
                    break
            results["split_popup_opened"] = popup_opened
            results["console_during_click"] = console_log[console_before:]
            if not popup_opened:
                results["split_modals"] = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
                results["split_toasts"] = await page.evaluate(js_lib.VALIDATION_TOAST_JS)
                await _shot(page, f"b_{evdn_code}_split_no_popup")
                print(f"[B][split] 무반응 — modals={results['split_modals']} toasts={results['split_toasts']} console={results['console_during_click']}", flush=True)
        else:
            results["split_popup_opened"] = False
            results["reason_no_click"] = f"버튼 없음/비활성: {split_btn}"

        if not popup_opened:
            results["ok"] = False
            results["reason"] = f"증빙 {evdn_code} 상태에서 비용분할 팝업 미출현"
            return results

        # ── 팝업 열림 — team-lead 지시대로 전체 사이클 진행 ─────────────────────
        print(f"===== CASE B({evdn_code}): 분할처리 팝업 — 컬럼 덤프 =====", flush=True)
        await _shot(page, f"b_{evdn_code}_split_popup_open")
        dump0 = {"ok": False}
        for _ in range(15):
            dump0 = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
            if dump0.get("grid") and not dump0["grid"].get("err"):
                break
            await page.wait_for_timeout(300)
        results["distribution_grid_empty"] = dump0
        cols = (dump0.get("grid") or {}).get("cols") or []
        print(f"[B][split] 컬럼: {[c.get('field') for c in cols]}", flush=True)
        # 금액 필드 = 헤더에 "거래금액" 포함 컬럼(메인그리드 SPPRC_AMT2="공급가액 (거래금액)"
        # 명명관례와 동형, F7 모달 텍스트 실측에 "분할금액(거래금액)"/"분할금액" 두 헤더 확인됨 —
        # "(거래금액)" 이 붙은 쪽이 사용자입력 primary 컬럼).
        amount_field = next((c.get("field") for c in cols if "거래금액" in (c.get("header") or "")), None)
        note_field = next((c.get("field") for c in cols if (c.get("header") or "") == "적요"), None)
        results["amount_field_guess"] = amount_field
        results["note_field_guess"] = note_field
        print(f"[B][split] amount_field={amount_field} note_field={note_field}", flush=True)

        # ⚠ team-lead 지시(2026-08-19 정정) — 녹화(split L140-146) 재현: 행1만 금액 수동,
        # 행2는 금액을 건드리지 않고 **차액반영**으로 잔액을 흡수시킨다(D7 마지막행 흡수 규칙의
        # ERP 구현). 행2 의 반영 결과값이 기준금액(공급가액 vs 부가세포함 합계) 실측 데이터다.
        row1_amount = CASE_B_AMOUNT // 2  # 42000
        vat_inclusive_total = round(CASE_B_AMOUNT * 1.1)  # 92400 — 세액 10% 가정
        rows_filled: list[dict] = []

        async def _add_row_verified(label: str) -> dict:
            """'추가' 클릭 + 행수 증가 확인(최대 3회 재시도) — SKILL.md 함정 #3 대응."""
            nonlocal_res: dict = {}
            for _retry in range(3):
                add_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "추가")
                if not add_btn:
                    nonlocal_res["add_error"] = "'추가' 버튼 없음"
                    break
                before_rc = await page.evaluate(DIST_ROWCOUNT_JS)
                await mouse_click(page, add_btn[-1]["x"], add_btn[-1]["y"])
                await page.wait_for_timeout(800)
                confirm_btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                if confirm_btn:
                    await mouse_click(page, confirm_btn["x"], confirm_btn["y"])
                    await page.wait_for_timeout(600)
                rc = await page.evaluate(DIST_ROWCOUNT_JS)
                if isinstance(rc, int) and isinstance(before_rc, int) and rc > before_rc:
                    nonlocal_res["row_added"] = True
                    nonlocal_res["rowcount_after_add"] = rc
                    print(f"[B][split] {label} 추가 성공(행수 {before_rc}→{rc})", flush=True)
                    return nonlocal_res
                await page.wait_for_timeout(500)
            nonlocal_res.setdefault("row_added", False)
            print(f"[B][split] {label} 추가 실패(행수 불변) — 3회 소진", flush=True)
            return nonlocal_res

        async def _set_note(label: str, row_index: int | None) -> dict:
            if not note_field:
                return {"note_set": False, "note_error": "note_field 미확정"}
            nop = await page.evaluate(OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": note_field})
            if not nop.get("ok"):
                return {"note_set": False, "note_editor_open": nop, "note_error": f"적요 셀 에디터 오픈 실패: {nop.get('reason')}"}
            line_loc = page.locator("#GLDDOC00300_DISTRIBUTION_grid_line")
            try:
                await line_loc.wait_for(state="visible", timeout=5_000)
                await line_loc.click()
                await line_loc.fill(label)
                await page.keyboard.press("Enter")  # ⚠ attempt 4: Escape 로 바꿨더니 NOTE_DC 가
                # 커밋 안 되고 None 으로 남았다(attempt 4 실측, 회귀) — Enter(attempt 3 에서 검증됨)로 원복.
                return {"note_set": True, "note_editor_open": nop}
            except Exception as exc:  # noqa: BLE001
                return {"note_set": False, "note_editor_open": nop, "note_error": str(exc)[:200]}

        async def _set_amount(amount: int, row_index: int | None) -> dict:
            if not amount_field:
                return {"amount_set": False, "amount_error": "amount_field 미확정"}
            op = await page.evaluate(OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": amount_field})
            if not op.get("ok"):
                return {"amount_set": False, "amount_editor_open": op, "amount_error": f"셀 에디터 오픈 실패: {op.get('reason')}"}
            num_loc = page.locator("#GLDDOC00300_DISTRIBUTION_grid_number")
            try:
                await num_loc.wait_for(state="visible", timeout=5_000)
                await num_loc.click()
                await num_loc.select_text()
                await num_loc.press_sequentially(str(amount), delay=60)
                await page.keyboard.press("Tab")
                return {"amount_set": True, "amount_editor_open": op}
            except Exception as exc:  # noqa: BLE001
                return {"amount_set": False, "amount_editor_open": op, "amount_error": str(exc)[:200]}

        async def _set_picker_field(row_index: int, field: str, label: str, keyword: str) -> dict:
            """분할행의 코드피커 필드(CC_NM/PJT_NM) 채움 — showEditor+돋보기+검색+선택 0행+적용.

            team-lead 가설③: 녹화(split L149-157)는 적용 전 전 행에 비용센터·프로젝트를 채웠다 —
            지금까지 프로브는 이 두 필드를 비워둔 채 적용을 눌러 6회 실패했다(최종 라운드 대응).
            """
            out: dict = {"field": field, "row_index": row_index, "keyword": keyword}
            opened = False
            op: dict = {}
            for _attempt in range(3):
                # ⚠ 최종라운드 attempt1 실측: 행0 은 editor_open ok:true 인데도 돋보기 클릭이
                # 팝업을 못 열었다(행1은 성공) — 같은 코드가 행마다 편차 있음(타이밍 의심).
                # _open_detail_cell_picker 관례대로 **매 시도마다 에디터를 재오픈**해 재시도한다.
                op = await page.evaluate(OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": field})
                if not op.get("ok"):
                    await page.wait_for_timeout(400)
                    continue
                mag = None
                for _ in range(10):
                    mag = await page.evaluate(DIST_EDITOR_MAGNIFIER_JS)
                    if mag:
                        break
                    await page.wait_for_timeout(200)
                if not mag:
                    await page.wait_for_timeout(400)
                    continue
                before = await page.evaluate(js_lib.POPUP_COUNT_JS)
                await mouse_click(page, mag["x"], mag["y"])
                opened = bool(await verify.confirm_popup_count(page, more_than=before, timing=verify.ASYNC))
                if opened:
                    break
                await page.wait_for_timeout(400)
            out["editor_open"] = op
            if not opened:
                return {**out, "ok": False, "reason": f"{label} 피커 팝업 안 열림(3회 재시도 소진)"}
            await _picker_search(page, keyword)
            dump = {"ok": False}
            for _ in range(15):
                dump = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
                if dump.get("grid") and not dump["grid"].get("err"):
                    break
                await page.wait_for_timeout(300)
            rows = (dump.get("grid") or {}).get("rows") or []
            out["candidates_n"] = len(rows)
            if not rows:
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                return {**out, "ok": False, "reason": f"{label} 검색결과 0건(keyword={keyword!r})"}
            # WBS_NO 정확매칭 우선(프로젝트만 해당 — 메인문서 WBS "800"과 일관성), 없으면 0행 폴백.
            pick_i = 0
            for i, r in enumerate(rows):
                if str(r.get("WBS_NO") or "") == keyword:
                    pick_i = i
                    break
            sel = await page.evaluate(js_lib.PICKER_SELECT_JS, pick_i)
            out["select"] = sel
            out["picked_index"] = pick_i
            await page.wait_for_timeout(400)
            apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
            if not apply_box:
                return {**out, "ok": False, "reason": f"{label} '적용' 버튼 없음"}
            before2 = await page.evaluate(js_lib.POPUP_COUNT_JS)
            await mouse_click(page, apply_box["x"], apply_box["y"])
            closed = await verify.confirm_popup_count(page, less_than=before2, timing=verify.ASYNC)
            out["picked"] = rows[pick_i]
            out["ok"] = bool(closed)
            if not closed:
                out["reason"] = f"{label} 적용 후 피커 미닫힘"
            return out

        async def _set_main_detail_picker_field(row_index: int, field: str, label: str, keyword: str, match_text: str) -> dict:
            """**메인 detail 그리드**(분할처리 팝업 아님)의 코드피커 필드 채움 — F7 반려 원인
            진단(FEOTH_ACCT_NM="계정과목" 상대계정)을 검증하는 신규 스텝. 분할 '적용' 커밋 후
            메인 그리드에 실제로 존재하는 배부비용행(row_index=1,2)을 대상으로 한다.
            `nbkit.omnisol.js_lib.DETAIL_EDITOR_MAGNIFIER_JS`(범용 오버레이 탐지) 재사용 —
            분할처리 팝업 스코프의 `_set_picker_field`와 자매 함수(그리드만 다르다).
            """
            out: dict = {"field": field, "row_index": row_index, "keyword": keyword, "match_text": match_text}
            opened = False
            op: dict = {}
            for _attempt in range(3):
                op = await page.evaluate(OPEN_MAIN_DETAIL_CELL_EDITOR_BY_INDEX_JS, {"rowIndex": row_index, "fieldName": field})
                if not op.get("ok"):
                    await page.wait_for_timeout(400)
                    continue
                mag = None
                for _ in range(10):
                    mag = await page.evaluate(js_lib.DETAIL_EDITOR_MAGNIFIER_JS)
                    if mag:
                        break
                    await page.wait_for_timeout(200)
                if not mag:
                    await page.wait_for_timeout(400)
                    continue
                before = await page.evaluate(js_lib.POPUP_COUNT_JS)
                await mouse_click(page, mag["x"], mag["y"])
                opened = bool(await verify.confirm_popup_count(page, more_than=before, timing=verify.ASYNC))
                if opened:
                    break
                await page.wait_for_timeout(400)
            out["editor_open"] = op
            out["magnifier"] = mag if opened else None
            if not opened:
                return {**out, "ok": False, "reason": f"{label} 피커 팝업 안 열림(3회 재시도 소진)"}
            dump0 = await page.evaluate(INVOICE_POPUP_DUMP_JS, 30)
            out["popup_title"] = dump0.get("title")
            out["popup_columns"] = [c.get("field") for c in ((dump0.get("grid") or {}).get("cols") or [])]
            await _picker_search(page, keyword)
            dump = {"ok": False}
            for _ in range(15):
                dump = await page.evaluate(INVOICE_POPUP_DUMP_JS, 30)
                if dump.get("grid") and not dump["grid"].get("err"):
                    break
                await page.wait_for_timeout(300)
            rows = (dump.get("grid") or {}).get("rows") or []
            out["candidates_n"] = len(rows)
            if not rows:
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                return {**out, "ok": False, "reason": f"{label} 검색결과 0건(keyword={keyword!r})"}
            pick_i, picked_row = _pick_row_by_text(rows, match_text)
            if pick_i is None:
                pick_i, picked_row = 0, rows[0]
                out["fallback_index0"] = True
            sel = await page.evaluate(js_lib.PICKER_SELECT_JS, pick_i)
            out["select"] = sel
            out["picked_index"] = pick_i
            out["picked"] = picked_row
            await page.wait_for_timeout(400)
            apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
            if not apply_box:
                return {**out, "ok": False, "reason": f"{label} '적용' 버튼 없음"}
            before2 = await page.evaluate(js_lib.POPUP_COUNT_JS)
            await mouse_click(page, apply_box["x"], apply_box["y"])
            closed = await verify.confirm_popup_count(page, less_than=before2, timing=verify.ASYNC)
            out["ok"] = bool(closed)
            if not closed:
                out["reason"] = f"{label} 적용 후 피커 미닫힘"
            return out

        # ── team-lead 최종 레시피(녹화 대조, split L140-160) ────────────────────────
        # 1) 행1: 추가→적요→금액 수동  2) 행2: 추가→적요→실클릭 선택→차액반영(잔액 새행 생성 사양)
        # 3) 잉여 빈 행(행2, SPPRC_AMT2 미채움) 체크→삭제  4) 남은 전 행에 비용센터·프로젝트 채움
        # 5) 적용→예→확인.
        row1: dict = {"plan": {"note": "분할행1", "amount": row1_amount}}
        row1.update(await _add_row_verified("row1"))
        if row1.get("row_added"):
            row1.update(await _set_note("분할행1", 0))
            row1.update(await _set_amount(row1_amount, 0))
        rows_filled.append(row1)

        row2: dict = {"plan": {"note": "분할행2 (차액반영 대상)"}}
        row2.update(await _add_row_verified("row2"))
        if row2.get("row_added"):
            row2.update(await _set_note("분할행2", 1))
        rows_filled.append(row2)
        results["rows_filled"] = rows_filled

        dump_pre_diff = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
        results["distribution_grid_pre_diff"] = dump_pre_diff
        rows_pre_diff = (dump_pre_diff.get("grid") or {}).get("rows") or []
        uuids_pre_diff = {r.get("__UUID") for r in rows_pre_diff}
        print(f"[B][split] 차액반영 전(행1+행2) rows={rows_pre_diff}", flush=True)
        await _shot(page, f"b_{evdn_code}_split_rows_filled")
        await _dump(f"case_b_{evdn_code}_results", results)

        # 행2 실클릭 선택(attempt⑤ 검증된 좌표식) 후 차액반영.
        rect = await page.evaluate(DIST_ROW_RECT_JS, 1)
        results["row2_select_rect"] = rect
        if rect:
            await mouse_click(page, rect["x"], rect["y"])
            await page.wait_for_timeout(400)

        print(f"===== CASE B({evdn_code}): 차액반영(녹화 사양 — 새 잔액행 생성) =====", flush=True)
        diff_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "차액반영")
        if diff_btn:
            await mouse_click(page, diff_btn[-1]["x"], diff_btn[-1]["y"])
            await page.wait_for_timeout(800)
            confirm_btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
            if confirm_btn:
                await mouse_click(page, confirm_btn["x"], confirm_btn["y"])
                await page.wait_for_timeout(600)
        dump2 = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
        results["distribution_grid_after_diff"] = dump2
        results["diff_button_found"] = bool(diff_btn)
        rows_after_diff = (dump2.get("grid") or {}).get("rows") or []
        print(f"[B][split] 차액반영 후 rows={rows_after_diff}", flush=True)

        # ── team-lead 마이크로라운드 지시(순서 변경): 잉여행 정리 **전**, 차액반영이 만든
        # 잔액행(NOTE_DC 없음+SPPRC_AMT2 있음)에 적요를 먼저 채운다(이전 시도는 정리 후에
        # 채워서 실패 — 순서 민감성 검증).
        pre_cleanup_balance_idx = next(
            (i for i, r in enumerate(rows_after_diff)
             if r.get("NOTE_DC") is None and r.get("SPPRC_AMT2") not in (None, "")), None,
        )
        results["pre_cleanup_balance_idx"] = pre_cleanup_balance_idx
        if pre_cleanup_balance_idx is not None:
            note_fill_early = await _set_note("분할행2(차액반영)", pre_cleanup_balance_idx)
            results["balance_row_note_fill_before_cleanup"] = note_fill_early
            print(f"[B][split] 잔액행(idx={pre_cleanup_balance_idx}, 정리 전) 적요 채움: {note_fill_early.get('note_set')}", flush=True)

        # ── 잉여 빈 행 정리(녹화 L145-148: 차액반영 직후 체크→삭제) — SPPRC_AMT2 가 여전히
        # None 인 행(=미리 만든 빈 행2, 채워지지 않고 고아로 남는 사양)을 찾아 체크→삭제한다.
        orphan_idx = next(
            (i for i, r in enumerate(rows_after_diff) if r.get("SPPRC_AMT2") in (None, "")), None,
        )
        results["orphan_row_index"] = orphan_idx
        if orphan_idx is not None:
            cb = await page.evaluate(DIST_ROW_CHECKBOX_RECT_JS, orphan_idx)
            results["orphan_checkbox_rect"] = cb
            if cb:
                await mouse_click(page, cb["x"], cb["y"])
                await page.wait_for_timeout(400)
                del_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "삭제")
                if del_btn:
                    before_del_rc = await page.evaluate(DIST_ROWCOUNT_JS)
                    await mouse_click(page, del_btn[-1]["x"], del_btn[-1]["y"])
                    await page.wait_for_timeout(800)
                    for label in ("예", "확인"):
                        btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
                        if btn:
                            await mouse_click(page, btn["x"], btn["y"])
                            await page.wait_for_timeout(600)
                    after_del_rc = await page.evaluate(DIST_ROWCOUNT_JS)
                    results["orphan_deleted"] = isinstance(after_del_rc, int) and isinstance(before_del_rc, int) and after_del_rc < before_del_rc
                    print(f"[B][split] 잉여행(idx={orphan_idx}) 삭제: 행수 {before_del_rc}→{after_del_rc}", flush=True)
                else:
                    results["orphan_deleted"] = False
                    results["orphan_delete_error"] = "'삭제' 버튼 없음"
        else:
            print("[B][split] 잉여 빈 행 없음(차액반영이 기존 행2를 직접 채웠을 가능성) — 정리 스킵", flush=True)

        dump3 = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
        results["distribution_grid_after_cleanup"] = dump3
        rows_final = (dump3.get("grid") or {}).get("rows") or []
        print(f"[B][split] 정리 후 rows={rows_final}", flush=True)
        await _shot(page, f"b_{evdn_code}_split_after_cleanup")
        await _dump(f"case_b_{evdn_code}_results", results)

        # ── 기준금액 실측(team-lead 요청 핵심) — 차액반영이 채운 행(행1 이 아닌 나머지)의
        # SPPRC_AMT2 를 정리 후 최종값으로 읽어 공급가액 기준(42,000) vs 부가세포함 합계 기준
        # (92,400-42,000=50,400) 중 어느 쪽인지 확정.
        balance_row = next((r for r in rows_final if r.get("NOTE_DC") != "분할행1"), None)
        analysis: dict = {"row1_amount": row1_amount, "vat_inclusive_total_assumed": vat_inclusive_total}
        if balance_row is not None:
            bal_amt = balance_row.get("SPPRC_AMT2")
            analysis["balance_row_SPPRC_AMT2"] = bal_amt
            supply_basis_expect = CASE_B_AMOUNT - row1_amount  # 42000
            vat_basis_expect = vat_inclusive_total - row1_amount  # 50400
            try:
                bal_amt_num = float(bal_amt)
            except (TypeError, ValueError):
                bal_amt_num = None
            if bal_amt_num == supply_basis_expect:
                analysis["basis"] = "공급가액 합계(SPPRC_AMT2 총합) 기준"
            elif bal_amt_num == vat_basis_expect:
                analysis["basis"] = "부가세 포함 합계(TOTAL_AMT) 기준"
            else:
                analysis["basis"] = f"불확정 — 실측값 {bal_amt} (공급가액기준 기대 {supply_basis_expect} / VAT포함기준 기대 {vat_basis_expect})"
            print(f"[B][기준금액] balance_row.SPPRC_AMT2={bal_amt} → {analysis['basis']}", flush=True)
        else:
            analysis["error"] = "정리 후 잔액행을 찾지 못함"
            print(f"[B][기준금액] {analysis['error']} — rows={rows_final}", flush=True)
        results["basis_analysis"] = analysis
        # ⚠ 잔액행 적요는 이제 잉여행 정리 **전**(위 pre_cleanup_balance_idx 블록)에 이미 채웠다
        # (team-lead 마이크로라운드 지시 — 순서 변경). 정리 후 재확인만 남긴다.
        results["balance_row_note_after_cleanup"] = next(
            (r.get("NOTE_DC") for r in rows_final if r.get("NOTE_DC") != "분할행1"), None,
        )
        await _dump(f"case_b_{evdn_code}_results", results)

        # ── team-lead 가설③: 적용 전 전 행에 비용센터·프로젝트 채움(녹화 L149-157) ──────────
        print(f"===== CASE B({evdn_code}): 전 행 비용센터·프로젝트 채움(가설③) =====", flush=True)
        cc_pjt_results: list[dict] = []
        for i in range(len(rows_final)):
            cc = await _set_picker_field(i, "CC_NM", f"비용센터(행{i})", "")
            pjt = await _set_picker_field(i, "PJT_NM", f"프로젝트(행{i})", "800")
            cc_pjt_results.append({"row": i, "cc": cc, "pjt": pjt})
            print(f"[B][split] 행{i} 비용센터={cc.get('ok')}({cc.get('reason', '')}) 프로젝트={pjt.get('ok')}({pjt.get('reason', '')})", flush=True)
        results["cc_pjt_fill"] = cc_pjt_results
        dump4 = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
        results["distribution_grid_after_cc_pjt"] = dump4
        await _shot(page, f"b_{evdn_code}_split_cc_pjt_filled")
        await _dump(f"case_b_{evdn_code}_results", results)

        print(f"===== CASE B({evdn_code}): 분할 확정(적용→예→확인) =====", flush=True)
        popups_before_apply = await page.evaluate(js_lib.POPUP_COUNT_JS)
        apply_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "적용")
        if apply_btn:
            await mouse_click(page, apply_btn[-1]["x"], apply_btn[-1]["y"])
            await page.wait_for_timeout(800)
            for label in ("예", "확인"):
                btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
                if btn:
                    await mouse_click(page, btn["x"], btn["y"])
                    await page.wait_for_timeout(600)
        # ⚠ attempt 1 근본원인: 적용 클릭이 팝업을 실제로 안 닫았는데 그대로 F7 을 눌러 save_document
        # 가 "분할처리" 팝업을 반복 스캔만 하다 예/확인/닫기 버튼을 못 찾고도 ok:true 로 오판(팬텀
        # 저장, 독립검증 0건으로 확정). 팝업이 **실제로 닫혔는지**(개수 감소) 확인 못 하면 F7 자체를
        # 호출하지 않는다(SKILL.md "잔존 팝업이 F7 을 삼킨다" 대응).
        closed = await verify.confirm_popup_count(page, less_than=popups_before_apply, timing=verify.HEAVY)
        results["split_confirmed"] = bool(apply_btn)
        results["split_popup_closed_after_apply"] = bool(closed)
        await _shot(page, f"b_{evdn_code}_split_confirmed")
        if not closed:
            results["ok"] = False
            results["reason"] = f"분할처리 팝업이 '적용' 이후에도 닫히지 않음 — F7 을 호출하지 않고 중단(팬텀저장 방지). {closed.reason if hasattr(closed, 'reason') else closed}"
            results["modals_before_abort"] = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
            print(f"[B][ABORT] {results['reason']}", flush=True)
            await _dump(f"case_b_{evdn_code}_results", results)  # ⚠ attempt 1~3: try 내부 return 이
            # finally 이후의 무조건 _dump 호출을 건너뛰어 abort 상태가 파일에 안 남는 버그였다 — 여기서 직접 기록.
            return results

        # ⚠ 최종라운드 attempt2 실측(스크린샷): 적용 직후 메인 그리드에 분할행 2개가 실제로
        # 반영됐다(진행 상황: 2/2 표시) — 그런데 F7 이 modals_seen=[] 로 아무 반응 없이 끝났고
        # 독립검증 0건(팬텀). "진행 상황" 비동기 커밋이 안 끝난 채 F7 을 눌렀을 가능성 — 그
        # 프로그레스가 사라질 때까지 실시간 대기 + 중립 영역 클릭으로 포커스를 리셋한 뒤 F7.
        for _ in range(20):
            prog = await page.evaluate(
                "() => [...document.querySelectorAll('*')].some(e => e.offsetParent!==null"
                " && /진행\\s*상황/.test((e.innerText||'').slice(0,20)))"
            )
            if not prog:
                break
            await page.wait_for_timeout(300)
        await page.wait_for_timeout(1_000)  # 커밋 후 그리드 재계산 여유(실시간).
        neutral = await page.evaluate(
            "() => { const h = [...document.querySelectorAll('*')].find(e => e.offsetParent!==null"
            " && (e.innerText||'').trim()==='결의서입력'); if(!h) return null;"
            " const r = h.getBoundingClientRect(); return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }"
        )
        if neutral:
            await mouse_click(page, neutral["x"], neutral["y"])
            await page.wait_for_timeout(400)

        # ── 상대계정(FEOTH_ACCT) 해소 — 3번째·최종 가설: 관리항목 패널에 "상대"/"합계계정"
        # 라벨이 없음을 확인했다(attempt2 실측: 패널=귀속사업장·부서·사원·자금예정일·자금과목·
        # 업무용차량·건설중인자산·거래처계좌번호·**결제조건**·결제수단). FEOTH_ACCT 는 직접
        # 편집 위젯이 없는 **파생(자동계산) 필드**일 가능성 — STLM_WAY_CD(결제방법)는 이미
        # 자동 상속됐지만(외상=6) 그 파생 트리거가 "값 변경 이벤트"라 상속만으론 재계산이 안
        # 됐을 수 있다. 관리항목의 "결제조건"을 분할행마다 명시 재선택해 트리거를 유도한다.
        print(f"===== CASE B({evdn_code}): 분할행 결제조건 재선택 — 상대계정 파생 트리거 가설 =====", flush=True)
        main_rowcount = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
        results["main_rowcount_after_apply"] = main_rowcount
        feoth_results: list[dict] = []
        if isinstance(main_rowcount, int) and main_rowcount >= 3:
            for ridx in range(1, main_rowcount):
                row_res: dict = {"row_index": ridx}
                rect = await page.evaluate(
                    "(idx) => { const g = document.querySelectorAll('.dews-ui-grid')[1];"
                    " const r = g.getBoundingClientRect();"
                    " return { x: Math.round(r.x+100), y: Math.round(r.y+34+idx*32+16) }; }",
                    ridx,
                )
                await mouse_click(page, rect["x"], rect["y"])
                await page.wait_for_timeout(600)
                before_feoth = await page.evaluate(
                    "(idx) => { try { const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1])"
                    ".data('dewsControl')._grid; return String(g.getValue(idx, 'FEOTH_ACCT_CD') || ''); }"
                    " catch(e) { return null; } }", ridx,
                )
                row_res["feoth_before"] = before_feoth
                await page.evaluate(ROW_SCROLL_JS, "결제조건")
                await page.wait_for_timeout(200)
                box = await page.evaluate(ROW_BUTTON_JS, "결제조건")
                row_res["button_box"] = box
                if box:
                    popups_before_x = await page.evaluate(js_lib.POPUP_COUNT_JS)
                    await mouse_click(page, box["x"], box["y"])
                    opened_x = await verify.confirm_popup_count(page, more_than=popups_before_x, timing=verify.ASYNC)
                    row_res["popup_opened"] = bool(opened_x)
                    if opened_x:
                        dumpx = {"ok": False}
                        for _ in range(15):
                            dumpx = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
                            if dumpx.get("grid") and not dumpx["grid"].get("err"):
                                break
                            await page.wait_for_timeout(300)
                        rowsx = (dumpx.get("grid") or {}).get("rows") or []
                        row_res["candidates"] = rowsx
                        pick_ix, _ = _pick_row_by_text(rowsx, "자동이체")
                        if pick_ix is None and rowsx:
                            pick_ix = 0
                        if pick_ix is not None:
                            await page.evaluate(js_lib.PICKER_SELECT_JS, pick_ix)
                            await page.wait_for_timeout(400)
                            apply_box_x = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
                            if apply_box_x:
                                await mouse_click(page, apply_box_x["x"], apply_box_x["y"])
                                await page.wait_for_timeout(800)
                                confirm_box_x = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                                if confirm_box_x:
                                    await mouse_click(page, confirm_box_x["x"], confirm_box_x["y"])
                                    await page.wait_for_timeout(500)
                                row_res["applied"] = True
                    else:
                        row_res["reason"] = "결제조건 팝업 안 열림"
                else:
                    row_res["reason"] = "'결제조건' 관리항목 버튼 없음"
                after_feoth = await page.evaluate(
                    "(idx) => { try { const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1])"
                    ".data('dewsControl')._grid; return String(g.getValue(idx, 'FEOTH_ACCT_CD') || ''); }"
                    " catch(e) { return null; } }", ridx,
                )
                row_res["feoth_after"] = after_feoth
                row_res["feoth_changed"] = (before_feoth or "").strip() != (after_feoth or "").strip()
                print(f"[B][상대계정] idx={ridx} 결제조건 재선택 → FEOTH_ACCT_CD {before_feoth!r}→{after_feoth!r} (변화={row_res['feoth_changed']})", flush=True)
                feoth_results.append(row_res)
        else:
            print(f"[B][상대계정] 메인 detail 행수 이상({main_rowcount}) — 스킵", flush=True)
        results["feoth_acct_fill"] = feoth_results
        await _shot(page, f"b_{evdn_code}_feoth_acct_filled")
        await _dump(f"case_b_{evdn_code}_results", results)

        results["pre_save_summary"] = await _read_summary(page)
        # ⚠ 최종라운드 attempt2: 화면상 3행 전부 값이 차 보이는데도 F7 이 "상세그리드에 필수
        # 값이 입력되지 않은 항목이 있습니다"(일반 문구, 필드명 미명시)로 반려됐다 — 또 추측
        # 하지 말고 메인 detail 그리드 **원본 84+컬럼 전량**을 F7 직전에 덤프해 행별로 어느
        # 필드가 비었는지 직접 눈으로 비교한다(다음 시도의 유일한 근거가 되도록).
        main_detail_dump = await page.evaluate(
            "() => { try { const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1])"
            ".data('dewsControl')._grid; const ds = g.getDataSource(); const n = ds.getRowCount();"
            " return { n, rows: n>0 ? ds.getJsonRows(0, n-1) : [] }; } catch(e)"
            " { return { err: String(e).slice(0,150) }; } }"
        )
        results["main_detail_dump_pre_f7"] = main_detail_dump
        await _dump(f"case_b_{evdn_code}_results", results)

        print(f"===== CASE B({evdn_code}): F7 저장 =====", flush=True)
        save = await save_document(page, confirm=True)
        results["save"] = save
        print(f"[B][save] {save}", flush=True)
        await _shot(page, f"b_{evdn_code}_after_save")
        results["ok"] = bool(save.get("ok"))
        saved = bool(save.get("ok"))
        if not save.get("ok"):
            results["reason"] = save.get("reason")
        else:
            # ── 저장 직후 같은 세션에서 '비용분할' 재오픈 — 영속 구조 확인(team-lead 요청).
            # 메인 detail 그리드가 다행으로 늘었는지는 erp_verify_and_delete(별도세션)가 재확인한다 —
            # 여기서는 분할처리 팝업 자체가 저장된 2행을 그대로 보여주는지만 읽기 전용으로 본다.
            print(f"===== CASE B({evdn_code}): 저장 직후 '비용분할' 재오픈 — 영속 확인 =====", flush=True)
            reopen: dict = {}
            rb = await page.evaluate(BUTTON_BY_TEXT_JS, "비용분할")
            if rb and not rb[0].get("disabled"):
                await mouse_click(page, rb[0]["x"], rb[0]["y"])
                popup_reopened = False
                for _ in range(15):
                    await page.wait_for_timeout(300)
                    wins = await page.evaluate(
                        "() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
                        ".map(w => (w.querySelector('.k-window-title')||{}).innerText || '')"
                    )
                    if any("분할처리" in w for w in wins):
                        popup_reopened = True
                        break
                reopen["popup_reopened"] = popup_reopened
                if popup_reopened:
                    dump_reopen = {"ok": False}
                    for _ in range(15):
                        dump_reopen = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
                        if dump_reopen.get("grid") and not dump_reopen["grid"].get("err"):
                            break
                        await page.wait_for_timeout(300)
                    reopen["dump"] = dump_reopen
                    print(f"[B][reopen] 저장후 분할행 rows={ (dump_reopen.get('grid') or {}).get('rows') }", flush=True)
                    await _shot(page, f"b_{evdn_code}_reopen_after_save")
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)
            results["reopen_after_save"] = reopen
            await _dump(f"case_b_{evdn_code}_results", results)
    except Exception as exc:  # noqa: BLE001
        results["ok"] = False
        results["error"] = f"case_b({evdn_code}) exception: {exc!r}"
        print(f"[B][ERROR] {results['error']}", flush=True)
        await _shot(raw_page, f"b_{evdn_code}_exception")
    finally:
        results["console_log"] = console_log[-60:]
        await browser.close()
        await pw.stop()
    await _dump(f"case_b_{evdn_code}_results", results)

    if saved:
        print(f"\n===== CASE B({evdn_code}): 독립 재조회 검증 + F6 삭제 + 잔존 0 확인 =====", flush=True)
        vd = await erp_verify_and_delete(
            gubun_label=GUBUN_LABEL, fg_code=FG_CODE, tag=f"tax_invoice_writeprobe_caseB_{evdn_code}",
            pick_master=lambda rows: len(rows) - 1, want_detail=True,
        )
        results["verify_delete"] = vd
        print(f"[B][verify_delete] before={vd.get('before')} deleted={vd.get('deleted')} after={vd.get('after')} error={vd.get('error')}", flush=True)
        await _dump(f"case_b_{evdn_code}_results", results)
    return results


async def case_b() -> dict:
    r_primary = await _case_b_attempt(CASE_B_EVDN_PRIMARY)
    if r_primary.get("split_popup_opened"):
        return {"primary": r_primary}
    print(f"\n[B] 증빙 {CASE_B_EVDN_PRIMARY} 에서 비용분할 미열림 — 증빙 {CASE_B_EVDN_FALLBACK} 로 재시도", flush=True)
    r_fallback = await _case_b_attempt(CASE_B_EVDN_FALLBACK)
    return {"primary": r_primary, "fallback": r_fallback}


async def main() -> None:
    all_results: dict = {"userid": USERID, "delay_scale": DELAY_SCALE, "cases_run": RUN_CASES}
    if "A" in RUN_CASES:
        all_results["case_a"] = await case_a()
    if "B" in RUN_CASES:
        all_results["case_b"] = await case_b()
    await _dump("final_results", all_results)
    print("\n===== WRITE PROBE COMPLETE =====", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
