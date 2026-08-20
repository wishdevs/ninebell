"""세금계산서 잔존 전표 조회 0건 원인 진단 — 결의서입력 조회조건 '결의일' 필터 구조 덤프.

배경: tax_invoice_cleanup.py 1차 실행이 조회 0건("데이터가 없습니다")을 반환했다. OMNISOL_NOTES
§'회계일 기간은 항상 명시 세팅한다'(2026-07-28) 경고와 일치하는 증상 — 기본 조회기간이 실제
문서의 날짜를 놓칠 수 있다. 이 스크립트는 '결의일' 콤보(결의일/회계일 토글 추정) + 월/일 필드의
실제 id·구조·옵션을 덤프해 올바른 조회조건 세팅 방법을 실측한다. 읽기 전용(조회만, 삭제 없음).

Usage: cd backend && .venv/bin/python e2e/tax_invoice_period_diag.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from e2e.product_cycle import MASTER_DUMP_JS, USERID, PASSWORD, query_master  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

DUMP_AREA_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label,span,div,th')]
    .find(e => e.offsetParent !== null && c(e.innerText) === '결의일');
  if (!lbl) return { ok: false, reason: 'label not found' };
  const lr = lbl.getBoundingClientRect();
  const near = [];
  for (const el of document.querySelectorAll('input, select, button')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (Math.abs(r.top - lr.top) < 25 && r.left >= lr.left - 5 && r.left < lr.left + 400) {
      near.push({ tag: el.tagName, id: el.id || null, type: el.type || null,
        value: c(el.value || el.innerText).slice(0, 30),
        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width) });
    }
  }
  return { ok: true, near };
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await page.goto(f"{base}/FI/GLDDOC00300")
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(1000)
        await page.wait_for_timeout(1500)

        area = await page.evaluate(DUMP_AREA_JS)
        print("[area]", json.dumps(area, ensure_ascii=False), flush=True)

        # 결의구분 = 세금계산서 로 세팅.
        r = await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": "세금계산서"},
        )
        print("[gubun]", r, flush=True)
        await page.wait_for_timeout(1500)

        # 1차: 기본 상태 그대로 조회(비교 기준선).
        rc0 = await query_master(page)
        print(f"[query default] rowcount={rc0}", flush=True)
        await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag_default.png")

        # 2차: s_month 를 이번달 1일로 유지한 채, 일자 입력을 넓게(예: 1) 바꿔 월 전체가 잡히는지
        # 시도 — 필드 구조를 모르니 후보 id 를 순서대로 시도(있으면만 세팅).
        candidates = area.get("near", []) if area.get("ok") else []
        print("[candidates]", json.dumps(candidates, ensure_ascii=False), flush=True)

        # 3차: 결의구분 필터를 비우고(전체) 같은 날짜조건으로 재조회 — 오늘자 전체 문서 건수 확인.
        clear_gubun = await page.evaluate(
            "(sel) => { const s = document.querySelector(sel); const w = window.jQuery(s).data('kendoDropDownList');"
            " if (w) { w.value(''); w.trigger('change'); } else { s.value=''; s.dispatchEvent(new Event('change',{bubbles:true})); }"
            " return true; }",
            selectors.GUBUN_SELECT,
        )
        print("[clear_gubun]", clear_gubun, flush=True)
        await page.wait_for_timeout(800)
        rc_all = await query_master(page)
        dump_all = await page.evaluate(MASTER_DUMP_JS, 0)
        rows_all = dump_all.get("rows") or []
        summary = [
            {"ABDOCU_NO": r.get("ABDOCU_NO"), "ABDOCU_FG_CD": r.get("ABDOCU_FG_CD"),
             "WRT_EMP_NM": r.get("WRT_EMP_NM"), "ACTG_DT": r.get("ACTG_DT"), "WRT_DT": r.get("WRT_DT"),
             "DOCU_NO": r.get("DOCU_NO")}
            for r in rows_all
        ]
        print(f"[query gubun=전체, 결의일=오늘] rowcount={rc_all}", flush=True)
        print("[rows]", json.dumps(summary, ensure_ascii=False), flush=True)
        await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag_allgubun.png")

        # 4차: '결의일' 드롭다운(결의일/회계일 토글 추정) 옵션 덤프 — 클릭해서 열기.
        dd_box = await page.evaluate(
            "() => { const l = [...document.querySelectorAll('span,div')].find(e=>e.offsetParent!==null"
            " && e.innerText && e.innerText.trim()==='결의일'); if(!l) return null;"
            " const w = l.closest('.k-dropdown') || l.parentElement; const r = w.getBoundingClientRect();"
            " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }"
        )
        print("[dd_box]", dd_box, flush=True)
        if dd_box:
            await page.mouse.click(dd_box["x"], dd_box["y"])
            await page.wait_for_timeout(500)
            opts = await page.evaluate(
                "() => [...document.querySelectorAll('li.k-item, .k-list li')].filter(e=>e.offsetParent!==null)"
                ".map(e=>e.innerText.trim())"
            )
            print("[dd_options]", opts, flush=True)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

        # 5차: s_month 위젯 종류 확인 후 kendo API 로 정식 세팅(raw DOM set 은 kendo 내부
        # 모델을 안 바꿔 조회에 반영 안 됐을 위험 — OMNISOL_NOTES 'JS .click()/.value() 는
        # 변경적용 핸들러를 못 깨운다' 함정과 동형).
        widget_kind = await page.evaluate(
            "() => { const $=window.jQuery; const el=$('#s_month');"
            " for (const k of ['kendoDatePicker','kendoMonthPicker','kendoNumericTextBox','kendoDropDownList']) {"
            "   if (el.data(k)) return k; } return null; }"
        )
        print("[s_month widget kind]", widget_kind, flush=True)

        # 6차: '회계일' 모드(드롭다운 2번째 옵션)로 토글 후 같은 날짜(오늘)로 재조회.
        if dd_box:
            await page.mouse.click(dd_box["x"], dd_box["y"])
            await page.wait_for_timeout(400)
            opt2 = await page.evaluate(
                "() => { const it = [...document.querySelectorAll('li.k-item, .k-list li')]"
                ".filter(e=>e.offsetParent!==null).find(e=>e.innerText.includes('회계일'));"
                " if(!it) return null; const r = it.getBoundingClientRect();"
                " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }"
            )
            print("[opt2 회계일]", opt2, flush=True)
            if opt2:
                await page.mouse.click(opt2["x"], opt2["y"])
                await page.wait_for_timeout(500)
                rc_actgdt = await query_master(page)
                print(f"[query mode=회계일, gubun=전체, 오늘] rowcount={rc_actgdt}", flush=True)
                await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag_actgdt_mode.png")

        # 7차(최종 진단): 결의부서/결의자 필터까지 비워 회사 전체·오늘·전체 결의구분으로 재조회 —
        # 필터 스코프 문제인지 vs 문서 자체가 없는지 결정적으로 가른다.
        cleared = await page.evaluate(
            "() => { const c = s => { const d=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
            "   const el = document.querySelector(s); if(!el) return false; d.set.call(el,'');"
            "   el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); return true; };"
            " return { dept: c('#s_cd_wdept_text'), writer: c('#s_no_emp_write_text') }; }"
        )
        print("[cleared scope filters]", cleared, flush=True)
        await page.wait_for_timeout(500)
        rc_company = await query_master(page)
        dump_company = await page.evaluate(MASTER_DUMP_JS, 0)
        rows_company = dump_company.get("rows") or []
        summary_company = [
            {"ABDOCU_NO": r.get("ABDOCU_NO"), "ABDOCU_FG_CD": r.get("ABDOCU_FG_CD"),
             "WRT_EMP_NM": r.get("WRT_EMP_NM"), "WRT_DEPT_NM": r.get("WRT_DEPT_NM"),
             "ACTG_DT": r.get("ACTG_DT"), "WRT_DT": r.get("WRT_DT"), "DOCU_NO": r.get("DOCU_NO")}
            for r in rows_company
        ]
        print(f"[query 회사전체, 부서/작성자 무필터, 오늘, 결의구분=전체] rowcount={rc_company}", flush=True)
        print("[rows]", json.dumps(summary_company, ensure_ascii=False), flush=True)
        await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag_companywide.png")

        await browser.close()
        await pw.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        try:
            await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag_exception.png")
        except Exception:  # noqa: BLE001
            pass
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
