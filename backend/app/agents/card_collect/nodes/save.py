"""최종 저장(F7) 노드 — ERP 거부 파싱·조치 안내·채팅 핸드오프(사용자 결정·화면 조작)."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
import uuid

from app.agents.common.llm import chat_decide, llm_ready
from app.config import get_settings
from app.core.http_client import new_async_client
from app.live.events import emit_chat, emit_hitl, emit_log, emit_step
from app.live.hitl import close_hitl_channel, open_hitl_channel
from nbkit.browser.actions import js_click
from nbkit.omnisol import selectors, verify
from nbkit.patterns import emit_shot

from .. import steps
from . import _shared

logger = logging.getLogger("app.agents.card_collect.nodes.save")

# 저장 실패 시 **자동 재시도 금지**(사용자 확정 2026-07-29) — 실패 사유를 채팅으로 보여주고
# 사용자 지시(채팅)로만 진행한다. 결정적 키워드는 LLM 없이 즉답하고, 그 외 지시는 LLM
# function-calling 으로 해석한다(화면 조작 도구 포함 — 사용자 요청 2026-07-29 2차).
_STOP_WORDS = ("종료", "그만", "중단", "취소", "포기", "stop")
_GRID_WORDS = ("다시시도", "재시도", "재입력", "그리드", "돌아가")

# 핸드오프 채팅 도구 — 화면 조작 도구는 실측 후 추가한다(관리항목 패널 프로브 진행 중).
_HANDOFF_TOOLS: list[dict] = [
    {
        "name": "save_now",
        "description": (
            "현재 화면 상태 그대로 저장(F7)을 다시 시도한다. 사용자가 '저장해줘/다시 저장/"
            "저장 다시 눌러봐' 등 저장 재시도를 지시하면 호출."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "retry_grid",
        "description": (
            "건별 입력 그리드로 돌아가 행별 예산단위·프로젝트·적요·제외를 다시 고른다"
            "(문서 재작성). '다시 시도/재입력/그리드로/처음부터' 지시 시 호출."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "stop",
        "description": "저장 없이 종료한다. '종료/그만/취소' 지시 시 호출.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "ask",
        "description": (
            "지시를 수행할 수 없거나(지원하지 않는 화면 조작 등) 정보가 더 필요할 때 "
            "사용자에게 상황을 설명하고 질문한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "사용자에게 보낼 설명/질문"}},
            "required": ["question"],
        },
    },
]

_HANDOFF_SYSTEM = (
    "너는 더존 옴니솔 '결의서입력' 화면에서 저장(F7)이 거부된 뒤 사용자의 조치를 돕는 "
    "도우미다. 문서 초안은 이 세션(헤드리스 브라우저)에만 있어 사용자가 자기 ERP 창에서 "
    "직접 고칠 수 없다. 사용자의 채팅 지시를 도구 1개로 처리하라. 저장 재시도는 save_now, "
    "건별 입력 그리드로 돌아가 재입력은 retry_grid, 종료는 stop. 아직 지원하지 않는 화면 "
    "조작을 지시하면 ask 로 무엇이 안 되는지와 대안(그리드 재입력으로 예산계정 변경·행 "
    "제외)을 설명하라."
)

# ERP 저장 거부 모달 파싱 — 승인번호·요구 계정을 뽑아 '어느 행을 어떤 계정으로' 안내한다.
# 예: "[승인번호 : 03187517, 승인취소] 승인 건 계정과 다릅니다. 세금과공과금-인사(과)와 동일해야 합니다."
_SAVE_APRVL_RE = re.compile(r"승인번호\s*[:：]\s*(\w+)")
_SAVE_REQ_ACCT_RE = re.compile(r"다릅니다[.\s]*(.+?)\s*와\s*동일")


def _parse_save_rejections(reason: str, rows_list: list[dict]) -> list[dict]:
    """ERP 저장 거부 메시지 → 조치 안내 리스트. 승인번호로 그리드 행(rowNo·가맹점)을 매핑한다.

    반환 [{aprvlNo, requiredAccount, rowNo, merchant, raw}] (파싱 실패분은 제외, 중복 승인번호 접기).
    형식이 달라 못 뽑으면 빈 리스트 — 호출부가 원문 폴백."""
    by_aprvl: dict[str, dict] = {r.get("APRVL_NO", "").lstrip("0"): r for r in rows_list if r.get("APRVL_NO")}
    idx_of = {id(r): i for i, r in enumerate(rows_list)}
    issues: list[dict] = []
    seen: set[str] = set()
    for seg in re.split(r"(?=\[?\s*승인번호)", reason or ""):
        seg = seg.strip()
        if not seg:
            continue
        m = _SAVE_APRVL_RE.search(seg)
        a = _SAVE_REQ_ACCT_RE.search(seg)
        aprvl = m.group(1) if m else None
        acct = a.group(1).strip() if a else None
        if not (aprvl or acct):
            continue
        key = f"{aprvl}|{acct}"
        if key in seen:
            continue
        seen.add(key)
        row = by_aprvl.get((aprvl or "").lstrip("0"))
        issues.append(
            {
                "aprvlNo": aprvl,
                "requiredAccount": acct,
                "rowNo": (idx_of.get(id(row)) + 1) if row is not None else None,
                "merchant": row.get("TRAN_NM") if row is not None else None,
                "raw": seg[:200],
            }
        )
    return issues


def _save_guidance(issues: list[dict], reason: str) -> str:
    """조치 안내 본문 — **왜 실패했고 무엇을 고칠지**. 계정 불일치는 어느 행을 어떤 계정으로,
    그 외 유형(필수값 미입력·적용 누락·일반 ERP 오류)은 사유별 구체 조치를 준다(블라인드 재시도 X).
    """
    if issues:
        lines = []
        for it in issues:
            where = (
                f"{it['rowNo']}행 「{it['merchant']}」"
                if it.get("rowNo")
                else f"승인번호 {it.get('aprvlNo') or '?'}"
            )
            if it.get("requiredAccount"):
                lines.append(
                    f"• {where}: 이 건은 예산계정이 **‘{it['requiredAccount']}’**와 같아야 합니다. "
                    f"그 계정에 해당하는 예산단위로 다시 선택해 주세요."
                )
            else:
                lines.append(f"• {where}: 계정이 맞지 않습니다. 예산단위를 다시 선택해 주세요.")
        return (
            "저장이 거부됐습니다 — 승인취소 건은 **원 승인 건과 같은 예산계정**이어야 합니다.\n"
            "아래 항목을 고쳐 다시 저장해 주세요:\n" + "\n".join(lines) +
            "\n\n다시 시도하면 표시된 행만 고치면 됩니다."
        )
    # 구조화되지 않은 거부 — 사유 문자열로 유형을 분류해 '무엇이 잘못됐고 무엇을 고칠지'를 준다.
    r = reason or ""
    if any(k in r for k in ("회계일이 마감", "마감되어", "마감된")):
        return (
            f"저장이 거부됐습니다 — **해당 회계일이 마감**되어 추가·수정·삭제할 수 없습니다.\n"
            f"(ERP 사유: {reason})\n\n"
            "이 건은 재시도해도 동일하게 거부됩니다. 옴니솔(회계) 관리자에게 **해당 월 마감 해제**를 "
            "요청하거나, 마감되지 않은 회계월로 처리해야 합니다."
        )
    if any(k in r for k in ("필수 값", "필수값", "입력되지 않은", "검증 실패")):
        return (
            f"저장이 거부됐습니다 — **필수값이 비어 있는 행**이 있습니다.\n(ERP 사유: {reason})\n\n"
            "각 행에 **프로젝트 등 필수값**을 채운 뒤 다시 저장해 주세요."
        )
    if "적용 단계" in r or "카드팝업" in r:
        return (
            f"저장이 완료되지 않았습니다 — **적용 단계가 누락**됐습니다(내부 오류).\n(사유: {reason})\n\n"
            "문서를 다시 만들어 재입력·적용 후 저장을 시도합니다."
        )
    return (
        f"저장이 ERP 에서 거부됐습니다:\n{reason}\n\n"
        "위 **사유**를 확인해 해당 항목(예산단위·계정·필수값 등)을 고친 뒤 다시 저장해 주세요."
    )


async def _attempt_save(state: dict, events, page) -> dict:
    """저장(F7) 1회 + 실저장 확인. 반환 {"status": "saved"|"terminal"|"failed", reason, issues}.

    saved = save_document ok + 재조회(F2) 문서 지속(판독 불가는 보류=saved 유지, 경고 로그).
    failed = ERP 거부(토스트·오류모달) 또는 팬텀(재조회 0건). terminal = 회계일 마감(재시도 무의미).

    양성 신호 근거(트립 실측 2026-07-07 + 프로브 2026-07-29): 결의번호(ABDOCU_NO)는 저장
    시점에 blank 라 신호가 아니고, F7 후 재조회에 문서가 지속하는 것이 확정 신호다. 하단
    검증 토스트(.dews-ui-snackbar, '관리항목[업무용차량] 미입력' 등)를 문구 매칭이 놓쳐도
    재조회 0건으로 잡힌다.
    """
    r = await steps.save_document(page, confirm=True)
    if not r.get("ok"):
        reason = r.get("reason") or str(r)
        issues = _parse_save_rejections(reason, state.get("rows_list") or [])
        status = "terminal" if r.get("closed_period") else "failed"
        return {"status": status, "reason": reason, "issues": issues}
    seen = r.get("modals_seen") or []
    if seen:
        await emit_log(
            events,
            "저장 중 확인창: "
            + " / ".join(f"[{m.get('title')}] {m.get('text', '')[:160]}" for m in seen[:3]),
            "info",
        )
    persisted = None
    try:
        await js_click(page, selectors.BTN_LOOKUP)  # 조회(F2)
        persisted = await verify.confirm_grid_rows(
            page,
            index=0,
            min_rows=1,
            timing=verify.HEAVY,
            unknown_when=lambda v: not isinstance(v, int) or v < 0,
        )
    except Exception as exc:  # noqa: BLE001 — 재조회 검증 실패는 저장 판정을 뒤집지 않는다(보류).
        await emit_log(events, f"저장 재조회 검증 보류(무시): {exc}", "warn")
    if persisted is not None and persisted.mismatch:  # 읽었는데 0건 = 서버에 문서 없음.
        reason = (
            "F7 후 재조회에 문서가 없습니다 — 실제 저장되지 않았습니다. 화면 하단 검증 "
            "메시지(예: 계정의 관리항목 미입력)로 저장이 거부됐을 가능성이 큽니다. "
            "관리항목을 요구하지 않는 예산계정(예산단위)으로 바꾸거나 해당 행을 제외해 보세요."
        )
        return {"status": "failed", "reason": reason, "issues": []}
    if persisted is not None and persisted.unknown:
        await emit_log(events, f"저장 재조회 검증 보류 — {persisted.reason}", "warn")
    elif persisted is not None:
        await emit_log(
            events, f"저장 양성 신호 확인 — 재조회 문서 지속(마스터 {persisted.actual}건).", "ok"
        )
    return {"status": "saved", "reason": "", "issues": []}


async def _handoff_save_failure(
    state: dict, events, page, *, reason: str, issues: list[dict], t0: float, success_text: str
) -> dict:
    """저장 실패 → 채팅 HITL 로 **사용자에게 키를 넘긴다**(자동 재시도 금지, 2026-07-29).

    결정적 키워드(저장/다시 시도/종료)는 즉답, 그 외 지시는 LLM function-calling 으로
    해석한다. '저장해줘'(save_now)는 **같은 화면에서 F7 재시도** — 사용자가 ERP 에서 직접
    필드(관리항목 등)를 고친 뒤 이어서 저장할 수 있다. 화면 조작 도구는 실측 후 추가 예정.
    타임아웃(hitl_timeout_s)이면 실패 종료.
    """
    retries = state.get("save_retries", 0)
    decision_id = uuid.uuid4().hex
    q = open_hitl_channel(decision_id, owner=state.get("owner"), run_id=state.get("run_id"))
    prompt = (
        "저장이 완료되지 않았습니다. 채팅으로 지시해 주세요.\n"
        "· **저장해줘** — 현재 화면 그대로 저장(F7) 재시도\n"
        "· **다시 시도** — 건별 입력 화면으로 돌아가 예산단위 변경·행 제외 후 재저장\n"
        "· **종료**(또는 완료 버튼) — 저장 없이 종료"
    )
    seq = 0
    guidance = _save_guidance(issues, reason)
    history = f"어시스턴트(저장 실패 안내): {guidance}\n"

    async def _say(content: str) -> None:
        nonlocal seq, history
        seq += 1
        history += f"어시스턴트: {content}\n"
        await emit_chat(
            events, chat_id=f"cc-savefail-{decision_id[:8]}-{seq}", role="assistant",
            content=content, streaming=False,
        )

    async def _fail_dict(msg: str | None = None) -> dict:
        await emit_step(events, "save_final", "failed")
        return {"error": msg or guidance, "retry_save": False}

    def _grid_dict() -> dict:
        return {
            "retry_save": True,
            "save_retries": retries + 1,
            "save_error_msg": reason,
            "save_error_issues": issues,
        }

    async def _save_now() -> dict | None:
        """같은 화면에서 F7 재시도. saved → 성공 dict, terminal → 실패 dict, 그 외 None(계속)."""
        nonlocal reason, issues, guidance
        await _say("저장(F7)을 다시 시도합니다…")
        att = await _attempt_save(state, events, page)
        if att["status"] == "saved":
            await _say("저장 완료를 확인했습니다.")
            return await _finish_saved(events, page, t0, success_text)
        if att["status"] == "terminal":
            return await _fail_dict(_save_guidance(att["issues"], att["reason"]))
        reason, issues = att["reason"], att["issues"]
        guidance = _save_guidance(issues, reason)
        await _say("여전히 저장되지 않았습니다.\n\n" + guidance + "\n\n" + prompt)
        return None

    settings = get_settings()
    try:
        await _say(guidance + "\n\n" + prompt)
        await emit_hitl(
            events, decision_id=decision_id, kind="chat",
            title="저장 실패 — 조치 선택", prompt=prompt, options=[],
        )
        await emit_log(events, "저장 실패 — 사용자 조치 대기(chat HITL, 자동 재시도 안 함).", "warn")
        async with new_async_client() as http:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=settings.hitl_timeout_s)
                except asyncio.TimeoutError:
                    return await _fail_dict(
                        f"저장 실패 후 조치 입력 대기 시간 초과({settings.hitl_timeout_s // 60}분).\n{guidance}"
                    )
                if msg.get("done"):
                    await _say("저장 없이 종료합니다.")
                    return await _fail_dict()
                text = str(msg.get("message") or "").strip()
                if not text:
                    continue
                await emit_log(events, f"사용자 입력: {text}", "info")
                history += f"사용자: {text}\n"
                t = text.replace(" ", "").lower()
                # 결정적 키워드 즉답(LLM 왕복 절약). '저장' 포함이면 저장 재시도가 우선 —
                # "다시 저장해줘"를 그리드 재입력으로 오해하지 않는다.
                if any(w in t for w in _STOP_WORDS):
                    await _say("저장 없이 종료합니다.")
                    return await _fail_dict()
                if "저장" in t:
                    out = await _save_now()
                    if out is not None:
                        return out
                    continue
                if any(w in t for w in _GRID_WORDS):
                    await _say("건별 입력 화면으로 돌아갑니다 — 수정 후 다시 저장을 시도합니다.")
                    await emit_step(events, "save_final", "failed")
                    return _grid_dict()
                # 그 외 지시 → LLM function-calling. LLM 미구성 시 안내만.
                if not llm_ready(settings):
                    await _say(
                        "죄송해요, 지금은 '저장해줘'·'다시 시도'·'종료'만 처리할 수 있어요"
                        "(LLM 미구성)."
                    )
                    continue
                try:
                    b64 = None
                    try:  # 스크린샷은 베스트에포트.
                        buf = await page.screenshot(type="jpeg", quality=45)
                        b64 = base64.b64encode(buf).decode()
                    except Exception:  # noqa: BLE001
                        b64 = None
                    name, args = await chat_decide(
                        http,
                        system=_HANDOFF_SYSTEM,
                        history="\n".join(history.splitlines()[-30:]),
                        context={"저장 실패 사유": reason},
                        shot_b64=b64,
                        tools=_HANDOFF_TOOLS,
                        settings=settings,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("save handoff chat_decide failed")
                    await _say("판단 호출에 실패했어요. '저장해줘'·'다시 시도'·'종료' 중 하나로 말씀해 주세요.")
                    continue
                if name == "save_now":
                    out = await _save_now()
                    if out is not None:
                        return out
                    continue
                if name == "retry_grid":
                    await _say("건별 입력 화면으로 돌아갑니다 — 수정 후 다시 저장을 시도합니다.")
                    await emit_step(events, "save_final", "failed")
                    return _grid_dict()
                if name == "stop":
                    await _say("저장 없이 종료합니다.")
                    return await _fail_dict()
                if name == "ask":
                    await _say(str(args.get("question") or "어떤 조치를 원하시는지 다시 말씀해 주세요."))
                    continue
                await _say("이해하지 못했어요 — '저장해줘'·'다시 시도'·'종료' 중 하나로 말씀해 주세요.")
    finally:
        close_hitl_channel(decision_id)


async def _finish_saved(events, page, t0: float, success_text: str) -> dict:
    """저장 성공 마무리 — 공용(첫 시도 성공·핸드오프 내 재시도 성공)."""
    await emit_log(events, "결의서 저장 시퀀스 완료(F7).", "ok")
    await emit_shot(events.put, page)
    await emit_step(events, "save_final", "done", _shared._ms(t0))
    return {"result": success_text, "retry_save": False}


def make_save_final_node():
    """최종 저장(F7) 1회 — 별도 확인 없음(사용자 업무 규칙: 그리드 '입력 완료' 제출이 곧
    저장까지의 승인이다). 반영 0건이면 저장하지 않는다.

    저장이 ERP 에서 거부되면(계정 불일치·관리항목 미입력 등) 자동 재시도 없이 채팅으로
    사유를 알리고 사용자 결정을 기다린다 — '다시 시도'를 선택한 경우에만 retry_save 를 켜서
    그래프가 menu_nav 로 되돌아가 문서를 새로 만들고 '건별 입력' 그리드부터 재입력한다.
    """

    async def save_final(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 저장하지 않음: {state.get('error')}", "retry_save": False}
        events = state["events"]
        page = state["page"]
        filled1 = state.get("filled", 0)
        filled2 = state.get("pass2_filled", 0)
        failed_n = state.get("pass1_failed", 0) + state.get("pass2_failed", 0)
        unmatched_n = state.get("pass2_unmatched", 0)
        # 매칭 실패(반영 누락)는 최종 결과에 반드시 노출한다(리뷰 HIGH #2).
        tail = f" · ⚠ 매칭 실패 {unmatched_n}건(수동 확인 필요)" if unmatched_n else ""
        if failed_n:
            tail += f" · ⚠ 행 반영 실패 {failed_n}건"
        total = filled1 + filled2
        await emit_step(events, "save_final", "running")
        t0 = time.monotonic()
        if not total:
            # 반영 0건: 조회 자체가 0건이면 정상 완료지만, 행 반영 **실패** 때문이라면
            # '처리 완료'로 위장하지 않고 실패로 보고한다(실전 2026-07-04: 40/40 실패가
            # '처리 완료 — 반영 0건'으로 성공 표시되던 문제).
            if failed_n:
                await emit_step(events, "save_final", "failed")
                return {"error": f"모든 행 반영 실패({failed_n}건) — 저장하지 않았습니다. 로그의 행별 실패 사유를 확인하세요.", "retry_save": False}
            await emit_step(events, "save_final", "done", _shared._ms(t0))
            return {"result": f"처리 완료 — 반영 0건(저장할 내용 없음){tail}.", "retry_save": False}
        # 과세/불공 어느 한쪽이 0건이면 그 패스는 생략된 것 — 나머지 반영분만으로 저장한다.
        await emit_log(events, f"과세 {filled1}건 · 불공 {filled2}건 반영 완료 — 저장(F7)을 진행합니다.", "info")
        success_text = f"처리 완료 — 과세 {filled1}건 · 불공 {filled2}건 입력·저장{tail}."
        att = await _attempt_save(state, events, page)
        if att["status"] == "saved":
            return await _finish_saved(events, page, t0, success_text)
        # 회계일 마감 등은 재시도로 못 고치는 확정 실패 — 채팅 핸드오프 없이 즉시 사유를 알린다.
        if att["status"] == "terminal":
            await emit_step(events, "save_final", "failed")
            return {"error": _save_guidance(att["issues"], att["reason"]), "retry_save": False}
        # 그 외 거부(계정 불일치·관리항목 미입력·팬텀 저장 등) — 자동 재시도 대신 사용자
        # 결정(채팅 핸드오프). 스텝은 결말(성공/그리드 재입력/종료)에서 마무리한다.
        return await _handoff_save_failure(
            state, events, page,
            reason=att["reason"], issues=att["issues"], t0=t0, success_text=success_text,
        )

    return save_final
