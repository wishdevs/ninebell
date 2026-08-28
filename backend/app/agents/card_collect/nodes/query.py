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
        # 카드 선택 — **모든 모드 전체선택**(사용자 확정 2026-08-27). 종전의 일반 모드
        # 본인 카드만(2026-07-31 분기, 카드명 괄호 매칭) 정책은 폐지 — 처리 대상은 어차피
        # 뒤의 그리드 개입에서 사용자가 확정하므로 후보는 전 카드를 담는다.
        # (본인 매칭 프리미티브 steps.owner_name_variants/own_only 는 정책 롤백 대비 유지.)
        r = await steps.select_all_cards(page)
        if not r.get("ok"):
            await emit_step(events, "select_all_cards", "failed")
            return {"error": f"카드 선택 실패: {r.get('reason')}"}
        # 확인 불가(리더가 못 읽음)는 하드 실패가 아니지만 **성공으로 단정하지 않는다** —
        # 로그에 미확인 사실을 남겨야 사후 진단이 된다.
        if r.get("warn"):
            await emit_log(events, f"⚠ 카드 선택 미확인: {r['warn']}", "warn")
        # 폼 반영을 확인하지 못했으면 '완료'가 아니라 '미확인'으로 적는다(성공 단정 금지).
        done = "완료" if r.get("verified", True) else "적용(폼 반영 미확인)"
        await emit_log(events, f"법인카드 {r.get('n')}장 전체선택·적용 {done}.", "ok")
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
        start, _end = steps.compute_period(
            _shared._params_today(state), _shared._params_cutoff_day(state)
        )
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
        cutoff_day = _shared._params_cutoff_day(state)  # 회계시점 결정일(에이전트 설정).
        start, end = steps.compute_period(today, cutoff_day)
        r = await steps.set_period(page, start, end)
        if not r.get("ok"):
            await emit_step(events, "set_period", "failed")
            return {"error": f"승인일 기간 설정 실패({start}~{end}): {r}"}
        if r.get("warn"):
            await emit_log(events, f"⚠ 승인일 기간 미확인: {r['warn']}", "warn")
        # 기간 시작 월 == 오늘 월이면 당월 규칙, 아니면 전월 규칙(라벨은 계산 결과에서 유도).
        rule = "당월" if start[:7] == today.isoformat()[:7] else "전월"
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
        # 저장 제외 필터(사용자 규칙 2026-07-29): 거래처 빈 행은 처리
        # 대상에서 뺀다 — 이후 그리드·반영·저장 전부에서 자연히 제외된다.
        dropped = [(r, why) for r in lst if (why := _shared._exclude_reason(r))]
        if dropped:
            desc = ", ".join(
                f"{(r.get('TRAN_NM') or '(거래처 없음)')[:10]} {r.get('TRAN_AMT', '?')}원({why})"
                for r, why in dropped[:5]
            )
            await emit_log(
                events,
                f"저장 제외 {len(dropped)}건 — {desc}"
                + (" 외" if len(dropped) > 5 else ""),
                "warn",
            )
            lst = [r for r in lst if _shared._exclude_reason(r) is None]
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
        title = f"법인카드 승인내역 {len(lst)}건" + (f" (제외 {len(dropped)}건)" if dropped else "")
        await emit_transactions(events, title=title, columns=columns, rows=table_rows)
        await emit_log(
            events,
            f"조회 완료 — 승인내역 {rows}건" + (f" 중 처리 대상 {len(lst)}건." if dropped else "."),
            "ok",
        )
        await emit_shot(events.put, page)
        await emit_step(events, "query", "done", _shared._ms(t0))
        return {"rows_list": lst}

    return query
