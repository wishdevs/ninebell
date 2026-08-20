"""HEADED 동반 세션 — 세금계산서 원증빙(11)+비용분할 F7 상대계정(FEOTH_ACCT) 미스터리.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 이 스크립트는 **F7(저장)·F6(삭제)를 스스로 절대 누르지 않는다** — 관련 함수(save_document·
    delete_selected 등)를 아예 import 하지 않는다(구조적 차단). 저장·삭제는 사용자가 브라우저에서
    직접 한다.
  - `headless=False` — 사람이 직접 보고 조작하는 세션. 헤드리스 프로브가 아니다.
  - 검증된 Case B 레시피(tax_invoice_write_probe.py, 2026-08-19 6회+ 라이브 확정)를 **적용→예→확인**
    까지만 자동 진행한다. 그 이후(상대계정 등 미해결 필드 채움 → F7)는 전부 사용자 조작이다.

배경(3라운드 라이브 실측, 2026-08-19): 분할행(배부비용, EVDN_CD=12)의 상대계정 필드
(FEOTH_ACCT_CD/NM)가 원본행(예 253001 "미지급금_일반")과 달리 공백으로 남아 F7 이 매번
"상세그리드에 필수 값이 입력되지 않은 항목이 있습니다"로 반려된다. 캔버스 셀 피커(FEOTH_ACCT_NM
은 visible:false 이고 대응 visible 짝 컬럼이 없어 편집 위젯 자체가 없음)·관리항목(부가선택) 패널
(라벨 목록에 상대계정류 항목 부재)·관리항목 재선택 파생 트리거 — 3가지 자동화 경로를 전부
반증했다. 이 하네스는 그 벽 앞까지 자동으로 데려다 놓고, 사람이 화면에서 직접 원인 필드를 찾아
채우는 동안 매 필드 변화를 타임스탬프와 함께 기록해 어떤 조작이 무엇을 바꿨는지 사후 추적한다.

재사용(신규 아님): `e2e.tax_invoice_write_probe`(_entry/_select_evdn/_read_summary/
_pick_row_by_text/_attach_console_capture + JS 상수 OPEN_DIST_CELL_EDITOR_JS 등 + 상수
GUBUN_LABEL/PARTNER_SEARCH/... ) · `app.agents.trip_domestic.steps`(_fill_partner_cell/
_open_detail_cell_picker/type_amount/fill_project) · `e2e.tax_invoice_split_probe`
(BUTTON_BY_TEXT_JS/INVOICE_POPUP_DUMP_JS) · `nbkit` 프리미티브 전반.
신규(이 하네스 고유): 행 채움 4개 헬퍼(원본은 tax_invoice_write_probe._case_b_attempt 안의
클로저라 page 외 상태를 캡처해 import 불가 — 동일 로직을 top-level 함수로 재작성) · 관측 루프
(스냅샷+diff, JSONL append) · 저장 성공 감지(마스터 ABDOCU_NO 등장) · Ctrl+C/브라우저 종료 처리.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/tax_invoice_headed_split_session.py
    (종료: 저장 성공/실패 관계없이 확인이 끝나면 터미널에서 Ctrl+C)

env: E2E_USERID/E2E_PASSWORD(기본 이트라이브2/1111) · TAX_INVOICE_MONITOR_INTERVAL_S(기본 4)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) ────────────────────────────────────────────────────────
from app.agents.trip_domestic.steps import (  # noqa: E402
    _fill_partner_cell,
    _open_detail_cell_picker,
    fill_project,
    type_amount,
)
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402  (뷰포트 재사용 — 좌표기반 JS 상수가 이 뷰포트에 의존)
from e2e.tax_invoice_split_probe import BUTTON_BY_TEXT_JS, INVOICE_POPUP_DUMP_JS  # noqa: E402
from e2e.tax_invoice_write_probe import (  # noqa: E402
    BUDGET_SEARCH_KEYWORDS,
    CASE_B_AMOUNT,
    DIST_EDITOR_MAGNIFIER_JS,
    DIST_ROW_CHECKBOX_RECT_JS,
    DIST_ROW_RECT_JS,
    DIST_ROWCOUNT_JS,
    OPEN_DIST_CELL_EDITOR_JS,
    PARTNER_NAME,
    PARTNER_SEARCH,
    PROJECT_WBS,
    _attach_console_capture,
    _entry,
    _pick_row_by_text,
    _select_evdn,
)
from nbkit.browser.actions import mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, verify  # noqa: E402
from nbkit.omnisol.codepicker import _picker_search  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
MONITOR_INTERVAL_S = float(os.environ.get("TAX_INVOICE_MONITOR_INTERVAL_S", "4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
JSONL_PATH = ARTIFACTS / "tax_invoice_headed_session.jsonl"

EVDN_CODE = "11"
ROW1_AMOUNT = CASE_B_AMOUNT // 2  # 42000

# team-lead 지정 관측 초점 필드(F7 반려 진단 후보) — 항상 이 필드들을 콘솔에 하이라이트한다.
FOCUS_FIELDS = [
    "FEOTH_ACCT_CD", "FEOTH_ACCT_NM", "BGACCT_FG_CD", "EVDN_MNDR_YN", "BIZR_NO_ORGN",
    "VAT_ACCT_CD", "VAT_ACCT_NM", "VAT_DRCRFG_CD",
]

# ── 신규 JS(이 하네스 고유) — 메인 detail 그리드 전 행 raw 덤프 + 마스터 핵심필드 ─────────
MAIN_DETAIL_ALL_ROWS_JS = """() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    return { ok: true, n, rows: n > 0 ? ds.getJsonRows(0, n - 1) : [] };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 150) }; }
}"""

MASTER_INFO_JS = """() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const ds = g.getDataSource();
    if (ds.getRowCount() < 1) return { ok: false, reason: 'no-master-row' };
    const row = ds.getJsonRows(0, 0)[0] || {};
    return {
      ok: true,
      ABDOCU_NO: row.ABDOCU_NO == null ? null : String(row.ABDOCU_NO),
      DOCU_NO: row.DOCU_NO == null ? null : String(row.DOCU_NO),
      ABDOCU_FG_CD: row.ABDOCU_FG_CD == null ? null : String(row.ABDOCU_FG_CD),
      WRT_EMP_NM: row.WRT_EMP_NM == null ? null : String(row.WRT_EMP_NM),
      DETAIL_SUM_AMT: row.DETAIL_SUM_AMT == null ? null : String(row.DETAIL_SUM_AMT),
    };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 150) }; }
}"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


# ══════════════════════════════════════════════════════════════════════════════
# 행 채움 헬퍼(top-level 재작성 — 원본은 tax_invoice_write_probe._case_b_attempt 의 클로저)
# ══════════════════════════════════════════════════════════════════════════════
async def add_row_verified(page: Page, label: str) -> dict:
    """'추가' 클릭 + 행수 증가 확인(최대 3회 재시도) — SKILL.md 함정#3 대응."""
    out: dict = {}
    for _retry in range(3):
        add_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "추가")
        if not add_btn:
            out["add_error"] = "'추가' 버튼 없음"
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
            out["row_added"] = True
            out["rowcount_after_add"] = rc
            print(f"[하네스][split] {label} 추가 성공(행수 {before_rc}→{rc})", flush=True)
            return out
        await page.wait_for_timeout(500)
    out.setdefault("row_added", False)
    print(f"[하네스][split] {label} 추가 실패(행수 불변) — 3회 소진", flush=True)
    return out


async def set_dist_note(page: Page, label: str, row_index: int | None) -> dict:
    nop = await page.evaluate(OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": "NOTE_DC"})
    if not nop.get("ok"):
        return {"note_set": False, "note_error": f"적요 셀 에디터 오픈 실패: {nop.get('reason')}"}
    line_loc = page.locator("#GLDDOC00300_DISTRIBUTION_grid_line")
    try:
        await line_loc.wait_for(state="visible", timeout=5_000)
        await line_loc.click()
        await line_loc.fill(label)
        await page.keyboard.press("Enter")
        return {"note_set": True}
    except Exception as exc:  # noqa: BLE001
        return {"note_set": False, "note_error": str(exc)[:200]}


async def set_dist_amount(page: Page, amount: int, row_index: int | None) -> dict:
    op = await page.evaluate(OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": "SPPRC_AMT2"})
    if not op.get("ok"):
        return {"amount_set": False, "amount_error": f"셀 에디터 오픈 실패: {op.get('reason')}"}
    num_loc = page.locator("#GLDDOC00300_DISTRIBUTION_grid_number")
    try:
        await num_loc.wait_for(state="visible", timeout=5_000)
        await num_loc.click()
        await num_loc.select_text()
        await num_loc.press_sequentially(str(amount), delay=60)
        await page.keyboard.press("Tab")
        return {"amount_set": True}
    except Exception as exc:  # noqa: BLE001
        return {"amount_set": False, "amount_error": str(exc)[:200]}


async def set_dist_picker_field(page: Page, row_index: int, field: str, label: str, keyword: str) -> dict:
    """분할행의 코드피커 필드(CC_NM/PJT_NM) 채움 — showEditor+돋보기+검색+선택+적용(3회 재시도)."""
    out: dict = {"field": field, "row_index": row_index, "keyword": keyword}
    opened = False
    for _attempt in range(3):
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
    if not rows:
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        return {**out, "ok": False, "reason": f"{label} 검색결과 0건(keyword={keyword!r})"}
    pick_i = 0
    for i, r in enumerate(rows):
        if str(r.get("WBS_NO") or "") == keyword:
            pick_i = i
            break
    await page.evaluate(js_lib.PICKER_SELECT_JS, pick_i)
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


async def _fill_budget_unit(page: Page) -> dict:
    """예산단위(BG_NM) 채움 — Case A/B 공통 인라인 로직(재사용, 원본은 tax_invoice_write_probe
    안에 두 번 인라인된 동일 코드)."""
    bg: dict = {}
    op = await _open_detail_cell_picker(page, "BG_NM", "예산단위")
    bg["open"] = op
    if not op.get("ok"):
        return {**bg, "ok": False}
    for kw in BUDGET_SEARCH_KEYWORDS:
        await _picker_search(page, kw)
        read = await page.evaluate(js_lib.PICKER_READ_JS, ["BG_CD", "BG_NM", 5])
        opts = read.get("options") or []
        if opts:
            await page.evaluate(js_lib.PICKER_SELECT_JS, opts[0]["i"])
            apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
            if apply_box:
                await mouse_click(page, apply_box["x"], apply_box["y"])
                await page.wait_for_timeout(1_000)
                confirm_box = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                if confirm_box:
                    await mouse_click(page, confirm_box["x"], confirm_box["y"])
                    await page.wait_for_timeout(500)
            bg["picked"] = {"kw": kw, "chosen": opts[0]}
            bg["ok"] = True
            return bg
    await page.evaluate(js_lib.PICKER_CLOSE_JS)
    return {**bg, "ok": False, "reason": "예산단위 검색어 전량 무매칭"}


# ══════════════════════════════════════════════════════════════════════════════
# 레시피 — 검증된 Case B 순서 그대로, "적용→예→확인" 까지만(F7 없음)
# ══════════════════════════════════════════════════════════════════════════════
async def run_recipe_to_apply(page: Page) -> dict:
    results: dict = {}
    print("===== [하네스] 진입(login+회계+GLDDOC00300+gubun+F3) =====", flush=True)
    await _entry(page)

    print(f"===== [하네스] 증빙유형 {EVDN_CODE} 적용 + 다이얼로그 =====", flush=True)
    ev = await _select_evdn(page, EVDN_CODE)
    results["evdn"] = ev
    if not ev.get("ok"):
        return {**results, "ok": False, "reason": f"증빙유형 적용 실패: {ev.get('reason')}"}

    print(f"===== [하네스] 거래처({PARTNER_NAME}) =====", flush=True)
    partner = await _fill_partner_cell(page, "PARTNER_NM", PARTNER_SEARCH, PARTNER_NAME, None, "거래처")
    results["partner"] = partner
    print(f"[하네스] 거래처: ok={partner.get('ok')}", flush=True)

    print("===== [하네스] 예산단위 =====", flush=True)
    budget = await _fill_budget_unit(page)
    results["budget"] = budget
    print(f"[하네스] 예산단위: ok={budget.get('ok')} picked={budget.get('picked')}", flush=True)

    print(f"===== [하네스] 공급가액 실타이핑({CASE_B_AMOUNT}) =====", flush=True)
    amt = await type_amount(page, CASE_B_AMOUNT)
    results["amount_typed"] = amt
    print(f"[하네스] 공급가액: ok={amt.get('ok')}", flush=True)

    print(f"===== [하네스] 프로젝트(WBS {PROJECT_WBS}) =====", flush=True)
    proj = await fill_project(page, {"wbsNo": PROJECT_WBS, "name": ""})
    results["project"] = proj
    print(f"[하네스] 프로젝트: ok={proj.get('ok')}", flush=True)

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(800)

    print("===== [하네스] '비용분할' 클릭 → 분할처리 팝업 =====", flush=True)
    split_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "비용분할")
    if not split_btn or split_btn[0].get("disabled"):
        return {**results, "ok": False, "reason": f"비용분할 버튼 없음/비활성: {split_btn}"}
    await mouse_click(page, split_btn[0]["x"], split_btn[0]["y"])
    popup_opened = False
    for _ in range(20):
        await page.wait_for_timeout(300)
        wins = await page.evaluate(
            "() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
            ".map(w => (w.querySelector('.k-window-title')||{}).innerText || '')"
        )
        if any("분할처리" in w for w in wins):
            popup_opened = True
            break
    if not popup_opened:
        return {**results, "ok": False, "reason": "분할처리 팝업 미출현"}

    print("===== [하네스] 행1: 추가→적요→금액 =====", flush=True)
    row1 = await add_row_verified(page, "row1")
    if row1.get("row_added"):
        row1.update(await set_dist_note(page, "분할행1", 0))
        row1.update(await set_dist_amount(page, ROW1_AMOUNT, 0))
    results["row1"] = row1

    print("===== [하네스] 행2: 추가→적요 =====", flush=True)
    row2 = await add_row_verified(page, "row2")
    if row2.get("row_added"):
        row2.update(await set_dist_note(page, "분할행2", 1))
    results["row2"] = row2

    print("===== [하네스] 차액반영(잔액행 자동생성) =====", flush=True)
    rect = await page.evaluate(DIST_ROW_RECT_JS, 1)
    if rect:
        await mouse_click(page, rect["x"], rect["y"])
        await page.wait_for_timeout(400)
    diff_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "차액반영")
    if diff_btn:
        await mouse_click(page, diff_btn[-1]["x"], diff_btn[-1]["y"])
        await page.wait_for_timeout(800)
        confirm_btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
        if confirm_btn:
            await mouse_click(page, confirm_btn["x"], confirm_btn["y"])
            await page.wait_for_timeout(600)

    # 잔액행 적요 채움(마이크로라운드 실측: F7 반려 사유는 아니었지만 완결성 위해 유지).
    dump_after_diff = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
    rows_after_diff = (dump_after_diff.get("grid") or {}).get("rows") or []
    balance_idx = next(
        (i for i, r in enumerate(rows_after_diff) if r.get("NOTE_DC") is None and r.get("SPPRC_AMT2") not in (None, "")),
        None,
    )
    if balance_idx is not None:
        await set_dist_note(page, "분할행2(차액반영)", balance_idx)

    print("===== [하네스] 잉여 빈 행 정리(체크→삭제) =====", flush=True)
    orphan_idx = next(
        (i for i, r in enumerate(rows_after_diff) if r.get("SPPRC_AMT2") in (None, "")), None,
    )
    results["orphan_row_index"] = orphan_idx
    if orphan_idx is not None:
        cb = await page.evaluate(DIST_ROW_CHECKBOX_RECT_JS, orphan_idx)
        if cb:
            await mouse_click(page, cb["x"], cb["y"])
            await page.wait_for_timeout(400)
            del_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "삭제")
            if del_btn:
                await mouse_click(page, del_btn[-1]["x"], del_btn[-1]["y"])
                await page.wait_for_timeout(800)
                for label in ("예", "확인"):
                    btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
                    if btn:
                        await mouse_click(page, btn["x"], btn["y"])
                        await page.wait_for_timeout(600)

    dump_final = await page.evaluate(INVOICE_POPUP_DUMP_JS, 20)
    rows_final = (dump_final.get("grid") or {}).get("rows") or []
    results["rows_final_n"] = len(rows_final)
    print(f"[하네스] 정리 후 분할행 {len(rows_final)}개", flush=True)

    print("===== [하네스] 전 행 비용센터·프로젝트 채움 =====", flush=True)
    cc_pjt: list[dict] = []
    for i in range(len(rows_final)):
        cc = await set_dist_picker_field(page, i, "CC_NM", f"비용센터(행{i})", "")
        pjt = await set_dist_picker_field(page, i, "PJT_NM", f"프로젝트(행{i})", "800")
        cc_pjt.append({"row": i, "cc": cc.get("ok"), "pjt": pjt.get("ok")})
        print(f"[하네스] 행{i} 비용센터={cc.get('ok')} 프로젝트={pjt.get('ok')}", flush=True)
    results["cc_pjt"] = cc_pjt

    print("===== [하네스] 분할 확정(적용→예→확인) =====", flush=True)
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
    closed = await verify.confirm_popup_count(page, less_than=popups_before_apply, timing=verify.HEAVY)
    results["split_popup_closed"] = bool(closed)
    if not closed:
        return {**results, "ok": False, "reason": "분할처리 팝업이 적용 이후에도 닫히지 않음"}

    # "진행 상황: N/N" 비동기 커밋 완료 대기(final round 실측 — 안 기다리면 F7 시도가 씹힘).
    for _ in range(20):
        prog = await page.evaluate(
            "() => [...document.querySelectorAll('*')].some(e => e.offsetParent!==null"
            " && /진행\\s*상황/.test((e.innerText||'').slice(0,20)))"
        )
        if not prog:
            break
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(1_000)

    results["ok"] = True
    return results


# ══════════════════════════════════════════════════════════════════════════════
# 관측 루프 — 스냅샷 + diff → JSONL append
# ══════════════════════════════════════════════════════════════════════════════
def _norm(v: object) -> str:
    return str(v) if v is not None else ""


def _diff_rows(prev_rows: list[dict] | None, cur_rows: list[dict]) -> list[dict]:
    if prev_rows is None:
        return [{"row": i, "event": "initial"} for i in range(len(cur_rows))]
    out: list[dict] = []
    n = max(len(prev_rows), len(cur_rows))
    for i in range(n):
        p = prev_rows[i] if i < len(prev_rows) else None
        c = cur_rows[i] if i < len(cur_rows) else None
        if p is None and c is not None:
            out.append({"row": i, "event": "row_added"})
            continue
        if p is not None and c is None:
            out.append({"row": i, "event": "row_removed"})
            continue
        if p is None or c is None:
            continue
        changed = {k: {"before": p.get(k), "after": c.get(k)}
                   for k in (set(p.keys()) | set(c.keys())) if _norm(p.get(k)) != _norm(c.get(k))}
        if changed:
            out.append({"row": i, "event": "changed", "fields": changed})
    return out


async def snapshot(page: Page) -> dict:
    detail = await page.evaluate(MAIN_DETAIL_ALL_ROWS_JS)
    master = await page.evaluate(MASTER_INFO_JS)
    modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
    toasts = await page.evaluate(js_lib.VALIDATION_TOAST_JS)
    return {"ts": _now_iso(), "detail": detail, "master": master, "modals": modals, "toasts": toasts}


def _append_jsonl(entry: dict) -> None:
    with JSONL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _print_focus(cur_rows: list[dict]) -> None:
    for i, r in enumerate(cur_rows):
        focus_vals = {k: r.get(k) for k in FOCUS_FIELDS}
        print(f"  [행{i}] {focus_vals}", flush=True)


async def monitor_loop(page: Page) -> dict:
    """저장 성공까지, 그 이후에도 사용자가 Ctrl+C 할 때까지 계속 관측한다."""
    prev_rows: list[dict] | None = None
    save_detected = False
    snapshot_count = 0
    first_ts = _now_iso()
    while True:
        if page.is_closed():
            print("[하네스] 브라우저 창이 닫혔습니다 — 관측 종료.", flush=True)
            break
        try:
            snap = await snapshot(page)
        except Exception as exc:  # noqa: BLE001 — 페이지 전환/닫힘 중 read 실패는 다음 루프에서 재시도.
            print(f"[하네스] 스냅샷 읽기 실패(일시적일 수 있음): {exc!r}", flush=True)
            await asyncio.sleep(MONITOR_INTERVAL_S)
            continue
        cur_rows = (snap.get("detail") or {}).get("rows") or []
        diff = _diff_rows(prev_rows, cur_rows)
        snap["diff"] = diff
        _append_jsonl(snap)
        snapshot_count += 1
        prev_rows = cur_rows
        if diff and any(d.get("event") == "changed" for d in diff):
            print(f"[하네스] {snap['ts']} — 필드 변화 감지:", flush=True)
            for d in diff:
                if d.get("event") == "changed":
                    print(f"  행{d['row']}: {d['fields']}", flush=True)
        if snap.get("toasts"):
            print(f"[하네스] 토스트: {snap['toasts']}", flush=True)
        if snap.get("modals"):
            print(f"[하네스] 모달: {[m.get('title') for m in snap['modals']]}", flush=True)

        master = snap.get("master") or {}
        if not save_detected and master.get("ok") and (master.get("ABDOCU_NO") or master.get("DOCU_NO")):
            save_detected = True
            print("\n" + "=" * 60, flush=True)
            print("[하네스] 저장 성공 감지 — 전체 상태 캡처 완료.", flush=True)
            print(f"  결의번호(ABDOCU_NO)={master.get('ABDOCU_NO')} 전표번호(DOCU_NO)={master.get('DOCU_NO')}", flush=True)
            print("  브라우저를 닫지 말고 잠시 대기해 주세요(계속 관측 중입니다).", flush=True)
            print("=" * 60 + "\n", flush=True)
            _append_jsonl({"ts": _now_iso(), "event": "save_detected", "master": master, "full_detail": cur_rows})

        await asyncio.sleep(MONITOR_INTERVAL_S)

    return {"snapshot_count": snapshot_count, "save_detected": save_detected,
            "first_ts": first_ts, "last_ts": _now_iso()}


async def main() -> None:
    if JSONL_PATH.exists():
        # 이전 세션 로그와 섞이지 않게 append 가 아니라 이번 실행 전용 파일로 시작.
        backup = JSONL_PATH.with_name(JSONL_PATH.stem + f"_{int(time.time())}.jsonl")
        JSONL_PATH.rename(backup)
        print(f"[하네스] 이전 로그를 {backup.name} 로 보관하고 새로 시작합니다.", flush=True)

    settings = get_settings()
    base = settings.erp_base
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    _attach_console_capture(raw_page)  # 콘솔/pageerror 캡처(진단 보조 — 별도 저장은 안 함, 필요시 브라우저 devtools 로 직접 확인)
    page: Page = raw_page

    summary: dict = {}
    try:
        recipe_result = await run_recipe_to_apply(page)
        _append_jsonl({"ts": _now_iso(), "event": "recipe_result", "result": recipe_result})
        if not recipe_result.get("ok"):
            print(f"\n[하네스][실패] 레시피가 '적용' 단계까지 못 갔습니다 — {recipe_result.get('reason')}", flush=True)
            print("[하네스] 그래도 브라우저는 열어두겠습니다 — 필요하면 직접 이어서 조작하세요.", flush=True)
        else:
            print("\n" + "=" * 70, flush=True)
            print("[하네스] 레시피 완료 — 분할 '적용' 까지 자동 진행됨(F7 은 누르지 않았습니다).", flush=True)
            print("이제 브라우저에서 직접 저장(F7)을 시도하세요.", flush=True)
            print("반려되면 화면에서 원인 필드를 찾아 채우고 재시도 —", flush=True)
            print("특히 상세그리드 우측 끝(상대계정 등)을 확인해 보세요.", flush=True)
            print("저장 성공까지만 하고 삭제는 하지 마세요.", flush=True)
            print("끝나면 이 터미널에서 Ctrl+C.", flush=True)
            print("=" * 70 + "\n", flush=True)

        summary = await monitor_loop(page)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[하네스] Ctrl+C 감지 — 관측을 종료합니다.", flush=True)
    finally:
        try:
            if not page.is_closed():
                await browser.close()
        except Exception:  # noqa: BLE001 — 브라우저가 이미 닫혔거나 연결이 끊긴 경우 무시.
            pass
        try:
            await pw.stop()
        except Exception:  # noqa: BLE001
            pass

    print("\n" + "=" * 70, flush=True)
    print("[하네스] 세션 요약", flush=True)
    print(f"  스냅샷 {summary.get('snapshot_count', 0)}건 기록 — {JSONL_PATH}", flush=True)
    print(f"  저장 성공 감지: {summary.get('save_detected', False)}", flush=True)
    print(f"  기간: {summary.get('first_ts', '?')} ~ {summary.get('last_ts', '?')}", flush=True)
    print("  F7/F6 은 이 스크립트가 누른 적이 없습니다 — 저장/삭제는 전부 사용자 조작입니다.", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
