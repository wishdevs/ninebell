"""적응형 대기 상한 — verify 커널·폴링 지점의 지연 배율(latency) 적용 계약.

고정하는 계약:
  1. verify 커널 — factor>1 이면 점증 대기(0 제외)만 배율 확대(스케줄 모양·회수 불변),
     factor=1.0 이면 기존 스케줄 그대로(무회귀).
  2. 되먹임 — confirm **성공** 시에만 record: 1회차 성공 = 비율 1.0(빠름 신호), 후속 회차
     성공 = 누적 명목 대기만큼 느림 신호. mismatch/unknown 실패는 기록하지 않는다.
  3. 폴링 지점 — navigate_menu 그리드 출현 폴링의 **회수 상한**이 배율로 확대되고(간격 불변),
     그리드 출현 실소요가 record 로 되먹여진다.

⚠ conftest 의 autouse 픽스처가 latency.reset() + record no-op 을 깔아 두므로, 여기서는
   factor/record 를 테스트별로 직접 패치해 배율·되먹임을 관측한다.
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import js_lib, latency, verify
from nbkit.omnisol.errors import MenuError
from nbkit.omnisol.navigator import GRID_APPEAR_EXPECTED_MS, navigate_menu

pytestmark = pytest.mark.asyncio


class _Recorder:
    """주입 sleeper — 실제로 자지 않고 요청된 대기(초)를 기록한다."""

    def __init__(self) -> None:
        self.naps: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.naps.append(seconds)


def _reads(values: list):
    box = list(values)

    async def read():
        return box.pop(0) if len(box) > 1 else box[0]

    return read


def _spy_record(monkeypatch) -> list[tuple[float, float]]:
    calls: list[tuple[float, float]] = []
    monkeypatch.setattr(latency, "record", lambda e, a: calls.append((e, a)))
    return calls


# ── 1. 커널 — factor 가 점증 대기에만 곱해진다(성공 경로·스케줄 모양 불변) ────────────
async def test_factor_scales_retry_waits_only(monkeypatch):
    monkeypatch.setattr(latency, "factor", lambda: 2.0)
    nap = _Recorder()
    res = await verify.confirm(
        _reads(["전체", "전체", "전체", "미결"]),
        lambda v: v == "미결",
        timing=verify.INSTANT,
        sleep=nap,
    )
    assert res.ok is True and res.attempts == 4  # 회수는 불변 — 대기만 늘어난다.
    assert nap.naps == [0.24, 0.72, 1.8]  # INSTANT(120/360/900ms) × 2.0
    assert res.waited_ms == 240 + 720 + 1_800  # waited_ms 는 실제 대기 총합.


async def test_factor_one_keeps_schedule_unchanged(monkeypatch):
    monkeypatch.setattr(latency, "factor", lambda: 1.0)
    nap = _Recorder()
    await verify.confirm(
        _reads(["전체", "전체", "전체", "미결"]),
        lambda v: v == "미결",
        timing=verify.INSTANT,
        sleep=nap,
    )
    assert nap.naps == [0.12, 0.36, 0.9]  # 무회귀 — 기존 스케줄 그대로.


async def test_first_read_success_never_waits_regardless_of_factor(monkeypatch):
    monkeypatch.setattr(latency, "factor", lambda: 4.0)
    nap = _Recorder()
    res = await verify.confirm(_reads(["미결"]), lambda v: v == "미결", sleep=nap)
    assert res.ok is True and res.waited_ms == 0
    assert nap.naps == []  # 성공 경로 불변 — 배율이 커도 추가 지연 0.


# ── 2. 되먹임 — 성공만 기록, 회차가 곧 지연 신호 ─────────────────────────────────
async def test_first_attempt_success_records_fast_signal(monkeypatch):
    calls = _spy_record(monkeypatch)
    await verify.confirm(_reads(["미결"]), lambda v: v == "미결", timing=verify.INSTANT)
    assert calls == [(120, 120)]  # 누적 대기 0 → 비율 1.0(빠름 신호 → factor 감쇠).


async def test_late_attempt_success_records_slow_signal(monkeypatch):
    calls = _spy_record(monkeypatch)
    await verify.confirm(
        _reads(["전체", "전체", "미결"]), lambda v: v == "미결", timing=verify.INSTANT
    )
    # 3회차 성공 = 명목 누적 120+360ms 대기 후 확인 → (120, 120+480) = 비율 5(클램프는 record 몫).
    assert calls == [(120, 600)]


async def test_mismatch_failure_is_not_recorded(monkeypatch):
    calls = _spy_record(monkeypatch)
    res = await verify.confirm(_reads(["전체"]), lambda v: v == "미결", timing=verify.INSTANT)
    assert res.mismatch is True
    assert calls == []  # 불일치는 지연이 아닐 수 있다 — 되먹임 제외.


async def test_unknown_failure_is_not_recorded(monkeypatch):
    calls = _spy_record(monkeypatch)
    res = await verify.confirm(
        _reads([None]), lambda v: v == "미결", timing=verify.INSTANT, unknown_when=lambda v: v is None
    )
    assert res.unknown is True
    assert calls == []


# ── 3. 폴링 지점 — navigate_menu 회수 상한 확대 + 그리드 출현 되먹임 ────────────────
class _MenuPage:
    """MENU_CHECK_JS 폴링 스텁 — grids_at 회차부터 그리드 출현(0 이면 영원히 미출현)."""

    def __init__(self, grids_at: int = 0) -> None:
        self.checks = 0
        self._grids_at = grids_at

    async def goto(self, url, **kwargs):
        return None

    async def evaluate(self, js_src, arg=None):
        assert js_src == js_lib.MENU_CHECK_JS
        self.checks += 1
        ok = self._grids_at and self.checks >= self._grids_at
        return {"grids": 1 if ok else 0, "notFound": False}

    async def wait_for_timeout(self, ms):
        return None


@pytest.fixture
def _no_notice_watch(monkeypatch):
    """진입 성공 후의 공지 배경 감시를 무음화 — 폴링 상한 계약만 검증(crash 테스트와 동일)."""
    monkeypatch.setattr("nbkit.omnisol.navigator.watch_notice_popup", lambda page, **kw: None)


async def test_navigate_menu_poll_cap_scales_with_factor(monkeypatch, _no_notice_watch):
    monkeypatch.setattr(latency, "factor", lambda: 2.0)
    page = _MenuPage(grids_at=0)
    with pytest.raises(MenuError):
        await navigate_menu(page, "/IM/TEST", "http://erp", label="테스트")
    assert page.checks == 66  # 기본 tries=33 × factor 2.0 — 폴 간격은 불변, 회수만 확대.


async def test_navigate_menu_poll_cap_unchanged_at_factor_one(monkeypatch, _no_notice_watch):
    monkeypatch.setattr(latency, "factor", lambda: 1.0)
    page = _MenuPage(grids_at=0)
    with pytest.raises(MenuError):
        await navigate_menu(page, "/IM/TEST", "http://erp", label="테스트")
    assert page.checks == 33  # 무회귀.


async def test_navigate_menu_records_grid_appearance_latency(monkeypatch, _no_notice_watch):
    calls = _spy_record(monkeypatch)
    page = _MenuPage(grids_at=1)
    await navigate_menu(page, "/IM/TEST", "http://erp", label="테스트")
    assert len(calls) == 1
    expected, actual = calls[0]
    assert expected == GRID_APPEAR_EXPECTED_MS  # 평시 기준선 대비 실소요를 되먹인다.
    assert actual >= 0
