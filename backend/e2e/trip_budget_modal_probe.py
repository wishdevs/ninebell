"""HEADLESS 긴급 진단 프로브 — 출장(국내/자차) 금액 입력 후 '예산현황' 확인모달 안 닫힘 재현.

실사용 증상(2026-07-30, trip_domestic/trip_overseas/gyeongjo_grant 3개 에이전트 공통):
"금액 입력 실패: 금액 입력 후 확인 모달이 닫히지 않았습니다([예산현황]) — 잔존 팝업은 이후
피커 오독·F7 삼킴을 유발합니다." 공유 지점은 app/agents/trip_domestic/steps.py::type_amount.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7(저장)·상신 절대 금지 — F3 초안까지만, 저장하지 않고 브라우저 종료로 정리.
  - type_amount 는 **프로덕션 함수 그대로** 호출한다(재구현 금지) — 실패가 재현되면 그 실패는
    실제 코드의 실제 동작이다.

진입·행 채움은 e2e/trip_smoke_cycle.py 의 실측 파라미터(department/cost_type/project)를 그대로
재사용한다(신규 값 발명 없음). type_amount 호출 **직전에** 진단용 MutationObserver 를 걸어 모달
DOM 변화를 관찰하고, 실패 시 k-window 전수 덤프(zIndex 포함)·MODAL_BTN_BOX_JS 원시 반환·클릭
전후 popup count 를 추가로 수집한다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/trip_budget_modal_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) ────────────────────────────────────────────────────────
from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import graph as trip_graph  # noqa: E402  (TRIP_GUBUN_LABEL)
from app.agents.trip_domestic import steps as trip_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

AMOUNT = 12000
DEPARTMENT = "인사/기획팀"
COST_TYPE = "판관비"
PROJECT = {"code": "1310|1310", "name": "포장개선"}
EVDN_CODE = "10"

# ── 신규 작성분(이 진단 고유 — 부작용 없는 읽기전용 서베이) ────────────────────────
# 보이는 k-window 전수 덤프(제목·zIndex·버튼목록·outerHTML 발췌) — MODALS_SNAPSHOT_JS 보다
# 상세(zIndex·outerHTML 포함, 팀 요청사항).
KWINDOW_FULL_SURVEY_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  return [...document.querySelectorAll('.k-window')].map((w, i) => {
    const cs = window.getComputedStyle(w);
    return {
      i,
      visible: w.offsetParent !== null,
      title: c((w.querySelector('.k-window-title') || {}).innerText),
      zIndex: cs.zIndex,
      display: cs.display,
      visibility: cs.visibility,
      buttons: [...w.querySelectorAll('button')].filter(b => b.offsetParent !== null).map(b => c(b.innerText)),
      outerHTML: w.outerHTML.slice(0, 500),
    };
  });
}"""

# 뷰포트 전체에서 보이는 모든 오버레이류 요소(k-window 아닌 것도 포함 — 스낵바/공지 등 다른
# 축의 오버레이가 있는지 확인). class 에 window/dialog/modal/popup/snackbar/notice 포함.
OVERLAY_SURVEY_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('div')) {
    if (el.offsetParent === null) continue;
    const cls = (el.className && el.className.toString) ? el.className.toString() : '';
    if (!/window|dialog|modal|popup|snackbar|notice|overlay/i.test(cls)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 20) continue;
    out.push({ cls, zIndex: window.getComputedStyle(el).zIndex, text: c(el.innerText).slice(0, 80),
      rect: { top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) } });
  }
  return out;
}"""


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"trip_budget_modal_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page: Page = await (await browser.new_context(viewport=LIVE_VIEWPORT)).new_page()
        try:
            print("[step] login → user_type(회계) → menu_nav → set_gubun(출장 국내·자차) → add_row(F3)")
            await ensure_logged_in(page, USERID, PASSWORD, base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, EXPENSE_CARD, base)
            for _ in range(50):
                if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                    break
                await page.wait_for_timeout(300)
            r = await page.evaluate(
                js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
                {"selector": selectors.GUBUN_SELECT, "text": trip_graph.TRIP_GUBUN_LABEL},
            )
            print("  gubun result:", r)
            await js_click(page, selectors.BTN_ADD)
            rows = -1
            for _ in range(33):
                await page.wait_for_timeout(300)
                rows = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                if isinstance(rows, int) and rows > 0:
                    break
            if not (isinstance(rows, int) and rows > 0):
                raise RuntimeError("add_row 실패")

            print("[step] 증빙유형(10) → 계산서일 → 거래처(본인) → 예산단위 → 프로젝트")
            oe = await doc_steps.open_evdn_editor(page)
            print("  open_evdn_editor:", oe)
            if not oe.get("ok"):
                raise RuntimeError(f"증빙 열기 실패: {oe}")
            se = await doc_steps.select_evdn_code(page, EVDN_CODE)
            print("  select_evdn_code:", se)
            if not se.get("ok"):
                raise RuntimeError(f"증빙유형 실패: {se}")

            from datetime import date as _date
            dt = await trip_steps.set_invoice_date(page, _date.today().strftime("%Y%m%d"))
            print("  set_invoice_date:", dt)

            pr = await trip_steps.fill_partner_by_search(page, USERID)
            print("  fill_partner_by_search:", pr)
            if not pr.get("ok"):
                raise RuntimeError(f"거래처 실패: {pr}")

            bu = await trip_steps.fill_budget_fixed(page, DEPARTMENT, COST_TYPE)
            print("  fill_budget_fixed:", bu)
            if not bu.get("ok"):
                raise RuntimeError(f"예산단위 실패: {bu}")

            pj = await trip_steps.fill_project(page, PROJECT)
            print("  fill_project:", pj)
            if not pj.get("ok"):
                raise RuntimeError(f"프로젝트 실패: {pj}")

            await page.screenshot(path=str(ARTIFACTS / "trip_budget_modal_1_before_amount.png"), full_page=True)

            print(f"[step] type_amount({AMOUNT}) — 프로덕션 함수 그대로 호출")
            sa = await trip_steps.type_amount(page, AMOUNT)
            print("  type_amount 반환:", json.dumps(sa, ensure_ascii=False, default=str))
            await page.screenshot(path=str(ARTIFACTS / "trip_budget_modal_2_after_type_amount.png"), full_page=True)

            reproduced = not sa.get("ok")
            print(f"\n재현 여부: {'✅ 재현됨' if reproduced else '❌ 재현 안 됨(정상 종료)'}")

            diag: dict = {"type_amount_result": sa, "reproduced": reproduced}

            if reproduced:
                print("[진단] k-window 전수 서베이 + 오버레이 서베이 + 재클릭 시도")
                kwindows = await page.evaluate(KWINDOW_FULL_SURVEY_JS)
                overlays = await page.evaluate(OVERLAY_SURVEY_JS)
                print("  k-windows:", json.dumps(kwindows, ensure_ascii=False, indent=2))
                print("  overlays:", json.dumps(overlays, ensure_ascii=False, indent=2))

                btn_raw = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                btn_raw_yes = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "예")
                print("  MODAL_BTN_BOX_JS('확인') 원시값:", btn_raw)
                print("  MODAL_BTN_BOX_JS('예') 원시값:", btn_raw_yes)

                before_count = len(await page.evaluate(
                    "() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
                ))
                if btn_raw:
                    from nbkit.browser.actions import mouse_click
                    await mouse_click(page, btn_raw["x"], btn_raw["y"])
                    await page.wait_for_timeout(1000)
                after_count = len(await page.evaluate(
                    "() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
                ))
                print(f"  진단용 재클릭 — popup count {before_count} -> {after_count}")
                kwindows_after_reclick = await page.evaluate(KWINDOW_FULL_SURVEY_JS)
                await page.screenshot(path=str(ARTIFACTS / "trip_budget_modal_3_after_reclick.png"), full_page=True)

                diag.update({
                    "kwindows_at_failure": kwindows,
                    "overlays_at_failure": overlays,
                    "modal_btn_box_confirm": btn_raw,
                    "modal_btn_box_yes": btn_raw_yes,
                    "popup_count_before_reclick": before_count,
                    "popup_count_after_reclick": after_count,
                    "kwindows_after_reclick": kwindows_after_reclick,
                })
            else:
                print("[정보] 정상 종료 — modals_seen:", sa.get("modals"))

            _dump("result", diag)
            print("\n=== SUMMARY ===")
            print(json.dumps(diag, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {exc}")
            try:
                await page.screenshot(path=str(ARTIFACTS / "trip_budget_modal_FAIL.png"), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            # F7 미실행 — 문서 미저장, 브라우저 종료로 충분.
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
