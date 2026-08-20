"""조회 조건 세팅(set_query) + 조회 실행(run_query) 노드.

set_query: D2 8필드 중 값 세팅이 필요한 것만 순서대로 반영(회계단위·역분개여부는 기본값 유지).
run_query: 조회(F2) → 마스터 그리드 rowcount 를 state["master_rowcount"] 로 넘긴다.
둘 다 한 필드/단계라도 실패하면 즉시 error 로 단락한다(잘못된 조건으로 결재 대상 오인 방지).
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_set_query_node(docu_types: tuple[str, ...] = steps.DOCU_TYPE_TARGETS):
    """조회 조건 세팅 — 패널 확장 → 작성부서 전체 → 회계일(폼 지정 기간, 기본 당월) → 작성자 비움
    → 전표상태 미결 → 전자결재상태 저장 → 전표유형. 전표유형은 실행 전 폼 선택
    (state.docu_types)이 우선하고, 미지정이면 빌드 인자(docu_types)가 기본값이다(2026-08-20 병합)."""

    async def set_query(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        # 실행 전 폼의 전표유형 선택(validate_params 산출)이 빌드 기본값을 덮는다.
        selected = tuple(state.get("docu_types") or ()) or docu_types
        await emit_step(events, "set_query", "running")
        t0 = time.monotonic()

        async def fail(field: str, reason) -> dict:
            await emit_step(events, "set_query", "failed")
            msg = f"조회조건 '{field}' 세팅 실패: {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg}

        async def warn_if_unverified(field: str, r: dict) -> None:
            """스텝이 '확인 불가'(리더로 값을 못 읽음)로 통과했으면 그 사실을 로그에 남긴다 —
            반영 실패는 하드 실패로 걸리지만, 확인 불가는 조용히 지나가면 안 된다."""
            if r.get("warn"):
                await emit_log(events, f"조회조건 '{field}' {r['warn']}", "warn")

        # 공지 팝업은 공유 로그인 플로우(ensure_logged_in)가 로그인 직후 닫고, 각 피커 클릭 직전
        # (_open_picker)에도 just-in-time 재확인한다 — 여기선 별도 처리 불필요.
        # 전표유형이 optional-area 라 패널을 먼저 펼친다(없으면 no-op).
        await steps.expand_condition_panel(page)

        # 각 필드는 스텝 안에서 **세팅 → 반영 확인**까지 끝낸 뒤 ok 를 돌려준다
        # (확인 커널: 즉시 1회 + 점증 대기 3회 재시도). 여기서는 결과만 분기한다.
        r = await steps.set_dept_all(page)
        if not r.get("ok"):
            return await fail("작성부서", r.get("reason"))
        await warn_if_unverified("작성부서", r)
        await emit_log(events, f"작성부서 = 전체({r.get('n')}건) — 반영 확인 ✅ {r.get('display')}", "info")

        # 회계일 — 실행 전 폼이 고른 기간(period_from~period_to). 미지정이면 당월(종전 동작).
        r = await steps.set_period(page, state.get("period_from"), state.get("period_to"))
        if not r.get("ok"):
            return await fail("회계일", r.get("reason"))
        await warn_if_unverified("회계일", r)
        await emit_log(events, f"회계일 = {r.get('display') or '당월(1일~말일)'}.", "info")

        r = await steps.clear_writer(page)
        if not r.get("ok"):
            return await fail("작성자", r.get("reason"))
        await warn_if_unverified("작성자", r)

        r = await steps.set_docu_status(page)
        if not r.get("ok"):
            return await fail("전표상태", r.get("reason"))
        await warn_if_unverified("전표상태", r)

        r = await steps.set_gwaprvlst(page)
        if not r.get("ok"):
            return await fail("전자결재상태", r.get("reason"))
        await warn_if_unverified("전자결재상태", r)

        r = await steps.set_docu_types(page, selected)
        if not r.get("ok"):
            return await fail("전표유형", r.get("reason"))
        await warn_if_unverified("전표유형", r)

        await emit_log(
            events,
            f"조회 조건 세팅 완료(미결·전자결재저장·전표유형 {'·'.join(selected)}).",
            "ok",
        )
        await emit_shot(events.put, page)
        await emit_step(events, "set_query", "done", _ms(t0))
        return {}

    return set_query


def make_run_query_node():
    """조회(F2) 실행 → 마스터 그리드 rowcount 를 state 로 넘긴다(0이면 처리 대상 없음)."""

    async def run_query(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "run_query", "running")
        t0 = time.monotonic()

        # ⚠ 조회 직전 재확정 게이트(2026-08-07): 작성자·회계일은 폼 리로드/change 캐스케이드가
        #   **첫 검증 통과 후** 값을 비동기로 되돌릴 수 있는 필드다(작성자 = 로그인 사용자
        #   재주입, 회계일 = 위젯 기본값 복귀 — 08-03·08-06 라이브 실측). 두 스텝은 멱등이고
        #   팝업이 없으며 INSTANT 첫 확인이 0ms 라, 조회 버튼을 누르기 직전 시점에 한 번 더
        #   확정해 '검증과 조회 사이' 되돌림 창을 봉합한다.
        #   불변식: 이 플로우는 작성자를 항상 비운다(작성자 필터 기능이 생기면 이 게이트 제거).
        r = await steps.clear_writer(page)
        if not r.get("ok"):
            await emit_step(events, "run_query", "failed")
            return {"error": f"조회 직전 작성자 재확정 실패: {r.get('reason')}"}
        r = await steps.set_period(page, state.get("period_from"), state.get("period_to"))
        if not r.get("ok"):
            await emit_step(events, "run_query", "failed")
            return {"error": f"조회 직전 회계일 재확정 실패: {r.get('reason')}"}

        r = await steps.run_query(page)
        if not r.get("ok"):
            await emit_step(events, "run_query", "failed")
            return {"error": r.get("reason") or "조회 실행 실패"}

        rowcount = int(r.get("rowcount", 0))
        if rowcount == 0:
            # 0건은 확정 근거까지 남긴다 — steps.run_query 가 전체 대기(HEAVY)를 소진한
            # 뒤에만 0건을 인정하므로, 이 로그가 곧 '조회 실패가 아니라 진짜 무데이터' 증빙이다.
            await emit_log(events, "조회 완료 — 대상 전표 0건(전체 대기 소진 후 확정).", "info")
        else:
            await emit_log(events, f"조회 완료 — 대상 전표 {rowcount}건.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "run_query", "done", _ms(t0))
        return {"master_rowcount": rowcount}

    return run_query
