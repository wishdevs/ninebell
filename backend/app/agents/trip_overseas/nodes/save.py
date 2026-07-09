"""최종 저장(F7) 노드 — card save_document 재사용 + ERP 거부 시 재시도 신호.

card 와 달리 2패스·부가세구분이 없어 단순하다: filled>0 이면 저장하고, ERP 가 거부하면
MAX_SAVE_RETRIES 까지 retry_save 를 켜서 그래프가 menu_nav 로 되돌아가 문서를 새로 만들고
재입력한다(초안은 딥링크 재로드로 폐기). 저장(F7)은 여기서만 실행한다(팬텀 저장 방지는
card save_document 의 VALIDATION_TOAST+오류모달 감지에 위임).
"""

from __future__ import annotations

import time

from app.live.events import emit_chat, emit_log, emit_step
from nbkit.browser.actions import js_click
from nbkit.omnisol import js_lib, selectors
from nbkit.patterns import emit_shot

from ...card_collect import steps as card_steps

# ERP 저장 거부 시 그리드 재입력으로 되돌리는 최대 재시도 횟수(card 와 동일).
MAX_SAVE_RETRIES = 2

# F7 전 포커스를 본문으로 강제 — 잔존 셀 에디터/피커에 포커스가 남아 있으면 F7 이 본문 저장
# 핸들러에 닿지 않고 삼켜질 수 있다(리뷰 반영). 활성 요소 blur + body 포커스.
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
    """최종 저장(F7) 1회 — 반영 0건이면 저장하지 않음. 거부 시 MAX_SAVE_RETRIES 까지 재시도."""

    async def save_doc(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 저장하지 않음: {state.get('error')}", "retry_save": False}
        events = state["events"]
        page = state["page"]
        filled = state.get("filled", 0)
        await emit_step(events, "save_doc", "running")
        t0 = time.monotonic()

        if not filled:
            await emit_step(events, "save_doc", "done", _ms(t0))
            return {"result": "처리 완료 — 반영된 행이 없어 저장하지 않았습니다.", "retry_save": False}

        await emit_log(events, f"{filled}개 행 반영 완료 — 저장(F7)을 진행합니다.", "info")
        # F7 전 포커스를 본문으로 강제(잔존 에디터 포커스가 F7 을 삼키는 것 방지, 리뷰 반영).
        await page.evaluate(_BLUR_ACTIVE_JS)
        # ⚠ TODO(Phase 6): 저장 성공의 **양성 신호**(결의번호 채번·성공 토스트)는 실 F7 저장으로만
        #   실측 가능하다. 현재 save_document 는 실패 신호(검증 토스트·오류 모달) 부재로 ok 를 판정한다
        #   (card 와 동일). 실측 후 양성 신호 검증을 추가한다 — PROCESS.md '남은 작업' 플래그 참조.
        r = await card_steps.save_document(page, confirm=True)
        if not r.get("ok"):
            await emit_step(events, "save_doc", "failed")
            reason = r.get("reason") or str(r)
            # 검증성(결정적) 거부 = 동일 입력 재작성이 무의미(trip 은 HITL 이 없어 입력이 고정)
            # → 재시도 없이 즉시 실패. 재시도는 일시적(비결정적) 실패에만 한정한다.
            deterministic = (
                bool(r.get("toasts_seen"))
                or "검증 실패" in reason
                or "ERP 오류" in reason
                or "필수" in reason
            )
            retries = state.get("save_retries", 0)
            if not deterministic and retries < MAX_SAVE_RETRIES:
                await emit_chat(
                    events,
                    chat_id="trip-retry",
                    role="assistant",
                    content=(
                        f"저장 중 일시적 오류로 보입니다:\n{reason}\n\n"
                        "결의서를 새로 작성해 같은 입력으로 다시 시도합니다."
                        f"\n\n(재시도 {retries + 1}/{MAX_SAVE_RETRIES}회)"
                    ),
                    streaming=False,
                )
                await emit_log(
                    events,
                    f"저장 실패(일시적 추정) → 재작성 재시도 {retries + 1}/{MAX_SAVE_RETRIES}: {reason}",
                    "warn",
                )
                return {
                    "retry_save": True,
                    "save_retries": retries + 1,
                    "save_error_msg": reason,
                }
            # 결정적 거부(입력값 문제) 또는 재시도 소진 → 재시도 안내 없이 원인 그대로 실패.
            prefix = "저장이 ERP 에서 거부됨" if deterministic else f"저장 실패({retries}회 재시도 후 포기)"
            return {"error": f"{prefix}: {reason}", "retry_save": False}

        seen = r.get("modals_seen") or []
        if seen:
            await emit_log(
                events,
                "저장 중 확인창: "
                + " / ".join(f"[{m.get('title')}] {m.get('text', '')[:160]}" for m in seen[:3]),
                "info",
            )
        # 양성 신호 검증(실측 2026-07-07): 저장 성공의 확정 신호는 결의번호(ABDOCU_NO)가 아니라
        # (저장 시점엔 blank) **재조회 시 문서가 마스터 그리드에 지속(persist)** 하는 것이다. 팬텀
        # 저장이면 서버에 문서가 없어 재조회가 0건이 된다. 재조회로 확정 0건이면 실패로 승격한다
        # (rowcount 를 못 읽으면(-1/비정수) 판정 보류 — 기존 ok 유지, 오탐 방지).
        try:
            await js_click(page, selectors.BTN_LOOKUP)  # 조회(F2)
            persisted = -1
            for _ in range(15):  # 서버 재조회 안정 폴링(상한 ~12s)
                await page.wait_for_timeout(800)
                persisted = await page.evaluate(js_lib.ROWCOUNT_JS)
                if isinstance(persisted, int) and persisted >= 1:
                    break
            if isinstance(persisted, int) and persisted == 0:
                await emit_step(events, "save_doc", "failed")
                return {
                    "error": "저장 검증 실패 — F7 후 재조회에 문서가 없습니다(팬텀 저장 의심).",
                    "retry_save": False,
                }
            await emit_log(events, f"저장 양성 신호 확인 — 재조회 문서 지속(마스터 {persisted}건).", "ok")
        except Exception as exc:  # noqa: BLE001 — 재조회 검증 실패는 저장 판정을 뒤집지 않는다(보류).
            await emit_log(events, f"저장 재조회 검증 보류(무시): {exc}", "warn")
        await emit_log(events, "결의서 저장 시퀀스 완료(F7).", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "save_doc", "done", _ms(t0))
        return {"result": f"처리 완료 — {filled}개 행 입력·저장.", "retry_save": False}

    return save_doc
