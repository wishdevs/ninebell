"""최종 저장(F7) 노드 — ERP 거부 파싱·조치 안내·그리드 재시도 신호."""

from __future__ import annotations

import re
import time

from app.live.events import emit_chat, emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps
from . import _shared


# 저장(F7)이 ERP 에서 거부되면 그리드 재선택으로 되돌리는 최대 재시도 횟수(방식 1).
# (2026-07-20 임시로 0 으로 껐다가 저장/불공 근본수정 후 재활성화 — 사용자 요청.) 0 = 재시도 없이
# 1회 실패 즉시 종료(사유+조치는 배너/결과/터미널에 노출).
MAX_SAVE_RETRIES = 2

# ERP 저장 거부 모달 파싱 — 승인번호·요구 계정을 뽑아 '어느 행을 어떤 계정으로' 안내한다.
# 예: "[승인번호 : 03187517, 승인취소] 승인 건 계정과 다릅니다. 세금과공과금-인사(과)와 동일해야 합니다."
_SAVE_APRVL_RE = re.compile(r"승인번호\s*[:：]\s*(\w+)")
_SAVE_REQ_ACCT_RE = re.compile(r"다릅니다[.\s]*(.+?)\s*와\s*동일")


def _parse_save_rejections(reason: str, rows_list: list[dict]) -> list[dict]:
    """ERP 저장 거부 메시지 → 조치 안내 리스트. 승인번호로 그리드 행(rowNo·가맹점)을 매핑한다.

    반환 [{aprvlNo, requiredAccount, rowNo, merchant, raw}] (파싱 실패분은 제외, 중복 승인번호 접기).
    형식이 달라 못 뽑으면 빈 리스트 — 호출부가 원문 폴백."""
    by_aprvl: dict[str, dict] = {r.get("APRVL_NO", "").lstrip("0"): r for r in rows_list if r.get("APRVL_NO")}
    idx_of = {id(r): i for i, r in enumerate(rows_list)}
    issues: list[dict] = []
    seen: set[str] = set()
    for seg in re.split(r"(?=\[?\s*승인번호)", reason or ""):
        seg = seg.strip()
        if not seg:
            continue
        m = _SAVE_APRVL_RE.search(seg)
        a = _SAVE_REQ_ACCT_RE.search(seg)
        aprvl = m.group(1) if m else None
        acct = a.group(1).strip() if a else None
        if not (aprvl or acct):
            continue
        key = f"{aprvl}|{acct}"
        if key in seen:
            continue
        seen.add(key)
        row = by_aprvl.get((aprvl or "").lstrip("0"))
        issues.append(
            {
                "aprvlNo": aprvl,
                "requiredAccount": acct,
                "rowNo": (idx_of.get(id(row)) + 1) if row is not None else None,
                "merchant": row.get("TRAN_NM") if row is not None else None,
                "raw": seg[:200],
            }
        )
    return issues


def _save_guidance(issues: list[dict], reason: str) -> str:
    """조치 안내 본문 — **왜 실패했고 무엇을 고칠지**. 계정 불일치는 어느 행을 어떤 계정으로,
    그 외 유형(필수값 미입력·적용 누락·일반 ERP 오류)은 사유별 구체 조치를 준다(블라인드 재시도 X).
    """
    if issues:
        lines = []
        for it in issues:
            where = (
                f"{it['rowNo']}행 「{it['merchant']}」"
                if it.get("rowNo")
                else f"승인번호 {it.get('aprvlNo') or '?'}"
            )
            if it.get("requiredAccount"):
                lines.append(
                    f"• {where}: 이 건은 예산계정이 **‘{it['requiredAccount']}’**와 같아야 합니다. "
                    f"그 계정에 해당하는 예산단위로 다시 선택해 주세요."
                )
            else:
                lines.append(f"• {where}: 계정이 맞지 않습니다. 예산단위를 다시 선택해 주세요.")
        return (
            "저장이 거부됐습니다 — 승인취소 건은 **원 승인 건과 같은 예산계정**이어야 합니다.\n"
            "아래 항목을 고쳐 다시 저장해 주세요:\n" + "\n".join(lines) +
            "\n\n'건별 입력' 화면으로 돌아갑니다. 표시된 행만 고치면 됩니다."
        )
    # 구조화되지 않은 거부 — 사유 문자열로 유형을 분류해 '무엇이 잘못됐고 무엇을 고칠지'를 준다.
    r = reason or ""
    if any(k in r for k in ("필수 값", "필수값", "입력되지 않은", "검증 실패")):
        return (
            f"저장이 거부됐습니다 — **필수값이 비어 있는 행**이 있습니다.\n(ERP 사유: {reason})\n\n"
            "각 행에 **프로젝트 등 필수값**을 채운 뒤 다시 저장해 주세요. '건별 입력' 화면으로 돌아갑니다."
        )
    if "적용 단계" in r or "카드팝업" in r:
        return (
            f"저장이 완료되지 않았습니다 — **적용 단계가 누락**됐습니다(내부 오류).\n(사유: {reason})\n\n"
            "문서를 다시 만들어 재입력·적용 후 저장을 시도합니다."
        )
    return (
        f"저장이 ERP 에서 거부됐습니다:\n{reason}\n\n"
        "위 **사유**를 확인해 해당 항목(예산단위·계정·필수값 등)을 고친 뒤 다시 저장해 주세요. "
        "'건별 입력' 화면으로 돌아갑니다."
    )


def make_save_final_node():
    """최종 저장(F7) 1회 — 별도 확인 없음(사용자 업무 규칙: 그리드 '입력 완료' 제출이 곧
    저장까지의 승인이다). 반영 0건이면 저장하지 않는다.

    저장이 ERP 에서 거부되면(계정 불일치 등) MAX_SAVE_RETRIES 까지 retry_save 를 켜서
    그래프가 menu_nav 로 되돌아가 문서를 새로 만들고 '건별 입력' 그리드부터 재입력하게 한다.
    """

    async def save_final(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 저장하지 않음: {state.get('error')}", "retry_save": False}
        events = state["events"]
        page = state["page"]
        filled1 = state.get("filled", 0)
        filled2 = state.get("pass2_filled", 0)
        failed_n = state.get("pass1_failed", 0) + state.get("pass2_failed", 0)
        unmatched_n = state.get("pass2_unmatched", 0)
        # 매칭 실패(반영 누락)는 최종 결과에 반드시 노출한다(리뷰 HIGH #2).
        tail = f" · ⚠ 매칭 실패 {unmatched_n}건(수동 확인 필요)" if unmatched_n else ""
        if failed_n:
            tail += f" · ⚠ 행 반영 실패 {failed_n}건"
        total = filled1 + filled2
        await emit_step(events, "save_final", "running")
        t0 = time.monotonic()
        if not total:
            # 반영 0건: 조회 자체가 0건이면 정상 완료지만, 행 반영 **실패** 때문이라면
            # '처리 완료'로 위장하지 않고 실패로 보고한다(실전 2026-07-04: 40/40 실패가
            # '처리 완료 — 반영 0건'으로 성공 표시되던 문제).
            if failed_n:
                await emit_step(events, "save_final", "failed")
                return {"error": f"모든 행 반영 실패({failed_n}건) — 저장하지 않았습니다. 로그의 행별 실패 사유를 확인하세요.", "retry_save": False}
            await emit_step(events, "save_final", "done", _shared._ms(t0))
            return {"result": f"처리 완료 — 반영 0건(저장할 내용 없음){tail}.", "retry_save": False}
        # 과세/불공 어느 한쪽이 0건이면 그 패스는 생략된 것 — 나머지 반영분만으로 저장한다.
        await emit_log(events, f"과세 {filled1}건 · 불공 {filled2}건 반영 완료 — 저장(F7)을 진행합니다.", "info")
        r = await steps.save_document(page, confirm=True)
        if not r.get("ok"):
            await emit_step(events, "save_final", "failed")
            reason = r.get("reason") or str(r)
            retries = state.get("save_retries", 0)
            issues = _parse_save_rejections(reason, state.get("rows_list") or [])
            # ERP 거부(계정 불일치 등)는 재선택으로 고칠 수 있다 — 상한까지 그리드로 되돌린다.
            if retries < MAX_SAVE_RETRIES:
                await emit_chat(
                    events,
                    chat_id="cc-retry",
                    role="assistant",
                    content=_save_guidance(issues, reason)
                    + f"\n\n(재시도 {retries + 1}/{MAX_SAVE_RETRIES}회)",
                    streaming=False,
                )
                await emit_log(
                    events, f"저장 거부 → 그리드 재입력 재시도 {retries + 1}/{MAX_SAVE_RETRIES}: {reason}", "warn"
                )
                return {
                    "retry_save": True,
                    "save_retries": retries + 1,
                    "save_error_msg": reason,
                    "save_error_issues": issues,
                }
            # 최종 포기 — 원문 사유만 남기지 말고 '왜 실패했고 무엇을 고칠지' 조치까지 결과에 남긴다
            #  (로깅 resultSummary 로 사용자가 원인·조치를 바로 볼 수 있게. 재시도 중 안내와 동일 본문).
            return {
                "error": f"저장 실패({retries}회 재시도 후 포기).\n" + _save_guidance(issues, reason),
                "retry_save": False,
            }
        seen = r.get("modals_seen") or []
        if seen:
            await emit_log(
                events,
                "저장 중 확인창: "
                + " / ".join(f"[{m.get('title')}] {m.get('text', '')[:160]}" for m in seen[:3]),
                "info",
            )
        await emit_log(events, "결의서 저장 시퀀스 완료(F7).", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "save_final", "done", _shared._ms(t0))
        return {"result": f"처리 완료 — 과세 {filled1}건 · 불공 {filled2}건 입력·저장{tail}.", "retry_save": False}

    return save_final
