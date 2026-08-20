"""HEADLESS 독립 검증 + F6 삭제 — headed 동반 세션이 저장한 RN202608190005 전용(단발성).

team-lead 지시(2026-08-19): headed 세션에서 사용자가 직접 자금과목(FUND_CD) 반려를 해소하고
F7 저장에 성공한 전표 RN202608190005 를 별도 세션에서 독립 재조회하고, 마스터+detail 3행
raw 전량을 읽어(FEOTH_ACCT_CD 자동파생 확인·분할행 FUND_CD 상태 확인) 3중 가드 통과 후 F6 삭제,
잔존 0 을 확인한다.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 삭제 3중 가드(결의자=이트라이브2 + 결의구분=세금계산서(51) + 미결 DOCU_NO 공백) 완화 금지.
    하나라도 안 맞으면 삭제 중단·전표번호와 함께 보고.
  - 상신 절대 금지 — F6 삭제만.
  - `product_cycle.py`(hakjagum/gyeongjo 등 4종 스모크가 공유하는 검증된 모듈)의
    `open_erp_doc_screen`/`query_master`/`row_is_ours`/`delete_selected`/`GridProvider`
    그대로 재사용 — 신규 로직은 raw detail 전량 읽기(FEOTH_ACCT/FUND_CD 등 진단 필드 포함, 기존
    `collect_detail`은 DETAIL_FIELDS 로 필터링해 이 필드들이 안 보임)뿐이다.

Usage: cd backend && .venv/bin/python e2e/tax_invoice_rn005_verify_delete.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from e2e.product_cycle import (  # noqa: E402  (재사용 — hakjagum/gyeongjo 등 4종 스모크와 동일 모듈)
    ART,
    HEADLESS,
    MASTER_DUMP_JS,
    SELECT_MASTER_JS,
    SLOW_MO,
    delete_selected,
    open_erp_doc_screen,
    query_master,
    row_is_ours,
)
from nbkit.grid.provider import GridProvider  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402

GUBUN_LABEL = "세금계산서"
FG_CODE = "51"
TARGET_DOCNO = "RN202608190005"
TAG = "tax_invoice_rn005"

# raw 조사 대상 — team-lead 지시(FEOTH 자동파생 확인·FUND_CD 행별 상태) + 기존 진단 후보군.
FOCUS_FIELDS = [
    "SPPRC_AMT2", "SPPRC_AMT", "TAXAMT_AMT", "TOTAL_AMT", "NOTE_DC", "PARTNER_NM",
    "EVDN_CD", "EVDN_TP_NM", "ACCT_CD", "ACCT_NM", "FUND_CD",
    "FEOTH_ACCT_CD", "FEOTH_ACCT_NM", "BGACCT_FG_CD", "EVDN_MNDR_YN", "BIZR_NO_ORGN",
    "VAT_ACCT_CD", "VAT_ACCT_NM", "VAT_DRCRFG_CD", "STLM_WAY_CD", "CC_NM", "PJT_NM",
]


def _focus(row: dict) -> dict:
    return {k: row.get(k) for k in FOCUS_FIELDS}


async def main() -> None:
    result: dict = {"target_docno": TARGET_DOCNO, "gubun_label": GUBUN_LABEL, "fg_code": FG_CODE}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    try:
        print("[검증] ERP 직접 로그인 → GLDDOC00300 → 결의구분 세금계산서…", flush=True)
        await open_erp_doc_screen(page, GUBUN_LABEL)
        before = await query_master(page)
        result["before_count"] = before
        dump = await page.evaluate(MASTER_DUMP_JS, 0)
        rows = dump.get("rows") or []
        result["all_docnos"] = [str(r.get("ABDOCU_NO") or "") for r in rows]
        print(f"[검증] 조회 결과 {before}건 전표={result['all_docnos']}", flush=True)
        await page.screenshot(path=str(ART / f"{TAG}_before.png"))

        target_idx = next(
            (i for i, r in enumerate(rows) if str(r.get("ABDOCU_NO") or "") == TARGET_DOCNO), None,
        )
        result["target_found"] = target_idx is not None
        if target_idx is None:
            result["error"] = f"{TARGET_DOCNO} 를 조회 결과에서 찾지 못함(before={before}건)"
            print(f"[검증][FATAL] {result['error']}", flush=True)
            _dump(result)
            return

        target_row = rows[target_idx]
        result["master"] = {
            "ABDOCU_NO": str(target_row.get("ABDOCU_NO") or ""),
            "ABDOCU_FG_CD": str(target_row.get("ABDOCU_FG_CD") or ""),
            "WRT_EMP_NM": str(target_row.get("WRT_EMP_NM") or ""),
            "ACTG_DT": str(target_row.get("ACTG_DT") or ""),
            "DETAIL_SUM_AMT": str(target_row.get("DETAIL_SUM_AMT") or ""),
            "DOCU_NO": str(target_row.get("DOCU_NO") or ""),
        }
        print(f"[검증] 대상 마스터: {result['master']}", flush=True)

        # ── 3중 가드 — 조회 결과 전체가 우리 것인지(다른 전표 오염 없는지) 먼저 확인 ──────
        all_ours = all(row_is_ours(r, FG_CODE) for r in rows)
        result["all_ours"] = all_ours
        target_ours = row_is_ours(target_row, FG_CODE)
        result["target_ours"] = target_ours
        print(f"[검증] 가드레일 — all_ours={all_ours} target_ours={target_ours}", flush=True)
        if not (all_ours and target_ours):
            result["error"] = "가드레일 불일치 — 삭제 중단(전표 보호)"
            print(f"[검증][ABORT] {result['error']} — 전표번호 목록: {result['all_docnos']}", flush=True)
            _dump(result)
            return

        # ── detail 전량 raw 읽기(FEOTH_ACCT/FUND_CD 등 진단 필드 포함) ──────────────────
        # 조회(F2) 직후 ERP 는 첫 행을 자동 선택해 상세를 렌더해 둔다 — target 이 그 유일한
        # 행(before==1)이면 GridProvider 직접 읽기가 가장 빠르고 안전(product_cycle.collect_detail
        # 과 동일 원리, DETAIL_FIELDS 필터링 없이 raw 그대로).
        detail_rows: list[dict] = []
        if before == 1 and target_idx == 0:
            gp = GridProvider(page, 1)
            if await gp.get_row_count() > 0:
                detail_rows = await gp.get_all_rows()
        if not detail_rows:
            result["error"] = f"detail 읽기 실패(before={before}, target_idx={target_idx}) — 삭제 보류"
            print(f"[검증][FATAL] {result['error']}", flush=True)
            await page.screenshot(path=str(ART / f"{TAG}_detail_read_fail.png"))
            _dump(result)
            return

        result["detail_n"] = len(detail_rows)
        result["detail_rows_full"] = detail_rows
        result["detail_rows_focus"] = [_focus(r) for r in detail_rows]
        print(f"[검증] detail {len(detail_rows)}행:", flush=True)
        for i, r in enumerate(detail_rows):
            print(f"  [행{i}] {_focus(r)}", flush=True)
        await page.screenshot(path=str(ART / f"{TAG}_detail_view.png"))
        _dump(result)

        # ── 구조 검증(team-lead 기대치 대조) ────────────────────────────────────────
        checks: dict = {}
        checks["rowcount_3"] = len(detail_rows) == 3
        orig = next((r for r in detail_rows if str(r.get("EVDN_CD") or "") == "11"), None)
        splits = [r for r in detail_rows if str(r.get("EVDN_CD") or "") == "12"]
        checks["orig_found"] = orig is not None
        checks["split_count_2"] = len(splits) == 2
        if orig:
            checks["orig_supply_84000"] = str(orig.get("SPPRC_AMT2") or "").replace(",", "") == "84000"
            checks["orig_tax_8400"] = str(orig.get("TAXAMT_AMT") or "").replace(",", "") == "8400"
            checks["orig_fund_cd"] = str(orig.get("FUND_CD") or "").strip()
            checks["orig_feoth_acct_cd"] = str(orig.get("FEOTH_ACCT_CD") or "").strip()
        for i, s in enumerate(splits):
            checks[f"split{i}_supply_42000"] = str(s.get("SPPRC_AMT2") or "").replace(",", "") == "42000"
            checks[f"split{i}_tax_0"] = str(s.get("TAXAMT_AMT") or "0").replace(",", "") in ("0", "")
            checks[f"split{i}_fund_cd"] = str(s.get("FUND_CD") or "").strip()
            checks[f"split{i}_feoth_acct_cd"] = str(s.get("FEOTH_ACCT_CD") or "").strip()
        result["structure_checks"] = checks
        print(f"[검증] 구조 검증: {json.dumps(checks, ensure_ascii=False)}", flush=True)
        _dump(result)

        # ── F6 삭제 ──────────────────────────────────────────────────────────────
        print("[검증] F6 삭제 진행…", flush=True)
        await page.evaluate(SELECT_MASTER_JS, 0)
        modals = await delete_selected(page)
        result["delete_modals"] = modals
        if modals:
            print(f"[검증] 삭제 모달: {json.dumps(modals[:3], ensure_ascii=False)}", flush=True)
        await page.wait_for_timeout(1_000)
        after = await query_master(page)
        result["after_count"] = after
        result["deleted"] = after == 0
        await page.screenshot(path=str(ART / f"{TAG}_after.png"))
        if after != 0:
            result["error"] = f"삭제 후 잔존 {after}건 — 수동 정리 필요(전표번호 확인 필요)"
            print(f"[검증][FAILURE] {result['error']}", flush=True)
        else:
            print(f"[검증] F6 삭제 완료 — 재조회 잔존 {after}건 ✅", flush=True)
        _dump(result)
    except Exception as exc:  # noqa: BLE001
        result["exception"] = f"{exc!r}"
        print(f"[검증][ERROR] {result['exception']}", flush=True)
        try:
            await page.screenshot(path=str(ART / f"{TAG}_exception.png"))
        except Exception:  # noqa: BLE001
            pass
        _dump(result)
    finally:
        await browser.close()
        await pw.stop()


def _dump(result: dict) -> None:
    path = ART / f"{TAG}_results.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
