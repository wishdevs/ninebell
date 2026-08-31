"""읽기전용 진단 프로브 — ETRI-006 PRQ2026080775~0783 의 ERP 진실 확인(2026-08-31).

배경: 재개 런이 발주 팝업 0행을 '이미 발주'로 판정하고 9건 전부 스킵했다. 이 프로브는
클릭/입력을 조회·탭 전환·팝업 조회로만 제한(F7/상신/삭제 없음)하고 다음을 실측한다:
  A. 화면②(구매요청처리): PRQ 별 결재상태·상신코드 + 행 선택 후 '발주' 탭 그리드(발주번호 존재?)
  B. 화면③(구매발주일괄입력) 구매요청 팝업: 번호 없이 전체 조회 → 우리 PRQ 라인 존재 여부
  C. 번호 필터(PRQ2026080776) 재현 → B 와 비교
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.purchase_order import js_screen3 as j3  # noqa: E402
from app.agents.purchase_order import steps_screen3 as s3  # noqa: E402
from app.agents.purchase_order import steps_write as sw  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.omnisol.navigator import navigate_menu  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "0") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ART = Path(__file__).resolve().parent / "artifacts"
ART.mkdir(exist_ok=True)

PRQS = [f"PRQ20260807{n}" for n in range(75, 84)]
SCREEN2 = ("/PU/PUOPRQ00300_X20616", "구매요청처리[나인벨]")
SCREEN3 = ("/PU/PUOORD02000_X20616", "구매발주일괄입력[나인벨]")

TAB_CANDIDATES_JS = r"""(texts) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const t of texts) {
    const els = [...document.querySelectorAll('a,li,div,span,button')].filter(e => e.offsetParent !== null && c(e.innerText) === t);
    for (const e of els) {
      const r = e.getBoundingClientRect();
      out.push({ text: t, x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), w: Math.round(r.width), h: Math.round(r.height) });
    }
  }
  return out;
}"""

DUMP_ALL_GRIDS_JS = r"""(limit) => {
  const out = [];
  document.querySelectorAll('.dews-ui-grid').forEach((el, gi) => {
    try {
      const g = window.jQuery(el).data('dewsControl')._grid;
      const cols = g.getColumns().map(c => c.fieldName);
      const ds = g.getDataSource();
      const n = ds.getRowCount();
      const rows = n > 0 ? ds.getJsonRows(0, Math.min(n, limit) - 1) : [];
      out.push({ gi, rowCount: n, columns: cols, rows });
    } catch (e) { out.push({ gi, err: String(e).slice(0, 100) }); }
  });
  return out;
}"""


async def shot(page, name):
    p = str(ART / f"po_resume_truth_{name}.png")
    try:
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] fail {name}: {exc!r}", flush=True)


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw, DELAY_SCALE)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")

        # ── A. 화면② — PRQ 별 결재상태 + '발주' 탭 그리드 ──
        await navigate_menu(page, SCREEN2[0], base, label=SCREEN2[1], grids_required=1)
        await page.wait_for_timeout(1200)
        await sw.ensure_req_plant(page)
        # '발주' 탭을 먼저 켜 두고 PRQ 마다 행 선택 → 탭 그리드를 읽는다.
        tabs = await page.evaluate(TAB_CANDIDATES_JS, ["발주"])
        if tabs:
            t = min(tabs, key=lambda c: c["w"] * c["h"])
            await raw.mouse.click(t["x"], t["y"])
            await page.wait_for_timeout(600)
        for prq in PRQS:
            r = await sw.query_request(page, prq)
            if not r.get("ok"):
                print(f"[A] {prq}: 조회 실패 — {r.get('reason')}", flush=True)
                continue
            row = r["row"]
            await sw.select_request_row(page, int(row["i"]))
            await page.wait_for_timeout(900)
            grids = await page.evaluate(DUMP_ALL_GRIDS_JS, 40)
            pur_hits = []
            for g in grids:
                for gr in g.get("rows") or []:
                    for k, v in gr.items():
                        if isinstance(v, str) and v.startswith("PUR") and ("DOC" in k or "PUR" in k):
                            pur_hits.append(f"{k}={v}")
            st = row.get("ATHZ_ST_NM"); gw = row.get("GWDOCU_NO")
            print(f"[A] {prq}: 결재상태={st!r} 상신코드={gw!r} 발주탭 PUR={sorted(set(pur_hits))[:8] or '없음'}", flush=True)
        await shot(page, "A_screen2")

        # ── B. 화면③ 팝업 — 번호 없이 전체 조회 ──
        await navigate_menu(page, SCREEN3[0], base, label=SCREEN3[1], grids_required=1)
        await page.wait_for_timeout(1200)
        r = await s3.ensure_po_type(page)
        print(f"[B] 발주유형: {r}", flush=True)
        r = await s3.open_request_popup(page)
        print(f"[B] 팝업 열림: {r}", flush=True)
        await page.wait_for_timeout(800)
        read = await page.evaluate(j3.POPUP_GRID_ROWS_JS, [0, 3000]) or {}
        rows = read.get("rows") or []
        nos = sorted({str(x.get("PURREQ_NO") or "").strip() for x in rows if x.get("PURREQ_NO")})
        print(f"[B] 무필터 조회 — 총 {len(rows)}행, 요청번호 {len(nos)}종", flush=True)
        print(f"[B] 우리 PRQ 존재: " + ", ".join(f"{p}={'있음' if p in nos else '없음'}" for p in PRQS), flush=True)
        print(f"[B] 리스트에 있는 번호(최대 30): {nos[:30]}", flush=True)
        await shot(page, "B_popup_unfiltered")

        # ── C. 번호 필터 재현(PRQ2026080776) ──
        q = await s3.popup_query_prq(page, "PRQ2026080776", tries=2)
        print(f"[C] PRQ2026080776 필터 조회: ok={q.get('ok')} rows={len(q.get('rows') or [])} already={q.get('already')} reason={q.get('reason')}", flush=True)
        await shot(page, "C_popup_filtered")
    finally:
        await browser.close()
        await pw.stop()


asyncio.run(main())
