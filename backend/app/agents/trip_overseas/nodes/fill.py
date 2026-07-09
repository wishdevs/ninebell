"""회계일 세팅 + 행별 채움 노드(진입 앞단 이후 본문 문서 채움).

fill_rows 는 plan_rows 를 내부 루프로 돈다(HITL 없음). P9 실측: 증빙 carry-over 없음 →
행마다 증빙(10)을 재선택한다. detail 조작은 항상 마지막(현재) 행 대상(steps 계약) — F3 직후
그 행을 채운다. 한 필드라도 실패하면 즉시 error 로 단락한다(반쪽 채워진 결의서 저장 방지).
"""

from __future__ import annotations

import time

from app.agents.common import doc_steps
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps

# 증빙유형 코드(D4/P2): 10 = 규정에의한 비용정산.
EVDN_CODE = "10"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_set_acct_date_node():
    """마스터 회계일(ACTG_DT) = 마지막 계산서일(validate_params 가 계산서일 최댓값으로 파생한 compact)."""

    async def set_acct_date(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "set_acct_date", "running")
        t0 = time.monotonic()
        compact = str(state.get("acct_date_compact") or "")
        if len(compact) != 8:
            await emit_step(events, "set_acct_date", "failed")
            return {"error": f"회계일자 형식 오류: {compact!r}"}
        dashed = f"{compact[0:4]}-{compact[4:6]}-{compact[6:8]}"
        r = await doc_steps.set_acct_date(page, compact, dashed)
        if not r.get("ok"):
            await emit_step(events, "set_acct_date", "failed")
            return {"error": f"회계일 설정 실패({dashed}): {r.get('reason')}"}
        await emit_log(events, f"회계일 = {dashed} (마지막 계산서일).", "info")
        await emit_step(events, "set_acct_date", "done", _ms(t0))
        return {}

    return set_acct_date


def make_fill_rows_node():
    """plan_rows 를 행별로 채운다 — 증빙(10)→계산서일→거래처→예산단위→프로젝트→공급가액→적요→상대계정.

    유형 구분 없음(모든 행 동일). 거래처·상대계정 = 작성자 본인(state['userid']).
    예산단위 = 부서 × 비용구분(판/제) 여비교통비-해외출장 고정 조합. 실패는 행·필드 명시 error.
    """

    async def fill_rows(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "fill_rows", "running")
        t0 = time.monotonic()

        plan_rows = state.get("plan_rows") or []
        department = str(state.get("department") or "")
        cost_type = str(state.get("cost_type") or "")
        self_name = str(state.get("userid") or "").strip()
        if not self_name:
            await emit_step(events, "fill_rows", "failed")
            return {"error": "작성자 본인 이름(로그인 계정)이 없어 거래처·상대계정을 검색할 수 없습니다."}

        async def fail(i: int, field: str, reason) -> dict:
            await emit_step(events, "fill_rows", "failed")
            msg = f"{i + 1}행 '{field}' 입력 실패: {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg, "fill_failures": [{"row": i + 1, "field": field, "reason": reason}]}

        total = len(plan_rows)
        filled = 0
        for i, row in enumerate(plan_rows):
            amount = int(row.get("amount") or 0)
            await emit_log(events, f"{i + 1}/{total}행 입력 시작 — 공급가액 {amount:,}원.", "info")

            # 1) 2행째부터 F3 행 추가(첫 행은 앞단 add_row 노드가 생성).
            if i > 0:
                r = await doc_steps.add_next_row(page, i + 1)
                if not r.get("ok"):
                    return await fail(i, "행추가(F3)", r.get("reason"))
            # 2) 증빙유형(10) — P9: 행마다 재선택.
            oe = await doc_steps.open_evdn_editor(page)
            if not oe.get("ok"):
                return await fail(i, "증빙 열기", oe.get("reason"))
            se = await doc_steps.select_evdn_code(page, EVDN_CODE)
            if not se.get("ok"):
                return await fail(i, "증빙유형(10)", se.get("reason"))
            # 2.5) (세금)계산서일(START_DT) = 행별 증빙일.
            dt = await steps.set_invoice_date(page, str(row.get("invoiceDate") or ""))
            if not dt.get("ok"):
                return await fail(i, "계산서일", dt.get("reason"))
            # 3) 거래처 = 작성자 본인 이름 검색(해외 정산서는 유형 구분 없이 전 행 본인).
            pr = await steps.fill_partner_by_search(page, self_name)
            if not pr.get("ok"):
                return await fail(i, "거래처", pr.get("reason"))
            # 4) 예산단위(부서 × 비용구분 여비교통비-해외출장 고정 조합).
            bu = await steps.fill_budget_fixed(page, department, cost_type)
            if not bu.get("ok"):
                return await fail(i, "예산단위", bu.get("reason"))
            # 5) 프로젝트.
            pj = await steps.fill_project(page, row.get("project") or {})
            if not pj.get("ok"):
                return await fail(i, "프로젝트", pj.get("reason"))
            # 6) 공급가액(거래금액=SPPRC_AMT2) = **셀 에디터 실 타이핑 + 예산현황 확인**(국내와 동일).
            #    setValue 는 예산현황 확인 트리거를 건너뛰어 저장 DB오류 → 타이핑+Tab→예산현황 확인.
            sa = await steps.type_amount(page, amount)
            if not sa.get("ok"):
                return await fail(i, "공급가액", sa.get("reason"))
            # 7) 적요.
            nt = await steps.set_row_note(page, row.get("note") or "")
            if not nt.get("ok"):
                return await fail(i, "적요", nt.get("reason"))
            # 8) 상대계정거래처(작성자 본인) = **부가선택 위젯 🔍 → 검색 → 행 더블클릭**(국내와 동일).
            #    등록 시 딸려오는 빈 행은 9) 에서 삭제.
            cp = await steps.register_counter_partner(page, self_name)
            if not cp.get("ok"):
                return await fail(i, "상대계정거래처", cp.get("reason"))
            if cp.get("skipped"):
                await emit_log(events, f"{i + 1}행 상대계정거래처 항목 없음(해외 정산서) — 스킵.", "info")
            # 9) 상대계정 등록으로 추가된 빈 행 삭제(데이터 행 유지).
            db = await steps.delete_blank_row(page)
            if not db.get("ok"):
                return await fail(i, "빈행삭제", db.get("reason"))

            filled += 1
            await emit_log(events, f"{i + 1}/{total}행 반영 완료.", "ok")
            await emit_shot(events.put, page)

        # 전 행 합계를 마스터에 명시 세팅 — setValue 는 ERP 합계 재계산 핸들러 미발화라 마스터
        # DETAIL_SUM_AMT 가 마지막 행을 누락한다(실측). 저장값 정합을 위해 총액을 직접 세팅.
        grand_total = sum(int(r.get("amount") or 0) for r in plan_rows)
        mt = await steps.set_master_total(page, grand_total)
        if not mt.get("ok"):
            await emit_step(events, "fill_rows", "failed")
            msg = f"마스터 합계금액 세팅 실패: {mt.get('reason')}"
            await emit_log(events, msg, "error")
            return {"error": msg, "fill_failures": [{"row": 0, "field": "마스터합계", "reason": mt.get("reason")}]}

        await emit_log(events, f"전체 {filled}/{total}행 반영 + 마스터 합계 {grand_total:,}원.", "ok")
        await emit_step(events, "fill_rows", "done", _ms(t0))
        return {"filled": filled, "fill_failures": []}

    return fill_rows
