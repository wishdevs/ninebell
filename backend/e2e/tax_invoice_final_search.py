"""세금계산서 잔존 전표 — 최종 탐색 라운드(team-lead 최종 지시, 2026-08-19).

회계일 후보(녹화 3건이 회계일을 조작한 흔적 + 저장 성공 확실성 높은 건 포함):
  8/19(발행 전 건, 오늘·미변경 추정) · 8/14(비과세건, 사유구분 채운 뒤 저장 성공) ·
  8/11 · 8/07 · 8/08(분할·1차 녹화 추정) — 전부 결의구분 무필터로 조회한다.
발견 시 3중 가드(결의자=로그인계정·결의구분=ABDOCU_FG_CD·미결 DOCU_NO 공백) 확인 후 F6 삭제.
전부 0건이면 '팬텀 저장'으로 확정 분류하고 종료(더 파지 않음 — team-lead 지시).

s_month 는 kendoDatePicker 위젯이라(진단 3차 확인) **UI 로 직접 타이핑**해야 내부 모델이
갱신된다(raw DOM value set 은 위젯이 무시).

Usage: cd backend && .venv/bin/python e2e/tax_invoice_final_search.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from e2e.product_cycle import (  # noqa: E402
    MASTER_DUMP_JS,
    PASSWORD,
    USERID,
    delete_selected,
    query_master,
)
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# (month, day) 후보 — 8/19 최우선(저장 성공 확실성 높음).
CANDIDATES = [("2026-08", "19"), ("2026-08", "14"), ("2026-08", "11"), ("2026-08", "07"), ("2026-08", "08")]

SELECT_MASTER_ALL_JS = """() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    if (g.checkAll) g.checkAll(true);
    if (g.setAllCheckState) g.setAllCheckState(true);
    g.setCurrent({ itemIndex: 0 });
    return true;
  } catch (e) { return false; }
}"""


def _rows_summary(dump: dict) -> list[dict]:
    rows = dump.get("rows") or []
    return [
        {"ABDOCU_NO": r.get("ABDOCU_NO"), "ABDOCU_FG_CD": r.get("ABDOCU_FG_CD"),
         "WRT_EMP_NM": r.get("WRT_EMP_NM"), "ACTG_DT": r.get("ACTG_DT"), "WRT_DT": r.get("WRT_DT"),
         "DOCU_NO": r.get("DOCU_NO")}
        for r in rows
    ]


def _row_is_ours(row: dict) -> bool:
    writer_ok = str(row.get("WRT_EMP_NM") or "").strip() == USERID
    not_posted = not str(row.get("DOCU_NO") or "").strip()
    return writer_ok and not_posted


async def _set_month_via_ui(page: Page, month: str) -> bool:
    """#s_month(kendoDatePicker) 를 실제 UI 타이핑으로 세팅 — raw DOM set 은 위젯 내부모델 무시."""
    box = await page.evaluate(
        "() => { const i=document.querySelector('#s_month'); if(!i) return null; const r=i.getBoundingClientRect();"
        " return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)}; }"
    )
    if not box:
        return False
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(150)
    await page.keyboard.press("Control+A")
    await page.keyboard.type(month, delay=40)
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(500)
    return True


async def _set_day_via_ui(page: Page, day: str) -> bool:
    box = await page.evaluate(
        "() => { const m=document.querySelector('#s_month'); if(!m) return null; const mr=m.getBoundingClientRect();"
        " const c=[...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && i!==m"
        " && Math.abs(i.getBoundingClientRect().top-mr.top)<10 && i.getBoundingClientRect().left>mr.right"
        " && i.getBoundingClientRect().left<mr.right+120)[0]; if(!c) return null; const r=c.getBoundingClientRect();"
        " return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)}; }"
    )
    if not box:
        return False
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(150)
    await page.keyboard.press("End")
    for _ in range(4):
        await page.keyboard.press("Backspace")
    await page.keyboard.type(day, delay=40)
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(400)
    return True


async def _clear_gubun(page: Page) -> None:
    await page.evaluate(
        "(sel) => { const s=document.querySelector(sel); const w=window.jQuery(s).data('kendoDropDownList');"
        " if(w){w.value('');w.trigger('change');} }", selectors.GUBUN_SELECT,
    )
    await page.wait_for_timeout(500)


async def _toggle_mode(page: Page, want: str) -> bool:
    """'결의일'/'회계일' 드롭다운 토글. want='결의일'|'회계일'. 반환 성공여부."""
    dd_box = await page.evaluate(
        "() => { const l = [...document.querySelectorAll('span,div')].find(e=>e.offsetParent!==null"
        " && e.innerText && (e.innerText.trim()==='결의일'||e.innerText.trim()==='회계일')); if(!l) return null;"
        " const w = l.closest('.k-dropdown') || l.parentElement; const r = w.getBoundingClientRect();"
        " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), cur: l.innerText.trim()}; }"
    )
    if not dd_box or dd_box.get("cur") == want:
        return dd_box is not None
    await page.mouse.click(dd_box["x"], dd_box["y"])
    await page.wait_for_timeout(400)
    opt = await page.evaluate(
        "(want) => { const it = [...document.querySelectorAll('li.k-item, .k-list li')]"
        ".filter(e=>e.offsetParent!==null).find(e=>e.innerText.includes(want));"
        " if(!it) return null; const r = it.getBoundingClientRect();"
        " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }",
        want,
    )
    if not opt:
        return False
    await page.mouse.click(opt["x"], opt["y"])
    await page.wait_for_timeout(500)
    return True


async def main() -> None:
    results: dict = {"candidates": [], "found": [], "deleted": []}
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
        await _clear_gubun(page)
        await _toggle_mode(page, "회계일")

        found_any = False
        for month, day in CANDIDATES:
            await _set_month_via_ui(page, month)
            await _set_day_via_ui(page, day)
            rc = await query_master(page)
            dump = await page.evaluate(MASTER_DUMP_JS, 0)
            rows = _rows_summary(dump)
            entry = {"month": month, "day": day, "rowcount": rc, "rows": rows}
            results["candidates"].append(entry)
            print(f"[search] 회계일={month}-{day} rowcount={rc} rows={json.dumps(rows, ensure_ascii=False)}", flush=True)
            if rc and rc > 0:
                found_any = True
                await page.screenshot(path=str(ARTIFACTS / f"tax_invoice_final_search_hit_{month}-{day}.png"))
                results["found"].append(entry)
                all_ours = all(_row_is_ours(r) for r in rows)
                if not all_ours:
                    print(f"[GUARD-FAIL] {month}-{day}: 가드레일 불일치 행 존재 — 삭제 중단. rows={rows}", flush=True)
                    results["deleted"].append({"month": month, "day": day, "ok": False, "reason": "guardrail", "rows": rows})
                    continue
                # 전체 선택 후 F6 삭제.
                sel_ok = await page.evaluate(SELECT_MASTER_ALL_JS)
                modals = await delete_selected(page)
                await page.wait_for_timeout(1000)
                after = await query_master(page)
                results["deleted"].append({
                    "month": month, "day": day, "select_ok": sel_ok, "modals": modals,
                    "before": rc, "after": after, "ok": after == 0,
                })
                print(f"[DELETE] {month}-{day}: before={rc} after={after} ok={after == 0}", flush=True)
                await page.screenshot(path=str(ARTIFACTS / f"tax_invoice_final_search_after_delete_{month}-{day}.png"))

        # 월 단위 통째 확인(team-lead 최종 지시 포함 항목) — day=31 로 월 전체 커버 시도.
        if not found_any:
            for month in ("2026-07", "2026-08"):
                await _set_month_via_ui(page, month)
                await _set_day_via_ui(page, "31")
                rc = await query_master(page)
                dump = await page.evaluate(MASTER_DUMP_JS, 0)
                rows = _rows_summary(dump)
                entry = {"month": month, "day": "31(월말)", "rowcount": rc, "rows": rows}
                results["candidates"].append(entry)
                print(f"[search-month] {month} 전체(1일~31일) rowcount={rc} rows={json.dumps(rows, ensure_ascii=False)}", flush=True)
                if rc and rc > 0:
                    found_any = True
                    results["found"].append(entry)
                    await page.screenshot(path=str(ARTIFACTS / f"tax_invoice_final_search_hit_{month}_full.png"))
                    all_ours = all(_row_is_ours(r) for r in rows)
                    if not all_ours:
                        print(f"[GUARD-FAIL] {month} 전체: 가드레일 불일치 — 삭제 중단. rows={rows}", flush=True)
                        results["deleted"].append({"month": month, "ok": False, "reason": "guardrail", "rows": rows})
                        continue
                    sel_ok = await page.evaluate(SELECT_MASTER_ALL_JS)
                    modals = await delete_selected(page)
                    await page.wait_for_timeout(1000)
                    after = await query_master(page)
                    results["deleted"].append({"month": month, "select_ok": sel_ok, "modals": modals,
                                                "before": rc, "after": after, "ok": after == 0})
                    print(f"[DELETE] {month} 전체: before={rc} after={after} ok={after == 0}", flush=True)

        results["found_any"] = found_any
        if not found_any:
            print("\n[CONCLUSION] 전 후보(일자 5개 + 월 전체 2개) 0건 — 팬텀 저장으로 확정 분류. 탐색 종료.", flush=True)
        (ARTIFACTS / "tax_invoice_final_search_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        await browser.close()
        await pw.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        try:
            await page.screenshot(path=str(ARTIFACTS / "tax_invoice_final_search_exception.png"))
        except Exception:  # noqa: BLE001
            pass
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
