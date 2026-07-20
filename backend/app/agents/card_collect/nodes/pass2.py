"""2차(불공) 단계 — 문서 반영(적용)·증빙유형 전환(재조회·매칭)·불공 반영."""

from __future__ import annotations

import time
from datetime import date

from app.agents.common.nodes import (
    make_add_row_node,
    make_open_evdn_node,
    make_select_evdn_node,
)
from app.live.events import emit_chat, emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps
from . import _shared, batch


# ── 문서 반영(적용) / 최종 저장(F7 은 마지막 1회, HITL 확인 후) ─────────────────────
# 업무 규칙(사용자 확정 2026-07-02): 과세 적용 → (저장 없이) F3 새 행 → 불공 진행·적용 →
# **마지막에만 저장(F7) 1회**. 적용은 draft(문서 반영, 전표 미생성)라 확인 없이 자동 진행.
async def _apply_doc(state: dict, *, label: str, step_key: str, applied_idx: list[int]) -> dict:
    """처리 행 체크 → 카드팝업 '적용' → '선택'(부가세0 포함? 예) → '예산현황' 확인 →
    팝업 닫힘·문서 반영(steps.apply_rows_to_document). 실패 시 화면 모달 텍스트 노출.
    반환 {"applied": True} | {"error": ...}."""
    events = state["events"]
    page = state["page"]
    ap = await steps.apply_rows_to_document(page, applied_idx)
    if not ap.get("ok"):
        modal_txt = "; ".join(
            f"[{m.get('title')}] {m.get('text', '')[:80]}" for m in (ap.get("modals") or [])[:2]
        )
        await emit_shot(events.put, page)
        await emit_step(events, step_key, "failed")
        return {
            "error": (
                f"{label} 적용 실패: {ap.get('reason')}"
                + (f" — 화면 메시지: {modal_txt}" if modal_txt else "")
            )
        }
    await emit_log(events, f"{label} {len(applied_idx)}건 결의서 반영(적용) 완료(저장 전).", "ok")
    await emit_shot(events.put, page)
    return {"applied": True}


def make_apply_doc_node():
    """1차(과세) 문서 반영(적용) — HITL 없음(draft). 0건이면 스킵하고 2차로."""

    async def apply_doc(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 반영하지 않음: {state.get('error')}"}
        events = state["events"]
        filled = state.get("filled", 0)
        await emit_step(events, "apply_doc", "running")
        t0 = time.monotonic()
        if not filled:
            await emit_step(events, "apply_doc", "done", _shared._ms(t0))
            await emit_log(events, "1차(과세) 반영 건이 없어 적용 없이 2차로 진행합니다.", "info")
            return {}
        out = await _apply_doc(
            state,
            label="법인카드(과세분)",
            step_key="apply_doc",
            applied_idx=state.get("pass1_applied_idx") or [],
        )
        if out.get("error"):
            return {"error": out["error"]}
        await emit_step(events, "apply_doc", "done", _shared._ms(t0))
        # 적용으로 팝업이 닫힘 — 2차는 새 상세행 추가(F3)부터 다시 플로우를 탄다(사용자 업무 규칙).
        return {"pass1_doc_applied": True}

    return apply_doc

    return save


# ── 2차: 증빙유형 전환(법인카드(불공)) → 재조회·매칭 ───────────────────────────────
def make_switch_evdn_node():
    """카드 팝업 닫기 → 증빙유형 02 재선택 → 카드/기간/조회 재실행 → 1차 입력값 행 매칭.

    프로브 실측(2026-07-02): 팝업 '닫기' 후 같은 행에서 open_evdn→select_evdn("02") 이
    F3 없이 동작. 매칭 키 = (APRVL_NO, TRAN_DT, TRAN_AMT) — 승인/취소 쌍 구분.
    """

    async def switch_evdn(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        pending: list[dict] = state.get("pending_nontax") or []
        await emit_step(events, "switch_evdn", "running")
        t0 = time.monotonic()
        if not pending:
            await emit_log(events, "불공(비과세) 대상이 없어 2차를 생략합니다.", "info")
            await emit_step(events, "switch_evdn", "done", _shared._ms(t0))
            return {"pass2_work": []}

        # 잔여 확인 모달('예산현황' 등)이 남아 있으면 F3/코드피커가 막힌다 — 방어적 정리.
        # (실측: 적용 후 지연 모달이 화면을 덮은 채 02 선택 시도 → TypeError 실패)
        cleared = await steps.dismiss_blocking_modals(page, rounds=3)
        if cleared:
            await emit_log(events, f"잔여 확인 모달 {len(cleared)}건을 닫고 진행합니다.", "info")

        r = await steps.close_card_popup(page)
        if not r.get("ok"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": f"카드 팝업 닫기 실패: {r.get('reason')}"}
        # 증빙유형 재선택 — 진입 공용 노드 재사용(state error 규약 공유, 스텝은 자체 방출).
        # 업무 규칙(사용자 확정): 1차 적용('적용' 클릭·문서 반영)을 했다면 **새 상세행 추가(F3)
        # 후** 다시 증빙유형부터 플로우를 탄다. 적용을 생략한 경우(과세 0건)는 기존 행에서
        # 재선택(프로브 실측: F3 불필요). 재선택 실패 시 F3 1회 폴백은 안전망으로 유지.
        if state.get("pass1_doc_applied"):
            await emit_log(events, "1차 적용 완료 — 새 상세행(F3) 추가 후 불공 플로우를 진행합니다.", "info")
            out = await make_add_row_node()(state)
            state.update(out or {})
            if state.get("error"):
                await emit_step(events, "switch_evdn", "failed")
                return {"error": state["error"]}
        out = await make_open_evdn_node()(state)
        state.update(out or {})
        if state.get("error") and not state.get("pass1_doc_applied"):
            await emit_log(events, "증빙 에디터 재오픈 실패 — 새 행(F3) 추가 후 재시도합니다.", "warn")
            state.pop("error", None)
            out = await make_add_row_node()(state)
            state.update(out or {})
            if not state.get("error"):
                out = await make_open_evdn_node()(state)
                state.update(out or {})
        if state.get("error"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": state["error"]}
        out = await make_select_evdn_node("02")(state)
        state.update(out or {})
        if state.get("error"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": state["error"]}

        r = await steps.select_all_cards(page, owner_name=state.get("userid"))
        if not r.get("ok"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": f"2차 카드 전체선택 실패: {r.get('reason')}"}
        period = state.get("period") or list(
            steps.compute_period(date.today(), _shared._params_cutoff_day(state))
        )
        pr = await steps.set_period(page, period[0], period[1])
        if not pr.get("ok"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": f"2차 승인일 기간 설정 실패: {pr}"}
        rows2 = await steps.run_query(page)
        if not isinstance(rows2, int) or rows2 < 0:
            await emit_step(events, "switch_evdn", "failed")
            return {"error": "2차 조회에 실패했습니다(그리드 로딩 실패)."}
        lst2 = await steps.read_rows(page, limit=500)
        # 2차 조회 리스트 전문 로깅 — 1차에서 적용된 행이 '처리여부' 전환 실패로 재출현하는
        # 이상 징후(실전 관찰: 불공 리스트 2건) 진단용. 승인번호·금액·부가세구분을 남긴다.
        summary2 = ", ".join(
            f"{(r.get('TRAN_NM') or '?')[:10]} {r.get('TRAN_AMT', '?')}"
            f"(승인 {r.get('APRVL_NO', '?')}·부가세구분 '{r.get('VAT_TP', '')}')"
            for r in lst2[:8]
        )
        await emit_log(events, f"2차(불공) 조회 {len(lst2)}건: {summary2}", "info")
        expected2 = len(pending)
        if len(lst2) > expected2:
            await emit_log(
                events,
                f"⚠ 2차 조회가 예상({expected2}건)보다 많음 — 1차 적용 행 중 처리 전환 안 된 행이 "
                "재출현했을 수 있음(승인취소 행 여부 확인 필요).",
                "warn",
            )

        # 키당 후보 큐 — 동일 복합키(같은 승인번호·일자·금액) 행이 여러 건이어도 각 pending 이
        # 서로 다른 실제 행을 1:1 소비한다. setdefault(단일 보관)면 두 입력이 같은 행에 이중
        # 반영되고 다른 행은 조용히 누락된다(리뷰 HIGH #1).
        by_key: dict[str, list[dict]] = {}
        for r2 in lst2:
            by_key.setdefault(_shared._row_key(r2), []).append(r2)
        work: list[dict] = []
        unmatched: list[str] = []
        for p in pending:
            queue = by_key.get(p["key"]) or []
            # 재조회에서 사라진(큐 소진) 행만 배제(실패 기록). ⚠ ERP VAT_TP=='과세' 로는 제외하지
            # 않는다 — **매입세액 불공제**(복리후생비-업무·해외출장·유류·접대비류 또는 AI 판정, vat.classify_vat)
            # 행은 ERP 상 VAT_TP 가 '과세'인데도 우리가 의도적으로 불공으로 분류한 것이라, 여기서
            # VAT_TP='과세' 로 되제외하면 계정/AI 기반 불공이 통째로 누락된다(실측: 네이버파이낸셜㈜).
            hit = queue.pop(0) if queue else None
            if hit is None:
                unmatched.append(f"{p['label']}행({p.get('merchant', '')})")
                continue
            work.append(
                {
                    "idx": hit.get("i"),
                    "label": p["label"],
                    "budgetUnit": p["budgetUnit"],
                    "project": p["project"],
                    "note": p["note"],
                }
            )
        if unmatched:
            await emit_log(
                events,
                f"2차 재조회 매칭 실패 {len(unmatched)}건(반영 제외): {', '.join(unmatched[:5])}",
                "warn",
            )
        await emit_log(
            events, f"증빙유형 '법인카드(불공)' 전환 완료 — 2차 대상 {len(work)}건.", "ok"
        )
        await emit_shot(events.put, page)
        await emit_step(events, "switch_evdn", "done", _shared._ms(t0))
        return {
            "rows2_list": lst2,
            "pass2_work": work,
            "pass2_unmatched": len(unmatched),
            "pass2_unmatched_desc": ", ".join(unmatched[:5]),
        }

    return switch_evdn


def make_apply_pass2_node():
    """2차(불공) 반영 — 1차 그리드에서 보존한 입력값을 매칭 행에 순차 적용(재입력 없음)."""

    async def apply_pass2(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        work: list[dict] = state.get("pass2_work") or []
        await emit_step(events, "apply_pass2", "running")
        t0 = time.monotonic()
        if not work:
            # switch_evdn 이 불공 재조회로 연 법인카드 팝업이 남아 있으면 닫는다(불공 0매칭). 안 닫으면
            # save_final 의 F7 이 '카드팝업 열림(적용 단계 누락)'으로 잘못 막힌다. 이미 닫혔으면 no-op.
            await steps.close_card_popup(page)
            await emit_step(events, "apply_pass2", "done", _shared._ms(t0))
            return {"pass2_filled": 0}
        rows2: list[dict] = state.get("rows2_list") or []
        target_idx = {w["idx"] for w in work}
        rows_view = [r for r in rows2 if r.get("i") in target_idx]
        status2: dict[int, str] = {r.get("i"): "pending" for r in rows_view}
        notes2: dict[int, str] = {w["idx"]: w["note"] for w in work}
        filled2, failures2, applied2_idx = await batch._apply_batch(
            page, events, rows_view, work, status2, notes2, chat_id="cc-status2"
        )
        unmatched_n = state.get("pass2_unmatched", 0)
        summary = (
            f"2차(법인카드·불공) 반영 {filled2}건 · 매칭 실패 {unmatched_n}건 · "
            f"실패 {len(failures2)}건"
        )
        if unmatched_n:
            # 재조회에서 못 찾은 거래는 반영이 누락된 것 — 요약에 반드시 노출(리뷰 HIGH #2).
            summary += f"\n\n⚠ 매칭 실패(수동 확인 필요): {state.get('pass2_unmatched_desc', '')}"
        if failures2:
            summary += "\n\n실패 상세:\n- " + "\n- ".join(failures2)
        await emit_chat(
            events,
            chat_id="cc-summary2",
            role="assistant",
            content=summary + "\n\n" + _shared._status_table(rows_view, status2, notes2),
            streaming=False,
        )
        await emit_log(events, f"2차(불공) 처리 완료 — {filled2}건 반영(저장 전).", "ok")
        # 불공분도 문서에 반영(적용) — 저장(F7)은 마지막 save_final 에서 1회만.
        if applied2_idx:
            out = await _apply_doc(
                state, label="법인카드(불공분)", step_key="apply_pass2", applied_idx=applied2_idx
            )
            if out.get("error"):
                return {"error": out["error"]}
        else:
            # 적용된 행이 없으면 _apply_doc(=팝업 닫기)가 안 도므로, 재조회로 열린 팝업을 직접 닫아
            # save_final F7 이 '팝업 열림'으로 오도되지 않게 한다(불공 전건 매칭/적용 실패).
            await steps.close_card_popup(page)
        await emit_step(events, "apply_pass2", "done", _shared._ms(t0))
        return {"pass2_filled": filled2, "pass2_applied_idx": applied2_idx, "pass2_failed": len(failures2)}

    return apply_pass2
