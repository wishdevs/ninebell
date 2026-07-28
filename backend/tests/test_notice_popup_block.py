"""공지 시스템 팝업 **상시 무시**(도착 즉시 닫기) — 설치 경로 + 닫기 판정 규칙.

핵심 계약:
  1) 공지창(art_seq_no= / callComp=UFAP…)은 도착 즉시 닫힌다.
  2) 결제창(EAP: approkey/docID/callComp=UBAP…)은 **절대 닫지 않는다** — 닫으면 결재 불가.
  3) 판정 불가(빈 url·about:blank·평범한 ERP 창)는 **닫지 않는다**(fail-safe).

⚠ 이 핸들러는 PopupWatcher 와 달리 **구간 제한이 없다**(런 내내). 그래서 판정 기준이 호스트가
  아니라 공지 마커여야 한다 — 이 테스트가 그 경계를 고정한다.
"""

from __future__ import annotations

import asyncio

import pytest

from nbkit.browser import popups


class _Page:
    """닫힘 여부만 추적하는 최소 Page 스텁."""

    def __init__(self, url: str, *, closed: bool = False) -> None:
        self.url = url
        self._closed = closed
        self.close_calls = 0

    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self.close_calls += 1
        self._closed = True


class _Ctx:
    def __init__(self) -> None:
        self.handlers: list = []

    def on(self, event: str, fn) -> None:
        assert event == "page"
        self.handlers.append(fn)


NOTICE_URL = (
    "https://uc.ninebell.co.kr/#/popup?art_seq_no=1573&boardNo=14&catType=N"
    "&portlet=true&callComp=UFAP013&popupUUID=cd760060-898e-11f1-907a-b99b18e205ec"
)
APPROVAL_URL = (
    "https://uc.ninebell.co.kr/#/popup?callComp=UBAP001&docID=2026072700123"
    "&approkey=abc123&MicroModuleCode=eap"
)


async def _nap(_seconds: float) -> None:
    return None


# ── 닫기 판정 ─────────────────────────────────────────────────────────────────
async def test_notice_window_is_closed():
    page = _Page(NOTICE_URL)
    assert await popups._close_if_notice(page, _nap) == NOTICE_URL
    assert page.close_calls == 1


async def test_approval_window_is_never_closed():
    """⚠ 회귀 금지 — 결제창을 닫으면 결재 순회가 통째로 불가능해진다."""
    page = _Page(APPROVAL_URL)
    assert await popups._close_if_notice(page, _nap) is None
    assert page.close_calls == 0


@pytest.mark.parametrize(
    "url",
    ["https://erp.ninebell.co.kr/", "https://www.ninebell.co.kr/default/00/01.php", ""],
)
async def test_non_notice_windows_are_left_alone(url):
    """공지로 확정되지 않은 창은 건드리지 않는다(fail-safe) — 업무 창 보호가 우선."""
    page = _Page(url)
    assert await popups._close_if_notice(page, _nap) is None
    assert page.close_calls == 0


async def test_already_closed_page_is_noop():
    page = _Page(NOTICE_URL, closed=True)
    assert await popups._close_if_notice(page, _nap) is None
    assert page.close_calls == 0


# ── 설치 경로 ─────────────────────────────────────────────────────────────────
def test_install_registers_page_listener():
    ctx = _Ctx()
    closed = popups.install_notice_autoclose(ctx)
    assert len(ctx.handlers) == 1
    assert closed == []


def test_install_failure_is_swallowed():
    class _Bad:
        def on(self, *_a, **_k):
            raise RuntimeError("컨텍스트가 이미 닫힘")

    assert popups.install_notice_autoclose(_Bad()) == []


async def test_handler_closes_arriving_notice_window():
    """등록된 핸들러가 도착한 공지창을 실제로 닫고, 닫힌 URL 을 누적한다."""
    ctx = _Ctx()
    closed = popups.install_notice_autoclose(ctx)
    notice, approval = _Page(NOTICE_URL), _Page(APPROVAL_URL)
    for handler in ctx.handlers:
        handler(notice)
        handler(approval)
    await asyncio.sleep(0)  # 예약된 태스크 소진.
    await asyncio.sleep(0)
    assert notice.close_calls == 1
    assert approval.close_calls == 0
    assert closed == [NOTICE_URL]
