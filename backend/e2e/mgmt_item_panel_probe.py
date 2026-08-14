"""HEADLESS 검증 프로브 — 결의서입력(GLDDOC00300) 하단 '항목(관리항목)' 패널 실측.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 상신(결재) 절대 금지, F7(저장) 절대 금지 — 문서는 끝까지 미저장 상태로 유지.
  - 업무용차량 코드피커 목록 덤프는 부작용 없음(읽기). 실제 선택은 검증 목적 1회만 하고
    반영을 되읽는다. 문서를 저장하지 않으므로 서버에 아무 것도 남지 않는다 — F6 은 예상 밖
    부작용(빈 행 추가 등)이 관측될 때만 정리 목적으로 쓴다(이번 실측에서는 관측 안 됨).

진입 앞단은 card_owner_col_probe.py(2026-07-29)와 동일 패턴 재사용(login→user_type(회계)→
menu_nav→set_gubun(카드)→add_row). 예산계정 선택은 app.agents.trip_domestic.steps 의
_open_detail_cell_picker(캔버스 셀 showEditor+돋보기, BUDGET_CELL='BG_NM')·
app.agents.card_collect.steps._picker_search 를 그대로 재사용.

핵심 실측 결과(요약 — 상세는 e2e/artifacts/mgmt_item_panel_*):
  - '항목/내역코드/내역명' 패널은 RealGrid 캔버스(.dews-ui-grid)가 **아니라** 순수 DOM
    `<table id="tb1">`(`div#controlItem.dews-custom-ui` 안, dews-ui-grid 인덱스와 무관).
  - 각 행은 <td>라벨(항목명, 텍스트)</td><td>코드피커(hidden input[data-target=MNGD_CD] +
    보이는 input#undefined_text — id 가 전 행 동일하게 충돌하므로 **id 로 행을 구분할 수 없다**,
    행은 라벨 텍스트로 찾아야 함) + button.dews-codepicker-button</td>
    <td>내역명 readonly input[data-target=MNGD_NM]</td> 3열 구조.
  - 예산계정 의존적: 신규 행(예산계정 미선택)은 패널 0행. '(판)차량유지비-유류' 선택 후
    11행(귀속사업장·부서·사원·신용카드·자금예정일·자금과목·업무용차량·건설중인자산·
    거래처계좌번호·결제조건·결제수단)으로 채워짐.
  - 행 선택 스코프: 상세행(디테일 그리드) 전환 시 패널이 그 행 기준으로 바뀐다(행B=미설정
    → 0행, 행A 재선택 → 11행+세팅값 그대로 복원).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/mgmt_item_panel_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) ────────────────────────────────────────────────────────
from app.agents.card_collect.steps import _picker_search  # noqa: E402
from app.agents.trip_domestic.steps import _open_detail_cell_picker  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
VIEWPORT = selectors.VIEWPORT  # {1600,1000} — trip_domestic 캔버스 셀 좌표가 이 뷰포트에서 검증됨.

VEHICLE_BUDGET_SEARCH_KEYWORD = "차량"
VEHICLE_BUDGET_PICK_INDEX = 5  # 검색결과 중 '(판)차량유지비-유류'(판관비 계열, 실측 인덱스).

# ── 신규 작성분(이 패널 고유) ────────────────────────────────────────────────────
# 라벨 텍스트로 tb1 테이블의 행을 찾는 3종 — id 충돌(모든 행이 id="undefined_text") 때문에
# 라벨 텍스트 매칭이 유일한 신뢰 가능한 방법이다. trip_domestic.js COUNTER_*(상대계정거래처
# 하드코딩)과 알고리즘은 동일(라벨 텍스트 검색 → 같은 행 오른쪽 위젯), 대상이 td/tr 구조라는
# 점과 라벨 파라미터화만 다르다.
ROW_SCROLL_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const td = [...document.querySelectorAll('td')].find(e => e.offsetParent!==null && c(e.innerText)===label);
  if (!td) return false;
  td.scrollIntoView({ block: 'center' });  // ⚠ 패널 내부 스크롤 컨테이너 — 없으면 버튼 좌표가 0/클리핑됨(1차 시도 실패 원인).
  return true;
}"""

ROW_BUTTON_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const td = [...document.querySelectorAll('td')].find(e => e.offsetParent!==null && c(e.innerText)===label);
  if (!td) return null;
  const tr = td.closest('tr');
  const btn = tr && tr.querySelector('.dews-codepicker-button');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

ROW_VALUES_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const td = [...document.querySelectorAll('td')].find(e => e.offsetParent!==null && c(e.innerText)===label);
  if (!td) return { found:false };
  const tr = td.closest('tr');
  const tds = [...tr.querySelectorAll('td')];
  const codeInput = tds[1] ? [...tds[1].querySelectorAll('input')].find(i => i.id === 'undefined_text') : null;
  const nameInput = tds[2] ? tds[2].querySelector('input') : null;
  return { found: true, code: codeInput ? c(codeInput.value) : null, name: nameInput ? c(nameInput.value) : null };
}"""

TABLE_DUMP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const th = [...document.querySelectorAll('th')].find(e => e.offsetParent!==null && c(e.innerText)==='항목');
  if (!th) return { found:false };
  const table = th.closest('table');
  if (!table) return { found:false, reason:'no-table' };
  const tbody = table.querySelector('tbody');
  const rows = [];
  if (tbody) {
    for (const tr of tbody.querySelectorAll('tr')) {
      const tds = [...tr.querySelectorAll('td')];
      const label = tds[0] ? c(tds[0].innerText) : null;
      const codeInput = tds[1] ? [...tds[1].querySelectorAll('input')].find(i => i.id === 'undefined_text') : null;
      const nameInput = tds[2] ? tds[2].querySelector('input') : null;
      const hasPicker = !!(tds[1] && tds[1].querySelector('.dews-codepicker-button'));
      rows.push({ label, code: codeInput ? c(codeInput.value) : null, name: nameInput ? c(nameInput.value) : null, hasPicker });
    }
  }
  return { found: true, tableId: table.id || null, rowCount: rows.length, rows };
}"""

PANEL_ROWCOUNT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const th = [...document.querySelectorAll('th')].find(e => e.offsetParent!==null && c(e.innerText)==='항목');
  if (!th) return -1;
  const tbody = th.closest('table').querySelector('tbody');
  return tbody ? tbody.querySelectorAll('tr').length : -1;
}"""

POPUP_DUMP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return { ok:false, reason:'no-popup' };
  const title = c((p.querySelector('.k-window-title') || {}).innerText);
  const buttons = [...p.querySelectorAll('button')].filter(b => b.offsetParent !== null).map(b => c(b.innerText));
  try {
    const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({ field: cc.fieldName || cc.name, header: (cc.header && cc.header.text) || cc.caption }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, Math.min(n, 10) - 1) : [];
    return { ok:true, title, buttons, n, cols, rows };
  } catch (e) { return { ok:false, title, buttons, err: String(e).slice(0, 150) }; }
}"""

POPUP_ROW_RECT_JS = r"""(rowIndex) => {
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return null;
  const gridEl = p.querySelector('.dews-ui-grid');
  if (!gridEl) return null;
  const gr = gridEl.getBoundingClientRect();
  return { x: Math.round(gr.x + 150), y: Math.round(gr.y + 30 + rowIndex * 32 + 16) };
}"""

POPUP_COUNT_VISIBLE_JS = "() => [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).length"

DETAIL_ROW_CLICK_JS = r"""(idx) => {
  const g = document.querySelectorAll('.dews-ui-grid')[1];
  const r = g.getBoundingClientRect();
  return { x: Math.round(r.x + 100), y: Math.round(r.y + 34 + idx * 32 + 16) };
}"""

DETAIL_ROWS_DUMP_JS = r"""() => { try {
  const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const n = g.getDataSource().getRowCount();
  const rows = n > 0 ? g.getDataSource().getJsonRows(0, n - 1) : [];
  return { n, rows: rows.map(r => ({ BGACCT_NM: r.BGACCT_NM, BG_NM: r.BG_NM })) };
} catch (e) { return { e: String(e).slice(0, 100) }; } }"""


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"mgmt_item_panel_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page: Page = await (await browser.new_context(viewport=VIEWPORT)).new_page()
        try:
            print("[step] login → user_type(회계) → menu_nav → set_gubun(카드) → add_row(F3)")
            await ensure_logged_in(page, USERID, PASSWORD, base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, EXPENSE_CARD, base)
            for _ in range(50):
                if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                    break
                await page.wait_for_timeout(300)
            await page.evaluate(
                js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
                {"selector": selectors.GUBUN_SELECT, "text": "카드"},
            )
            await js_click(page, selectors.BTN_ADD)
            rows = -1
            for _ in range(33):
                await page.wait_for_timeout(300)
                rows = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                if isinstance(rows, int) and rows > 0:
                    break
            if not (isinstance(rows, int) and rows > 0):
                raise RuntimeError("add_row 실패")
            await page.wait_for_timeout(500)

            print("[가설1/2] 예산계정 미선택 상태 — 항목 패널 덤프(빈 상태 기대)")
            before = await page.evaluate(TABLE_DUMP_JS)
            print("  rowCount:", before.get("rowCount"))
            _dump("1_table_before_account", before)
            await page.screenshot(path=str(ARTIFACTS / "mgmt_item_panel_1_before_account.png"), full_page=True)

            print(f"[가설2] 예산단위(BG_NM) 캔버스 셀 피커 오픈 → '{VEHICLE_BUDGET_SEARCH_KEYWORD}' 검색")
            op = await _open_detail_cell_picker(page, "BG_NM", "예산단위")
            if not op.get("ok"):
                raise RuntimeError(f"예산단위 피커 오픈 실패: {op}")
            await _picker_search(page, VEHICLE_BUDGET_SEARCH_KEYWORD)
            read = await page.evaluate(
                js_lib.PICKER_READ_MULTI_JS,
                [["BG_CD", "BG_NM", "BIZPLAN_NM", "BGACCT_CD", "BGACCT_NM"], 0],
            )
            opts = read.get("options") or []
            print(f"  검색결과 {len(opts)}건")
            chosen = opts[VEHICLE_BUDGET_PICK_INDEX]
            print("  선택:", chosen)
            sel = await page.evaluate(js_lib.PICKER_SELECT_JS, chosen["i"])
            await page.wait_for_timeout(500)
            ab = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
            if not ab:
                raise RuntimeError("예산단위 피커 '적용' 버튼 없음")
            await mouse_click(page, ab["x"], ab["y"])
            await page.wait_for_timeout(1500)

            print("[가설2] 예산계정 선택 후 — 항목 패널 재덤프")
            after = await page.evaluate(TABLE_DUMP_JS)
            print("  rowCount:", after.get("rowCount"))
            for r in after.get("rows", []):
                print("   ", r["label"], "hasPicker=", r["hasPicker"])
            _dump("2_table_after_vehicle_account", after)
            await page.screenshot(path=str(ARTIFACTS / "mgmt_item_panel_2_after_account.png"), full_page=True)

            print("[가설3] 업무용차량 행 스크롤 → 코드피커 오픈")
            scrolled = await page.evaluate(ROW_SCROLL_JS, "업무용차량")
            await page.wait_for_timeout(300)
            box = await page.evaluate(ROW_BUTTON_JS, "업무용차량")
            print("  scrolled:", scrolled, "button box:", box)
            if not box:
                raise RuntimeError("업무용차량 코드피커 버튼을 찾지 못했습니다")
            popups_before = await page.evaluate(POPUP_COUNT_VISIBLE_JS)
            await mouse_click(page, box["x"], box["y"])
            await page.wait_for_timeout(1200)
            popup_dump = await page.evaluate(POPUP_DUMP_JS)
            print("  popup:", popup_dump.get("title"), "n=", popup_dump.get("n"), "buttons=", popup_dump.get("buttons"))
            _dump("3_vehicle_popup", popup_dump)
            await page.screenshot(path=str(ARTIFACTS / "mgmt_item_panel_3_vehicle_popup.png"), full_page=True)
            if not popup_dump.get("ok"):
                raise RuntimeError(f"업무용차량 팝업 덤프 실패: {popup_dump}")

            print("[가설3] 목록 0행 더블클릭(적용 버튼 아님 — 기존 코드피커 패턴과 동형) → 반영 확인")
            rr = await page.evaluate(POPUP_ROW_RECT_JS, 0)
            await page.mouse.dblclick(rr["x"], rr["y"])
            await page.wait_for_timeout(1200)
            popups_after = await page.evaluate(POPUP_COUNT_VISIBLE_JS)
            await page.evaluate(ROW_SCROLL_JS, "업무용차량")
            await page.wait_for_timeout(300)
            readback = await page.evaluate(ROW_VALUES_JS, "업무용차량")
            print(f"  popup {popups_before}->{popups_after}, readback:", readback)
            _dump("4_vehicle_readback", {"popups_before": popups_before, "popups_after": popups_after, "readback": readback})
            await page.screenshot(path=str(ARTIFACTS / "mgmt_item_panel_4_after_select.png"), full_page=True)

            print("[가설4] 행B(F3 신규, 예산계정 미설정) 추가 → 패널 재확인")
            await js_click(page, selectors.BTN_ADD)
            rows2 = -1
            for _ in range(33):
                await page.wait_for_timeout(300)
                rows2 = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                if isinstance(rows2, int) and rows2 >= 2:
                    break
            await page.wait_for_timeout(800)
            panel_rowcount_b = await page.evaluate(PANEL_ROWCOUNT_JS)
            print("  행B 항목 패널 행수(기대 0):", panel_rowcount_b)
            detail_dump = await page.evaluate(DETAIL_ROWS_DUMP_JS)
            print("  detail grid 상태:", detail_dump)

            print("[가설4] 행A 재클릭 → 패널이 행A 값으로 복원되는지 확인")
            click_box = await page.evaluate(DETAIL_ROW_CLICK_JS, 0)
            await mouse_click(page, click_box["x"], click_box["y"])
            await page.wait_for_timeout(800)
            panel_rowcount_a2 = await page.evaluate(PANEL_ROWCOUNT_JS)
            await page.evaluate(ROW_SCROLL_JS, "업무용차량")
            await page.wait_for_timeout(300)
            readback_a2 = await page.evaluate(ROW_VALUES_JS, "업무용차량")
            print("  행A 재선택 후 패널 행수:", panel_rowcount_a2, "업무용차량:", readback_a2)
            await page.screenshot(path=str(ARTIFACTS / "mgmt_item_panel_5_rowA_reselected.png"), full_page=True)

            result = {
                "table_before_account": before,
                "table_after_account": after,
                "vehicle_popup": popup_dump,
                "vehicle_readback_row_A": readback,
                "row_scope": {
                    "rowB_panel_rowcount": panel_rowcount_b,
                    "detail_grid_rows": detail_dump,
                    "rowA_reselected_panel_rowcount": panel_rowcount_a2,
                    "rowA_reselected_readback": readback_a2,
                },
            }
            _dump("result", result)
            print("\n=== DONE ===")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {exc}")
            try:
                await page.screenshot(path=str(ARTIFACTS / "mgmt_item_panel_FAIL.png"), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            # ⚠ 문서 미저장(F7 없음) — 서버에 아무 것도 남지 않으므로 F6 정리 불필요. 브라우저만 종료.
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
