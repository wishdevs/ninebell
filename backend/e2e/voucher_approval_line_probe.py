"""D5-1 결재라인 교차 지정 e2e 프로브 — 정식 스텝(ensure_cross_approval_line) 검증.

실측 이력(2026-08-21): tmp 프로브 approval_line_probe_1/2/4a/4b + cleanup 으로 모달 구조·
캔버스 산식·비영속을 확정한 뒤, 이 파일이 **정식 스텝 경로**를 같은 사이클로 재검증한다.

사이클: login(이트라이브2) → 조회 → **전 행 체크(배치 재현, E2E_ROWS 로 축소 가능)** →
결제창 열기 → **자식 뷰포트 1920×1500 강제(라이브 러너 CHILD_VIEWPORT 와 동일)** →
ensure_cross_approval_line(이트라이브 추가 + 전표 헤더 검증) → **상신 없이 close_child** → 종료.
지정은 비영속(상신 전 닫으면 소멸 — 실측 확정)이라 별도 정리가 필요 없다.

⚠ 라이브 패리티(2026-08-21 회귀 교훈): 러너는 부모 1920×1200(LIVE_VIEWPORT)·자식 1920×1500
(CHILD_VIEWPORT 강제 리사이즈)라 소형 창 검증만으론 좌표 가정이 라이브에서만 터진다. 이
프로브는 **러너와 같은 크기 + 배치(다건) 자식 문서**를 기본값으로 재현한다.

⚠ 절대 안전: 상신·보관 미클릭. F7/F6 없음. EAP draft 잔존은 알려진 이슈(PROCESS.md)로 무시.
실행: cd backend && .venv/bin/python e2e/voucher_approval_line_probe.py
env: E2E_USERID(기본 이트라이브2) / E2E_PASSWORD / E2E_HEADLESS(기본 1) / E2E_ROWS(기본 0=전부)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.voucher_receivable import steps as vsteps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
# 체크할 행 수(기본 10 — 다건 배치 재현). ⚠ 전 건 체크 금지: ERP 가 "전표 상세내역 200 건
# 이하만 결재 상신 가능" 다이얼로그로 결제창을 거부한다(실측 2026-08-21 — 상세 6044건 전표
# 포함 시). 실제 에이전트는 count_details 로 하위 200 기준 묶음을 계획해 이 제한을 지킨다.
ROWS = int(os.environ.get("E2E_ROWS", "10"))
# 라이브 러너 패리티 — app/live/runner.py LIVE_VIEWPORT / CHILD_VIEWPORT 와 동일하게 유지.
LIVE_VIEWPORT = {"width": 1920, "height": 1200}
CHILD_VIEWPORT = {"width": 1920, "height": 1500}

ARTIFACTS = Path(__file__).parent / "artifacts"
OUT = ARTIFACTS / "voucher_approval_line_probe.json"


async def main() -> int:
    settings = get_settings()
    report: dict = {"userid": USERID}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
        page = await ctx.new_page()
        child = None
        try:
            await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)

            await vsteps.expand_condition_panel(page)
            for label, call in (
                ("작성부서", vsteps.set_dept_all(page)),
                ("회계일", vsteps.set_period(page, "20260801", "20260831")),
                ("작성자", vsteps.clear_writer(page)),
                ("전표상태", vsteps.set_docu_status(page)),
                ("전자결재상태", vsteps.set_gwaprvlst(page)),
            ):
                res = await call
                if not res.get("ok"):
                    print(f"[FAIL] {label}: {res.get('reason')}")
                    return 1
            res = await vsteps.set_docu_types(page, vsteps.DOCU_TYPE_DEFAULTS)
            if not res.get("ok"):
                print(f"[FAIL] 전표유형: {res.get('reason')}")
                return 1

            q = await vsteps.run_query(page)
            if not q.get("ok") or int(q.get("rowcount", 0)) < 1:
                await vsteps.set_period(page, "20260701", "20260731")
                q = await vsteps.run_query(page)
            if not q.get("ok") or int(q.get("rowcount", 0)) < 1:
                print(f"[FAIL] 대상 전표 없음: {q}")
                return 1
            print(f"[ok] 조회 {q['rowcount']}건")

            await vsteps.uncheck_all_rows(page)
            report["target_docu_no"] = await vsteps.read_row_key(page, 0)
            n_check = int(q["rowcount"]) if ROWS <= 0 else min(ROWS, int(q["rowcount"]))
            for i in range(n_check):
                if not await vsteps.check_row(page, i):
                    print(f"[FAIL] checkRow({i})")
                    return 1
            report["checked_rows"] = n_check
            # 배치 노드와 동일한 체크 상태 확인 읽기 — 그리드 동기화를 강제하는 부수효과 포함.
            chk = await vsteps.checked_row_indexes(page)
            got = len(chk.get("rows") or []) if isinstance(chk, dict) else "?"
            print(f"[ok] {n_check}행 체크(배치 재현, 확인 {got}행)")

            # 연속 checkRow(setCurrent)가 띄우는 로딩 오버레이가 결재 클릭을 가로챈다
            # (D7 근본원인과 동일) — 소거 대기 후 열고, 실패 시 1회 더 정착 후 재시도.
            await vsteps.wait_loading_overlay_gone(page)
            child = await vsteps.open_approval(page)
            if child is None:
                await asyncio.sleep(2.0)
                await vsteps.wait_loading_overlay_gone(page)
                child = await vsteps.open_approval(page)
            if child is None:
                rect = None
                try:
                    from app.agents.voucher_receivable import js as vjs

                    rect = await page.evaluate(vjs.APPROVAL_BTN_RECT_JS)
                except Exception as exc:  # noqa: BLE001
                    rect = f"eval 실패: {exc}"
                pages_n = len(page.context.pages)
                shot = ARTIFACTS / "voucher_approval_line_probe_openfail.png"
                try:
                    await page.screenshot(path=str(shot))
                except Exception:  # noqa: BLE001
                    pass
                print(f"[FAIL] 결제창 미출현 — rect={rect} context_pages={pages_n} shot={shot}")
                return 1
            # 라이브 러너 패리티 — _cast_child 와 동일하게 자식 뷰포트 강제.
            try:
                await child.set_viewport_size(CHILD_VIEWPORT)
            except Exception as exc:  # noqa: BLE001
                print(f"[경고] 자식 뷰포트 강제 실패(계속): {exc}")
            await vsteps.poll_child_ready(child)

            line = await vsteps.ensure_cross_approval_line(child, USERID)
            report["line"] = line
            print(f"[결과] ensure_cross_approval_line: {line}")
            shot = ARTIFACTS / "voucher_approval_line_probe_after.png"
            try:
                await child.screenshot(path=str(shot))
                report["screenshot"] = str(shot)
            except Exception as exc:  # noqa: BLE001
                report["screenshot_error"] = str(exc)[:200]
            if not line.get("ok"):
                return 1
            if line.get("skipped"):
                print("[정보] 대상 계정이 아니라 지정을 건너뛰었습니다(E2E_USERID 확인).")
        finally:
            if child is not None:
                # 상신 미클릭 → 지정 비영속 소멸(정리 불필요).
                await vsteps.close_child(child)
            await ctx.close()
            await browser.close()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"[artifact] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
