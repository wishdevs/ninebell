"""대화형 폼 채움 노드 — 카드상세 모달의 '나머지 필드'를 자연어로 채운다.

ninebell-bak `erp/graph.py` 의 `make_chat_form_node`(+`_CARD_FORM_SCHEMA_JS`/`_READ_TX_JS`/
`_MODAL_IDLE_JS`/`_CHAT_SYSTEM_TMPL`)을 이 엔진의 이벤트/HITL 계약에 맞게 이식했다.

흐름: 모달 로딩 대기 → 필드 스키마 선행학습 → (턴 반복) chat HITL 로 사용자 메시지 수신
→ Gemini 비전 function-calling 한 턴 → 도구 디스패치(fill_search/fill_dropdown/fill_text/
set_expense/read_transactions/ask/turn_done) → chat/transactions 이벤트 스트림 → 성공한 fill 을
ChatSelection 으로 누적. 종료는 오직 사용자의 '선택 완료'(hitl done=true) 신호로만.

⚠ 저장(F7)·상신·전표생성 절대 금지 — 모달 '적용'까지만.
멀티턴 입력은 app.live.hitl.wait_hitl(kind='chat') 을 턴마다 호출해 받는다(단발 대기의 반복).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any

import httpx

from app.config import get_settings
from app.live.events import emit_chat, emit_hitl, emit_log, emit_step, emit_transactions

# 대화형(chat) HITL 은 하나의 decision_id 에 사용자 메시지를 여러 번 + '선택 완료' 1번 받는다
# (resolve_hitl 이 같은 큐로 여러 턴을 전달 — app.live.hitl 설계). wait_hitl 은 단발이라
# 여기선 엔진의 chat-HITL 큐(_hitl_queues)에 직접 등록해 멀티턴을 받는다. 소유권(_hitl_owner)은
# LiveSession 이 hitl 프레임을 보며 등록하고, 종료 시 여기서 정리한다.
from app.live.hitl import _hitl_owner, _hitl_queues
from nbkit.patterns import emit_shot

from .domain import remark_for
from .gemini import gemini_chat_decide
from .tools import (
    SCAFFOLD_DROPDOWN_FIELDS,
    SCAFFOLD_SEARCH_FIELDS,
    SCAFFOLD_TEXT_FIELDS,
    VERIFIED_FIELDS,
    do_account,
    do_budget,
    do_fill_dropdown,
    do_fill_search,
    do_fill_text,
)

logger = logging.getLogger("app.agents.expense_card.chat_form")

_MAX_TOOLS_PER_TURN = 12  # 한 사용자 턴 안에서 순차 실행할 도구 상한(연속 fill 방지 상한).


# 카드 상세 모달의 채울 수 있는 필드(코드피커/드롭다운/텍스트)를 선행학습한다.
CARD_FORM_SCHEMA_JS = """() => {
  try {
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const root = wins.length ? wins[wins.length - 1] : document.body;
    const clean = s => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim().slice(0, 24);
    const pickers = [];
    [...root.querySelectorAll('button.dews-codepicker-button')].filter(b => b.offsetParent !== null).forEach(b => {
      const br = b.getBoundingClientRect();
      let lbl = '', bd = 1e9;
      [...root.querySelectorAll('label,span,div,th')].forEach(e => {
        if (e.offsetParent === null) return; const t = clean(e.innerText); if (!t || t.length > 12) return;
        const r = e.getBoundingClientRect();
        if (Math.abs(r.top - br.top) < 22 && r.left < br.left) { const dx = br.left - r.left; if (dx < bd) { bd = dx; lbl = t; } }
      });
      if (lbl) pickers.push(lbl);
    });
    const drops = [];
    [...root.querySelectorAll('select')].filter(s => s.offsetParent !== null || true).forEach(s => {
      const id = s.id || ''; const opts = [...s.options].map(o => clean(o.text)).filter(Boolean).slice(0, 12);
      if (opts.length) drops.push({ id, options: opts });
    });
    const inputs = [];
    [...root.querySelectorAll('input')].filter(i => i.offsetParent !== null && i.type !== 'hidden').forEach(i => {
      const id = i.id || ''; const ph = clean(i.placeholder); const type = i.type || 'text';
      if (/codepicker|search_key/.test(id)) return;
      inputs.push({ id, placeholder: ph, type });
    });
    return { ok: true, pickers: [...new Set(pickers)], drops, inputs, root: wins.length ? 'modal' : 'document' };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 60) }; }
}"""

# 하단 법인카드 거래 그리드(gi=0) 전체 행을 읽는다. 카드 선택+조회 전엔 0건.
READ_TX_JS = """() => {
  try {
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const root = wins.length ? wins[wins.length - 1] : document;
    const els = [...root.querySelectorAll('.dews-ui-grid')];
    if (!els.length) return { n: 0, rows: [] };
    const g = window.jQuery(els[0]).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount();
    const rows = n ? ds.getJsonRows(0, n - 1) : [];
    const s = v => (v == null || v === 'null') ? '' : String(v).trim();
    return { n, rows: rows.map((r, i) => ({
      idx: i, key: s(r.__UUID) || ('tx-' + i),
      가맹점: s(r.TRAN_NM), 승인일: s(r.TRAN_DT).slice(0, 10),
      승인액: s(r.TRAN_AMT) || s(r.SUM_AMT), 공급가액: s(r.SPPRC_AMT), 적요: s(r.NOTE_DC)
    })) };
  } catch (e) { return { n: 0, rows: [], err: String(e).slice(0, 60) }; }
}"""

# 카드 모달 로딩 오버레이(dews 진행 바/마스크)가 걷혔는지 — 보이면 false(아직 로딩 중).
MODAL_IDLE_JS = """() => {
  try {
    const prog = [...document.querySelectorAll('.dews-ui-progress, .dews-progress-wrapper, .dews-progress-bar, [class*="dews-progress"]')]
      .filter(e => e.offsetParent !== null);
    if (prog.length) return false;
    const masks = [...document.querySelectorAll('.k-loading-mask, .k-overlay')]
      .filter(e => e.offsetParent !== null);
    return masks.length === 0;
  } catch (e) { return true; }
}"""


_CHAT_SYSTEM_TMPL = """당신은 더존 ERP 법인카드 지출 카드상세 모달의 '나머지 필드'를 채우는 대화형 폼 에이전트입니다.
증빙유형·프로젝트는 이전 단계에서 이미 처리됐습니다(또는 채팅 중 프로젝트는 fill_search 로 처리).
사용자가 자연어 한 문장으로 여러 필드를 말하면, 매핑해서 도구 호출로 화면을 조작하세요.

[채울 수 있는 필드 — 현재 모달에서 선행학습한 스키마]
{schema}

[필드 채우는 법(도구 선택 규칙)]
- 코드피커(돋보기) 검색형 필드 → fill_search(field, query?, value). 예: 프로젝트·거래처·계정·예산계정·예산단위·비용센터·사업계획·사용자.
  · '프로젝트'는 검증된 경로(라이브 확인). 그 외 코드피커 필드는 **미검증(스캐폴드)** — 베스트에포트로 시도하고, 실패하면 ask 로 안내하세요.
- Kendo 드롭다운 → fill_dropdown(field, value). 예: 처리여부·승인구분·부가세구분·봉사료. **미검증(스캐폴드).**
- 텍스트/날짜/카드번호 → fill_text(field, value). 예: 적요·카드번호·승인일. **미검증(스캐폴드).**
- 부가세는 보통 '부가세구분' 드롭다운에서 '공제'/'불공제' 로 선택합니다.

[법인카드 지출 — 사용항목/순서 규칙]
- 사용자가 사용항목(야근식대·휴일식대·회식·국내출장·주차료·해외출장·유류·업무추진비·사무용품비·접대비·해외접대비·대리운전비·하이패스·중식식대·직원조식·직원간식·우편물발송)을 말하면 **set_expense(use_item)** 로 예산단위+적요를 한 번에 채우세요(검증: 야근식대만 라이브 확인).
- set_expense 가 'ambiguous: 제조/판매 중?' 을 반환하면 ask 로 물어보고, 답을 받아 **set_expense(use_item, division='제조' 또는 '판매')** 로 재호출하세요.
- **입력 순서: 예산단위 → 계정 → 프로젝트 → 적요.** set_expense 가 **예산단위·계정·적요를 자동** 처리합니다 — **계정은 절대 사용자에게 묻지 마세요**(예산단위 세팅 시 자동축소된 계정이 자동 선택됨). 프로젝트만 fill_search 로 받으세요.

[도구 사용 규칙]
- 사용자가 '내역/거래/리스트 보여줘, 뭐 있어' 처럼 **거래 목록을 물으면 read_transactions** 로 표를 보여주세요(읽기 전용, 값 안 채움).
- 한 메시지에 여러 필드/항목이 있으면 **도구를 순서대로 여러 번 호출**해 그 메시지의 모든 항목을 처리하세요. 그 메시지를 다 처리했으면 turn_done 으로 마무리하세요.
- 값이 불명확/누락이면 추측하지 말고 ask 로 되물으세요.
- 이번 요청의 필드를 다 처리했으면 turn_done(message) 으로 짧게 안내하고 다음 입력을 기다리세요.
- **절대 대화를 스스로 종료하지 마세요.** 종료(전송 완료)는 사용자가 화면의 '선택 완료' 버튼으로만 합니다(finish 같은 종료 도구는 없습니다).
- 사용자가 이전 선택을 바꾸려 하면(예: '프로젝트를 ~로 변경해줘') 해당 필드를 다시 fill 하세요 — 같은 필드는 최신값으로 갱신됩니다.

[절대 금지]
- 저장(F7)·상신·전표생성·확정 액션 절대 금지. 모달 '적용'까지만. 당신의 도구는 적용까지만 수행합니다.
"""

_CHAT_PROMPT = (
    "카드 상세의 나머지 필드를 한 문장으로 말씀해 주세요. "
    "예: '프로젝트 SPARES_ACM, 부가세 공제, 카드번호 1234, 적요 출장비'. "
    "프로젝트는 검증됐고, 나머지 필드는 미검증(시범)입니다. 저장은 하지 않습니다. "
    "끝나면 '선택 완료'를 눌러주세요."
)


async def _wait_modal_idle(page: Any, timeout_ms: int = 15000) -> bool:
    """카드 모달의 로딩 오버레이가 걷힐 때까지 폴링 대기(고정 딜레이 대신 화면 상태)."""
    await page.wait_for_timeout(700)  # 진행 오버레이가 나타날 짧은 여유
    waited = 700
    step = 400
    while waited < timeout_ms:
        try:
            if await page.evaluate(MODAL_IDLE_JS):
                await page.wait_for_timeout(300)  # 잔여 렌더 안정화
                if await page.evaluate(MODAL_IDLE_JS):  # 한 번 더(다시 안 뜨는지)
                    return True
        except Exception:
            pass
        await page.wait_for_timeout(step)
        waited += step
    return False


def make_chat_form_node(timeout_s: int = 600):
    """대화형 폼 채움 노드 팩토리. timeout_s = 사용자 입력 한 턴 대기 상한(초)."""

    async def chat_form(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "chat_form", "running")

        # 카드 모달 로딩 오버레이가 걷힐 때까지 대기 → 로딩 화면 캡처/조작 방지.
        await _wait_modal_idle(page)

        settings = get_settings()
        if not settings.gemini_api_key:
            await emit_step(events, "chat_form", "failed")
            return {"error": "GEMINI_API_KEY 가 설정되지 않아 대화형 폼 에이전트를 실행할 수 없습니다."}

        # 1) 카드 상세 모달 필드 선행학습.
        schema = await page.evaluate(CARD_FORM_SCHEMA_JS)
        if not (schema or {}).get("ok"):
            schema = {"ok": False, "pickers": [], "drops": [], "inputs": []}
            await emit_log(events, "카드 모달 필드 스키마 선행학습 실패 — 알려진 필드 목록으로 대체.", "warn")
        # 검증/미검증 표기를 스키마에 부착(거짓 검증 주장 방지).
        schema["검증된_필드"] = sorted(VERIFIED_FIELDS)
        schema["미검증_검색필드"] = SCAFFOLD_SEARCH_FIELDS
        schema["미검증_드롭다운"] = SCAFFOLD_DROPDOWN_FIELDS
        schema["미검증_텍스트"] = SCAFFOLD_TEXT_FIELDS
        system = _CHAT_SYSTEM_TMPL.replace("{schema}", json.dumps(schema, ensure_ascii=False, indent=2))

        http = httpx.AsyncClient(timeout=60.0)
        chat_prefix = uuid.uuid4().hex  # 이 노드 인스턴스의 채팅 id 접두(FE upsert 키 안정화).
        history = ""
        selections: list[dict] = []  # 성공한 fill 을 ChatSelection 으로 누적(필드별 최신값만).
        seq = 0
        pending_budget: str | None = None  # set_expense 가 제/판 모호로 물어본 직전 사용항목.

        def _summary() -> str:
            return ", ".join(f"{s['field']}={s['value']}" for s in selections) or "채운 필드 없음"

        async def _say(content: str, *, done: bool = False, note: str | None = None) -> None:
            # 각 어시스턴트 말풍선은 고유 id — FE 가 id upsert 라 동일 id면 말풍선이 합쳐진다.
            nonlocal seq
            seq += 1
            await emit_chat(
                events,
                chat_id=f"{chat_prefix}-{seq}",
                role="assistant",
                content=content,
                streaming=False,
                done=done,
                note=note,
            )

        async def _apply_budget(use_item: str, division: str) -> str:
            """set_expense — 예산단위 + 계정(자동축소) + 적요(규칙)를 한 번에. 반환 status."""
            nonlocal pending_budget, history
            try:
                status, bmsg = await do_budget(page, use_item, division)
            except Exception as exc:  # noqa: BLE001 — graceful(노드가 죽지 않게)
                logger.warning("set_expense 예외: %s", use_item, exc_info=True)
                status, bmsg = "fail", f"예산단위 처리 예외: {str(exc)[:60]}"
            await _say(("ok: " if status == "ok" else status + ": ") + bmsg, note="action")
            history += f"어시스턴트(set_expense {use_item} {division}): {status} {bmsg}\n"
            if status == "ok":
                pending_budget = None
                selections[:] = [s for s in selections if s.get("field") != "예산단위"]
                # division(제조/판매)을 query 에 저장 → 재현 시 do_budget 로 복원.
                selections.append(
                    {"tool": "set_expense", "field": "예산단위", "value": use_item, "query": division}
                )
                # 계정: 예산단위 후 자동축소된 계정을 무조건 자동 선택(묻지 않음).
                try:
                    astatus, amsg = await do_account(page)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("계정 자동선택 예외", exc_info=True)
                    astatus, amsg = "fail", f"계정 예외: {str(exc)[:50]}"
                await _say(("ok: " if astatus == "ok" else "warn: ") + amsg, note="action")
                if astatus == "ok":
                    selections[:] = [s for s in selections if s.get("field") != "계정"]
                    selections.append({"tool": "set_account", "field": "계정", "value": "자동"})
                # 적요: 규칙 템플릿.
                remark = remark_for(use_item)
                ract = await do_fill_text(page, "적요", remark)
                await _say(ract, note="action")
                if ract.startswith("ok"):
                    selections[:] = [s for s in selections if s.get("field") != "적요"]
                    selections.append({"tool": "fill_text", "field": "적요", "value": remark})
                await _say(f"'{use_item}' → 예산단위·계정·적요 설정 완료. 프로젝트를 이어서 입력하세요.")
            elif status == "ambiguous":
                pending_budget = use_item
                await _say(bmsg)
            else:
                pending_budget = None
                await _say(bmsg)
            await emit_shot(events.put, page)
            return status

        # chat HITL 오픈 — 하나의 decision_id 로 멀티턴(사용자 메시지 여러 번 + '선택 완료' 1번).
        # 소유권은 LiveSession 이 이 hitl 프레임을 보며 등록한다(/runs/hitl 격리).
        decision_id = uuid.uuid4().hex
        q: asyncio.Queue = asyncio.Queue()
        _hitl_queues[decision_id] = q
        await emit_hitl(
            events,
            decision_id=decision_id,
            kind="chat",
            title="지출 상세 입력",
            prompt=_CHAT_PROMPT,
            options=[],
        )
        await emit_log(events, "대화형 폼 입력 대기 중(chat HITL) — 사용자 메시지를 기다립니다.", "info")
        await emit_shot(events.put, page)

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=timeout_s)
                except asyncio.TimeoutError:
                    await emit_step(events, "chat_form", "failed")
                    return {
                        "error": f"대화형 폼 입력 대기 시간 초과({timeout_s // 60}분). 다시 실행해 주세요."
                    }

                # 종료는 사용자가 '선택 완료'(done)를 눌렀을 때만. 에이전트는 스스로 끝내지 않는다.
                if msg.get("done"):
                    summary = _summary()
                    await _say(f"선택을 완료했습니다 — {summary}", done=True)
                    await emit_log(events, f"대화형 폼 완료(사용자 '선택 완료') — {summary} (저장 안 함)", "ok")
                    await emit_shot(events.put, page)
                    await emit_step(events, "chat_form", "done")
                    return {"result": f"대화형 폼 완료: {summary} (적용까지만, 저장·상신 안 함)"}

                user_text = (msg.get("message") or "").strip()
                if not user_text:
                    continue
                history += f"사용자: {user_text}\n"

                # 예산단위 제/판 모호로 물어본 상태면 '제조/판매' 답을 Gemini 없이 직접 처리.
                if pending_budget:
                    _t = user_text.replace(" ", "")
                    _div = (
                        "제조" if ("제조" in _t or _t == "제")
                        else ("판매" if ("판매" in _t or _t == "판") else "")
                    )
                    if _div:
                        await _apply_budget(pending_budget, _div)
                        continue

                # 한 사용자 턴 안에서 Gemini 가 ask/turn_done 을 낼 때까지 도구를 순차 실행.
                for _t2 in range(_MAX_TOOLS_PER_TURN):
                    try:
                        b64: str | None = None
                        try:  # 스크린샷은 베스트에포트(없어도 텍스트 스키마로 판단 가능).
                            buf = await page.screenshot(type="jpeg", quality=45)
                            b64 = base64.b64encode(buf).decode()
                        except Exception:  # noqa: BLE001
                            b64 = None
                        name, args = await gemini_chat_decide(
                            http,
                            settings.gemini_api_key,
                            settings.gemini_model,
                            settings.gemini_base_url,
                            system,
                            "\n".join(history.splitlines()[-40:]),  # 최근 40줄만(컨텍스트 비대 방지)
                            schema,
                            b64,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("chat gemini decide failed")
                        await _say("판단 호출에 실패했어요. 다시 한 번 말씀해 주세요.")
                        break

                    if not name:
                        await _say("어떤 필드를 채울지 이해하지 못했어요. 다시 말씀해 주세요.")
                        break

                    if name == "ask":
                        question = args.get("question") or "추가 정보를 알려주세요."
                        history += f"어시스턴트(ask): {question}\n"
                        await _say(question)
                        break  # 다음 사용자 메시지 대기

                    if name == "turn_done":
                        note_msg = (
                            args.get("message")
                            or "처리했어요. 더 추가하거나 수정할 게 있으면 말씀하시고, 끝나면 '선택 완료'를 눌러주세요."
                        )
                        if selections:
                            note_msg += f" (현재 채운 필드: {_summary()})"
                        history += f"어시스턴트(turn_done): {note_msg}\n"
                        await _say(note_msg)
                        break  # 대화는 종료하지 않음 — 사용자 다음 입력/'선택 완료'를 기다린다.

                    if name == "read_transactions":
                        try:
                            res = await page.evaluate(READ_TX_JS)
                        except Exception as exc:  # noqa: BLE001
                            res = {"n": 0, "rows": [], "err": str(exc)[:60]}
                        raw = res.get("rows") or []
                        n = res.get("n", len(raw))
                        cols = [
                            {"key": "번호", "header": "No"},
                            {"key": "가맹점", "header": "가맹점명"},
                            {"key": "승인일", "header": "승인일"},
                            {"key": "승인액", "header": "승인액", "align": "right"},
                            {"key": "적요", "header": "적요"},
                        ]
                        rows = [
                            {
                                "번호": i + 1,
                                "가맹점": r.get("가맹점", ""),
                                "승인일": r.get("승인일", ""),
                                "승인액": r.get("승인액", ""),
                                "적요": r.get("적요", ""),
                            }
                            for i, r in enumerate(raw)
                        ]
                        await emit_transactions(events, title="법인카드 내역", columns=cols, rows=rows)
                        history += f"어시스턴트(read_transactions): {n}건\n"
                        if n:
                            await _say(
                                f"법인카드 내역 {n}건을 읽었어요(아래 표). 각 거래의 예산단위·계정·프로젝트·적요를 행 번호로 말씀해 주세요."
                            )
                        else:
                            await _say(
                                "현재 거래 내역이 0건입니다. 카드번호를 선택하고 '조회'해야 거래가 표시됩니다(테스트 계정엔 거래가 없을 수 있어요)."
                            )
                        await emit_shot(events.put, page)
                        break  # 다음 사용자 메시지 대기

                    if name == "set_expense":
                        st = await _apply_budget(
                            (args.get("use_item") or "").strip(),
                            (args.get("division") or "").strip(),
                        )
                        if st == "ambiguous":
                            break  # 제/판 답을 기다린다.
                        continue  # ok/실패 → 같은 메시지의 다음 항목을 이어서 처리.

                    # fill_* 도구 디스패치 — 예외는 잡아 graceful 처리.
                    field = (args.get("field") or "").strip()
                    value = (args.get("value") or "").strip()
                    try:
                        if name == "fill_search":
                            action = await do_fill_search(page, field, (args.get("query") or "").strip(), value)
                        elif name == "fill_dropdown":
                            action = await do_fill_dropdown(page, field, value)
                        elif name == "fill_text":
                            action = await do_fill_text(page, field, value)
                        else:
                            action = f"unknown-tool: {name}"
                    except Exception as exc:  # noqa: BLE001
                        action = f"error(미검증 가능): {field} 처리 중 예외 — {str(exc)[:60]}"

                    if action.startswith("ok"):
                        # 성공한 fill 을 구조화 selection 으로 누적. 같은 필드는 최신값으로 갱신.
                        sel: dict = {"tool": name, "field": field, "value": value}
                        if name == "fill_search":
                            sel["query"] = (args.get("query") or "").strip()
                        selections[:] = [s for s in selections if s.get("field") != field]
                        selections.append(sel)
                    history += f"어시스턴트({name} {field}={value}): {action}\n"
                    await emit_log(events, f"[chat_form] {action}", "info")
                    await _say(action, note="action")
                    await emit_shot(events.put, page)
                    # 같은 사용자 턴의 추가 필드 처리로 루프 계속.
                else:
                    # for 가 break 없이 상한 소진(연속 fill)된 경우만 — 무응답 방지 안내.
                    await _say(
                        "요청하신 필드를 처리했어요. 더 추가/수정할 게 있으면 말씀하시고, 끝나면 '선택 완료'를 눌러주세요."
                    )
        finally:
            _hitl_queues.pop(decision_id, None)
            _hitl_owner.pop(decision_id, None)
            await http.aclose()

    return chat_form
