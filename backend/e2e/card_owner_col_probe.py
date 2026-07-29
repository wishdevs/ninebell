"""HEADLESS 읽기전용(부작용 0) 프로브 — 법인카드 '카드' 서브팝업 그리드 컬럼 실측.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7(저장)·상신 절대 금지.
  - 서브팝업 체크/적용 금지(읽기만) — CARD_SUB_SELECT_ALL_JS/CARD_SUB_SELECT_BY_NAME_JS 호출 안 함.
  - 종료 시 저장하지 않고 브라우저를 닫는다.

card_collect 의 진입 앞단(login→user_type(회계)→menu_nav→set_gubun(카드)→add_row→
open_evdn→select_evdn(01))을 그대로 재사용해 법인카드 팝업까지 도달한 뒤, card_collect.js 의
CARD_SEARCH_BTN_JS(돋보기 좌표)로 '카드' 서브팝업을 연다. 서브팝업 그리드는 신규 읽기전용 JS
(CARD_SUB_DUMP_JS, 이 파일 고유)로 getColumns()+getJsonRows(0,4)만 덤프한다 — 체크/적용 없음.

확인 대상(team-lead 요청, select_all_cards 매칭 0건 버그 조사):
  1. '카드' 서브팝업 그리드 전체 컬럼 키
  2. CARD_OWNR_NM/KOR_NM 존재·값 여부
  3. "국민법인카드(석대현)-2826" 형태 카드명이 담긴 컬럼 키
  4. 로그인 userid 형식과 카드명/소유자명 형식 비교

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/card_owner_col_probe.py
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
from app.agents.card_collect import js as cc_js  # noqa: E402  (CARD_SEARCH_BTN_JS)
from app.agents.common.doc_steps import open_evdn_editor, select_evdn_code  # noqa: E402
from app.config import get_settings  # noqa: E402
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

# ── 신규 작성분(이 화면 고유 필요) ───────────────────────────────────────────────
# '카드' 서브팝업(법인카드 아님, 최근 열린 k-window) 그리드 컬럼+앞5행 읽기전용 덤프.
# card_collect.js 의 CARD_SUB_SELECT_ALL_JS/CARD_SUB_SELECT_BY_NAME_JS 와 동일한 서브팝업
# 탐색 방식(최근 non-법인카드 k-window)을 그대로 따르되, checkAll/setChecked 호출은 없다.
CARD_SUB_DUMP_JS = """() => {
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
    const rows = n > 0 ? ds.getJsonRows(0, Math.min(n, 5) - 1) : [];
    const title = c((sub.querySelector('.k-window-title')||{}).innerText);
    return { ok:true, title, n, cols, rows };
  } catch (e) { return { ok:false, err:String(e).slice(0, 160) }; }
}"""

# 프로필 패널(아바타)에서 사용자명 텍스트 읽기 — 로그인 userid 와 화면 표시명 형식 비교용.
PROFILE_NAME_JS = """() => {
  const el = document.querySelector('.user-info .user-name, .user-info');
  return el ? el.innerText.trim().slice(0, 200) : null;
}"""


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"card_owner_col_probe_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page: Page = await (await browser.new_context(viewport=VIEWPORT)).new_page()
        try:
            print("[step] login")
            login_result = await ensure_logged_in(page, USERID, PASSWORD, base)
            print("  profile:", login_result.get("profile"))
            await page.screenshot(path=str(ARTIFACTS / "card_owner_col_probe_1_login.png"))

            print("[step] user_type 회계")
            await ensure_user_type(page, "회계")

            print("[step] menu_nav (결의서입력)")
            await navigate_schema(page, EXPENSE_CARD, base)
            await page.screenshot(path=str(ARTIFACTS / "card_owner_col_probe_2_menu.png"))

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
            print("  open_evdn:", r)
            if not r.get("ok"):
                raise RuntimeError(f"open_evdn 실패: {r}")

            print("[step] select_evdn(01 법인카드)")
            r = await select_evdn_code(page, "01")
            print("  select_evdn:", r)
            if not r.get("ok"):
                raise RuntimeError(f"select_evdn 실패: {r}")
            await page.screenshot(path=str(ARTIFACTS / "card_owner_col_probe_3_card_popup.png"))

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
            await page.screenshot(path=str(ARTIFACTS / "card_owner_col_probe_4_sub_popup.png"))

            print("[step] 서브팝업 그리드 읽기전용 덤프(체크/적용 없음)")
            dump = None
            for _ in range(15):
                dump = await page.evaluate(CARD_SUB_DUMP_JS)
                if dump.get("ok"):
                    break
                await page.wait_for_timeout(400)
            print("  dump ok:", dump.get("ok") if isinstance(dump, dict) else dump)
            _dump("grid_dump", dump)

            profile_name = await page.evaluate(PROFILE_NAME_JS)
            summary = {
                "login_userid": USERID,
                "profile": login_result.get("profile"),
                "profile_name_panel_text": profile_name,
            }
            _dump("summary", summary)

            print("\n=== RESULT ===")
            print(json.dumps({"dump": dump, "summary": summary}, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001 — 실패도 스크린샷으로 남긴다
            print(f"[FAIL] {exc}")
            try:
                await page.screenshot(path=str(ARTIFACTS / "card_owner_col_probe_FAIL.png"))
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            # ⚠ 읽기전용 프로브 — 저장(F7)·상신 없음. 만든 행/문서는 저장하지 않았으므로
            # 브라우저를 그냥 닫는 것으로 충분하다(서버에 아무 것도 반영되지 않음).
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
