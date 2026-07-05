"""조회 단계 노드 — 카드 전체선택·회계일(말일)·승인일 기간(D2)·조회/리스트 표 보고."""

from __future__ import annotations

import time
from datetime import date

from app.live.events import emit_log, emit_step, emit_transactions
from nbkit.patterns import emit_shot

from .. import steps
from . import _shared


# ── 카드 전체선택 ────────────────────────────────────────────────────────────────
def make_select_all_cards_node():
    async def select_all_cards(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "select_all_cards", "running")
        t0 = time.monotonic()
        # 로그인ID(=사용자명)와 일치하는 본인 카드만 우선 선택, 없으면 전체선택 폴백.
        owner = state.get("userid")
        r = await steps.select_all_cards(page, owner_name=owner)
        if not r.get("ok"):
            await emit_step(events, "select_all_cards", "failed")
            return {"error": f"카드 선택 실패: {r.get('reason')}"}
        if r.get("by") == "name":
            await emit_log(
                events, f"본인('{owner}') 카드 {r.get('checked')}장 선택·적용 완료.", "ok"
            )
        else:
            await emit_log(events, f"법인카드 {r.get('n')}장 전체선택·적용 완료(본인 카드 없음).", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "select_all_cards", "done", _shared._ms(t0))
        return {}

    return select_all_cards


# ── 회계일(마스터 그리드 ACTG_DT = 수집 기간 월의 말일) ────────────────────────────
def make_set_acct_date_node():
    """회계일 규칙(사용자 확정 2026-07-04): 전월 수집=전월 말일, 당월 수집=당월 말일.

    F3 직후 생성된 마스터(결의서) 행의 ACTG_DT 를 수집 기간 월의 말일로 설정한다.
    카드 팝업이 뜨기 전(메인 화면)이라 안전하게 datasource 로 쓴다(프로브 실측).
    """

    async def set_acct_date(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "set_acct_date", "running")
        t0 = time.monotonic()
        start, _end = steps.compute_period(_shared._params_today(state))
        compact, dashed = steps.period_month_end(start)
        r = await steps.set_acct_date(page, compact, dashed)
        if not r.get("ok"):
            await emit_step(events, "set_acct_date", "failed")
            return {"error": f"회계일 설정 실패({dashed}): {r.get('reason')}"}
        await emit_log(events, f"회계일 = {dashed} (수집 기간 월의 말일).", "info")
        await emit_step(events, "set_acct_date", "done", _shared._ms(t0))
        return {}

    return set_acct_date


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
        await emit_step(events, "set_period", "done", _shared._ms(t0))
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
        # 리스트 표 보고(승인일/가맹점명/승인액/부가세구분).
        columns = [
            {"key": "d", "header": "승인일"},
            {"key": "m", "header": "가맹점명"},
            {"key": "a", "header": "승인액", "align": "right"},
            {"key": "v", "header": "부가세구분"},
        ]
        table_rows = [
            {
                "d": r.get("TRAN_DT") or "",
                "m": r.get("TRAN_NM") or "",
                "a": _shared._fmt_won(r.get("TRAN_AMT")),
                "v": r.get("VAT_TP") or "-",
            }
            for r in lst
        ]
        await emit_transactions(events, title=f"법인카드 승인내역 {rows}건", columns=columns, rows=table_rows)
        await emit_log(events, f"조회 완료 — 승인내역 {rows}건.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "query", "done", _shared._ms(t0))
        return {"rows_list": lst}

    return query
