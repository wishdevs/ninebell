"""발행 후 — 전자세금계산서 팝업 조회 + 계산서 그리드 개입(kind="invoice-grid").

발행 전·수동분할 실행에서는 이 노드가 스킵된다(계산서 조회 없음).
발행 후에는 조회(F2)→게이트 "예"→팝업→기간 조회로 계산서 목록을 얻고, **법인카드 그리드와
같은 방식**으로 행 선택 + **선택 행별 예산단위·프로젝트·적요**를 한 화면에서 받는다
(PROCESS.md D1 — 2026-08-20 재확정: 발행 후 항목은 행마다 달라 실행 전 폼으로 못 받는다).

HITL 계약(프론트 확정 — src/lib/live/types.ts):
  프레임 kind="invoice-grid" + invoiceRows(InvoiceGridRow[]) + split(bool) +
  budgetUnits(HitlBudgetUnits) + projects(HitlProjects, favorites 만) — types.ts:242-267.
  응답 rows(GridRowSubmit[]: no·budgetUnit·project·note·skip) + splitPlan(SplitPlanRowSubmit[])
  — types.ts:269-300 / backend/app/routers/runs.py:116-138·193-194.
  ⚠ 선택 여부는 **skip 필드**다(선택=skip:false). 빈 선택 = 저장 없이 우아하게 종료(aborted).
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.agents.card_collect.nodes import _shared as card_shared
from app.agents.card_collect.nodes import catalog as card_catalog
from app.live.events import emit_log, emit_step
from app.live.hitl import wait_hitl
from app.services.code_sync import dept_matches_budget_name
from nbkit.patterns import emit_shot

from .. import steps

logger = logging.getLogger("app.agents.tax_invoice.invoice_pick")


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _amount(value: object) -> int | None:
    """그리드 금액(정수/실수/'1,234' 문자열) → 정수. 파싱 불가는 None(프론트가 빈 칸 처리)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _invoice_date(value: object) -> str:
    """계산서일 — compact 'YYYYMMDD' 는 보기 좋게 끊어 준다."""
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def invoice_grid_row(i: int, r: dict) -> dict:
    """팝업 그리드 행 → InvoiceGridRow(types.ts:100-116). no 는 1-based 행 식별자."""
    return {
        "no": i + 1,
        "invoiceDate": _invoice_date(r.get("START_DT")),
        "partnerName": str(r.get("PARTNER_NM") or ""),
        "partnerCode": str(r.get("PARTNER_CD") or ""),
        "supplyAmount": _amount(r.get("SPPRC_AMT")),
        "taxAmount": _amount(r.get("VAT_AMT")),
        "sumAmount": _amount(r.get("SUM_AMT")),
        "ntsAprvlNo": str(r.get("NTS_APRVL_NO") or ""),
        "itemName": str(r.get("ITEM_NM") or ""),
        "dataKind": str(r.get("DATA_FG_NM") or ""),
    }


async def load_catalogs(owner: str | None) -> tuple[dict, list[dict]]:
    """개입 화면 선택지 — (budgetUnits, projects.favorites). 카드 그리드와 같은 출처·캡.

    예산단위는 즐겨찾기 + '내 부서' 매칭분(전사 전체는 과다 — card_collect 사용자 확정 관례).
    카탈로그 조회 실패는 런을 죽이지 않는다(즐겨찾기만으로 진행 가능).
    """
    budget_favs, project_favs, department = await card_catalog._load_user_favorites(owner)
    try:
        all_units = await card_catalog._load_budget_catalog()
    except Exception:  # noqa: BLE001 — 카탈로그 실패로 런을 죽이지 않는다.
        logger.exception("tax-invoice budget catalog load failed")
        all_units = []
    mine = [u for u in all_units if dept_matches_budget_name(department, u.get("name"))]
    budget_units = {
        "favorites": budget_favs[: card_shared._MAX_FAVORITES],
        "mine": mine[: card_shared._MAX_BUDGET_UNITS],
    }
    return budget_units, project_favs[: card_shared._MAX_FAVORITES]


def parse_invoice_submission(resp: object, row_count: int) -> tuple[list[dict], str | None]:
    """개입 응답 rows → 선택 행 목록. 반환 (selection, 한국어 오류|None).

    선택 = skip 이 아닌 행. 선택 행은 예산단위·적요가 필수다(카드 그리드와 같은 계약).
    범위 밖 no·중복은 버린다(경계 방어 — 프론트 계약 위반이 실행을 오염시키지 않게).
    """
    rows = resp.get("rows") if isinstance(resp, dict) else None
    if not isinstance(rows, list):
        return [], None
    selection: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("skip"):
            continue
        no = row.get("no")
        if not isinstance(no, int) or not (1 <= no <= row_count) or no in seen:
            continue
        seen.add(no)
        budget = row.get("budgetUnit") or {}
        project = row.get("project") or None
        note = str(row.get("note") or "").strip()
        if not budget.get("name"):
            return [], f"{no}번 계산서의 예산단위가 비어 있습니다 — 선택한 행은 예산단위를 지정해야 합니다."
        if not note:
            return [], f"{no}번 계산서의 적요가 비어 있습니다 — 선택한 행은 적요를 입력해야 합니다."
        selection.append(
            {
                "no": no,
                "index": no - 1,  # 팝업 그리드 행 인덱스(0-based).
                "budget_unit_name": str(budget.get("name") or "").strip(),
                "budget_unit_code": str(budget.get("code") or "").strip(),
                "project_wbs": str((project or {}).get("wbsNo") or (project or {}).get("code") or "").strip(),
                "project_name": str((project or {}).get("name") or "").strip(),
                "note": note,
            }
        )
    return sorted(selection, key=lambda s: s["no"]), None


def parse_split_plan(resp: object) -> tuple[list[dict], str | None]:
    """개입 응답 splitPlan → 분할 노드 계약(note/amount/cost_center/project_wbs)으로 정규화.

    마지막 행 amount=None = 차액반영(ERP 가 잔액 흡수 — 계산해 보내지 않는다, types.ts:288-300).
    """
    plan = resp.get("splitPlan") if isinstance(resp, dict) else None
    if not isinstance(plan, list) or not plan:
        return [], None
    rows: list[dict] = []
    for i, r in enumerate(plan):
        if not isinstance(r, dict):
            return [], f"분할 {i + 1}행 형식이 올바르지 않습니다."
        note = str(r.get("note") or "").strip()
        cost_center = str(r.get("costCenter") or "").strip()
        wbs = str(r.get("projectWbs") or "").strip()
        if not note:
            return [], f"분할 {i + 1}행 적요가 비어 있습니다."
        if not cost_center:
            return [], f"분할 {i + 1}행 비용센터가 비어 있습니다."
        if not wbs:
            return [], f"분할 {i + 1}행 프로젝트가 비어 있습니다."
        amount = r.get("amount")
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int)):
            return [], f"분할 {i + 1}행 금액은 정수여야 합니다: {amount!r}"
        if amount is not None and i == len(plan) - 1:
            pass  # 마지막 행 금액 명시도 허용(차액반영을 안 쓰는 계획).
        rows.append({"note": note, "amount": amount, "cost_center": cost_center, "project_wbs": wbs})
    for i, r in enumerate(rows[:-1]):
        if r["amount"] is None:
            return [], f"분할 금액 비움(차액반영)은 마지막 행에만 허용됩니다(행 {i + 1})."
    return rows, None


def make_pick_invoices_node():
    """발행 후 전용 — 계산서 목록 조회 + 그리드 개입(선택·행별 입력·분할계획)."""

    async def pick_invoices(state: dict) -> dict:
        if state.get("error") or state.get("aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        plan = state.get("plan") or {}
        await emit_step(events, "pick_invoices", "running")
        t0 = time.monotonic()
        if plan.get("issue") != "post":
            await emit_log(events, "발행 전 — 계산서 조회를 건너뜁니다.", "info")
            await emit_step(events, "pick_invoices", "done", _ms(t0))
            return {}

        r = await steps.open_invoice_list(page, plan["period_from"], plan["period_to"])
        if not r.get("ok"):
            await emit_step(events, "pick_invoices", "failed")
            return {"error": r.get("reason") or "전자세금계산서 팝업 진입 실패"}
        rows = r.get("rows") or []
        for entry in r.get("gate_chain") or []:
            if entry.get("kind") == "draft":
                # ❓ 실측 대기: '조회를 계속' 이후 작성 중 상세행이 유지되는지.
                await emit_log(
                    events,
                    "조회 전 '저장하지 않은 데이터' 확인에 '예'로 응답 — 응답 직후 상세 행수 "
                    f"{entry.get('detail_rows_after')}.",
                    "info",
                )
        await emit_shot(events.put, page)
        if not rows:
            await emit_step(events, "pick_invoices", "failed")
            if r.get("settled") is False:
                return {
                    "error": (
                        "계산서 목록이 로딩 중에 확정되지 않았습니다(행수 안정 실패) — "
                        "0건인지 판단할 수 없어 중단합니다. 잠시 후 다시 실행해 주세요."
                    )
                }
            return {
                "error": (
                    f"조회기간({plan['period_from']}~{plan['period_to']})에 전자발행 계산서가 "
                    f"없습니다(조회 {r.get('attempts', 1)}회 실행) — 기간을 바꿔 다시 실행하세요."
                )
            }

        split = bool(plan.get("split"))
        budget_units, project_favs = await load_catalogs(state.get("owner"))
        grid_rows = [invoice_grid_row(i, row) for i, row in enumerate(rows)]
        await emit_log(
            events,
            f"전자발행 계산서 {len(rows)}건 조회 — 처리할 행을 고르고 행별 예산단위·프로젝트·"
            "적요를 입력하는 개입을 띄웁니다. ⚠ 취소분(음수)을 원거래와 함께 고르면 총액이 상계됩니다.",
            "action",
        )
        prompt = (
            "처리할 계산서를 고르고 행별로 예산단위·프로젝트·적요를 입력한 뒤 '입력 완료'를 "
            "누르세요. 공급가액·회계일은 선택한 계산서에서 자동 반영됩니다."
        )
        if split:
            prompt += " 비용분할 계획(행별 금액·비용센터·프로젝트·적요)도 함께 입력하세요."
        try:
            resp = await wait_hitl(
                events,
                kind="invoice-grid",
                title="세금계산서",
                prompt=prompt,
                extra={
                    "invoiceRows": grid_rows,
                    "split": split,
                    "budgetUnits": budget_units,
                    "projects": {"favorites": project_favs, "searchResults": None, "query": None},
                },
                owner=state.get("owner"),
                run_id=state.get("run_id"),
            )
        except asyncio.TimeoutError:
            await emit_step(events, "pick_invoices", "failed")
            return {"error": "계산서 선택 응답 시간 초과 — 저장하지 않았습니다."}

        selection, err = parse_invoice_submission(resp, len(rows))
        if err:
            await emit_step(events, "pick_invoices", "failed")
            return {"error": err}
        if not selection:
            await emit_log(events, "선택 없음 — 저장하지 않고 종료합니다.", "info")
            await emit_step(events, "pick_invoices", "done", _ms(t0))
            return {"aborted": True, "result": "선택한 계산서가 없어 저장하지 않고 종료했습니다."}

        split_plan: list[dict] = []
        if split:
            split_plan, err = parse_split_plan(resp)
            if err:
                await emit_step(events, "pick_invoices", "failed")
                return {"error": err}
            if not split_plan:
                await emit_step(events, "pick_invoices", "failed")
                return {"error": "비용분할 계획(splitPlan)이 비어 있습니다 — 분할 행을 입력해 주세요."}
            if len(selection) > 1:
                await emit_step(events, "pick_invoices", "failed")
                return {
                    "error": (
                        f"비용분할은 계산서 1건만 선택할 수 있습니다(현재 {len(selection)}건) — "
                        "분할 계획은 선택한 1건의 금액을 쪼갭니다."
                    )
                }

        # 재조회 재매칭용 원본 요약을 달아 둔다(복수 순차 적용 — apply_invoices ❓ 구조).
        for s in selection:
            s["grid_row"] = grid_rows[s["index"]]

        picked = ", ".join(f"{s['no']}번({s['budget_unit_name']})" for s in selection[:5])
        await emit_log(
            events,
            f"계산서 {len(selection)}건 선택 — {picked}{'…' if len(selection) > 5 else ''}."
            + (f" 분할 계획 {len(split_plan)}행." if split_plan else ""),
            "ok",
        )
        await emit_step(events, "pick_invoices", "done", _ms(t0))
        return {
            "invoice_picked": [s["index"] for s in selection],
            "invoice_selection": selection,
            "split_plan": split_plan,
        }

    return pick_invoices
