"""메뉴 진입 크래시 복구 — navigate 의 렌더러 크래시 한정 1회 재시도 계약.

라이브 실증(2026-07-31, gyeongjo-grant): menu_nav 의 page.goto 가 "Page.goto: Page crashed"
로 즉사했고 2분 뒤 동일 경로가 정상 진입 — 일시적 렌더러 크래시였다. 고정하는 계약:
  ① 크래시 1회 → 같은 컨텍스트 새 페이지로 진입 1회 재시도, 성공 시 **새 page 반환**.
  ② 크래시 2회 → 기존과 같은 실패(크래시 예외 전파·menu_nav failed).
  ③ 일반 타임아웃/권한 오류(MenuError) → 재시도 없이 기존 즉시 실패(동작 불변).
부가: 대기 배율 프록시(_ScaledPage 형)면 새 페이지를 같은 배율로 재래핑해 반환한다.
"""

from __future__ import annotations

import pytest

from nbkit.omnisol.errors import MenuError
from nbkit.omnisol.menu_schemas import EXPENSE_CARD
from nbkit.patterns.menu_navigate_flow import navigate, navigate_schema

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _mute_notice_watch(monkeypatch):
    """진입 성공 후의 공지 배경 감시(watch_notice_popup)를 무음화 — 크래시 계약만 검증."""
    monkeypatch.setattr(
        "nbkit.omnisol.navigator.watch_notice_popup", lambda page, **kw: None
    )


class _FakeCtx:
    """new_page 호출 횟수와 다음에 내줄 페이지를 통제하는 컨텍스트 스텁."""

    def __init__(self) -> None:
        self.pages_to_serve: list = []
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        if not self.pages_to_serve:
            raise RuntimeError("no fresh page available")
        return self.pages_to_serve.pop(0)


class _FakePage:
    """goto 가 지정 예외를 던지거나, MENU_CHECK 폴링에 grids/notFound 를 돌려주는 페이지."""

    def __init__(self, ctx=None, *, goto_exc=None, grids=1, not_found=False) -> None:
        self.context = ctx
        self.goto_exc = goto_exc
        self.grids = grids
        self.not_found = not_found
        self.goto_urls: list[str] = []
        self.closed = False

    async def goto(self, url, **kw):
        self.goto_urls.append(url)
        if self.goto_exc is not None:
            raise self.goto_exc

    async def evaluate(self, js_src, arg=None):
        return {"grids": self.grids, "notFound": self.not_found, "popup": "메뉴를 찾을 수 없습니다"}

    async def wait_for_timeout(self, ms):
        return None

    async def close(self):
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


def _collector():
    frames: list[dict] = []

    async def emit(ev: dict) -> None:
        frames.append(ev)

    return frames, emit


def _step_statuses(frames: list[dict]) -> list[str]:
    return [f["status"] for f in frames if f.get("step") == "menu_nav"]


def _logs(frames: list[dict], level: str | None = None) -> list[str]:
    return [f["log"] for f in frames if "log" in f and (level is None or f.get("level") == level)]


# ── ① 크래시 1회 → 새 페이지 재시도 성공 ─────────────────────────────────────────
async def test_crash_once_retries_on_fresh_page_and_returns_it():
    ctx = _FakeCtx()
    fresh = _FakePage(ctx)  # grids=1 → 재시도는 성공.
    ctx.pages_to_serve = [fresh]
    old = _FakePage(ctx, goto_exc=RuntimeError("Page.goto: Page crashed"))
    frames, emit = _collector()

    out = await navigate(old, "/IM/TEST", "http://erp", emit=emit)

    assert out is fresh  # 이후 플로우가 쓸 page 로 새 페이지를 돌려준다.
    assert ctx.new_page_calls == 1
    assert old.closed is True  # 크래시 페이지는 정리(렌더러 자원 반환).
    assert fresh.goto_urls == ["http://erp/IM/TEST"]
    assert _step_statuses(frames)[-1] == "done"
    warns = _logs(frames, "warn")
    assert any("크래시 감지" in w for w in warns)
    assert any("복구 성공" in w for w in warns)  # 성공도 사용자에게 보인다.


async def test_navigate_schema_returns_replaced_page_too():
    ctx = _FakeCtx()
    fresh = _FakePage(ctx, grids=EXPENSE_CARD.grids_expected)  # 스키마 기대 그리드 수 충족.
    ctx.pages_to_serve = [fresh]
    old = _FakePage(ctx, goto_exc=RuntimeError("Target crashed"))

    out = await navigate_schema(old, EXPENSE_CARD, "http://erp")

    assert out is fresh
    assert fresh.goto_urls == [f"http://erp{EXPENSE_CARD.deeplink}"]


# ── ② 크래시 2회 → 기존과 같은 실패 ────────────────────────────────────────────
async def test_crash_twice_fails_with_original_crash_error():
    ctx = _FakeCtx()
    ctx.pages_to_serve = [_FakePage(ctx, goto_exc=RuntimeError("Page.goto: Page crashed"))]
    old = _FakePage(ctx, goto_exc=RuntimeError("Page.goto: Page crashed"))
    frames, emit = _collector()

    with pytest.raises(RuntimeError, match="Page crashed"):
        await navigate(old, "/IM/TEST", "http://erp", emit=emit)

    assert ctx.new_page_calls == 1  # 재시도는 정확히 1회.
    assert _step_statuses(frames)[-1] == "failed"
    assert any("복구 실패" in m for m in _logs(frames, "error"))  # 실패도 사용자에게 보인다.


async def test_crash_recovery_page_creation_failure_reraises_crash():
    """컨텍스트까지 죽어 새 페이지를 못 만들면 — 원인(크래시) 예외를 그대로 올린다."""
    ctx = _FakeCtx()  # pages_to_serve 비어 있음 → new_page 실패.
    old = _FakePage(ctx, goto_exc=RuntimeError("Page.goto: Page crashed"))
    frames, emit = _collector()

    with pytest.raises(RuntimeError, match="Page crashed"):
        await navigate(old, "/IM/TEST", "http://erp", emit=emit)

    assert _step_statuses(frames)[-1] == "failed"
    assert any("새 페이지를 만들지 못했습니다" in m for m in _logs(frames, "error"))


# ── ③ 크래시가 아닌 오류 → 재시도 없이 기존 동작 ──────────────────────────────────
async def test_plain_timeout_does_not_retry():
    ctx = _FakeCtx()
    ctx.pages_to_serve = [_FakePage(ctx)]
    old = _FakePage(ctx, goto_exc=RuntimeError("Timeout 25000ms exceeded."))
    frames, emit = _collector()

    with pytest.raises(RuntimeError, match="Timeout"):
        await navigate(old, "/IM/TEST", "http://erp", emit=emit)

    assert ctx.new_page_calls == 0  # 새 페이지 시도 자체가 없다.
    assert old.closed is False
    assert _step_statuses(frames)[-1] == "failed"
    assert _logs(frames, "warn") == []  # 크래시 경고도 없다(기존 프레임과 동일).


async def test_permission_popup_menu_error_does_not_retry():
    """goto 는 성공했지만 권한 팝업(MenuError) — 도메인 실패는 재시도 대상이 아니다."""
    ctx = _FakeCtx()
    ctx.pages_to_serve = [_FakePage(ctx)]
    old = _FakePage(ctx, grids=0, not_found=True)
    frames, emit = _collector()

    with pytest.raises(MenuError):
        await navigate(old, "/IM/TEST", "http://erp", emit=emit, label="테스트")

    assert ctx.new_page_calls == 0
    assert _step_statuses(frames)[-1] == "failed"


async def test_success_path_returns_original_page_unchanged():
    ctx = _FakeCtx()
    page = _FakePage(ctx)
    out = await navigate(page, "/IM/TEST", "http://erp")
    assert out is page
    assert ctx.new_page_calls == 0


# ── 대기 배율 프록시(_ScaledPage 형) 재래핑 ─────────────────────────────────────
class _ScaledProxy:
    """runner._ScaledPage 와 동일 시맨틱(생성자 (page, scale)·_page/_scale·위임)의 미니 복제."""

    def __init__(self, page, scale: float) -> None:
        object.__setattr__(self, "_page", page)
        object.__setattr__(self, "_scale", scale)

    async def wait_for_timeout(self, ms):
        return await self._page.wait_for_timeout(ms * self._scale)

    def __getattr__(self, name):
        return getattr(self._page, name)


async def test_scaled_proxy_is_rewrapped_with_same_scale():
    """교체된 페이지도 대기 배율을 유지해야 한다(card-collect 등 delay_scale 런 보존)."""
    ctx = _FakeCtx()
    fresh_raw = _FakePage(ctx)
    ctx.pages_to_serve = [fresh_raw]
    old_raw = _FakePage(ctx, goto_exc=RuntimeError("Page.goto: Page crashed"))
    proxy = _ScaledProxy(old_raw, 0.4)

    out = await navigate(proxy, "/IM/TEST", "http://erp")

    assert isinstance(out, _ScaledProxy)
    assert out._page is fresh_raw and out._scale == 0.4
    assert old_raw.closed is True  # close 는 원본(raw)에 간다.


# ── step_id 계약(2026-09-01) — 워커 재진입은 스텝 프레임을 억제한다(로그는 유지) ──
async def test_step_id_none_suppresses_step_frames_but_keeps_logs():
    """병렬 워커의 화면 재진입이 완료된 menu_nav 를 running 으로 되돌리지 않는다."""
    page = _FakePage(_FakeCtx())
    frames, emit = _collector()

    out = await navigate(page, "/IM/TEST", "http://erp", emit=emit, step_id=None)

    assert out is page
    assert _step_statuses(frames) == []  # 스텝 프레임 없음
    assert any("메뉴 진입 중" in line for line in _logs(frames))  # 로그는 그대로


async def test_default_step_id_still_emits_menu_nav():
    """기존 호출부(step_id 미지정)는 동작 불변 — running→done 방출."""
    page = _FakePage(_FakeCtx())
    frames, emit = _collector()

    await navigate(page, "/IM/TEST", "http://erp", emit=emit)

    assert _step_statuses(frames) == ["running", "done"]
