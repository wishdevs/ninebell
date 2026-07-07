"""HEADLESS 실채움 검증 — 출장(국내·자차) detail 셀 실입력(저장 직전까지).

프로브 P1~P9 이후 미완 2건을 닫는다:
1) 코드 셀 apply 메커니즘 — showEditor→돋보기→피커 선택→적용이 **셀에 반영**되는지(재독 검증).
2) SPPRC_AMT setValue 후 TOTAL_AMT/ABDOCU_AMT **자동계산**(저장 전) 여부.
추가로 dump_partners 를 카드 문맥에서 1회 돌려 총 거래처 수·소요시간을 실측한다.

⚠ F7/저장 절대 금지 — 채움까지만 하고 저장 없이 종료. 실행:
   cd backend && .venv/bin/python e2e/trip_fill_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.common import doc_steps  # noqa: E402
from app.agents.common.nodes import (  # noqa: E402
    make_add_row_node,
    make_login_node,
    make_menu_nav_node,
    make_open_evdn_node,
    make_select_evdn_node,
    make_set_gubun_node,
    make_user_type_node,
)
from app.agents.trip_domestic import js as trip_js  # noqa: E402
from app.agents.trip_domestic import steps as trip_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 검증용 값(저장 안 하므로 사용자 실제 부서와 무관 — 피커에 존재하는 조합이면 메커니즘 검증 성립).
TOLL_PARTNER = {"code": "10512", "name": "한국도로공사"}  # 프로브 P5 exact 1건.
BUDGET = {"department": "회계팀", "cost_type": "판관비"}  # 프로브 P6 존재 조합(BG_CD 2005·(판)).
FUEL_AMOUNT = 91428  # 320km ÷ 7 × 2000 = 91428.57→91429? (검증은 setValue 반영만; 계산은 params.py)


async def _shot(page: Page, name: str) -> None:
    try:
        await page.screenshot(path=str(ARTIFACTS / f"trip_fill_{name}.png"))
    except Exception:  # noqa: BLE001
        pass


async def _entry_trip(page: Page) -> None:
    """login→회계→GLDDOC00300→결의구분(출장)→F3→회계일→증빙10 까지(공유 앞단 재사용)."""
    events: asyncio.Queue = asyncio.Queue()

    async def _drain() -> None:
        while True:
            await events.get()

    drainer = asyncio.create_task(_drain())
    state = {"page": page, "events": events, "userid": USERID, "password": PASSWORD, "params": {}}
    try:
        for name, node in [
            ("login", make_login_node()),
            ("user_type", make_user_type_node("회계")),
            ("menu_nav", make_menu_nav_node()),
            ("set_gubun", make_set_gubun_node("출장(국내·자차)")),
            ("add_row", make_add_row_node()),
        ]:
            out = await node(state)
            state.update(out or {})
            if state.get("error"):
                raise RuntimeError(f"진입 실패({name}): {state['error']}")
        # 회계일(마스터) — 오늘 날짜 compact.
        from datetime import date

        today = date.today()
        r = await doc_steps.set_acct_date(page, today.strftime("%Y%m%d"), today.isoformat())
        if not r.get("ok"):
            raise RuntimeError(f"회계일 실패: {r}")
        for name, node in [
            ("open_evdn", make_open_evdn_node()),
            ("select_evdn", make_select_evdn_node("10")),
        ]:
            out = await node(state)
            state.update(out or {})
            if state.get("error"):
                raise RuntimeError(f"진입 실패({name}): {state['error']}")
    finally:
        drainer.cancel()


async def _read_detail(page: Page, fields: list[str]) -> dict:
    return await page.evaluate(trip_js.READ_DETAIL_CELL_JS, fields)


async def _fill_one_row(page: Page, results: dict, tag: str, *, partner_by_search: bool) -> None:
    """한 행 채움 + 각 단계 셀 재독. partner_by_search=True 면 거래처=본인(유류비 행)."""
    row: dict = {"tag": tag}

    # 1) 공급가액 setValue → 자동계산 확인(before/after).
    before_amt = await page.evaluate(trip_js.READ_AMOUNT_FIELDS_JS)
    sup = await trip_steps.set_transaction_amount(page, FUEL_AMOUNT)
    after_amt = await page.evaluate(trip_js.READ_AMOUNT_FIELDS_JS)
    row["supply_amount"] = {"set": sup, "before": before_amt, "after": after_amt}
    print(f"[{tag}] 공급가액 set={sup.get('ok')} display={sup.get('display')} "
          f"master_before={before_amt.get('master')} master_after={after_amt.get('master')}", flush=True)

    # 2) 적요.
    row["note"] = await trip_steps.set_row_note(page, "국내출장 자차 유류비 지원" if partner_by_search else "통행료(현금)")

    # 3) 거래처(코드 셀 apply 메커니즘 핵심 검증).
    if partner_by_search:
        pr = await trip_steps.fill_partner_by_search(page, USERID)
    else:
        pr = await trip_steps.fill_partner(page, TOLL_PARTNER["code"], TOLL_PARTNER["name"])
    cell_after = await _read_detail(page, ["PARTNER_CD", "PARTNER_NM", "SPPRC_AMT", "NOTE_DC"])
    row["partner"] = {"fill": pr, "cell": cell_after}
    print(f"[{tag}] 거래처 fill={pr.get('ok')} code={pr.get('code')} → 셀재독 PARTNER_NM={cell_after.get('values',{}).get('PARTNER_NM')}", flush=True)

    # 4) 예산단위(고정 조합).
    bg = await trip_steps.fill_budget_fixed(page, BUDGET["department"], BUDGET["cost_type"])
    bg_cell = await _read_detail(page, ["BG_CD", "BG_NM", "BGACCT_NM"])
    row["budget"] = {"fill": bg, "cell": bg_cell}
    print(f"[{tag}] 예산 fill={bg.get('ok')} {bg.get('name') or bg.get('reason')} → 셀 BG_NM={bg_cell.get('values',{}).get('BG_NM')}", flush=True)

    # 5) 상대계정거래처(본인).
    bfc = await trip_steps.fill_bfc_partner(page, USERID)
    row["bfc"] = {"fill": bfc}
    print(f"[{tag}] 상대계정 fill={bfc.get('ok')} {bfc.get('name') or bfc.get('reason')}", flush=True)

    results.setdefault("rows", []).append(row)
    await _shot(page, tag)


async def _run_fill(results: dict) -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    try:
        t0 = time.monotonic()
        print("[fill] 진입(출장 국내·자차)…", flush=True)
        await _entry_trip(page)
        results["entry_ms"] = int((time.monotonic() - t0) * 1000)
        await _shot(page, "entry")

        # 행1 = 통행료(거래처=한국도로공사)
        r1 = time.monotonic()
        await _fill_one_row(page, results, "row1_toll", partner_by_search=False)
        results["row1_ms"] = int((time.monotonic() - r1) * 1000)

        # 행2 = 유류비(F3 새 행 → 증빙 재선택(P9 carry-over 없음) → 거래처=본인)
        r2 = time.monotonic()
        add = await doc_steps.add_next_row(page, 2)
        results["add_row2"] = add
        print(f"[fill] F3 2행 add={add.get('ok')} rows={add.get('rows')}", flush=True)
        if add.get("ok"):
            events: asyncio.Queue = asyncio.Queue()
            drain_task = asyncio.create_task(_drain_forever(events))
            st = {"page": page, "events": events}
            await make_open_evdn_node()(st)
            await make_select_evdn_node("10")(st)
            await _fill_one_row(page, results, "row2_fuel", partner_by_search=True)
            drain_task.cancel()
        results["row2_ms"] = int((time.monotonic() - r2) * 1000)

        results["final_detail"] = await page.evaluate(
            trip_js.READ_DETAIL_CELL_JS,
            ["PARTNER_CD", "PARTNER_NM", "SPPRC_AMT", "NOTE_DC", "BG_CD", "BGACCT_NM", "PJT_NO", "BFC_PARTNER_NM"],
        )
        results["final_amounts"] = await page.evaluate(trip_js.READ_AMOUNT_FIELDS_JS)
        # 자동계산 필드 발견용 — 마스터 0행/detail 마지막행의 금액류(*_AMT) 전량 덤프.
        results["amount_fields_discovery"] = await page.evaluate(
            """() => {
              const out = {};
              const grab = (gi, key) => {
                try {
                  const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[gi]).data('dewsControl')._grid;
                  const ds = g.getDataSource(); const n = ds.getRowCount();
                  const row = key === 'master' ? 0 : Math.max(0, n - 1);
                  if (n < 1) { out[key] = {}; return; }
                  const j = ds.getJsonRows(row, row)[0] || {};
                  const amt = {};
                  for (const k of Object.keys(j)) if (/AMT|AMOUNT/.test(k)) amt[k] = String(j[k]);
                  out[key] = amt;
                } catch (e) { out[key] = { err: String(e).slice(0, 60) }; }
              };
              grab(0, 'master'); grab(1, 'detail');
              return out;
            }"""
        )
        await _shot(page, "final")
        print("[fill] ⚠ 저장 없이 종료(F7 금지).", flush=True)
    finally:
        await browser.close()
        await pw.stop()


async def _drain_forever(q: asyncio.Queue) -> None:
    while True:
        await q.get()


async def _run_dump_partners(results: dict) -> None:
    """카드 문맥(code_sync._run_entry_chain 미러)에서 dump_partners 실측 — 총수·소요시간."""
    from app.services import code_sync

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    try:
        print("\n[dump] 카드 진입 체인…", flush=True)
        await code_sync._run_entry_chain(page, USERID, PASSWORD)
        t0 = time.monotonic()
        rows = await trip_steps.dump_partners(page)
        dt = int((time.monotonic() - t0) * 1000)
        results["dump_partners"] = {"count": len(rows), "ms": dt, "sample": rows[:5]}
        print(f"[dump] 거래처 총 {len(rows)}건, {dt}ms, sample={rows[:3]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        results["dump_partners"] = {"error": repr(exc)}
        print(f"[dump][ERROR] {exc!r}", flush=True)
    finally:
        await browser.close()
        await pw.stop()


async def main() -> None:
    results: dict = {"userid": USERID}
    try:
        await _run_fill(results)
    except Exception as exc:  # noqa: BLE001
        results["fill_error"] = repr(exc)
        print(f"[fill][ERROR] {exc!r}", flush=True)
    try:
        await _run_dump_partners(results)
    except Exception as exc:  # noqa: BLE001
        results["dump_error"] = repr(exc)
    (ARTIFACTS / "trip_fill_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("\n[dump] trip_fill_results.json 저장. 완료(저장 없이 종료).", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
