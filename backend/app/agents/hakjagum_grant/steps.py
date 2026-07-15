"""학자금신청서 결의서입력 — detail 그리드 채움 스텝(대부분 trip_domestic 재사용).

경조금(gyeongjo_grant) 형제 클론 — detail 그리드가 국내출장/경조금과 동형(동일 GLDDOC00300 스키마,
2026-07-15 라이브 프로브에서 84필드·SPPRC_AMT2·START_DT 확인)이라 거래처(본인 검색)·프로젝트·금액
타이핑·적요·계산서일·상대계정(본인)·빈행삭제·마스터합계 스텝을 **국내출장에서 그대로 import** 한다.
학자금 고유 델타는 **예산계정 base('복리후생비-기타')·검색어('복리후생비')** 뿐이라 예산단위 스텝
(bgacct_name_for_cost_type·fill_budget_fixed)만 재정의한다. 매칭 함수(pick_budget_row)와 피커 공용 헬퍼(_open_detail_cell_picker·
_fail_close·_select_and_apply)도 국내출장 것을 재사용한다.
"""

from __future__ import annotations

from typing import Any

from nbkit.omnisol import js_lib
from nbkit.omnisol.codepicker import _picker_search

from app.agents.trip_domestic import steps as trip_steps

# 국내출장에서 그대로 재사용하는 스텝(학자금 델타 없음) — fill 노드가 `steps.<name>` 으로 참조.
from app.agents.trip_domestic.steps import (  # noqa: F401
    BUDGET_CELL,
    BUDGET_FIELDS,
    _COST_PREFIX,
    delete_blank_row,
    fill_partner_by_search,
    fill_project,
    pick_budget_row,
    register_counter_partner,
    set_counter_partner,
    set_invoice_date,
    set_master_total,
    set_row_note,
    type_amount,
)

# ── 학자금 델타: 예산단위(D8) — base·검색어만 경조금과 다름 ────────────────────
# 경조금: base "복리후생비-경조"/kw "경조" → 학자금: base "복리후생비-기타"/kw "복리후생비".
# 실측(2026-07-15, hakjagum_probe_results.json D8): (제)복리후생비-기타=BGACCT_CD 511010600 ·
# (판)복리후생비-기타=811010600(부서 무관 고정, (제)/(판)만 부서별로 갈림). kw "복리후생비"는
# 444행 전량 '복리후생비-*' 계열이라 pick_budget_row 정확매칭에 안전한 반면, 초기값이던 kw
# "기타"는 270행 중 226행이 여비교통비-기타·보험료-기타 등 무관 계정으로 오염돼 비추천. 검증:✅.
# 비용구분→접두(_COST_PREFIX)는 국내출장과 동일 규칙이라 trip_domestic.steps 에서 재사용(중복 정의 금지).
HAKJAGUM_BGACCT_BASE = "복리후생비-기타"
BUDGET_SEARCH_KW = "복리후생비"


def bgacct_name_for_cost_type(cost_type: str | None) -> str:
    """cost_type('판관비'|'제조원가') → 예산계정명 '(판)/(제)복리후생비-기타'.

    알 수 없는 cost_type 이면 ValueError(한국어) — 임의 접두 금지(잘못된 예산계정 방지).
    """
    prefix = _COST_PREFIX.get((cost_type or "").strip())
    if not prefix:
        raise ValueError(f"알 수 없는 비용구분입니다: {cost_type!r} (판관비/제조원가)")
    return f"{prefix}{HAKJAGUM_BGACCT_BASE}"


async def fill_budget_fixed(page: Any, department: str, cost_type: str) -> dict:
    """예산단위 셀 = "복리후생비-기타" 고정 — 부서 × cost_type(판/제) 조합 정확매칭 선택.

    경조금 fill_budget_fixed 와 동일 로직이며 base/검색어만 학자금 값이다. 무/다중매칭 시 후보
    나열 오류(임의선택 금지). 반환 {ok, code, name} | {ok:False, reason}.
    """
    try:
        bgacct_nm = bgacct_name_for_cost_type(cost_type)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    op = await trip_steps._open_detail_cell_picker(page, BUDGET_CELL, "예산단위")
    if not op.get("ok"):
        return op
    await _picker_search(page, BUDGET_SEARCH_KW)
    read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [BUDGET_FIELDS, 0])
    row, err = pick_budget_row(read.get("options") or [], department, bgacct_nm)
    if err:
        return await trip_steps._fail_close(page, err)
    fin = await trip_steps._select_and_apply(page, row["i"], "예산단위", "BG_NM", row.get("BG_NM"))
    if not fin.get("ok"):
        return fin
    return {
        "ok": True,
        "code": row.get("BG_CD"),
        "name": f"{row.get('BG_NM')} · {row.get('BIZPLAN_NM')} · {row.get('BGACCT_NM')}",
    }
