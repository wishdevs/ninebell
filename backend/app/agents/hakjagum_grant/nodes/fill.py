"""회계일 세팅 + 단건 채움 노드(학자금신청서).

학자금은 단건(1행) — 경조금과 동일하게 국내/해외출장의 다행 루프를 단일 행으로 축약한다(학자금
1건 = 결의서 1장). detail 조작은 항상 마지막(현재) 행 대상(steps 계약) — 앞단 add_row 가 만든
첫 행을 채운다. 한 필드라도 실패하면 즉시 error 로 단락한다(반쪽 채워진 결의서 저장 방지).

학자금 델타(경조금 대비): ①예산단위=복리후생비-기타(steps.fill_budget_fixed 가 학자금 base)
②적요='학자금-{본인이름}'(본인 이름은 거래처 본인검색 결과, D7) ③공급가액=사용자 입력 금액
그대로(50% 규칙 없음). 단일 행·거래처=작성자 본인·증빙유형 10·계산서일·금액 타이핑은 경조금
동형. **상대계정거래처는 미사용**(경조금 동형 가정, 검증:❓) — trip 의 register_counter_partner·
빈행삭제 스텝 미사용.
"""

from __future__ import annotations

import time

from app.agents.common import doc_steps
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps

# 증빙유형 코드(D5): 10 = 규정에의한 비용정산(경조금·trip 25종 목록과 동일 코드).
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
        # 확인 불가(그리드 셀 readback 실패)는 하드 실패로 막지 않되 **조용히 넘기지도 않는다** —
        # 회계일은 저장될 데이터 자체라, 반영을 못 본 채 진행했다는 사실이 로그에 남아야 한다.
        if r.get("warn"):
            await emit_log(events, f"회계일 {r['warn']}", "warn")
        verified = "" if r.get("verified", True) else " (반영 미확인)"
        await emit_log(events, f"회계일 = {dashed} (증빙일).{verified}", "info")
        await emit_step(events, "set_acct_date", "done", _ms(t0))
        return {}

    return set_acct_date


def make_fill_rows_node():
    """단건 채움 — 증빙(10)→계산서일→거래처(본인)→예산단위(복리후생비-기타)→프로젝트→공급가액→적요.

    거래처 = 작성자 본인(state['userid']). 적요 = '학자금-{본인이름}'(거래처 본인검색 결과 이름으로
    조립). 예산단위 = 부서 × 비용구분(판/제) 복리후생비-기타 고정 조합. 상대계정거래처는 미사용
    (경조금 동형 가정, 검증:❓). 실패는 필드 명시 error.
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
            return {"error": "작성자 본인 이름(로그인 계정)이 없어 거래처·적요를 구성할 수 없습니다."}
        if not plan_rows:
            await emit_step(events, "fill_rows", "failed")
            return {"error": "채울 입력 행이 없습니다."}

        async def fail(field: str, reason) -> dict:
            await emit_step(events, "fill_rows", "failed")
            msg = f"'{field}' 입력 실패: {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg, "fill_failures": [{"row": 1, "field": field, "reason": reason}]}

        # 스텝이 '확인 불가'(리더로 셀을 못 읽음)로 통과했으면 그 사실을 반드시 노출한다 —
        # 반영 실패는 하드 실패로 걸리지만, 확인 불가가 조용히 지나가면 아래 완료 로그가 거짓이 된다.
        warns: list[str] = []

        async def note_warn(field: str, r: dict) -> None:
            if r.get("warn"):
                warns.append(field)
                await emit_log(events, f"'{field}' {r['warn']}", "warn")

        row = plan_rows[0]  # 단건.
        amount = int(row.get("amount") or 0)
        await emit_log(events, f"학자금 입력 시작 — 공급가액 {amount:,}원.", "info")

        # 1) 증빙유형(10). (첫 행은 앞단 add_row 가 이미 생성 — 단건이라 F3 추가 없음.)
        oe = await doc_steps.open_evdn_editor(page)
        if not oe.get("ok"):
            return await fail("증빙 열기", oe.get("reason"))
        # 스테일 팝업(열기)·팝업 미닫힘(적용 후) warn 도 유실 금지 — 이후 피커 오독·엉뚱한 셀
        # 덮어쓰기의 전조라 완료 로그가 이를 감추면 안 된다(trip_domestic warn_if_unverified 동형).
        await note_warn("증빙 열기", oe)
        se = await doc_steps.select_evdn_code(page, EVDN_CODE)
        if not se.get("ok"):
            return await fail("증빙유형(10)", se.get("reason"))
        await note_warn("증빙유형(10)", se)
        # 2) (세금)계산서일(START_DT) = 증빙일.
        dt = await steps.set_invoice_date(page, str(row.get("invoiceDate") or ""))
        if not dt.get("ok"):
            return await fail("계산서일", dt.get("reason"))
        # 3) 거래처 = 작성자 본인(전 행 본인 검색 — 경조금 동일). 반환 name 으로 적요 조립.
        pr = await steps.fill_partner_by_search(page, self_name)
        if not pr.get("ok"):
            return await fail("거래처", pr.get("reason"))
        await note_warn("거래처", pr)
        self_display = str(pr.get("name") or self_name).strip()
        # 4) 예산단위(부서 × 비용구분 복리후생비-기타 고정 조합).
        bu = await steps.fill_budget_fixed(page, department, cost_type)
        if not bu.get("ok"):
            return await fail("예산단위", bu.get("reason"))
        await note_warn("예산단위", bu)
        # 5) 프로젝트.
        pj = await steps.fill_project(page, row.get("project") or {})
        if not pj.get("ok"):
            return await fail("프로젝트", pj.get("reason"))
        await note_warn("프로젝트", pj)
        # 6) 공급가액(거래금액=SPPRC_AMT2) = 셀 에디터 실 타이핑 + 예산현황 확인(setValue 금지).
        sa = await steps.type_amount(page, amount)
        if not sa.get("ok"):
            return await fail("공급가액", sa.get("reason"))
        # 7) 적요 = '학자금-{본인이름}'(D7) — 본인이름은 거래처 본인검색 결과.
        note = f"학자금-{self_display}"
        nt = await steps.set_row_note(page, note)
        if not nt.get("ok"):
            return await fail("적요", nt.get("reason"))
        await note_warn("적요", nt)
        # (상대계정거래처는 미사용 — 경조금 동형 가정(검증:❓). trip 의 register_counter_partner +
        #  그로 인해 딸려오는 빈 행 삭제(delete_blank_row) 스텝 미사용. 다른 피커는 빈 행을 만들지 않는다.)

        # 단건 총액을 마스터에 명시 세팅 — setValue 는 ERP 합계 재계산 핸들러 미발화라 마스터
        # DETAIL_SUM_AMT 가 stale 일 수 있다(국내/해외출장·경조금과 동일 방어). 저장값 정합을 위해 직접 세팅.
        mt = await steps.set_master_total(page, amount)
        if not mt.get("ok"):
            await emit_step(events, "fill_rows", "failed")
            msg = f"마스터 합계금액 세팅 실패: {mt.get('reason')}"
            await emit_log(events, msg, "error")
            return {"error": msg, "fill_failures": [{"row": 0, "field": "마스터합계", "reason": mt.get("reason")}]}

        # 확인되지 않은 필드가 하나라도 있으면 '완료'라고 단정하지 않는다(어느 필드가 미확인인지 명시).
        if warns:
            await emit_log(
                events,
                f"학자금 반영 — 적요 '{note}' · 공급가액 {amount:,}원. "
                f"⚠ 반영 미확인: {', '.join(warns)}(저장 후 값 확인 필요).",
                "warn",
            )
        else:
            await emit_log(
                events, f"학자금 반영 완료 — 적요 '{note}' · 공급가액 {amount:,}원.", "ok"
            )
        await emit_shot(events.put, page)
        await emit_step(events, "fill_rows", "done", _ms(t0))
        return {"filled": 1, "fill_failures": [], "fill_warnings": warns}

    return fill_rows
