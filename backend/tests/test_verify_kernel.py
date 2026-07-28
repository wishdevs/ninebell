"""확인 커널(nbkit.omnisol.verify) 계약 — 브라우저 없이.

고정하는 계약(사용자 지시 2026-07-27):
  1. **가능하면 딜레이 없이** — 첫 확인은 대기 0ms 로 하고, 성공하면 아무것도 기다리지 않는다.
  2. 실패하면 **짧은 대기부터 점증하며 3회 재시도**(총 4회 read).
  3. 종류별 스케줄 분리(INSTANT/ASYNC/HEAVY) — 즉시 반영/비동기 반영/화면 전환.
  4. 연쇄(cascade) 훅 — reapply(되돌려지는 값 재실행) / settle(로딩 정착 후 확인).
  5. 확인 불가(unknown)와 불일치(mismatch) 구분 — 호출부가 soft/hard 를 나눠 판단한다.
  6. 대기는 **실시간** — page.wait_for_timeout(delay_scale 로 축소됨)을 쓰지 않는다.

⚠ conftest 의 autouse 픽스처가 DEFAULT_SLEEP 을 no-op 으로 갈아끼우므로, 대기 규율을 보는
   테스트는 sleep= 을 **직접 주입**해 실제 대기 인자를 기록한다.
"""

from __future__ import annotations

import inspect

import pytest

from nbkit.omnisol import js_lib, verify

pytestmark = pytest.mark.asyncio


class _Recorder:
    """주입 sleeper — 실제로 자지 않고 요청된 대기(초)를 기록한다."""

    def __init__(self) -> None:
        self.naps: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.naps.append(seconds)


# ── 1·2. 즉시 확인 → 실패 시 점증 3회 재시도 ──────────────────────────────────────
async def test_success_on_first_read_never_sleeps():
    nap = _Recorder()
    res = await verify.confirm(_reads(["미결"]), lambda v: v == "미결", sleep=nap)
    assert res.ok is True and res.attempts == 1 and res.waited_ms == 0
    assert nap.naps == []  # 정상 경로에서 추가 지연 0.


async def test_retries_three_times_with_increasing_delays():
    nap = _Recorder()
    res = await verify.confirm(
        _reads(["전체", "전체", "전체", "미결"]),
        lambda v: v == "미결",
        timing=verify.INSTANT,
        sleep=nap,
    )
    assert res.ok is True and res.attempts == 4
    # 즉시 1회 + 3회 재시도, 대기는 점증(0.12 → 0.36 → 0.9초).
    assert nap.naps == [0.12, 0.36, 0.9]
    assert nap.naps == sorted(nap.naps)


async def test_exhausted_retries_report_mismatch_with_actual():
    res = await verify.confirm(_reads(["전체"]), lambda v: v == "미결", what="전표상태", expected="미결")
    assert res.ok is False and res.mismatch is True and res.unknown is False
    assert res.attempts == len(verify.ASYNC)
    assert "전표상태" in res.reason and "'전체'" in res.reason  # 실제값이 사유에 실린다.


# ── 3. 종류별 스케줄 — 즉시/비동기/화면 전환 ──────────────────────────────────────
async def test_schedules_are_ordered_immediate_first_and_increasing():
    for schedule in (verify.INSTANT, verify.ASYNC, verify.HEAVY):
        assert schedule[0] == 0  # 첫 확인은 딜레이 없이.
        assert len(schedule) == 4  # 즉시 1회 + 3회 재시도.
        assert list(schedule) == sorted(schedule)  # 점증.
    # 반영이 느린 종류일수록 더 오래 기다린다.
    assert sum(verify.INSTANT) < sum(verify.ASYNC) < sum(verify.HEAVY)


# ── 4. 연쇄(cascade) 훅 ──────────────────────────────────────────────────────────
async def test_reapply_runs_before_each_retry_read_not_on_first():
    calls: list[str] = []

    async def reapply() -> None:
        calls.append("reapply")

    seq = iter(["전체", "미결"])

    async def read():
        calls.append("read")
        return next(seq)

    res = await verify.confirm(
        read, lambda v: v == "미결", timing=verify.INSTANT, reapply=reapply
    )
    assert res.ok is True
    # 첫 확인은 재실행 없이(딜레이 0) → 실패 후에만 재실행하고 다시 읽는다.
    assert calls == ["read", "reapply", "read"]


async def test_settle_runs_before_every_read():
    calls: list[str] = []

    async def settle() -> None:
        calls.append("settle")

    async def read():
        calls.append("read")
        return "미결"

    await verify.confirm(read, lambda v: v == "미결", settle=settle)
    assert calls == ["settle", "read"]


async def test_settle_failure_does_not_break_confirmation():
    async def settle() -> None:
        raise RuntimeError("로딩 판정 실패")

    res = await verify.confirm(_reads(["미결"]), lambda v: v == "미결", settle=settle)
    assert res.ok is True  # 정착 훅은 best-effort.


# ── 5. 확인 불가(unknown) vs 불일치(mismatch) ────────────────────────────────────
async def test_unknown_when_reader_cannot_read_target():
    res = await verify.confirm(
        _reads([None]),
        lambda v: v == "미결",
        unknown_when=lambda v: v is None,
    )
    assert res.ok is False and res.unknown is True and res.mismatch is False
    assert "확인 불가" in res.reason


async def test_read_exception_is_retried_not_raised():
    calls = {"n": 0}

    async def read():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("navigation in progress")
        return "미결"

    res = await verify.confirm(read, lambda v: v == "미결", timing=verify.INSTANT)
    assert res.ok is True and res.attempts == 3  # 확인 코드가 런을 죽이지 않는다.


# ── 6. 대기는 실시간(page.wait_for_timeout 금지) ─────────────────────────────────
async def test_kernel_never_uses_scaled_page_wait():
    """⚠ page.wait_for_timeout 은 delay_scale 로 축소돼(예: 0.4) 느린 세션에서 확인이 조기
    실패한다(공지 팝업 관찰창이 같은 이유로 붕괴했던 선례). 커널은 실시간 sleep 만 쓴다."""
    src = inspect.getsource(verify)
    assert "wait_for_timeout(" not in src  # 호출부 기준(문서에서 금지 이유는 언급한다).
    assert "asyncio.sleep" in src


# ── 종류별 헬퍼가 같은 커널을 쓰는지(리더 단일소스 확인) ───────────────────────────
async def test_confirm_select_reads_selected_text_and_compares_normalized():
    class _Page:
        async def evaluate(self, js_src, arg=None):
            assert js_src == js_lib.SELECTED_TEXT_JS and arg == "#s_docu_st_cd"
            return {"ok": True, "text": " 미결 ", "value": "1"}  # 공백은 정규화 대상.

    assert await verify.confirm_select(_Page(), "#s_docu_st_cd", "미결")


async def test_confirm_visible_element_uses_visibility_not_presence():
    class _Page:
        async def evaluate(self, js_src, arg=None):
            assert js_src == js_lib.VISIBLE_ELEMENT_JS
            return False  # DOM 엔 있으나 다른 탭이라 숨김.

    res = await verify.confirm_visible_element(_Page(), "#ABDOCU_FG_CD")
    assert res.ok is False


def _reads(values: list):
    """values 를 순서대로 돌려주는 read 코루틴(소진되면 마지막 값 유지)."""
    box = list(values)

    async def read():
        return box.pop(0) if len(box) > 1 else box[0]

    return read
