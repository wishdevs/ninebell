"""구매발주 자동 재개 — 이전 실패/취소 런의 잔여물(IRQ·PRQ)을 우리 런 기록에서 수거.

왜 ERP 가 아니라 런 기록인가(2026-08-31 재개 진단 프로브):
- 이동요청 행은 저장 후에도 화면 ① 뷰에서 소멸하지 않아(완결 ETRI-002 = 여전히 163행) 행수로
  '이미 저장됨'을 판별할 수 없다.
- 화면 ② 마스터의 비고(RMK_DC)는 비어 있어 프로젝트 접두 매칭이 불가하다.
런 로그에는 프로젝트 적용·이동요청번호·발주단위별 PRQ 가 결정적 문구로 남고, 계획서는
purchase_order_plans 에 run_id 로 보관된다 — 이 둘을 결합하면 (프로젝트, IRQ, PRQ↔unit) 이 나온다.
각 PRQ 의 **현재 상태**(상신됐나/발주됐나) 확인은 노드가 ERP 에서 한다(화면 ② 결재상태 가드,
발주 팝업 행 유무).
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import AgentRun, PurchaseOrderPlan

logger = logging.getLogger(__name__)

RE_PROJECT = re.compile(r"프로젝트 '[^']*'\(코드 ([^)]+)\) 적용")
RE_UNIT = re.compile(r"발주단위 #(\d+) 저장 완료 — 구매요청번호 (PRQ\d+)")
RE_MOVE = re.compile(r"이동요청번호 (IRQ\d+)")
#: 잔여물 수거 대상 런 상태 — 성공 런의 PRQ 는 이미 끝까지 처리됐으므로 제외.
RESUMABLE_STATUSES = ("failed", "cancelled")


def parse_run_artifacts(logs: list) -> dict:
    """런 로그(list[{message,...}]) → {"projectCode", "moveRequestNo", "units": [(seq, prq)]}. 순수."""
    project_code: str | None = None
    move_no: str | None = None
    units: list[tuple[int, str]] = []
    for entry in logs or []:
        msg = str((entry or {}).get("message") or "")
        if project_code is None:
            m = RE_PROJECT.search(msg)
            if m:
                project_code = m.group(1).strip()
        m = RE_MOVE.search(msg)
        if m:
            move_no = m.group(1)
        m = RE_UNIT.search(msg)
        if m:
            units.append((int(m.group(1)), m.group(2)))
    return {"projectCode": project_code, "moveRequestNo": move_no, "units": units}


async def prior_artifacts(project_code: str, *, exclude_run_id: str | None = None) -> dict:
    """같은 프로젝트의 이전 실패/취소 런에서 잔여물 수거.

    반환 {"moveRequestNo": str|None, "prqs": [{"seq","number","runId"}], "planByRun": {run_id: plan}}.
    실패해도 빈 결과 — 재개 수거가 정상 실행을 깨선 안 된다.
    """
    empty = {"moveRequestNo": None, "prqs": [], "planByRun": {}}
    code = (project_code or "").strip()
    if not code:
        return empty
    try:
        async with get_sessionmaker()() as s:
            runs = (
                (
                    await s.execute(
                        select(AgentRun)
                        .where(
                            AgentRun.agent_id == "purchase-order",
                            AgentRun.status.in_(RESUMABLE_STATUSES),
                        )
                        .order_by(AgentRun.started_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            move_no: str | None = None
            prqs: list[dict] = []
            seen: set[str] = set()
            run_ids: list[str] = []
            for run in runs:
                if exclude_run_id and str(run.id) == str(exclude_run_id):
                    continue
                art = parse_run_artifacts(run.logs or [])
                if art["projectCode"] != code:
                    continue
                if art["moveRequestNo"]:
                    move_no = art["moveRequestNo"]
                for seq, prq in art["units"]:
                    if prq in seen:
                        continue
                    seen.add(prq)
                    prqs.append({"seq": seq, "number": prq, "runId": str(run.id)})
                if art["units"] or art["moveRequestNo"]:
                    run_ids.append(str(run.id))
            plan_by_run: dict[str, dict] = {}
            if run_ids:
                rows = (
                    (
                        await s.execute(
                            select(PurchaseOrderPlan).where(PurchaseOrderPlan.run_id.in_(run_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                plan_by_run = {str(p.run_id): p.plan for p in rows}
            return {"moveRequestNo": move_no, "prqs": prqs, "planByRun": plan_by_run}
    except Exception:  # noqa: BLE001 — 수거 실패는 재개 없이 진행(정상 실행 보호).
        logger.exception("purchase-order resume: 잔여물 수거 실패")
        return empty
