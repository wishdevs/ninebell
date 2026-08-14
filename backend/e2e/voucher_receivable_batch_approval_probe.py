"""프로브 — 전표조회승인에서 **여러 행을 체크한 뒤 결재 1회**가 일괄 결재로 동작하는지 실측.

배경(사용자 요구 2026-07-27): 결재 순회를 건수 기반 배치로 바꾼다(하위 200 이상 단독 → 나머지는
합계 200 미만으로 묶어 일괄). 현재 그래프는 **정확히 1행만 체크**하고 결재를 열도록 D7 이
하드 가드하고 있어, 배치로 가려면 그 가드를 '체크 행 수 == 계획한 배치 크기'로 바꿔야 한다.
그 전에 ERP 가 실제로 다중 선택 결재를 받는지, 결제창(EAP)이 어떻게 뜨는지 확정한다:

  Q1. 2행 체크 후 결재 클릭 → 자식창이 **1개만** 뜨는가(문서별로 여러 개가 아니라)?
  Q2. 그 자식창에 **두 전표번호가 모두** 표시되는가(=묶여서 올라감)?
  Q3. 실패한다면 어떤 형태인가(경고 모달 / 버튼 무반응 / 첫 행만 처리)?

⚠⚠ 절대 안전 ⚠⚠
  - **상신·보관 절대 클릭 금지** — 자식창은 열어서 읽고 `close()` 만 한다(비영속).
  - EAP 임시문서(draft)가 1건 생길 수 있다(기존 단건 결재와 동일 성격·범위).
  - 저장(F7)·삭제(F6) 없음.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_receivable_batch_approval_probe.py
    E2E_BATCH_N=3 .venv/bin/python e2e/voucher_receivable_batch_approval_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.voucher_receivable import js as vjs  # noqa: E402
from app.agents.voucher_receivable import steps as vsteps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
BATCH_N = int(os.environ.get("E2E_BATCH_N", "2"))  # 체크할 행 수.

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "voucher_receivable_batch_approval.json"
SHOT = ARTIFACTS / "voucher_receivable_batch_child.png"

# 화면에 뜬 경고/확정 모달 텍스트(다중 선택 거부 시 그 문구를 잡기 위해 — 읽기 전용).
_MODAL_TEXT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const w of document.querySelectorAll('.k-window, .k-dialog')) {
    if (w.offsetParent === null) continue;
    const t = c(w.innerText);
    if (t) out.push(t.slice(0, 300));
  }
  return out;
}"""


async def main() -> int:
    settings = get_settings()
    report: dict = {"userid": USERID, "batch_n": BATCH_N}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await ctx.new_page()
        opened_pages: list = []
        ctx.on("page", lambda p: opened_pages.append(p))
        child = None
        try:
            await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)

            await vsteps.expand_condition_panel(page)
            for label, call in (
                ("작성부서", vsteps.set_dept_all(page)),
                ("회계일", vsteps.set_period_this_month(page)),
                ("작성자", vsteps.clear_writer(page)),
                ("전표상태", vsteps.set_docu_status(page)),
                ("전자결재상태", vsteps.set_gwaprvlst(page)),
            ):
                res = await call
                if not res.get("ok"):
                    print(f"[FAIL] 조회조건 {label}: {res.get('reason')}")
                    return 1
            res = await vsteps.set_docu_types(page, vsteps.DOCU_TYPES_RECEIVABLE)
            if not res.get("ok"):
                print(f"[FAIL] 조회조건 전표유형: {res.get('reason')}")
                return 1
            q = await vsteps.run_query(page)
            if not q.get("ok") or int(q["rowcount"]) < BATCH_N:
                print(f"[FAIL] 조회 결과 부족: {q}")
                return 1
            print(f"[ok] 조회 완료 — 대상 {q['rowcount']}건")

            # 대상 N행 체크(전체 해제 후) — 체크 수를 실측으로 확정한다.
            await vsteps.uncheck_all_rows(page)
            keys = []
            for i in range(BATCH_N):
                keys.append(await vsteps.read_row_key(page, i))
                if not await vsteps.check_row(page, i):
                    print(f"[FAIL] {i}행 checkRow 실패")
                    return 1
            chk = await vsteps.checked_row_indexes(page)
            report["target_docu_nos"] = keys
            report["checked"] = chk
            print(f"[체크] 대상 {keys} / 체크 상태 {chk}")
            if not (isinstance(chk, dict) and chk.get("ok") and len(chk.get("rows") or []) == BATCH_N):
                print(f"[FAIL] 다중 체크가 유지되지 않음(그리드가 단일 선택일 가능성): {chk}")
                report["verdict"] = "다중 체크 불가"
                return 1

            # 결재 클릭 → 자식창 캡처(열기·읽기·닫기만).
            before_pages = len(opened_pages)
            child = await vsteps.open_approval(page)
            report["child_opened"] = child is not None
            report["new_pages"] = len(opened_pages) - before_pages
            report["parent_modals"] = await page.evaluate(_MODAL_TEXT_JS)
            if child is None:
                print(f"[Q1] 자식창 미출현 — 부모 모달: {report['parent_modals']}")
                report["verdict"] = "다중 선택 결재 불가(자식창 미출현)"
            else:
                top = await vsteps.poll_child_ready(child)
                docu = await vsteps.read_child_docu_no(child)
                report["child_top_buttons"] = [t.get("text") for t in top] if top else []
                report["child_docu_candidates"] = docu
                try:
                    await child.screenshot(path=str(SHOT))
                    report["screenshot"] = str(SHOT)
                except Exception as exc:  # noqa: BLE001
                    report["screenshot_error"] = str(exc)[:120]
                covered = [k for k in keys if k and any(k in d for d in docu)]
                report["covered_docu_nos"] = covered
                report["verdict"] = (
                    "일괄(자식창 1개에 전 대상 표시)"
                    if len(covered) == len(keys)
                    else f"부분/불명(자식창 표시 {docu})"
                )
                print(f"[Q1] 새 자식창 {report['new_pages']}개 / 상단버튼 {report['child_top_buttons']}")
                print(f"[Q2] 자식창 전표번호 후보 {docu} → 대상 커버 {covered}")
        finally:
            if child is not None:
                await vsteps.close_child(child)  # ⚠ 상신·보관 미클릭(비영속)
            await ctx.close()
            await browser.close()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[판정] {report.get('verdict')}")
    print(f"[artifact] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
