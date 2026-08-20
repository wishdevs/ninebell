"""세금계산서 실저장 사이클 스모크(스켈레톤) — 그래프 직접 ainvoke → ERP 독립검증 → F6 삭제.

⚠⚠ 이 스크립트는 **실저장(F7)** 을 실행한다 — 사용자 지시 없이 돌리지 말 것(작성 시점
2026-08-19 미실행). 시나리오 2종을 사이클로 돈다:
  - PRE22: 발행 전 과세(증빙 22) — 쓰기 프로브 Case A 조합(RN202608190004 PASS 재현).
  - SPLIT11: 발행 후 원증빙(11) + 비용분할 2행(마지막 행 차액반영) — Case B 조합
    (RN202608190006 PASS 재현, 분할행 상대계정 포함).
발행 후(03/04 — 계산서 행 선택 HITL) 시나리오는 이 환경에 전자발행 데이터가 0건이라 돌릴 수
없다(PROCESS.md D5 리스크) — 실데이터 환경에서 사용자 감독 1회 검증으로 대체한다.

한 사이클 = 그래프 실행(F7 실저장) → `e2e.product_cycle.erp_verify_and_delete`(별도 세션
독립 재조회 + 3중 가드 + F6 삭제 + 잔존 0 확인). 삭제 가드레일: 결의자=로그인계정 +
결의구분(ABDOCU_FG_CD)=51 + 미결(DOCU_NO 공백) — **완화 금지**. 상신(결재) 절대 금지.

Usage: cd backend && TAX_INVOICE_SMOKE_CYCLES=1 .venv/bin/python e2e/tax_invoice_smoke_cycle.py
env:
  TAX_INVOICE_SMOKE_CYCLES  사이클 수(기본 1 — 무결 확정은 10)
  TAX_INVOICE_SCENARIOS     "PRE22,SPLIT11"(기본 둘 다) 중 콤마 구분 선택
  TAX_INVOICE_BUDGET        예산단위 정확명(BG_NM, 기본 "임원실" — 쓰기 프로브 '일반' 검색 결과)
  TAX_INVOICE_CC            분할 비용센터 검색어(기본 "임원실" — ⚠ 첫 실행 전 실카탈로그 확인)
  E2E_USERID/E2E_PASSWORD   (기본 이트라이브2/1111) · E2E_HEADLESS(기본 1) · E2E_DELAY_SCALE(기본 0.4)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.tax_invoice.graph import (  # noqa: E402
    TAX_INVOICE_FG_CODE,
    TAX_INVOICE_GUBUN_LABEL,
    build_tax_invoice_graph,
)
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from e2e.product_cycle import erp_verify_and_delete  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
CYCLES = int(os.environ.get("TAX_INVOICE_SMOKE_CYCLES", "1"))
SCENARIOS = [s.strip().upper() for s in os.environ.get("TAX_INVOICE_SCENARIOS", "PRE22,SPLIT11").split(",") if s.strip()]
BUDGET_NAME = os.environ.get("TAX_INVOICE_BUDGET", "임원실")
COST_CENTER = os.environ.get("TAX_INVOICE_CC", "임원실")
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

PARTNER_NAME = "코웨이(주)"  # 실측: ERP 정확 등록명 "(주)" 포함(PROCESS.md 검증 로그).
PROJECT_WBS = "800"
TODAY = date.today().isoformat()

# 사이클별 금액(라운드 숫자 회피 — 테스트 데이터 티 나게, 형제 스모크 관례).
_PRE_AMOUNTS = [37_001, 41_003, 55_007, 23_009, 67_011, 31_013, 45_017, 29_019, 53_021, 39_023]
_SPLIT_AMOUNTS = [84_002, 96_004, 72_006, 88_008, 64_010, 92_012, 76_014, 80_016, 68_018, 90_020]


def _pre22_params(cycle: int) -> dict:
    return {
        "tax_invoice": {
            "issue": "pre",
            "tax": "taxable",
            "nondeduct_reason": None,
            "split": False,
            "partner_name": PARTNER_NAME,
            "supply_amount": _PRE_AMOUNTS[(cycle - 1) % len(_PRE_AMOUNTS)],
            "budget_unit_name": BUDGET_NAME,
            "project_wbs": PROJECT_WBS,
            "note": f"옴니솔스모크A-{cycle}",
            "actg_date": TODAY,
        }
    }


def _split11_params(cycle: int) -> dict:
    supply = _SPLIT_AMOUNTS[(cycle - 1) % len(_SPLIT_AMOUNTS)]
    return {
        "tax_invoice": {
            "issue": "post",
            "tax": "taxable",
            "nondeduct_reason": None,
            "split": True,
            "partner_name": PARTNER_NAME,
            "supply_amount": supply,
            "budget_unit_name": BUDGET_NAME,
            "project_wbs": PROJECT_WBS,
            "note": f"옴니솔스모크B-{cycle}",
            # 마지막 행 amount=None = 차액반영으로 잔액 흡수(D7 확정 레시피).
            "split_rows": [
                {"note": f"스모크분할1-{cycle}", "amount": supply // 2, "cost_center": COST_CENTER, "project_wbs": PROJECT_WBS},
                {"note": f"스모크분할2-{cycle}", "amount": None, "cost_center": COST_CENTER, "project_wbs": PROJECT_WBS},
            ],
        }
    }


_SCENARIO_BUILDERS = {"PRE22": _pre22_params, "SPLIT11": _split11_params}
# 검증 기대치: 메인 detail 행수(원본 1 + 분할행 N — D7 영속 구조).
_EXPECT_DETAIL_ROWS = {"PRE22": 1, "SPLIT11": 3}


async def _drain_events(q: asyncio.Queue, tag: str = "run") -> None:
    """그래프 진행 이벤트를 콘솔로 흘린다(step/log/screenshot/hitl — 러너 대체 최소 소비자).

    ⚠ screenshot 프레임(nbkit.patterns.emit_shot 이 보내는 {screenshot: dataURL})은 그동안
    조용히 버려지고 있었다(team-lead 지시로 진단강화, 2026-08-19) — 실패 직전 화면을 파일로
    남겨야 SPLIT11 류 실패의 잔존 팝업 정체를 시각적으로 확인할 수 있다.
    """
    shot_n = 0
    while True:
        frame = await q.get()
        if not isinstance(frame, dict):
            continue
        if "step" in frame:
            s = frame["step"]
            print(f"[step] {s.get('key')} {s.get('status')}", flush=True)
        elif "log" in frame:
            l = frame["log"]
            print(f"[log:{l.get('level')}] {l.get('message')}", flush=True)
        elif "hitl" in frame:
            # PRE22/SPLIT11 은 HITL 이 없어야 한다 — 뜨면 설계 위반(즉시 눈에 띄게).
            print(f"[HITL?!] {json.dumps(frame['hitl'], ensure_ascii=False)[:200]}", flush=True)
        elif "screenshot" in frame:
            shot_n += 1
            data_url = frame["screenshot"] or ""
            if "," in data_url:
                shot_n_path = ARTIFACTS / f"{tag}_shot{shot_n}.png"
                try:
                    shot_n_path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
                    print(f"[shot] {shot_n_path}", flush=True)
                except Exception as exc:  # noqa: BLE001 — 스크린샷 저장 실패가 사이클을 막으면 안 된다.
                    print(f"[shot] 저장 실패: {exc!r}", flush=True)


async def _run_graph(params: dict, tag: str) -> dict:
    """그래프 1회 실행(phase1 — F7 실저장까지). 반환 {ok, result|error}."""
    graph = build_tax_invoice_graph()
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    events: asyncio.Queue = asyncio.Queue()
    drain = asyncio.create_task(_drain_events(events, tag))
    try:
        state = {
            "page": page,
            "browser": browser,
            "events": events,
            "userid": USERID,
            "password": PASSWORD,
            "params": params,
            "owner": None,
            "run_id": None,
        }
        out = await graph.ainvoke(state)
        if out.get("error"):
            return {"ok": False, "error": out["error"]}
        return {"ok": True, "result": out.get("result")}
    except Exception as exc:  # noqa: BLE001 — 사이클 단위로 실패를 보고하고 다음으로.
        try:
            await raw_page.screenshot(path=str(ARTIFACTS / f"tax_invoice_smoke_{tag}_exception.png"))
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"graph exception: {exc!r}"}
    finally:
        drain.cancel()
        await browser.close()
        await pw.stop()


async def _one_cycle(scenario: str, cycle: int) -> dict:
    tag = f"tax_invoice_smoke_{scenario}_c{cycle}"
    params = _SCENARIO_BUILDERS[scenario](cycle)
    print(f"\n===== [{scenario}] cycle {cycle}/{CYCLES} — phase1 그래프 실행(F7 실저장) =====", flush=True)
    run = await _run_graph(params, tag)
    out: dict = {"scenario": scenario, "cycle": cycle, "run": run}
    print(f"[{scenario}][c{cycle}] phase1 → {run}", flush=True)
    if not run.get("ok"):
        return {**out, "ok": False}

    print(f"===== [{scenario}] cycle {cycle} — phase2 독립검증 + F6 삭제 + 잔존 0 =====", flush=True)
    vd = await erp_verify_and_delete(
        gubun_label=TAX_INVOICE_GUBUN_LABEL,
        fg_code=TAX_INVOICE_FG_CODE,
        tag=tag,
        pick_master=lambda rows: len(rows) - 1,
        want_detail=True,
    )
    out["verify_delete"] = vd
    detail_n = (vd.get("detail") or {}).get("n")
    expected_n = _EXPECT_DETAIL_ROWS[scenario]
    detail_ok = detail_n == expected_n
    out["detail_rows_ok"] = detail_ok
    out["ok"] = bool(vd.get("deleted")) and vd.get("after") == 0 and not vd.get("error") and detail_ok
    print(
        f"[{scenario}][c{cycle}] phase2 → before={vd.get('before')} detail={detail_n}"
        f"(기대 {expected_n}) deleted={vd.get('deleted')} after={vd.get('after')} error={vd.get('error')}",
        flush=True,
    )
    return out


async def main() -> None:
    for s in SCENARIOS:
        if s not in _SCENARIO_BUILDERS:
            raise SystemExit(f"알 수 없는 시나리오: {s} (PRE22/SPLIT11)")
    results: list[dict] = []
    aborted = False
    for cycle in range(1, CYCLES + 1):
        for scenario in SCENARIOS:
            r = await _one_cycle(scenario, cycle)
            results.append(r)
            # 안전 게이트(형제 관례): 사이클 실패(저장/검증/삭제/행수) 시 즉시 중단 —
            # 실패 원인을 안고 반복하면 잔존 전표가 쌓인다.
            if not r.get("ok"):
                print(f"\n[ABORT] {scenario} cycle {cycle} 실패 — 나머지 사이클 중단.", flush=True)
                aborted = True
                break
        if aborted:
            break
    path = ARTIFACTS / "tax_invoice_smoke_cycle_results.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ok_n = sum(1 for r in results if r.get("ok"))
    print(f"\n===== SMOKE COMPLETE — {ok_n}/{len(results)} PASS (결과: {path}) =====", flush=True)
    if ok_n != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
