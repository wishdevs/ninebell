"""상대계정거래처 실필드 집중 재프로브 — 문서 하단(프로젝트 그리드 아래 왼쪽) 전수 덤프.

사용자 스펙 힌트: "프로젝트 그리드 하단에 왼쪽에 위치". P8 은 detail 셀만 봤으므로, 이번엔
모든 그리드(index 0/1/2…) 컬럼 + 문서 전역 input/select/코드피커/라벨(위치 포함)을 전수 덤프하고
전체 스크린샷을 남긴다. '상대계정'/'거래처'/'계정' 라벨과 하단(Y 큰)·좌측(X 작은) 요소를 집중 확인.

⚠ F7 절대 금지. Usage: cd backend && .venv/bin/python e2e/trip_bottom_probe.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.trip_domestic import steps as trip_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
ART = Path(__file__).resolve().parent / "artifacts"
ART.mkdir(exist_ok=True)

# 모든 그리드 컬럼 + 문서 전역 폼 요소(위치 포함) 전수 덤프.
DUMP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = { grids: [], pickers: [], inputs: [], selects: [], labels: [] };
  // 그리드(index 별) 컬럼·행수.
  const grids = document.querySelectorAll('.dews-ui-grid');
  for (let gi = 0; gi < grids.length; gi++) {
    const r = grids[gi].getBoundingClientRect();
    try {
      const g = window.jQuery(grids[gi]).data('dewsControl')._grid;
      const cols = (g.getColumns ? g.getColumns() : []).map(cc => cc.fieldName || cc.name).filter(Boolean);
      out.grids.push({ index: gi, y: Math.round(r.top), h: Math.round(r.height), rows: g.getDataSource().getRowCount(), cols });
    } catch (e) { out.grids.push({ index: gi, y: Math.round(r.top), err: String(e).slice(0,60) }); }
  }
  // 코드피커/멀티코드피커 버튼(래퍼 id + 근처 라벨 + 위치).
  for (const b of document.querySelectorAll('button.dews-codepicker-button, button.dews-multicodepicker-button')) {
    if (b.offsetParent === null) continue;
    const r = b.getBoundingClientRect();
    const wr = b.closest('[id$=-wrapper]');
    let label = '';
    let best = 1e9;
    for (const l of document.querySelectorAll('label,th,span,div')) {
      if (l.offsetParent === null) continue;
      const t = c(l.innerText); if (!t || t.length > 16) continue;
      const lr = l.getBoundingClientRect();
      if (Math.abs(lr.top - r.top) < 22 && lr.left < r.left) { const dx = r.left - lr.left; if (dx < best) { best = dx; label = t; } }
    }
    out.pickers.push({ wrapper: wr ? wr.id : null, label, x: Math.round(r.x), y: Math.round(r.y), multi: b.className.includes('multi') });
  }
  // 문서 전역 input(id).
  for (const i of document.querySelectorAll('input[id]')) {
    if (i.offsetParent === null) continue;
    const r = i.getBoundingClientRect();
    out.inputs.push({ id: i.id, type: i.type || '', x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), val: c(i.value).slice(0,30) });
  }
  // select(id).
  for (const s of document.querySelectorAll('select[id]')) {
    if (s.offsetParent === null) continue;
    const r = s.getBoundingClientRect();
    out.selects.push({ id: s.id, x: Math.round(r.x), y: Math.round(r.y), opts: s.options.length });
  }
  // '상대'/'거래처'/'계정' 포함 라벨(위치).
  for (const el of document.querySelectorAll('label,th,span,div,td')) {
    if (el.offsetParent === null) continue;
    const t = c(el.innerText);
    if (t && t.length <= 16 && /상대|거래처|계정/.test(t)) {
      const r = el.getBoundingClientRect();
      out.labels.push({ text: t, x: Math.round(r.x), y: Math.round(r.y) });
    }
  }
  return out;
}"""


async def _entry_and_row(page, base):
    await ensure_logged_in(page, USERID, PASSWORD, base)
    await ensure_user_type(page, "회계")
    await navigate_schema(page, EXPENSE_CARD, base)
    for _ in range(20):
        if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
            break
        await page.wait_for_timeout(500)
    await page.evaluate(
        js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
        {"selector": selectors.GUBUN_SELECT, "text": "출장(국내·자차)"},
    )
    await page.wait_for_timeout(1_800)
    await js_click(page, selectors.BTN_ADD)
    for _ in range(33):
        await page.wait_for_timeout(300)
        if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
            break


def _report(tag: str, d: dict) -> None:
    print(f"\n===== DUMP ({tag}) =====", flush=True)
    print(f"grids: {[{'i': g['index'], 'y': g.get('y'), 'rows': g.get('rows'), 'ncols': len(g.get('cols') or [])} for g in d['grids']]}", flush=True)
    for g in d["grids"]:
        if g.get("cols"):
            print(f"  grid[{g['index']}] cols: {g['cols']}", flush=True)
    print(f"labels(상대/거래처/계정): {d['labels']}", flush=True)
    # 하단(Y 큰) 순 피커/인풋 — '프로젝트 그리드 하단 왼쪽' 후보.
    pickers = sorted(d["pickers"], key=lambda p: -p["y"])
    print(f"pickers(하단순): {pickers}", flush=True)
    inputs_bottom = sorted([i for i in d["inputs"] if i["y"] > 400], key=lambda i: -i["y"])[:15]
    print(f"inputs(Y>400 하단순 15): {inputs_bottom}", flush=True)
    print(f"selects: {d['selects']}", flush=True)


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base
    try:
        await _entry_and_row(page, base)
        # (a) F3 직후 덤프.
        d1 = await page.evaluate(DUMP_JS)
        _report("after F3", d1)
        await page.screenshot(path=str(ART / "trip_bottom_after_f3.png"), full_page=True)

        # (b) 한 행을 채운 뒤 덤프(상대계정 필드가 데이터 있을 때만 렌더될 가능성).
        await trip_steps.fill_partner(page, "10512", "한국도로공사")
        await trip_steps.fill_budget_fixed(page, "인사/기획팀", "판관비")
        await trip_steps.fill_project(page, {"code": "1310|1310", "name": "포장개선"})
        await trip_steps.set_transaction_amount(page, 15400)
        await trip_steps.set_row_note(page, "통행료(현금)")
        d2 = await page.evaluate(DUMP_JS)
        _report("after fill row", d2)
        await page.screenshot(path=str(ART / "trip_bottom_after_fill.png"), full_page=True)

        (ART / "trip_bottom_probe.json").write_text(
            json.dumps({"after_f3": d1, "after_fill": d2}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n[dump] trip_bottom_probe.json + trip_bottom_after_f3.png / trip_bottom_after_fill.png", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        await page.screenshot(path=str(ART / "trip_bottom_exception.png"))
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
