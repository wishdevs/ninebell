"""브라우저 **시스템 팝업**(window.open 으로 뜨는 별도 창) 처리 — 인페이지 모달과 다른 축.

옴니솔 로그인 시 **계정에 따라** 회사 홈페이지가 별도 창으로 뜬다(사용자 리포트 2026-07-27,
실측: 계정 '석대현' → ``http://www.ninebell.co.kr/default/00/01.php`` / '주식회사 나인벨',
메인 페이지의 인페이지 다이얼로그는 0개 — `e2e/artifacts/login_popup_probe.json`).
공지 팝업 닫기(`nbkit.omnisol.modals.dismiss_notice_popup`)는 **인페이지 레이어** 전용이라
이 창은 전혀 잡지 못한다. 이 모듈이 그 자리를 메운다.

⚠⚠ 범위를 반드시 로그인 구간으로 한정할 것 ⚠⚠
  결제(결재)창(EAP)도 **다른 호스트의 시스템 팝업**이다 — 상시 자동 닫기를 걸면 정상 업무 창을
  죽인다. 그래서 이 모듈은 "감시 시작 → 로그인 → 그 사이 뜬 외부 창만 닫기"라는 **명시적 구간**
  API 로만 제공한다(전역 훅 없음).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 팝업이 뜰 때까지의 관찰 상한(실시간). 로그인 직후 비동기로 뜨므로 0ms 확인만으론 놓친다.
DEFAULT_APPEAR_CAP_MS = 2_000
_APPEAR_INTERVAL_MS = 200
# 갓 열린 창은 잠시 about:blank 다 — 목적지 URL 이 정해질 때까지의 대기 상한(실시간).
_URL_SETTLE_CAP_MS = 1_500
_URL_SETTLE_INTERVAL_MS = 100

# ⚠⚠ 업무 창 보호(2026-07-27 실측으로 확정한 안전 결함) ⚠⚠
#   결제창(EAP)과 공지창이 **같은 호스트·같은 경로**다:
#     공지: uc.ninebell.co.kr/#/popup?art_seq_no=1573&…&callComp=UFAP013
#     결제: uc.ninebell.co.kr/#/popup?callComp=UBAP001&docID=…&approkey=…&MicroModuleCode=eap
#   따라서 "ERP 호스트가 아니면 닫는다"는 규칙만으로는 **결제창을 죽인다**. 결제 파라미터가
#   보이면 무슨 일이 있어도 닫지 않는다(호출 시점 제약과 무관한 최종 방어선).
_APPROVAL_MARKERS = ("approkey=", "docid=", "micromodulecode=eap", "callcomp=ubap")
# 공지 게시글 팝업(닫아도 화면 전환마다 다시 뜬다) — 게시글 번호/공지 컴포넌트로 식별한다.
_NOTICE_MARKERS = ("art_seq_no=", "callcomp=ufap")
# 공지창의 재출현을 막는 버튼(스크린샷 실측). '더이상'은 영구 설정이라 쓰지 않는다.
_NOTICE_SUPPRESS_TEXT = "하루동안 열지 않기"


def is_approval_window(url: str | None) -> bool:
    """결제(결재)창인가 — **절대 닫으면 안 되는 업무 창**."""
    u = (url or "").lower()
    return any(m in u for m in _APPROVAL_MARKERS)


def is_notice_window(url: str | None) -> bool:
    """공지 게시글 팝업인가(닫기 전에 '하루동안 열지 않기'를 눌러 재출현을 막는다)."""
    u = (url or "").lower()
    return any(m in u for m in _NOTICE_MARKERS)


async def _suppress_notice(page: Any) -> bool:
    """공지창의 '하루동안 열지 않기'를 눌러 **재출현을 막는다**(실패해도 무해).

    ⚠ 그냥 닫기만 하면 화면 전환마다 다시 뜬다(실측: 로그인 후·메뉴 진입 후 반복 출현) —
      사람이 하는 것과 같은 조치를 취해야 런 내내 조용해진다. 영구 설정('더이상 열지 않기')은
      사용자 환경을 바꾸므로 쓰지 않는다.
    """
    try:
        loc = page.get_by_text(_NOTICE_SUPPRESS_TEXT, exact=True)
        await loc.first.click(timeout=1_500)
        return True
    except Exception:  # noqa: BLE001 — 버튼이 없거나 이미 닫힘 — 그냥 창을 닫으면 된다.
        logger.debug("공지창 '하루동안 열지 않기' 클릭 실패(무시)", exc_info=True)
        return False


class PopupWatcher:
    """구간 동안 새로 열린 Page 를 모아두는 감시자.

    ``start()`` → (작업) → ``close_foreign(base)`` → ``stop()`` 순서로 쓴다.
    리스너는 반드시 ``stop()`` 으로 떼어낸다(다음 구간의 정상 팝업까지 잡지 않도록).
    """

    def __init__(self, context: Any, main_page: Any, *, auto_close_base: str | None = None) -> None:
        self._context = context
        self._main = main_page
        self._pages: list[Any] = []
        self._tasks: list[Any] = []
        self._closed: list[str] = []
        self._auto_base = auto_close_base
        self._started = False

    def _on_page(self, page: Any) -> None:
        """새 창 도착 — 감시 목록에 넣고, auto_close 모드면 **즉시** 닫기를 예약한다.

        ⚠ 즉시 닫기가 필요한 이유(2026-07-27 실측): 이 팝업은 로그인 시퀀스 중 **일정하지 않은
        시점**에 뜬다(공지 정리 뒤·프로필 읽기 중에 온 사례). 한 지점에서 한 번만 훑으면
        그 뒤에 온 창을 놓친다 — 구간 내내 도착하는 대로 처리해야 확실히 닫힌다.
        """
        if page is self._main:
            return
        self._pages.append(page)
        if not self._auto_base:
            return
        try:
            self._tasks.append(asyncio.create_task(self._close_if_foreign(page, self._auto_base)))
        except RuntimeError:  # 실행 중 이벤트 루프 없음(동기 스텁) — 최종 sweep 이 처리한다.
            logger.debug("팝업 즉시 닫기 예약 실패(최종 정리로 대체)", exc_info=True)

    async def _close_if_foreign(self, page: Any, base: str) -> None:
        """도착한 창의 목적지가 정해지면 외부 호스트일 때만 닫는다(ERP 창은 보존)."""
        try:
            url = await _settled_url(page, asyncio.sleep)
            if not _host(url) or _host(url) == _host(base):
                return
            if is_approval_window(url):
                logger.info("결제창은 보호합니다(닫지 않음) — %s", url)
                return
            if page.is_closed():
                return
            if is_notice_window(url):
                await _suppress_notice(page)
            await page.close()
            self._closed.append(url)
            logger.info("로그인 중 뜬 외부 창을 닫았습니다 — %s", url)
        except Exception:  # noqa: BLE001 — 이미 닫힘/유실은 무해.
            logger.debug("팝업 즉시 닫기 실패(무시)", exc_info=True)

    def start(self) -> "PopupWatcher":
        """감시 시작 — **작업 시작 전에** 호출해야 그 사이 뜬 창을 놓치지 않는다."""
        try:
            self._context.on("page", self._on_page)
            self._started = True
        except Exception:  # noqa: BLE001 — 스텁 컨텍스트 등(best-effort).
            logger.debug("PopupWatcher 리스너 등록 실패(무시)", exc_info=True)
        return self

    def stop(self) -> None:
        """감시 종료 — 리스너를 뗀다(이후 정상 업무 팝업은 건드리지 않는다)."""
        if not self._started:
            return
        try:
            self._context.remove_listener("page", self._on_page)
        except Exception:  # noqa: BLE001
            logger.debug("PopupWatcher 리스너 해제 실패(무시)", exc_info=True)
        self._started = False

    async def close_foreign(
        self,
        base: str,
        *,
        appear_cap_ms: int = DEFAULT_APPEAR_CAP_MS,
        sleep: Optional[Any] = None,
    ) -> list[str]:
        """``base`` 와 **호스트가 다른** 팝업 창을 닫고 닫힌 URL 목록을 돌려준다.

        - 이미 떠 있으면 대기 없이 즉시 닫는다(정상 경로 추가 지연 0).
        - 아직 없으면 ``appear_cap_ms`` 까지 **실시간**으로 관찰한다(뜨는 즉시 조기 종료).
          ⚠ 실시간(:func:`asyncio.sleep`)인 이유: ``page.wait_for_timeout`` 은 워크플로우
          ``delay_scale``(예: 0.4)로 축소돼, 느린 세션에서 관찰창이 통째로 무너진다
          (공지 팝업 관찰창이 같은 이유로 붕괴했던 2026-07-26 선례).
        - 같은 호스트(ERP) 창은 **닫지 않는다** — 업무 창일 수 있다.
        """
        nap = sleep or asyncio.sleep
        want = _host(base)
        t0 = time.monotonic()
        while not self._pages and (time.monotonic() - t0) * 1_000 < appear_cap_ms:
            await nap(_APPEAR_INTERVAL_MS / 1_000)

        # 도착 즉시 예약된 닫기들을 먼저 정리한다(중복 close 는 무해 — 아래에서 is_closed 확인).
        if self._tasks:
            pending, self._tasks = self._tasks, []
            for task in pending:
                try:
                    await task
                except Exception:  # noqa: BLE001
                    logger.debug("팝업 즉시 닫기 태스크 실패(무시)", exc_info=True)

        closed: list[str] = list(self._closed)
        self._closed = []
        for page in list(self._pages):
            try:
                if page.is_closed():
                    continue
                url = await _settled_url(page, nap)
                if _host(url) and _host(url) == want:
                    logger.info("로그인 팝업 유지(ERP 호스트) — %s", url)
                    continue
                if is_approval_window(url):
                    logger.info("결제창은 보호합니다(닫지 않음) — %s", url)
                    continue
                if is_notice_window(url):
                    await _suppress_notice(page)
                await page.close()
                closed.append(url)
                logger.info("로그인 시 뜬 외부 창을 닫았습니다 — %s", url)
            except Exception:  # noqa: BLE001 — 이미 닫힘/유실은 무해.
                logger.debug("팝업 닫기 실패(무시)", exc_info=True)
        self._pages = [p for p in self._pages if not _safe_closed(p)]
        return closed


async def close_foreign_pages(page: Any, base: str) -> list[str]:
    """지금 열려 있는 창 중 ``base`` 와 **호스트가 다른** 것을 닫는다(1회성·대기 없음).

    감시자(:class:`PopupWatcher`)가 로그인 구간만 커버하는 데 비해, 이 함수는 **호출 시점의
    현재 상태**를 훑는다 — 팝업이 로그인 이후(사용자유형 전환·메뉴 진입 중)에 뜨는 경우를
    위한 just-in-time 방어다(공지 팝업의 JIT dismiss 와 같은 규율).

    ⚠⚠ **결재 순회 단계에서는 절대 호출 금지** ⚠⚠ — 결제창(EAP)이 바로 그 '다른 호스트 창'이라
    업무 창을 닫아버린다. 호출부는 로그인~메뉴 진입(결재 이전) 단계로 한정한다.
    """
    context = getattr(page, "context", None)
    if context is None:
        return []
    main = getattr(page, "_page", page)  # _ScaledPage 래퍼면 원본 Page 와 비교해야 한다.
    want = _host(base)
    closed: list[str] = []
    try:
        pages = list(context.pages)
    except Exception:  # noqa: BLE001 — 스텁 컨텍스트 방어.
        return []
    for other in pages:
        if other is main or other is page:
            continue
        try:
            if other.is_closed():
                continue
            url = other.url or ""
            if not _host(url) or _host(url) == want:
                continue
            if is_approval_window(url):
                logger.info("결제창은 보호합니다(닫지 않음) — %s", url)
                continue
            if is_notice_window(url):
                await _suppress_notice(other)  # 재출현 방지 후 닫는다.
            await other.close()
            closed.append(url)
            logger.info("외부 창을 닫았습니다(JIT) — %s", url)
        except Exception:  # noqa: BLE001 — 이미 닫힘/유실은 무해.
            logger.debug("JIT 팝업 닫기 실패(무시)", exc_info=True)
    return closed


def _host(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _safe_closed(page: Any) -> bool:
    try:
        return bool(page.is_closed())
    except Exception:  # noqa: BLE001
        return True


async def _settled_url(page: Any, nap: Any) -> str:
    """갓 열린 창의 목적지 URL 이 정해질 때까지 짧게 기다린다(about:blank → 실제 URL)."""
    t0 = time.monotonic()
    url = ""
    while (time.monotonic() - t0) * 1_000 < _URL_SETTLE_CAP_MS:
        url = page.url or ""
        if url and not url.startswith("about:"):
            return url
        await nap(_URL_SETTLE_INTERVAL_MS / 1_000)
    return url
