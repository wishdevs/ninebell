"""상대계정거래처 실필드(문서 하단 폼 코드피커) 세팅·반영 검증 — 저장 없음.

trip_bottom_probe 로 확정: 행 채움 후 문서 하단에 '상대계정거래처' 라벨(≈265,1113) + 코드피커
버튼(≈469,1113)이 렌더된다(id 없음 → 라벨 기준 좌표 로케이트). 이 프로브는 그 피커를 라벨로
찾아 본인 검색·선택·적용하고, (1) 본 거래처(PARTNER_NM)가 안 덮이는지 (2) 어느 필드에 반영되는지
확정한다. ⚠ F7 금지. Usage: cd backend && .venv/bin/python e2e/trip_counter_field_probe.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.trip_domestic import steps as trip_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
ART = Path(__file__).resolve().parent / "artifacts"

# '상대계정거래처' 라벨과 같은 행(top 근접) 오른쪽의 코드피커 버튼 중심 좌표.
COUNTER_PICKER_BOX_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label,span,div,td')].find(e => e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if (!lbl) return null;
  const lr = lbl.getBoundingClientRect();
  const btns = [...document.querySelectorAll('button.dews-codepicker-button')].filter(b=>b.offsetParent!==null);
  let best=null, bd=1e9;
  for (const b of btns) { const r=b.getBoundingClientRect(); if (Math.abs(r.top-lr.top)<18 && r.left>lr.left) { const dx=r.left-lr.left; if (dx<bd){bd=dx;best=b;} } }
  if (!best) return null;
  const r=best.getBoundingClientRect();
  return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), labelY: Math.round(lr.top) };
}"""

# detail 마지막 행 전체에서 값 있는 거래처/BFC/상대 키 + PARTNER 확인.
ROW_DUMP_JS = r"""() => {
  try {
    const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
    const n = ds.getRowCount(); const row = Math.max(0, n-1);
    const j = ds.getJsonRows(row, row)[0] || {};
    const hit = {};
    for (const k of Object.keys(j)) { const v=j[k]; if (v==null||v==='') continue;
      if (/PARTNER|BFC|CUST|상대/i.test(k)) hit[k]=String(v); }
    return { ok:true, PARTNER_NM: String(j.PARTNER_NM==null?'':j.PARTNER_NM), hit };
  } catch(e) { return { ok:false, reason:String(e).slice(0,100) }; }
}"""

# 하단 폼 '상대계정거래처' 입력(라벨 같은 행 오른쪽 text input) 값 재독.
COUNTER_INPUT_VAL_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label,span,div,td')].find(e => e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if (!lbl) return null;
  const lr = lbl.getBoundingClientRect();
  const inps = [...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && Math.abs(i.getBoundingClientRect().top-lr.top)<18 && i.getBoundingClientRect().left>lr.left);
  return inps.map(i => c(i.value)).filter(Boolean);
}"""


async def main() -> None:
    from app.live.runner import LIVE_VIEWPORT  # 프로덕션 뷰포트(1440×900) — 스모크와 동일 레이아웃.

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=LIVE_VIEWPORT)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": "출장(국내·자차)"})
        await page.wait_for_timeout(1_800)
        await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
                break
        # 스모크와 동일하게 증빙(10) 먼저 선택(레이아웃 영향 확인).
        from app.agents.common import doc_steps
        oe = await doc_steps.open_evdn_editor(page)
        se = await doc_steps.select_evdn_code(page, "10")
        print(f"[evdn] open={oe.get('ok')} select={se.get('ok')}", flush=True)
        # 행 채움(상대계정 폼이 렌더되려면 데이터 필요).
        print("[fill] 거래처=한국도로공사 …", flush=True)
        await trip_steps.fill_partner(page, "10512", "한국도로공사")
        await trip_steps.fill_budget_fixed(page, "인사/기획팀", "판관비")
        await trip_steps.fill_project(page, {"code": "1310|1310", "name": "포장개선"})
        await trip_steps.set_transaction_amount(page, 15400)
        await trip_steps.set_row_note(page, "통행료(현금)")
        before = await page.evaluate(ROW_DUMP_JS)
        print(f"[before] PARTNER_NM={before.get('PARTNER_NM')} hit={before.get('hit')}", flush=True)

        # 상대계정거래처는 뷰포트(1000px) 아래(Y~1126)라 먼저 스크롤로 노출시킨다.
        await page.evaluate(r"""() => {
          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
          const lbl = [...document.querySelectorAll('label,span,div,td')].find(e => e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
          if (lbl) lbl.scrollIntoView({block:'center'});
        }""")
        await page.wait_for_timeout(600)
        # 상대계정거래처 하단 피커를 라벨로 찾아 클릭(스크롤 후 좌표).
        box = await page.evaluate(COUNTER_PICKER_BOX_JS)
        print(f"[counter] picker box(scrolled)={box}", flush=True)
        if not box:
            print("[counter] 상대계정거래처 피커 못 찾음", flush=True)
            await page.screenshot(path=str(ART / "trip_counter_field_nofind.png"), full_page=True)
            return
        await mouse_click(page, box["x"], box["y"])
        opened = False
        for _ in range(20):
            await page.wait_for_timeout(300)
            n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
            if isinstance(n, int) and n >= 0:
                opened = True
                break
        print(f"[counter] popup opened={opened}", flush=True)
        if opened:
            await trip_steps._picker_search(page, USERID)
            read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [trip_steps.PARTNER_FIELDS, 0])
            row, err = trip_steps.pick_partner_row(read.get("options") or [], USERID, None)
            print(f"[counter] pick err={err} nm={row.get('PARTNER_NM') if row else None}", flush=True)
            if row:
                await page.evaluate(js_lib.PICKER_SELECT_JS, row["i"])
                await page.wait_for_timeout(400)
                ab = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
                if ab:
                    await mouse_click(page, ab["x"], ab["y"])
                await page.wait_for_timeout(2_000)
                after = await page.evaluate(ROW_DUMP_JS)
                cinp = await page.evaluate(COUNTER_INPUT_VAL_JS)
                # 값이 있는 모든 input(id/value/좌표) 전수 — 이트라이브2/2026032511 이 어디 있는지.
                allinp = await page.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  return [...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && c(i.value))
                    .map(i=>({id:i.id||'(none)', val:c(i.value), x:Math.round(i.getBoundingClientRect().x), y:Math.round(i.getBoundingClientRect().y)}))
                    .filter(o=>/이트라이브|2026032511/.test(o.val));
                }""")
                lblpos = await page.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const l = [...document.querySelectorAll('label,span,div,td')].find(e=>e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
                  return l ? {y: Math.round(l.getBoundingClientRect().y), x: Math.round(l.getBoundingClientRect().x)} : null;
                }""")
                print(f"[after] PARTNER_NM={after.get('PARTNER_NM')} hit={after.get('hit')}", flush=True)
                print(f"[after] COUNTER_INPUT_VAL={cinp}  라벨위치={lblpos}", flush=True)
                print(f"[after] 이트라이브2 든 input 전수={allinp}", flush=True)
                print(f"[verdict] PARTNER 보존={after.get('PARTNER_NM')=='한국도로공사'}", flush=True)
        await page.screenshot(path=str(ART / "trip_counter_field.png"), full_page=True)
        print("[done] 저장 없이 종료", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        await page.screenshot(path=str(ART / "trip_counter_field_exc.png"))
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
