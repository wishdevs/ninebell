"""최종 저장(F7) 노드 — 게이트(card save_document) + **독립 재조회**로 성공 판정.

trip_domestic save_doc 와 같은 규율(F7 사전 팝업 0 확인·commit shield·반려 토스트 사유
그대로 노출·재조회 지속 검증)이되, 세금계산서 델타가 하나 있다: 재조회(F2) 시 증빙 문맥에
따라 "전자발행된 증빙으로 입력하시겠습니까?" 게이트 다이얼로그가 다시 뜰 수 있다 —
"아니요"로 닫고 마스터 지속을 확인한다(다이얼로그 응답은 성공 판정이 아니다).

⚠ 상신(결재)은 절대 하지 않는다 — 사용자가 ERP 에서 직접(PROCESS.md D11).
⚠ 저장 거부 시 재작성 재시도는 두지 않는다 — 입력이 실행 전 폼/HITL 로 고정돼 동일 입력
  재작성이 무의미하고, 사유(토스트/모달 전문)를 그대로 노출하는 것이 실패 정책이다.
"""

from __future__ import annotations

import time

from app.agents.card_collect import steps as card_steps
from app.agents.common.commit_shield import shielded_commit
from app.live.events import emit_log, emit_step
from nbkit.browser.actions import js_click
from nbkit.omnisol import js_lib, selectors, verify
from nbkit.patterns import emit_shot

from ..steps import GATE_DIALOG_HINT, _click_modal

# 잔존 셀 에디터 포커스가 F7 을 삼키는 것 방지(trip 동일).
_BLUR_ACTIVE_JS = """() => {
  try {
    const a = document.activeElement; if (a && a.blur) a.blur();
    if (document.body && document.body.focus) document.body.focus();
    return true;
  } catch (e) { return false; }
}"""


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_save_doc_node():
    """F7 1회 — filled>0 일 때만. 반려 토스트/오류 모달 사유를 그대로 error 로 노출."""

    async def save_doc(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 저장하지 않음: {state.get('error')}"}
        if state.get("aborted"):
            return {}  # HITL 빈 선택 등 우아한 종료 — pick 노드가 result 를 이미 남겼다.
        events = state["events"]
        page = state["page"]
        await emit_step(events, "save_doc", "running")
        t0 = time.monotonic()
        if not state.get("filled"):
            await emit_step(events, "save_doc", "done", _ms(t0))
            return {"result": "처리 완료 — 반영된 행이 없어 저장하지 않았습니다."}

        await emit_log(events, "본문 반영 완료 — 저장(F7)을 진행합니다.", "info")
        await page.evaluate(_BLUR_ACTIVE_JS)
        # F7 사전 조건: 열린 팝업 0 — 잔존 k-window 는 F7 을 삼켜 팬텀 저장을 만든다(trip 동일).
        popups = await verify.confirm(
            lambda: page.evaluate(js_lib.POPUP_COUNT_JS),
            lambda n: isinstance(n, int) and n == 0,
            timing=verify.ASYNC,
            what="F7 직전 열린 팝업 수",
            expected=0,
            unknown_when=lambda n: not isinstance(n, int),
        )
        if popups.mismatch:
            await emit_step(events, "save_doc", "failed")
            # 진단 강화(team-lead 지시, 2026-08-19) — 잔존 팝업의 타이틀을 메시지에 포함해
            # SPLIT11 스모크 실패의 정체(예산현황 잔존? CC/PJT 피커 잔존?)를 바로 알 수 있게 한다.
            try:
                snapshot = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
            except Exception:  # noqa: BLE001 — 진단 실패가 원래 실패 판정을 가리면 안 된다.
                snapshot = None
            titles = [str((m or {}).get("title") or "").strip() for m in (snapshot or [])]
            titles = [t for t in titles if t]
            title_note = f" 잔존 팝업 타이틀: {titles}" if titles else " 잔존 팝업 타이틀 확인 불가."
            msg = (
                f"저장(F7) 중단 — 열린 팝업이 {popups.actual}개 남아 있습니다."
                f"{title_note} 잔존 팝업은 F7 을 삼켜 팬텀 저장을 유발합니다."
            )
            await emit_log(events, msg, "error")
            await emit_shot(events.put, page)
            return {"error": msg}
        if popups.unknown:
            await emit_log(events, f"F7 직전 팝업 수 확인 불가 — 진행: {popups.reason}", "warn")

        # F7 + "저장하시겠습니까? 예" — card save_document 가 확인 모달을 처리하고, 반려
        # 토스트(VALIDATION_TOAST_JS)·오류 모달 전문을 reason 으로 돌려준다(실패 표면화).
        r = await shielded_commit(
            lambda: card_steps.save_document(page, confirm=True), events=events, label="저장(F7)"
        )
        if not r.get("ok"):
            await emit_step(events, "save_doc", "failed")
            reason = r.get("reason") or str(r)
            return {"error": f"저장이 ERP 에서 거부됨: {reason}"}
        seen = r.get("modals_seen") or []
        if seen:
            await emit_log(
                events,
                "저장 중 확인창: "
                + " / ".join(f"[{m.get('title')}] {m.get('text', '')[:160]}" for m in seen[:3]),
                "info",
            )

        # 성공 판정 = **독립 재조회**(다이얼로그 응답이 아님): 조회(F2) 후 마스터 그리드에
        # 문서가 지속하는지 본다. 팬텀 저장이면 0건 → 하드 실패로 승격(녹화 4건 전부 팬텀 선례).
        try:
            await js_click(page, selectors.BTN_LOOKUP)
            # 세금계산서 델타: 재조회 시 "전자발행된 증빙…" 게이트가 다시 뜰 수 있다 — "아니요".
            for _ in range(10):
                await page.wait_for_timeout(300)
                modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
                gate = next(
                    (m for m in (modals or []) if GATE_DIALOG_HINT in (m.get("text") or "")), None
                )
                if gate:
                    await _click_modal(page, "아니요")
                    break
            persisted = await verify.confirm_grid_rows(
                page,
                index=0,
                min_rows=1,
                timing=verify.HEAVY,
                unknown_when=lambda v: not isinstance(v, int) or v < 0,
            )
            if persisted.mismatch:  # 읽었는데 0건 = 서버에 문서 없음(팬텀).
                await emit_step(events, "save_doc", "failed")
                return {"error": "저장 검증 실패 — F7 후 재조회에 문서가 없습니다(팬텀 저장 의심)."}
            if persisted.unknown:
                await emit_log(events, f"저장 재조회 검증 보류 — {persisted.reason}", "warn")
            else:
                await emit_log(
                    events, f"저장 양성 신호 확인 — 재조회 문서 지속(마스터 {persisted.actual}건).", "ok"
                )
        except Exception as exc:  # noqa: BLE001 — 재조회 검증 실패는 저장 판정을 뒤집지 않는다(보류).
            await emit_log(events, f"저장 재조회 검증 보류(무시): {exc}", "warn")

        await emit_log(events, "결의서 저장 시퀀스 완료(F7). 상신은 ERP 에서 직접 진행하세요.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "save_doc", "done", _ms(t0))
        plan = state.get("plan") or {}
        # 분할 행수는 **실제로 쓴 계획**에서 센다 — 발행 후는 개입(state.split_plan)에서 오고
        # plan.split_rows 는 폼 경로 전용이라, 종전처럼 plan 만 보면 개입 분할이 '0행'으로
        # 잘못 보고됐다(2026-08-25 증빙 11 실측 — 실제로는 2행이 반영됐다).
        split_rows = state.get("split_plan") or plan.get("split_rows") or []
        return {
            "result": (
                f"처리 완료 — 세금계산서 결의서 저장(증빙 {plan.get('evidence_code')}"
                f"{' · 분할 ' + str(len(split_rows)) + '행' if plan.get('split') else ''}). "
                "상신은 ERP 에서 직접 진행하세요."
            )
        }

    return save_doc
