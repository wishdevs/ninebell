"""행별 예산단위·프로젝트 프리셀렉트 — 학습(결정적) > AI > 전사 seed > 기본지정."""

from __future__ import annotations

import logging

from typing import Any

from app.agents.common.llm import llm_ready
from app.core.http_client import new_async_client
from app.live.events import emit_log
from app.services import card_learning

from ..merchant_dict import load_rules, match_in
from .. import grouping, meal_time
from ..recommend import (
    RECOMMEND_CHUNK_SIZE,
    RECOMMEND_CONFIDENCE_THRESHOLD,
    recommend_selections,
)
from . import _shared, catalog

logger = logging.getLogger(__name__)

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
    user_job_title: str | None = None,
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

    # 가맹점 분류 사전(하이브리드) — learned/seed 이력이 없는 가맹점을 카드 표기명 키워드로 인식.
    #  · dict_budget_by_no: strong 규칙(주유소·해외 OTA 등)이 계정으로 해석되면 결정적 폴백 후보.
    #  · dict_hint_by_no: 모든 매칭의 유형 문구 — AI 프롬프트에 힌트로 주입(애매한 카페·택시 등).
    # seed 이력이 있으면(그게 더 구체적) 사전은 건너뛴다.
    dict_rules = await load_rules()  # DB 사전(캐시) 1회 로드 → 행별 in-memory 매칭.
    dict_budget_by_no: dict[int, dict] = {}
    dict_hint_by_no: dict[int, str] = {}
    for idx, r in enumerate(rows_list):
        no = idx + 1
        if no in seed_budget_by_no:
            continue
        rule = match_in(r.get("TRAN_NM"), dict_rules)
        if not rule:
            continue
        dict_hint_by_no[no] = rule.category
        if rule.strong and rule.acct:
            db = catalog._resolve_seed_budget(rule.acct, budget_candidates)
            if db:
                dict_budget_by_no[no] = db

    # ── 그룹 판단 계획(2026-07-31 사용자 확정) ────────────────────────────────
    # 판단 단위는 행이 아니라 (가맹점×시간슬롯) 그룹이다 — 같은 그룹의 반복 결제는 분류가 같다.
    #  · learned 결정적 행(budget·project 모두 확보)은 최종 선택에서 AI 를 이기므로 AI 제외.
    #  · 남은 행은 그룹 대표 1행만 AI 로 보내고 결과를 그룹 전원에 전파한다.
    #  · 금액 이탈 행(회식/접대 가능성)은 전파·learned 를 우회해 개별 AI 판단.
    #  · 승인취소 행은 원거래 최종 선택을 미러링한다(아래 후처리).
    learned_det_idx = frozenset(
        no - 1
        for no, hit in learned_by_no.items()
        if (hit.get("count") or 0) >= card_learning.LEARNED_APPLY_MIN_COUNT
        and (hit.get("budget") or {}).get("code")
        and (hit.get("project") or {}).get("code")
    )
    plan = grouping.plan_groups(rows_list, skip_ai=learned_det_idx)

    recommendations: dict[int, dict] = {}
    if llm_ready(settings) and (budget_candidates or project_candidates):
        rec_rows = [
            {
                "no": idx + 1,
                "merchant": r.get("TRAN_NM") or "",
                "amount": _shared._fmt_won(r.get("TRAN_AMT")),
                "vatType": r.get("VAT_TP") or "",
                # ⚠ 거래일시(2026-07-27 사용자 리포트): 18:33 결제가 '복리후생비-**중식**'으로
                #   추천된 사고 — 그리드에서 TRAN_DT/TRAN_TM 을 읽어두고도 AI 에 보내지 않아
                #   시간대를 알 수 없었다. 식대 계정은 중식/석식/야식으로 나뉘므로 필수 근거다.
                "date": r.get("TRAN_DT") or "",
                "time": r.get("TRAN_TM") or "",
                "note": recs[r.get("i", idx)],
            }
            for idx, r in ((i, rows_list[i]) for i in plan.ai_rows)
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
            elif rr["no"] in dict_budget_by_no:
                # learned/seed 없음 + 사전 strong 매칭(주유소 등) → 사전 해석 예산단위를 AI 힌트로.
                db = dict_budget_by_no[rr["no"]]
                rr["priorChoice"] = {
                    "budgetUnitCode": db.get("code") or "",
                    "budgetUnitName": db.get("name") or "",
                    "bgacctNm": db.get("bgacctNm") or "",
                    "projectCode": "",
                    "projectName": "",
                    "count": 1,
                }
            # 가맹점 유형 힌트(사전 매칭) — 계정 확정과 별개로 AI 판단 근거로 주입(카페·택시 등).
            if rr["no"] in dict_hint_by_no:
                rr["merchantHint"] = dict_hint_by_no[rr["no"]]
        # 그룹 계획 요약 — 왜 전 행이 AI 로 가지 않는지가 로그로 보여야 '누락'과 구분된다.
        if len(rec_rows) < len(rows_list):
            n_outlier = len(plan.outliers)
            await emit_log(
                events,
                f"그룹 판단: {len(rows_list)}행 → AI {len(rec_rows)}행"
                f"(그룹 대표 {len(rec_rows) - n_outlier}·금액 이탈 {n_outlier})"
                f" · 그룹 전파 {len(plan.propagate)}행 · 학습 확정 {len(learned_det_idx)}행"
                f" · 취소 미러 {len(plan.mirrors)}행",
                "info",
            )
        # 청크 수를 미리 노출한다 — 400행이 한 번에 안 가고 나뉘어 간다는 것이 로그로 보여야
        # '왜 오래 걸리는지 / 일부만 추천됐는지'를 판단할 수 있다.
        n_chunks = max(1, -(-len(rec_rows) // RECOMMEND_CHUNK_SIZE))
        await emit_log(
            events,
            f"AI 추천을 계산하는 중입니다… ({len(rec_rows)}행"
            + (f" → {n_chunks}청크" if n_chunks > 1 else "") + ")",
            "info",
        )
        http = new_async_client(timeout=60.0)
        try:
            recommendations = await recommend_selections(
                rec_rows,
                budget_candidates,
                project_candidates,
                http=http,
                settings=settings,
                cost_prefix=cost_prefix,  # 판/제 반대 버킷 후보를 LLM 컨텍스트에서 제외(토큰 절감).
                user_job_title=user_job_title,  # 직급 제외 계정(팀원→접대비·회식비) 필터.
            )
        finally:
            await http.aclose()
        if not recommendations:
            await emit_log(events, "AI 추천을 받지 못해 기본지정으로 프리필합니다.", "warn")
        elif len(recommendations) < len(rec_rows):
            # 일부 청크만 성공한 경우 — 나머지는 기본지정으로 채워진다(전량 실패와 구분).
            await emit_log(
                events,
                f"AI 추천 {len(recommendations)}/{len(rec_rows)}행 수신 — 나머지는 기본지정으로 프리필합니다.",
                "warn",
            )
        # 그룹 전파 — 대표 행의 추천을 같은 그룹 나머지 행에 복사한다(수신 검증·경고 이후에
        # 해야 위 수신율 로그가 실제 AI 응답 기준으로 남는다). confidence 도 함께 복사되므로
        # 임계값 게이트는 행별로 동일하게 적용된다.
        for member, rep in plan.propagate.items():
            rep_rec = recommendations.get(rep + 1)
            if rep_rec and (member + 1) not in recommendations:
                recommendations[member + 1] = rep_rec

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
    meal_fixes: list[tuple[int, str]] = []  # 시간대 교정 내역(로그 요약용)
    for idx in range(len(rows_list)):
        no = idx + 1
        rec = recommendations.get(no) or {}
        hi = rec.get("confidence", 0.0) >= RECOMMEND_CONFIDENCE_THRESHOLD
        # Tier 1 — 결정적 적용: 반복 확정(count>=MIN)한 가맹점은 그 선택을 그대로.
        # 단, 금액 이탈 행(그룹 금액대 초과 — 회식/접대 가능성)은 learned 를 우회해 개별 AI
        # 판단을 쓴다: 반복 확정은 평소 금액대의 근거일 뿐, 이탈 결제의 근거가 아니다.
        lh = learned_by_no.get(no) or {}
        learned_ok = (
            (lh.get("count") or 0) >= card_learning.LEARNED_APPLY_MIN_COUNT
            and (no - 1) not in plan.outliers
        )

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
            elif no in dict_budget_by_no:
                # 사전 strong 해석(주유소 등) — seed 없을 때 blind 기본값보다 나은 폴백.
                budget, budget_source = dict_budget_by_no[no], "dict"
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

        # ── 식대 시간대 교정(최종) ────────────────────────────────────────────
        # ⚠ learned 를 포함해 **모든 경로**에 적용한다 — learned 가 AI 를 우회하므로, 여기서
        #   보정하지 않으면 한 번 굳은 '석식'이 11시 결제에도 계속 붙는다(2026-07-27 감사 46건).
        #   사용자 확정은 존중하되 '시각과 모순되는 슬롯'만 형제 계정으로 바꾼다(성격 계정은 무시).
        if budget:
            fixed, why = meal_time.correct_budget(
                budget, rows_list[idx].get("TRAN_TM"), budget_candidates
            )
            if fixed:
                budget = catalog._pick_budget(fixed)
                meal_fixes.append((no, why))
                budget_source = f"{budget_source or '?'}+시간대"
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
    # ── 승인취소 미러링(후처리) ──────────────────────────────────────────────
    # 취소 행은 원거래와 같은 분류여야 전표가 상계된다 — 원거래의 **최종** 선택(판/제 강제·
    # 시간대 교정까지 끝난 값)을 그대로 복사한다. 원거래를 못 찾았거나 원거래가 비어 있으면
    # 일반 파이프라인 결과를 그대로 둔다(임의 추측 금지).
    for c_idx, o_idx in plan.mirrors.items():
        src = out.get(o_idx + 1)
        if not src or not src.get("budgetUnit"):
            continue
        out[c_idx + 1] = {
            # 방어적 복사 — 원거래와 dict 를 공유하면 이후 in-place 수정 시 서로 오염된다.
            "budgetUnit": dict(src["budgetUnit"]),
            "project": dict(src["project"]) if src.get("project") else None,
            "budgetSource": "mirror",
            "projectSource": "mirror" if src.get("project") else None,
            "vatDeduction": src.get("vatDeduction"),
        }
    if plan.mirrors:
        logger.info("승인취소 미러 %d건 — 원거래 분류 복사", len(plan.mirrors))
    if meal_fixes:
        # 무엇이 왜 바뀌었는지 한 줄로 — 조용히 바꾸면 사용자가 신뢰할 수 없다.
        sample = ", ".join(f"{no}행 {why}" for no, why in meal_fixes[:5])
        more = f" 외 {len(meal_fixes) - 5}건" if len(meal_fixes) > 5 else ""
        logger.info("식대 시간대 교정 %d건 — %s%s", len(meal_fixes), sample, more)
    return out
