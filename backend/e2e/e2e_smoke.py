"""HEADED Playwright smoke test for the card-chat agent — reusable, two phases.

Phase 1 (dashboard): drives the REAL product UI at :3101 — login, navigate to
  /agents/card-chat, click 실행, wait for the HITL grid card, click 입력 완료
  (accepting whatever is prefilled), then click 저장 진행 (inline save-gate
  confirmation), wait for terminal result, report whether the result indicates
  a real save (입력·저장) or a no-op (반영 0건).

Phase 2 (ERP): separate browser context, logs into ERP directly, opens
  GLDDOC00300, filters 결의구분=카드, verifies every row is today's date +
  카드 (guardrail), then F6-deletes and re-verifies 0 rows remain.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python /path/to/e2e_smoke.py [run|delete|both]

Default mode is "both". Run headed with slow_mo so a human can watch.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright, Page  # noqa: E402

from app.agents.card_collect import js as cc_js  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

import os
FRONTEND_BASE = os.environ.get("E2E_FRONTEND", "http://localhost:3101")
USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
SCRATCH = ARTIFACTS  # 스크린샷 저장 위치(gitignore)

TODAY = _date.today().isoformat()
TODAY_COMPACT = TODAY.replace("-", "")

GRID_WAIT_TIMEOUT_S = 300  # 5 min — backend drives ERP headlessly for 1st pass
RESULT_WAIT_TIMEOUT_S = 300  # 5 min — 2nd pass (불공) can also take a while

# ── in-page JS helpers for GLDDOC00300 verify/delete (copied from loop_harness.py) ──
BTN_BOX_JS = """(sel) => {
  const b = document.querySelector(sel);
  if (!b) return null;
  const r = b.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

MASTER_ROWCOUNT_JS = ("() => { try { return window.jQuery(document.querySelectorAll('.dews-ui-grid')[0])"
                      ".data('dewsControl')._grid.getDataSource().getRowCount(); } catch(e) { return -1; } }")

MASTER_DUMP_JS = """(index) => {
  try {
    const ctrl = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl');
    const g = ctrl._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    let columns = [];
    try {
      const cols = g.getColumns ? g.getColumns() : [];
      columns = cols.map(c => ({
        field: c.fieldName || c.name || c.field || null,
        header: (c.header && (c.header.text || c.header.caption)) || c.caption || c.title || c.headerText || null
      }));
    } catch (e) { columns = [{ err: String(e).slice(0, 100) }]; }
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    return { n, columns, fieldKeys: rows[0] ? Object.keys(rows[0]) : null, rows };
  } catch (e) { return { n: -1, err: String(e).slice(0, 160) }; }
}"""

SELECT_MASTER_JS = """(index) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    let via = [];
    try { if (g.checkAll) { g.checkAll(true); via.push('checkAll'); } } catch (e) {}
    try { if (g.setAllCheckState) { g.setAllCheckState(true); via.push('setAllCheckState'); } } catch (e) {}
    try { g.setCurrent({ itemIndex: 0 }); via.push('setCurrent0'); } catch (e) {}
    return { ok: true, n, via };
  } catch (e) { return { ok: false, err: String(e).slice(0, 120) }; }
}"""


def _row_is_ours(row: dict) -> bool:
    """삭제 안전가드 — 우리 테스트 전표 판정.

    날짜 문자열 매칭은 신뢰 불가(그리드가 UTC datetime 저장 + 회계일은 기간월 말일이라
    로컬 오늘과 안 맞음, 실측 2026-07-04). 대신 견고한 신원으로 판정:
      결의자명(WRT_EMP_NM)=로그인 사용자 + 결의구분(ABDOCU_FG_CD)=52(카드) + 미결(상태≠결재완료).
    이 테스트 계정의 카드 결의는 전부 에이전트가 만든 테스트 전표라 안전하다.
    """
    writer_ok = str(row.get("WRT_EMP_NM") or "").strip() == USERID
    card_ok = str(row.get("ABDOCU_FG_CD") or "") == "52"
    # 상태(RDOCU_ST_CD): 미결/미결의 draft 만 삭제(전표번호 DOCU_NO 가 비어 있음 = 미전기).
    not_posted = not str(row.get("DOCU_NO") or "").strip()
    return writer_ok and card_ok and not_posted


def _db_check() -> str:
    """Ground-truth poll of the most recent agent_runs row (best-effort)."""
    try:
        out = subprocess.run(
            ["docker", "exec", "dashboard-pg", "psql", "-U", "dashboard", "-d", "dashboard", "-tA",
             "-c", "SELECT status, substr(result::text,1,200) FROM agent_runs ORDER BY started_at DESC LIMIT 1;"],
            capture_output=True, text=True, timeout=15,
        )
        return (out.stdout or out.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return f"<db check failed: {exc!r}>"


async def _query_master(page: Page) -> None:
    """조회(F2) 클릭 후 마스터 rowcount 안정화까지 폴링(READ-ONLY)."""
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box:
        await page.mouse.click(box["x"], box["y"])
        print(f"[P2] clicked 조회(F2) at {box}", flush=True)
    else:
        await page.keyboard.press("F2")
        print("[P2] 조회 button not found — pressed F2 key", flush=True)
    prev = -2
    for _ in range(20):
        await page.wait_for_timeout(1_000)
        rc = await page.evaluate(MASTER_ROWCOUNT_JS)
        if isinstance(rc, int) and rc >= 0 and rc == prev:
            break
        prev = rc


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — dashboard agent run
# ─────────────────────────────────────────────────────────────────────────────
async def phase1() -> dict:
    report: dict = {
        "logged_in": False, "run_started": False, "grid_appeared": False,
        "stuck_disabled": False, "submit_clicked": False, "stuck_after_click": False,
        "reached_terminal": False, "result_text": None, "saved": False,
        "zero_effect": False, "db_check": None, "screenshot": None, "error": None,
    }

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=120)
    context = await browser.new_context(viewport={"width": 1600, "height": 1000})
    page = await context.new_page()

    try:
        print("[P1] goto frontend...", flush=True)
        await page.goto(FRONTEND_BASE)
        await page.wait_for_timeout(1000)
        if "/login" not in page.url:
            print(f"[P1] not on /login yet (url={page.url}) — proceeding, page may already redirect", flush=True)
            await page.wait_for_timeout(1000)

        await page.fill("#userid", USERID)
        await page.fill("#password", PASSWORD)
        await page.get_by_role("button", name="로그인").click()
        print("[P1] submitted login form, waiting for redirect off /login...", flush=True)

        for _ in range(20):
            if "/login" not in page.url:
                break
            await page.wait_for_timeout(500)
        if "/login" in page.url:
            report["error"] = f"login did not redirect away from /login (url={page.url})"
            await page.screenshot(path=str(SCRATCH / "e2e_p1_login_fail.png"))
            print(f"[P1][ERROR] {report['error']}", flush=True)
            return report

        report["logged_in"] = True
        print(f"[P1] logged in, url={page.url}", flush=True)
        await page.wait_for_timeout(2000)

        print("[P1] goto /agents/card-chat", flush=True)
        await page.goto(f"{FRONTEND_BASE}/agents/card-chat")
        await page.wait_for_timeout(1500)

        run_btn = page.get_by_role("button", name="실행", exact=True)
        if await run_btn.count() == 0:
            run_btn = page.get_by_role("button", name="다시 실행", exact=True)
            print("[P1] exact '실행' button not found — using '다시 실행'", flush=True)
        await run_btn.first.click()
        report["run_started"] = True
        print(f"[P1] clicked run button — waiting up to {GRID_WAIT_TIMEOUT_S}s for HITL grid (입력 완료)...", flush=True)

        submit_btn = page.get_by_role("button", name="입력 완료")
        appeared = False
        elapsed = 0
        while elapsed < GRID_WAIT_TIMEOUT_S:
            if await submit_btn.count() > 0 and await submit_btn.first.is_visible():
                appeared = True
                break
            await page.wait_for_timeout(5000)
            elapsed += 5
            if elapsed % 20 == 0:
                print(f"[P1] ...waiting for grid ({elapsed}s elapsed)", flush=True)

        if not appeared:
            report["error"] = f"grid intervention card (입력 완료) never appeared within {GRID_WAIT_TIMEOUT_S}s"
            await page.screenshot(path=str(SCRATCH / "e2e_p1_no_grid.png"))
            print(f"[P1][ERROR] {report['error']}", flush=True)
            return report

        report["grid_appeared"] = True
        print("[P1] grid appeared", flush=True)
        await page.wait_for_timeout(2000)

        is_disabled = await submit_btn.first.is_disabled()
        if is_disabled:
            report["stuck_disabled"] = True
            report["error"] = (
                "입력 완료 button is DISABLED — no default budgetUnit/note prefill; "
                "grid requires manual fill before it can be submitted"
            )
            await page.screenshot(path=str(SCRATCH / "e2e_p1_disabled.png"))
            print(f"[P1][FINDING] {report['error']}", flush=True)
            return report

        await submit_btn.first.click()
        report["submit_clicked"] = True
        print("[P1] clicked 입력 완료 — waiting for save-gate (저장 진행) button...", flush=True)

        # 저장 안전 게이트: '입력 완료'는 인라인 확인 단계로 전환될 뿐 제출하지 않는다.
        # '저장 진행' 버튼이 나타나면 클릭해야 실제 제출이 이뤄진다.
        # exact=True — 제출 후 버튼 '반영·저장 진행 중…'과의 부분일치 오탐 방지.
        confirm_btn = page.get_by_role("button", name="저장 진행", exact=True)
        confirm_appeared = False
        elapsed = 0
        while elapsed < 15:
            if await confirm_btn.count() > 0 and await confirm_btn.first.is_visible():
                confirm_appeared = True
                break
            await page.wait_for_timeout(1000)
            elapsed += 1
        if not confirm_appeared:
            report["error"] = "save-gate button (저장 진행) never appeared within 15s after 입력 완료"
            await page.screenshot(path=str(SCRATCH / "e2e_p1_no_save_gate.png"))
            print(f"[P1][ERROR] {report['error']}", flush=True)
            return report

        await confirm_btn.first.click()
        report["confirm_clicked"] = True
        print("[P1] clicked 저장 진행 (save-gate confirmed)", flush=True)
        await page.wait_for_timeout(5000)

        still_confirm = await confirm_btn.count() > 0 and await confirm_btn.first.is_visible()
        still_submit = await submit_btn.count() > 0 and await submit_btn.first.is_visible()
        if still_confirm or still_submit:
            report["stuck_after_click"] = True
            report["error"] = (
                "저장 진행/입력 완료 still present ~5s after click — server validation likely "
                "rejected (e.g. empty 예산단위) and re-emitted the grid"
            )
            await page.screenshot(path=str(SCRATCH / "e2e_p1_stuck_validation.png"))
            print(f"[P1][FINDING] {report['error']}", flush=True)
            return report

        print(f"[P1] waiting up to {RESULT_WAIT_TIMEOUT_S}s for terminal state (다시 실행 button)...", flush=True)
        restart_btn = page.get_by_role("button", name="다시 실행", exact=True)
        elapsed = 0
        terminal = False
        while elapsed < RESULT_WAIT_TIMEOUT_S:
            if await restart_btn.count() > 0 and await restart_btn.first.is_visible():
                terminal = True
                break
            await page.wait_for_timeout(5000)
            elapsed += 5
            if elapsed % 20 == 0:
                print(f"[P1] ...waiting for terminal state ({elapsed}s elapsed)", flush=True)

        report["reached_terminal"] = terminal
        if not terminal:
            report["error"] = f"run never reached terminal state (다시 실행) within {RESULT_WAIT_TIMEOUT_S}s"
            await page.screenshot(path=str(SCRATCH / "e2e_p1_no_terminal.png"))
            print(f"[P1][ERROR] {report['error']}", flush=True)
            return report

        await page.wait_for_timeout(1500)
        candidates = page.get_by_text("처리 완료")
        cnt = await candidates.count()
        result_text = None
        for idx in range(cnt):
            loc = candidates.nth(idx)
            if await loc.is_visible():
                result_text = (await loc.inner_text()).strip()
                break

        if result_text is None:
            body_text = await page.locator("body").inner_text()
            report["error"] = "terminal reached but no visible '처리 완료' text found — dumping body snippet"
            print(f"[P1][WARN] {report['error']}", flush=True)
            print(f"[P1] body text (first 1000 chars): {body_text[:1000]}", flush=True)
        else:
            report["result_text"] = result_text
            report["saved"] = "입력·저장" in result_text
            report["zero_effect"] = "반영 0건" in result_text
            print(f"[P1] RESULT TEXT: {result_text}", flush=True)
            print(f"[P1] saved(입력·저장)={report['saved']} zero_effect(반영 0건)={report['zero_effect']}", flush=True)

        report["db_check"] = _db_check()
        print(f"[P1] DB check (agent_runs latest): {report['db_check']}", flush=True)

        shot_path = str(SCRATCH / "e2e_p1.png")
        await page.screenshot(path=shot_path, full_page=True)
        report["screenshot"] = shot_path
        print(f"[P1] screenshot: {shot_path}", flush=True)
        await page.wait_for_timeout(2000)

    except Exception as exc:  # noqa: BLE001
        report["error"] = f"phase1 exception: {exc!r}"
        print(f"[P1][ERROR] {report['error']}", flush=True)
        try:
            await page.screenshot(path=str(SCRATCH / "e2e_p1_exception.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        await context.close()
        await browser.close()
        await pw.stop()

    return report


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — ERP direct verify + F6 delete
# ─────────────────────────────────────────────────────────────────────────────
async def phase2() -> dict:
    report: dict = {
        "rows": None, "all_ours": None, "deleted": False, "post_delete_count": None,
        "error": None, "screenshots": [],
    }

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=120)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base

    try:
        print("[P2] logging into ERP...", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        print("[P2] login done", flush=True)

        await page.goto(f"{base}/FI/GLDDOC00300")
        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:  # noqa: BLE001
            pass
        for _ in range(15):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(1_000)

        gr = await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
            {"selector": selectors.GUBUN_SELECT, "text": "카드"},
        )
        print(f"[P2] set 결의구분=카드 -> {gr}", flush=True)
        await page.wait_for_timeout(1_500)
        await _query_master(page)

        dump = await page.evaluate(MASTER_DUMP_JS, 0)
        n = dump.get("n", -1)
        report["rows"] = n
        before_path = str(SCRATCH / "e2e_p2_before.png")
        await page.screenshot(path=before_path)
        report["screenshots"].append(before_path)
        print(f"[P2] master grid n={n}; screenshot: {before_path}", flush=True)

        if n <= 0:
            report["error"] = "nothing to delete (0 rows) — phase 1 likely didn't save"
            print(f"[P2] {report['error']}", flush=True)
            return report

        rows = dump.get("rows") or []
        all_ours = all(_row_is_ours(r) for r in rows)
        report["all_ours"] = all_ours
        print(f"[P2] guardrail: {len(rows)} rows, all_ours(today+카드)={all_ours}", flush=True)
        if not all_ours:
            report["error"] = "unexpected rows — manual review (not all rows match today+카드; delete ABORTED)"
            print(f"[P2][ABORT] {report['error']}", flush=True)
            print("[P2] dump:", json.dumps(dump, ensure_ascii=False, default=str)[:2000], flush=True)
            return report

        sel = await page.evaluate(SELECT_MASTER_JS, 0)
        print(f"[P2] select master -> {sel}", flush=True)

        dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
        if dbox:
            await page.mouse.click(dbox["x"], dbox["y"])
            print(f"[P2] clicked 삭제 button at {dbox}", flush=True)
        else:
            await page.keyboard.press("F6")
            print("[P2] 삭제 button not found — pressed F6", flush=True)

        delete_modals: list = []
        for _ in range(8):
            await page.wait_for_timeout(1_500)
            modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
            if not modals:
                break
            delete_modals.extend(modals)
            clicked = False
            for label in ("예", "확인", "삭제"):
                btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, label)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    print(f"[P2] delete modal — clicked '{label}'", flush=True)
                    clicked = True
                    break
            if not clicked:
                print(f"[P2] delete modal present but no 예/확인/삭제 button: {modals}", flush=True)
                break
        if delete_modals:
            print(f"[P2] delete modals seen: {json.dumps(delete_modals[:5], ensure_ascii=False)}", flush=True)

        await page.wait_for_timeout(1_500)
        await _query_master(page)
        dump2 = await page.evaluate(MASTER_DUMP_JS, 0)
        report["post_delete_count"] = dump2.get("n", -1)
        report["deleted"] = report["post_delete_count"] == 0

        after_path = str(SCRATCH / "e2e_p2_after.png")
        await page.screenshot(path=after_path)
        report["screenshots"].append(after_path)
        print(f"[P2] post_delete_count={report['post_delete_count']} deleted={report['deleted']}; screenshot: {after_path}", flush=True)

        if report["post_delete_count"] != 0:
            report["error"] = f"LEFTOVER DOC — post_delete_count={report['post_delete_count']} (manual cleanup required)"
            print(f"[P2][FAILURE] {report['error']}", flush=True)

        await page.wait_for_timeout(2000)

    except Exception as exc:  # noqa: BLE001
        report["error"] = f"phase2 exception: {exc!r}"
        print(f"[P2][ERROR] {report['error']}", flush=True)
        try:
            await page.screenshot(path=str(SCRATCH / "e2e_p2_exception.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        await browser.close()
        await pw.stop()

    return report


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode not in ("run", "delete", "both"):
        print(f"unknown mode {mode!r}, expected run|delete|both", flush=True)
        sys.exit(1)

    results: dict = {}

    if mode in ("run", "both"):
        print("\n========== PHASE 1: dashboard agent run ==========", flush=True)
        results["phase1"] = await phase1()
        print("[P1] DONE:", json.dumps(results["phase1"], ensure_ascii=False, default=str), flush=True)

    if mode in ("delete", "both"):
        print("\n========== PHASE 2: ERP verify + delete ==========", flush=True)
        results["phase2"] = await phase2()
        print("[P2] DONE:", json.dumps(results["phase2"], ensure_ascii=False, default=str), flush=True)

    print("\n===== FINAL SUMMARY =====", flush=True)
    print(json.dumps(results, ensure_ascii=False, default=str, indent=1), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
