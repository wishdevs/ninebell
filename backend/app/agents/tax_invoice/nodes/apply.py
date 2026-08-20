"""발행 후 — 선택한 계산서를 문서에 적용하고, 생성된 detail 행마다 본문을 채운다.

발행 전 실행에서는 스킵된다(폼 입력 경로의 fill_rows 가 담당).

순서(1건 기준 — PROCESS.md D1): 팝업에서 선택 행 적용 → ERP 가 거래처·공급가액·회계일을 채운
detail 행 생성 → 그 행에 예산단위·프로젝트·적요(+비과세 사유구분) → 자금과목.

⚠❓ **복수 선택의 detail 행 생성 구조는 쓰기 프로브 실측 대기**다(PROCESS.md D1 ❓):
  - 계산서 1건 = detail 1행인지, 합산 1행인지 미확인.
  - 복수 행을 한 번에 적용했을 때 행별 채움을 어떤 순서로 잡아야 하는지 미확인.
  그래서 여기서는 **1건씩 순차 적용 → 방금 생긴 행 채움**으로 구현한다(마지막 행 기준 채움
  스텝을 그대로 쓸 수 있는 유일한 구조). 2건째부터는 팝업을 다시 열어 **승인번호로 재매칭**
  한다 — 이미 반영된 계산서가 목록에서 빠질 수 있어 첫 조회의 행 인덱스를 재사용하지 않는다(❓).
  실측 후 '한 번에 적용 + 행 인덱스 채움'이 맞다고 확인되면 이 노드만 바꾸면 된다.
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step
from nbkit.omnisol import js_lib
from nbkit.patterns import emit_shot

from .. import steps


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def _detail_rowcount(page) -> int:
    n = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
    return n if isinstance(n, int) else -1


def match_invoice_index(rows: list[dict], want: dict) -> int | None:
    """재조회 목록에서 대상 계산서 행을 찾는다 — 승인번호 우선, 없으면 (거래처+합계).

    ❓ 이미 반영된 계산서가 목록에서 빠지는지 미실측이라 인덱스를 재사용하지 않는다.
    """
    aprvl = str(want.get("ntsAprvlNo") or "").strip()
    if aprvl:
        for i, r in enumerate(rows):
            if str(r.get("NTS_APRVL_NO") or "").strip() == aprvl:
                return i
    partner = str(want.get("partnerName") or "").strip()
    total = want.get("sumAmount")
    if partner:
        for i, r in enumerate(rows):
            same_partner = str(r.get("PARTNER_NM") or "").strip() == partner
            same_total = total is None or str(r.get("SUM_AMT") or "").replace(",", "") == str(total)
            if same_partner and same_total:
                return i
    return None


def make_apply_invoices_node():
    """선택 계산서 적용 + 행별 채움. 실패는 필드 명시 error 로 즉시 단락(반쪽 결의서 방지)."""

    async def apply_invoices(state: dict) -> dict:
        if state.get("error") or state.get("aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        plan = state.get("plan") or {}
        selection = state.get("invoice_selection") or []
        await emit_step(events, "apply_invoices", "running")
        t0 = time.monotonic()
        if plan.get("issue") != "post" or not selection:
            await emit_log(events, "발행 전 — 계산서 적용을 건너뜁니다.", "info")
            await emit_step(events, "apply_invoices", "done", _ms(t0))
            return {}

        async def fail(what: str, reason) -> dict:
            await emit_step(events, "apply_invoices", "failed")
            msg = f"계산서 반영 실패({what}): {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg}

        warns: list[str] = []

        async def note_warn(field: str, r: dict) -> None:
            if r.get("warn"):
                warns.append(field)
                await emit_log(events, f"'{field}' {r['warn']}", "warn")

        for order, item in enumerate(selection):
            label = f"{item['no']}번 계산서"
            index = item["index"]
            if order > 0:
                # 2건째부터는 팝업을 다시 열고 **승인번호로 재매칭**한다(❓ 구조 실측 대기).
                reopen = await steps.open_invoice_list(page, plan["period_from"], plan["period_to"])
                if not reopen.get("ok"):
                    return await fail(f"{label} 재조회", reopen.get("reason"))
                rows = reopen.get("rows") or []
                found = match_invoice_index(rows, item.get("grid_row") or {})
                if found is None:
                    return await fail(
                        f"{label} 재매칭",
                        "재조회 목록에서 해당 계산서를 찾지 못했습니다(이미 반영됐거나 조회조건 변동) — "
                        "남은 계산서는 반영하지 않았습니다.",
                    )
                index = found
            before_rows = await _detail_rowcount(page)
            ap = await steps.apply_invoice_rows(page, [index])
            if not ap.get("ok"):
                return await fail(f"{label} 적용", ap.get("reason"))
            after_rows = await _detail_rowcount(page)
            if before_rows >= 0 and after_rows >= 0 and after_rows <= before_rows:
                # ❓ 1계산서=1행 가정의 검증 지점 — 행이 안 늘면 다음 행 채움이 엉뚱한 행을 친다.
                return await fail(
                    f"{label} 적용 확인",
                    f"적용 후 상세 행이 늘지 않았습니다(행수 {before_rows}→{after_rows}).",
                )
            await emit_log(events, f"{label} 적용 — 상세 행 {after_rows}행.", "ok")

            # 방금 생긴 행(마지막 행)에 본문 채움 — 채움 스텝은 전부 마지막 행 기준이다.
            nt = await steps.set_row_note(page, item["note"])
            if not nt.get("ok"):
                return await fail(f"{label} 적요", nt.get("reason"))
            await note_warn(f"{label} 적요", nt)
            bu = await steps.fill_budget_by_name(page, item["budget_unit_name"])
            if not bu.get("ok"):
                return await fail(f"{label} 예산단위", bu.get("reason"))
            await note_warn(f"{label} 예산단위", bu)
            if item.get("project_wbs"):
                pj = await steps.fill_project(
                    page, {"wbsNo": item["project_wbs"], "name": item.get("project_name") or ""}
                )
                if not pj.get("ok"):
                    return await fail(f"{label} 프로젝트", pj.get("reason"))
                await note_warn(f"{label} 프로젝트", pj)
            if plan.get("exempt_reason"):
                er = await steps.fill_exempt_reason(page, plan["exempt_reason"])
                if not er.get("ok"):
                    return await fail(f"{label} 사유구분", er.get("reason"))
            fd = await steps.fill_fund_item(page)
            if not fd.get("ok"):
                return await fail(f"{label} 자금과목", fd.get("reason"))
            await emit_log(
                events,
                f"{label} 본문 반영 — 적요 '{item['note']}' · 예산단위 {item['budget_unit_name']} · "
                f"자금과목 {fd.get('name') or fd.get('code')}.",
                "ok",
            )

        if warns:
            await emit_log(
                events, f"⚠ 반영 미확인: {', '.join(warns)}(저장 후 값 확인 필요).", "warn"
            )
        await emit_shot(events.put, page)
        await emit_step(events, "apply_invoices", "done", _ms(t0))
        return {"filled": 1, "fill_warnings": warns}

    return apply_invoices
