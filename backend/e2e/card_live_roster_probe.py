"""HEADLESS 읽기전용(부작용 0) 라이브 프로브 — 법인카드 '카드' 서브팝업 전 카드 실측 채집.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7(저장)·상신 절대 금지.
  - 서브팝업 '적용' 버튼 클릭 금지 — 체크는 매칭 검증 목적으로만 하고 즉시 checkAll(false) 로 원복.
  - 종료 시 저장하지 않고 브라우저를 닫는다(만든 상세행은 draft 상태로 버려짐 = 서버 영향 0).

배경: 2026-08-01 커밋 7102b2f(카드 선택 본인/전체 분기) 이후 e2e 가
  "본인 카드 0장 — 카드 6장 중 이름(이트라이브2) 일치 없음" 으로 하드 실패했는데 실패 로그에
  카드 목록이 안 남아 원인 판별이 불가했다. 이 프로브는 그 6장(또는 현재 N장)의 **원문 전량**과
  실제 매칭 로직(steps.owner_name_variants + js.CARD_SUB_SELECT_BY_NAME_JS, 프로덕션 그대로 재사용)
  판정 결과를 실측한다.

진입 경로는 card_owner_col_probe.py(2026-07-29)를 그대로 재사용/확장한다:
  login → user_type(회계) → menu_nav(EXPENSE_CARD) → set_gubun(카드) → add_row(F3) →
  open_evdn → select_evdn(01) → 카드번호 돋보기 → '카드' 서브팝업.

이 파일 고유 신규 작성분:
  - CARD_SUB_FULL_DUMP_JS: getColumns() 전체 + getJsonRows(0, n-1) **전량**(기존 프로브는 5행 캡).
  - 프로필 raw display_name 에 app.erp.profile.split_job_title 적용(프로덕션 authenticate() 와
    동일 변환) 후 steps.owner_name_variants 로 매칭 키 생성 — 실제 런타임과 동일 조건 재현.
  - 읽기전용 매칭 검증: js.CARD_SUB_SELECT_BY_NAME_JS(owners) 체크 → 매칭 행 읽기 →
    checkAll(false) 원복(card_owner_match_verify_probe.py 패턴 재사용, 적용 클릭 없음).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/card_live_roster_probe.py
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
from app.agents.card_collect import js as cc_js  # noqa: E402  (CARD_SEARCH_BTN_JS, CARD_SUB_SELECT_BY_NAME_JS)
from app.agents.card_collect import steps as cc_steps  # noqa: E402  (owner_name_variants)
from app.agents.common.doc_steps import open_evdn_editor, select_evdn_code  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.erp.profile import split_job_title  # noqa: E402  (프로덕션 authenticate() 와 동일 변환)
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
VIEWPORT = {"width": 1440, "height": 900}

# ── 신규 작성분(이 프로브 고유 필요) ──────────────────────────────────────────────
# 기존 CARD_SUB_DUMP_JS(card_owner_col_probe.py)는 앞 5행 캡 — 여기선 전량(getJsonRows(0,n-1)).
CARD_SUB_FULL_DUMP_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try {
    const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || cc.field || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
      visible: cc.visible !== false }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    const title = c((sub.querySelector('.k-window-title')||{}).innerText);
    return { ok:true, title, n, cols, rows };
  } catch (e) { return { ok:false, err:String(e).slice(0, 160) }; }
}"""

# 체크된 행의 FINPRODUCT_NM 읽기전용 대조(체크만, 적용 없음) — card_owner_match_verify_probe.py 재사용.
CARD_SUB_CHECKED_ROWS_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try {
    const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    const idx = g.getCheckedRows() || [];
    const names = idx.map(i => (rows[i] || {}).FINPRODUCT_NM || null);
    return { ok:true, n, idx, names };
  } catch (e) { return { ok:false, err:String(e).slice(0, 120) }; }
}"""

CARD_SUB_CHECKALL_FALSE_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try {
    const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    g.checkAll(false);
    let checked=-1; try { checked=(g.getCheckedRows()||[]).length; } catch(e){}
    return { ok:true, checked };
  } catch (e) { return { ok:false, err:String(e).slice(0, 120) }; }
}"""


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"card_live_roster_probe_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


async def _match_case(page: Page, owners: list[str]) -> dict:
    """읽기전용 매칭 검증 — 체크→읽기→즉시 원복(적용 클릭 없음)."""
    r = await page.evaluate(cc_js.CARD_SUB_SELECT_BY_NAME_JS, owners)
    checked_detail = await page.evaluate(CARD_SUB_CHECKED_ROWS_JS)
    reset = await page.evaluate(CARD_SUB_CHECKALL_FALSE_JS)
    return {"owners": owners, "raw": r, "checked_rows": checked_detail, "reset": reset}


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page: Page = await (await browser.new_context(viewport=VIEWPORT)).new_page()
        try:
            print("[step] login")
            login_result = await ensure_logged_in(page, USERID, PASSWORD, base)
            raw_profile = login_result.get("profile") or {}
            print("  raw profile:", raw_profile)
            # 프로덕션 authenticate()(app/erp/login.py)와 동일 변환 — "석대현 프로" 형 표기 분리.
            display_name, job_title = split_job_title((raw_profile.get("display_name") or "").strip())
            print(f"  split → display_name={display_name!r} job_title={job_title!r}")
            await page.screenshot(path=str(ARTIFACTS / "card_live_roster_probe_1_login.png"))

            print("[step] user_type 회계")
            await ensure_user_type(page, "회계")

            print("[step] menu_nav (결의서입력)")
            await navigate_schema(page, EXPENSE_CARD, base)
            await page.screenshot(path=str(ARTIFACTS / "card_live_roster_probe_2_menu.png"))

            print("[step] set_gubun 카드")
            for _ in range(50):
                if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                    break
                await page.wait_for_timeout(300)
            r = await page.evaluate(
                js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
                {"selector": selectors.GUBUN_SELECT, "text": "카드"},
            )
            print("  gubun result:", r)

            print("[step] add_row (F3)")
            await js_click(page, selectors.BTN_ADD)
            rows = -1
            for _ in range(33):
                await page.wait_for_timeout(300)
                rows = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                if isinstance(rows, int) and rows > 0:
                    break
            print("  detail rows:", rows)
            if not (isinstance(rows, int) and rows > 0):
                raise RuntimeError("add_row 실패 — 입력 행이 생성되지 않았습니다")

            print("[step] open_evdn")
            r = await open_evdn_editor(page)
            if not r.get("ok"):
                raise RuntimeError(f"open_evdn 실패: {r}")

            print("[step] select_evdn(01 법인카드)")
            r = await select_evdn_code(page, "01")
            if not r.get("ok"):
                raise RuntimeError(f"select_evdn 실패: {r}")
            await page.screenshot(path=str(ARTIFACTS / "card_live_roster_probe_3_card_popup.png"))

            print("[step] 카드번호 돋보기 클릭 → '카드' 서브팝업 오픈")
            box = None
            for _ in range(20):  # 카드팝업 로딩('데이터 처리 중') 대비 폴링
                box = await page.evaluate(cc_js.CARD_SEARCH_BTN_JS)
                if box:
                    break
                await page.wait_for_timeout(300)
            print("  magnifier box:", box)
            if not box:
                raise RuntimeError("돋보기 버튼을 찾지 못했습니다(법인카드 팝업 아님?)")
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1200)
            await page.screenshot(path=str(ARTIFACTS / "card_live_roster_probe_4_sub_popup.png"))

            print("[step] 서브팝업 그리드 전량 덤프(체크 없음)")
            dump = None
            for _ in range(15):
                dump = await page.evaluate(CARD_SUB_FULL_DUMP_JS)
                if dump.get("ok"):
                    break
                await page.wait_for_timeout(400)
            print("  dump ok:", dump.get("ok") if isinstance(dump, dict) else dump)
            print(f"  카드 {dump.get('n')}장:")
            for row in dump.get("rows", []):
                print(
                    "   -", row.get("FINPRODUCT_NM"),
                    "| CARD_OWNR_NM:", row.get("CARD_OWNR_NM"),
                    "| KOR_NM:", row.get("KOR_NM"),
                    "| PARTNER_NM:", row.get("PARTNER_NM"),
                )
            _dump("full_dump", dump)

            # ── 매칭 판정(프로덕션 로직 그대로 재사용) ──────────────────────────────
            owners_live = cc_steps.owner_name_variants(USERID, display_name, job_title)
            print(f"\n[step] 매칭 검증(라이브 프로필 변형) owners={owners_live}")
            case_live = await _match_case(page, owners_live)
            print("  raw:", case_live["raw"])
            print("  checked FINPRODUCT_NM:", case_live["checked_rows"].get("names"))

            # 대조군: 실카드 보유자로 확인된 이름(2026-07-29 실측 "정원호")으로 매칭 로직 자체가
            # 살아있는지 양성 확인(음성 결과가 로직 결함인지 데이터 부재인지 가르는 대조).
            POSITIVE_CONTROL = "정원호"
            print(f"\n[step] 매칭 로직 살아있음 대조(양성 컨트롤 owner={POSITIVE_CONTROL!r})")
            case_positive = await _match_case(page, [POSITIVE_CONTROL])
            print("  raw:", case_positive["raw"])
            print("  checked FINPRODUCT_NM:", case_positive["checked_rows"].get("names"))

            summary = {
                "login_userid": USERID,
                "raw_profile": raw_profile,
                "split_display_name": display_name,
                "split_job_title": job_title,
                "owners_live": owners_live,
                "card_count": dump.get("n"),
                "columns": dump.get("cols"),
                "match_live": case_live,
                "match_positive_control": case_positive,
            }
            _dump("summary", summary)

            print("\n=== RESULT ===")
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001 — 실패도 스크린샷으로 남긴다
            print(f"[FAIL] {exc}")
            try:
                await page.screenshot(path=str(ARTIFACTS / "card_live_roster_probe_FAIL.png"))
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            # ⚠ 읽기전용 프로브 — '적용'·저장(F7)·상신 없음. draft 상세행은 저장 안 했으므로
            # 브라우저를 닫는 것으로 서버에 아무 영향이 남지 않는다.
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
