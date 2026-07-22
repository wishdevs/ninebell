"""라이브 실행(run) 라우터 — SSE 수집 + HITL 응답.

POST /runs/collect: 워크플로우를 라이브 세션으로 실행하고 단계 이벤트를 SSE 로 스트리밍한다.
  세션이 SSE 연결과 분리돼 살아있으므로(app.live.session), 끊김 뒤 같은 runId+cursor 로
  재부착하면 흐름을 재시작하지 않고 커서 이후만 재생한다. 인증은 세션 쿠키(get_current_user).
POST /runs/hitl: 라이브 흐름의 HITL 대기에 사용자 응답을 전달한다(소유자=현재 유저 +
  채널이 바인딩한 run_id=요청 runId 교차검증).
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.creds import omnisol_password as _omnisol_password
from app.core.deps import CurrentUser, DbSession, require_permission, user_has_permission
from app.core.listing import PageQuery
from app.core.permissions import AGENTS_RUN, LOGS_READ
from app.live import store
from app.live.hitl import hitl_owner, hitl_run_id, resolve_hitl
from app.live.registry import get_spec
from app.live.runner import run_workflow
from app.live.session import cancel_session, create_session, get_session
from app.models import Agent, AgentRun, AgentTemplate
from app.services.agent_settings import effective_settings

# 숨김 집합의 단일 소스는 services.agent_visibility — 모듈 전역 별칭(_HIDDEN_AGENT_IDS)은
# 테스트 주입 앵커(test_runs_hidden.py 가 monkeypatch). collect 가 호출 시점에 이 전역을 읽는다.
from app.services.agent_visibility import HIDDEN_AGENT_IDS as _HIDDEN_AGENT_IDS
from app.services.agent_visibility import ensure_can_run
from app.services.org_lookup import user_cost_type

logger = logging.getLogger(__name__)
# 전 엔드포인트 AGENTS_RUN 강제(라우터 레벨) — 인증 + 실행 권한. 조직구분 접근은 collect 에서 추가.
router = APIRouter(
    prefix="/runs",
    tags=["runs"],
    dependencies=[Depends(require_permission(AGENTS_RUN))],
)


def _sse(events) -> StreamingResponse:
    """이벤트 dict 비동기 이터러블을 SSE(text/event-stream) 응답으로 감싼다."""

    async def body():
        async for ev in events:
            # default=str: 날짜(datetime) 등 비직렬화 값을 문자열로.
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class CollectRequest(BaseModel):
    # 서버 세션/런 id(세션 사용자 소유). 있으면 재연결·런 추적, 없으면 익명(1회성).
    runId: str | None = Field(default=None, max_length=40)
    agentId: str = Field(min_length=1, max_length=64)
    # 재연결(resume) 커서 — 이미 받은 이벤트 수. >0 이면 기존 세션 재부착(새 흐름 시작 안 함).
    cursor: int = Field(default=0, ge=0)
    # 워크플로우 파라미터(그래프 state["params"] 로 주입).
    params: dict | None = None
    # AUTO 재생(회수): 저장된 템플릿 id. 있으면 그 selections 를 params["template"] 로 주입해
    # expense_card chat_form 의 AUTO 경로(대화·Gemini 없이 순서대로 적용)를 태운다.
    templateId: str | None = Field(default=None, max_length=40)


class CancelRequest(BaseModel):
    runId: str = Field(min_length=1, max_length=40)


class TemplateCreate(BaseModel):
    agentId: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    # 대화형 실행에서 누적한 ChatSelection[] — [{"tool","field","value","query"?}, ...].
    selections: list[dict] = Field(default_factory=list)


class GridCodeRef(BaseModel):
    code: str = Field(max_length=64)
    name: str = Field(max_length=255)
    # 예산단위 조합 선택(BG×사업계획×예산계정) — 반영 시 그 조합 행을 정확히 고르기 위한 값.
    bizplanNm: str | None = Field(default=None, max_length=255)
    bgacctNm: str | None = Field(default=None, max_length=255)
    # 프로젝트 WBS 행 선택 — 반영 시 그 WBS 요소를 정확히 고르기 위한 값(PJT_NM 검색 후 WBS_NO 일치).
    wbsNo: str | None = Field(default=None, max_length=64)


class GridRowIn(BaseModel):
    # 그리드 HITL 일괄 제출 1행. 행 번호(no)는 프레임의 # 컬럼(1-based).
    no: int = Field(ge=1)
    budgetUnit: GridCodeRef | None = None
    project: GridCodeRef | None = None
    note: str = Field(default="", max_length=200)
    skip: bool = False
    # 개입 학습(필드 단위): 사용자가 프리필에서 실제로 바꾼 필드 표시 — 바꾼 것만 학습한다.
    # ⚠ 이 필드가 없으면 프론트가 보낸 편집 플래그가 model_dump 에서 버려져 학습이 전량 0건이
    #   된다(2026-07-05 실측 회귀). collect_rows 가 row.get('budgetEdited') 로 읽는다.
    budgetEdited: bool = False
    projectEdited: bool = False
    noteEdited: bool = False


class HitlDecision(BaseModel):
    runId: str | None = Field(default=None, max_length=40)
    decisionId: str = Field(min_length=1, max_length=64)
    value: str | None = Field(default=None, max_length=100)
    values: list[str] | None = None
    text: str | None = Field(default=None, max_length=500)
    query: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=2000)  # 대화형 HITL 한 턴 자연어
    done: bool | None = None  # 대화형 폼 '선택 완료' 신호
    # 그리드 HITL 일괄 제출 — 행별 예산단위·프로젝트·적요·건너뜀(최대 500행).
    rows: list[GridRowIn] | None = Field(default=None, max_length=500)


def _browser_factory(request: Request):
    """fresh 헤드리스 브라우저를 여는 async 콜러블. 테스트는 app.state override 로 주입."""
    override = getattr(request.app.state, "browser_factory", None)
    if override is not None:
        return override
    pw = request.app.state.playwright

    async def factory():
        return await pw.chromium.launch(headless=True)

    return factory


@router.post("/collect")
async def collect(body: CollectRequest, request: Request, user: CurrentUser, db: DbSession):
    """워크플로우를 라이브 세션으로 실행하고 단계 이벤트를 SSE 로 스트리밍(재연결 지원)."""
    owner = str(user.id)

    # 재연결(resume): 같은 runId 세션이 살아있으면 흐름을 재시작하지 않고 커서 이후만 재생.
    # 진행 중 흐름 유지를 위해 재연결 경로는 조직접근을 재검사하지 않는다(소유자 검증만).
    sess = get_session(body.runId)
    if sess is not None:
        if sess.owner and sess.owner != owner:
            return JSONResponse({"error": "이 흐름에 대한 권한이 없습니다."}, status_code=403)
        return _sse(sess.stream(body.cursor))

    # 세션이 없는데 커서>0 → 흐름이 이미 종료/정리됨(새 브라우저를 띄우지 않는다).
    if body.runId and body.cursor > 0:
        return JSONResponse(
            {"error": "흐름이 종료되었습니다. 다시 실행해 주세요."}, status_code=410
        )

    # 실행 allowlist + 조직접근 게이트(신규 세션 경로만). workflow_id 로 Agent 역조회 →
    # 없으면 404(=워크플로우 매핑된 에이전트만 실행 가능, demo-echo 등 미매핑 자동 차단).
    agent_row = (
        await db.execute(select(Agent).where(Agent.workflow_id == body.agentId))
    ).scalar_one_or_none()
    if agent_row is None:
        return JSONResponse(
            {"error": f"실행할 수 없는 에이전트입니다: {body.agentId}"}, status_code=404
        )
    # 실행 게이트(숨김 + 조직구분 접근) — agents.py 목록/상세 가시성과 동일 소스
    # (services.agent_visibility)로 통합. 숨김은 비관리자만 차단(관리자는 게이트 스모크 허용),
    # 조직접근은 명시 설정된 에이전트에 한해 user 롤만 검사(admin+ 우회).
    gate_error = await ensure_can_run(db, user, agent_row, hidden_ids=_HIDDEN_AGENT_IDS)
    if gate_error is not None:
        return JSONResponse({"error": gate_error}, status_code=403)

    spec = get_spec(body.agentId)
    if spec is None:
        return JSONResponse(
            {"error": f"알 수 없는 워크플로우입니다: {body.agentId}"}, status_code=404
        )
    factory = spec.factory

    tracked_run_id = body.runId
    if tracked_run_id:
        # 재추적: 다른 사용자의 런 id 면 차단(소유 격리).
        existing = await store.get_run(tracked_run_id)
        if existing is not None and str(existing.user_id) != owner:
            return JSONResponse({"error": "런을 찾을 수 없습니다."}, status_code=404)
        await store.create_run(run_id=tracked_run_id, agent_id=body.agentId, user_id=user.id)

    browser_factory = _browser_factory(request)
    semaphore = getattr(request.app.state, "run_semaphore", None)
    # 세션 자격증명(비밀번호)을 CredCache(jti)에서 조회해 실 워크플로우(expense-card-chat)에
    # 주입한다. demo-echo 는 비밀번호를 쓰지 않으므로 None 이어도 무해하다.
    creds = {"userid": user.omnisol_userid, "password": _omnisol_password(request)}
    # 에이전트별 세부설정(스키마 기본값+관리자 저장값)을 개별 키로 평탄화해 params 에 먼저 깐다.
    # ⚠ body.params 는 **서버 권위 키를 덮을 수 없다** — 사용자가 관리자 설정(fuel_* 단가/연비 등
    # AGENT_SETTINGS_SCHEMA 키)·department·cost_type 을 조작해 유류비 금액이나 예산계정을 바꾸는
    # 권한 상승을 차단한다(리뷰 HIGH). 권위 키 집합 = effective_settings 가 그 에이전트에 대해
    # 반환하는 키(스키마 유일소스라 에이전트별 하드코딩 없음) + department/cost_type(서버 주입).
    server_settings = effective_settings(agent_row.id, agent_row.settings)
    authoritative_keys = set(server_settings) | {"department", "cost_type"}
    user_params = {
        k: v for k, v in (body.params or {}).items() if k not in authoritative_keys
    }
    params = {**server_settings, **user_params}

    # 사용자 소속 팀의 비용구분(판관비/제조원가)을 params 로 주입 → 카드 자동화가 예산계정
    # (판)/(제) 접두사를 우선 선택하는 힌트로 쓴다(팀에만 비용구분이 붙는다).
    team_cost_type = await user_cost_type(db, user)
    if team_cost_type:
        params.setdefault("cost_type", team_cost_type)
    # 사용자 부서(BG_NM) 주입 → 출장 자동화가 예산단위(여비교통비-국내출장) 조합을 부서×비용구분
    # 으로 특정한다(카드 경로는 department 를 읽지 않아 불변). body.params 가 있으면 우선.
    if user.department:
        params.setdefault("department", user.department)

    # AUTO 재생(회수): templateId 가 있으면 소유자·워크플로우를 검증하고 저장된 selections 를
    # params["template"] 로 주입한다. chat_form 이 이를 보면 대화 없이 순서대로 적용한다.
    if body.templateId:
        tpl = await store.get_template(body.templateId)
        if tpl is None or str(tpl.user_id) != owner:
            return JSONResponse({"error": "템플릿을 찾을 수 없습니다."}, status_code=404)
        if tpl.agent_id != body.agentId:
            return JSONResponse(
                {"error": "템플릿의 에이전트가 요청과 일치하지 않습니다."}, status_code=400
            )
        params["template"] = tpl.selections or []

    # 에이전트별 실행 노브(대기 배율·브라우저 필요 여부·웜캐시 스코프)는 WorkflowSpec 이
    # 단일소스다(app/live/registry.py — 코드와 함께 버전). env CARD_DELAY_SCALE 은 여전히
    # 우선(테스트 override). needs_browser=False 면 브라우저 경로 전체를 생략(순수 API/LLM).
    def producer():
        return run_workflow(
            factory(),
            browser_factory if spec.needs_browser else None,
            creds,
            params,
            semaphore=semaphore,
            owner=owner,
            run_id=tracked_run_id,
            delay_scale=spec.delay_scale,
            site=spec.site,
            login_form_selector=spec.login_form_selector,
        )

    async def on_terminal(status: str, note: object, logs: list) -> None:
        if tracked_run_id:
            await store.set_terminal(tracked_run_id, status, note, logs)

    sess = create_session(body.runId, owner, producer, on_terminal)
    return _sse(sess.stream(0))


@router.post("/hitl")
async def hitl(body: HitlDecision, user: CurrentUser):
    """라이브 흐름의 HITL 대기에 사용자 응답 전달. 세션이 소유한 HITL 은 같은 사용자만 가능."""
    owner = hitl_owner(body.decisionId)
    if owner is not None and owner != str(user.id):
        return JSONResponse(
            {"ok": False, "error": "이 HITL 에 대한 권한이 없습니다."}, status_code=403
        )
    # 런바인딩 교차검증: 채널이 특정 run_id 에 묶여 있으면 요청의 runId 와 일치해야 한다
    # (다른 흐름의 decisionId 를 도용한 응답 주입 차단). 바인딩 없으면(스크립트/익명) 검사 생략.
    bound_run = hitl_run_id(body.decisionId)
    if bound_run is not None and bound_run != body.runId:
        return JSONResponse(
            {"ok": False, "error": "이 HITL 에 대한 권한이 없습니다."}, status_code=403
        )
    payload = {
        "value": body.value,
        "values": body.values,
        "text": body.text,
        "query": body.query,
        "message": body.message,
        "done": body.done,
        # 그리드 일괄 제출은 plain dict 목록으로 채널에 전달(노드가 서버검증 후 반영).
        "rows": [r.model_dump() for r in body.rows] if body.rows is not None else None,
    }
    return {"ok": resolve_hitl(body.decisionId, payload)}


# ── 즉시 종료(cancel) ──────────────────────────────────────────────────────
@router.post("/cancel")
async def cancel(body: CancelRequest, user: CurrentUser):
    """실행을 즉시 종료(브라우저 반납) — 소유자 검증 후 세션 cancel. 멱등(세션 없어도 200)."""
    owner = str(user.id)
    run = await store.get_run(body.runId)
    # 추적된 런이면 소유자만. 다른 사용자의 런은 존재를 숨긴다(404).
    if run is not None and str(run.user_id) != owner:
        return JSONResponse({"error": "런을 찾을 수 없습니다."}, status_code=404)
    sess = get_session(body.runId)
    if sess is not None and sess.owner and sess.owner != owner:
        return JSONResponse({"error": "이 흐름에 대한 권한이 없습니다."}, status_code=403)

    cancelled = await cancel_session(body.runId)
    # 세션이 없지만(이미 정리됨) DB 가 아직 미완료면 직접 cancelled 로 확정한다(멱등).
    if not cancelled and run is not None and run.status in ("running", "waiting"):
        await store.set_terminal(
            body.runId, "cancelled", "사용자가 실행을 종료했습니다.", run.logs or []
        )
    return {"ok": True, "status": "cancelled"}


# ── 실행 이력(run history) — 직렬화 헬퍼(camelCase) ──────────────────────────
def _result_summary(result: object) -> str | None:
    """목록용 짧은 결과 요약. 구조 결과(dict — 대화형 selections)는 summary 우선."""
    if result is None:
        return None
    if isinstance(result, str):
        return result[:200]
    if isinstance(result, dict) and result.get("summary"):
        return str(result["summary"])[:200]
    return json.dumps(result, ensure_ascii=False, default=str)[:200]


# 단계 로그 마커(session._accumulate_log) → 상태. 구조 필드가 없는 옛 로그의 폴백 파싱용.
_STEP_MARKS = {"▶": "running", "✓": "done", "✗": "failed"}


def _step_of(line: dict) -> tuple[str, str] | None:
    """로그 1줄에서 (step, status) 추출 — 구조 필드 우선, 없으면 '{mark} {step} ({status})' 파싱."""
    step, status = line.get("step"), line.get("status")
    if step and status:
        return str(step), str(status)
    msg = str(line.get("message", ""))
    if msg and msg[0] in _STEP_MARKS:
        rest = msg[1:].strip()
        if rest.endswith(")") and " (" in rest:
            name, sp = rest.rsplit(" (", 1)
            return name.strip(), sp[:-1].strip()
        return rest, _STEP_MARKS[msg[0]]
    return None


def _failed_step(logs: list | None) -> str | None:
    """실패한 마지막 단계명(logs 에서 status='failed' 인 마지막 step). 없으면 None."""
    for line in reversed(logs or []):
        parsed = _step_of(line)
        if parsed and parsed[1] == "failed":
            return parsed[0]
    return None


def _run_steps(logs: list | None) -> list[dict]:
    """단계별 진행(step+status+message+ts) — 어느 step 에서 실패했는지 재구성용."""
    out: list[dict] = []
    for line in logs or []:
        parsed = _step_of(line)
        if parsed:
            out.append(
                {
                    "step": parsed[0],
                    "status": parsed[1],
                    "message": line.get("message"),
                    "ts": line.get("ts"),
                }
            )
    return out


def _run_inputs(result: object) -> dict:
    """상세용 inputs — 사용자가 입력한 값. 완료된 대화형/AUTO 는 result(dict)에 담긴
    selections(+대화형 messages)를 회수한다. 실패/미완료(result=문자열)면 빈 목록."""
    if isinstance(result, dict):
        return {
            "selections": result.get("selections") or [],
            "messages": result.get("messages") or [],
        }
    return {"selections": [], "messages": []}


def _display_name(r: AgentRun) -> str | None:
    """실행자 표시명 — users.display_name(없으면 omnisol_userid 폴백)."""
    u = getattr(r, "user", None)
    if u is None:
        return None
    return u.display_name or u.omnisol_userid


def _run_summary(r: AgentRun) -> dict:
    return {
        "id": r.id,
        "agentId": r.agent_id,
        "userId": str(r.user_id),  # 로깅 뷰(관리자 전체)에서 실행 주체 식별용(안정 키).
        "userDisplayName": _display_name(r),  # 누가 실행했는지(users.display_name 조인).
        "status": r.status,
        "startedAt": r.started_at,
        "finishedAt": r.finished_at,
        "resultSummary": _result_summary(r.result),
        # 실패한 실행이면 마지막 실패 단계명(아니면 null) — 목록에서 실패지점 한눈에.
        "failedStep": _failed_step(r.logs) if r.status == "failed" else None,
    }


def _run_detail(r: AgentRun) -> dict:
    return {
        **_run_summary(r),
        "result": r.result,
        "inputs": _run_inputs(r.result),  # 무엇을 입력했는지(selections/messages)
        "steps": _run_steps(r.logs),  # 어느 단계에서 실패했는지(step+status)
        "logs": r.logs or [],
    }


def _template_dict(t: AgentTemplate) -> dict:
    return {
        "id": t.id,
        "agentId": t.agent_id,
        "name": t.name,
        "selections": t.selections or [],
        "createdAt": t.created_at,
    }


# ── 템플릿 CRUD(대화형 selections 저장·재생) ────────────────────────────────
# ⚠ 라우트 순서: GET /runs/templates 는 GET /runs/{run_id} 보다 먼저 선언해야
#   '/runs/templates' 가 {run_id} 로 잡히지 않는다(FastAPI 는 선언 순서로 매칭).
@router.post("/templates")
async def create_template(body: TemplateCreate, user: CurrentUser):
    """대화형 실행에서 누적한 selections 를 이름 붙여 저장. 소유자=현재 유저."""
    template_id = f"tpl-{uuid.uuid4().hex[:16]}"
    tpl = await store.create_template(
        template_id=template_id,
        agent_id=body.agentId,
        user_id=user.id,
        name=body.name,
        selections=body.selections,
    )
    return _template_dict(tpl)


@router.get("/templates")
async def list_templates(user: CurrentUser, agentId: str | None = None):
    """현재 유저의 템플릿 목록(최신순). agentId 로 워크플로우 필터."""
    tpls = await store.list_templates(user_id=user.id, agent_id=agentId)
    return {"templates": [_template_dict(t) for t in tpls]}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, user: CurrentUser):
    """소유자 스코프 삭제. 대상이 없거나 소유자 불일치면 404."""
    ok = await store.delete_template(template_id, user_id=user.id)
    if not ok:
        return JSONResponse({"error": "템플릿을 찾을 수 없습니다."}, status_code=404)
    return {"ok": True}


# ── 실행 이력(run history) 목록/상세 ────────────────────────────────────────
@router.get("")
async def list_runs(
    user: CurrentUser,
    page: PageQuery,
    agentId: str | None = None,
    status: str | None = None,
):
    """실행 이력(에이전트 사용 로깅, 최신순 요약). agentId 로 워크플로우, status 로 실행
    상태 필터.

    스코프: logs:read(관리자)는 전체 유저의 run 을, 그 외는 본인 것만 본다(감사와 달리
    로깅은 관리자가 전체를 봐야 보완 가능)."""
    # 수동 clamp(max(1,min(limit,100))) → PageQuery(범위 밖=422). 상한 100→200 · 기본 20→50 은
    # 의도된 통일 결정(docs/LIST-COMMONALIZATION.md — DEFAULT_LIMIT=50/MAX_LIMIT=200).
    # 관리자(logs:read)는 전체 조회(user_id=None), 일반 사용자는 소유 스코프.
    scope_user_id = None if user_has_permission(user, LOGS_READ) else user.id
    runs = await store.list_runs(
        user_id=scope_user_id,
        agent_id=agentId,
        status=status,
        limit=page.limit,
        offset=page.offset,
    )
    total = await store.count_runs(user_id=scope_user_id, agent_id=agentId, status=status)
    items = [_run_summary(r) for r in runs]
    # dual-key: 구 키(runs)와 표준 키(items)에 같은 목록 병기 — FE 전환 후 별도 커밋에서 구 키 제거 예정.
    return {
        "runs": items,
        "items": items,
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.get("/{run_id}")
async def get_run_detail(run_id: str, user: CurrentUser):
    """실행 상세(결과·inputs·steps·로그). 소유자 또는 logs:read 관리자만(로깅 뷰 일관성).
    그 외 사용자의 런은 404."""
    run = await store.get_run(run_id)
    if run is None:
        return JSONResponse({"error": "런을 찾을 수 없습니다."}, status_code=404)
    if str(run.user_id) != str(user.id) and not user_has_permission(user, LOGS_READ):
        return JSONResponse({"error": "런을 찾을 수 없습니다."}, status_code=404)
    return _run_detail(run)
