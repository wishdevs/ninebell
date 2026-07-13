"""회계일 세팅 + 단건 채움 노드(경조금신청서).

경조금은 단건(1행) — 국내/해외출장의 다행 루프를 단일 행으로 축약한다(경조사 1건 = 결의서 1장).
detail 조작은 항상 마지막(현재) 행 대상(steps 계약) — 앞단 add_row 가 만든 첫 행을 채운다. 한
필드라도 실패하면 즉시 error 로 단락한다(반쪽 채워진 결의서 저장 방지).

경조금 델타(국내/해외출장 대비): ①단일 행(F3 추가 루프 없음) ②거래처=작성자 본인(전 행 본인 검색)
③예산단위=복리후생비-경조(steps.fill_budget_fixed 가 경조금 base) ④적요='경조금-{본인이름}'(본인
이름은 거래처 본인검색 결과, D7) ⑤증빙유형 10·계산서일·금액 타이핑은 재사용. **상대계정거래처는
경조금엔 불필요**(2026-07-13 사용자 확정) — trip 의 register_counter_partner·빈행삭제 스텝 미사용.
"""

from __future__ import annotations

import time

from app.agents.common import doc_steps
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps

# 증빙유형 코드(D5): 10 = 규정에의한 비용정산(trip 25종 목록과 동일 코드).
EVDN_CODE = "10"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_set_acct_date_node():
    """마스터 회계일(ACTG_DT) = 증빙일자(validate_params 가 증빙일 그대로 파생한 compact, D4)."""

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
        await emit_log(events, f"회계일 = {dashed} (증빙일).", "info")
        await emit_step(events, "set_acct_date", "done", _ms(t0))
        return {}

    return set_acct_date


def make_fill_rows_node():
    """단건 채움 — 증빙(10)→계산서일→거래처(본인)→예산단위(복리후생비-경조)→프로젝트→공급가액→적요.

    거래처 = 작성자 본인(state['userid']). 적요 = '경조금-{본인이름}'(거래처 본인검색 결과 이름으로
    조립). 예산단위 = 부서 × 비용구분(판/제) 복리후생비-경조 고정 조합. 상대계정거래처는 경조금엔
    불필요(사용자 확정)라 미사용. 실패는 필드 명시 error.
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
            return {"error": "작성자 본인 이름(로그인 계정)이 없어 거래처·상대계정·적요를 구성할 수 없습니다."}
        if not plan_rows:
            await emit_step(events, "fill_rows", "failed")
            return {"error": "채울 입력 행이 없습니다."}

        async def fail(field: str, reason) -> dict:
            await emit_step(events, "fill_rows", "failed")
            msg = f"'{field}' 입력 실패: {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg, "fill_failures": [{"row": 1, "field": field, "reason": reason}]}

        row = plan_rows[0]  # 단건.
        amount = int(row.get("amount") or 0)
        await emit_log(events, f"경조금 입력 시작 — 공급가액 {amount:,}원.", "info")

        # 1) 증빙유형(10). (첫 행은 앞단 add_row 가 이미 생성 — 단건이라 F3 추가 없음.)
        oe = await doc_steps.open_evdn_editor(page)
        if not oe.get("ok"):
            return await fail("증빙 열기", oe.get("reason"))
        se = await doc_steps.select_evdn_code(page, EVDN_CODE)
        if not se.get("ok"):
            return await fail("증빙유형(10)", se.get("reason"))
        # 2) (세금)계산서일(START_DT) = 증빙일.
        dt = await steps.set_invoice_date(page, str(row.get("invoiceDate") or ""))
        if not dt.get("ok"):
            return await fail("계산서일", dt.get("reason"))
        # 3) 거래처 = 작성자 본인(전 행 본인 검색 — trip_overseas 동일). 반환 name 으로 적요 조립.
        pr = await steps.fill_partner_by_search(page, self_name)
        if not pr.get("ok"):
            return await fail("거래처", pr.get("reason"))
        self_display = str(pr.get("name") or self_name).strip()
        # 4) 예산단위(부서 × 비용구분 복리후생비-경조 고정 조합).
        bu = await steps.fill_budget_fixed(page, department, cost_type)
        if not bu.get("ok"):
            return await fail("예산단위", bu.get("reason"))
        # 5) 프로젝트.
        pj = await steps.fill_project(page, row.get("project") or {})
        if not pj.get("ok"):
            return await fail("프로젝트", pj.get("reason"))
        # 6) 공급가액(거래금액=SPPRC_AMT2) = 셀 에디터 실 타이핑 + 예산현황 확인(setValue 금지).
        sa = await steps.type_amount(page, amount)
        if not sa.get("ok"):
            return await fail("공급가액", sa.get("reason"))
        # 7) 적요 = '경조금-{본인이름}'(D7) — 본인이름은 거래처 본인검색 결과.
        note = f"경조금-{self_display}"
        nt = await steps.set_row_note(page, note)
        if not nt.get("ok"):
            return await fail("적요", nt.get("reason"))
        # (상대계정거래처는 경조금엔 불필요 — 2026-07-13 사용자 확정. trip 의 register_counter_partner +
        #  그로 인해 딸려오는 빈 행 삭제(delete_blank_row) 스텝을 제거. 다른 피커는 빈 행을 만들지 않는다.)

        # 단건 총액을 마스터에 명시 세팅 — setValue 는 ERP 합계 재계산 핸들러 미발화라 마스터
        # DETAIL_SUM_AMT 가 stale 일 수 있다(국내/해외출장과 동일 방어). 저장값 정합을 위해 직접 세팅.
        mt = await steps.set_master_total(page, amount)
        if not mt.get("ok"):
            await emit_step(events, "fill_rows", "failed")
            msg = f"마스터 합계금액 세팅 실패: {mt.get('reason')}"
            await emit_log(events, msg, "error")
            return {"error": msg, "fill_failures": [{"row": 0, "field": "마스터합계", "reason": mt.get("reason")}]}

        await emit_log(events, f"경조금 반영 완료 — 적요 '{note}' · 공급가액 {amount:,}원.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "fill_rows", "done", _ms(t0))
        return {"filled": 1, "fill_failures": []}

    return fill_rows
