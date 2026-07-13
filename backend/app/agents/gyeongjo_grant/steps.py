"""경조금신청서 결의서입력 — detail 그리드 채움 스텝(대부분 trip_domestic 재사용).

detail 그리드가 국내출장과 84필드 완전 동일(2026-07-13 프로브)이라 거래처(본인 검색)·프로젝트·
금액 타이핑·적요·계산서일·상대계정(본인)·빈행삭제·마스터합계 스텝을 **국내출장에서 그대로
import** 한다. 경조금 고유 델타는 **예산계정 base('복리후생비-경조')·검색어('경조')** 뿐이라
예산단위 스텝(bgacct_name_for_cost_type·fill_budget_fixed)만 재정의한다. 매칭 함수(pick_budget_row)
와 피커 공용 헬퍼(_open_detail_cell_picker·_fail_close·_select_and_apply)도 국내출장 것을 재사용한다.
"""

from __future__ import annotations

from typing import Any

from nbkit.omnisol import js_lib
from nbkit.omnisol.codepicker import _picker_search

from app.agents.trip_domestic import steps as trip_steps

# 국내출장에서 그대로 재사용하는 스텝(경조금 델타 없음) — fill 노드가 `steps.<name>` 으로 참조.
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

# ── 경조금 델타: 예산단위(D8) — base·검색어만 국내출장과 다름 ────────────────────
# 국내출장: base "여비교통비-국내출장"/kw "국내출장" → 경조금: base "복리후생비-경조"/kw "경조".
# 비용구분→접두(_COST_PREFIX)는 국내출장과 동일 규칙이라 trip_domestic.steps 에서 재사용(중복 정의 금지).
GYEONGJO_BGACCT_BASE = "복리후생비-경조"
BUDGET_SEARCH_KW = "경조"


def bgacct_name_for_cost_type(cost_type: str | None) -> str:
    """cost_type('판관비'|'제조원가') → 예산계정명 '(판)/(제)복리후생비-경조'.

    알 수 없는 cost_type 이면 ValueError(한국어) — 임의 접두 금지(잘못된 예산계정 방지).
    """
    prefix = _COST_PREFIX.get((cost_type or "").strip())
    if not prefix:
        raise ValueError(f"알 수 없는 비용구분입니다: {cost_type!r} (판관비/제조원가)")
    return f"{prefix}{GYEONGJO_BGACCT_BASE}"


async def fill_budget_fixed(page: Any, department: str, cost_type: str) -> dict:
    """예산단위 셀 = "복리후생비-경조" 고정 — 부서 × cost_type(판/제) 조합 정확매칭 선택.

    국내출장 fill_budget_fixed 와 동일 로직이며 base/검색어만 경조금 값이다. 무/다중매칭 시 후보
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
