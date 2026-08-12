"""전자결재 상신 취소 — LangGraph 노드(진행 이벤트 + HITL 개입).

브라우저 조작은 전부 `steps.py`(프로브 이식)에 있고, 이 모듈은 **무엇을 얼마나 할지**만
결정한다: 취소 가능한 문서를 모아 사용자에게 보이고(HITL multiselect), 체크된 문서만
3단계(결재취소 → 상신취소 → 삭제)로 순회한다.

⚠⚠ 절대 안전 ⚠⚠
  - 후보는 **상신문서함의 '진행' 상태 문서**뿐이다(본인이 상신했고 아직 결재선에 있는 건).
  - 세 단계는 비가역이며 문서가 완전히 사라진다 — 그래서 자동 전량 처리를 하지 않고
    HITL 로 목록을 제시해 **사용자가 체크한 건만** 진행한다. 선택 0건이면 아무것도 하지 않는다.
  - 문서 식별은 제목 부분일치다. 선택한 제목이 목록에서 유일하지 않으면(동명·부분포함)
    어느 문서가 열릴지 확정할 수 없으므로 **아무것도 건드리지 않고 중단**한다.
  - 한 문서가 중간 단계에서 실패하면 즉시 중단하고, 어디까지 진행됐는지를 사유에 적는다
    (남은 선택 건은 손대지 않는다).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.live.events import emit_log, emit_step
from app.live.hitl import wait_hitl
from nbkit.patterns import emit_shot

from . import steps

logger = logging.getLogger(__name__)

CANCELABLE_STATUS = "진행"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _describe(row: dict) -> str:
    """개입 카드의 보조설명 — 기안일 · 결재자(있을 때). 제목만으론 같은 건이 구분되지 않는다."""
    parts = [row.get("date") or "", f"결재자 {row['approver']}" if row.get("approver") else ""]
    return " · ".join(p for p in parts if p)


def ambiguous_titles(rows: list[dict], titles: list[str]) -> list[str]:
    """리스트에서 유일하게 식별되지 않는 제목(동명 또는 다른 행 제목의 부분문자열)을 돌려준다.

    문서 클릭은 제목 **부분일치**로 하므로, 같은 리스트에 그 문자열을 포함한 행이 둘 이상이면
    대상을 특정할 수 없다. 브라우저를 건드리기 전에 순수 판정으로 걸러 낸다.
    """
    return [t for t in titles if sum(1 for r in rows if t in (r.get("text") or "")) != 1]


def make_enter_eap_node():
    """GNB '전자결재' 진입(iframe #content_UB 대기). 사용자유형 전환은 필요 없다."""

    async def enter_eap(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "enter_eap", "running")
        t0 = time.monotonic()
        r = await steps.enter_eap(page)
        if not r.get("ok"):
            await emit_step(events, "enter_eap", "failed")
            return {"error": r.get("reason") or "전자결재 화면에 진입하지 못했습니다."}
        await emit_log(events, "전자결재 화면 진입 완료.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "enter_eap", "done", _ms(t0))
        return {}

    return enter_eap


def make_list_docs_node():
    """상신문서함의 '진행' 문서를 모아 HITL(multiselect)로 취소 대상을 받는다."""

    async def list_docs(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "list_docs", "running")
        t0 = time.monotonic()

        if not await steps.click_menu(page, steps.MENU_SUBMITTED, steps.MENU_SUBMIT_GROUP):
            await emit_step(events, "list_docs", "failed")
            return {"error": "상신/보관함 > 상신문서 메뉴로 이동하지 못했습니다."}
        rows = await steps.wait_rows(page)
        await emit_shot(events.put, page)
        if not rows:
            await emit_step(events, "list_docs", "failed")
            return {"error": "상신문서 목록을 읽지 못했습니다(행 렌더 미확인)."}

        candidates = [
            r for r in rows if r.get("status") == CANCELABLE_STATUS and r.get("title")
        ]
        if not candidates:
            await emit_log(events, "'진행' 상태 문서가 없습니다 — 취소할 것이 없습니다.", "info")
            await emit_step(events, "list_docs", "done", _ms(t0))
            return {
                "picked": [],
                "result": f"취소 완료 — 상신문서 {len(rows)}건 중 '진행' 상태 문서가 없습니다.",
            }

        await emit_log(
            events,
            f"취소 가능한 문서 {len(candidates)}건(상신문서 첫 페이지 {len(rows)}건 중 '진행' 상태) — "
            "취소할 문서를 선택하는 개입을 띄웁니다.",
            "action",
        )
        options = [
            {
                "value": str(i),
                "label": r.get("title") or "(제목없음)",
                "description": _describe(r),
            }
            for i, r in enumerate(candidates)
        ]
        try:
            resp = await wait_hitl(
                events,
                kind="multiselect",
                title="전자결재 상신 취소",
                prompt=(
                    f"상신문서함 첫 페이지의 '진행' 상태 문서 {len(candidates)}건입니다. "
                    "취소할 문서만 체크하세요 — 선택한 문서는 결재취소 → 상신취소 → 삭제까지 "
                    "진행되어 완전히 사라집니다(복구 불가). 체크하지 않은 문서는 그대로 남습니다."
                ),
                options=options,
                owner=state.get("owner"),
                run_id=state.get("run_id"),
            )
        except TimeoutError:
            await emit_step(events, "list_docs", "failed")
            return {"error": "취소 선택 응답 시간 초과 — 아무것도 취소하지 않았습니다."}

        values = resp.get("values") if isinstance(resp, dict) else None
        idxs = sorted(
            {int(v) for v in (values or []) if str(v).isdigit() and 0 <= int(v) < len(candidates)}
        )
        if not idxs:
            await emit_log(events, "선택 없음 — 아무것도 취소하지 않고 종료합니다.", "info")
            await emit_step(events, "list_docs", "done", _ms(t0))
            return {"picked": [], "result": "취소 완료 — 선택한 문서가 없어 아무것도 취소하지 않았습니다."}

        picked = [candidates[i]["title"] for i in idxs]
        # 브라우저를 건드리기 전 사전 가드 — 제목이 유일하지 않으면 대상을 특정할 수 없다.
        bad = ambiguous_titles(rows, picked)
        if bad:
            await emit_step(events, "list_docs", "failed")
            return {
                "error": (
                    f"제목으로 대상을 특정할 수 없는 문서 {len(bad)}건({', '.join(bad[:3])}"
                    f"{'…' if len(bad) > 3 else ''}) — 목록에 같은 제목이거나 제목을 포함하는 "
                    "다른 문서가 있습니다. 아무것도 취소하지 않았습니다."
                )
            }
        head = ", ".join(picked[:5]) + ("…" if len(picked) > 5 else "")
        await emit_log(events, f"선택 {len(picked)}건 취소 진행 — {head}", "action")
        await emit_step(events, "list_docs", "done", _ms(t0))
        return {"picked": picked}

    return list_docs


def make_cancel_docs_node():
    """선택 건마다 결재취소 → 상신취소 → 삭제 → 임시보관 부재 확인. 실패 시 즉시 중단."""

    async def cancel_docs(state: dict) -> dict:
        if state.get("error"):
            return {}
        picked: list[str] = list(state.get("picked") or [])
        if not picked:
            return {}  # list_docs 가 이미 result 를 남겼다(선택 0건 / 후보 0건).
        events = state["events"]
        page = state["page"]
        total = len(picked)
        done: list[str] = []
        await emit_step(events, "cancel_docs", "running", progress={"done": 0, "total": total})
        t0 = time.monotonic()

        for title in picked:
            for phase_no, (menu_label, leaf, group, button) in enumerate(steps.PHASES, 1):
                r = await steps.cancel_phase(page, title, leaf, group, button)
                if not r.get("ok"):
                    await emit_step(events, "cancel_docs", "failed")
                    return {
                        "cancelled": done,
                        "error": _partial_failure(title, phase_no, menu_label, button, done, r),
                    }
                await emit_log(events, f"'{title}' — {menu_label} '{button}' 완료.", "info")

            # 성공 판정: 삭제 후 임시보관문서 리스트에서 그 문서가 사라졌는가.
            if not await steps.click_menu(page, steps.MENU_DRAFTBOX, steps.MENU_SUBMIT_GROUP):
                await emit_step(events, "cancel_docs", "failed")
                return {
                    "cancelled": done,
                    "error": (
                        f"'{title}' 삭제 후 임시보관문서로 이동하지 못해 잔존 여부를 확인하지 "
                        f"못했습니다. 앞서 취소 완료: {len(done)}건."
                    ),
                }
            if not await steps.wait_title(page, title, present=False, cap_ms=steps.GONE_CAP_MS):
                await emit_step(events, "cancel_docs", "failed")
                return {
                    "cancelled": done,
                    "error": (
                        f"'{title}' 삭제 후에도 임시보관문서에 남아 있습니다 — 옴니솔에서 직접 "
                        f"확인해 주세요. 앞서 취소 완료: {len(done)}건."
                    ),
                }
            done.append(title)
            await emit_log(events, f"'{title}' 취소 완료 — 임시보관 잔존 0 확인 ✅", "ok")
            await emit_shot(events.put, page)
            await emit_step(
                events, "cancel_docs", "running", progress={"done": len(done), "total": total}
            )

        await emit_step(events, "cancel_docs", "done", _ms(t0))
        head = ", ".join(done[:5]) + ("…" if len(done) > 5 else "")
        return {
            "cancelled": done,
            "result": (
                f"취소 완료 — 선택 {total}건 전부 결재취소·상신취소·삭제까지 처리하고 "
                f"임시보관 잔존 0을 확인했습니다. 문서: {head}"
            ),
        }

    return cancel_docs


def _partial_failure(
    title: str, phase_no: int, menu_label: str, button: str, done: list[str], r: dict
) -> str:
    """중간 실패 사유 — 이 문서가 **어느 상태에 남았는지**까지 적는다(수동 마무리용)."""
    left = {
        1: "상신문서(진행) 상태 그대로입니다 — 아무것도 바뀌지 않았습니다.",
        2: "결재취소까지만 되어 미결문서함에 있습니다 — 상신취소·삭제가 남았습니다.",
        3: "상신취소까지만 되어 임시보관문서함에 있습니다 — 삭제가 남았습니다.",
    }[phase_no]
    reason = r.get("reason") or f"{menu_label} '{button}' 실패"
    return (
        f"'{title}' {menu_label} 단계에서 중단 — {reason}\n"
        f"이 문서는 {left}\n"
        f"앞서 취소 완료: {len(done)}건{(' (' + ', '.join(done[:5]) + ')') if done else ''}. "
        "선택했던 나머지 문서는 손대지 않았습니다."
    )
