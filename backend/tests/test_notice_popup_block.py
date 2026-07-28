"""공지 팝업 **원천 차단**(window.open 가로채기) — 설치 경로 + 차단 판정 규칙.

핵심 계약:
  1) 공지 URL(art_seq_no= / callComp=UFAP…)로 window.open 하면 **창이 열리지 않고** 스텁이 온다.
  2) 결제창(EAP: approkey/docID/callComp=UBAP…)은 **반드시 통과** — 막으면 결재 자체가 불가능.
  3) 판정 불가(빈 url·예외)는 통과(fail-open) — 못 막은 공지는 감시자 폴백이 닫는다.

JS 자체는 브라우저 없이 못 돌리므로, 스크립트의 판정부와 동치인 파이썬 포트로 규칙을 고정하고
(마커 목록은 모듈 단일 소스를 그대로 읽는다), 설치 경로는 스텁 컨텍스트로 검증한다.
"""

from __future__ import annotations

import pytest

from nbkit.browser import popups

# (asyncio_mode = auto — async 테스트에 별도 마크 불필요.)


# ── 설치 경로 ─────────────────────────────────────────────────────────────────
class _Ctx:
    def __init__(self, fail: bool = False) -> None:
        self.scripts: list[str] = []
        self._fail = fail

    async def add_init_script(self, src: str) -> None:
        if self._fail:
            raise RuntimeError("컨텍스트가 이미 닫힘")
        self.scripts.append(src)


async def test_block_installs_init_script():
    ctx = _Ctx()
    assert await popups.block_notice_popups(ctx) is True
    assert len(ctx.scripts) == 1
    assert "window.open" in ctx.scripts[0]


async def test_block_install_failure_is_swallowed():
    """설치 실패해도 런을 깨지 않는다 — 감시자(PopupWatcher) 폴백이 남는다."""
    assert await popups.block_notice_popups(_Ctx(fail=True)) is False


# ── 차단 판정 규칙(스크립트 판정부와 동치) ────────────────────────────────────
def _blocked(url) -> bool:
    """NOTICE_OPEN_BLOCK_JS 의 판정부와 같은 규칙 — 공지 마커가 있으면 차단."""
    try:
        u = ("" if url is None else str(url)).lower()
    except Exception:  # noqa: BLE001 — JS 의 try/catch 와 동일하게 통과.
        return False
    return any(m in u for m in popups._NOTICE_MARKERS)


NOTICE_URL = (
    "https://uc.ninebell.co.kr/#/popup?art_seq_no=1573&boardNo=14&catType=N"
    "&portlet=true&callComp=UFAP013&popupUUID=cd760060-898e-11f1-907a-b99b18e205ec"
)
APPROVAL_URL = (
    "https://uc.ninebell.co.kr/#/popup?callComp=UBAP001&docID=2026072700123"
    "&approkey=abc123&MicroModuleCode=eap"
)


def test_notice_url_is_blocked():
    assert _blocked(NOTICE_URL) is True


def test_approval_url_passes_through():
    """⚠ 회귀 금지 — 결제창을 막으면 결재 순회가 통째로 불가능해진다."""
    assert _blocked(APPROVAL_URL) is False
    # 차단 스크립트가 결제 마커를 아예 갖고 있지 않은지도 함께 고정한다.
    for marker in popups._APPROVAL_MARKERS:
        assert marker not in popups.NOTICE_OPEN_BLOCK_JS.lower()


@pytest.mark.parametrize(
    "url",
    ["", None, "https://erp.ninebell.co.kr/", "about:blank"],
)
def test_unknown_urls_pass_through(url):
    """판정 불가·평범한 URL 은 통과(fail-open) — 못 막은 공지는 감시자가 닫는다."""
    assert _blocked(url) is False


def test_block_script_is_idempotent_and_fail_open():
    """중복 설치 가드와 native 폴백이 스크립트에 들어 있는지 고정."""
    src = popups.NOTICE_OPEN_BLOCK_JS
    assert "__nbkitNoticeBlocked" in src  # 이중 래핑 방지
    assert "native.apply(window, arguments)" in src  # 비공지는 원래 open 으로
    # 스텁 반환(호출부가 focus()/close() 를 만져도 TypeError 로 ERP 를 깨뜨리지 않는다).
    for member in ("close:", "focus:", "postMessage:"):
        assert member in src
