"""구매발주 병렬 워커 공용부 — 세션 부트스트랩 + FE 워커 칩 브로드캐스트.

같은 계정 동시 3세션 허용은 `e2e/concurrent_session_probe.py` 실측(2026-09-01 — 강제
로그아웃·세션 간섭 없음). 부트스트랩 로그인은 **순차**(동시 로그인 발사는 미실측).
self_approve 가 풀을 만들고 state["worker_pool"] 로 place_orders 에 넘겨 재사용한다
(로그인 1회) — 정리는 마지막 사용자(place_orders)가, 그 전에 런이 죽으면 러너의
browser.close 가 컨텍스트까지 정리한다.
"""

from __future__ import annotations

import asyncio

from app.live.events import emit_log, emit_workers
from nbkit.browser.popups import install_notice_autoclose
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.user_type_flow import ensure_user_type

WORKERS = 3  # 동시 브라우저 세션 상한 — concurrent_session_probe 실측 범위(3) 이내

# ── 재시도 패스(2026-09-02 사용자 설계) — 병렬 1차 → 실패분 판정 → 다수면 재병렬, 소수면 직렬.
#    혼선·타이밍 같은 단순 실패는 다음 패스에서 자연 해소되고, 진짜 오류만 마지막 패스 뒤 표면화된다.
#    재시도 안전성은 각 단계의 가드가 보장한다(상신은 결재상태 '저장'만, 발주는 팝업 잔여 행만).
MAX_PASSES = 3  # 1차 병렬 + 재시도 최대 2회
RETRY_PARALLEL_MIN_FAILS = 3  # 실패가 이 건수 이상이면 '다수' → 2차도 병렬
RETRY_PARALLEL_MIN_RATIO = 0.5  # 또는 배치의 이 비율 이상 실패
MODE_LABEL = {"parallel": "병렬", "serial": "직렬"}


def plan_retry(n_failed: int, n_total: int, pass_no: int) -> str | None:
    """다음 패스 방식 — 'parallel' | 'serial' | None(재시도 없음). 순수 함수."""
    if n_failed <= 0 or pass_no >= MAX_PASSES:
        return None
    # 1건 실패는 병렬이 무의미(세션 1개면 족하다) → 항상 직렬.
    many = n_failed >= 2 and (
        n_failed >= RETRY_PARALLEL_MIN_FAILS
        or (n_total > 0 and n_failed / n_total >= RETRY_PARALLEL_MIN_RATIO)
    )
    if pass_no == 1 and many:
        return "parallel"
    return "serial"


async def run_with_retry(items: list, run_pass, *, events: asyncio.Queue, label: str, item_id) -> tuple[list, list]:
    """items 를 패스 단위로 처리한다. run_pass(batch, mode, pass_no) → (done, failed_items, error_records).

    각 패스 결과를 로그로 남기고(조용한 재시도 금지), 마지막 패스의 error_records 만 반환한다.
    """
    batch = list(items)
    pass_no = 1
    mode = "parallel"
    done: list = []
    errors: list = []
    while True:
        d, failed, errs = await run_pass(batch, mode, pass_no)
        done.extend(d)
        nxt = plan_retry(len(failed), len(batch), pass_no)
        if failed:
            ids = ", ".join(item_id(x) for x in failed)
            if nxt:
                await emit_log(
                    events,
                    f"{label} {pass_no}차({MODE_LABEL[mode]}) {len(batch)}건 중 {len(failed)}건 실패 → "
                    f"{MODE_LABEL[nxt]}로 재시도({pass_no + 1}차): {ids}",
                    "warn",
                )
            else:
                await emit_log(
                    events,
                    f"{label} {pass_no}차({MODE_LABEL[mode]}) {len(batch)}건 중 {len(failed)}건 실패 — "
                    f"재시도 소진(최대 {MAX_PASSES}차): {ids}",
                    "error",
                )
        if not nxt:
            errors = errs
            return done, errors
        batch = failed
        pass_no += 1
        mode = nxt


async def bootstrap_worker_page(browser, *, userid: str, password: str, base: str, scale) -> tuple:
    """추가 워커용 새 브라우저 컨텍스트+페이지 — 로그인→SCM 유저타입까지. 반환 (ctx, page).

    실패는 예외로 승격(호출부가 해당 워커만 제외하고 진행). 메뉴 진입은 각 노드의 워커 루프
    책임이다(화면이 노드마다 다르다).
    """
    from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # 지연 import — 순환 방지

    ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
    install_notice_autoclose(ctx)
    page = await ctx.new_page()
    if scale and scale != 1.0:
        page = _ScaledPage(page, scale)
    await ensure_logged_in(page, userid, password, base)
    await ensure_user_type(page, "SCM")
    return ctx, page


class WorkerTracker:
    """워커 상태 프레임 브로드캐스터 — FE 라이브 스테이지 칩({"workers": [...]}) 계약.

    병렬(n>1)일 때만 방출한다 — 단독 직렬 런은 기존 로그로 충분(재생 노이즈 방지).
    """

    def __init__(self, events: asyncio.Queue, n: int):
        self.events = events
        self.state: dict[int, dict] = {i: {"id": i + 1, "status": "idle"} for i in range(n)}
        self.broadcast = n > 1

    async def emit(self) -> None:
        if self.broadcast:
            await emit_workers(self.events, [dict(self.state[k]) for k in sorted(self.state)])

    async def working(self, wid: int, prq: str, seq=None) -> None:
        self.state[wid] = {"id": wid + 1, "prq": prq, "seq": seq, "status": "working"}
        await self.emit()

    async def done(self, wid: int) -> None:
        self.state[wid] = {"id": wid + 1, "status": "done"}
        await self.emit()
