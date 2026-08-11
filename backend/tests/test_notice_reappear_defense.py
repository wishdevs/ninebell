"""공지팝업 화면별 재출현 방어 — 전환/메뉴 진입 지점의 dismiss 호출 순서 검증.

사용자 실측(2026-07-23, card-chat 라이브뷰): 하루동안 보지 않기·닫기(로그인 직후)에도
서버 정책상 화면 전환/리로드 후 공지가 재출현 — ① 회계/인사(사용자유형) 선택 화면,
② 결의서작성 화면. 공지는 화면 로드 ~1.5s 뒤 비동기 렌더라 JIT(appear_cap_ms=0)로는
부족하고 전환 직후 관찰창(2000~2500ms)이 필요하다. 여기서는:

- switch_user_type: 패널 조작 **직전** + 변경적용 reload settle **직후** NOTICE JS 조회
  (전환 실행 경로에만 — 웜 경로는 관찰창 대기 없음).
- navigate_menu: 목적 화면 도착 확인(그리드 로드) **직후** NOTICE JS 조회.
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import auth, js_lib
from nbkit.omnisol.navigator import navigate_menu

pytestmark = pytest.mark.asyncio


class _Mouse:
    async def click(self, x, y):
        return None


class _LogPage:
    """evaluate 호출을 종류별로 log 에 기록하는 스텁(공지는 항상 없음 → dismiss no-op).

    dismiss 관찰창 상한은 monotonic 실시간이라, wait_for_timeout 이 가짜 시계를 진행시키고
    modals.time.monotonic 를 그 시계로 monkeypatch 해야 공지 부재 시 관찰창이 실시간 낭비 없이
    소진된다(install_clock). 안 하면 부재 경로가 매 dismiss 마다 실 2~2.5s CPU 스핀.
    """

    def __init__(self, log: list[str], *, menu_grids: int = 1) -> None:
        self.log = log
        self._menu_grids = menu_grids
        self.mouse = _Mouse()
        self.clock_ms = 0.0

    async def goto(self, url, **kwargs):
        self.log.append("goto")

    async def evaluate(self, js_src, arg=None):
        if js_src == js_lib.NOTICE_POPUP_BOXES_JS:
            self.log.append("notice_js")
            return None  # 공지 없음 → dismiss 는 관찰창 소진 후 False(무해).
        if js_src == js_lib.MENU_CHECK_JS:
            self.log.append("menu_check")
            return {"grids": self._menu_grids, "notFound": False}
        self.log.append("other_js")
        return None

    async def wait_for_timeout(self, ms):
        self.clock_ms += ms  # 가짜 실시간 진행 — dismiss 관찰창(monotonic 상한) 소진용.

    def install_clock(self, monkeypatch) -> None:
        monkeypatch.setattr("nbkit.omnisol.modals.time.monotonic", lambda: self.clock_ms / 1_000)


async def test_menu_nav_watches_notice_in_background_after_arrival(monkeypatch):
    """메뉴 진입 성공 직후 공지 재출현 방어가 **배경으로** 시작된다.

    ⚠ 계약 변경(2026-07-28): 종전에는 도착 직후 관찰창 2.5s 를 **차단형으로** 기다렸고, 실측상
    재출현이 없는 경우가 대부분이라 매 실행 ~2.8s 를 헛대기했다. 이제 예약만 하고 즉시 반환하며
    (진입이 그만큼 빨라진다), 팝업이 뜨면 배경 감시가 닫는다. 클릭 직전 JIT 방어는 그대로다.
    """
    import asyncio

    log: list[str] = []
    page = _LogPage(log)
    page.install_clock(monkeypatch)
    await navigate_menu(page, "/IM/TEST", "http://erp", label="테스트")
    # 반환 시점에는 아직 공지 조회가 일어나지 않았어야 한다(= 기다리지 않았다).
    assert "notice_js" not in log
    # 배경 태스크를 소진시키면 그때 방어가 돈다.
    for _ in range(50):
        await asyncio.sleep(0)
        if "notice_js" in log:
            break
    assert "notice_js" in log
    assert log.index("menu_check") < log.index("notice_js")


async def test_switch_user_type_dismisses_before_and_after_switch(monkeypatch):
    """전환 실행 경로: 패널 조작 직전 + 변경적용 reload settle 직후에 NOTICE JS 가 조회된다.

    (2026-07-31 전환) reload settle 은 networkidle(옴니솔에서 못 잡아 상한 12s 소진 패턴)이
    아니라 조건 폴링 `_wait_reload_after_apply`(마커 소멸 → 아바타 재출현)다 — 계약(순서)은
    동일: settle **뒤에** 공지 dismiss, 그 뒤에 재확인 패널 오픈.
    """
    log: list[str] = []
    page = _LogPage(log)
    page.install_clock(monkeypatch)
    reads = iter(["인사사용자(예외)", "회계사용자"])  # 전환 전 → 전환 후 재확인.

    async def _panel(p):
        log.append("panel")

    async def _read(p):
        return next(reads)

    async def _switch(p, target, **_kw):  # **_kw: 라벨 해석 결과(exact=…)를 무시하는 스텁.
        log.append("switch")
        return True

    async def _settle(p):
        log.append("reload_settle")

    monkeypatch.setattr(auth, "open_user_panel", _panel)
    monkeypatch.setattr(auth, "read_current_user_type", _read)
    monkeypatch.setattr(auth, "_switch_user_type_real", _switch)
    monkeypatch.setattr(auth, "_wait_reload_after_apply", _settle)

    await auth.switch_user_type(page, "회계")

    i_switch = log.index("switch")
    # ① 패널 조작(전환 실클릭) 직전 관찰창 dismiss — 직전 화면에서 늦게 뜬 공지 흡수.
    assert "notice_js" in log[:i_switch]
    # ② 변경적용 reload settle(조건 폴링) 뒤·재확인 패널 열기 전 dismiss.
    i_settle = log.index("reload_settle")
    i_repanel = log.index("panel", i_settle)  # settle 후 재확인 패널 오픈.
    assert "notice_js" in log[i_settle:i_repanel]


async def test_switch_user_type_warm_path_skips_notice_wait(monkeypatch):
    """웜 경로(이미 target): 전환이 스킵되므로 관찰창 dismiss 도 안 돈다(불필요 대기 금지)."""
    log: list[str] = []
    page = _LogPage(log)

    async def _panel(p):
        log.append("panel")

    async def _read(p):
        return "회계사용자"

    monkeypatch.setattr(auth, "open_user_panel", _panel)
    monkeypatch.setattr(auth, "read_current_user_type", _read)

    await auth.switch_user_type(page, "회계")
    assert "notice_js" not in log
