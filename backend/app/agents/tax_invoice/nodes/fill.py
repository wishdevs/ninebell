"""본문 채움 노드 — 발행 전/분할(수동)·발행 후 공용.

발행 전·분할(수동 채움): 거래처(정확명)→적요→예산단위(BG_NM)→공급가액(실타이핑, 세액 자동)
→프로젝트(WBS)→[비과세 사유구분]→[회계일(발행 전 폼 입력 시)]→자금과목 — 쓰기 프로브
Case A 검증 순서. 발행 후(행 적용 완료): 거래처·공급가액·회계일은 ERP 가 채웠으므로
적요→예산단위→프로젝트→[사유구분]→자금과목만 채운다.

⚠ 자금과목(FUND_CD)은 **계정의 관리항목 구성에 따라 필수**다 — 미입력이면 "계정의 관리항목
[자금과목] 항목이 입력되지 않았습니다"로 저장이 반려된다(2026-08-19 headed 세션 확정, 분할
F7 반려의 진짜 원인). 구성별 편차를 미리 판별할 수단이 없어 **항상 기본값 '일반경비'로 채운다**.
결제방법·자금예정일·결제조건은 저장 비필수(결제방법은 자동 기본값 '6' 외상)라 채우지 않는다.
'당월결제' 기본값은 환경 카탈로그에 없어 사용자 확인 대기(PROCESS.md 검증 체인 4).
"""

from __future__ import annotations

import time

from app.agents.common import doc_steps
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_fill_rows_node():
    """단일(원본) 행 채움 — 실패는 필드 명시 error 로 즉시 단락(반쪽 결의서 저장 방지)."""

    async def fill_rows(state: dict) -> dict:
        if state.get("error") or state.get("aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        plan = state.get("plan") or {}
        await emit_step(events, "fill_rows", "running")
        t0 = time.monotonic()
        # 발행 후는 계산서 행마다 값이 달라 개입(invoice-grid)에서 받고 apply_invoices 가
        # 행별로 채운다(D1 2026-08-20) — 이 노드는 발행 전 폼 경로 전용이다.
        if plan.get("issue") == "post":
            await emit_log(events, "발행 후 — 본문은 계산서 적용 단계에서 행별로 채웁니다.", "info")
            await emit_step(events, "fill_rows", "done", _ms(t0))
            return {}
        # 거래처·공급가액을 직접 채우는 경로 = 발행 전 + 수동분할. 발행 후(자동분할 포함)는
        # 계산서 행 적용이 이미 채웠다.
        manual = plan.get("issue") == "pre" or bool(plan.get("split") and plan.get("split_manual"))

        async def fail(field: str, reason) -> dict:
            await emit_step(events, "fill_rows", "failed")
            msg = f"'{field}' 입력 실패: {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg}

        warns: list[str] = []

        async def note_warn(field: str, r: dict) -> None:
            if r.get("warn"):
                warns.append(field)
                await emit_log(events, f"'{field}' {r['warn']}", "warn")

        # 1) 거래처 — 발행 전/분할만(발행 후는 선택 행이 채움). ERP 등록 정확명 매칭("(주)" 포함 주의).
        if manual:
            partner = plan["partner_name"]
            pr = await steps._fill_partner_cell(page, "PARTNER_NM", partner, partner, None, "거래처")
            if not pr.get("ok"):
                return await fail("거래처", pr.get("reason"))
            await note_warn("거래처", pr)
        # 2) 적요(NOTE_DC — inert setValue + 재독 대조).
        nt = await steps.set_row_note(page, plan["note"])
        if not nt.get("ok"):
            return await fail("적요", nt.get("reason"))
        await note_warn("적요", nt)
        # 3) 예산단위(BG_NM 완전일치 — 사업계획/예산계정/비용센터 자동연동).
        bu = await steps.fill_budget_by_name(page, plan["budget_unit_name"])
        if not bu.get("ok"):
            return await fail("예산단위", bu.get("reason"))
        await note_warn("예산단위", bu)
        # 4) 공급가액 — 발행 전/분할만. 실타이핑으로 세액 10%·합계 자동계산(즉시 반영 — 실측).
        if manual:
            sa = await steps.type_amount(page, plan["supply_amount"])
            if not sa.get("ok"):
                return await fail("공급가액", sa.get("reason"))
        # 5) 프로젝트(WBS 정확매칭).
        pj = await steps.fill_project(page, {"wbsNo": plan["project_wbs"], "name": ""})
        if not pj.get("ok"):
            return await fail("프로젝트", pj.get("reason"))
        await note_warn("프로젝트", pj)
        # 6) 비과세 사유구분(04/13/23 — 04 는 미입력 시 저장 반려 실측).
        if plan.get("exempt_reason"):
            er = await steps.fill_exempt_reason(page, plan["exempt_reason"])
            if not er.get("ok"):
                return await fail("사유구분", er.get("reason"))
        # 7) 회계일(발행 전 폼 입력 시 — 그리드 API, 달력 클릭 금지: 캔버스+decoy input 함정 D9).
        if plan.get("actg_date_compact"):
            compact = plan["actg_date_compact"]
            dashed = f"{compact[0:4]}-{compact[4:6]}-{compact[6:8]}"
            ad = await doc_steps.set_acct_date(page, compact, dashed)
            if not ad.get("ok"):
                return await fail("회계일", ad.get("reason"))
            await note_warn("회계일", ad)
            await emit_log(events, f"회계일 = {dashed}.", "info")
        # 8) 자금과목 — 계정 관리항목이 요구하면 필수(미입력 시 저장 반려). 예산단위 적용으로
        #    예산계정이 붙은 뒤라야 패널에 행이 생기므로 채움 마지막에 둔다.
        fd = await steps.fill_fund_item(page)
        if not fd.get("ok"):
            return await fail("자금과목", fd.get("reason"))
        await emit_log(events, f"자금과목 = {fd.get('name') or fd.get('code')}.", "info")

        amount_txt = (
            f" · 공급가액 {plan['supply_amount']:,}원" if plan.get("supply_amount") is not None else ""
        )
        if warns:
            await emit_log(
                events,
                f"본문 반영 — 적요 '{plan['note']}'{amount_txt}. "
                f"⚠ 반영 미확인: {', '.join(warns)}(저장 후 값 확인 필요).",
                "warn",
            )
        else:
            await emit_log(events, f"본문 반영 완료 — 적요 '{plan['note']}'{amount_txt}.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "fill_rows", "done", _ms(t0))
        return {"filled": 1, "fill_warnings": warns}

    return fill_rows
