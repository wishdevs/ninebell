"""self_approve — D7 셀프결재(화면 ② 구매요청처리 PUOPRQ00300): 저장된 PRQ 번호마다 조회 →
가드레일(결재상태 '저장' ∧ 결재상신코드 빈칸) → 행 선택 → 결재 아이콘 → EAP 결재창 → 상신.

게이트 2겹: (1) 빌더 allow_submit, (2) params.debug(디버그 모드면 결재창을 열고 닫기만) —
계획 확정 이후는 전부 자동 진행(사용자 확정 2026-08-31). ⛔ 보관 버튼은 절대 클릭하지 않는다.
결재라인은 본인만(셀프) — 교차 지정 없음. 상신 성공 판정 = 결재창 닫힘 + 재조회에서 결재상태 변화.

병렬화(2026-09-01 사용자 승인 — "결제부터 병렬"): PRQ 상신은 문서 단위 독립이라 워커 세션
(최대 3, `parallel.WORKERS`)이 큐를 분담한다. 각 워커는 화면 진입+공장 지정을 1회 하고 PRQ 를
소비한다. 실패 정책 = 실패 PRQ 만 기록하고 나머지 완주 후 종합 보고 — 단, 실패가 있으면 발주
(place_orders)로 넘어가지 않고 여기서 런을 실패시킨다(상신 안 된 문서의 발주 시도를 막는다.
상신된 건은 다음 '이어서 실행'이 발주부터 재개). 상신이 끝나면 **정리 패스**로 '한 개의 창'
상태로 정돈한다(잔여 결제창 전부 닫기 + 추가 세션 종료 + FE 자식창 표시 해제) — 발주는
place_orders 가 새 병렬 세션으로 시작한다(2026-09-01 사용자 지시: 세션 재사용 이득보다 꼬임·
화면 오염 방지 우선 — 닫힘 지연으로 살아남은 EAP 창이 발주 단계 화면에 남던 실사례).
재개 파서 규격 문구('PRQ…: 상신 완료')는 유지.
"""

from __future__ import annotations

import asyncio
import time

from app.agents.purchase_order import steps_write
from app.agents.purchase_order.parallel import WORKERS, WorkerTracker
from app.agents.purchase_order.parallel import bootstrap_worker_page as _bootstrap_worker_page
from app.agents.voucher_receivable import steps as voucher_steps
from app.config import get_settings
from app.live.events import emit_log, emit_step
from nbkit.omnisol.menu_schemas import PURCHASE_REQ_PROCESS
from nbkit.patterns import emit_shot
from nbkit.patterns.menu_navigate_flow import navigate_schema

STEP = "self_approve"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def _submit_one(page, x: dict, events, submit_on: bool) -> dict:
    """PRQ 1건 상신 — 조회→가드→(행 선택→결재창→상신→재조회 검증)×최대 2회.

    반환 {"ok": True, "record": {…}|None(가드 스킵)} 또는 {"ok": False, "reason": str}.
    화면 진입·공장 지정은 호출부(워커) 책임. 재시도는 **재조회가 미상신('저장')을 확정한
    경우에만** 1회 — 이중 상신 위험 없음(2026-09-01 PRQ2026090076 실측: 상신 클릭 완전
    무반응 + 재조회 '저장' — 변경거래처/저장 클릭 유실과 같은 간헐 무반응 계열).
    """
    no = x["number"]
    q = await steps_write.query_request(page, no)
    if not q.get("ok"):
        return {"ok": False, "reason": f"{no}: {q.get('reason')}"}
    row = q["row"]
    guard = steps_write.submit_guard(row)
    if guard:
        # 이미 상신된 문서(결재상태 진행/종결 또는 상신코드 존재) — 재개 런의 정상 경로다.
        # 'PRQ…: 상신 완료' 는 재개 파서(purchase_order_resume.RE_SUBMITTED) 규격 문구 —
        # 이 로그가 남아야 다음 실행/배너가 이 PRQ 를 완료로 인식한다(기록 자가 보정).
        await emit_log(events, f"{no}: 상신 완료 — 이전 런에서 상신됨({guard}). 건너뜁니다.", "info")
        return {"ok": True, "record": None}

    attempts = 2 if submit_on else 1
    last_reason = ""
    st = gw = None
    for attempt in range(1, attempts + 1):
        if not await steps_write.select_request_row(page, int(row["i"])):
            return {"ok": False, "reason": f"{no}: 마스터 행 선택 실패."}
        await emit_shot(events.put, page)
        o = await steps_write.open_request_approval(page)
        if not o.get("ok"):
            return {"ok": False, "reason": f"{no}: {o.get('reason')}"}
        child = o["child"]
        await emit_log(events, f"{no}: 결재창 열림({o.get('selector')}).", "info")
        click_fail: str | None = None
        try:
            top = await voucher_steps.poll_child_ready(child)
            if not top:
                return {"ok": False, "reason": f"{no}: 결재창 상단 버튼(상신)이 렌더되지 않았습니다."}
            await emit_shot(events.put, child, window="child")
            if not submit_on:
                await emit_log(events, f"{no}: (가상 상신) 결재창 확인 후 닫습니다.", "info")
                return {"ok": True, "record": {"number": no, "submitted": False}}
            s = await voucher_steps.click_child_submit(child)
            if not s.get("ok"):
                # 즉시 실패로 단정하지 않는다 — 상신 클릭은 이미 나갔으므로(EAP 창 닫힘만 지연됐을 수
                # 있다, 병렬 첫 실전 8건 중 2건 실측) 아래 재조회가 진실원천으로 판정한다.
                click_fail = str(s.get("reason") or "상신 클릭 실패")
                await emit_shot(events.put, child, window="child")
        finally:
            await voucher_steps.close_child(child)
            await voucher_steps.settle_parent_after_child_close(page, child)

        q2 = await steps_write.query_request(page, no)
        row2 = (q2.get("row") or {}) if q2.get("ok") else {}
        st, gw = row2.get("ATHZ_ST_NM"), row2.get("GWDOCU_NO")
        submitted_now = bool(q2.get("ok") and steps_write.submit_guard(row2))
        if submitted_now or (not click_fail and not q2.get("ok")):
            # 성공 — 재조회가 상신 반영을 확정(재조회 실패 시엔 클릭 성공을 신뢰하는 기존 관용 경로).
            if click_fail:
                await emit_log(
                    events,
                    f"{no}: 결제창 닫힘 지연이었지만 재조회에서 상신 반영을 확인했습니다({click_fail}).",
                    "warn",
                )
            await emit_log(events, f"{no}: 상신 완료 — 결재상태 {st} · 결재상신코드 {gw or '(미조회)'}.", "ok")
            await emit_shot(events.put, page)
            return {"ok": True, "record": {"number": no, "submitted": True, "status": st, "gwdocuNo": gw}}
        # 미상신 확정(재조회 '저장' 유지) — 간헐 무반응. 마지막 시도 전이면 결재창을 다시 연다.
        last_reason = click_fail or "상신 후 재조회에서 결재상태가 여전히 '저장'/상신코드 빈칸입니다."
        if attempt < attempts:
            await emit_log(
                events,
                f"{no}: 상신 {attempt}차가 무반응(재조회 '저장' 확인 — 이중 상신 위험 없음) — "
                f"결재창을 다시 열어 재시도합니다({last_reason}).",
                "warn",
            )
            if q2.get("ok"):
                row = row2  # 행 인덱스 최신화.
    return {
        "ok": False,
        "reason": f"{no}: 상신 실패 — {last_reason} (재시도 {attempts - 1}회 포함, 재조회 결재상태 {st or '미확인'})",
    }


def make_self_approve_node(*, allow_submit: bool = False):
    async def self_approve(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        # read_bom 이 no_modules 로 남긴 '발주할 모듈 없음' result 는 재실행(submit_prqs) 경로에선
        # 무의미하다 — report 가 최종 result 로 덮어쓴다.
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()
        prqs = [p for p in (state.get("purchase_request_nos") or []) if p.get("number")]
        # 자동 재개(2026-08-31) — 이전 중단 런의 PRQ 를 합류시킨다. 이미 상신된 건은 가드
        # (결재상태 '저장'만 상신)가 로그와 함께 자연 스킵한다.
        prior = [
            {**p, "prior": True}
            for p in ((state.get("resume") or {}).get("prqs") or [])
            if p.get("number") not in {x.get("number") for x in prqs}
        ]
        if prior:
            await emit_log(
                events,
                "재개 — 이전 런에서 저장된 구매요청 합류: " + ", ".join(str(p["number"]) for p in prior),
                "info",
            )
            prqs = [*prqs, *prior]
        # 재실행 경로 — 이미 저장된 PRQ 만 상신(graph._after_read_bom 이 여기로 직행시킨다).
        po = (state.get("params") or {}).get("purchase_order") or {}
        if po.get("submit_prqs"):
            prqs = [{"number": str(x).strip(), "seq": "-"} for x in po["submit_prqs"] if str(x).strip()]
        if not prqs:
            await emit_log(events, "상신할 구매요청번호가 없습니다(저장된 PRQ 0건) — 셀프결재를 건너뜁니다.", "warn")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"submitted": []}

        debug = bool((state.get("params") or {}).get("debug")) or bool(state.get("debug_mode"))
        submit_on = allow_submit and not debug
        if allow_submit and not submit_on:
            await emit_log(events, "디버그 모드 — 결재창을 열고 확인만 하며 상신하지 않습니다.", "info")

        # 개입 없음(사용자 확정 2026-08-31) — 계획 확정 이후는 전부 자동 진행. 상신 게이트는
        # allow_submit(빌더) ∧ ¬debug 만 남는다.
        if submit_on:
            await emit_log(
                events,
                "셀프결재 상신 시작 — " + ", ".join(str(x["number"]) for x in prqs) + " (결재라인 본인만, 보관 미클릭).",
                "info",
            )

        base = get_settings().erp_base
        # ── 워커 부트스트랩 — 메인 페이지 1 + 추가 세션 최대 WORKERS-1(순차 로그인). 세션은
        #    상신이 끝나면 정리 패스에서 전부 종료한다(인계 없음 — 2026-09-01 사용자 지시).
        worker_pages: list = [page]
        contexts: list = []
        browser = state.get("browser")
        userid, password = state.get("userid"), state.get("password")
        want_extra = min(WORKERS, len(prqs)) - len(worker_pages)
        if want_extra > 0 and browser is not None and userid:
            scale = getattr(page, "_scale", None)
            for _ in range(want_extra):
                try:
                    ctx, wpage = await _bootstrap_worker_page(
                        browser, userid=userid, password=password, base=base, scale=scale
                    )
                except Exception as exc:  # noqa: BLE001 — 워커 하나 실패는 해당 워커만 제외.
                    await emit_log(events, f"병렬 워커 기동 실패 — 해당 세션 없이 진행합니다({str(exc)[:120]}).", "warn")
                    continue
                contexts.append(ctx)
                worker_pages.append(wpage)
            if len(worker_pages) > 1:
                await emit_log(
                    events,
                    f"병렬 상신 — 브라우저 세션 {len(worker_pages)}개가 {len(prqs)}건을 분담합니다"
                    "(같은 계정 동시 세션 실측 허용 — concurrent_session_probe).",
                    "info",
                )
        order_pos = {str(x.get("number")): i for i, x in enumerate(prqs)}
        submitted: list[dict] = []
        errors: list[dict] = []
        main = {"page": page}
        tracker = WorkerTracker(events, len(worker_pages))
        await tracker.emit()

        queue: asyncio.Queue = asyncio.Queue()
        for x in prqs:
            queue.put_nowait(x)

        async def _worker(wid: int, wpage) -> None:
            page_w = wpage
            # 워커당 1회 — 화면 진입 + 공장(나인벨) 지정. 실패하면 이 워커만 빠진다(큐는 남는다).
            try:
                active = await navigate_schema(page_w, PURCHASE_REQ_PROCESS, base, emit=events.put, step_id=None)
                if active is not None:
                    page_w = active
                    if wid == 0:
                        main["page"] = page_w
                p = await steps_write.ensure_req_plant(page_w)
                if not p.get("ok"):
                    raise RuntimeError(p.get("reason") or "공장(나인벨) 지정 실패")
            except Exception as exc:  # noqa: BLE001
                await emit_log(events, f"상신 워커 {wid + 1} 화면 준비 실패 — 이 세션 없이 진행합니다({str(exc)[:120]}).", "warn")
                await tracker.done(wid)
                return
            while True:
                try:
                    x = queue.get_nowait()
                except asyncio.QueueEmpty:
                    await tracker.done(wid)
                    return
                no = str(x["number"])
                await tracker.working(wid, no, x.get("seq"))
                try:
                    r = await _submit_one(page_w, x, events, submit_on)
                except Exception as exc:  # noqa: BLE001
                    r = {"ok": False, "reason": f"{no}: 상신 처리 예외 — {str(exc)[:160]}"}
                if r.get("ok"):
                    if r.get("record"):
                        submitted.append(r["record"])
                else:
                    errors.append({"prq": no, "reason": str(r.get("reason"))})
                    await emit_log(events, f"{r.get('reason')} — 나머지 구매요청은 계속 진행합니다.", "error")

        await asyncio.gather(*[_worker(i, wp) for i, wp in enumerate(worker_pages)])
        # 전 워커가 준비 실패로 빠지면 큐가 남는다 — 조용히 삼키지 않고 실패로 승격.
        while not queue.empty():
            x = queue.get_nowait()
            errors.append({"prq": str(x["number"]), "reason": f"{x['number']}: 처리 워커 없음(전 세션 준비 실패)."})

        # ── 정리 패스(2026-09-01 사용자 지시) — 결제 병렬 후 '한 개의 창'으로 정돈: 잔여
        #    결제창(자식 페이지) 전부 닫기 + 추가 세션 종료 + FE 자식창(PIP) 표시 해제. 발주는
        #    place_orders 가 새 병렬 세션으로 시작한다.
        closed_children = 0
        try:
            raw_main = getattr(main["page"], "_page", main["page"])
            for extra in [p for p in list(raw_main.context.pages) if p is not raw_main]:
                try:
                    await extra.close()
                    closed_children += 1
                except Exception:  # noqa: BLE001 — 이미 닫힌 창 등.
                    pass
        except Exception:  # noqa: BLE001 — 정리 실패가 결과를 바꾸면 안 된다.
            pass
        for ctx in contexts:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass
        await events.put({"window": "child", "closed": True})  # FE 자식창 표시 해제(잔상 방지).
        if len(worker_pages) > 1 or closed_children:
            await emit_log(
                events,
                f"상신 세션 정리 — 잔여 결제창 {closed_children}개 닫음 · 추가 세션 {len(contexts)}개 종료. "
                "발주는 새 병렬 세션으로 진행합니다.",
                "info",
            )

        submitted.sort(key=lambda r: order_pos.get(str(r.get("number")), len(order_pos)))
        if errors:
            await emit_step(events, STEP, "failed")
            summary = "; ".join(e["reason"] for e in errors[:3])
            if len(errors) > 3:
                summary += f" 외 {len(errors) - 3}건"
            return {
                "error": f"상신 {len(errors)}건 실패({len(submitted)}건 처리) — {summary}",
                "submitted": submitted,
                "page": main["page"],
            }
        await emit_step(events, STEP, "done", _ms(t0))
        return {"submitted": submitted, "page": main["page"]}

    return self_approve
