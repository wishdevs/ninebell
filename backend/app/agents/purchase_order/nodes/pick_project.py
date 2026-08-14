"""pick_project — 프로젝트 선택(실행 전 폼 사전 선택 우선, 없으면 HITL 검색 개입).

진입 경로 2개 — 적용 이후(필드 반영 확인 → 조회(F2) → BOM 로드)는 `_apply_and_load` 로 공유한다:
  ① **사전 선택**(2026-08-13): 실행 전 폼이 기존 프로젝트 카탈로그로 고른
     `params["purchase_order"]{project_no, keyword}` 가 있으면 개입 없이 바로 적용한다.
     적용 실패는 하드가 아니다 — 아래 ② 개입으로 폴백해 사용자가 직접 검색·선택한다
     (카탈로그 스냅샷이 낡아 ERP 도움창에서 안 잡히는 경우 대비).
  ② **HITL 검색 개입**(기존 kind 'search' 재사용, 신규 kind 아님) — 지속 채널
     (open_hitl_channel) + query 왕복 루프(card_collect collect.py 패턴):
       query 제출 → ERP 프로젝트 도움창 검색(팝업당 1회 + 재오픈 재시도 상한 2)
                  → **프레임 전체 재방출**(options 갱신 — 프론트는 run.hitl 을 통째로 교체).
       value 제출 → 그 PJT_NO 를 도움창 재검색·선택·적용 → 필드 반영 확인 → 조회(F2) → break.

프레임(공유 계약): {"hitl": {"id","kind":"search","title":"프로젝트 선택",
  "prompt":"발주할 프로젝트를 검색해 선택하세요.",
  "options":[{"value":"<PJT_NO>","label":"<PJT_NM>","description":"<담당 · 기간 · 상태>"}]}}
초기 프레임 options=[] — emit_hitl 은 빈 options 를 누락시키므로 events.put 으로 직접 방출해
키 존재를 보장한다.

⚠ 프리필 불신(D11): 진입 시 프로젝트 필드에 이전 값이 남아 있어도 항상 명시 재검색·선택한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.agents.purchase_order import steps
from app.agents.purchase_order.params import parse_purchase_order_params
from app.config import get_settings
from app.live.events import emit_log, emit_step
from app.live.hitl import close_hitl_channel, open_hitl_channel
from nbkit.patterns import emit_shot

logger = logging.getLogger(__name__)

STEP = "pick_project"
TITLE = "프로젝트 선택"
PROMPT = "발주할 프로젝트를 검색해 선택하세요."
MAX_QUERY_LEN = 50
APPLY_FAIL_CAP = 2  # 적용 실패 시 사용자 재시도 허용 횟수(초과 = 하드 실패)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _describe(row: dict) -> str:
    """개입 카드 보조설명 — 담당 · 기간 · 상태(있는 것만)."""
    period = "~".join(p for p in (row.get("START_DT") or "", row.get("END_DT") or "") if p)
    parts = [row.get("RSPNBER_EMP_NM") or "", period, row.get("PJT_ST_NM") or ""]
    return " · ".join(p for p in parts if p)


async def _apply_and_load(
    page, events, *, keyword: str, pjt_no: str, label: str
) -> dict:
    """프로젝트 적용 → 필드 반영 확인 → 조회(F2) → BOM 로드 확인. 두 진입 경로가 공유한다.

    반환 {"ok": True, "project": {...}} | {"ok": False, "reason": …, "hard": bool}
      hard=True  적용은 됐는데 BOM 이 안 떴다 — 다른 프로젝트를 골라도 해결될 문제가 아니라 중단.
      hard=False 적용 실패 — 호출부가 재시도(개입) 폴백을 결정한다.
    """
    r = await steps.apply_project(page, keyword, pjt_no)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "적용 실패", "hard": False}
    name = r.get("name") or label
    await emit_log(events, f"프로젝트 '{name}'(코드 {pjt_no}) 적용 — 필드 반영 확인 ✅", "ok")
    # 적용 직후 조회(F2) — BOM 로드까지 확인(계약: 적용→반영 확인→조회).
    await steps.click_lookup(page)
    rows_n = await steps.wait_bom_loaded(page)
    if rows_n <= 0:
        return {
            "ok": False,
            "reason": f"프로젝트 '{name}' 조회(F2) 후 BOM 그리드가 로드되지 않았습니다.",
            "hard": True,
        }
    await emit_log(events, f"조회(F2) — BOM {rows_n}행 로드.", "ok")
    await emit_shot(events.put, page)
    return {"ok": True, "project": {"code": pjt_no, "name": name}}


def make_pick_project_node():
    async def pick_project(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()
        wait_timeout = get_settings().hitl_timeout_s

        # ── ① 사전 선택(실행 전 폼) — 개입 없이 바로 적용, 실패하면 ② 개입으로 폴백 ──
        try:
            pre = parse_purchase_order_params(state.get("params"))
        except ValueError as exc:  # 한국어 메시지 — 그대로 error 프레임으로.
            await emit_step(events, STEP, "failed")
            return {"error": str(exc)}

        if pre.has_preselection:
            label = pre.project_name or pre.project_no or ""
            await emit_log(
                events,
                f"실행 전 선택한 프로젝트 '{label}'(코드 {pre.project_no}) 적용 중… "
                f"(도움창 검색어 '{pre.keyword}')",
                "action",
            )
            res = await _apply_and_load(
                page, events, keyword=pre.keyword or "", pjt_no=pre.project_no or "", label=label
            )
            if res.get("ok"):
                await emit_step(events, STEP, "done", _ms(t0))
                return {"project": res["project"]}
            if res.get("hard"):
                await emit_step(events, STEP, "failed")
                return {"error": res["reason"]}
            # 적용 실패(카탈로그 스냅샷이 낡아 도움창에 없는 등) — 개입으로 직접 고르게 한다.
            # ⚠ 서버 로그에도 남긴다(2026-08-14): 종전엔 사유가 SSE 로그 프레임에만 있어
            #   런이 살아 있는 동안 원인을 사후 조회할 방법이 없었다(DB logs 는 종료 시 기록).
            logger.warning(
                "purchase-order 사전 선택 적용 실패 — pjt_no=%s keyword=%r reason=%s",
                pre.project_no,
                pre.keyword,
                res.get("reason"),
            )
            await emit_log(
                events,
                f"선택한 프로젝트를 적용하지 못했습니다({res['reason']}) — "
                "검색 개입으로 직접 선택해 주세요.",
                "warn",
            )
            await steps.close_popup(page)

        decision_id = uuid.uuid4().hex
        q = open_hitl_channel(decision_id, owner=state.get("owner"), run_id=state.get("run_id"))

        options: list[dict] = []
        by_value: dict[str, dict] = {}  # value(PJT_NO) → 옵션(라벨 회수용)
        last_query: str | None = None
        apply_fails = 0

        async def _emit_frame() -> None:
            # 프론트는 run.hitl 을 통째로 교체 — 재방출마다 options 전체를 싣는다.
            # options=[] 도 키로 실어야 하므로 emit_hitl(빈 리스트 누락) 대신 직접 방출.
            await events.put(
                {
                    "hitl": {
                        "id": decision_id,
                        "kind": "search",
                        "title": TITLE,
                        "prompt": PROMPT,
                        "options": options,
                    }
                }
            )

        await _emit_frame()
        try:
            while True:
                try:
                    resp = await asyncio.wait_for(q.get(), timeout=wait_timeout)
                except (TimeoutError, asyncio.TimeoutError):
                    await emit_step(events, STEP, "failed")
                    return {"error": f"프로젝트 선택 대기 시간 초과({wait_timeout // 60}분)."}

                query = resp.get("query") if isinstance(resp, dict) else None
                if isinstance(query, str) and query.strip():
                    kw = query.strip()[:MAX_QUERY_LEN]
                    r = await steps.open_and_search_once(page, kw)
                    if not r.get("ok"):
                        await emit_log(
                            events, f"프로젝트 검색 실패 — {r.get('reason')}", "warn"
                        )
                        options = []
                        by_value = {}
                    else:
                        rows = r.get("rows") or []
                        options = [
                            {
                                "value": row["PJT_NO"],
                                "label": row["PJT_NM"],
                                "description": _describe(row),
                            }
                            for row in rows
                            if row.get("PJT_NO")
                        ]
                        by_value = {o["value"]: o for o in options}
                        last_query = kw
                        await emit_log(
                            events, f"'{kw}' 검색 결과 {len(options)}건.", "info"
                        )
                        # 검색만 한 팝업은 닫아 둔다(선택·적용은 value 제출 시 새 사이클로).
                        await steps.close_popup(page)
                    await _emit_frame()
                    continue

                value = resp.get("value") if isinstance(resp, dict) else None
                if isinstance(value, str) and value.strip():
                    v = value.strip()
                    opt = by_value.get(v)
                    if opt is None or not last_query:
                        await emit_log(
                            events,
                            "선택한 프로젝트가 최근 검색 결과에 없습니다 — 다시 검색해 주세요.",
                            "warn",
                        )
                        await _emit_frame()
                        continue
                    res = await _apply_and_load(
                        page, events, keyword=last_query, pjt_no=v, label=opt["label"]
                    )
                    if res.get("ok"):
                        await emit_step(events, STEP, "done", _ms(t0))
                        return {"project": res["project"]}
                    if res.get("hard"):  # 적용은 됐는데 BOM 미로드 — 재선택으로 안 풀린다.
                        await emit_step(events, STEP, "failed")
                        return {"error": res["reason"]}
                    apply_fails += 1
                    if apply_fails >= APPLY_FAIL_CAP:
                        await emit_step(events, STEP, "failed")
                        return {"error": f"프로젝트 적용 실패 — {res['reason']}"}
                    await emit_log(
                        events,
                        f"프로젝트 적용 실패({res['reason']}) — 다시 선택해 주세요.",
                        "warn",
                    )
                    await _emit_frame()
                    continue

                logger.debug("purchase-order pick_project: 무시된 메시지 %r", resp)
                continue
        finally:
            close_hitl_channel(decision_id)

    return pick_project
