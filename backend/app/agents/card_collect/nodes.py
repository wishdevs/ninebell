"""법인카드 승인내역 정리(card-collect) — 카드팝업 이후 노드(진입 앞단은 expense_card 재사용).

체인: (login→user_type→menu_nav→set_gubun→add_row→open_evdn→select_evdn = expense_card 재사용)
→ select_all_cards → set_period(D2) → query(리스트 조회·표 보고) → collect_rows(행별 HITL 루프)
→ save(최종 HITL 확인 후에만 F7).

state 계약: page/browser/events/userid/password/params(러너 주입). 실패는 {"error"} 로 남긴다.
⚠ 저장(F7)은 collect 완료 후 사용자가 HITL 로 '저장'을 택했을 때만. 그 외 저장 절대 금지.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date
from typing import Any

from app.live.events import emit_chat, emit_log, emit_step, emit_transactions
from app.live.hitl import wait_hitl
from nbkit.patterns import emit_shot

from . import steps

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


def _parse_fields(msg: str) -> dict[str, str]:
    """사용자 메시지에서 예산단위/계정/프로젝트/적요 추출(‘필드 값’·‘필드=값’·‘필드: 값’).

    라벨은 **구분자로 둘러싸인 경계 위치**에서만 필드 마커로 인정한다(값 안에 라벨 단어가 들어가도
    오분배 방지, 리뷰 #3). 적요는 자유텍스트라 그 마커 이후 **문자열 끝까지** 취하고, 적요 마커
    뒤에 나오는 다른 라벨은 적요 값의 일부로 본다(무시).
    """
    labels = ["예산단위", "계정", "프로젝트", "적요"]
    text = msg
    marks: list[tuple[int, int, str]] = []
    for lb in labels:
        for m in re.finditer(r"(?:^|(?<=[\s,·\n]))" + re.escape(lb) + r"(?=[\s:=]|$)", text):
            marks.append((m.start(), m.end(), lb))
            break  # 라벨당 첫 경계 마커만.
    marks.sort()
    note_pos = next((s for s, _e, lb in marks if lb == "적요"), None)
    if note_pos is not None:
        marks = [t for t in marks if t[2] == "적요" or t[0] < note_pos]
    out: dict[str, str] = {}
    strip_chars = " ,·:=\t\n"
    for idx, (_s, e, lb) in enumerate(marks):
        if lb == "적요":
            val = text[e:].strip(strip_chars)
        else:
            nxt = marks[idx + 1][0] if idx + 1 < len(marks) else len(text)
            val = text[e:nxt].strip(strip_chars)
        if val:
            out[lb] = val
    return out


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


# ── 행별 입력 루프(HITL) ─────────────────────────────────────────────────────────
def make_collect_rows_node(timeout_s: int = 600):
    async def collect_rows(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        rows_list: list[dict] = state.get("rows_list") or []
        await emit_step(events, "collect_rows", "running")
        if not rows_list:
            await emit_log(events, "처리할 승인내역이 없습니다.", "warn")
            await emit_step(events, "collect_rows", "done")
            return {"filled": 0}

        filled = 0
        seq = 0
        for row in rows_list:
            i = row.get("i", 0)
            nm = row.get("TRAN_NM") or ""
            when = row.get("TRAN_DT") or ""
            amt = _fmt_won(row.get("TRAN_AMT"))
            rec = recommend_note(nm, row.get("TRAN_AMT") or "")
            collected: dict[str, str] = {"적요": rec}
            # 이 행이 완성될 때까지 대화(부족하면 재요청, '건너뛰기'면 skip).
            while True:
                seq += 1
                await emit_chat(
                    events,
                    chat_id=f"row-{i}-{seq}",
                    role="assistant",
                    content=(
                        f"[{i + 1}/{len(rows_list)}] {when} · {nm} · {amt}\n"
                        f"추천 적요: '{collected['적요']}'.\n"
                        "예산단위·계정·프로젝트를 알려주세요(예: 예산단위 경영, 계정 복리후생비, 프로젝트 공통). "
                        "적요를 바꾸려면 '적요 …'로, 이 건을 건너뛰려면 '건너뛰기'라고 하세요."
                    ),
                    streaming=False,
                )
                try:
                    resp = await wait_hitl(
                        events,
                        kind="chat",
                        title=f"행 {i + 1} 입력",
                        prompt="예산단위·계정·프로젝트(필요시 적요)를 입력하세요.",
                        extra={"row": {"index": i, "date": when, "merchant": nm, "amount": amt}},
                        timeout_s=timeout_s,
                    )
                except asyncio.TimeoutError:
                    await emit_step(events, "collect_rows", "failed")
                    return {"error": f"행 입력 대기 시간 초과({timeout_s // 60}분). 지금까지 {filled}건 반영(저장 전). 다시 실행해 주세요."}
                if resp.get("done"):
                    await emit_log(events, "사용자 '완료' — 남은 행 처리를 종료합니다.", "info")
                    await emit_step(events, "collect_rows", "done")
                    return {"filled": filled}
                msg = (resp.get("message") or "").strip()
                if not msg:
                    continue
                if "건너" in msg or msg.lower() in {"skip", "pass"}:
                    await emit_log(events, f"행 {i + 1} 건너뜀.", "info")
                    break
                parsed = _parse_fields(msg)
                collected.update({k: v for k, v in parsed.items() if v})
                missing = [f for f in ("예산단위", "계정", "프로젝트") if not collected.get(f)]
                if missing:
                    await emit_chat(
                        events,
                        chat_id=f"row-{i}-ask-{seq}",
                        role="assistant",
                        content=f"아직 {', '.join(missing)}이(가) 필요합니다. 알려주세요.",
                        streaming=False,
                    )
                    continue
                # 필수 3필드 확보 → 채우기.
                ok, detail = await _apply_row_fields(page, events, i, collected)
                if ok:
                    filled += 1
                    await emit_chat(
                        events,
                        chat_id=f"row-{i}-ok",
                        role="assistant",
                        content=f"행 {i + 1} 반영 완료 ({detail}).",
                        note="action",
                        streaming=False,
                    )
                    await emit_shot(events.put, page)
                    break
                # 실패 사유(무매칭·후보다건 등)를 그대로 보여주고, 해당 필드만 정정 입력받는다(리뷰 #1).
                await emit_chat(
                    events,
                    chat_id=f"row-{i}-retry-{seq}",
                    role="assistant",
                    content=f"반영 실패: {detail}\n해당 값을 다시 확인해 알려주세요(예: '프로젝트 정확한명').",
                    streaming=False,
                )
        await emit_log(events, f"행별 입력 완료 — {filled}건 반영(저장 전).", "ok")
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
