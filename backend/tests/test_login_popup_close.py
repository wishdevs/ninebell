"""로그인 시 뜨는 **시스템 팝업(별도 창)** 닫기 계약 — 브라우저 없이.

실측 배경(2026-07-27, `e2e/login_popup_probe.py`): 계정에 따라 로그인 직후 회사 홈페이지가
별도 창으로 뜬다(`http://www.ninebell.co.kr/...` / '주식회사 나인벨'). 메인 페이지의 인페이지
다이얼로그는 **0개**라 공지 팝업 닫기(`dismiss_notice_popup`)로는 잡히지 않는다.

⚠ 가장 중요한 계약: **결제(결재)창을 죽이지 않는다.** 결제창도 다른 호스트의 시스템 팝업이라,
  감시가 로그인 구간을 넘어 살아 있으면 정상 업무 창을 닫아버린다.
"""

from __future__ import annotations

import pytest

from nbkit.browser.popups import PopupWatcher

pytestmark = pytest.mark.asyncio

ERP = "https://erp.ninebell.co.kr"


async def _nap(_seconds: float) -> None:
    """관찰 대기 주입(실시간 sleep 대신 즉시 반환)."""
    return None


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class _FakeContext:
    """Playwright BrowserContext 의 on/remove_listener 만 흉내낸다."""

    def __init__(self) -> None:
        self.handlers: list = []

    def on(self, event: str, handler) -> None:
        assert event == "page"
        self.handlers.append(handler)

    def remove_listener(self, event: str, handler) -> None:
        assert event == "page"
        self.handlers.remove(handler)

    def emit_page(self, page) -> None:
        for h in list(self.handlers):
            h(page)


def _watch():
    ctx = _FakeContext()
    main = _FakePage(ERP)
    return ctx, main, PopupWatcher(ctx, main).start()


async def test_closes_company_homepage_popup():
    ctx, _main, w = _watch()
    home = _FakePage("http://www.ninebell.co.kr/default/00/01.php")
    ctx.emit_page(home)
    closed = await w.close_foreign(ERP, sleep=_nap)
    assert home.closed is True
    assert closed == ["http://www.ninebell.co.kr/default/00/01.php"]


async def test_keeps_erp_host_popup():
    # 같은 ERP 호스트 창은 업무 창일 수 있다 — 닫지 않는다.
    ctx, _main, w = _watch()
    erp_popup = _FakePage("https://erp.ninebell.co.kr/FI/GLDDOC00700")
    ctx.emit_page(erp_popup)
    closed = await w.close_foreign(ERP, sleep=_nap)
    assert erp_popup.closed is False and closed == []


async def test_never_touches_main_page():
    ctx, main, w = _watch()
    ctx.emit_page(main)  # 메인 페이지가 이벤트로 들어와도 대상이 아니다.
    await w.close_foreign(ERP, sleep=_nap)
    assert main.closed is False


async def test_stop_removes_listener_so_later_popups_survive():
    """⚠ 핵심 안전 계약: 로그인 구간이 끝나면 이후 팝업(결제창)은 감시 대상이 아니다."""
    ctx, _main, w = _watch()
    w.stop()
    assert ctx.handlers == []
    eap = _FakePage("https://eap.example.com/approval/12345")  # 결재창(다른 호스트)
    ctx.emit_page(eap)
    closed = await w.close_foreign(ERP, sleep=_nap)
    assert eap.closed is False and closed == []


async def test_no_popup_returns_empty_without_error():
    _ctx, _main, w = _watch()
    assert await w.close_foreign(ERP, sleep=_nap) == []


async def test_waits_for_about_blank_to_settle_before_deciding():
    """갓 열린 창은 about:blank — 목적지 URL 이 정해진 뒤에 호스트를 판정해야 한다."""

    class _LatePage(_FakePage):
        def __init__(self) -> None:
            super().__init__("about:blank")
            self._reads = 0

        @property  # type: ignore[misc]
        def url(self):  # noqa: D401
            self._reads += 1
            return "about:blank" if self._reads < 3 else "http://www.ninebell.co.kr/"

        @url.setter
        def url(self, v):
            pass

    ctx, _main, w = _watch()
    late = _LatePage()
    ctx.emit_page(late)
    closed = await w.close_foreign(ERP, sleep=_nap)
    assert late.closed is True and closed == ["http://www.ninebell.co.kr/"]


async def test_already_closed_popup_is_skipped():
    ctx, _main, w = _watch()
    gone = _FakePage("http://www.ninebell.co.kr/")
    gone.closed = True
    ctx.emit_page(gone)
    assert await w.close_foreign(ERP, sleep=_nap) == []


async def test_close_failure_does_not_raise():
    class _Stubborn(_FakePage):
        async def close(self):
            raise RuntimeError("target closed")

    ctx, _main, w = _watch()
    ctx.emit_page(_Stubborn("http://www.ninebell.co.kr/"))
    assert await w.close_foreign(ERP, sleep=_nap) == []  # 예외를 삼키고 계속.


# ── 로그인 플로우 배선 ────────────────────────────────────────────────────────
async def test_ensure_logged_in_closes_popup_and_stops_watching(monkeypatch):
    from nbkit.patterns import login_flow

    ctx = _FakeContext()

    class _Page(_FakePage):
        def __init__(self):
            super().__init__(ERP)
            self.context = ctx

    page = _Page()

    async def _login(pg, uid, pw, base):
        ctx.emit_page(_FakePage("http://www.ninebell.co.kr/default/00/01.php"))  # 로그인 중 팝업

    async def _dismiss(pg, **kw):
        return None

    async def _profile(pg):
        return {"name": "석대현"}

    monkeypatch.setattr(login_flow, "omnisol_login", _login)
    monkeypatch.setattr(login_flow, "dismiss_notice_popup", _dismiss)
    monkeypatch.setattr(login_flow, "read_profile", _profile)

    out = await login_flow.ensure_logged_in(page, "석대현", "***", ERP)
    assert out["profile"] == {"name": "석대현"}
    # 감시는 로그인 구간에서만 — 끝나면 리스너가 남지 않는다(결제창 보호).
    assert ctx.handlers == []


async def test_ensure_logged_in_stops_watching_even_when_login_fails(monkeypatch):
    from nbkit.patterns import login_flow

    ctx = _FakeContext()

    class _Page(_FakePage):
        def __init__(self):
            super().__init__(ERP)
            self.context = ctx

    async def _boom(pg, uid, pw, base):
        raise RuntimeError("자격증명 오류")

    monkeypatch.setattr(login_flow, "omnisol_login", _boom)
    with pytest.raises(RuntimeError):
        await login_flow.ensure_logged_in(_Page(), "석대현", "***", ERP)
    assert ctx.handlers == []  # 실패 경로에서도 리스너 누수 없음.


# ── 즉시 닫기(auto_close) — 구간 중 아무 때나 도착해도 닫힌다 ───────────────────
async def test_auto_close_closes_popup_arriving_late_in_the_window():
    """⚠ 회귀 핵심(2026-07-27 라이브): 팝업은 로그인 시퀀스 중 시점이 일정하지 않다.
    공지 정리 뒤(=첫 sweep 이후, 프로필 읽기 중)에 도착해도 닫혀야 한다."""
    ctx = _FakeContext()
    main = _FakePage(ERP)
    w = PopupWatcher(ctx, main, auto_close_base=ERP).start()

    first = await w.close_foreign(ERP, sleep=_nap)  # 아직 아무것도 안 뜬 시점의 sweep
    assert first == []

    late = _FakePage("http://www.ninebell.co.kr/default/00/01.php")
    ctx.emit_page(late)  # 첫 sweep 이후 도착(프로필 읽기 구간)
    closed = await w.close_foreign(ERP, appear_cap_ms=0, sleep=_nap)
    assert late.closed is True and closed == ["http://www.ninebell.co.kr/default/00/01.php"]


async def test_auto_close_keeps_erp_popup_arriving_late():
    ctx = _FakeContext()
    w = PopupWatcher(ctx, _FakePage(ERP), auto_close_base=ERP).start()
    erp_popup = _FakePage("https://erp.ninebell.co.kr/FI/GLDDOC00700")
    ctx.emit_page(erp_popup)
    assert await w.close_foreign(ERP, appear_cap_ms=0, sleep=_nap) == []
    assert erp_popup.closed is False


async def test_ensure_logged_in_closes_popup_arriving_during_profile_read(monkeypatch):
    """로그인 함수 배선 회귀 — 프로필 읽기 중 뜬 창도 닫고 로그로 보고한다."""
    from nbkit.patterns import login_flow

    ctx = _FakeContext()
    late = _FakePage("http://www.ninebell.co.kr/default/00/01.php")

    class _Page(_FakePage):
        def __init__(self):
            super().__init__(ERP)
            self.context = ctx

    async def _login(pg, uid, pw, base):
        return None

    async def _dismiss(pg, **kw):
        return None

    async def _profile(pg):
        ctx.emit_page(late)  # ⚠ 첫 sweep 이후 시점에 팝업 도착.
        return {"name": "석대현"}

    logs: list = []

    async def _emit(frame):
        logs.append(frame)

    monkeypatch.setattr(login_flow, "omnisol_login", _login)
    monkeypatch.setattr(login_flow, "dismiss_notice_popup", _dismiss)
    monkeypatch.setattr(login_flow, "read_profile", _profile)

    await login_flow.ensure_logged_in(_Page(), "석대현", "***", ERP, emit=_emit)
    assert late.closed is True
    assert any("외부 창을 닫았습니다" in str(f.get("log", "")) for f in logs)
    assert ctx.handlers == []


# ── JIT 정리(로그인 이후 도착분) — close_foreign_pages ─────────────────────────
from nbkit.browser.popups import close_foreign_pages  # noqa: E402


class _CtxWithPages:
    def __init__(self, pages) -> None:
        self.pages = pages


class _PageWithCtx(_FakePage):
    def __init__(self, url, pages) -> None:
        super().__init__(url)
        self.context = _CtxWithPages(pages)


async def test_close_foreign_pages_closes_late_arrival_and_keeps_others():
    main = _FakePage(ERP)
    home = _FakePage("http://www.ninebell.co.kr/default/00/01.php")
    erp_win = _FakePage("https://erp.ninebell.co.kr/FI/GLDDOC00700")
    page = _PageWithCtx(ERP, [])
    page.context.pages = [main, home, erp_win, page]

    closed = await close_foreign_pages(page, ERP)
    assert home.closed is True
    assert erp_win.closed is False and main.closed is False and page.closed is False
    assert closed == ["http://www.ninebell.co.kr/default/00/01.php"]


async def test_close_foreign_pages_is_noop_without_context():
    assert await close_foreign_pages(_FakePage(ERP), ERP) == []


async def test_user_type_node_cleans_foreign_popup_before_switching(monkeypatch):
    """사용자유형 전환 **전에** 외부 창을 치운다(포커스 탈취로 아바타 클릭이 막히지 않게)."""
    import asyncio

    from app.agents.common import nodes as common_nodes

    home = _FakePage("http://www.ninebell.co.kr/")
    page = _PageWithCtx(ERP, [])
    page.context.pages = [page, home]
    order: list[str] = []

    async def _ensure(pg, target, emit=None):
        order.append(f"switch:{target}")

    monkeypatch.setattr(common_nodes, "ensure_user_type", _ensure)
    out = await common_nodes.make_user_type_node("회계")(
        {"events": asyncio.Queue(), "page": page}
    )
    assert out == {}
    assert home.closed is True  # 전환 전에 닫혔다.
    assert order == ["switch:회계"]


# ── 로그인 이후 단계에서도 팝업은 남으면 안 된다(사용자 요구 2026-07-27) ──────────
# 실측: 더존 공지창(uc.ninebell.co.kr)이 로그인 완료 +252ms 에 뜨고, **닫아도 메뉴 진입 후
# 다시 뜬다**. 그래서 로그인 구간 감시만으로는 부족하고 각 단계에 JIT 정리가 필요하다.
async def test_menu_nav_node_closes_popup_that_appears_after_navigation(monkeypatch):
    import asyncio

    from app.agents.common import nodes as common_nodes

    notice = _FakePage("https://uc.ninebell.co.kr/#/popup?art_seq_no=1573")
    page = _PageWithCtx(ERP, [])
    page.context.pages = [page]

    async def _navigate(pg, schema, base, emit=None):
        page.context.pages.append(notice)  # 메뉴 진입 도중/직후 공지창 출현

    monkeypatch.setattr(common_nodes, "navigate_schema", _navigate)
    out = await common_nodes.make_menu_nav_node()({"events": asyncio.Queue(), "page": page})
    assert out == {}
    assert notice.closed is True


async def test_approval_loop_sweeps_popups_before_opening_child(monkeypatch):
    """결제창을 열기 **직전**에도 정리한다 — 공지창이 화면을 덮으면 결재 클릭이 가로채인다."""
    import asyncio

    from app.agents.voucher_receivable.nodes import approvals

    notice = _FakePage("https://uc.ninebell.co.kr/#/popup?art_seq_no=1573")

    class _Page(_PageWithCtx):
        async def evaluate(self, js_src, arg=None):
            return True

        async def wait_for_timeout(self, ms):
            return None

    page = _Page(ERP, [])
    page.context.pages = [page, notice]
    order: list[str] = []

    async def _key(pg, idx):
        return f"FI{idx}"

    async def _uncheck(pg):
        return True

    async def _check(pg, idx):
        return True

    async def _checked(pg):
        return {"ok": True, "rows": [0]}

    async def _open(pg, **kw):
        order.append("open_approval")
        assert notice.closed is True, "결제창을 열기 전에 외부 창이 닫혀 있어야 한다"
        return None  # 이후 경로는 이 테스트의 관심사가 아니다.

    for name, fn in (("read_row_key", _key), ("uncheck_all_rows", _uncheck),
                     ("check_row", _check), ("checked_row_indexes", _checked),
                     ("open_approval", _open)):
        monkeypatch.setattr(approvals.steps, name, fn)

    out = await approvals.make_loop_approvals_node()(
        {"events": asyncio.Queue(), "page": page, "master_rowcount": 1}
    )
    assert "error" in out and order == ["open_approval"]


# ══════════════════════════════════════════════════════════════════════════════
# ⚠⚠ 업무 창 보호 — 결제창과 공지창이 **같은 호스트·같은 경로**다(2026-07-27 실측)
#   공지: uc.ninebell.co.kr/#/popup?art_seq_no=1573&…&callComp=UFAP013
#   결제: uc.ninebell.co.kr/#/popup?callComp=UBAP001&docID=…&approkey=…&MicroModuleCode=eap
#   호스트만 보고 닫으면 결제창을 죽인다 — 파라미터로 구분해야 한다.
# ══════════════════════════════════════════════════════════════════════════════
from nbkit.browser.popups import is_approval_window, is_notice_window  # noqa: E402

_APPROVAL_URL = (
    "https://uc.ninebell.co.kr/#/popup?callComp=UBAP001&docID=1015671"
    "&approkey=1000_FI_GWA2026072794&formId=1077&MicroModuleCode=eap&docAuth=0"
)
_NOTICE_URL = (
    "https://uc.ninebell.co.kr/#/popup?art_seq_no=1573&boardNo=14&catType=N"
    "&portlet=true&callComp=UFAP013&popupUUID=cd760060"
)


async def test_url_classifier_separates_approval_from_notice():
    assert is_approval_window(_APPROVAL_URL) is True
    assert is_approval_window(_NOTICE_URL) is False
    assert is_notice_window(_NOTICE_URL) is True
    assert is_notice_window(_APPROVAL_URL) is False


async def test_close_foreign_pages_never_closes_approval_window():
    """⚠ 안전 크리티컬: 결제창은 외부 호스트여도 **절대** 닫지 않는다."""
    approval = _FakePage(_APPROVAL_URL)
    notice = _FakePage(_NOTICE_URL)
    page = _PageWithCtx(ERP, [])
    page.context.pages = [page, approval, notice]

    closed = await close_foreign_pages(page, ERP)
    assert approval.closed is False, "결제창이 닫혔다 — 업무 창 보호 실패"
    assert notice.closed is True
    assert closed == [_NOTICE_URL]


async def test_watcher_auto_close_protects_approval_window():
    ctx = _FakeContext()
    w = PopupWatcher(ctx, _FakePage(ERP), auto_close_base=ERP).start()
    approval = _FakePage(_APPROVAL_URL)
    ctx.emit_page(approval)
    assert await w.close_foreign(ERP, appear_cap_ms=0, sleep=_nap) == []
    assert approval.closed is False


async def test_notice_window_suppressed_before_closing():
    """공지창은 그냥 닫으면 화면 전환마다 다시 뜬다 — '하루동안 열지 않기'를 먼저 누른다."""

    class _NoticePage(_FakePage):
        def __init__(self):
            super().__init__(_NOTICE_URL)
            self.suppressed = False

        def get_by_text(self, text, exact=False):
            page = self

            class _Loc:
                @property
                def first(self):
                    return self

                async def click(self, timeout=None):
                    assert text == "하루동안 열지 않기"
                    page.suppressed = True

            return _Loc()

    notice = _NoticePage()
    page = _PageWithCtx(ERP, [])
    page.context.pages = [page, notice]
    await close_foreign_pages(page, ERP)
    assert notice.suppressed is True and notice.closed is True
