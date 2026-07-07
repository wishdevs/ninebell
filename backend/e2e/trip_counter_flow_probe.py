"""상대계정거래처 재배선 실측 — 모든 행 채운 뒤 문서 레벨 1회 세팅(팀리드 접근 #1). 저장 없음.

멀티행(통행료2)을 실 플로우로 채우고(증빙 포함), 마지막에 상대계정거래처를 1회 세팅한 뒤
detail 행(거래처/금액/적요)이 온전한지 + 상대계정 반영됐는지 재독한다. 리셋 재현 시 모달 관찰.
⚠ F7 금지. Usage: cd backend && .venv/bin/python e2e/trip_counter_flow_probe.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js  # noqa: E402
from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import steps as ts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
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

DETAIL_DUMP_JS = """() => {
  try {
    const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
    const n = ds.getRowCount(); const rows = n>0 ? ds.getJsonRows(0,n-1) : [];
    return { n, rows: rows.map(r => ({ PARTNER_NM: String(r.PARTNER_NM==null?'':r.PARTNER_NM),
      SPPRC_AMT2: String(r.SPPRC_AMT2==null?'':r.SPPRC_AMT2), NOTE_DC: String(r.NOTE_DC==null?'':r.NOTE_DC),
      EVDN_TP_NM: String(r.EVDN_TP_NM==null?'':r.EVDN_TP_NM) })) };
  } catch(e){ return { err: String(e).slice(0,100) }; }
}"""


async def _fill_row(page, i, partner_code, partner_name, amount, note):
    if i > 0:
        r = await doc_steps.add_next_row(page, i + 1)
        assert r.get("ok"), f"add_next_row: {r}"
    oe = await doc_steps.open_evdn_editor(page)
    assert oe.get("ok"), f"open_evdn: {oe}"
    se = await doc_steps.select_evdn_code(page, "10")
    assert se.get("ok"), f"select_evdn: {se}"
    pr = await ts.fill_partner(page, partner_code, partner_name)
    assert pr.get("ok"), f"fill_partner: {pr}"
    bu = await ts.fill_budget_fixed(page, "인사/기획팀", "판관비")
    assert bu.get("ok"), f"budget: {bu}"
    pj = await ts.fill_project(page, {"code": "1310|1310", "name": "포장개선"})
    assert pj.get("ok"), f"project: {pj}"
    import os as _o
    amt_mode = _o.environ.get("TRIP_AMT", "txn")  # txn=set_transaction_amount / spprc=SPPRC_AMT만 / none
    if amt_mode == "txn":
        sa = await ts.set_transaction_amount(page, amount)
        assert sa.get("ok"), f"amount: {sa}"
    elif amt_mode == "spprc":
        r = await page.evaluate(ts.js.SET_DETAIL_CELL_JS, {"field": "SPPRC_AMT", "value": amount})
        assert r.get("ok"), f"spprc: {r}"
    # amt_mode == "none": 금액 세팅 안 함(counter 영향 격리).
    nt = await ts.set_row_note(page, note)
    assert nt.get("ok"), f"note: {nt}"


async def main() -> None:
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
        # 2행 채움(통행료). ⚠ set_master_total 은 counter 뒤로 미룸(master setValue 가 편집
        # 포커스를 detail 셀에 남겨 counter 적용이 오발한다는 가설 검증).
        import os as _os
        nrows = int(_os.environ.get("TRIP_NROWS", "2"))
        await _fill_row(page, 0, "10512", "한국도로공사", 12500, "통행료(현금)")
        if nrows >= 2:
            await _fill_row(page, 1, "10512", "한국도로공사", 15800, "통행료(현금)")

        before = await page.evaluate(DETAIL_DUMP_JS)
        print(f"[before counter] {json.dumps(before, ensure_ascii=False)}", flush=True)

        # 네트워크(XHR) 관찰 — counter 적용 시 어떤 서버 요청이 뜨는지(팀리드 지시 #2).
        net_log: list = []
        def _on_req(req):
            if any(k in req.url for k in ("/Service/", "/api/", "search", "list", "save", "add")):
                net_log.append(("REQ", req.method, req.url.split("?")[0][-80:]))
        page.on("request", _on_req)
        # ★ 상대계정 전에 detail 그리드 편집상태를 커밋/블러(가설: set_transaction_amount 의 3회
        #   setValue 가 detail 셀을 편집상태로 남겨 counter '적용'이 그 셀에 커밋 → 행 추가).
        commit = await page.evaluate(r"""() => {
          const out = {};
          try { const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
            for (const m of ['commit','endEdit','cancelEdit','clearCurrent']) if (typeof g[m]==='function') { try{ g[m](); out[m]='called'; }catch(e){ out[m]='err'; } }
          } catch(e){ out.err = String(e).slice(0,60); }
          if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
          if (document.body && document.body.focus) document.body.focus();
          return out;
        }""")
        print(f"[counter] detail commit/blur: {commit}", flush=True)
        await page.wait_for_timeout(500)
        # 상대계정거래처 문서 레벨 1회 세팅 — 단계별 계측.
        scrolled = await page.evaluate(ts.js.COUNTER_SCROLL_JS)
        await page.wait_for_timeout(500)
        box = await page.evaluate(ts.js.COUNTER_PICKER_BOX_JS)
        rc_before = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
        print(f"[counter] scrolled={scrolled} box={box} detail_rc_before_click={rc_before}", flush=True)
        # 라벨/버튼 위치 진단 — 모든 상대계정 관련 라벨·근처 버튼 위치.
        diag = await page.evaluate(r"""() => {
          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
          const out = [];
          for (const l of document.querySelectorAll('label,span,div,td')) {
            if (l.offsetParent===null) continue;
            if (c(l.innerText)==='상대계정거래처') { const r=l.getBoundingClientRect(); out.push({y:Math.round(r.y), x:Math.round(r.x)}); }
          }
          return out;
        }""")
        print(f"[counter] 상대계정거래처 라벨 위치들={diag}", flush=True)
        _apply = None
        if box:
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1_500)
            await page.screenshot(path=str(ART / "trip_counter_popup_open.png"), full_page=True)
            print(f"[counter] after click: detail_rc={await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)} (popup screenshot saved)", flush=True)
            # 검색 + Enter.
            await ts._picker_search(page, USERID)
            read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [ts.PARTNER_FIELDS, 0])
            row, err = ts.pick_partner_row(read.get("options") or [], USERID, None)
            print(f"[counter] search: rows={read.get('rows')} pick_err={err} pick_i={row.get('i') if row else None} rc={await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)}", flush=True)
            if row:
                sel = await page.evaluate(js_lib.PICKER_SELECT_JS, row["i"])
                await page.wait_for_timeout(400)
                # ★ '적용' 버튼 대신 팝업 그리드 매칭 행을 **더블클릭**(dews 표준 — 원 필드에 적용).
                # 매칭 행의 화면 좌표를 팝업 그리드에서 계산해 실좌표 더블클릭.
                rowbox = await page.evaluate(r"""(idx) => {
                  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null).slice(-1)[0];
                  if(!p) return null; const g = p.querySelector('.dews-ui-grid'); if(!g) return null;
                  const gr = g.getBoundingClientRect();
                  // 대략: 헤더 ~34px + 행높이 ~32px, idx 행 중앙.
                  return { x: Math.round(gr.x + gr.width*0.30), y: Math.round(gr.y + 44 + idx*32 + 16) };
                }""", row["i"])
                print(f"[counter] select={sel} rowbox={rowbox} rc={await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)}", flush=True)
                if rowbox:
                    await page.mouse.dblclick(rowbox["x"], rowbox["y"])
                    await page.wait_for_timeout(1_500)
                    print(f"[counter] after DBLCLICK: rc={await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)} cinp={await page.evaluate(ts.js.COUNTER_INPUT_VAL_JS)} popup_gone={(await page.evaluate(js_lib.PICKER_ROWCOUNT_JS))<0}", flush=True)
                print("[counter] NET during counter:", flush=True)
                for e in net_log[-15:]:
                    print(f"    {e}", flush=True)
        cp = {"ok": False, "reason": "수동 계측"}
        await page.wait_for_timeout(500)
        modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
        print(f"[counter] modals after: {[m.get('title') for m in (modals or [])]}", flush=True)

        after = await page.evaluate(DETAIL_DUMP_JS)
        print(f"[after counter] {json.dumps(after, ensure_ascii=False)}", flush=True)
        cinp = await page.evaluate(ts.js.COUNTER_INPUT_VAL_JS)
        print(f"[after counter] 상대계정 입력값={cinp}", flush=True)

        # 판정.
        rows_ok = (isinstance(after, dict) and after.get("n") == 2 and
                   all(r.get("PARTNER_NM") == "한국도로공사" and r.get("SPPRC_AMT2") for r in (after.get("rows") or [])))
        counter_ok = "이트라이브2" in (cinp or [])
        print(f"[verdict] detail_rows_intact={rows_ok} counter_set={counter_ok}", flush=True)
        await page.screenshot(path=str(ART / "trip_counter_flow.png"), full_page=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        await page.screenshot(path=str(ART / "trip_counter_flow_exc.png"))
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
