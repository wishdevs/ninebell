"""일괄적용 배치 — 같은 (예산단위·프로젝트·적요) 그룹을 '일괄적용' 1회로 반영."""

from __future__ import annotations

from typing import Any

from app.live.events import emit_chat, emit_log
from nbkit.patterns import emit_shot

from .. import steps
from . import _shared


def _batch_key(w: dict) -> tuple:
    """일괄적용 그룹 키 — (예산단위 조합, 프로젝트/WBS, 적요) 가 모두 같으면 한 번에 반영."""
    bu = w.get("budgetUnit") or {}
    pj = w.get("project") or {}
    return (
        bu.get("code") or "",
        bu.get("bizplanNm") or "",
        bu.get("bgacctNm") or "",
        pj.get("code") or "",
        pj.get("wbsNo") or "",
        (w.get("note") or "").strip(),
    )


async def _apply_batch(
    page: Any,
    events: Any,
    rows_view: list[dict],
    work: list[dict],
    status: dict[int, str],
    notes: dict[int, str],
    *,
    chat_id: str,
) -> tuple[int, list[str], list[int]]:
    """행 배치를 반영. work 항목 = {idx(현재 그리드 행 인덱스), label(표시 행번호),
    budgetUnit, project, note}. 같은 (예산단위·프로젝트·적요)는 **한 번의 '일괄적용'으로
    묶어** 처리한다(사용자 확정 2026-07-04 — 피커/적용 왕복이 그룹당 1회). 실패는 그룹
    단위로 기록하고 배치를 중단하지 않는다.
    반환 (filled, failures, applied_idx — 성공 행 인덱스, 카드팝업 '적용' 체크 대상)."""
    filled = 0
    failures: list[str] = []
    applied_idx: list[int] = []
    # 등장 순서를 유지하며 그룹핑.
    groups: dict[tuple, list[dict]] = {}
    for w in work:
        groups.setdefault(_batch_key(w), []).append(w)
    total_groups = len(groups)
    for pos, members in enumerate(groups.values()):
        idxs = [m["idx"] for m in members]
        labels = "·".join(str(m["label"]) for m in members)
        first = members[0]
        bu = first.get("budgetUnit") or {}
        proj = first.get("project") or None
        note = first["note"]
        for m in members:
            notes[m["idx"]] = note
        if len(members) > 1:
            await emit_log(
                events,
                f"{labels}행 {len(members)}건 일괄 반영 중…(같은 예산단위·프로젝트·적요)",
                "info",
            )
        else:
            await emit_log(events, f"{labels}행 반영 중…", "info")
        collected = {
            "예산단위": bu.get("name") or "",
            # 조합 선택(BG×사업계획×예산계정) — 값이 있으면 그 행을 정확히 고른다.
            "예산단위_사업계획": bu.get("bizplanNm") or "",
            "예산단위_예산계정": bu.get("bgacctNm") or "",
            "프로젝트": (proj.get("name") if proj else "") or "",
            # WBS 행 단위 선택 — 값이 있으면 그 WBS 요소를 정확히 고른다.
            "프로젝트_wbsNo": (proj.get("wbsNo") if proj else "") or "",
            "적요": note,
        }
        ok, detail = await _apply_group_fields(page, events, idxs, collected)
        for m in members:
            if ok:
                filled += 1
                status[m["idx"]] = "done"
                applied_idx.append(m["idx"])
            else:
                status[m["idx"]] = "failed"
                failures.append(f"{m['label']}행: {detail}")
        if not ok:
            # 실패 사유를 실행 로그에도 남긴다 — 현황표(chat)만으론 종료 후 진단 불가(실전 런 교훈).
            await emit_log(events, f"{labels}행 반영 실패: {detail}", "warn")
        # 진행 현황 표를 그룹마다 갱신(같은 chat_id 로 대체) + 스냅샷.
        await emit_chat(
            events,
            chat_id=chat_id,
            role="assistant",
            content="처리 현황:\n\n" + _shared._status_table(rows_view, status, notes),
            streaming=False,
        )
        if (pos + 1) % 2 == 0 or pos == total_groups - 1:
            await emit_shot(events.put, page)
    return filled, failures, applied_idx


async def _apply_group_fields(
    page: Any, events: Any, rows: list[int], collected: dict[str, str]
) -> tuple[bool, str]:
    """같은 (예산단위·프로젝트·적요) 그룹을 **'일괄적용' 1회**로 반영.

    수순: 그룹 행별 적요 인라인 세팅 → 예산단위 피커 1회 → 프로젝트 피커 1회(값 있으면)
    → 그룹 행 전체 체크 → '일괄적용'. 반환 (ok, detail — 실제 선택된 이름, 리뷰 #1).
    적요 세팅 실패는 치명(리뷰 #11) — 적요 없이 반영하지 않는다.
    ⚠ **계정 피커는 열지 않는다** — 예산단위 선택으로 자동 결정된다(사용자 확정 2026-07-04,
    기존 acct_cd allow_default 자동축소 선택 제거).
    """
    for row in rows:
        note_res = await steps.set_note(page, row, collected["적요"])
        if not note_res.get("ok"):
            return False, f"적요 세팅 실패(행 {row + 1}): {note_res.get('err') or note_res.get('reason')}"
    applied: list[str] = []
    # 선택 단위 = (BG × 사업계획 × 예산계정) 조합 행 — 그 행을 정확히 고른다.
    r = await steps.fill_budget_codepicker(
        page,
        {
            "name": collected["예산단위"],
            "bizplanNm": collected.get("예산단위_사업계획", ""),
            "bgacctNm": collected.get("예산단위_예산계정", ""),
        },
    )
    if not r.get("ok"):
        return False, f"예산단위 '{collected['예산단위']}': {r.get('reason')}"
    await emit_log(events, f"예산단위 = {r.get('name')} (code {r.get('code')})", "info")
    applied.append(f"예산단위 {r.get('name')}")
    # 프로젝트는 선택하지 않을 수 있다(옵션) — 값이 있으면 WBS 행을 정확히 고른다.
    if (collected.get("프로젝트") or "").strip():
        r = await steps.fill_project_codepicker(
            page,
            {"name": collected["프로젝트"], "wbsNo": collected.get("프로젝트_wbsNo", "")},
        )
        if not r.get("ok"):
            return False, f"프로젝트 '{collected['프로젝트']}': {r.get('reason')}"
        await emit_log(events, f"프로젝트 = {r.get('name')} (code {r.get('code')})", "info")
        applied.append(f"프로젝트 {r.get('name')}")
    ap = await steps.apply_rows(page, rows)
    if not ap.get("ok"):
        return False, f"일괄적용 실패: {ap.get('reason')}"
    suffix = f" ({len(rows)}건 일괄)" if len(rows) > 1 else ""
    return True, " / ".join(applied) + f" / 적요 '{collected['적요']}'{suffix}"
