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
        # 카드 선택 분기(사용자 요구 2026-07-31): 디버그 모드(runs.py 가 불리언 강제 주입)면
        # 종전처럼 **전체선택**, 기본(일반 모드)은 로그인ID·프로필 이름·"이름 직책"과 일치하는
        # **본인 카드만**(매칭 0장이면 폴백 없이 중단 — 무매칭 임의선택 금지).
        # 직책 변형은 패널 이름 "석대현 프로" 표기 대응(사용자 요청 2026-07-29).
        params = state.get("params") or {}
        debug = params.get("debug") is True
        owners = steps.owner_name_variants(
            state.get("userid"), params.get("user_display_name"), params.get("user_job_title")
        )
        owner = owners[0] if owners else None  # 로그 표시용 대표 키.
        if debug:
            r = await steps.select_all_cards(page)
        else:
            r = await steps.select_all_cards(page, owner_name=owners, own_only=True)
        if not r.get("ok"):
            if not debug and r.get("matched") == 0:
                # 매칭 진단(카드 수·대조 이름)을 로그로 남긴다 — 사후 원인 추적용.
                await emit_log(
                    events,
                    f"본인 카드 매칭 0장(전체 {r.get('n')}장) — 대조 이름: {', '.join(owners)}",
                    "error",
                )
            await emit_step(events, "select_all_cards", "failed")
            return {"error": f"카드 선택 실패: {r.get('reason')}"}
        # 확인 불가(리더가 못 읽음)는 하드 실패가 아니지만 **성공으로 단정하지 않는다** —
        # 로그에 미확인 사실을 남겨야 사후 진단이 된다.
        if r.get("warn"):
            await emit_log(events, f"⚠ 카드 선택 미확인: {r['warn']}", "warn")
        # 폼 반영을 확인하지 못했으면 '완료'가 아니라 '미확인'으로 적는다(성공 단정 금지).
        done = "완료" if r.get("verified", True) else "적용(폼 반영 미확인)"
        if r.get("by") == "name":
            names = ", ".join(n for n in (r.get("names") or []) if n)
            await emit_log(
                events,
                f"본인('{owner}') 카드 {r.get('checked')}장 선택·적용 {done}."
                + (f" — {names}" if names else ""),
                "ok",
            )
        elif debug:
            await emit_log(events, f"법인카드 {r.get('n')}장 전체선택·적용 {done}(디버그 모드).", "ok")
        else:
            # 일반 모드인데 by='all' = 본인 카드 0장 폴백(사용자 확정 2026-08-03).
            # 왜 전체가 선택됐는지 사용자가 화면에서 바로 알 수 있어야 한다.
            await emit_log(
                events,
                f"본인('{owner}') 명의 카드가 없어 법인카드 {r.get('n')}장 **전체**를 선택했습니다"
                " — 처리할 내역은 다음 단계 그리드에서 직접 확인·선택해 주세요.",
                "warn",
            )
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
        # 저장 제외 필터(사용자 규칙 2026-07-29): 승인번호 00000000·거래처 빈 행은 처리
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
