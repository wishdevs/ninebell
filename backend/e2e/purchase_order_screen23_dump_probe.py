"""HEADLESS 읽기전용(부작용 0에 준함) 프로브 — Task B/C/D: 화면②·③ 랜딩 구조 전량 덤프
+ 메뉴 트리에서 '구매발주처리[나인벨]' 확인.

omnisol-flow-prober 위임(2026-08-25, purchase_order PROCESS.md 화면②·③ 실측). 기존
purchase_order_{discover,menu_entry}_probe.py 의 스캔 JS 패턴(SCAN_MENU_JS·DUMP_FORM_FIELDS_JS·
GRID_INFO_JS)을 재사용하고, 화면②·③ 전용 덤프(라벨 li 스니펫·코드피커 wrapper·아이콘 버튼·탭)만
새로 추가했다.

⛔ 안전 경계:
  - 화면③(`PUOORD02000_X20616`)은 **완전 랜딩 상태 그대로 덤프** — 클릭·입력 0건.
    `구매요청` 버튼은 셀렉터만 잡고 절대 클릭하지 않는다.
  - 화면②(`PUOPRQ00300_X20616`)은 랜딩 덤프 + 하위 탭 전환(품목/거래처/계정/발주, 허용) +
    공장='나인벨' 코드피커 채움 + 조회(F2, 둘 다 미션에서 명시 허용된 '읽기' 동작)까지만.
    저장(F7)·요청취소·요청마감·마감취소·상신·결재 버튼은 존재를 기록만 하고 클릭 금지.
  - 메뉴 스캔(Task D)은 사이드바 DOM 을 읽기만 한다(클릭 없음).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_screen23_dump_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.purchase_order import js as po_js  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.omnisol import codepicker, js_lib  # noqa: E402
from nbkit.omnisol.errors import MenuError  # noqa: E402
from nbkit.omnisol.navigator import navigate_menu  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DEEPLINK_SCREEN2 = "/PU/PUOPRQ00300_X20616"
LABEL_SCREEN2 = "구매요청처리[나인벨]"
DEEPLINK_SCREEN3 = "/PU/PUOORD02000_X20616"
LABEL_SCREEN3 = "구매발주일괄입력[나인벨]"

# ── Task D: 메뉴 트리 스캔(purchase_order_discover_probe.py SCAN_MENU_JS 그대로 재사용) ──
SCAN_MENU_JS = r"""(keywords) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  const seen = new Set();
  for (const kw of keywords) {
    const els = [...document.querySelectorAll('a,button,span,div,li,td,i,img,[role=menuitem],[role=treeitem]')]
      .filter(e => {
        const t = c(e.innerText || e.textContent || '');
        const title = c(e.getAttribute && e.getAttribute('title'));
        const alt = c(e.getAttribute && e.getAttribute('alt'));
        return (t === kw || title === kw || alt === kw || t.includes(kw));
      });
    for (const e of els) {
      if (seen.has(e)) continue;
      seen.add(e);
      const r = e.getBoundingClientRect();
      out.push({
        kw,
        tag: e.tagName,
        text: c(e.innerText || e.textContent || '').slice(0, 60),
        id: e.id || '',
        cls: (e.className || '').toString().slice(0, 120),
        href: e.getAttribute ? (e.getAttribute('href') || '') : '',
        visible: e.offsetParent !== null,
      });
    }
  }
  return out;
}"""

# ── 라벨 필드 전량 덤프(공용) — outerHTML 스니펫 포함(required 클래스·id 판정을 사후에
#    증거 기반으로 하기 위함, 가정으로 하드코딩하지 않음). ──
DUMP_LABELED_FIELDS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  const labels = [...document.querySelectorAll('label')].filter(l => l.offsetParent !== null);
  for (const lbl of labels) {
    const text = c(lbl.innerText);
    if (!text) continue;
    const li = lbl.closest('li') || lbl.closest('div') || lbl.closest('td') || lbl.parentElement;
    if (!li) continue;
    const wrapper = li.querySelector('[id$="-wrapper"]');
    const codepickerText = li.querySelector('.dews-multicodepicker-text, .dews-codepicker-text');
    const checkbox = li.querySelector('input[type=checkbox]');
    const select = li.querySelector('select');
    const anyInput = li.querySelector('input');
    out.push({
      label: text,
      liClassName: (li.className || '').toString().slice(0, 150),
      wrapperId: wrapper ? wrapper.id : null,
      hasCodepickerText: !!codepickerText,
      codepickerValue: codepickerText ? codepickerText.value : null,
      hasCheckbox: !!checkbox,
      hasSelect: !!select,
      selectValue: select ? (select.options[select.selectedIndex] || {}).text : null,
      anyInputId: anyInput ? anyInput.id : null,
      anyInputValue: anyInput ? anyInput.value : null,
      anyInputReadonly: anyInput ? anyInput.readOnly : null,
      liHtmlSnippet: li.outerHTML.replace(/\s+/g, ' ').slice(0, 500),
    });
  }
  return out;
}"""

# 코드피커 wrapper 전량 — id 규칙(#{field_id}-wrapper)으로 field_id 를 역산(codepicker._open_picker 용).
DUMP_CODEPICKER_FIELDS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wrappers = [...document.querySelectorAll('[id$="-wrapper"]')].filter(e => e.offsetParent !== null);
  return wrappers.map(w => {
    const li = w.closest('li') || w.closest('div') || w.closest('td');
    const lbl = li ? li.querySelector('label') : null;
    return {
      wrapperId: w.id,
      fieldId: w.id.replace(/-wrapper$/, ''),
      label: lbl ? c(lbl.innerText) : null,
      hasBtn: !!w.querySelector('.dews-codepicker-button'),
    };
  });
}"""

# 버튼 + title/aria-label 요소 전량(툴바 버튼 + 우측 상단 아이콘) — 텍스트/id/class/title/aria/disabled.
DUMP_TOOLBAR_ICON_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const seen = new Set();
  const out = [];
  const els = [...document.querySelectorAll('button, [title], [aria-label]')].filter(e => e.offsetParent !== null);
  for (const e of els) {
    if (seen.has(e)) continue;
    seen.add(e);
    const r = e.getBoundingClientRect();
    out.push({
      tag: e.tagName,
      id: e.id || '',
      cls: (e.className || '').toString().slice(0, 150),
      text: c(e.innerText).slice(0, 30),
      title: e.getAttribute('title') || '',
      aria: e.getAttribute('aria-label') || '',
      disabled: !!e.disabled,
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    });
  }
  return out;
}"""

# 그리드 전량 컬럼 fieldName — purchase_order_menu_entry_probe.py GRID_INFO_JS 그대로.
GRID_INFO_JS = r"""() => {
  const grids = [...document.querySelectorAll('.dews-ui-grid')];
  return grids.map((g, i) => {
    try {
      const ctrl = window.jQuery(g).data('dewsControl')._grid;
      const cols = ctrl.getColumns().map(col => ({ fieldName: col.fieldName, header: col.header, visible: col.visible }));
      return { i, rowCount: ctrl.getDataSource().getRowCount(), columnCount: cols.length, columns: cols };
    } catch (e) { return { i, error: String(e).slice(0, 80) }; }
  });
}"""

# '적용' 버튼이 달린 필터 행(공용) — 라벨/근접 텍스트로 구분(예: 납기예정일 옆 적용).
DUMP_APPLY_ROWS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null && c(b.innerText) === '적용');
  return btns.map(b => {
    const row = b.closest('tr') || b.closest('li') || b.closest('div');
    const r = b.getBoundingClientRect();
    return {
      rowText: row ? c(row.innerText).slice(0, 150) : '',
      btnId: b.id || '',
      btnCls: (b.className || '').toString().slice(0, 120),
      btnRect: { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) },
    };
  });
}"""

# 하위 탭 후보(품목/거래처/계정/발주) — 텍스트 완전일치, 화면에 보이는 요소만.
TAB_CANDIDATES_JS = r"""(texts) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const t of texts) {
    const els = [...document.querySelectorAll('a,li,div,span,button')].filter(e => e.offsetParent !== null && c(e.innerText) === t);
    for (const e of els) {
      const r = e.getBoundingClientRect();
      out.push({
        text: t, tag: e.tagName, id: e.id || '',
        cls: (e.className || '').toString().slice(0, 150),
        x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
        w: Math.round(r.width), h: Math.round(r.height),
      });
    }
  }
  return out;
}"""

# '구매요청' 버튼 셀렉터/위치만 — 클릭 금지(호출부에서 절대 클릭하지 않는다).
PURCHASE_REQUEST_BTN_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const b = [...document.querySelectorAll('button')].find(x => x.offsetParent !== null && c(x.innerText) === '구매요청');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { id: b.id || '', cls: (b.className || '').toString().slice(0, 150), rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } };
}"""

# 코드피커 팝업(마지막 visible .k-window) 그리드 컬럼+전량 로드분 raw rows — 지금 열려 있는
# 팝업이 하나뿐이라는 전제(공장 피커 탐색 전용, 프로젝트 도움창과 별개 화면이라 충돌 없음).
LAST_POPUP_GRID_DUMP_JS = r"""(limit) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-window' };
  const gridEl = dlg.querySelector('.dews-ui-grid');
  if (!gridEl) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(gridEl).data('dewsControl')._grid;
    const cols = g.getColumns().map(c2 => c2.fieldName);
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, Math.min(n, limit) - 1) : [];
    return { ok: true, rowCount: n, columns: cols, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_screen23_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_screen23_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _enter_screen(page: Page, base: str, deeplink: str, label: str) -> dict:
    """grids_required=2 시도 → MenuError 면 1 로 재시도. 실제 그리드 개수는 항상 재측정."""
    out: dict = {}
    try:
        await navigate_menu(page, deeplink, base, label=label, grids_required=2)
        out["entered_with"] = "grids_required=2"
    except MenuError as exc:
        out["grids_required_2_error"] = str(exc)
        await navigate_menu(page, deeplink, base, label=label, grids_required=1)
        out["entered_with"] = "grids_required=1(폴백)"
    await page.wait_for_timeout(1_500)
    out["actual_grid_count"] = await page.evaluate("() => document.querySelectorAll('.dews-ui-grid').length")
    return out


async def _dump_screen2(page: Page) -> dict:
    """Task B — 화면② 구매요청처리[나인벨] 랜딩 구조 + 탭 + 공장 채움 + F2."""
    out: dict = {}

    fields = await page.evaluate(DUMP_LABELED_FIELDS_JS)
    out["labeled_fields"] = fields
    print(f"[screen2] 라벨 필드 {len(fields)}개", flush=True)

    toolbar = await page.evaluate(DUMP_TOOLBAR_ICON_JS)
    out["toolbar_icon_elements"] = toolbar
    print(f"[screen2] 버튼/아이콘 {len(toolbar)}개", flush=True)

    grid_info_before = await page.evaluate(GRID_INFO_JS)
    out["grid_info_landing"] = grid_info_before
    print(f"[screen2] 랜딩 그리드 {len(grid_info_before)}개", flush=True)
    await _shot(page, "02_screen2_landing")

    # ── 하위 탭 4종 전환 + 각 탭 그리드 컬럼(허용된 클릭: 하위 탭 전환) ──
    tab_texts = ["품목", "거래처", "계정", "발주"]
    tab_candidates = await page.evaluate(TAB_CANDIDATES_JS, tab_texts)
    out["tab_candidates"] = tab_candidates
    print(f"[screen2] 탭 후보 {tab_candidates}", flush=True)

    tabs_result = []
    for t in tab_texts:
        cands = [c for c in tab_candidates if c["text"] == t]
        if not cands:
            tabs_result.append({"tab": t, "ok": False, "reason": "탭 후보 미발견"})
            continue
        # 가장 작은 요소(리프) 우선 — 컨테이너 오클릭 방지.
        cand = min(cands, key=lambda c: c["w"] * c["h"])
        await page.mouse.click(cand["x"], cand["y"])
        await page.wait_for_timeout(800)
        grid_info_after = await page.evaluate(GRID_INFO_JS)
        tabs_result.append({"tab": t, "ok": True, "clicked": cand, "grid_info_after": grid_info_after})
        await _shot(page, f"03_screen2_tab_{t}")
        print(f"[screen2] 탭 '{t}' 클릭 → grid_info={grid_info_after}", flush=True)
    out["tabs"] = tabs_result

    # ── 공장='나인벨' 채움(코드피커 엔진 재사용) + 조회(F2) — 미션에서 명시 허용 ──
    plant_result: dict = {}
    try:
        wrappers = await page.evaluate(DUMP_CODEPICKER_FIELDS_JS)
        plant_result["wrapper_fields"] = wrappers
        plant = next((w for w in wrappers if w.get("label") == "공장"), None)
        if not plant:
            plant_result["ok"] = False
            plant_result["reason"] = "공장 코드피커 wrapper 미발견"
        else:
            field_id = plant["fieldId"]
            plant_result["field_id"] = field_id
            # ⚠ codepicker._open_picker 는 CARD_WIN(.k-window 타이틀 '법인카드')에 스코프돼
            #   있어 이 화면(모달 아님, 최상위 폼)에선 항상 null — 버튼 오픈만 document 스코프로
            #   직접 찾는다(팝업 이후 search/select/apply/close 는 _PICKER_POP_PREAMBLE 이
            #   document 전역 스캔이라 그대로 재사용 가능, 1차 시도 실패로 확인됨).
            btn_box = await page.evaluate(
                r"""(fid) => {
                  const wr = document.querySelector('#' + fid + '-wrapper');
                  if (!wr) return null;
                  const b = wr.querySelector('.dews-codepicker-button');
                  if (!b) return null;
                  const r = b.getBoundingClientRect();
                  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
                }""",
                field_id,
            )
            plant_result["btn_box"] = btn_box
            opened = False
            if btn_box:
                await page.mouse.click(btn_box["x"], btn_box["y"])
                await codepicker._wait_picker_rows_stable(page, cap_ms=3_000)
                opened = (await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)) >= 0
            plant_result["opened"] = opened
            if not opened:
                plant_result["ok"] = False
                plant_result["reason"] = "피커 오픈 실패(버튼 미발견 또는 팝업 미출현)"
            else:
                await _shot(page, "04_screen2_plant_picker_open")
                dump_before = await page.evaluate(LAST_POPUP_GRID_DUMP_JS, 30)
                plant_result["popup_before_search"] = dump_before
                await codepicker._picker_search(page, "나인벨")
                dump_after = await page.evaluate(LAST_POPUP_GRID_DUMP_JS, 30)
                plant_result["popup_after_search"] = dump_after
                rows = (dump_after.get("rows") if dump_after.get("ok") else None) or []
                idx = None
                for i, r in enumerate(rows):
                    if any("나인벨" in str(v) for v in r.values() if v is not None):
                        idx = i
                        break
                plant_result["match_row_index"] = idx
                if idx is None:
                    await page.evaluate(js_lib.PICKER_CLOSE_JS)
                    plant_result["ok"] = False
                    plant_result["reason"] = "검색 결과에서 '나인벨' 행 미발견"
                else:
                    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, idx)
                    plant_result["select"] = sel
                    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
                    plant_result["apply_box"] = apply_box
                    if not apply_box:
                        plant_result["ok"] = False
                        plant_result["reason"] = "적용 버튼 미발견"
                    else:
                        await page.mouse.click(apply_box["x"], apply_box["y"])
                        closed = await codepicker._wait_picker_closed(page)
                        plant_result["closed"] = closed
                        field_val = await page.evaluate(js_lib.FIELD_DISPLAY_JS, "공장")
                        plant_result["field_value"] = field_val
                        plant_result["ok"] = bool(closed and field_val and "나인벨" in str(field_val))
    except Exception as exc:  # noqa: BLE001
        plant_result["ok"] = False
        plant_result["exception"] = repr(exc)
    out["plant_fill"] = plant_result
    print(f"[screen2] 공장 채움 결과: {plant_result.get('ok')} reason={plant_result.get('reason')}", flush=True)
    await _shot(page, "05_screen2_after_plant_fill")

    if plant_result.get("ok"):
        toolbar_before_query = await page.evaluate(DUMP_TOOLBAR_ICON_JS)
        lookup_box = await page.evaluate(po_js.LOOKUP_BTN_JS)
        if lookup_box:
            await page.mouse.click(lookup_box["x"], lookup_box["y"])
        else:
            await page.keyboard.press("F2")
        await page.wait_for_timeout(2_500)
        await _shot(page, "06_screen2_after_query")
        toolbar_after_query = await page.evaluate(DUMP_TOOLBAR_ICON_JS)
        grid_info_after_query = await page.evaluate(GRID_INFO_JS)
        out["query"] = {
            "lookup_box": lookup_box,
            "toolbar_before": toolbar_before_query,
            "toolbar_after": toolbar_after_query,
            "grid_info_after_query": grid_info_after_query,
        }
        before_sig = {(b["text"], b["title"], b["aria"]) for b in toolbar_before_query}
        after_sig = {(b["text"], b["title"], b["aria"]) for b in toolbar_after_query}
        new_buttons = [dict(zip(["text", "title", "aria"], s)) for s in (after_sig - before_sig)]
        out["query"]["new_buttons_after_query"] = new_buttons
        print(f"[screen2] 조회 후 새 버튼: {new_buttons}", flush=True)

        # ── 가설: 셀프결재 진입 버튼은 정적 툴바가 아니라 마스터 그리드 행 선택 시 나타난다.
        #    조회 결과가 있으면(rowCount>0) 첫 행을 선택(setCurrent+setSelection, 클릭 아님 —
        #    결재/상신 자체를 누르는 게 아니라 '행 선택'이므로 안전 경계 내)해 재확인한다. ──
        row_select_probe: dict = {}
        master_rowcount = (grid_info_after_query[0] or {}).get("rowCount") if grid_info_after_query else 0
        row_select_probe["master_rowcount"] = master_rowcount
        if isinstance(master_rowcount, int) and master_rowcount > 0:
            sel = await page.evaluate(
                r"""() => {
                  try {
                    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
                    const cols = g.getColumns();
                    const f = (cols.find(c => c.visible) || cols[0]).fieldName;
                    g.setCurrent({ itemIndex: 0, fieldName: f });
                    g.setSelection({ startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 });
                    return { ok: true, field: f };
                  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
                }"""
            )
            row_select_probe["select_result"] = sel
            await page.wait_for_timeout(1_000)
            await _shot(page, "07_screen2_after_row_select")
            toolbar_after_select = await page.evaluate(DUMP_TOOLBAR_ICON_JS)
            row_select_probe["toolbar_after_select"] = toolbar_after_select
            after_select_sig = {(b["text"], b["title"], b["aria"]) for b in toolbar_after_select}
            new_after_select = [dict(zip(["text", "title", "aria"], s)) for s in (after_select_sig - after_sig)]
            row_select_probe["new_buttons_after_select"] = new_after_select
            print(f"[screen2] 행 선택 후 새 버튼: {new_after_select}", flush=True)
        out["row_select_probe"] = row_select_probe
    else:
        out["query"] = {"skipped": True, "reason": "공장 채움 실패 — 조회 생략"}

    return out


async def _dump_screen3(page: Page) -> dict:
    """Task C — 화면③ 구매발주일괄입력[나인벨] 랜딩 상태 그대로 덤프(클릭·입력 0건)."""
    out: dict = {}

    fields = await page.evaluate(DUMP_LABELED_FIELDS_JS)
    out["labeled_fields"] = fields
    print(f"[screen3] 라벨 필드 {len(fields)}개", flush=True)

    toolbar = await page.evaluate(DUMP_TOOLBAR_ICON_JS)
    out["toolbar_icon_elements"] = toolbar
    print(f"[screen3] 버튼/아이콘 {len(toolbar)}개", flush=True)

    purchase_req_btn = await page.evaluate(PURCHASE_REQUEST_BTN_JS)
    out["purchase_request_button"] = purchase_req_btn
    print(f"[screen3] '구매요청' 버튼(클릭 안 함): {purchase_req_btn}", flush=True)

    grid_info = await page.evaluate(GRID_INFO_JS)
    out["grid_info"] = grid_info
    print(f"[screen3] 그리드 {len(grid_info)}개", flush=True)

    apply_rows = await page.evaluate(DUMP_APPLY_ROWS_JS)
    out["apply_rows"] = apply_rows
    print(f"[screen3] '적용' 버튼 행 {apply_rows}", flush=True)

    await _shot(page, "10_screen3_landing")
    return out


async def _dump_menu_tree(page: Page) -> dict:
    """Task D — 사이드바 DOM 에서 '구매발주처리[나인벨]' 확인(클릭 없음)."""
    keywords = [
        "구매발주처리[나인벨]",
        "구매발주처리",
        "구매발주일괄입력[나인벨]",
        "구매요청처리[나인벨]",
        "구매발주관리",
    ]
    scan = await page.evaluate(SCAN_MENU_JS, keywords)
    target = [s for s in scan if s["kw"] in ("구매발주처리[나인벨]", "구매발주처리")]
    print(f"[menu] '구매발주처리[나인벨]' 후보: {target}", flush=True)
    return {"scan": scan, "target_candidates": target}


async def main() -> None:
    results: dict = {"userid": USERID}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    try:
        print("[entry] login + SCM 전환…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")

        # ── 화면② 진입 + Task B 덤프 ──
        print(f"[menu] 화면② 진입 시도: {DEEPLINK_SCREEN2}", flush=True)
        try:
            entry2 = await _enter_screen(page, base, DEEPLINK_SCREEN2, LABEL_SCREEN2)
            results["screen2_entry"] = entry2
            print(f"[menu] 화면② 진입 결과: {entry2}", flush=True)
            results["screen2"] = await _dump_screen2(page)
        except MenuError as exc:
            results["screen2_entry_error"] = str(exc)
            print(f"[menu] 화면② 진입 실패: {exc}", flush=True)
            await _shot(page, "99_screen2_fail")

        # ── 화면③ 진입 + Task C 덤프 + Task D 메뉴 스캔(구매발주관리 그룹 확장 상태) ──
        print(f"[menu] 화면③ 진입 시도: {DEEPLINK_SCREEN3}", flush=True)
        try:
            entry3 = await _enter_screen(page, base, DEEPLINK_SCREEN3, LABEL_SCREEN3)
            results["screen3_entry"] = entry3
            print(f"[menu] 화면③ 진입 결과: {entry3}", flush=True)
            results["screen3"] = await _dump_screen3(page)
            results["menu_tree"] = await _dump_menu_tree(page)
        except MenuError as exc:
            results["screen3_entry_error"] = str(exc)
            print(f"[menu] 화면③ 진입 실패: {exc}", flush=True)
            await _shot(page, "99_screen3_fail")

        await _dump("results", results)
        print("\n===== SCREEN2/3 DUMP + MENU TREE PROBE COMPLETE =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
