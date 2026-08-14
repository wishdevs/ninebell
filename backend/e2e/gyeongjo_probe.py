"""HEADLESS 읽기전용(부작용 0) 프로브 — 경조금신청서 결의서입력 필드 토폴로지 실측.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7(저장) 절대 금지.
  - 코드피커 확정 '적용'/더블클릭 금지(검색·읽기만).
  - 금액 입력→예산현황 다이얼로그 커밋 금지(에디터 구조만 덤프, 값 타이핑/Tab 금지).
  - 행 삭제·상신 금지. 종료 시 저장하지 않고 브라우저를 닫는다.

trip_domestic(P1~P9, e2e/trip_probe*.py)을 참조 구현으로 **최대 재사용**한다(새 JS/셀렉터를
발명하지 않는다) — 진입 앞단(login/user_type/menu_nav)은 common 패턴(nbkit.patterns.*), 결의구분·
행추가·증빙 JS 는 nbkit.omnisol.js_lib/selectors 단일소스, 발견용 덤프 JS(SELECT_OPTIONS_JS·
EVDN_DUMP_ALL_JS·DOC_PICKERS_JS·DOC_INPUTS_JS)는 `e2e.trip_probe` 에서 **직접 import**, 코드 셀
피커 오픈 로직(`_open_detail_cell_picker`)은 `app.agents.trip_domestic.steps` 에서 **직접 import**
한다(중복정의 금지). 경조금 고유(❓ 항목 특유)라 새로 작성한 것은 GRID_COLUMNS_JS 의 editor 필드
확장·AMOUNT_EDITOR_DUMP_JS(전량 덤프판)·COUNTER_LABEL_EXISTS_JS(부작용 없는 존재확인판) 3개뿐 —
모듈 하단 "재사용 소스 지도" 주석 참조. 프로덕션 조건 재현: LIVE_VIEWPORT(1440x900) +
_ScaledPage(delay_scale=0.4)(trip_agent_validate.py 와 동일 패턴, app.live.runner 재사용).

확인 대상(gyeongjo_grant PROCESS.md ❓):
  1. D3 결의구분 "경조금신청서" value
  2. detail 그리드 getColumns() 전량(출장과 동일 컬럼셋인지)
  3. D8 예산단위 피커에서 "복리후생비"/"경조" 검색 → 코드 2005 행의 정확 BGACCT_NM + 검색 결과행수
  4. D5 증빙유형 코드 10 라벨
  5. D10 공급가액 필드(SPPRC_AMT2 추정) 에디터 오버레이 구조(gridDetail_number vs _line, 값 미입력)
  6. D12 상대계정거래처 관리항목 존재 여부(구조 힌트만 — 실제 렌더는 행 데이터 필요, trip 선례)

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/gyeongjo_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) — app.agents.trip_domestic 형제 구현체 그대로 import ────────
from app.agents.trip_domestic.steps import _open_detail_cell_picker  # noqa: E402  (재사용: 셀 피커 오픈 3회 재시도 로직)
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402  (재사용: trip_agent_validate.py 와 동일 프로덕션조건 재현 프록시)
from e2e.trip_probe import (  # noqa: E402  (재사용: trip_probe.py 발견용 in-page JS 그대로)
    DOC_INPUTS_JS,
    DOC_PICKERS_JS,
    EVDN_DUMP_ALL_JS,
    SELECT_OPTIONS_JS,
)
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.codepicker import _picker_search  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

GUBUN_LABEL = "경조금신청서"
EVDN_CODE = "10"
BUDGET_CODE = "2005"
BUDGET_SEARCH_KEYWORDS = ["복리후생비", "경조"]

# ── 신규 작성분(경조금 고유 필요) — 나머지 발견용 JS 는 상단에서 e2e.trip_probe 를 그대로
#    import 했으므로 여기 재정의하지 않는다(SELECT_OPTIONS_JS/EVDN_DUMP_ALL_JS/DOC_PICKERS_JS/
#    DOC_INPUTS_JS). GRID_COLUMNS_JS 만 trip_probe.py 원본에 **editor 필드를 추가**한 확장판
#    (본 과업 지시 "getColumns()(fieldName·visible·editor·헤더) 전량 덤프"가 editor 를 명시 요구).
GRID_COLUMNS_JS = """(index) => {
  try {
    const ctrl = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl');
    const g = ctrl._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || cc.field || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
      visible: cc.visible !== false,
      editor: (cc.editor && (cc.editor.type || cc.editor.editorType)) || null }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const row0 = n > 0 ? ds.getJsonRows(0, 0)[0] : null;
    return { ok: true, n, cols, fieldKeys: row0 ? Object.keys(row0) : null };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""

# app.agents.trip_domestic.js.AMOUNT_EDITOR_INPUT_JS 를 응용(그대로 import 하지 않은 이유: 원본은
# 진짜 숫자칸 1개만 골라 반환 — 여기선 "구조만 확인"이 목적이라 decoy(_line)까지 **전량** 덤프해
# gridDetail_number(진짜) vs gridDetail_line(접힌 decoy, width~1)을 육안 대조한다(§1 함정 재확인).
AMOUNT_EDITOR_DUMP_JS = """() => {
  const out = [];
  for (const i of document.querySelectorAll('input')) {
    if (i.offsetParent === null) continue;
    if (!/gridDetail|_editor/.test(i.id || '')) continue;
    const r = i.getBoundingClientRect();
    out.push({ id: i.id, width: Math.round(r.width), height: Math.round(r.height),
      x: Math.round(r.x), y: Math.round(r.y), value: String(i.value || '') });
  }
  return out;
}"""

# app.agents.trip_domestic.js.COUNTER_SCROLL_JS 를 응용(그대로 import 하지 않은 이유: 원본은
# 라벨을 찾으면 scrollIntoView 로 화면을 스크롤하는 부작용이 있다 — read-only 프로브는 존재
# 여부만 필요하므로 스크롤 없이 boolean 만 반환하도록 축소).
COUNTER_LABEL_EXISTS_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label,span,div,td,th')]
    .find(e => e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  return !!lbl;
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"gyeongjo_probe_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"gyeongjo_probe_{name}.png")
        await page.screenshot(path=p)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


# _open_detail_cell_picker 는 재정의하지 않는다 — app.agents.trip_domestic.steps 에서 그대로
# import(상단) 했다. 셀 에디터 오픈+돋보기 실클릭+피커 준비폴링(3회 재시도) 로직은 nbkit
# js_lib(OPEN_DETAIL_CELL_EDITOR_JS/DETAIL_EDITOR_MAGNIFIER_JS/PICKER_ROWCOUNT_JS)만 쓰고
# trip 고유 로직이 없어 gyeongjo 에도 그대로 통한다(경조금 전용 변형 불필요, 실측 확인됨).


async def main() -> None:
    results: dict = {"userid": USERID, "gubun_label": GUBUN_LABEL, "delay_scale": DELAY_SCALE}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)  # 프로덕션 조건 재현(gyeongjo-grant 예정 delay_scale=0.4)
    base = get_settings().erp_base

    try:
        # ── 진입: login → 회계 → GLDDOC00300 (공유 앞단, trip 과 동일 프리미티브) ────
        print("[entry] login + user_type(회계) + menu_nav(GLDDOC00300)…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        await _shot(page, "entry")

        # ── 1) D3: 결의구분 옵션 덤프 + "경조금신청서" 전환 ─────────────────────────
        print("\n===== D3: 결의구분 옵션 =====", flush=True)
        opt = await page.evaluate(SELECT_OPTIONS_JS, selectors.GUBUN_SELECT)
        options = opt.get("options") or []
        chosen = next((o for o in options if o["text"] == GUBUN_LABEL), None)
        results["D3"] = {"all_options": options, "chosen": chosen}
        print(f"[D3] options={[o['text'] for o in options]}", flush=True)
        print(f"[D3] chosen({GUBUN_LABEL})={chosen}", flush=True)
        if not chosen:
            results["D3"]["set_result"] = {"ok": False, "reason": f"'{GUBUN_LABEL}' 라벨 없음"}
            await _dump("results", results)
            print("[FATAL] 결의구분 옵션에 '경조금신청서' 없음 — 즉시 중단(원인분류: 필드부재/문서종류 편차)", flush=True)
            return
        r = await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
            {"selector": selectors.GUBUN_SELECT, "text": GUBUN_LABEL},
        )
        await page.wait_for_timeout(1_800)
        results["D3"]["set_result"] = r
        print(f"[D3] set gubun -> {r}", flush=True)
        await _shot(page, "d3_gubun")
        await _dump("results", results)

        # ── add_row (F3) ─────────────────────────────────────────────────────────
        print("\n===== add_row (F3) =====", flush=True)
        await js_click(page, selectors.BTN_ADD)
        drc = -1
        for _ in range(33):
            await page.wait_for_timeout(300)
            drc = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
            if isinstance(drc, int) and drc > 0:
                break
        results["add_row"] = {"detail_rowcount": drc}
        print(f"[add_row] detail_rowcount={drc}", flush=True)
        await _shot(page, "addrow")
        await _dump("results", results)
        if not (isinstance(drc, int) and drc > 0):
            print("[FATAL] F3 후 행 생성 실패 — 중단(원인분류: 타이밍/셀렉터드리프트)", flush=True)
            return

        # ── 2) detail/master 컬럼 전량 + 문서 폼 피커/인풋 발견 ────────────────────
        print("\n===== detail/master 컬럼 + 문서 폼 피커 =====", flush=True)
        detail_cols = await page.evaluate(GRID_COLUMNS_JS, 1)
        master_cols = await page.evaluate(GRID_COLUMNS_JS, 0)
        doc_pickers = await page.evaluate(DOC_PICKERS_JS)
        doc_inputs = await page.evaluate(DOC_INPUTS_JS)
        counter_label_before = await page.evaluate(COUNTER_LABEL_EXISTS_JS)
        results["detail_grid"] = detail_cols
        results["master_grid"] = master_cols
        results["doc_pickers"] = doc_pickers
        results["doc_inputs"] = doc_inputs
        results["counter_label_before_fill"] = counter_label_before
        detail_field_set = {c.get("field") for c in (detail_cols.get("cols") or []) if c.get("field")}
        results["D12_bfc_field_in_columns"] = {
            "BFC_PARTNER_CD": "BFC_PARTNER_CD" in detail_field_set,
            "BFC_PARTNER_NM": "BFC_PARTNER_NM" in detail_field_set,
        }
        print(f"[detail] n={detail_cols.get('n')} cols={[c.get('field') for c in (detail_cols.get('cols') or [])]}", flush=True)
        print(f"[detail] BFC_PARTNER_CD in cols? {results['D12_bfc_field_in_columns']}", flush=True)
        print(f"[counter] 상대계정거래처 라벨 존재(행 채움 前)? {counter_label_before}", flush=True)
        await _shot(page, "detail_cols")
        await _dump("results", results)

        # ── 3) D5: 증빙유형 팝업 전량 덤프(코드 10 라벨) — 적용 없이 닫기 ───────────
        print("\n===== D5: 증빙유형 코드 10 라벨 =====", flush=True)
        d5: dict = {"opened": False}
        for attempt in range(1, 4):
            shown = await page.evaluate(js_lib.OPEN_EVDN_EDITOR_JS)
            if not shown:
                continue
            rect = None
            waited = 0
            while waited < 1_500:
                await page.wait_for_timeout(150)
                waited += 150
                rect = await page.evaluate(js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS)
                if rect:
                    break
            if not rect:
                continue
            await mouse_click(page, rect["x"], rect["y"])
            for _ in range(20):
                await page.wait_for_timeout(300)
                if await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS):
                    d5["opened"] = True
                    break
            if d5["opened"]:
                break
        if d5["opened"]:
            await page.wait_for_timeout(600)
            dump_all = await page.evaluate(EVDN_DUMP_ALL_JS)
            d5["evdn_dump"] = dump_all
            rows = dump_all.get("rows") or []
            code_row = next((x for x in rows if x["code"] == EVDN_CODE), None)
            d5["code10"] = code_row
            print(f"[D5] evdn rows n={dump_all.get('n')}: {[(x['code'], x['name']) for x in rows]}", flush=True)
            print(f"[D5] code{EVDN_CODE}={code_row}", flush=True)
            await _shot(page, "d5_evdn_popup")
            # ⚠ 적용 클릭 없이 팝업만 닫는다(read-only 엄수 — trip_probe 와 달리 적용 생략).
            closed = await page.evaluate(js_lib.PICKER_CLOSE_JS)
            d5["closed_without_apply"] = closed
            await page.wait_for_timeout(500)
        else:
            d5["reason"] = "증빙유형 팝업 열기 실패(3회)"
        results["D5"] = d5
        await _dump("results", results)

        # ── 4) D8: 예산단위 피커 — "복리후생비"/"경조" 검색 → 코드 2005 매칭 ────────
        print("\n===== D8: 예산단위 복리후생비/경조 =====", flush=True)
        d8: dict = {}
        op = await _open_detail_cell_picker(page, "BG_NM", "예산단위")
        d8["open"] = op
        if op.get("ok"):
            await _shot(page, "d8_popup_open")
            for kw in BUDGET_SEARCH_KEYWORDS:
                await _picker_search(page, kw)
                read = await page.evaluate(
                    js_lib.PICKER_READ_MULTI_JS,
                    [["BG_CD", "BG_NM", "BIZPLAN_NM", "BGACCT_CD", "BGACCT_NM"], 0],
                )
                options = read.get("options") or []
                match2005 = [o for o in options if str(o.get("BGACCT_CD") or "").strip() == BUDGET_CODE]
                d8[f"search_{kw}"] = {
                    "rows": read.get("rows"),
                    "n_options": len(options),
                    "match_2005": match2005,
                    "sample": options[:10],
                }
                print(f"[D8] '{kw}' -> rows={read.get('rows')} n_opts={len(options)} match2005={match2005}", flush=True)
                await _shot(page, f"d8_search_{kw}")
            # ⚠ 적용/선택 없이 닫기.
            closed = await page.evaluate(js_lib.PICKER_CLOSE_JS)
            d8["closed_without_apply"] = closed
            await page.wait_for_timeout(500)
        else:
            d8["reason"] = op.get("reason")
        results["D8"] = d8
        await _dump("results", results)

        # ── 5) D10: 공급가액(SPPRC_AMT2) 에디터 오버레이 구조(값 미입력) ────────────
        print("\n===== D10: 공급가액 필드 구조(SPPRC_AMT2, 커밋 없음) =====", flush=True)
        d10: dict = {}
        amt_open = await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, "SPPRC_AMT2")
        d10["open"] = amt_open
        if amt_open.get("ok"):
            await page.wait_for_timeout(500)
            dump = await page.evaluate(AMOUNT_EDITOR_DUMP_JS)
            d10["editor_inputs"] = dump
            print(f"[D10] SPPRC_AMT2 에디터 오버레이 inputs: {dump}", flush=True)
            await _shot(page, "d10_amount_editor")
            # 에디터 닫기(Escape) — 값 미입력·미커밋.
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
        else:
            d10["reason"] = amt_open.get("reason")
        results["D10"] = d10
        await _dump("results", results)

        # ── 6) D12: 상대계정거래처 관리항목 존재(구조 힌트 — read-only 라 실렌더 미확정) ─
        print("\n===== D12: 상대계정거래처 존재(구조 힌트) =====", flush=True)
        counter_label_after = await page.evaluate(COUNTER_LABEL_EXISTS_JS)
        doc_pickers_after = await page.evaluate(DOC_PICKERS_JS)
        results["D12"] = {
            "counter_label_after_probe": counter_label_after,
            "bfc_field_in_columns": results["D12_bfc_field_in_columns"],
            "doc_pickers_after": doc_pickers_after,
            "note": "trip_domestic 선례상 상대계정거래처 위젯은 행 데이터(거래처/예산 등) 채움 후에만 "
                    "렌더됨 — read-only 프로브(코드피커 적용 금지)라 실제 UI 존재는 확정 불가. "
                    "getColumns() dataSource 필드 존재만 구조적 힌트로 확인.",
        }
        print(f"[D12] 라벨 존재(프로브 종료 시점)={counter_label_after}, 필드셋={results['D12_bfc_field_in_columns']}", flush=True)
        await _shot(page, "d12_counter_hint")
        await _dump("results", results)

        print("\n===== PROBE COMPLETE (저장 없이 종료, 부작용 0) =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        # ⚠ 저장하지 않고 그냥 닫는다(미영속 draft 폐기) — F7 미클릭.
        await browser.close()
        await pw.stop()

    print("\n===== FINAL RESULTS SUMMARY =====", flush=True)
    print(json.dumps({k: (v if not isinstance(v, dict) else "…") for k, v in results.items()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
