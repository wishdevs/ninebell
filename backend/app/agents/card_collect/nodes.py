"""법인카드 승인내역 정리(card-collect) — 카드팝업 이후 노드(진입 앞단은 expense_card 재사용).

체인: (login→user_type→menu_nav→set_gubun→add_row→open_evdn→select_evdn = expense_card 재사용)
→ select_all_cards → set_period(D2) → query(리스트 조회·표 보고) → collect_rows(항목 처리, Gemini
function-calling 대화) → save(최종 HITL 확인 후에만 F7).

state 계약: page/browser/events/userid/password/params(러너 주입). 실패는 {"error"} 로 남긴다.
⚠ 저장(F7)은 collect 완료 후 사용자가 HITL 로 '저장'을 택했을 때만. 그 외 저장 절대 금지.

collect_rows 는 ninebell-bak/expense_card.chat_form 과 동일한 패턴(사용자 자연어 → Gemini
function-calling → 도구 디스패치)을 쓴다 — 정규식 파서가 아니라 app.agents.expense_card.gemini.
gemini_chat_decide 가 사용자 의도를 판단한다(도구 스키마는 .tools.CARD_COLLECT_TOOLS).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any

import httpx

from app.agents.expense_card.gemini import gemini_chat_decide
from app.config import get_settings
from app.live.events import emit_chat, emit_log, emit_step, emit_transactions
from app.live.hitl import wait_hitl
from nbkit.patterns import emit_shot

from . import steps
from .tools import CARD_COLLECT_TOOLS

logger = logging.getLogger("app.agents.card_collect.nodes")

_MAX_TOOLS_PER_TURN = 12  # 한 사용자 턴 안에서 순차 실행할 도구 상한(expense_card.chat_form 과 동일).

# 코드피커 필드 스펙: 폼 id → (팝업 code 컬럼, name 컬럼). probe5~8 실측.
# ⚠ 순서 의존: 계정(acct_cd)은 예산단위 선택 후에야 목록이 채워진다(예산계정 연동). → 반드시
#   예산단위 → 계정 → 프로젝트 순서로 채운다(_apply_row_fields 의 튜플 순서 유지).
FIELD_SPEC: dict[str, dict[str, str]] = {
    "예산단위": {"id": "bg_cd", "code": "BG_CD", "name": "BG_NM"},
    "계정": {"id": "acct_cd", "code": "ACCT_CD", "name": "ACCT_NM"},
    "프로젝트": {"id": "pjt_cd", "code": "PJT_NO", "name": "PJT_NM"},
}


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _fmt_won(v: Any) -> str:
    try:
        return f"{int(str(v).replace(',', '')):,}원"
    except (ValueError, TypeError):
        return f"{v}원"


def recommend_note(tran_nm: str, amount: str) -> str:
    """가맹점명 기반 적요 초안 추천(휴리스틱 v1, 추후 Gemini 로 고도화)."""
    nm = tran_nm or ""
    rules = [
        (("식", "푸드", "요기요", "배달", "김밥", "곱창", "고기"), "식대(법인카드)"),
        (("주차", "파킹"), "주차료(법인카드)"),
        (("택시", "카카오T", "코레일", "고속", "항공", "대한항공", "아시아나"), "교통비(법인카드)"),
        (("주유", "에너지", "오일", "GS칼텍스", "SK에너지"), "차량 주유비(법인카드)"),
        (("네이버", "쿠팡", "11번가", "G마켓", "다이소", "코스트코", "이마트"), "소모품 구입(법인카드)"),
    ]
    for keys, note in rules:
        if any(k in nm for k in keys):
            return note
    return f"{nm} 사용" if nm else "법인카드 사용"


# ── 카드 전체선택 ────────────────────────────────────────────────────────────────
def make_select_all_cards_node():
    async def select_all_cards(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "select_all_cards", "running")
        t0 = time.monotonic()
        r = await steps.select_all_cards(page)
        if not r.get("ok"):
            await emit_step(events, "select_all_cards", "failed")
            return {"error": f"카드 전체선택 실패: {r.get('reason')}"}
        await emit_log(events, f"법인카드 {r.get('n')}장 전체선택·적용 완료.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "select_all_cards", "done", _ms(t0))
        return {}

    return select_all_cards


# ── 승인일 기간(D2) ──────────────────────────────────────────────────────────────
def make_set_period_node():
    async def set_period(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "set_period", "running")
        t0 = time.monotonic()
        params = state.get("params") or {}
        # 테스트/재현용 override 가능(params['today']=YYYY-MM-DD), 없거나 형식오류면 실제 오늘(리뷰 #12).
        today = date.today()
        raw_today = params.get("today")
        if raw_today:
            try:
                today = date.fromisoformat(str(raw_today))
            except (ValueError, TypeError):
                await emit_log(events, f"params.today 형식 오류({raw_today!r}) — 오늘 날짜로 진행.", "warn")
        start, end = steps.compute_period(today)
        r = await steps.set_period(page, start, end)
        if not r.get("ok"):
            await emit_step(events, "set_period", "failed")
            return {"error": f"승인일 기간 설정 실패({start}~{end}): {r}"}
        rule = "전월" if today.day < steps.DAY_CUTOFF else "당월"
        await emit_log(events, f"승인일 기간 = {start} ~ {end} ({rule} 규칙).", "info")
        await emit_step(events, "set_period", "done", _ms(t0))
        return {"period": [start, end]}

    return set_period


# ── 조회 + 리스트 표 보고 ─────────────────────────────────────────────────────────
def make_query_node():
    async def query(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "query", "running")
        t0 = time.monotonic()
        rows = await steps.run_query(page)
        if not isinstance(rows, int) or rows < 0:
            await emit_step(events, "query", "failed")
            return {"error": "조회에 실패했습니다(그리드 로딩 실패)."}
        lst = await steps.read_rows(page, limit=500)
        # 리스트 표 보고(승인일/가맹점명/승인액).
        columns = [
            {"key": "d", "header": "승인일"},
            {"key": "m", "header": "가맹점명"},
            {"key": "a", "header": "승인액", "align": "right"},
        ]
        table_rows = [
            {"d": r.get("TRAN_DT") or "", "m": r.get("TRAN_NM") or "", "a": _fmt_won(r.get("TRAN_AMT"))}
            for r in lst
        ]
        await emit_transactions(events, title=f"법인카드 승인내역 {rows}건", columns=columns, rows=table_rows)
        await emit_log(events, f"조회 완료 — 승인내역 {rows}건.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "query", "done", _ms(t0))
        return {"rows_list": lst}

    return query


# ── 리스트 표 / 항목 지정 파서 ─────────────────────────────────────────────────
def _md_cell(v: object) -> str:
    """마크다운 표 셀 안전화(파이프·개행 제거)."""
    return str(v or "").replace("|", "/").replace("\n", " ").strip()


def _full_table(rows: list[dict], recs: dict[int, str]) -> str:
    """전체 승인내역 마크다운 표(# · 승인일 · 가맹점명 · 승인액 · 추천 적요)."""
    head = "| # | 승인일 | 가맹점명 | 승인액 | 추천 적요 |\n|---:|---|---|---:|---|"
    lines = [head]
    for r in rows:
        i = r.get("i", 0)
        lines.append(
            f"| {i + 1} | {_md_cell(r.get('TRAN_DT'))} | {_md_cell(r.get('TRAN_NM'))} "
            f"| {_md_cell(_fmt_won(r.get('TRAN_AMT')))} | {_md_cell(recs.get(i, ''))} |"
        )
    return "\n".join(lines)


_STATUS_MARK = {"done": "✅ 반영", "skipped": "⏭️ 건너뜀", "pending": "· 대기"}


def _status_table(rows: list[dict], status: dict[int, str], notes: dict[int, str]) -> str:
    """처리 현황 마크다운 표(# · 가맹점명 · 승인액 · 적요 · 상태)."""
    head = "| # | 가맹점명 | 승인액 | 적요 | 상태 |\n|---:|---|---:|---|---|"
    lines = [head]
    for r in rows:
        i = r.get("i", 0)
        lines.append(
            f"| {i + 1} | {_md_cell(r.get('TRAN_NM'))} | {_md_cell(_fmt_won(r.get('TRAN_AMT')))} "
            f"| {_md_cell(notes.get(i, ''))} | {_STATUS_MARK.get(status.get(i, 'pending'))} |"
        )
    return "\n".join(lines)


# ── Gemini 시스템 프롬프트(ninebell-bak/expense_card.chat_form 과 동일 스타일) ────────────
# 행별 현재 상태(날짜·가맹점·상태·적요)는 시스템 프롬프트가 아니라 매 호출 "컨텍스트 데이터"로
# 넘긴다(gemini_chat_decide 의 context 인자) — 매 턴 바뀌는 값을 정적 프롬프트에 넣지 않는다.
_CC_SYSTEM = """당신은 더존 ERP 법인카드 승인내역을 정리하는 대화형 에이전트입니다.
사용자에게 이미 전체 승인내역 표(#·승인일·가맹점명·승인액·추천 적요)를 보여줬습니다.
사용자가 자연어로 특정 행(들)에 처리 지시를 내리면, 함께 전달되는 컨텍스트 데이터(행별 현재
상태)를 참고해 도구를 호출하세요.

[도구 사용 규칙]
- 행 번호는 표의 # 컬럼(1-based)입니다. 여러 행에 같은 값을 적용하려면 row_numbers 배열에 여러 번호를 담으세요.
- 예산단위·프로젝트를 말했으면(계정 언급 여부 무관) **apply_fields**. 계정은 보통 예산단위로
  자동 결정되니 사용자가 명시하지 않으면 account 를 비워 두세요(자동 처리됨) — 계정을 묻지 마세요.
- 적요만 바꾸고 싶다는 요청(예산단위/프로젝트 언급 없음)이면 **update_note**.
- '건너뛰어/스킵/제외/빼줘' 같은 표현은 **skip_rows**.
- '표/현황 다시 보여줘'는 **show_status**.
- 한 메시지에 여러 지시가 있으면(예: "1번은 예산단위 경영 프로젝트 공통, 3번은 건너뛰기") **도구를
  순서대로 여러 번 호출**해 그 메시지의 모든 지시를 처리한 뒤 turn_done 으로 마무리하세요.
- **하나의 지시를 도구로 한 번 처리했으면 그걸로 끝입니다.** 같은 지시에 대해 같은 도구를
  반복 호출하지 말고, 그 메시지의 모든 지시를 처리했으면 즉시 turn_done 을 호출하세요.
- 값이 불명확하거나 존재하지 않는 행 번호를 말하면 추측하지 말고 **ask** 로 되물으세요.
- **절대 대화를 스스로 종료하지 마세요.** 종료(저장 단계로 진행)는 사용자가 화면의 '선택 완료'
  버튼으로만 합니다(그런 종료용 도구는 없습니다).

[절대 금지]
- 저장(F7)·상신·전표생성·확정 액션은 이 대화에서 수행하지 않습니다(저장은 별도 확인 단계에서만).
"""


# ── 항목 처리(Gemini function-calling 대화): 전체 리스트 표 → 자연어로 항목별 처리 ────────
def make_collect_rows_node(timeout_s: int = 600):
    async def collect_rows(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        rows_list: list[dict] = state.get("rows_list") or []
        await emit_step(events, "collect_rows", "running")
        if not rows_list:
            period = state.get("period") or []
            period_txt = f"{period[0]} ~ {period[1]}" if len(period) == 2 else "이번 조회 기간"
            # 조회는 정상 실행됐지만 결과가 0건인 경우 — 채팅에 명확히 알린다(조용히 끝나면
            # 사용자가 '먹통'으로 오해하기 쉽다). 로그 탭 warn 만으론 부족(리뷰).
            await emit_chat(
                events,
                chat_id="cc-empty",
                role="assistant",
                content=f"{period_txt} 기간에 해당하는 법인카드 승인내역이 0건입니다. 처리할 항목이 없어 이대로 종료합니다.",
                streaming=False,
            )
            await emit_log(events, "처리할 승인내역이 없습니다.", "warn")
            await emit_step(events, "collect_rows", "done")
            return {"filled": 0}

        settings = get_settings()
        if not settings.gemini_api_key:
            await emit_step(events, "collect_rows", "failed")
            return {"error": "GEMINI_API_KEY 가 설정되지 않아 대화형 처리를 실행할 수 없습니다."}

        n = len(rows_list)
        recs = {r.get("i", idx): recommend_note(r.get("TRAN_NM") or "", r.get("TRAN_AMT") or "")
                for idx, r in enumerate(rows_list)}
        status: dict[int, str] = {r.get("i", idx): "pending" for idx, r in enumerate(rows_list)}
        notes = dict(recs)  # 최종 적용/예정 적요(적요 override 반영).

        def _context() -> dict:
            return {
                "rows": [
                    {
                        "no": r.get("i", idx) + 1,
                        "date": r.get("TRAN_DT"),
                        "merchant": r.get("TRAN_NM"),
                        "amount": _fmt_won(r.get("TRAN_AMT")),
                        "status": status[r.get("i", idx)],
                        "note": notes[r.get("i", idx)],
                    }
                    for idx, r in enumerate(rows_list)
                ]
            }

        # 1) 전체 리스트 표로 무엇이 있는지 먼저 보여준다.
        await emit_chat(
            events,
            chat_id="cc-list",
            role="assistant",
            content=(
                f"법인카드 승인내역 **{n}건**입니다. 자연어로 편하게 처리 방법을 말씀해 주세요.\n\n"
                + _full_table(rows_list, recs)
            ),
            streaming=False,
        )
        await emit_chat(
            events,
            chat_id="cc-howto",
            role="assistant",
            content=(
                "예: `1번 예산단위 경영, 프로젝트 공통으로 처리해줘` · `2,3번은 영업 예산에 프로젝트는 공통` · "
                "`4번은 건너뛰어` · `1번 적요는 6월 팀 회식으로 바꿔줘`\n다 되면 **선택 완료** 버튼을 눌러주세요."
            ),
            streaming=False,
        )

        filled = 0
        seq = 0

        async def _say(content: str, *, note: str | None = None, chat_id: str | None = None) -> None:
            nonlocal seq
            seq += 1
            await emit_chat(
                events,
                chat_id=chat_id or f"cc-turn-{seq}",
                role="assistant",
                content=content,
                streaming=False,
                note=note,
            )

        def _row_numbers(args: dict) -> list[int]:
            """1-based row_numbers → 유효한 0-based 인덱스 목록(정렬·중복제거)."""
            nums = args.get("row_numbers") or []
            idxs = {int(v) - 1 for v in nums if isinstance(v, (int, float)) and 0 <= int(v) - 1 < n}
            return sorted(idxs)

        def _sig(name: str, args: dict) -> tuple:
            """도구 호출 서명(중복 감지용) — 리스트는 정렬된 튜플로 고정."""
            def freeze(v: Any) -> Any:
                if isinstance(v, list):
                    return tuple(sorted(v, key=str))
                return v
            return (name, tuple(sorted((k, freeze(v)) for k, v in args.items())))

        http = httpx.AsyncClient(timeout=60.0)
        history = ""  # 세션 전체 누적(턴을 넘어 유지) — 매 호출은 최근 40줄만 잘라 보낸다.
        try:
            while True:
                try:
                    resp = await wait_hitl(
                        events,
                        kind="chat",
                        title="항목 처리",
                        prompt="자연어로 처리 방법을 입력하세요. 완료되면 화면의 '선택 완료' 버튼을 누르세요.",
                        timeout_s=timeout_s,
                    )
                except asyncio.TimeoutError:
                    await emit_step(events, "collect_rows", "failed")
                    return {"error": f"입력 대기 시간 초과({timeout_s // 60}분). 지금까지 {filled}건 반영(저장 전)."}

                if resp.get("done"):
                    break
                msg = (resp.get("message") or "").strip()
                if not msg:
                    continue

                history += f"\n사용자: {msg}"
                # 실측(라이브 Gemini): 같은 지시를 도구로 처리한 뒤 모델이 turn_done 대신 같은 도구를
                # 반복 호출하는 경우가 있었다(예: skip_rows 를 12회 연속). 프롬프트 지시만으론 신뢰할
                # 수 없어, 이번 턴 안에서 동일 (도구,인자) 서명이 재등장하면 재실행 없이 턴을 마친다.
                seen_actions: set[tuple] = set()
                for _ in range(_MAX_TOOLS_PER_TURN):
                    try:
                        name, args = await gemini_chat_decide(
                            http,
                            settings.gemini_api_key,
                            settings.gemini_model,
                            settings.gemini_base_url,
                            _CC_SYSTEM,
                            "\n".join(history.splitlines()[-40:]),  # 최근 40줄만(컨텍스트 비대 방지)
                            _context(),
                            None,  # 스크린샷 불필요 — 구조화 데이터만으로 판단.
                            CARD_COLLECT_TOOLS,
                        )
                    except Exception:  # noqa: BLE001 — graceful(노드가 죽지 않게)
                        logger.exception("card-collect gemini decide failed")
                        await _say("판단 호출에 실패했어요. 다시 한 번 말씀해 주세요.")
                        break

                    if not name:
                        await _say("이해하지 못했어요. 다시 말씀해 주세요.")
                        break

                    if name in {"skip_rows", "update_note", "apply_fields", "show_status"}:
                        sig = _sig(name, args)
                        if sig in seen_actions:
                            history += f"\n어시스턴트: ({name} 반복 감지 — 이미 처리됨, 이번 턴 종료)"
                            break
                        seen_actions.add(sig)

                    if name == "ask":
                        question = args.get("question") or "추가 정보를 알려주세요."
                        history += f"\n어시스턴트(ask): {question}"
                        await _say(question)
                        break

                    if name == "turn_done":
                        note_msg = args.get("message") or "처리했어요. 더 있으면 말씀하시고, 끝나면 완료 버튼을 눌러주세요."
                        history += f"\n어시스턴트(turn_done): {note_msg}"
                        await _say(note_msg)
                        break

                    if name == "show_status":
                        await _say("처리 현황:\n\n" + _status_table(rows_list, status, notes))
                        history += "\n어시스턴트(show_status): 표시함"
                        continue

                    if name == "skip_rows":
                        idxs = _row_numbers(args)
                        for ri in idxs:
                            status[ri] = "skipped"
                        msg_out = f"{', '.join(str(i + 1) for i in idxs)}번 건너뜀." if idxs else "유효한 행 번호를 찾지 못했습니다."
                        await _say(msg_out, note="action" if idxs else None)
                        history += f"\n어시스턴트(skip_rows {idxs}): 처리"
                        continue

                    if name == "update_note":
                        idxs = _row_numbers(args)
                        note = (args.get("note") or "").strip()
                        if not idxs or not note:
                            await _say("적요와 대상 행 번호를 확인해 주세요.")
                        else:
                            for ri in idxs:
                                notes[ri] = note
                            await _say(f"{', '.join(str(i + 1) for i in idxs)}번 적요 → '{note}'.", note="action")
                        history += f"\n어시스턴트(update_note {idxs}): 처리"
                        continue

                    if name == "apply_fields":
                        idxs = _row_numbers(args)
                        bg = (args.get("budget_unit") or "").strip()
                        acct = (args.get("account") or "").strip()
                        proj = (args.get("project") or "").strip()
                        note_override = (args.get("note") or "").strip()
                        if not idxs or not bg or not proj:
                            await _say("행 번호·예산단위·프로젝트를 확인해 주세요.")
                            history += "\n어시스턴트(apply_fields): 필수값 부족"
                            continue
                        for ri in idxs:
                            if note_override:
                                notes[ri] = note_override
                            collected = {"예산단위": bg, "계정": acct, "프로젝트": proj, "적요": notes[ri]}
                            ok, detail = await _apply_row_fields(page, events, ri, collected)
                            if ok:
                                filled += 1
                                status[ri] = "done"
                                await _say(f"{ri + 1}번 반영 완료 ({detail}).", note="action")
                            else:
                                await _say(f"{ri + 1}번 반영 실패: {detail}")
                            history += f"\n어시스턴트(apply_fields row={ri + 1}): {'ok' if ok else 'fail: ' + detail}"
                        await emit_shot(events.put, page)
                        continue

                    # 알 수 없는 도구명(모델 이탈) — graceful 처리.
                    await _say("처리할 수 없는 요청이에요. 다시 말씀해 주세요.")
                    break
                else:
                    await _say("요청하신 내용을 처리했어요. 더 있으면 말씀하시고, 끝나면 완료 버튼을 눌러주세요.")

                await _say("처리 현황:\n\n" + _status_table(rows_list, status, notes), chat_id="cc-status")
                if all(s != "pending" for s in status.values()):
                    await _say("모든 항목을 처리했습니다. **선택 완료** 버튼을 누르거나 값을 수정하세요.", chat_id="cc-alldone")
        finally:
            await http.aclose()

        await emit_log(events, f"항목 처리 완료 — {filled}건 반영(저장 전).", "ok")
        await emit_step(events, "collect_rows", "done")
        return {"filled": filled}

    return collect_rows


async def _apply_row_fields(
    page: Any, events: Any, row: int, collected: dict[str, str]
) -> tuple[bool, str]:
    """한 행에 적요(인라인) + 예산단위/계정/프로젝트(코드피커) 채우고 apply_row(일괄적용).

    반환 (ok, detail). detail 은 성공 시 **실제 선택된 이름**(사용자 입력이 아님, 리뷰 #1), 실패 시 사유.
    적요 세팅 실패는 치명(리뷰 #11) — 적요 없이 반영하지 않는다. 필드 순서(예산단위→계정→프로젝트)
    는 계정의 예산단위 의존 때문에 고정. 계정만 자동축소 단일 허용(allow_default).
    """
    note_res = await steps.set_note(page, row, collected["적요"])
    if not note_res.get("ok"):
        return False, f"적요 세팅 실패: {note_res.get('err') or note_res.get('reason')}"
    applied: list[str] = []
    for field in ("예산단위", "계정", "프로젝트"):
        spec = FIELD_SPEC[field]
        r = await steps.fill_codepicker(
            page, spec["id"], collected[field], spec["code"], spec["name"],
            allow_default=(field == "계정"),
        )
        if not r.get("ok"):
            return False, f"{field} '{collected[field]}': {r.get('reason')}"
        await emit_log(events, f"{field} = {r.get('name')} (code {r.get('code')})", "info")
        applied.append(f"{field} {r.get('name')}")
    ap = await steps.apply_row(page, row)
    if not ap.get("ok"):
        return False, f"일괄적용 실패: {ap.get('reason')}"
    return True, " / ".join(applied) + f" / 적요 '{collected['적요']}'"


# ── 저장(최종 HITL 확인 후에만) ───────────────────────────────────────────────────
def make_save_node():
    async def save(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 저장하지 않음: {state.get('error')}"}
        events = state["events"]
        page = state["page"]
        filled = state.get("filled", 0)
        await emit_step(events, "save", "running")
        if not filled:
            await emit_step(events, "save", "done")  # 스텝을 'pending' 에 멈추지 않는다(리뷰 #13).
            return {"result": "반영된 건이 없어 저장하지 않았습니다."}
        # 실 회계 반영이라 반드시 사용자 확인(choice) 후에만 F7.
        try:
            resp = await wait_hitl(
                events,
                kind="choice",
                title="결의서 저장 확인",
                prompt=f"{filled}건이 입력되었습니다. 결의서를 저장(F7)할까요? 저장 시 실제 전표가 생성됩니다.",
                options=[
                    {"value": "save", "label": "저장", "description": "실제 결의서 저장(F7)"},
                    {"value": "cancel", "label": "저장 안 함", "description": "입력만 유지, 저장 취소"},
                ],
            )
        except asyncio.TimeoutError:
            await emit_step(events, "save", "failed")
            return {"error": f"저장 확인 대기 시간 초과 — {filled}건 입력됨(저장 안 함)."}
        choice = (resp.get("value") or resp.get("message") or "").strip()
        if choice != "save":
            await emit_step(events, "save", "done")
            return {"result": f"{filled}건 입력 완료 — 사용자 선택으로 저장하지 않았습니다."}
        r = await steps.save_document(page, confirm=True)
        if not r.get("ok"):
            await emit_step(events, "save", "failed")
            return {"error": f"저장 실패: {r}"}
        await emit_log(events, f"결의서 저장 완료(F7, via {r.get('via')}).", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "save", "done")
        return {"result": f"{filled}건 입력·저장 완료."}

    return save
