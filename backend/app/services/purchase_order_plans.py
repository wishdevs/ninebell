"""구매발주 계획서 보관 서비스 — 확정 계획(confirmed_plan)을 purchase_order_plans 에 저장.

plan 노드가 검증 통과 직후 호출한다. 저장은 부가기능 — owner 없으면(스크립트/익명) no-op,
DB 실패는 로그만 남기고 None 을 돌려 런을 깨지 않는다.
"""

from __future__ import annotations

import logging
import uuid

from app.db import get_sessionmaker
from app.models import PurchaseOrderPlan

logger = logging.getLogger(__name__)


def plan_unit_count(plan: dict) -> int:
    return len(plan.get("units") or [])


def plan_total_amount(plan: dict) -> float:
    """모든 발주단위의 vendorGroups[].amount 합(숫자 아닌 값은 0 취급)."""
    total = 0.0
    for unit in plan.get("units") or []:
        for vg in unit.get("vendorGroups") or []:
            amount = vg.get("amount")
            if isinstance(amount, (int, float)):
                total += float(amount)
    return total


def _uuid(owner: str | None) -> uuid.UUID | None:
    if not owner:
        return None
    try:
        return uuid.UUID(str(owner))
    except (ValueError, TypeError):
        return None


async def record_plan(
    owner: str | None,
    *,
    run_id: str | None,
    agent_id: str,
    plan: dict,
    project: dict | None,
    bom_summary: dict | None,
) -> uuid.UUID | None:
    """확정 계획서 1건 저장 → 생성 id. owner 없거나 저장 실패면 None."""
    uid = _uuid(owner)
    if uid is None:
        return None
    # 프로젝트·WBS 는 제출 계획 값을 우선, 없으면 상태(project)의 값으로 채운다.
    plan_project = plan.get("project") if isinstance(plan.get("project"), dict) else {}
    state_project = project or {}
    row = PurchaseOrderPlan(
        user_id=uid,
        run_id=run_id,
        agent_id=agent_id,
        project_code=plan_project.get("code") or state_project.get("code"),
        project_name=plan_project.get("name") or state_project.get("name"),
        wbs=plan.get("wbs") or state_project.get("wbs"),
        unit_count=plan_unit_count(plan),
        total_amount=plan_total_amount(plan),
        plan=plan,
        bom_summary=bom_summary,
    )
    try:
        async with get_sessionmaker()() as s:
            s.add(row)
            await s.commit()
            return row.id
    except Exception:  # noqa: BLE001 — 보관 실패가 런을 깨선 안 된다.
        logger.exception("purchase-order record_plan failed")
        return None
