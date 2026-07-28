"""경조금신청서 결의서입력 — detail 그리드 채움 스텝(대부분 trip_domestic 재사용).

detail 그리드가 국내출장과 84필드 완전 동일(2026-07-13 프로브)이라 거래처(본인 검색)·프로젝트·
금액 타이핑·적요·계산서일·상대계정(본인)·빈행삭제·마스터합계 스텝을 **국내출장에서 그대로
import** 한다(확인 커널 적용분도 그 단일소스에서 승계된다 — 여기서 다시 확인하지 않는다).
경조금 고유 델타는 **예산계정 base('복리후생비-경조')·검색어('경조')** 뿐이라 예산단위 스텝
(bgacct_name_for_cost_type·fill_budget_fixed)만 재정의한다. 매칭 함수(pick_budget_row)와 피커 공용
헬퍼(_open_detail_cell_picker·_fail_close·_search_and_pick·_select_and_apply)도 국내출장 것을 재사용한다.
"""

from __future__ import annotations

from typing import Any

from nbkit.omnisol import js_lib, verify
from nbkit.omnisol.codepicker import _norm

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

# ══════════════════════════════════════════════════════════════════════════════
# 확인(verify) 규율 — 값을 세팅한 스텝은 **반영을 확인**하고서야 ok 를 돌려준다.
#   불일치(리더로 셀을 읽었는데 값이 다름) = 하드 실패(잘못된 값이 그대로 저장되는 것을 차단).
#   확인 불가(리더가 그리드/행/필드를 못 잡음) = 경고 후 진행(리더 오탐이 플로우를 끊지 않게 —
#   기존 D7 규율과 동일). 재시도는 nbkit.omnisol.verify 커널(즉시 1회 + 점증 대기 3회)이 담당하고
#   대기는 실시간이라 delay_scale 에 깎이지 않는다. 정상 경로는 첫 read(0ms)에서 끝난다.
# 재사용 스텝(적요·계산서일·금액·마스터합계·거래처·프로젝트)의 확인은 국내출장 단일소스에
# 이미 들어 있다 — 여기서는 **경조금 델타(예산단위)에만** 추가 확인을 붙인다.
# ══════════════════════════════════════════════════════════════════════════════
DETAIL_GRID_INDEX = 1  # 0=마스터(결의서 헤더), 1=상세(detail) — GRID_CELL_VALUE_JS 인자.


def _cell_unreadable(v: Any) -> bool:
    """GRID_CELL_VALUE_JS 가 ok:false = 그리드/행/필드를 못 잡음(값이 틀린 게 아니라 확인 불가)."""
    return not (isinstance(v, dict) and v.get("ok"))


async def confirm_detail_cell(page: Any, field: str, expected: Any, *, what: str) -> verify.Confirmed:
    """detail **마지막 행**의 field 원시값이 expected 와 **완전일치**하는지 확인.

    detail 조작은 항상 마지막(현재) 행 대상이라는 steps 계약을 그대로 따른다(GRID_CELL_VALUE_JS
    의 row 생략 = 마지막 행). 셀을 읽었는데 **비어 있으면 미반영(=불일치)** 이지 확인 불가가
    아니다 — 빈 값을 확인 불가로 넘기면 적용이 통째로 안 붙은 사고를 못 잡는다.
    """
    want = _norm(expected)

    async def read() -> Any:
        return await page.evaluate(
            js_lib.GRID_CELL_VALUE_JS, {"index": DETAIL_GRID_INDEX, "field": field}
        )

    def ok(v: Any) -> bool:
        if _cell_unreadable(v):
            return False
        return _norm(((v.get("raw") or {}).get(field))) == want

    return await verify.confirm(
        read,
        ok,
        timing=verify.INSTANT,  # 적용 반영은 셀 확인 시점엔 이미 끝나 있다 — 정상이면 첫 read.
        what=what,
        expected=expected,
        unknown_when=_cell_unreadable,
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

    ⚠ 적용 후 **BG_CD 완전일치**까지 확인한다: `_select_and_apply` 의 반영 판정은 BG_NM(부서명)
    상호포함이라 이름이 서로 포함되는 다른 예산단위 행이 붙어도 통과한다(예 '회계팀' ⊂ '회계팀2').
    예산단위는 이 전표가 어느 예산을 집행하는지를 정의하므로 유일키로 확정한다 — 불일치는 하드
    실패, 셀을 못 읽으면 warn 후 진행.
    """
    try:
        bgacct_nm = bgacct_name_for_cost_type(cost_type)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    op = await trip_steps._open_detail_cell_picker(page, BUDGET_CELL, "예산단위")
    if not op.get("ok"):
        return op
    # 검색 정착 확인 + 무매칭 재검색(국내출장 단일소스) — Enter 직후 정착 전에 읽으면 필터 전
    # 전량(444행)이 잡혀 '다중매칭' 오류나 필터 전 행 오선택이 난다.
    row, err = await trip_steps._search_and_pick(
        page,
        BUDGET_SEARCH_KW,
        BUDGET_FIELDS,
        lambda opts: pick_budget_row(opts, department, bgacct_nm),
    )
    if err or not row:
        return await trip_steps._fail_close(page, err or "예산단위 후보를 읽지 못했습니다")
    fin = await trip_steps._select_and_apply(page, row["i"], "예산단위", "BG_NM", row.get("BG_NM"))
    if not fin.get("ok"):
        return fin
    out: dict = {
        "ok": True,
        "code": row.get("BG_CD"),
        "name": f"{row.get('BG_NM')} · {row.get('BIZPLAN_NM')} · {row.get('BGACCT_NM')}",
    }
    warns = [w for w in (fin.get("warn"),) if w]
    # BG_NM 판정(_select_and_apply)은 **상호포함**이라 이름이 서로 포함되는 다른 예산단위 행이
    # 붙어도 통과한다(예 '회계팀' ⊂ '회계팀2'). 예산단위는 이 전표가 어느 예산을 집행하는지를
    # 정의하므로 유일키(BG_CD) 완전일치로 확정한다 — 불일치는 하드 실패.
    res = await confirm_detail_cell(page, "BG_CD", row.get("BG_CD"), what="예산단위 코드(BG_CD)")
    if res.mismatch:
        return {"ok": False, "reason": res.reason}
    if not res:  # 확인 불가 — 반영을 단정하지 않고 경고만 남긴다.
        warns.append(res.reason)
    if warns:
        out["warn"] = " / ".join(warns)
    return out
