"""HEADLESS 프로브 — 구매발주일괄입력[나인벨](PUOORD02000) `구매요청` 팝업 하단 적용이
품목거래처명(PRINCIPALPARTN_NM) 공란 행에서 왜 실패하는지(팝업 미소멸) 원인 확정.

omnisol-flow-prober 위임(2026-09-01). 트리거: 라이브 런 실패
"PRQ2026090017: 하단 적용 후 팝업이 닫히지 않았습니다."
(`app.agents.purchase_order.steps_screen3.popup_bottom_apply` — 적용 클릭 → scan_dialog 4s
→ [예] → `_wait_popup(False)` 20s 초과). PRQ2026090015·016 은 같은 흐름으로 성공.

가설:
  H1 — ERP 가 거래처 없는 행의 하단 적용을 거부(경고/무반응)해 팝업이 안 닫힌다.
  H2 — 두 번째 다이얼로그가 popup_bottom_apply 의 4s scan_dialog 창 이후 늦게 뜬다.
  H3 — [예] 클릭이 미적중(dews msgbox 는 로케이터 클릭만 먹는 케이스).

방법(팀리드 지시 시퀀스 그대로):
  1. 로그인(이트라이브2/1111) → SCM 전환 → 화면③ 진입 → 원재료 → 구매요청 팝업 →
     PRQ2026090017 조회.
  2. 행 전수 덤프 — PRINCIPALPARTN_NM 공란 행 존재/개수/인덱스 확정.
  3. 실험(a) 최소 재현 — 공란 행 1행만 체크 → 하단 적용 → 5초 타임라인(0.3s 간격,
     다이얼로그/스낵바/팝업상태) → [예] 뜨면 클릭 후 계속 관찰.
  4. 실험(b) 대조 — 공란 행 제외 실거래처 행만 체크 → 하단 적용 → 같은 타임라인.
  5. 정리 — 저장(F7) 금지. 딥링크 재진입으로 초기화, 마스터 0행 확인.

재사용: nbkit.patterns.{login_flow,user_type_flow}, nbkit.omnisol.navigator.navigate_menu,
  app.agents.purchase_order.{js as po_js, js_screen3 as j3, steps_screen3 as s3,
  steps_write as po_write}(ensure_po_type/open_request_popup/popup_query_prq/click_dialog_button/
  scan_dialog), app.live.runner._ScaledPage.
신규: 이 파일 로컬 타임라인 캡처 헬퍼(`_timeline_capture`) — 팀리드가 요구한 0.3s 간격
  다이얼로그/스낵바/팝업상태 동시 관찰은 기존 프리미티브(1회성 scan_dialog)에 없어 새로 작성.

Usage:
    cd backend && .venv/bin/python e2e/purchase_order_bottom_apply_empty_vendor_probe.py
env:
    E2E_HEADLESS=1(기본, 헤드리스) / 0(헤디드)
    E2E_USERID/E2E_PASSWORD (기본 이트라이브2/1111)
    E2E_DELAY_SCALE (기본 0.4 — 등록된 purchase-order 워크플로우 delay_scale 그대로 재현)
    E2E_PRQ (기본 PRQ2026090017)

안전: 저장(F7/💾)·상신·보관 절대 금지. 하단 적용은 비가역 아님(PROCESS.md D8 실측 —
딥링크 재진입만으로 초기화) — 각 실험 후 재진입으로 폐기.
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
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))  # 등록된 purchase-order 배율
SLOW_MO_MS = int(os.environ.get("E2E_SLOW_MO", "0"))
PRQ = os.environ.get("E2E_PRQ", "PRQ2026090017")
VIEWPORT = {"width": 1920, "height": 1200}
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DEEPLINK_SCREEN3 = "/PU/PUOORD02000_X20616"
LABEL_SCREEN3 = "구매발주일괄입력[나인벨]"

TIMELINE_DURATION_MS = 5_000
TIMELINE_INTERVAL_MS = 300


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"po_empty_vendor_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"po_empty_vendor_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def stage(name: str) -> None:
    print(f"\n===== STAGE: {name} =====", flush=True)


async def _timeline_capture(page: Page, *, duration_ms: int, interval_ms: int) -> dict:
    """0.3s 간격으로 {다이얼로그, 스낵바, 팝업상태} 를 동시 관찰. 적용 확인 다이얼로그가
    보이면 [예] 를 1회만 클릭(그 이전 프레임의 원문은 이미 기록됐다) 하고 계속 관찰한다.
    반환 {"entries": [...], "yes_clicked_at_ms": int|None, "final_popup": {...}}.
    """
    entries: list[dict] = []
    yes_clicked_at: int | None = None
    t0 = time.monotonic()
    while True:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if elapsed_ms >= duration_ms:
            break
        dlgs = await page.evaluate(po_js.DIALOGS_JS) or []
        snacks = await page.evaluate(po_js.SNACKBARS_JS) or []
        popup_state = await page.evaluate(j3.POPUP_PRESENT_JS) or {}
        entries.append(
            {
                "t_ms": elapsed_ms,
                "dialogs": dlgs,
                "snacks": [s.get("text") for s in snacks if s.get("text")],
                "popup": popup_state,
            }
        )
        if yes_clicked_at is None:
            cand = next((d for d in dlgs if "예" in (d.get("buttons") or [])), None)
            if cand:
                clicked = await po_write.click_dialog_button(page, "예")
                yes_clicked_at = elapsed_ms
                print(f"   [{elapsed_ms}ms] dialog {cand.get('text')!r} btns={cand.get('buttons')} → [예] clicked={clicked}", flush=True)
        await asyncio.sleep(interval_ms / 1000)
    final_popup = await page.evaluate(j3.POPUP_PRESENT_JS) or {}
    return {"entries": entries, "yes_clicked_at_ms": yes_clicked_at, "final_popup": final_popup}


async def _close_leftover_dialogs(page: Page, *, tries: int = 3) -> list[str]:
    """실험 정리용 — 남은 확인 다이얼로그를 아니요/취소/확인 순으로 닫는다."""
    closed: list[str] = []
    for _ in range(tries):
        dlgs = await page.evaluate(po_js.DIALOGS_JS) or []
        cand = next((d for d in dlgs if d.get("buttons")), None)
        if not cand:
            break
        btns = cand.get("buttons") or []
        pick = next((b for b in ("아니요", "취소", "닫기", "확인") if b in btns), btns[0])
        await po_write.click_dialog_button(page, pick)
        closed.append(f"{cand.get('text', '')[:60]!r}→{pick}")
        await asyncio.sleep(0.5)
    return closed


async def _reenter_screen3(page: Page, base: str) -> dict:
    """딥링크 재진입으로 미저장 변경 폐기 → 마스터 rowcount 확인(기대 0)."""
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


async def _setup_popup(page: Page, base: str) -> dict:
    """화면③ 진입(또는 재진입) → 원재료 → 구매요청 팝업 → PRQ 조회. 실패 시 {"ok": False}."""
    r0 = await s3.ensure_po_type(page)
    if not r0.get("ok"):
        return {"ok": False, "reason": f"ensure_po_type 실패 — {r0}"}
    r1 = await s3.open_request_popup(page)
    if not r1.get("ok"):
        return {"ok": False, "reason": f"open_request_popup 실패 — {r1}"}
    r2 = await s3.popup_query_prq(page, PRQ, tries=4)
    if not r2.get("ok"):
        return {"ok": False, "reason": f"popup_query_prq({PRQ}) 실패 — {r2}"}
    return {"ok": True, "query": r2}


async def _run_bottom_apply_experiment(page: Page, *, name: str, row_idxs: list[int]) -> dict:
    """지정 행만 체크 → 하단 적용 클릭 → 타임라인 캡처. 저장(F7) 호출 없음."""
    result: dict = {"row_idxs": row_idxs}
    r0 = await page.evaluate(j3.POPUP_CHECK_ALL_JS, [0, False])
    result["uncheck_all"] = r0
    r1 = await page.evaluate(j3.POPUP_CHECK_ROWS_JS, [0, row_idxs])
    result["check_rows"] = r1
    got = sorted(int(x) for x in (r1.get("checked") or []))
    if not r1.get("ok") or got != sorted(row_idxs):
        result["ok"] = False
        result["reason"] = f"행 체크 불일치 — 기대 {sorted(row_idxs)} / 실제 {got}"
        return result
    await _shot(page, f"{name}_00_checked")

    box = await page.evaluate(j3.POPUP_BOTTOM_APPLY_BOX_JS)
    result["apply_btn_box"] = box
    if not box:
        result["ok"] = False
        result["reason"] = "팝업 하단 '적용' 버튼을 찾지 못했습니다."
        return result

    await page.mouse.click(box["x"], box["y"])
    print(f"[{name}] 하단 적용 클릭 → {TIMELINE_DURATION_MS}ms 타임라인 관찰 시작", flush=True)
    tl = await _timeline_capture(page, duration_ms=TIMELINE_DURATION_MS, interval_ms=TIMELINE_INTERVAL_MS)
    result["timeline"] = tl
    await _shot(page, f"{name}_01_after_timeline")

    popup_present = bool((tl.get("final_popup") or {}).get("present"))
    result["popup_present_after"] = popup_present
    if popup_present:
        closed = await _close_leftover_dialogs(page)
        result["cleanup_dialogs_closed"] = closed
        still = await page.evaluate(j3.POPUP_PRESENT_JS) or {}
        result["popup_present_after_cleanup"] = still.get("present")
        await _shot(page, f"{name}_02_after_cleanup")
    else:
        master_n = await page.evaluate(j3.MAIN_GRID_COUNT_JS, 0)
        result["master_rows_after"] = master_n
        if isinstance(master_n, int) and master_n > 0:
            rows = await page.evaluate(j3.MAIN_GRID_ROWS_JS, [0, master_n])
            result["master_rows_sample"] = rows.get("rows")

    result["ok"] = True  # 실험 자체는 완주(관찰 목적) — 팝업 잔존 여부는 별도 필드로 판정.
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

        await stage(f"3. 원재료 → 구매요청 팝업 → {PRQ} 조회")
        setup = await _setup_popup(page, base)
        results["setup"] = setup
        if not setup.get("ok"):
            print(f"[FATAL] {setup.get('reason')}", flush=True)
            _dump("results", results)
            return
        await _shot(raw_page, "02_popup_queried")

        await stage("4. 행 전수 덤프 — 품목거래처명 공란 행 확정")
        q = setup["query"]
        rows = q.get("rows") or []
        idxs = q.get("idxs") or []
        row_dump = []
        empty_idxs: list[int] = []
        real_idxs: list[int] = []
        for real_i, r in zip(idxs, rows):
            partner = str(r.get("PRINCIPALPARTN_NM") or "").strip()
            entry = {
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
            row_dump.append(entry)
            if partner:
                real_idxs.append(real_i)
            else:
                empty_idxs.append(real_i)
        results["row_dump"] = row_dump
        results["empty_vendor_idxs"] = empty_idxs
        results["real_vendor_idxs"] = real_idxs
        print(f"[rows] 전체 {len(row_dump)}행 — 공란거래처 {len(empty_idxs)}개 idx={empty_idxs}, 실거래처 {len(real_idxs)}개 idx={real_idxs[:10]}{'...' if len(real_idxs) > 10 else ''}", flush=True)
        _dump("04_row_dump", {"row_dump": row_dump, "empty_idxs": empty_idxs, "real_idxs": real_idxs})

        if not empty_idxs:
            print("[WARN] 공란 거래처 행이 이 PRQ 에 없습니다 — 재현 대상 자체가 없을 수 있습니다. 계속 진행은 하되 결과 해석에 반영.", flush=True)

        # ── 실험 (a): 공란 행 1행만 체크 → 하단 적용 ─────────────────────────────
        if empty_idxs:
            await stage("5. 실험(a) 최소 재현 — 공란 거래처 행 1행만 체크 → 하단 적용")
            exp_a = await _run_bottom_apply_experiment(page, name="expA_empty", row_idxs=[empty_idxs[0]])
            results["exp_a"] = exp_a
            print(f"[exp_a] popup_present_after={exp_a.get('popup_present_after')} master_rows_after={exp_a.get('master_rows_after')}", flush=True)
            _dump("results_partial", results)

            await stage("6. 실험(a) 정리 — 재진입 폐기")
            reentry_a = await _reenter_screen3(raw_page, base)
            results["reentry_after_a"] = reentry_a
            print(f"[reentry_a] {reentry_a}", flush=True)
        else:
            results["exp_a"] = {"skipped": "no empty vendor rows found"}

        # ── 실험 (b): 공란 행 제외, 실거래처 행 2~3개만 체크 → 하단 적용(대조) ──────
        await stage("7. 실험(b) 준비 — 화면③ 재진입 → 원재료 → 구매요청 팝업 → PRQ 재조회")
        setup2 = await _setup_popup(page, base)
        results["setup2"] = setup2
        if not setup2.get("ok"):
            print(f"[FATAL] {setup2.get('reason')}", flush=True)
            _dump("results", results)
            return
        q2 = setup2["query"]
        rows2 = q2.get("rows") or []
        idxs2 = q2.get("idxs") or []
        real_idxs2 = [i for i, r in zip(idxs2, rows2) if str(r.get("PRINCIPALPARTN_NM") or "").strip()]
        contrast_idxs = real_idxs2[:3]
        results["exp_b_candidate_idxs"] = contrast_idxs
        if not contrast_idxs:
            print("[WARN] 실거래처 행이 없어 대조 실험을 건너뜁니다.", flush=True)
            results["exp_b"] = {"skipped": "no real vendor rows found on reload"}
        else:
            await stage(f"8. 실험(b) 대조 — 실거래처 행 {contrast_idxs} 체크 → 하단 적용")
            exp_b = await _run_bottom_apply_experiment(page, name="expB_real", row_idxs=contrast_idxs)
            results["exp_b"] = exp_b
            print(f"[exp_b] popup_present_after={exp_b.get('popup_present_after')} master_rows_after={exp_b.get('master_rows_after')}", flush=True)
        _dump("results_partial", results)

        await stage("9. 최종 정리 — 재진입 폐기 + 마스터 0행 확인(잔존 0)")
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
