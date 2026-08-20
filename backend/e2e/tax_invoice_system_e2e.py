"""시스템 e2e — tax-invoice **제품 경로** 실전 검증(대시보드 UI → POST 실행 → 라이브 러너 → 저장).

이제까지의 스모크(`tax_invoice_smoke_cycle.py`)는 `build_tax_invoice_graph()` 를 스크립트가
직접 `ainvoke` 했다 — `runs.py` params 수집·러너 큐·SSE 스크린캐스트·`agent_runs` 기록을 전혀
타지 않는다. 이 스크립트는 그 제품 경로 자체가 실제로 동작하는지 확인한다(팀 지시 2026-08-19).

시나리오는 `SCENARIO` 로 고른다:
  - PRE22  : 발행 전(22)·과세, 무개입 완주 — 가장 검증된 경로. 전표 저장까지 확인.
  - POST03 : 발행 후(03)·과세. 이 환경은 전자발행 데이터가 0건이라 저장은 확인 대상이 아니다 —
             steps.py 수정(팝업 조회 버튼 부분일치) 후 "조회 버튼을 찾지 못했습니다" 크래시가
             사라지고 `invoice_pick.py` 의 **우아한 종료**(0건 안내 에러)로 끝나는지만 본다.
  - POST04 : 발행 후(04)·비과세 — 사유구분 필드(기본 "일반면세") 노출을 확인. 나머지는 POST03 동일.
  - SPLIT11: 발행 후(11)·분할·과세 — 분할 계획 섹션(2행) 폼이 정상 동작하는지가 실검증 대상.
             마지막 행은 금액 미입력(차액반영 계약). 나머지는 POST03 과 동일하게 0건 종료 기대.

SKIP_CLEANUP=1 이면 phase2(ERP 정리)를 생략한다 — 여러 시나리오를 연달아 돌릴 때 마지막에
한 번만 정리하기 위함(팀 지시 2026-08-19). 전표가 실제로 안 생기는 시나리오(POST03/04/SPLIT11)
에 한해서만 쓸 것 — PRE22 는 항상 정리한다.

이번 검증의 진짜 목적은 **제품 경로의 결함 발견**이다(폼 검증 오류·라이브 표시 문제 등) —
PRE22 저장 성공 자체는 스모크 20/20 으로 이미 확인됐다.

⚠ 안전 수칙
  - **시나리오당 1회만 실행**(시스템 검증 목적). 반복 사이클이 필요하면 `tax_invoice_smoke_cycle.py`.
  - 저장된 전표는 phase2 `erp_verify_and_delete`(3중 가드+F6+잔존0)로 반드시 정리 — 이 스크립트가
    F7 을 직접 누르지 않는다(제품 그래프가 누른다), 정리는 표준 e2e 삭제 경로로만.
  - 상신 절대 금지 — 이 경로엔 상신 버튼 자체가 없다(저장까지만).

env: product_cycle.py 와 동일(E2E_FRONTEND/E2E_USERID/E2E_PASSWORD/E2E_HEADLESS/E2E_RUN_TIMEOUT_S).
     SCENARIO=PRE22(기본)|POST03|POST04|SPLIT11 · SKIP_CLEANUP=1 이면 phase2 생략.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from e2e.product_cycle import (  # noqa: E402
    ART,
    FRONTEND_BASE,
    HEADLESS,
    PASSWORD,
    RESULT_WAIT_TIMEOUT_S,
    SLOW_MO,
    USERID,
    db_latest_run,
    db_run_by_id,
    erp_verify_and_delete,
    open_agent,
    set_date,
    submit_pre_run,
)

SCENARIO = os.environ.get("SCENARIO", "PRE22").strip().upper()
SKIP_CLEANUP = os.environ.get("SKIP_CLEANUP", "0").strip() == "1"
TAG = f"tax_invoice_system_e2e_{SCENARIO.lower()}"
AGENT_ID = "tax-invoice"
WORKFLOW_ID = "tax-invoice"
GUBUN_LABEL = "세금계산서"
FG_CODE = "51"

# 대시보드 UI 표준 데스크톱 뷰포트(ERP 자동화 스크립트의 1600×1000 과 다르다 — 팀 지시).
VIEWPORT = {"width": 1440, "height": 900}

TODAY = date.today().isoformat()

# 공통 예산단위·프로젝트(4 시나리오 전부 동일 — 팀 지시).
_BUDGET = {"budget_query": "임원실", "budget_match": "임원실"}
_PROJECT = {"project_query": "800", "project_match": "판매관리비"}

# 발행 전(22)은 거래처명·공급가액·회계일을 직접 채운다(isBefore 전용 필드).
# 발행 후(03/04/11)는 그 필드들이 폼에 아예 렌더되지 않는다 — 기간은 포털 카드가 기본값
# (이번 달)으로 채우고, 예산단위·프로젝트·적요만 공통 필수다.
PARAMS = {
    "PRE22": {
        "portal_code": "22",  # 발행 전·과세(무분할) — 포털 카드 라벨 "과세".
        "partner_name": "코웨이(주)",
        "supply_amount": "41000",
        "note": "시스템e2e검증",
        **_BUDGET,
        **_PROJECT,
    },
    "POST03": {
        "portal_code": "03",  # 발행 후·과세(무분할) — 포털 카드 라벨 "세금계산서".
        "note": "시스템e2e검증(발행후우아종료)",
        **_BUDGET,
        **_PROJECT,
    },
    "POST04": {
        "portal_code": "04",  # 발행 후·비과세(무분할) — 포털 카드 라벨 "계산서".
        "note": "시스템e2e검증(비과세)",
        **_BUDGET,
        **_PROJECT,
    },
    "SPLIT11": {
        "portal_code": "11",  # 발행 후·분할·과세 — 포털 카드 라벨 "과세"(발행 후·분할 그룹).
        "note": "시스템e2e검증(분할)",
        **_BUDGET,
        **_PROJECT,
        # 마지막 행은 차액반영 계약(amount 키 없음 — 폼에도 입력칸 자체가 없다).
        "split_rows": [
            {"note": "분할1", "cost_center": "임원실", "amount": "20000", **_PROJECT},
            {"note": "분할2", "cost_center": "임원실", **_PROJECT},
        ],
    },
}[SCENARIO]

# 라이브 실행 관찰 — 종료 대기 중 이 간격으로 스크린샷을 남긴다(요청: 3~4장 확보).
PROGRESS_SHOT_INTERVAL_S = 20


async def _complete_signup(page: Page) -> None:
    """가입 리다이렉트 방어 처리 — 이름/부서는 읽기전용(옴니솔 프로필 자동), 약관만 체크 후 제출."""
    checkbox = page.locator('input[type="checkbox"]')
    await checkbox.wait_for(state="visible", timeout=10_000)
    await checkbox.check()
    await page.get_by_role("button", name="가입 완료").click()


async def _login(page: Page) -> dict:
    """대시보드 로그인 — 첫 접속 가입 리다이렉트를 감지해 화면 그대로 완료(방어 경로)."""
    out: dict = {"signup_triggered": False, "signup_screenshot": None}
    await page.goto(FRONTEND_BASE)
    await page.wait_for_timeout(1_000)
    await page.fill("#userid", USERID)
    await page.fill("#password", PASSWORD)
    await page.get_by_role("button", name="로그인").click()
    for _ in range(40):
        if "/login" not in page.url:
            break
        await page.wait_for_timeout(500)
    if "/signup" in page.url:
        out["signup_triggered"] = True
        shot = str(ART / f"{TAG}_signup.png")
        await page.screenshot(path=shot, full_page=True)
        out["signup_screenshot"] = shot
        print(f"[E2E] 가입 리다이렉트 감지 — {shot}, 안내대로 완료 진행", flush=True)
        await _complete_signup(page)
        for _ in range(40):
            if "/login" not in page.url and "/signup" not in page.url:
                break
            await page.wait_for_timeout(500)
    if "/login" in page.url or "/signup" in page.url:
        raise RuntimeError(f"로그인 미완료 — url={page.url}")
    return out


async def _enable_debug_mode(page: Page) -> None:
    """DEBUG_ONLY 에이전트(tax-invoice) 노출 — localStorage 플래그 후 리로드(팀 지시 방식)."""
    await page.evaluate("() => localStorage.setItem('nb_debug_mode', '1')")
    await page.reload()
    await page.wait_for_timeout(1_000)


async def _pick_combo(page: Page, index: int, query: str, match: str) -> None:
    """CatalogCombobox 실조작 — **Radix Popover(포털) 대응** 로컬 재구현.

    ⚠ product_cycle.py 의 공유 `pick_combo()` 는 트리거의 **형제(following-sibling) div** 로
    팝업을 찾는다(옛 자체 absolute 팝업 가정). tax-invoice 가 쓰는 CatalogCombobox 는 이미
    Radix Popover(포털, document.body 하위에 렌더링)로 바뀌어 형제 탐색이 실패한다(실측
    2026-08-19, `catalog-combobox.tsx` 자체 주석에도 이 마이그레이션이 명시돼 있음). 다른
    문서종류가 공유하는 product_cycle.py 는 건드리지 않고, 이 스크립트 안에서만 고친다.
    """
    trigger = page.locator('button[title="검색하여 선택"]').nth(index)
    await trigger.wait_for(state="visible", timeout=10_000)
    await trigger.click()

    box = page.get_by_placeholder("자주쓰는 필터 / ERP 검색어")
    await box.wait_for(state="visible", timeout=5_000)
    pop = page.locator("[data-radix-popper-content-wrapper]").filter(has=box)
    await box.fill(query)
    await page.wait_for_timeout(400)

    option = pop.get_by_role("button").filter(has_text=match)
    if await option.count() == 0:
        await pop.get_by_role("button", name="검색").click()
        for _ in range(30):
            await page.wait_for_timeout(500)
            if await option.count() > 0:
                break
    if await option.count() == 0:
        raise RuntimeError(f"콤보박스에서 '{match}' 옵션을 찾지 못했습니다(query={query!r}).")
    await option.first.click()
    await page.wait_for_timeout(300)
    shown = (await trigger.inner_text()).strip()
    if match not in shown:
        raise RuntimeError(f"콤보박스 선택 반영 실패 — 기대 '{match}', 표시 '{shown}'")


async def _fill_split_rows(page: Page) -> None:
    """SPLIT11 전용 — 분할 계획 행 채움. 예산단위(index0)·상단 프로젝트(index1) 다음부터
    행마다 프로젝트 콤보가 하나씩 늘어난다(index2, index3, …). 마지막 행은 amount 키가 없으면
    입력칸 자체가 없다(차액반영 — 폼이 정적 표시로 대체)."""
    combo_index = 2
    for i, row in enumerate(PARAMS["split_rows"]):
        n = i + 1
        await page.get_by_label(f"{n}행 적요").fill(row["note"])
        await _pick_combo(page, combo_index, row["project_query"], row["project_match"])
        combo_index += 1
        await page.get_by_label(f"{n}행 비용센터").fill(row["cost_center"])
        if "amount" in row:
            await page.get_by_label(f"{n}행 공급가액").fill(row["amount"])


async def _fill_form(page: Page) -> dict:
    """실행 전 폼 — 포털 카드 선택 후 필드 채움. 시나리오별 결함 관측을 반환한다.

    ⚠ 이전 제출 이력이 있으면(`initialParams` 복원) 폼이 포털 화면이 아니라 **질문 행 화면으로
    바로 열린다**(entryMode 초기값이 value.issue!==null 이면 'form' — 실측 2026-08-19). 포털
    카드가 안 보이면 "증빙유형 코드로 바로 선택" 버튼으로 포털 화면으로 되돌린 뒤 고른다.
    """
    observations: dict = {}
    portal_btn = page.get_by_role("button", name="증빙유형 코드로 바로 선택")
    if await portal_btn.count() > 0 and await portal_btn.first.is_visible():
        await portal_btn.first.click()
        await page.wait_for_timeout(300)

    card = page.locator("button").filter(has=page.get_by_text(PARAMS["portal_code"], exact=True))
    await card.first.wait_for(state="visible", timeout=15_000)
    await card.first.click()
    await page.wait_for_timeout(300)

    if SCENARIO == "PRE22":
        # 발행 전 전용 필드(isBefore) — 발행 후는 이 셋이 폼에 렌더되지 않는다.
        await page.fill("#tax-invoice-partner", PARAMS["partner_name"])
        await page.get_by_label("공급가액").fill(PARAMS["supply_amount"])

    await _pick_combo(page, 0, PARAMS["budget_query"], PARAMS["budget_match"])
    await _pick_combo(page, 1, PARAMS["project_query"], PARAMS["project_match"])

    await page.fill("#tax-invoice-note", PARAMS["note"])

    if SCENARIO == "PRE22":
        await set_date(page, "회계일", TODAY)
    # 발행 후는 기간(이번 달)이 포털 카드 클릭으로 이미 채워져 있다 — 추가 조작 불필요.

    if SCENARIO == "POST04":
        reason = page.locator("#tax-invoice-exempt-reason")
        observations["exempt_reason_field_visible"] = await reason.count() > 0 and await reason.is_visible()
        if observations["exempt_reason_field_visible"]:
            observations["exempt_reason_value"] = (await reason.input_value()).strip()

    if SCENARIO == "SPLIT11":
        split_section = page.get_by_text("비용분할 계획")
        observations["split_section_visible"] = (
            await split_section.count() > 0 and await split_section.first.is_visible()
        )
        await _fill_split_rows(page)

    return observations


async def _wait_terminal_with_progress_shots(page: Page, run_id: str, timeout_s: int) -> dict:
    """DB 종결 대기 + 주기적 스크린샷 + 발행 후 계산서 선택 HITL(kind=multiselect) 자동 처리.

    HITL 옵션 버튼(``aria-pressed`` 마커 — LiveChoiceCard 고유)이 나타나면 1회만: 스크린샷 →
    첫 옵션 선택 → 스크린샷 → '선택 확인' 제출. PRE22/SPLIT11(HITL 없음)은 그냥 지나간다.
    """
    out: dict = {
        "terminal": False, "db_status": None, "ui_status": None,
        "result_text": None, "fail_reason": None, "progress_shots": [],
        "hitl": {"appeared": False, "options_count": None, "chosen_option_text": None,
                 "screenshot": None, "selected_screenshot": None, "submit_clicked": False},
    }
    import asyncio

    elapsed = 0
    next_shot_at = 0
    shot_n = 0
    hitl_handled = False
    option_btn = page.locator("button[aria-pressed]")
    while elapsed < timeout_s:
        row = db_run_by_id(run_id)
        st = (row or {}).get("status")

        if not hitl_handled and await option_btn.count() > 0:
            hitl_handled = True
            out["hitl"]["appeared"] = True
            n = await option_btn.count()
            out["hitl"]["options_count"] = n
            shot = str(ART / f"{TAG}_hitl_options.png")
            await page.screenshot(path=shot, full_page=True)
            out["hitl"]["screenshot"] = shot
            print(f"[E2E] HITL 개입 감지 — 옵션 {n}개, 스크린샷 {shot}", flush=True)
            out["hitl"]["chosen_option_text"] = (await option_btn.first.inner_text()).strip()
            await option_btn.first.click()
            await page.wait_for_timeout(300)
            shot2 = str(ART / f"{TAG}_hitl_selected.png")
            await page.screenshot(path=shot2, full_page=True)
            out["hitl"]["selected_screenshot"] = shot2
            submit_btn = page.get_by_role("button", name="선택 확인", exact=False)
            if await submit_btn.count() > 0 and await submit_btn.first.is_visible():
                await submit_btn.first.click()
                out["hitl"]["submit_clicked"] = True
                print(
                    f"[E2E] HITL 1행 선택({out['hitl']['chosen_option_text'][:60]!r}) → "
                    "'선택 확인' 제출",
                    flush=True,
                )
            else:
                print("[E2E][WARN] HITL 옵션은 떴으나 '선택 확인' 버튼을 못 찾음", flush=True)
            await page.wait_for_timeout(500)

        if elapsed >= next_shot_at:
            shot_n += 1
            path = str(ART / f"{TAG}_progress{shot_n}.png")
            try:
                await page.screenshot(path=path, full_page=True)
                out["progress_shots"].append(path)
                print(f"[E2E] 진행 스크린샷 {path} (elapsed={elapsed}s status={st})", flush=True)
            except Exception as exc:  # noqa: BLE001 — 관찰 실패가 판정을 막으면 안 된다.
                print(f"[E2E] 진행 스크린샷 실패: {exc!r}", flush=True)
            next_shot_at = elapsed + PROGRESS_SHOT_INTERVAL_S
        if st in ("succeeded", "failed", "cancelled"):
            out["terminal"] = True
            out["db_status"] = st
            break
        await asyncio.sleep(3)
        elapsed += 3
    if not out["terminal"]:
        return out
    await page.wait_for_timeout(1_500)
    try:
        banner = page.get_by_text("실행 실패 — 사유")
        if await banner.count() > 0 and await banner.first.is_visible():
            out["ui_status"] = "failed"
            out["fail_reason"] = (await banner.first.locator("xpath=..").inner_text()).strip()[:600]
        else:
            out["ui_status"] = out["db_status"]
        done = page.get_by_text("처리 완료")
        for i in range(await done.count()):
            loc = done.nth(i)
            if await loc.is_visible():
                out["result_text"] = (await loc.inner_text()).strip()[:600]
                break
    except Exception:  # noqa: BLE001 — UI 텍스트 수집 실패는 판정에 영향 없음(판정은 DB).
        pass
    return out


async def main() -> None:
    report: dict = {
        "scenario": SCENARIO, "login": None, "debug_mode": False, "form_filled": False,
        "form_observations": None, "submitted": False, "run_id": None, "term": None,
        "console_errors": [], "final_screenshot": None, "doc_no_guess": None,
        "p1_error": None, "cleanup": None,
    }

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
    ctx = await browser.new_context(viewport=VIEWPORT)
    page = await ctx.new_page()

    console_errors: list[dict] = []
    page.on(
        "console",
        lambda msg: console_errors.append({"type": msg.type, "text": msg.text})
        if msg.type in ("error", "warning")
        else None,
    )
    page.on("pageerror", lambda exc: console_errors.append({"type": "pageerror", "text": str(exc)}))

    try:
        print(f"[E2E] 대시보드 로그인({FRONTEND_BASE}, 계정={USERID})…", flush=True)
        report["login"] = await _login(page)
        print(f"[E2E] 로그인 완료 url={page.url}", flush=True)

        await _enable_debug_mode(page)
        report["debug_mode"] = True
        print("[E2E] 디버그 모드 on(localStorage nb_debug_mode=1) + 리로드", flush=True)

        run_before = db_latest_run(WORKFLOW_ID)

        print(f"[E2E] /agents/{AGENT_ID} 진입 — 실행 전 입력 폼 대기", flush=True)
        await open_agent(page, AGENT_ID)
        pre_shot = str(ART / f"{TAG}_p1_prerun.png")
        await page.screenshot(path=pre_shot, full_page=True)
        print(f"[E2E] pre-run 폼 스크린샷 {pre_shot}", flush=True)

        report["form_observations"] = await _fill_form(page)
        report["form_filled"] = True
        form_shot = str(ART / f"{TAG}_p1_form_filled.png")
        await page.screenshot(path=form_shot, full_page=True)
        print(f"[E2E] 폼 입력 완료 스크린샷 {form_shot}", flush=True)

        await submit_pre_run(page)
        report["submitted"] = True
        print("[E2E] 실행 클릭", flush=True)

        before_id = (run_before or {}).get("id")
        run_id = None
        for _ in range(20):
            latest = db_latest_run(WORKFLOW_ID)
            if latest and latest.get("id") and latest.get("id") != before_id:
                run_id = latest["id"]
                break
            await page.wait_for_timeout(1_000)
        report["run_id"] = run_id
        if run_id is None:
            report["p1_error"] = "실행 클릭 후 20s 안에 새 agent_runs 행이 나타나지 않음."
        else:
            print(f"[E2E] agent_runs 확인 run={run_id[:8]} — 종료까지 최대 {RESULT_WAIT_TIMEOUT_S}s 대기", flush=True)
            term = await _wait_terminal_with_progress_shots(page, run_id, RESULT_WAIT_TIMEOUT_S)
            report["term"] = term
            final_shot = str(ART / f"{TAG}_p1_final.png")
            await page.screenshot(path=final_shot, full_page=True)
            report["final_screenshot"] = final_shot
            print(f"[E2E] 최종 스크린샷 {final_shot} term={json.dumps(term, ensure_ascii=False)[:400]}", flush=True)
    except Exception as exc:  # noqa: BLE001 — 실패도 리포트로 남긴다.
        report["p1_error"] = f"{report.get('p1_error') or ''} / 예외: {exc!r}".strip(" /")
        try:
            await page.screenshot(path=str(ART / f"{TAG}_p1_exception.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
        print(f"[E2E][ERROR] phase1 예외: {exc!r}", flush=True)
    finally:
        report["console_errors"] = console_errors
        await ctx.close()
        await browser.close()
        await pw.stop()

    print(f"[E2E] 콘솔 에러/경고 {len(console_errors)}건: {json.dumps(console_errors[:20], ensure_ascii=False)}", flush=True)

    # ── 정리 — phase1 결과와 무관하게 항상 시도(저장이 됐을 수 있으므로), SKIP_CLEANUP=1 이면
    # 이 실행에서는 생략(다중 시나리오 배치 뒤 한 번만 정리하는 팀 지시 운용) ──────────────
    if SKIP_CLEANUP:
        print("[E2E] SKIP_CLEANUP=1 — phase2 정리는 이 실행에서 생략(배치 종료 후 별도 실행)", flush=True)
    else:
        print("[E2E] phase2 — ERP 독립 재조회 + 정리(F6) 시작", flush=True)
        cleanup = await erp_verify_and_delete(gubun_label=GUBUN_LABEL, fg_code=FG_CODE, tag=TAG)
        report["cleanup"] = cleanup
        print(f"[E2E] phase2 결과: {json.dumps(cleanup, ensure_ascii=False, default=str)[:1200]}", flush=True)

    out_path = ART / f"{TAG}_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[E2E] 리포트 저장 {out_path}", flush=True)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
