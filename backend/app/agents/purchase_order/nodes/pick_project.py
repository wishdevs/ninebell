"""pick_project — 실행 전 폼에서 고른 프로젝트를 적용한다(개입 없음).

실행 전 폼(`purchase-order-pre-run-form.tsx`)이 프로젝트(카탈로그 선택 또는 직접 검색어)를
필수로 받으므로, 여기서는 **적용만** 한다:

    도움창 검색(keyword) → 행 선택(PJT_NO, 없으면 단일 결과) → '적용'
    → 필드 반영 확인 → 조회(F2) → BOM 로드.

⚠ 검색 개입(HITL) 폴백은 제거했다(사용자 지시 2026-08-14) — 폼에서 이미 골랐는데 실패했다고
  같은 것을 다시 고르라는 개입을 띄우는 이중 입력이었다. 이제 적용 실패는 **하드 실패**로
  사유를 그대로 error 프레임에 싣는다(재실행이 재시도다).

⚠ 검색어에 '#' 금지(진단 프로브 2026-08-14): 도움창은 '#' 포함 검색·PJT_NO 숫자 검색에서
  팝업이 죽는다. 검색어 정화('#' 앞까지)는 params.parse 가 담당하고, 'MISC-ESR3' 처럼
  넓어진 결과에서 PJT_NO 로 정확 선택한다.

⚠ 프리필 불신(D11): 진입 시 프로젝트 필드에 이전 값이 남아 있어도 항상 명시 재검색·선택한다.
"""

from __future__ import annotations

import logging
import time

from app.agents.purchase_order import steps
from app.agents.purchase_order.params import parse_purchase_order_params
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

logger = logging.getLogger(__name__)

STEP = "pick_project"
# 개입 폴백이 없으므로 재시도가 유일한 복원 수단 — 기본(2)보다 한 번 더 준다.
APPLY_RETRIES = 3


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def _apply_and_load(page, events, *, keyword: str, pjt_no: str, label: str) -> dict:
    """프로젝트 적용 → 필드 반영 확인 → 조회(F2) → BOM 로드 확인.

    반환 {"ok": True, "project": {...}} | {"ok": False, "reason": …}
    """
    r = await steps.apply_project(page, keyword, pjt_no, retries=APPLY_RETRIES)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "적용 실패"}
    name = r.get("name") or label
    code = str(r.get("pjt_no") or pjt_no)
    await emit_log(events, f"프로젝트 '{name}'(코드 {code}) 적용 — 필드 반영 확인 ✅", "ok")
    # 적용 직후 조회(F2) — BOM 로드까지 확인(계약: 적용→반영 확인→조회).
    await steps.click_lookup(page)
    rows_n = await steps.wait_bom_loaded(page)
    if rows_n <= 0:
        return {
            "ok": False,
            "reason": f"프로젝트 '{name}' 조회(F2) 후 BOM 그리드가 로드되지 않았습니다.",
        }
    await emit_log(events, f"조회(F2) — BOM {rows_n}행 로드.", "ok")
    await emit_shot(events.put, page)
    return {"ok": True, "project": {"code": code, "name": name}}


def make_pick_project_node():
    async def pick_project(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()

        try:
            pre = parse_purchase_order_params(state.get("params"))
        except ValueError as exc:  # 한국어 메시지 — 그대로 error 프레임으로.
            await emit_step(events, STEP, "failed")
            return {"error": str(exc)}

        if not pre.has_preselection:
            await emit_step(events, STEP, "failed")
            return {
                "error": (
                    "실행 전 입력에서 프로젝트를 선택(또는 검색어를 입력)해 주세요 — "
                    "실행 중 프로젝트 선택 개입은 제공하지 않습니다."
                )
            }

        label = pre.project_name or pre.project_no or pre.keyword or ""
        await emit_log(
            events,
            f"실행 전 선택한 프로젝트 '{label}' 적용 중… "
            f"(도움창 검색어 '{pre.keyword}'"
            + (f", 코드 {pre.project_no})" if pre.project_no else ", 단일 결과 자동 선택)"),
            "action",
        )
        res = await _apply_and_load(
            page, events, keyword=pre.keyword or "", pjt_no=pre.project_no or "", label=label
        )
        if res.get("ok"):
            await emit_step(events, STEP, "done", _ms(t0))
            return {"project": res["project"]}

        # 하드 실패 — 폴백 없음. 사유를 서버 로그와 error 프레임 양쪽에 남긴다.
        logger.warning(
            "purchase-order 프로젝트 적용 실패 — pjt_no=%s keyword=%r reason=%s",
            pre.project_no,
            pre.keyword,
            res.get("reason"),
        )
        await steps.close_popup(page)
        await emit_step(events, STEP, "failed")
        return {
            "error": (
                f"프로젝트 '{label}' 적용에 실패했습니다 — {res.get('reason')} "
                "실행 전 입력을 확인하고 다시 실행해 주세요."
            )
        }

    return pick_project
