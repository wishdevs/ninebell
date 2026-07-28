"""읽기전용 프로브 — 결재번호 맵(결의서조회승인) 수집이 **왜 실행마다 요동치는지** 확정.

사용자 리포트 배경(2026-07-27): 미지급금 법인카드에서 참조문서 단계에 도달하는 행이 없다.
실측(석대현 계정, 4회): 맵 크기가 4건 ↔ 32건으로 요동하고, 4건일 때의 키
(RN202607050001/100004/200003/220004)는 전표조회승인 행의 결의서번호
(RN202607030012/060001/070001/130001)와 **하나도 겹치지 않는다** → 처리 대상 0건.

가설: 조회조건 중 하나가 결과를 로그인 사용자/부서로 좁힌다.
  H1. 결의부서 전체선택(set_collect_dept_all) 실패 → 로그인 부서만.
  H2. 결의자 비움(clear_collect_writer) 실패 → 로그인 계정이 결의한 건만.
  H3. 회계일 기본값이 당월이 아님(범위 밖 결의서 누락).
이 프로브는 **각 스텝 직후 폼 표시값과 조회 건수**를 찍어 어느 조건이 범인인지 가른다.

⚠ 절대 안전: 조회(F2)만 실행한다. 결제·상신·저장(F7)·삭제(F6) 없음. 결제창을 열지 않는다.

Usage:
    cd backend && E2E_USERID='...' E2E_PASSWORD='...' \
        .venv/bin/python e2e/voucher_card_collect_filter_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.voucher_card import js as cjs  # noqa: E402
from app.agents.voucher_card import steps as csteps  # noqa: E402
from app.agents.voucher_receivable import js as vr_js  # noqa: E402
from app.agents.voucher_receivable import steps as vr_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.omnisol import js_lib  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "voucher_card_collect_filter.json"

# 결의서조회승인 조회조건 폼의 **현재 값 전부** — 어떤 조건이 결과를 좁히는지 눈으로 가른다.
FORM_STATE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = { fields: [], selects: [] };
  // 라벨 ↔ 같은 li/행의 입력값(코드피커 표시값 포함).
  for (const lbl of document.querySelectorAll('label')) {
    if (lbl.offsetParent === null) continue;
    const name = c(lbl.innerText);
    if (!name) continue;
    const li = lbl.closest('li') || lbl.parentElement;
    if (!li) continue;
    const vals = [...li.querySelectorAll('input')]
      .filter(i => i.offsetParent !== null || i.type === 'hidden')
      .map(i => i.value).filter(v => v !== undefined);
    out.fields.push({ label: name, values: vals.slice(0, 4) });
  }
  for (const sel of document.querySelectorAll('select')) {
    const opt = sel.options[sel.selectedIndex];
    out.selects.push({ id: sel.id || null, text: opt ? c(opt.text) : null, value: sel.value });
  }
  return out;
}"""


async def _snapshot(page, label: str, report: dict) -> None:
    """현재 폼 상태 + 가시 그리드 건수를 기록한다(읽기 전용)."""
    form = await page.evaluate(FORM_STATE_JS)
    rc = await page.evaluate(cjs.VISIBLE_MASTER_ROWCOUNT_JS)
    report.setdefault("steps", []).append({"at": label, "rowcount": rc, "form": form})
    interesting = [f for f in form["fields"] if f["label"] in ("결의부서", "결의자", "회계일", "결의구분")]
    print(f"[{label}] rowcount={rc} | {json.dumps(interesting, ensure_ascii=False)}")


async def main() -> int:
    settings = get_settings()
    report: dict = {"userid": USERID}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await ctx.new_page()
        try:
            await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)

            # 전표조회승인(일반) 조회 — 대상 행의 결의서번호를 먼저 확보한다.
            await vr_steps.expand_condition_panel(page)
            for call in (
                vr_steps.set_dept_all(page),
                vr_steps.set_period_this_month(page),
                vr_steps.clear_writer(page),
                vr_steps.set_docu_status(page),
                vr_steps.set_gwaprvlst(page),
            ):
                await call
            await vr_steps.set_docu_types(page, csteps.DOCU_TYPES_CARD)
            q = await vr_steps.run_query(page)
            rowcount = int(q.get("rowcount") or 0)
            wanted = []
            for idx in range(rowcount):
                ab = await vr_steps.read_row_abdocu_no(page, idx)
                if ab and str(ab).strip():
                    wanted.append(str(ab).strip())
            report["voucher_rowcount"] = rowcount
            report["wanted_abdocu"] = wanted
            print(f"[A] 전표조회승인 {rowcount}건 / 결의서번호 보유 {len(wanted)}건: {wanted}")

            # 결의서조회승인 탭 — 스텝을 하나씩 밟으며 폼 상태·건수를 기록한다.
            opened = await csteps.open_collect_tab(page)
            if not opened.get("ok"):
                print(f"[FAIL] 탭 도착: {opened.get('reason')}")
                return 1
            await _snapshot(page, "탭 진입 직후", report)

            dept_ok = await csteps.set_collect_dept_all(page)
            report["dept_ok"] = dept_ok
            await _snapshot(page, f"결의부서 전체선택({dept_ok})", report)

            writer_ok = await csteps.clear_collect_writer(page)
            report["writer_ok"] = writer_ok
            await _snapshot(page, f"결의자 비움({writer_ok})", report)

            gubun_ok = await csteps.set_collect_gubun_card(page)
            report["gubun_ok"] = gubun_ok
            await _snapshot(page, f"결의구분=카드({gubun_ok})", report)

            ran = await csteps.run_collect_query(page)
            report["query_ok"] = ran
            await _snapshot(page, f"조회 실행({ran})", report)

            pm = await csteps.read_payment_map(page)
            keys = sorted((pm.get("map") or {}))
            report["map_keys"] = keys
            covered = [w for w in wanted if w in (pm.get("map") or {})]
            report["covered"] = covered
            print(f"[B] 맵 {len(keys)}건 / 대상 커버 {len(covered)}/{len(wanted)}")
            print(f"[B] 맵 키: {keys[:12]}")

            # ── 진단 1: set_collect_dept_all 이 어느 단계에서 실패하는가 ──────────
            stage = {}
            stage["open_picker"] = await vr_steps._open_picker(page, csteps.COLLECT_DEPT_LABEL)
            if stage["open_picker"]:
                res_chk = await page.evaluate(vr_js.POPUP_CHECK_ALL_JS)
                stage["check_all"] = res_chk
                stage["apply"] = await vr_steps._apply_popup(page)
            stage["display_after"] = await page.evaluate(js_lib.FIELD_DISPLAY_JS, csteps.COLLECT_DEPT_LABEL)
            stage["search_btn_rect"] = await page.evaluate(
                vr_js.FIELD_SEARCH_BTN_RECT_JS, csteps.COLLECT_DEPT_LABEL)
            stage["label_visible"] = await page.evaluate(
                js_lib.FIELD_LABEL_VISIBLE_JS, csteps.COLLECT_DEPT_LABEL)
            report["dept_stage"] = stage
            print(f"[진단1] 결의부서 단계별: {json.dumps(stage, ensure_ascii=False)[:400]}")
            await csteps.run_collect_query(page)
            await _snapshot(page, "부서 전체선택 재시도 후 재조회", report)
            pm_d = await csteps.read_payment_map(page)
            cov_d = [w for w in wanted if w in (pm_d.get("map") or {})]
            print(f"[진단1] 재시도 후 맵 {len(pm_d.get('map') or {})}건 / 커버 {len(cov_d)}/{len(wanted)}")

            # ── 진단 2: 결의부서를 **비우면**(=필터 없음) 전 부서가 나오는가? ────────
            cleared_dept = await page.evaluate(
                "() => { try { const el = [...document.querySelectorAll('label')]"
                ".find(l => l.innerText.trim() === '결의부서'); const li = el && el.closest('li');"
                " const inp = li && li.querySelector('.dews-multicodepicker-text');"
                " const ctrl = inp && window.jQuery(inp.closest('[id]')).data('dewsControl');"
                " if (ctrl && ctrl.clear) { ctrl.clear(); return 'cleared'; }"
                " return inp ? 'no-control' : 'no-input'; } catch (e) { return 'err:' + e; } }")
            report["dept_clear_attempt"] = cleared_dept
            await csteps.run_collect_query(page)
            await _snapshot(page, f"결의부서 비움({cleared_dept}) 후 재조회", report)
            pm3 = await csteps.read_payment_map(page)
            cov3 = [w for w in wanted if w in (pm3.get("map") or {})]
            report["covered_after_dept_clear"] = cov3
            print(f"[진단2] 부서 비움({cleared_dept}) → 맵 {len(pm3.get('map') or {})}건 / 커버 {len(cov3)}/{len(wanted)}")

            # ── 진단 실험: 결의자/부서를 비운 뒤 다시 조회하면 늘어나는가? ─────────
            cleared = await page.evaluate(cjs.CLEAR_WRT_EMP_JS)
            await csteps.run_collect_query(page)
            await _snapshot(page, f"결의자 재비움({cleared}) 후 재조회", report)
            pm2 = await csteps.read_payment_map(page)
            keys2 = sorted((pm2.get("map") or {}))
            covered2 = [w for w in wanted if w in (pm2.get("map") or {})]
            report["map_keys_after_clear"] = keys2
            report["covered_after_clear"] = covered2
            print(f"[C] 재비움 후 맵 {len(keys2)}건 / 대상 커버 {len(covered2)}/{len(wanted)}")

            await page.screenshot(path=str(ARTIFACTS / "collect_filter_form.png"))
        finally:
            await ctx.close()
            await browser.close()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[artifact] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
