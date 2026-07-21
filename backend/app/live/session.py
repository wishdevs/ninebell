"""라이브 세션 — SSE 연결 수명과 흐름(브라우저+그래프+HITL)을 분리한다.

흐름이 SSE 제너레이터 안에서 돌면 클라이언트가 끊길 때 러너가 즉시 취소되고 헤드리스
브라우저가 닫혀 HITL 큐가 사라진다. 이 모듈은 흐름을 서버 측 세션으로 승격시켜, 연결이
끊겨도 grace(기본 120s) 동안 살아있게 하고, 재연결 시 커서 이후 이벤트만 재생한다.

핵심:
- producer = 러너(run_workflow)를 그대로 감싼 async 이터레이터.
- 펌프 태스크가 producer 이벤트를 버퍼(인덱스 배열)에 누적 + HITL 소유권 등록 + 최종 상태/로그 확정.
- 구독자(stream)는 버퍼[cursor:] 를 읽고 Condition 으로 다음 이벤트를 기다린다(끊겨도 흐름은 무관).
- 리퍼가 detached(구독자 0) 후 grace 지난 세션을 정리(러너 취소 → 브라우저 close).

ninebell-bak `erp/session.py` 를 워크플로우 무관 엔진으로 이식. HITL 소유권은 `.hitl` 에서,
grace/스크린캐스트 튜닝은 `app.config` 에서 단일 소스로 가져온다. 최종 상태는 8종 이벤트
모델(error→failed / result→succeeded)에 맞춰 판정한다(원본의 dataset 분기는 제거).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import AsyncIterator, Awaitable, Callable

from app.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()
# 구독자가 모두 끊긴(detached) 미완료 흐름을 유지하는 시간 — 이 동안 재연결 가능.
DETACH_GRACE_S = _settings.session_detach_grace_s
# 종료(terminal)된 흐름을 재연결용으로 유지하는 시간(브라우저는 이미 닫힘, 버퍼만 유지).
TERMINAL_GRACE_S = _settings.session_terminal_grace_s
REAPER_INTERVAL_S = _settings.session_reaper_interval_s
_MAX_RUN_LOGS = 2000

ProducerFactory = Callable[[], AsyncIterator[dict]]
OnTerminal = Callable[[str, "str | None", list], Awaitable[None]]

_SESSIONS: dict[str, "LiveSession"] = {}


class LiveSession:
    """하나의 라이브 흐름. SSE 요청과 독립적으로 산다."""

    def __init__(
        self,
        key: str,
        owner: str | None,
        producer_factory: ProducerFactory,
        on_terminal: OnTerminal,
    ) -> None:
        self.key = key
        self.owner = owner  # 세션 사용자(HITL 소유권/재연결 권한). None=개방(스크립트).
        self._producer_factory = producer_factory
        self._on_terminal = on_terminal
        self.buffer: list[dict] = []  # 재생용 히스토리(스크린샷 제외 — 커서 기준)
        # 라이브 화면(스크린샷)은 버퍼에 쌓지 않고 '창별 최신 1장'만 유지(메모리 폭증 방지).
        # 16fps 캐스트를 버퍼링하면 세션당 수백 MB가 되므로, 재생 대상에서 제외한다. 부모/자식
        # 창(진짜 두 번째 브라우저 창)을 각각 유지해 스테이지가 탭으로 전환한다.
        self.latest_shots: dict[str, dict] = {}  # window('parent'|'child') → 최신 프레임
        self.shot_seqs: dict[str, int] = {}  # window → 창별 시퀀스(구독자별 최신 감지)
        self.shot_seq = 0  # 전역 tick — 아무 창이나 갱신되면 증가(Condition wake 판정)
        self._cond = asyncio.Condition()
        self.terminal = False
        self.subscribers = 0
        self.detached_at: float | None = time.monotonic()  # 아직 구독자 없음
        self.created_at = time.monotonic()
        self._pump: asyncio.Task | None = None
        self._agen: AsyncIterator[dict] | None = None
        self._run_logs: list[dict] = []
        self._final_status = "failed"
        self._final_note: str | None = None

    # ── 생명주기 ──────────────────────────────────────────────────────────
    def start(self) -> None:
        self._pump = asyncio.create_task(self._run())

    async def _run(self) -> None:
        from .hitl import set_hitl_owner  # 지연 임포트(순환참조 회피)

        agen = self._producer_factory()
        self._agen = agen
        try:
            async for ev in agen:
                # 라이브 화면 — 버퍼/커서 대상 아님. 창별 최신 1장만 유지하고 구독자에게 라이브 전달.
                if "screenshot" in ev:
                    window = ev.get("window", "parent")
                    async with self._cond:
                        self.latest_shots[window] = ev
                        self.shot_seqs[window] = self.shot_seqs.get(window, 0) + 1
                        self.shot_seq += 1
                        self._cond.notify_all()
                    continue
                # 자식 창 닫힘 전이({"window","closed"}) — 창별 최신 화면 슬롯을 비워(늦은 구독자가
                # 닫힌 창 스크린샷을 다시 활성화하지 않게) 두되, 프레임 자체는 버퍼로 재생 가능하게
                # 남긴다(상태 전이라 커서 대상). 아래 _push 로 흘려보낸다.
                if ev.get("closed") and "window" in ev:
                    async with self._cond:
                        self.latest_shots.pop(ev["window"], None)
                if self.owner and isinstance(ev.get("hitl"), dict):
                    hid = ev["hitl"].get("id")
                    if hid:
                        set_hitl_owner(hid, self.owner)
                self._accumulate_log(ev)
                if "error" in ev:
                    self._final_status, self._final_note = "failed", str(ev["error"])[:500]
                elif "result" in ev:
                    res = ev["result"]
                    # 구조(dict/list) 결과는 그대로 보존(대화형 selections 를 run.result 로 회수).
                    # 문자열 결과만 안전 상한.
                    self._final_status = "succeeded"
                    self._final_note = res if not isinstance(res, str) else res[:500]
                await self._push(ev)
        except asyncio.CancelledError:
            raise  # 리퍼/종료에 의한 취소 → finally 에서 agen.aclose()
        except Exception:
            logger.exception("session pump 실패: %s", self.key)
            await self._push({"error": "실행 중 오류(세션)."})
        finally:
            async with self._cond:
                self.terminal = True
                if self.detached_at is None and self.subscribers == 0:
                    self.detached_at = time.monotonic()
                self._cond.notify_all()
            try:
                await agen.aclose()  # run_workflow.finally → 러너 취소 + 브라우저 close
            except Exception:
                logger.debug("agen.aclose 무시: %s", self.key, exc_info=True)
            try:
                await self._on_terminal(self._final_status, self._final_note, self._run_logs)
            except Exception:
                logger.exception("on_terminal 영속 실패: %s", self.key)

    async def close(self) -> None:
        """세션을 강제 종료(리퍼/셧다운). 펌프 취소 → finally 가 브라우저까지 정리."""
        pump = self._pump
        if pump is not None and not pump.done():
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("pump 종료 예외 무시: %s", self.key, exc_info=True)

    async def cancel(self) -> None:
        """사용자 요청 즉시 종료 — 'cancelled' 로 확정하고 세션을 정리(브라우저 즉시 반납).

        close()(리퍼/셧다운)와 달리 최종 상태를 'cancelled' 로 고정한 뒤 펌프를 취소한다.
        펌프의 finally 가 agen.aclose(러너·스크린캐스트 취소 + 브라우저 close) 후
        on_terminal(status='cancelled') 로 agent_runs 를 확정한다. 이미 종료된 세션은
        멱등(추가 작업 없음)."""
        if self.terminal:
            return
        self._final_status = "cancelled"
        self._final_note = "사용자가 실행을 종료했습니다."
        await self.close()

    # ── 이벤트 누적/전달 ──────────────────────────────────────────────────
    async def _push(self, ev: dict) -> None:
        async with self._cond:
            self.buffer.append(ev)
            self._cond.notify_all()

    def _accumulate_log(self, ev: dict) -> None:
        # 런 이력에 남길 로그(log/step 프레임만 — 스크린샷 등 무거운 건 제외).
        if len(self._run_logs) >= _MAX_RUN_LOGS:
            return
        if "log" in ev:
            self._run_logs.append(
                {
                    "ts": int(time.time() * 1000),
                    "level": ev.get("level", "info"),
                    "message": str(ev["log"]),
                }
            )
        elif "step" in ev and ev.get("status"):
            mark = {"running": "▶", "done": "✓", "failed": "✗"}.get(ev["status"], "·")
            lvl = (
                "ok"
                if ev["status"] == "done"
                else "error"
                if ev["status"] == "failed"
                else "info"
            )
            self._run_logs.append(
                {
                    "ts": int(time.time() * 1000),
                    "level": lvl,
                    "message": f"{mark} {ev['step']} ({ev['status']})",
                    # 구조 필드도 함께 남긴다 — 실행 이력 상세가 step/실패지점을 견고하게 파싱.
                    "step": ev["step"],
                    "status": ev["status"],
                }
            )

    async def stream(self, cursor: int = 0) -> AsyncIterator[dict]:
        """버퍼[cursor:] 부터 이벤트를 재생하고, 이후 새 이벤트를 Condition 으로 기다린다.

        끊김(클라 disconnect)은 이 제너레이터의 aclose 로만 감지되며, 흐름 자체는 건드리지 않는다.
        """
        async with self._cond:
            self.subscribers += 1
            self.detached_at = None
        try:
            i = max(0, cursor)
            last_tick = 0  # 이 구독자가 마지막으로 소비한 전역 화면 tick(Condition wake 판정)
            last_shots: dict[str, int] = {}  # 창별로 이 구독자가 마지막으로 보낸 시퀀스
            while True:
                async with self._cond:
                    while (
                        i >= len(self.buffer)
                        and last_tick == self.shot_seq
                        and not self.terminal
                    ):
                        await self._cond.wait()
                    chunk = self.buffer[i:]
                    i = len(self.buffer)
                    # 창별로 새 프레임이 있으면 각 창 최신 1장씩 모아 보낸다(밀린 프레임은 합쳐짐).
                    shots = [
                        self.latest_shots[w]
                        for w, seq in self.shot_seqs.items()
                        if last_shots.get(w, 0) != seq and w in self.latest_shots
                    ]
                    for w, seq in self.shot_seqs.items():
                        last_shots[w] = seq
                    last_tick = self.shot_seq
                    done = self.terminal and i >= len(self.buffer)
                for ev in chunk:
                    yield ev
                for shot in shots:  # 창별 최신 화면(부모/자식 각 1장)
                    yield shot
                if done:
                    return
        finally:
            async with self._cond:
                self.subscribers -= 1
                if self.subscribers <= 0:
                    self.detached_at = time.monotonic()


# ── 레지스트리 ───────────────────────────────────────────────────────────
def get_session(key: str | None) -> LiveSession | None:
    if not key:
        return None
    return _SESSIONS.get(key)


def create_session(
    key: str | None,
    owner: str | None,
    producer_factory: ProducerFactory,
    on_terminal: OnTerminal,
) -> LiveSession:
    """세션 생성(이미 있으면 그대로 반환 — 동시 생성 경합 방지). key 없으면 익명(재연결 불가)."""
    if key:
        existing = _SESSIONS.get(key)
        if existing is not None:
            return existing
    sess_key = key or f"anon-{uuid.uuid4().hex}"
    sess = LiveSession(sess_key, owner, producer_factory, on_terminal)
    _SESSIONS[sess_key] = sess
    sess.start()
    return sess


async def cancel_session(key: str | None) -> bool:
    """키로 세션을 찾아 즉시 cancel(브라우저 반납)하고 레지스트리에서 제거한다.

    세션이 없으면 False(멱등 — 호출자가 200 처리). 있으면 cancel 후 True.
    리퍼 grace 를 기다리지 않고 즉시 정리하므로 화면 이탈 시 큐가 바로 반납된다.
    """
    sess = _SESSIONS.get(key) if key else None
    if sess is None:
        return False
    try:
        await sess.cancel()
    finally:
        _SESSIONS.pop(key, None)
    return True


async def _reap_once(now: float | None = None) -> None:
    """리퍼 1회 패스 — grace 지난 detached 세션을 정리(테스트 가능 단위)."""
    now = time.monotonic() if now is None else now
    for key, sess in list(_SESSIONS.items()):
        if sess.subscribers > 0 or sess.detached_at is None:
            continue
        grace = TERMINAL_GRACE_S if sess.terminal else DETACH_GRACE_S
        if now - sess.detached_at < grace:
            continue
        try:
            await sess.close()
        except Exception:
            logger.exception("세션 정리 실패: %s", key)
        _SESSIONS.pop(key, None)


async def reap_sessions() -> None:
    """주기적으로 detached 세션 정리 — 미완료는 DETACH_GRACE, 종료는 TERMINAL_GRACE 후."""
    while True:
        await asyncio.sleep(REAPER_INTERVAL_S)
        await _reap_once()


async def close_all_sessions() -> None:
    """셧다운 시 모든 세션 정리(브라우저 누수 방지)."""
    for key, sess in list(_SESSIONS.items()):
        try:
            await sess.close()
        except Exception:
            logger.debug("셧다운 세션 정리 예외: %s", key, exc_info=True)
        _SESSIONS.pop(key, None)
