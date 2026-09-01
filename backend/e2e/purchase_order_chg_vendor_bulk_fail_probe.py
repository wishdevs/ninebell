"""HEADLESS 프로브 — 구매발주일괄입력[나인벨](PUOORD02000) `구매요청` 팝업 변경거래처 적용이
왜 33/33행 전부 미반영으로 끝났는지 원인 확정.

omnisol-flow-prober 위임(2026-09-01). 트리거: 라이브 런 4d252115(ETRI-011) 실패 —
"PRQ2026090025: 팝업에 타 요청 잔존 539행 — 대상 42행만 선택합니다." 직후
"PRQ2026090025: 변경거래처 적용 미반영 행 33/33 — 예 {'CHG_PARTNER_NM': None, 'CHG_PARTNER_CD': None}"
(`app.agents.purchase_order.steps_screen3.popup_apply_vendor` — 체크→피커 '알파테크'→#btn_apply→
6s 폴 전부 None). 계획 매핑(seq 1): 판금품→알파테크 33행, 가공품→해룡 1행, 나머지 실거래처 8행.

가설(팀리드 지시):
  H-A 필터 미적용 재현성 — popup_query_prq 가 지금도 타 요청 539행을 남기는가, 재시도(Enter
      재입력)로 좁혀지는가.
  H-B 대용량 그리드에서 체크/적용 무력화 — 581행 상태에서 33행 체크→피커→#btn_apply 후 스낵바·
      반영시각(6s 넘는지 최대 20s)·getCheckedRows 유지를 타임라인으로 기록.
  H-C 행 좁힌 대조군 — 같은 581행 팝업에서 소규모(1행) 체크→적용이 정상 반영되는지 대조
      (서버 필터를 강제로 좁힐 수단이 없어, 배치 크기를 변수로 격리하는 근사 대조군).

방법: 로그인(이트라이브2/1111) → SCM 전환 → 화면③ 진입 → 원재료 → 구매요청 팝업 →
  PRQ2026090025 조회(H-A) → 행 전수 덤프 → 대조군 1행(가공품→해룡) 적용 타임라인(H-C) →
  재진입·재조회 → 본 재현 33행(판금품→알파테크) 적용 타임라인(H-B) → 정리(재진입, 마스터 0행).

재사용: nbkit.omnisol.{js_lib,codepicker,verify}, nbkit.patterns.{login_flow,user_type_flow},
  nbkit.omnisol.navigator.navigate_menu, app.agents.purchase_order.{js as po_js,
  js_screen3 as j3, steps_screen3 as s3(ensure_po_type/open_request_popup/popup_query_prq/
  vendor_keyword/norm), steps_write as po_write(click_dialog_button/scan_dialog/
  pick_code_document/click_by_id)}, app.live.runner._ScaledPage.
신규(이 파일 로컬): 확장 타임라인 캡처(`_apply_timeline`, 20s·0.5s 간격, CHG_PARTNER_NM 샘플+
  체크상태+스낵바+다이얼로그 동시 관찰) — 기존 popup_apply_vendor 의 1회성 6s 폴보다 길고
  진단정보가 많아 이 프로브 전용으로 새로 작성(empty_vendor 프로브의 _timeline_capture 패턴 재사용).

Usage:
    cd backend && .venv/bin/python e2e/purchase_order_chg_vendor_bulk_fail_probe.py
env:
    E2E_HEADLESS=1(기본) / 0(헤디드)
    E2E_USERID/E2E_PASSWORD (기본 이트라이브2/1111)
    E2E_DELAY_SCALE (기본 0.4 — 등록된 purchase-order 워크플로우 배율 그대로 재현)
    E2E_PRQ (기본 PRQ2026090025)

안전: 저장(F7/💾)·상신·보관·하단 적용 절대 금지. 팝업 내 변경거래처 [적용]·행 체크·조회만.
  각 실험 후 재진입으로 폐기, 최종 마스터 0행 확인.
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
from app.agents.purchase_order import js_screen3 as j3  # noqa: E402
from app.agents.purchase_order import steps_screen3 as s3  # noqa: E402
from app.agents.purchase_order import steps_write as po_write  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import _ScaledPage  # noqa: E402
from nbkit.omnisol.errors import MenuError  # noqa: E402
from nbkit.omnisol.navigator import navigate_menu  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") == "1"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))  # 등록된 purchase-order 배율 재현
SLOW_MO_MS = int(os.environ.get("E2E_SLOW_MO", "0"))
PRQ = os.environ.get("E2E_PRQ", "PRQ2026090025")
VIEWPORT = {"width": 1920, "height": 1200}
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DEEPLINK_SCREEN3 = "/PU/PUOORD02000_X20616"
LABEL_SCREEN3 = "구매발주일괄입력[나인벨]"
VENDOR_HAERYONG = "주식회사 해룡엔지니어링"
VENDOR_ALPHA = "알파테크"

TIMELINE_DURATION_MS = 20_000
TIMELINE_INTERVAL_MS = 500


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"po_chgvendor_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"po_chgvendor_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def stage(name: str) -> None:
    print(f"\n===== STAGE: {name} =====", flush=True)


async def _setup_popup(page: Page) -> dict:
    r0 = await s3.ensure_po_type(page)
    if not r0.get("ok"):
        return {"ok": False, "reason": f"ensure_po_type 실패 — {r0}"}
    r1 = await s3.open_request_popup(page)
    if not r1.get("ok"):
        return {"ok": False, "reason": f"open_request_popup 실패 — {r1}"}
    return {"ok": True}


async def _reenter_screen3(page: Page, base: str) -> dict:
    try:
        await page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.5)
    try:
        await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=2)
    except MenuError as exc:
        await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=1)
        return {"entry_retry": str(exc)}
    await asyncio.sleep(1.5)
    n = await page.evaluate(j3.MAIN_GRID_COUNT_JS, 0)
    return {"master_rowcount_after_reentry": n}


async def _extra_enter_probe(page: Page, *, tries: int = 3) -> list[dict]:
    """H-A — 이미 조회된 상태에서 Enter 를 추가로 눌러 행수가 좁혀지는지 관찰."""
    out = []
    for i in range(1, tries + 1):
        await page.keyboard.press("Enter")
        await asyncio.sleep(1.0)
        n = await page.evaluate(j3.POPUP_GRID_COUNT_JS, 0)
        out.append({"attempt": i, "rowcount": n})
        print(f"   [extra-enter {i}] rowcount={n}", flush=True)
    return out


async def _row_dump(rows: list[dict], idxs: list[int]) -> list[dict]:
    out = []
    for real_i, r in zip(idxs, rows):
        out.append(
            {
                "real_idx": real_i,
                "PURREQ_NO": r.get("PURREQ_NO"),
                "ITEM_CD": r.get("ITEM_CD"),
                "ITEM_NM": r.get("ITEM_NM"),
                "PRINCIPALPARTN_NM": r.get("PRINCIPALPARTN_NM"),
                "PRINCIPALPARTN_CD": r.get("PRINCIPALPARTN_CD"),
                "CHG_PARTNER_NM": r.get("CHG_PARTNER_NM"),
                "CHG_PARTNER_CD": r.get("CHG_PARTNER_CD"),
                "WBS_NO": r.get("WBS_NO"),
            }
        )
    return out


async def _apply_timeline(
    page: Page,
    *,
    name: str,
    row_idxs: list[int],
    vendor_keyword: str,
    duration_ms: int,
    interval_ms: int,
) -> dict:
    """행 체크 → 변경거래처 피커 → #btn_apply → duration_ms 동안 0.5s 간격으로
    {CHG_PARTNER_NM 샘플, getCheckedRows, 스낵바, 다이얼로그} 동시 관찰.
    popup_apply_vendor(6s 고정 폴) 대신 20s 로 늘려 '6s 넘게 걸리다 반영되는지' 를 직접 본다.
    """
    result: dict = {"row_idxs": row_idxs, "vendor_keyword": vendor_keyword}
    await page.evaluate(j3.POPUP_CHECK_ALL_JS, [0, False])
    c = await page.evaluate(j3.POPUP_CHECK_ROWS_JS, [0, row_idxs])
    got = sorted(int(x) for x in (c.get("checked") or []))
    result["check_result"] = c
    if not c.get("ok") or got != sorted(row_idxs):
        result["ok"] = False
        result["reason"] = f"팝업 행 체크 불일치 — 기대 {len(row_idxs)} / 실제 {len(got)}"
        return result
    await _shot(page, f"{name}_00_checked")

    p = await po_write.pick_code_document(page, s3.POPUP_VENDOR_FIELD, vendor_keyword)
    result["picker"] = p
    if not p.get("ok"):
        result["ok"] = False
        result["reason"] = f"변경거래처 '{vendor_keyword}' 선택 실패 — {p.get('reason')}"
        return result
    await _shot(page, f"{name}_01_vendor_picked")

    a = await po_write.click_by_id(page, s3.POPUP_APPLY_BTN)
    result["apply_click"] = a
    if not a.get("ok"):
        result["ok"] = False
        result["reason"] = f"#{s3.POPUP_APPLY_BTN} 클릭 실패 — {a}"
        return result

    print(f"[{name}] #btn_apply 클릭 → {duration_ms}ms 타임라인 관찰 시작", flush=True)
    sample_idxs = row_idxs[:3] + row_idxs[-1:] if len(row_idxs) > 3 else row_idxs
    entries: list[dict] = []
    t0 = time.monotonic()
    first_reflect_ms: int | None = None
    while True:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if elapsed_ms >= duration_ms:
            break
        vals = await page.evaluate(j3.POPUP_FIELDS_JS, [0, sample_idxs, ["CHG_PARTNER_NM", "CHG_PARTNER_CD"]])
        checked = await page.evaluate(
            """() => { try {
                 const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
                   .filter(w=>!/법인카드/.test((w.querySelector('.k-window-title')||{}).innerText||''))
                   .slice(-1)[0];
                 const el = [...p.querySelectorAll('.dews-ui-grid')][0];
                 return (window.jQuery(el).data('dewsControl')._grid.getCheckedRows() || []).length;
               } catch (e) { return -1; } }"""
        )
        dlgs = await page.evaluate(po_js.DIALOGS_JS) or []
        snacks = [s.get("text") for s in (await page.evaluate(po_js.SNACKBARS_JS) or []) if s.get("text")]
        reflected = all(
            s3.norm(vendor_keyword) in s3.norm((vals.get(str(i)) or vals.get(i) or {}).get("CHG_PARTNER_NM"))
            for i in sample_idxs
        )
        if reflected and first_reflect_ms is None:
            first_reflect_ms = elapsed_ms
        entries.append(
            {
                "t_ms": elapsed_ms,
                "sample_vals": vals,
                "checked_rowcount": checked,
                "dialogs": [(d.get("text") or "")[:100] for d in dlgs],
                "snacks": snacks,
                "reflected_sample": reflected,
            }
        )
        if dlgs:
            cand = next((d for d in dlgs if d.get("buttons")), None)
            if cand:
                print(f"   [{elapsed_ms}ms] unexpected dialog {cand.get('text')!r} btns={cand.get('buttons')}", flush=True)
        await asyncio.sleep(interval_ms / 1000)
    result["timeline"] = entries
    result["first_reflect_ms"] = first_reflect_ms
    await _shot(page, f"{name}_02_after_timeline")

    final_vals = await page.evaluate(j3.POPUP_FIELDS_JS, [0, row_idxs, ["CHG_PARTNER_NM", "CHG_PARTNER_CD"]])
    bad = [
        i
        for i in row_idxs
        if s3.norm(vendor_keyword) not in s3.norm((final_vals.get(str(i)) or final_vals.get(i) or {}).get("CHG_PARTNER_NM"))
    ]
    result["final_vals_all_rows"] = final_vals
    result["bad_count"] = len(bad)
    result["bad_idxs"] = bad[:10]
    result["ok"] = len(bad) == 0
    print(
        f"[{name}] first_reflect_ms={first_reflect_ms} bad={len(bad)}/{len(row_idxs)} "
        f"final_checked_rowcount={entries[-1]['checked_rowcount'] if entries else None}",
        flush=True,
    )
    return result


async def main() -> None:
    results: dict = {"userid": USERID, "prq": PRQ, "delay_scale": DELAY_SCALE}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
    raw_page = await browser.new_page(viewport=VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    try:
        await stage("1. 로그인 + SCM 전환")
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")

        await stage("2. 화면③ 진입")
        try:
            await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=2)
        except MenuError as exc:
            results["entry_error"] = str(exc)
            await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=1)
        await asyncio.sleep(1.5)
        await _shot(raw_page, "01_landing")

        await stage(f"3. 원재료 → 구매요청 팝업 오픈")
        setup = await _setup_popup(page)
        results["setup"] = setup
        if not setup.get("ok"):
            print(f"[FATAL] {setup.get('reason')}", flush=True)
            _dump("results", results)
            return
        n_before_filter = await page.evaluate(j3.POPUP_GRID_COUNT_JS, 0)
        results["rowcount_before_filter"] = n_before_filter
        print(f"[popup] 필터 전 rowcount={n_before_filter}", flush=True)
        await _shot(raw_page, "02_popup_opened")

        await stage(f"4. H-A — {PRQ} 조회(popup_query_prq, trusted Enter)")
        q = await s3.popup_query_prq(page, PRQ, tries=4)
        results["query_prq"] = {k: v for k, v in q.items() if k != "rows"}
        results["query_prq"]["matched_count"] = len(q.get("rows") or [])
        print(
            f"[H-A] ok={q.get('ok')} matched={len(q.get('rows') or [])} foreign={q.get('foreign')} "
            f"count(전체)={q.get('count')}",
            flush=True,
        )
        await _shot(raw_page, "03_after_prq_query")
        if not q.get("ok"):
            print(f"[FATAL] popup_query_prq 실패 — {q.get('reason')}", flush=True)
            _dump("results", results)
            return

        await stage("5. H-A 추가 — Enter 재입력 3회로 좁혀지는지 관찰")
        extra = await _extra_enter_probe(page, tries=3)
        results["extra_enter_after_match"] = extra

        rows = q.get("rows") or []
        idxs = q.get("idxs") or []
        row_dump = await _row_dump(rows, idxs)
        results["row_dump"] = row_dump
        _dump("04_row_dump", row_dump)

        by_class: dict[str, list[int]] = {}
        for entry in row_dump:
            cls = str(entry.get("PRINCIPALPARTN_NM") or "").strip()
            by_class.setdefault(cls, []).append(entry["real_idx"])
        results["class_distribution"] = {k: len(v) for k, v in by_class.items()}
        print(f"[rows] 42행 분포: { {k: len(v) for k, v in by_class.items()} }", flush=True)

        pseudo_idxs = by_class.get("판금품") or []
        haeryong_idxs = by_class.get("가공품") or []
        results["pseudo_idxs_판금품"] = pseudo_idxs
        results["haeryong_idxs_가공품"] = haeryong_idxs

        # ── H-C 대조군: 같은 581행 팝업에서 1행(가공품)만 적용 ──────────────────
        if haeryong_idxs:
            await stage("6. H-C 대조군 — 가공품 1행만 체크 → 해룡 적용 → 20s 타임라인")
            exp_c = await _apply_timeline(
                page,
                name="expC_control_1row",
                row_idxs=haeryong_idxs[:1],
                vendor_keyword=VENDOR_HAERYONG,
                duration_ms=TIMELINE_DURATION_MS,
                interval_ms=TIMELINE_INTERVAL_MS,
            )
            results["exp_c_control"] = exp_c
            _dump("results_partial", results)
        else:
            results["exp_c_control"] = {"skipped": "가공품 행 없음"}

        await stage("7. 재진입 → 재조회(H-B 준비, 상태 초기화)")
        reentry1 = await _reenter_screen3(raw_page, base)
        results["reentry_after_c"] = reentry1
        setup2 = await _setup_popup(page)
        results["setup2"] = setup2
        if not setup2.get("ok"):
            print(f"[FATAL] {setup2.get('reason')}", flush=True)
            _dump("results", results)
            return
        q2 = await s3.popup_query_prq(page, PRQ, tries=4)
        results["query_prq_2"] = {k: v for k, v in q2.items() if k != "rows"}
        results["query_prq_2"]["matched_count"] = len(q2.get("rows") or [])
        print(f"[H-B setup] matched={len(q2.get('rows') or [])} foreign={q2.get('foreign')}", flush=True)
        if not q2.get("ok"):
            print(f"[FATAL] 재조회 실패 — {q2.get('reason')}", flush=True)
            _dump("results", results)
            return

        rows2 = q2.get("rows") or []
        idxs2 = q2.get("idxs") or []
        by_class2: dict[str, list[int]] = {}
        for real_i, r in zip(idxs2, rows2):
            cls = str(r.get("PRINCIPALPARTN_NM") or "").strip()
            by_class2.setdefault(cls, []).append(real_i)
        pseudo_idxs2 = by_class2.get("판금품") or []
        results["pseudo_idxs2_판금품"] = pseudo_idxs2

        # ── H-B 본 재현: 33행(판금품) 체크 → 알파테크 적용 ──────────────────────
        if pseudo_idxs2:
            await stage(f"8. H-B 본 재현 — 판금품 {len(pseudo_idxs2)}행 체크 → 알파테크 적용 → 20s 타임라인")
            exp_b = await _apply_timeline(
                page,
                name="expB_repro_33row",
                row_idxs=pseudo_idxs2,
                vendor_keyword=VENDOR_ALPHA,
                duration_ms=TIMELINE_DURATION_MS,
                interval_ms=TIMELINE_INTERVAL_MS,
            )
            results["exp_b_repro"] = exp_b
            _dump("results_partial", results)
        else:
            results["exp_b_repro"] = {"skipped": "판금품 행 없음(재조회에서 매칭 실패)"}

        # ── H-D — 필터를 아예 걸지 않은 581행 그대로에서, 타겟 PRQ 행을 클라이언트측으로만
        #    찾아(Enter 미실행) 그 '흩어진 실 인덱스'를 체크→적용. 라이브 실패(foreign=539)의
        #    핵심 변수는 '필터 미적용으로 그리드가 크다'가 아니라 '타겟 행이 넓은 그리드에
        #    흩어져 있다'일 수 있어, 이번 실험 2회(H-B/H-C)가 못 만든 그 조건을 직접 만든다. ──
        await stage("10. 재진입 → 팝업만 열고 Enter 조회 없이 581행 그대로 유지(H-D 준비)")
        reentry2 = await _reenter_screen3(raw_page, base)
        results["reentry_before_d"] = reentry2
        setup3 = await _setup_popup(page)
        results["setup3"] = setup3
        if not setup3.get("ok"):
            print(f"[FATAL] {setup3.get('reason')}", flush=True)
            _dump("results", results)
            return
        n_raw = await page.evaluate(j3.POPUP_GRID_COUNT_JS, 0)
        results["rowcount_unfiltered_for_d"] = n_raw
        print(f"[H-D] Enter 미실행 — 원본 rowcount={n_raw}", flush=True)

        await stage("11. H-D — 원본 그리드에서 클라이언트측으로 PRQ 행만 매칭(흩어진 실 인덱스)")
        raw_read = await page.evaluate(j3.POPUP_GRID_ROWS_JS, [0, max(int(n_raw or 0), 700)])
        raw_rows = raw_read.get("rows") or []
        d_matched = [(i, r) for i, r in enumerate(raw_rows) if str(r.get("PURREQ_NO") or "").strip() == PRQ]
        results["d_matched_count"] = len(d_matched)
        d_real_idxs = [i for i, _ in d_matched]
        d_rows = [r for _, r in d_matched]
        d_by_class: dict[str, list[int]] = {}
        for real_i, r in d_matched:
            cls = str(r.get("PRINCIPALPARTN_NM") or "").strip()
            d_by_class.setdefault(cls, []).append(real_i)
        results["d_class_distribution"] = {k: len(v) for k, v in d_by_class.items()}
        d_pseudo_idxs = d_by_class.get("판금품") or []
        results["d_pseudo_idxs_판금품"] = d_pseudo_idxs
        # 흩어짐 정도 — 인접 인덱스 간 최대 gap(연속이면 gap=1).
        gaps = [b - a for a, b in zip(d_pseudo_idxs, d_pseudo_idxs[1:])] if len(d_pseudo_idxs) > 1 else []
        results["d_pseudo_idx_span"] = {
            "min": min(d_pseudo_idxs) if d_pseudo_idxs else None,
            "max": max(d_pseudo_idxs) if d_pseudo_idxs else None,
            "max_gap": max(gaps) if gaps else None,
        }
        print(
            f"[H-D] 미필터 {n_raw}행 중 {PRQ} 매칭 {len(d_matched)}행, 분포={results['d_class_distribution']}, "
            f"판금품 실인덱스 span={results['d_pseudo_idx_span']}",
            flush=True,
        )
        _dump("results_partial", results)

        if d_pseudo_idxs:
            await stage(f"12. H-D 본 실험 — 미필터 {n_raw}행 그리드에서 판금품 {len(d_pseudo_idxs)}행(흩어진 실인덱스) 체크 → 알파테크 적용 → 20s 타임라인")
            exp_d = await _apply_timeline(
                page,
                name="expD_unfiltered_scattered",
                row_idxs=d_pseudo_idxs,
                vendor_keyword=VENDOR_ALPHA,
                duration_ms=TIMELINE_DURATION_MS,
                interval_ms=TIMELINE_INTERVAL_MS,
            )
            results["exp_d_unfiltered"] = exp_d
            _dump("results_partial", results)
        else:
            results["exp_d_unfiltered"] = {"skipped": "미필터 상태에서 판금품 행을 못 찾음"}

        await stage("13. 최종 정리 — 재진입 폐기 + 마스터 0행 확인(잔존 0)")
        final_reentry = await _reenter_screen3(raw_page, base)
        results["final_reentry"] = final_reentry
        print(f"[final] {final_reentry}", flush=True)

        print("\n===== 프로브 완료 =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        _dump("results", results)
        raise
    finally:
        _dump("results", results)
        if HEADLESS:
            await browser.close()
        else:
            await asyncio.sleep(3)
            await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
