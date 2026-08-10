"""HEADLESS 라이브 프로브 — 총계정원장>전표관리>전표조회승인(GLDDOC00700) 실측.

voucher_receivable(PROCESS.md) ❓ 목록 확정:
  D1 menu_id/deeplink, D2 조회 8필드 셀렉터·값 세팅 방식, D3 조회 버튼·결과그리드 컬럼·행선택,
  D5 결제(결재)창 유형(팝업/탭/모달) + 상신·취소 버튼 좌표 + 취소 비영속 여부.

⚠⚠ 절대 안전 ⚠⚠
  - 실제 상신(전자결재 상신) 절대 클릭 금지. F7 저장·F6 삭제도 금지.
  - Phase B 는 결제창(전자결재 팝업)을 **열어서 관찰만** 하고 상신/보관 버튼을 누르지 않고
    **창을 닫는다**(비영속 확인 목적). 상신/보관은 절대 클릭하지 않는다.
  - Phase A(조회까지)는 완전 읽기전용(부작용 0). Phase B 는 결제창 오픈+닫기만(전표 상태
    비변경을 재조회로 검증) — 결제창 내부에서는 관찰 외 어떤 클릭도 하지 않는다.

재사용(신규 작성 아님): nbkit.patterns.login_flow/user_type_flow/menu_navigate_flow,
nbkit.omnisol.menu_schemas.VOUCHER_RECEIVABLE(본 프로브로 신규 등록), nbkit.omnisol.js_lib
(KENDO_SET_DROPDOWN_BY_TEXT_JS/ROWCOUNT_BY_INDEX_JS), nbkit.omnisol.selectors.BTN_LOOKUP,
nbkit.browser.actions(mouse_click/js_click), app.live.runner(LIVE_VIEWPORT/_ScaledPage).

신규(이 화면 고유 — 결의서입력에 없던 위젯): 조회 조건 패널의 dews MultiCodePicker/CodePicker/
PeriodPicker 위젯을 잡는 라벨-근접 탐색 JS(FIELD_BTN_RECT_JS), MultiCodePicker 팝업(RealGrid
checkbox 컬럼) 체크+적용 JS(POPUP_CHECK_AND_LIST_JS), 결제(결재) 버튼 클릭 후 새 Page(팝업윈도우)
감지·닫기 로직.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_receivable_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# D2 조회 조건 목표값.
DEPT_ALL = "작성부서"  # 전체선택(전체 부서 checkAll)
GWAPRVLST_TARGET = "저장"
DOCU_ST_TARGET = "미결"
DOCU_TYPE_TARGETS = ["국내매출", "해외매출"]

# ── 신규 in-page JS(이 화면 고유 위젯: dews MultiCodePicker/CodePicker) ─────────────
# 라벨 텍스트로 그 필드의 '검색(돋보기)' dews-multicodepicker-button 좌표를 찾는다(신규 —
# 결의서입력엔 없던 위젯 종류). 같은 li 안에서 두 번째 버튼(1번=화살표 드롭다운, 2번=돋보기).
FIELD_SEARCH_BTN_RECT_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label')].find(e => c(e.innerText) === label);
  if (!lbl) return null;
  const li = lbl.closest('li');
  const btns = [...li.querySelectorAll('.dews-multicodepicker-button')];
  const btn = btns[1] || btns[0];
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 마지막(최상단) k-window 팝업의 RealGrid에서 지정 필드값과 일치하는 행을 checkRow(신규 —
# 이 팝업은 card_collect 의 PICKER_* 와 다른 위젯: 단일 선택 아니라 RealGrid checkbox 컬럼).
# arg = [targets(문자열 배열), fieldName]. 반환 [{t, idx}] — 매칭 못한 target 은 빠짐.
POPUP_CHECK_ROWS_JS = r"""([targets, fieldName]) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-popup' };
  const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
  const ds = g.getDataSource();
  const n = ds.getRowCount();
  const rows = ds.getJsonRows(0, n - 1);
  const idxs = [];
  for (const t of targets) {
    const idx = rows.findIndex(r => String(r[fieldName]).trim() === t);
    if (idx >= 0) { g.checkRow(idx, true); idxs.push({ t, idx, code: rows[idx][fieldName.replace('_NM', '_CD')] }); }
  }
  return { ok: true, idxs, n };
}"""

# 팝업의 checkAll(부서 전체선택 전용 — checkbox 컬럼 헤더 체크와 동일 효과).
POPUP_CHECK_ALL_JS = r"""() => {
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false };
  const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
  g.checkAll();
  return { ok: true, n: g.getDataSource().getRowCount() };
}"""

# 마지막 k-window 팝업의 '적용' 버튼 좌표.
POPUP_APPLY_BTN_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return null;
  const b = [...dlg.querySelectorAll('button')].find(x => c(x.innerText) === '적용');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 조회조건 패널 확장(▲/▼) 토글 좌표(전표유형 필드가 optional-area 라 펼쳐야 보임).
EXPAND_TOGGLE_RECT_JS = r"""() => {
  const b = document.querySelector('.dews-condition-panel-expand-button');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 필드 표시값(멀티코드피커 text input) 읽기 — 검증용.
FIELD_DISPLAY_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label')].find(e => c(e.innerText) === label);
  if (!lbl) return null;
  const li = lbl.closest('li');
  const inp = li.querySelector('.dews-multicodepicker-text, .dews-codepicker-text');
  return inp ? inp.value : null;
}"""

# 결과 마스터 그리드(index 0) 컬럼+rowcount+상위 N행 덤프.
MASTER_DUMP_JS = r"""(limit) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const cols = g.getColumns().map(c => ({ field: c.fieldName, header: (c.header && c.header.text) || c.name }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(n, limit || 5);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, n, cols, sample: rows };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""

# 특정 DOCU_NO 행의 상태 필드만 재조회(비영속 검증용).
FIND_ROW_STATUS_JS = r"""(docuNo) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = ds.getJsonRows(0, n - 1);
    const row = rows.find(r => r.DOCU_NO === docuNo);
    if (!row) return { ok: false, reason: 'not-found' };
    return { ok: true, DOCU_ST_NM: row.DOCU_ST_NM, GWAPRVLST_NM: row.GWAPRVLST_NM, DOCU_NO: row.DOCU_NO };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""

# 결제(결재) 버튼 좌표 — button.main-button.approval, innerText='결재'(신규: BTN_SAVE 처럼
# selectors.py 상수화할 값이지만 이 프로브 단계에선 확정 전이라 로컬 상수로 둔다).
APPROVAL_BTN_RECT_JS = r"""() => {
  const b = document.querySelector('button.main-button.approval');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 결제창(전자결재 팝업, 새 Page) 상단 버튼(미리보기/보관/상신) 좌표 — 텍스트 리프노드 탐색.
CHILD_TOP_BUTTONS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const targets = ['상신', '미리보기', '보관'];
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    const t = c(el.innerText || el.textContent || '');
    if (targets.includes(t)) {
      const r = el.getBoundingClientRect();
      out.push({ text: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), visible: el.offsetParent !== null });
    }
  }
  return out;
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"voucher_receivable_probe_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str, *, full_page: bool = True) -> None:
    try:
        p = str(ARTIFACTS / f"voucher_receivable_probe_{name}.png")
        await page.screenshot(path=p, full_page=full_page)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _picker_check_and_apply(raw_page, page, targets: list[str], field: str = "SYSDEF_NM") -> dict:
    """돋보기로 연 MultiCodePicker 팝업에서 targets 를 체크→적용. 팝업은 apply 후 자동 닫힘."""
    res = await raw_page.evaluate(POPUP_CHECK_ROWS_JS, [targets, field])
    apply_rect = await raw_page.evaluate(POPUP_APPLY_BTN_JS)
    if apply_rect:
        await mouse_click(page, apply_rect["x"], apply_rect["y"])
        await page.wait_for_timeout(1_200)
    return res


async def main() -> None:
    results: dict = {"userid": USERID, "menu": VOUCHER_RECEIVABLE.key, "delay_scale": DELAY_SCALE}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    context = await browser.new_context(viewport=LIVE_VIEWPORT)
    raw_page = await context.new_page()
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    new_pages: list = []
    context.on("page", lambda p: new_pages.append(p))

    try:
        # ── 진입: login → 회계 → 전표조회승인(D1, 신규 등록 MenuSchema) ────────────
        print("[entry] login + user_type(회계) + menu_nav(GLDDOC00700)…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, base)
        await page.wait_for_timeout(1_500)
        await _shot(raw_page, "entry")
        results["D1"] = {"menu_id": VOUCHER_RECEIVABLE.menu_id, "deeplink": VOUCHER_RECEIVABLE.deeplink,
                          "entry_ok": True, "url": raw_page.url}
        await _dump("results", results)

        # ── D2: 조회조건 패널 펼치기(전표유형 optional-area) ────────────────────────
        toggle = await raw_page.evaluate(EXPAND_TOGGLE_RECT_JS)
        if toggle:
            await mouse_click(page, toggle["x"], toggle["y"])
            await page.wait_for_timeout(1_000)
        await _shot(raw_page, "d2_expanded")

        # ── D2-1: 작성부서 = 전체선택(checkAll) ─────────────────────────────────
        print("\n===== D2: 작성부서=전체선택 =====", flush=True)
        rect = await raw_page.evaluate(FIELD_SEARCH_BTN_RECT_JS, DEPT_ALL)
        await mouse_click(page, rect["x"], rect["y"])
        await page.wait_for_timeout(1_200)
        await raw_page.evaluate(POPUP_CHECK_ALL_JS)
        apply_rect = await raw_page.evaluate(POPUP_APPLY_BTN_JS)
        await mouse_click(page, apply_rect["x"], apply_rect["y"])
        await page.wait_for_timeout(1_200)
        dept_val = await raw_page.evaluate(FIELD_DISPLAY_JS, "작성부서")
        print(f"[D2] 작성부서 = {dept_val!r}", flush=True)

        # ── D2-2: 회계일 = 당월(dews periodpicker 앱 API setMonth) ──────────────
        await raw_page.evaluate(
            "() => window.jQuery(document.querySelector('#s_period')).data('dewsControl').setMonth()"
        )
        period_val = await raw_page.evaluate(
            "() => document.querySelector('#s_period_startinput').value + '~' + "
            "document.querySelector('#s_period_endinput').value"
        )
        print(f"[D2] 회계일 = {period_val!r}", flush=True)

        # ── D2-3: 작성자 = 비움(dews multicodepicker 앱 API clear) ──────────────
        await raw_page.evaluate(
            "() => window.jQuery(document.querySelector('#s_wrt_emp_no')).data('dewsControl').clear()"
        )
        writer_val = await raw_page.evaluate(FIELD_DISPLAY_JS, "작성자")
        print(f"[D2] 작성자 = {writer_val!r}", flush=True)

        # ── D2-4: 전표상태 = 미결(native kendo dropdownlist — 기존 KENDO_SET_DROPDOWN_BY_TEXT_JS 재사용) ─
        r1 = await raw_page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": "#s_docu_st_cd", "text": DOCU_ST_TARGET}
        )
        print(f"[D2] 전표상태 set -> {r1}", flush=True)

        # ── D2-5: 전자결재상태 = 저장(MultiCodePicker 팝업 RealGrid checkRow) ───
        rect = await raw_page.evaluate(FIELD_SEARCH_BTN_RECT_JS, "전자결재상태")
        await mouse_click(page, rect["x"], rect["y"])
        await page.wait_for_timeout(1_200)
        gwap_res = await _picker_check_and_apply(raw_page, page, [GWAPRVLST_TARGET])
        print(f"[D2] 전자결재상태 checked -> {gwap_res}", flush=True)

        # ── D2-6: 전표유형 = 국내매출+해외매출(MultiCodePicker 팝업, 다중 checkRow) ─
        rect = await raw_page.evaluate(FIELD_SEARCH_BTN_RECT_JS, "전표유형")
        await mouse_click(page, rect["x"], rect["y"])
        await page.wait_for_timeout(1_200)
        docu_res = await _picker_check_and_apply(raw_page, page, DOCU_TYPE_TARGETS)
        print(f"[D2] 전표유형 checked -> {docu_res}", flush=True)

        # ── D2 검증: 8필드 최종 표시값 스냅샷 ─────────────────────────────────────
        final_vals = await raw_page.evaluate(r"""() => {
          const val = (sel) => { const e = document.querySelector(sel); return e ? e.options[e.selectedIndex].text : null; };
          return {
            회계단위: document.querySelector('#s_pc_cd_text').value,
            역분개여부: val('#s_revjrnz_yn'),
            전표상태: val('#s_docu_st_cd'),
          };
        }""")
        results["D2"] = {
            "회계단위": final_vals["회계단위"],
            "작성부서": dept_val,
            "회계일": period_val,
            "작성자": writer_val,
            "역분개여부": final_vals["역분개여부"],
            "전표상태": final_vals["전표상태"],
            "전자결재상태": gwap_res,
            "전표유형": docu_res,
            "field_controls": {
                "회계단위": "dews-codepicker(단일값, id=s_pc_cd/#s_pc_cd_text) — 기본값 (주)나인벨 유지, 변경 불필요",
                "작성부서": "dews-multicodepicker(id=s_wdept_cd) — 팝업 RealGrid checkAll()+적용",
                "회계일": "dews-periodpicker(id=s_period) — dewsControl.setMonth() 앱 API(당월=1일~말일 자동)",
                "전표번호": "plain input(#s_docu_no) — 미사용(빈칸 유지)",
                "작성자": "dews-multicodepicker(id=s_wrt_emp_no) — dewsControl.clear() 앱 API",
                "역분개여부": "kendo dropdownlist(select#s_revjrnz_yn) — 기본값 전체(value='') 유지",
                "전표상태": "kendo dropdownlist(select#s_docu_st_cd) — KENDO_SET_DROPDOWN_BY_TEXT_JS({selector:'#s_docu_st_cd',text:'미결'})",
                "전자결재상태": "dews-multicodepicker(id=s_gwaprvlst_cd, module_cd=MA field_cd=P01300) — 팝업 RealGrid checkRow(SYSDEF_NM='저장')+적용. 코드=1",
                "전표유형": "dews-multicodepicker(id=s_docu_cd, module_cd=MA field_cd=P00620, optional-area) — 팝업 checkRow(국내매출=21,해외매출=23)+적용",
            },
        }
        await _shot(raw_page, "d2_filled")
        await _dump("results", results)

        # ── D3: 조회(F2) → 결과 그리드 ───────────────────────────────────────────
        print("\n===== D3: 조회 실행 =====", flush=True)
        await js_click(page, selectors.BTN_LOOKUP)
        rc = -1
        for _ in range(30):
            await page.wait_for_timeout(400)
            rc = await raw_page.evaluate(js_lib.ROWCOUNT_BY_INDEX_JS, 0)
            if isinstance(rc, int) and rc >= 0:
                break
        print(f"[D3] master rowcount = {rc}", flush=True)
        dump = await raw_page.evaluate(MASTER_DUMP_JS, 5)
        results["D3"] = {
            "lookup_btn_selector": selectors.BTN_LOOKUP,
            "lookup_btn_shortcut": "F2",
            "master_rowcount": rc,
            "master_columns": dump.get("cols"),
            "sample_row0": (dump.get("sample") or [None])[0],
            "row_select_mechanism": "grid.checkRow(idx,true)(checkbox 컬럼, __UUID 필드) 또는 setCurrent(체크와 무관, 파랑 하이라이트/디테일 연동)",
            "detail_grid_index": 1,
            "detail_grid_note": "마스터 행 클릭(setCurrent/checkRow와 무관) 시 하단 계정정보 디테일 그리드 자동 연동(결의서입력과 동일 마스터-디테일 패턴)",
        }
        await _shot(raw_page, "d3_results")
        await _dump("results", results)

        if not isinstance(rc, int) or rc <= 0:
            print("[FATAL] 조회 결과 0건 — Phase B(결제창) 스킵. 원인분류: 데이터없음(업무전제 확인필요).", flush=True)
            await _dump("results", results)
            return

        # ══════════════════════════════════════════════════════════════════════
        # Phase B — 결제(결재)창 유형 확정. 1건만 선택→결제 버튼→관찰→닫기.
        # ⚠ 상신/보관 버튼 절대 클릭 금지. 관찰 후 창을 닫아 비영속 확인만 한다.
        # ══════════════════════════════════════════════════════════════════════
        print("\n===== Phase B: 결제(결재)창 유형 확정 =====", flush=True)
        row0_before = await raw_page.evaluate(
            "() => { const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0])"
            ".data('dewsControl')._grid; const r = g.getDataSource().getJsonRows(0,0)[0]; "
            "return { DOCU_NO: r.DOCU_NO, DOCU_ST_NM: r.DOCU_ST_NM, GWAPRVLST_NM: r.GWAPRVLST_NM }; }"
        )
        print(f"[PhaseB] target row (before) = {row0_before}", flush=True)

        # 행 선택: 체크박스(checkRow) — D4 "체크/클릭 ❓" 확정: checkRow 로 체크해야 결제 버튼이
        # 그 행을 대상으로 인식한다(결제 버튼 자체는 disabled 속성으로 gate 하지 않으므로, 대상
        # 문서를 명확히 하려면 checkRow 가 필요 — setCurrent 만으로는 대상 모호).
        await raw_page.evaluate(
            "() => { const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0])"
            ".data('dewsControl')._grid; g.setCurrent({itemIndex:0, fieldName: g.getColumns()[1].fieldName}); "
            "g.checkRow(0, true); }"
        )
        await page.wait_for_timeout(500)
        await _shot(raw_page, "phaseb_row_checked")

        approval_rect = await raw_page.evaluate(APPROVAL_BTN_RECT_JS)
        results["D5"] = {"approval_btn_selector": "button.main-button.approval", "approval_btn_text": "결재",
                          "approval_btn_rect": approval_rect}
        print(f"[PhaseB] 결제(결재) 버튼 @ {approval_rect} — 클릭…", flush=True)
        await mouse_click(page, approval_rect["x"], approval_rect["y"])
        await page.wait_for_timeout(2_000)

        if not new_pages:
            print("[PhaseB] 새 Page 미감지 — 인페이지 모달일 가능성. 모달 스냅샷 확인.", flush=True)
            modal = await raw_page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
            results["D5"]["window_type"] = "unknown(no-new-page)"
            results["D5"]["inpage_modal_snapshot"] = modal
            await _shot(raw_page, "phaseb_no_child")
            await _dump("results", results)
            return

        child = new_pages[-1]
        print(f"[PhaseB] 새 Page 감지(별도 팝업 윈도우) url(초기) = {child.url}", flush=True)
        try:
            await child.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            print(f"[PhaseB] child networkidle 대기 실패(계속 진행): {exc!r}", flush=True)
        # 고정 settle 대신 조건 폴링(상단 버튼 렌더 완료까지) — EAP(전자결재) SPA 는 SSO 리다이렉트
        # 2회 + micro-frontend 마운트로 렌더 완료 시점이 9~20s 사이로 변동(실측 편차 큼).
        top_btns: list[dict] = []
        waited_ms = 0
        while waited_ms < 25_000:
            await child.wait_for_timeout(1_000)
            waited_ms += 1_000
            try:
                top_btns = await child.evaluate(CHILD_TOP_BUTTONS_JS)
            except Exception:  # noqa: BLE001 — child 아직 네비게이션 중일 수 있음
                top_btns = []
            if top_btns:
                break
        print(f"[PhaseB] child 최종 url = {child.url} (렌더 대기 {waited_ms}ms)", flush=True)
        print(f"[PhaseB] 결제창 상단 버튼(폴링 완료) = {top_btns}", flush=True)
        await child.screenshot(path=str(ARTIFACTS / "voucher_receivable_probe_child_window.png"), full_page=True)
        print(f"[shot] {ARTIFACTS / 'voucher_receivable_probe_child_window.png'}", flush=True)

        results["D5"]["window_type"] = "popup(separate browser Page via window.open, cross-origin)"
        results["D5"]["child_url_final"] = child.url
        results["D5"]["child_render_wait_ms_observed"] = waited_ms  # 실측 편차 큼(7~20s+) — 조건폴링 필수, 고정 settle 금지
        results["D5"]["child_top_buttons"] = top_btns
        results["D5"]["submit_btn"] = next((b for b in top_btns if b["text"] == "상신"), None)
        results["D5"]["preview_btn"] = next((b for b in top_btns if b["text"] == "미리보기"), None)
        results["D5"]["archive_btn"] = next((b for b in top_btns if b["text"] == "보관"), None)
        results["D5"]["note"] = (
            "결제창은 옴니솔(erp.ninebell.co.kr)이 아니라 별도 전자결재 시스템(uc.ninebell.co.kr, "
            "SSO 경유)의 독립 브라우저 창이다. 인페이지 모달/iframe 아님 — Playwright "
            "context.on('page') 로 감지해야 한다. 명시적 취소/닫기 버튼이 창 안에 없다 — "
            "취소는 이 창을 그냥 닫는 것(비영속, 상신/보관을 누르지 않는 한 아무것도 저장되지 않음)."
        )

        # ⚠⚠ 상신/보관 버튼 절대 클릭 금지 — 관찰만 하고 창을 닫는다(비영속 확인) ⚠⚠
        print("[PhaseB] 상신/보관 클릭 금지 — 관찰 완료, 창을 닫는다(비영속 검증)…", flush=True)
        await child.close()
        await page.wait_for_timeout(1_000)

        # 부모 화면으로 복귀 확인 + 재조회로 비영속(상태 불변) 검증.
        await _shot(raw_page, "phaseb_after_child_close")
        await js_click(page, selectors.BTN_LOOKUP)
        rc2 = -1
        for _ in range(30):
            await page.wait_for_timeout(400)
            rc2 = await raw_page.evaluate(js_lib.ROWCOUNT_BY_INDEX_JS, 0)
            if isinstance(rc2, int) and rc2 >= 0:
                break
        row0_after = await raw_page.evaluate(FIND_ROW_STATUS_JS, row0_before["DOCU_NO"])
        print(f"[PhaseB] re-query rowcount={rc2}, target row (after close, no submit) = {row0_after}", flush=True)
        results["D5"]["persistence_check"] = {
            "before": row0_before,
            "after_close_requery": row0_after,
            "unchanged": bool(
                row0_after.get("ok")
                and row0_after.get("DOCU_ST_NM") == row0_before["DOCU_ST_NM"]
                and row0_after.get("GWAPRVLST_NM") == row0_before["GWAPRVLST_NM"]
            ),
        }
        await _dump("results", results)

        print("\n===== PROBE COMPLETE (상신/저장/삭제 없음, 결제창 관찰 후 닫기만) =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        await browser.close()
        await pw.stop()

    print("\n===== FINAL RESULTS SUMMARY =====", flush=True)
    print(json.dumps({k: (v if not isinstance(v, dict) else "…") for k, v in results.items()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
