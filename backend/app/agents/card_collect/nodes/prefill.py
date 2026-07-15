"""행별 예산단위·프로젝트 프리셀렉트 — 학습(결정적) > AI > 전사 seed > 기본지정."""

from __future__ import annotations

from typing import Any

import httpx

from app.live.events import emit_log
from app.services import card_learning

from ..recommend import RECOMMEND_CONFIDENCE_THRESHOLD, recommend_selections
from . import _shared, catalog

# 비용구분 접두사 → 프로젝트 판/제 버킷(PJT_NO). 제조원가=500 / 판관비=800.
_PREFIX_PROJECT_NO = {"(제)": "500", "(판)": "800"}


def _enforce_budget_prefix(budget: dict, cost_prefix: str | None, candidates: list[dict]) -> dict:
    """부서 비용구분(판/제)과 다른 계정이면 같은 계정명의 부서 판/제 형제로 교정.

    예: 판관 사용자에게 '(제)복리후생비-석식'(제조)이 잡히면 후보에서 '(판)복리후생비-석식'을 찾아
    바꾼다(가맹점 이력이 제조여도 부서가 판관이면 판관 계정으로). 접두사 없음·이미 일치·형제 후보
    없음이면 원본 유지 — 무리하게 바꾸지 않는다.
    """
    if not cost_prefix:
        return budget
    nm = budget.get("bgacctNm") or ""
    if nm.startswith(cost_prefix):
        return budget  # 이미 부서 판/제와 일치.
    key = catalog._acct_norm(nm)
    if not key:
        return budget
    sib = next(
        (
            c
            for c in candidates
            if (c.get("bgacctNm") or "").startswith(cost_prefix)
            and catalog._acct_norm(c.get("bgacctNm")) == key
        ),
        None,
    )
    return catalog._pick_budget(sib) if sib else budget


def _enforce_project_cost(
    project: dict, cost_prefix: str | None, cost_project: dict | None
) -> dict:
    """부서와 다른 판/제 버킷 프로젝트(제조원가 500 / 판관비 800)면 부서 프로젝트로 교정.

    버킷(500/800)이 아닌 특정 프로젝트는 부서 무관이라 건드리지 않는다. 부서 프로젝트 미상이면 원본.
    """
    if not cost_prefix or not cost_project:
        return project
    want = _PREFIX_PROJECT_NO.get(cost_prefix)
    if not want:
        return project
    pjt_no = str(project.get("code") or "").split("|")[0]
    if pjt_no in ("500", "800") and pjt_no != want:
        return catalog._pick_project(cost_project)
    return project


async def _prefill_selections(
    events: Any,
    settings: Any,
    rows_list: list[dict],
    recs: dict[int, str],
    budget_favs: list[dict],
    mine_units: list[dict],
    project_favs: list[dict],
    cost_prefix: str | None = None,
    cost_project: dict | None = None,
    learned: dict | None = None,
    seed: dict | None = None,
) -> dict[int, dict]:
    """행별 예산단위·프로젝트 프리셀렉트 — 예산단위 단: 학습(결정적) > AI > 전사seed > 기본지정.

    반환 {no: {budgetUnit, project, budgetSource, projectSource}} — 각 값은 없으면 None.
    learned={norm_merchant: {budget, project, note, count}} — 과거 개입 확정분. 같은 가맹점을
    LEARNED_APPLY_MIN_COUNT 회 이상 확정했으면 AI 없이 그 선택을 그대로 프리필(source='learned').
    seed={norm_merchant: {acct_name, note, count, dominance}} — 전사 기초자료. 계정→예산단위로
    해석해 AI 힌트(priorChoice) + 일반 기본보다 나은 폴백(source='seed')으로만 쓴다(결정적 아님 —
    키워드 매칭·비개인 데이터라 AI 가 맥락으로 판단). 예산단위·프로젝트는 서로 독립 결정.
    """
    learned = learned or {}
    # 학습 힌트를 recommend 프롬프트에 실어(Tier 2) — 결정적 적용에 못 미치는 가맹점도 AI 가
    # 과거 선택을 우선하도록 유도한다. {no: {budgetName, bgacctNm, projectName}}.
    learned_by_no: dict[int, dict] = {}
    for idx, r in enumerate(rows_list):
        hit = learned.get(card_learning.norm_merchant(r.get("TRAN_NM")))
        if hit:
            learned_by_no[idx + 1] = hit
    # AI 후보 — 예산단위(자주쓰는 + 내 부서, code 중복 제거) / 프로젝트(자주쓰는).
    budget_candidates: list[dict] = []
    seen: set[str] = set()
    for c in [*budget_favs, *mine_units]:
        code = c.get("code")
        if code and code not in seen:
            seen.add(code)
            budget_candidates.append(c)
    project_candidates = list(project_favs)

    # 전사 seed → 계정(acct_name)을 예산단위 후보의 bgacctNm 과 매칭해 해석(결정 1.a). 개인 학습이
    # 없는 행에 대해 AI 힌트·개선된 폴백으로 쓴다(결정적 아님). {no: 예산단위(_pick_budget 형태)}.
    seed = seed or {}
    seed_budget_by_no: dict[int, dict] = {}
    for idx, r in enumerate(rows_list):
        sh = seed.get(card_learning.norm_merchant(r.get("TRAN_NM")))
        if sh:
            sb = catalog._resolve_seed_budget(sh.get("acct_name"), budget_candidates)
            if sb:
                seed_budget_by_no[idx + 1] = sb

    recommendations: dict[int, dict] = {}
    if settings.gemini_api_key and (budget_candidates or project_candidates):
        rec_rows = [
            {
                "no": idx + 1,
                "merchant": r.get("TRAN_NM") or "",
                "amount": _shared._fmt_won(r.get("TRAN_AMT")),
                "vatType": r.get("VAT_TP") or "",
                "note": recs[r.get("i", idx)],
            }
            for idx, r in enumerate(rows_list)
        ]
        # 학습 힌트를 각 행에 부착(AI 가 과거 선택을 우선하도록).
        for rr in rec_rows:
            hit = learned_by_no.get(rr["no"])
            if hit:
                bu = hit.get("budget") or {}
                pj = hit.get("project") or {}
                rr["priorChoice"] = {
                    "budgetUnitCode": bu.get("code") or "",
                    "budgetUnitName": bu.get("name") or "",
                    "bgacctNm": bu.get("bgacctNm") or "",
                    "projectCode": pj.get("code") or "",
                    "projectName": pj.get("name") or "",
                    "count": hit.get("count") or 1,
                }
            elif rr["no"] in seed_budget_by_no:
                # 개인 학습 없음 → 전사 seed 로 해석한 예산단위를 AI 힌트로(전사 관례 우선 유도).
                sb = seed_budget_by_no[rr["no"]]
                rr["priorChoice"] = {
                    "budgetUnitCode": sb.get("code") or "",
                    "budgetUnitName": sb.get("name") or "",
                    "bgacctNm": sb.get("bgacctNm") or "",
                    "projectCode": "",
                    "projectName": "",
                    "count": 1,
                }
        await emit_log(events, "AI 추천을 계산하는 중입니다…", "info")
        http = httpx.AsyncClient(timeout=60.0)
        try:
            recommendations = await recommend_selections(
                rec_rows, budget_candidates, project_candidates, http=http, settings=settings
            )
        finally:
            await http.aclose()
        if not recommendations:
            await emit_log(events, "AI 추천을 받지 못해 기본지정으로 프리필합니다.", "warn")

    budget_by_code = {c["code"]: c for c in budget_candidates}
    project_by_code = {c["code"]: c for c in project_candidates}

    # 기본 예산단위 폴백: 기본지정(isDefault) 우선, 단 비용구분 접두사가 있으면 접두사 일치를
    # 더 우선한다(기본지정 없음 + 접두사 일치 후보가 있으면 그것으로 폴백).
    def _prefix_ok(c: dict) -> bool:
        return bool(cost_prefix) and (c.get("bgacctNm") or "").startswith(cost_prefix)

    default_budget = (
        next((c for c in budget_favs if c.get("isDefault") and _prefix_ok(c)), None)
        or next((c for c in budget_favs if c.get("isDefault")), None)
        or (next((c for c in budget_candidates if _prefix_ok(c)), None) if cost_prefix else None)
    )
    # 프로젝트 기본: 기본지정 즐겨찾기(명시 설정) 우선, 없으면 팀 비용구분 프로젝트
    # (제조원가→500 / 판관비→800, 사용자 확정 2026-07-04).
    default_project = next((c for c in project_favs if c.get("isDefault")), None) or cost_project

    out: dict[int, dict] = {}
    for idx in range(len(rows_list)):
        no = idx + 1
        rec = recommendations.get(no) or {}
        hi = rec.get("confidence", 0.0) >= RECOMMEND_CONFIDENCE_THRESHOLD
        # Tier 1 — 결정적 적용: 반복 확정(count>=MIN)한 가맹점은 그 선택을 그대로.
        lh = learned_by_no.get(no) or {}
        learned_ok = (lh.get("count") or 0) >= card_learning.LEARNED_APPLY_MIN_COUNT

        learned_budget = lh.get("budget") if learned_ok else None
        if learned_budget and learned_budget.get("code"):
            budget, budget_source = catalog._pick_budget(learned_budget), "learned"
        else:
            ai_budget = budget_by_code.get(rec.get("budgetUnitCode", "")) if hi else None
            if ai_budget:
                budget, budget_source = catalog._pick_budget(ai_budget), "ai"
            elif no in seed_budget_by_no:
                # 전사 seed 해석 예산단위 — 일반 기본보다 나은 폴백(계정 기반 실제 관례).
                budget, budget_source = seed_budget_by_no[no], "seed"
            elif default_budget:
                budget, budget_source = catalog._pick_budget(default_budget), "default"
            else:
                budget, budget_source = None, None

        learned_project = lh.get("project") if learned_ok else None
        if learned_project and learned_project.get("code"):
            project, project_source = catalog._pick_project(learned_project), "learned"
        else:
            ai_project = project_by_code.get(rec.get("projectCode", "")) if hi else None
            if ai_project:
                project, project_source = catalog._pick_project(ai_project), "ai"
            elif default_project:
                project, project_source = catalog._pick_project(default_project), "default"
            else:
                project, project_source = None, None

        # 부서 비용구분(판/제) 강제 — AI/seed/기본 자동 픽이 부서와 다른 판/제를 고르면 교정한다.
        # (학습=사용자 확정은 존중해 건드리지 않는다.) 가맹점 이력이 제조여도 로그인 부서가 판관이면
        # 판관 계정·프로젝트로 맞춘다. 예산: 같은 계정명의 부서 판/제 형제로, 프로젝트: 부서 프로젝트로.
        if budget and budget_source != "learned":
            budget = _enforce_budget_prefix(budget, cost_prefix, budget_candidates)
        if project and project_source != "learned":
            project = _enforce_project_cost(project, cost_prefix, cost_project)

        out[no] = {
            "budgetUnit": budget,
            "project": project,
            "budgetSource": budget_source,
            "projectSource": project_source,
            # 가맹점 기반 부가세구분(AI) — collect 가 계정/VAT_TP 와 함께 classify_vat 로 최종 결정.
            "vatDeduction": rec.get("vatDeduction"),
        }
    return out
