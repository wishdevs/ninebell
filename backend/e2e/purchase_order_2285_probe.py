"""HEADLESS 읽기전용(부작용 0) 프로브 — Task A: 프로젝트 2285(GY03-019) 발주 대상 판정
+ 3-way 체크박스 비교(둘다체크/구매요청만/이동요청만) + 재조회 시 초기화 확인 다이얼로그 실측.

omnisol-flow-prober 위임(2026-08-25, purchase_order PROCESS.md D4·D5·D10 검증 대상).
검증된 `app.agents.purchase_order.steps` 프리미티브(apply_project/set_checkbox/
click_lookup/read_bom_signature)를 그대로 재사용한다 — 새로 추가한 것은 그리드 전량
분포 덤프(TREEGRID_FULL_DIST_JS)와 다중 조회(2·3회차) 확인 다이얼로그 스캐너,
시그니처 변화 대기(_wait_signature_settle, wait_bom_filtered 의 mvY==0 하드코딩을
일반화한 버전 — 3번째 시나리오(이동요청만)는 mvY==0 이 아니라 반대이므로)뿐이다.

⛔ 읽기 전용 — 저장(F7)/구매요청 버튼/요청취소/요청마감/마감취소/상신/결재 절대 금지.
허용되는 클릭: 사용자유형 전환, 프로젝트 도움창 검색/선택/'적용'(조회조건 세팅일 뿐 —
purchase_order_project_apply_probe.py 선례로 승인됨), 체크박스 토글, 조회(F2), 뜬 확인
다이얼로그의 '예' 클릭.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_2285_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.purchase_order import js as po_js  # noqa: E402
from app.agents.purchase_order import steps as po_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.omnisol.errors import MenuError  # noqa: E402
from nbkit.omnisol.navigator import navigate_menu  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DEEPLINK = "/PU/PUOPRQ00200_X20616"
MENU_LABEL = "프로젝트BOM구매요청[나인벨]"
KEYWORD = "GY03-019"  # PJT_NO 2285 = "GY03-019, 12CH-L3" — 콤마 앞 토큰(숫자 검색 금지, D10 실측)
PJT_NO = "2285"

# 트리그리드 전량 분포 — 레벨/PUR_FG/MV_FG/WBS_NM 카운트 + level==3(SET) 별 level==4 리프 개수.
# 인덱스 공간 규율(app/agents/purchase_order/js.py TREEGRID_READ_JS 실측 그대로): ds.getValue 만
# 사용, 루프는 1..count 포함(0=숨은 루트).
TREEGRID_FULL_DIST_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    if (!el) return { ok: false, reason: 'no-treegrid' };
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    const levelCounts = {};
    const purFg = { Y: 0, N: 0, other: 0 };
    const mvFg = { Y: 0, N: 0, other: 0 };
    const wbsCounts = {};
    const sets = [];
    let cur = null;
    for (let i = 1; i <= count; i++) {
      let level = -1;
      try { level = ds.getLevel(i); } catch (e) {}
      levelCounts[level] = (levelCounts[level] || 0) + 1;
      let pf = null, mf = null, wbs = null;
      try { pf = ds.getValue(i, 'PUR_FG'); } catch (e) {}
      try { mf = ds.getValue(i, 'MV_FG'); } catch (e) {}
      try { wbs = ds.getValue(i, 'WBS_NM'); } catch (e) {}
      if (pf === 'Y') purFg.Y++; else if (pf === 'N') purFg.N++; else purFg.other++;
      if (mf === 'Y') mvFg.Y++; else if (mf === 'N') mvFg.N++; else mvFg.other++;
      if (level >= 2 && wbs) { const k = String(wbs); wbsCounts[k] = (wbsCounts[k] || 0) + 1; }
      if (level === 3) {
        let itemCd = null, itemNm = null;
        try { itemCd = ds.getValue(i, 'ITEM_CD'); } catch (e) {}
        try { itemNm = ds.getValue(i, 'ITEM_NM'); } catch (e) {}
        cur = { i, ITEM_CD: itemCd, ITEM_NM: itemNm, leafCount: 0 };
        sets.push(cur);
      } else if (level === 4) {
        if (cur) cur.leafCount++;
      } else if (level <= 2) {
        cur = null;
      }
    }
    return { ok: true, count, levelCounts, purFg, mvFg, wbsCounts, sets };
  } catch (e) { return { ok: false, err: String(e).slice(0, 200) }; }
}"""

# 조회 후 뜰 수 있는 확인 다이얼로그(예/아니오·확인/취소 등) 스캔 —
# purchase_order_checkbox_filter_probe.py 의 CONFIRM_DIALOG_JS 그대로 재사용.
CONFIRM_DIALOG_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window, .k-dialog, [role=alertdialog]')].filter(w => w.offsetParent !== null);
  return wins.map(w => {
    const title = c((w.querySelector('.k-window-title')||{}).innerText);
    const text = c(w.innerText).slice(0, 200);
    const buttons = [...w.querySelectorAll('button')].filter(b => b.offsetParent !== null).map(b => c(b.innerText));
    const r = w.getBoundingClientRect();
    return { title, text, buttons, rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } };
  });
}"""

CONFIRM_BTN_BOX_JS = r"""(btnText) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window, .k-dialog')].filter(w => w.offsetParent !== null);
  for (const w of wins) {
    const b = [...w.querySelectorAll('button')].find(x => x.offsetParent !== null && c(x.innerText) === btnText);
    if (b) { const r = b.getBoundingClientRect(); return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }; }
  }
  return null;
}"""


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_2285_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_2285_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _wait_signature_settle(page: Page, prev_sig: dict | None, *, cap_s: float = 15.0, poll_s: float = 0.3) -> dict | None:
    """조회 후 시그니처가 prev 와 달라지고 연속 2회 동일(정착)할 때까지 대기(스테일그리드 방지).

    steps.wait_bom_filtered 는 '구매요청만'(mvY==0 하드코딩) 전용이라, 3번째 시나리오
    (이동요청만 — mvY 는 오히려 >0)에 그대로 못 쓴다 — 그 판정 로직을 일반화한 프로브 전용 버전.
    0행도 유효한 결과로 인정한다(진짜 데이터 없음과 타임아웃을 구분 못 하는 문제는 상한 소진 시
    마지막 관측치를 그대로 반환해 호출부가 판단하게 한다).
    """
    t0 = time.monotonic()
    stable: dict | None = None
    last: dict | None = None
    while (time.monotonic() - t0) < cap_s:
        sig = await po_steps.read_bom_signature(page)
        last = sig
        changed = sig is not None and (prev_sig is None or sig != prev_sig)
        if changed:
            if stable == sig:
                return sig
            stable = sig
        else:
            stable = None
        await page.wait_for_timeout(int(poll_s * 1000))
    return last


async def _query_and_scan(page: Page, *, label: str, query_num: int, prev_sig: dict | None) -> tuple[dict, dict | None]:
    result: dict = {"label": label, "query_num": query_num}
    lookup = await po_steps.click_lookup(page)
    result["click_lookup"] = lookup

    # 확인 다이얼로그 조밀 폴링(최대 3s) — 사용자 보고 '재조회 시 초기화 메시지' 실측 대상.
    dialog_seen = None
    t0 = time.monotonic()
    while (time.monotonic() - t0) < 3.0:
        dialogs = await page.evaluate(CONFIRM_DIALOG_JS)
        cand = next(
            (d for d in dialogs if d["buttons"] and len(d["buttons"]) <= 3 and "프로젝트" not in d["title"]),
            None,
        )
        if cand:
            dialog_seen = cand
            break
        await page.wait_for_timeout(150)
    result["dialog_seen"] = dialog_seen
    if dialog_seen:
        await _shot(page, f"q{query_num}_{label}_dialog")
        btn_text = next(
            (b for b in dialog_seen["buttons"] if b in ("예", "확인", "OK", "Yes")),
            dialog_seen["buttons"][0],
        )
        box = await page.evaluate(CONFIRM_BTN_BOX_JS, btn_text)
        result["dialog_button_clicked"] = btn_text
        result["dialog_button_box"] = box
        if box:
            await page.mouse.click(box["x"], box["y"])

    sig = await _wait_signature_settle(page, prev_sig)
    result["signature_after"] = sig
    await page.wait_for_timeout(800)
    await _shot(page, f"q{query_num}_{label}_after")
    dist = await page.evaluate(TREEGRID_FULL_DIST_JS)
    result["distribution"] = dist
    return result, sig


async def main() -> None:
    results: dict = {"userid": USERID, "keyword": KEYWORD, "pjt_no": PJT_NO}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    # 가설: '초기화 메시지' 가 커스텀 .k-window 가 아니라 네이티브 confirm()/alert() 일 수 있다 —
    # 리스너가 없으면 Playwright 가 조용히 자동 묵살(dismiss)해 DOM 스캐너에 절대 안 잡힌다.
    native_dialogs: list[dict] = []

    async def _on_native_dialog(dialog) -> None:
        entry = {"type": dialog.type, "message": dialog.message}
        native_dialogs.append(entry)
        print(f"[NATIVE DIALOG] {entry}", flush=True)
        await dialog.accept()  # '예/확인' 상당 — 조회일 뿐이라 진행 허용.

    raw_page.on("dialog", lambda d: asyncio.ensure_future(_on_native_dialog(d)))

    try:
        print("[entry] login + SCM 전환 + 메뉴 진입…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")
        try:
            await navigate_menu(page, DEEPLINK, base, label=MENU_LABEL, grids_required=1)
        except MenuError as exc:
            results["menu_entry_error"] = str(exc)
            await _dump("results", results)
            return
        await page.wait_for_timeout(1_500)

        print(f"[project] apply_project({KEYWORD!r}, {PJT_NO!r})…", flush=True)
        apply_res = await po_steps.apply_project(page, KEYWORD, PJT_NO)
        results["project_apply"] = apply_res
        print(f"[project] {apply_res}", flush=True)
        await _shot(page, "00_after_apply")
        if not apply_res.get("ok"):
            results["error"] = "프로젝트 적용 실패 — 이하 체크박스 비교 신뢰불가, 중단"
            await _dump("results", results)
            return

        cb_init = {
            "구매요청": await page.evaluate(po_js.CHECKBOX_RECT_JS, "구매요청"),
            "이동요청": await page.evaluate(po_js.CHECKBOX_RECT_JS, "이동요청"),
        }
        results["checkbox_initial"] = cb_init
        print(f"[checkbox] 초기상태={cb_init}", flush=True)

        # ── Q1: 둘 다 체크(초기상태) 그대로 조회(1회차) ──
        r1, sig1 = await _query_and_scan(page, label="both_checked", query_num=1, prev_sig=None)
        results["q1_both_checked"] = r1
        print(
            f"[q1] dialog={r1.get('dialog_seen')} "
            f"count={r1['distribution'].get('count')} levelCounts={r1['distribution'].get('levelCounts')}",
            flush=True,
        )

        # ── Q2: 이동요청 해제(구매요청만) → 조회(2회차 — '초기화' 다이얼로그 후보) ──
        set_move_off = await po_steps.set_checkbox(page, "이동요청", False)
        results["set_이동요청_off"] = set_move_off
        r2, sig2 = await _query_and_scan(page, label="purreq_only", query_num=2, prev_sig=sig1)
        results["q2_purreq_only"] = r2
        print(
            f"[q2] dialog={r2.get('dialog_seen')} "
            f"count={r2['distribution'].get('count')} levelCounts={r2['distribution'].get('levelCounts')}",
            flush=True,
        )

        # ── Q3: 구매요청 해제 + 이동요청 재체크(이동요청만) → 조회(3회차 — '초기화' 다이얼로그 후보) ──
        set_pu_off = await po_steps.set_checkbox(page, "구매요청", False)
        set_move_on = await po_steps.set_checkbox(page, "이동요청", True)
        results["set_구매요청_off"] = set_pu_off
        results["set_이동요청_on"] = set_move_on
        r3, sig3 = await _query_and_scan(page, label="movreq_only", query_num=3, prev_sig=sig2)
        results["q3_movreq_only"] = r3
        print(
            f"[q3] dialog={r3.get('dialog_seen')} "
            f"count={r3['distribution'].get('count')} levelCounts={r3['distribution'].get('levelCounts')}",
            flush=True,
        )

        # ── Q4(가설 검증): 필터 변경 없이 동일 조건으로 재조회(4회차) — 사용자가 말한
        #    '다시 조회 버튼을 클릭하면 초기화 메시지' 가 필터 변경 여부와 무관하게 매 조회마다
        #    뜨는지, 아니면 '조건 변경 없는 재클릭'에만 뜨는지 가르는 대조군. ──
        # prev_sig=None(사용 안 함) — 필터 불변이라 sig3 와 동일한 값이 '정상'이므로 변화 대기를
        # 강제하면 상한(15s)을 매번 소진한다. 대신 두 번 연속 동일 관측(정착)만 확인한다.
        r4, sig4 = await _query_and_scan(page, label="movreq_only_repeat_unchanged", query_num=4, prev_sig=None)
        results["q4_movreq_only_repeat_unchanged"] = r4
        print(
            f"[q4-repeat] dialog={r4.get('dialog_seen')} "
            f"count={r4['distribution'].get('count')} levelCounts={r4['distribution'].get('levelCounts')}",
            flush=True,
        )

        # ── 핵심 판정: 구매요청만 필터에서 level==4 리프가 1개 이상인가 ──
        leaf_level4 = (r2["distribution"].get("levelCounts") or {}).get("4", 0)
        results["verdict_leaf_count_purreq_only"] = leaf_level4
        print(
            f"\n[VERDICT] 구매요청만(2285) level==4 리프 개수 = {leaf_level4} → "
            f"{'발주 대상 있음' if leaf_level4 else '발주 대상 없음(리프 0)'}",
            flush=True,
        )

        # ── 재조회 다이얼로그 요약(사용자 확인 요청 대상) ──
        dialog_summary = {
            f"query_{q['query_num']}_{q['label']}": bool(q.get("dialog_seen"))
            for q in (r1, r2, r3, r4)
        }
        results["dialog_summary"] = dialog_summary
        print(f"[dialog_summary] {dialog_summary}", flush=True)
        results["native_dialogs"] = native_dialogs
        print(f"[native_dialogs] {native_dialogs}", flush=True)

        await _dump("results", results)
        print("\n===== 2285 PROBE COMPLETE (읽기 전용) =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        results["native_dialogs"] = native_dialogs
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
