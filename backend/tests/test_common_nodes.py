"""공용 진입 노드(app.agents.common.nodes) 확인 계약 — 브라우저 없이.

고정하는 계약(§10 "값 선택은 선택 → 확인 → 다음"):
  1. 결의구분 — 세팅 JS 의 {ok:true} 를 성공으로 믿지 않고 **선택값을 다시 읽어** 확인한다.
     반영 성공 → 진행 / 되돌려짐(값 다름) → 하드 실패(error 로 단락) / 리더가 못 읽음 →
     warn 로그 + '반영 미확인' 문구로 진행(성공을 단정하지 않는다).
  2. doc_steps 스텝이 돌려준 ``warn``(확인 불가)은 노드가 반드시 run 로그로 노출한다.

페이크 페이지는 실물 시맨틱을 지킨다 — 세팅 JS 가 native select 의 값을 실제로 바꾸고,
SELECTED_TEXT_JS 는 그 **현재 값**을 읽는다. 되돌림 재현은 change 핸들러가 값을 원복하는
방식(reverts_to)으로 모사한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.common import doc_steps, nodes
from nbkit.omnisol import js_lib, selectors

pytestmark = pytest.mark.asyncio


class _GubunPage:
    """결의구분 native select + kendo 위젯 모사.

    reverts_to 를 주면 세팅 직후 change 핸들러가 값을 그 옵션으로 되돌린다 — 세팅 JS 는
    여전히 {ok:true} 를 돌려주므로(옵션을 찾아 넣기까지는 성공) 확인 리더만이 잡을 수 있다.
    unreadable=True 는 리더가 select 를 못 찾는 경우(위젯 구조 차이) = 확인 불가.
    """

    OPTIONS = {"카드": "3", "출장(국내·자차)": "7", "일반": "1"}

    def __init__(self, *, reverts_to: str | None = None, unreadable: bool = False) -> None:
        self.current = "일반"  # 화면 초기값.
        self.reverts_to = reverts_to
        self.unreadable = unreadable
        self.set_calls: list[str] = []
        self.waits: list[int] = []

    async def evaluate(self, js_src, arg=None):
        if isinstance(js_src, str) and js_src.startswith("(s) =>"):
            return arg == selectors.GUBUN_SELECT  # select 로드 폴링.
        if js_src is js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS:
            assert arg["selector"] == selectors.GUBUN_SELECT
            text = arg["text"]
            if text not in self.OPTIONS:
                return {"ok": False, "found": False}
            self.set_calls.append(text)
            self.current = self.reverts_to or text  # change 핸들러가 되돌리는 자리.
            return {"ok": True, "val": self.OPTIONS[text]}
        if js_src is js_lib.SELECTED_TEXT_JS:
            if self.unreadable:
                return {"ok": False, "reason": "no-select"}
            return {"ok": True, "text": self.current, "value": self.OPTIONS[self.current]}
        raise AssertionError(f"예상치 못한 evaluate: {str(js_src)[:60]}")

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


def _state(page) -> dict:
    return {"events": asyncio.Queue(), "page": page}


def _drain(events: asyncio.Queue) -> list[dict]:
    out: list[dict] = []
    while not events.empty():
        out.append(events.get_nowait())
    return out


def _logs(frames: list[dict], level: str | None = None) -> list[str]:
    return [f["log"] for f in frames if "log" in f and (level is None or f.get("level") == level)]


def _steps(frames: list[dict], key: str) -> list[str]:
    return [f["status"] for f in frames if f.get("step") == key]


# ══════════════════════════════════════════════════════════════════════════════
# 결의구분(set_gubun) — 세팅 후 선택값 재확인
# ══════════════════════════════════════════════════════════════════════════════
async def test_set_gubun_ok_when_selection_sticks():
    page = _GubunPage()
    st = _state(page)
    out = await nodes.make_set_gubun_node("카드")(st)
    assert out == {}
    frames = _drain(st["events"])
    assert _steps(frames, "set_gubun")[-1] == "done"
    assert "결의구분 = 카드" in _logs(frames)
    assert _logs(frames, "warn") == []
    assert page.set_calls == ["카드"]  # 확인 성공 시 재세팅 없음.


async def test_set_gubun_hard_fails_when_value_reverts():
    """세팅 JS 는 성공했는데 화면이 '일반'으로 되돌아간 경우 — 다른 문서 종류로 진행하면
    증빙·금액을 엉뚱한 화면에 채우게 되므로 error 로 단락한다."""
    page = _GubunPage(reverts_to="일반")
    st = _state(page)
    out = await nodes.make_set_gubun_node("카드")(st)
    assert "error" in out
    assert "결의구분" in out["error"] and "'일반'" in out["error"]
    frames = _drain(st["events"])
    assert _steps(frames, "set_gubun")[-1] == "failed"
    assert "결의구분 = 카드" not in _logs(frames)  # 성공 로그를 남기지 않는다.


async def test_set_gubun_warns_and_proceeds_when_reader_cannot_read():
    """리더가 select 를 못 읽으면 '값이 다름'이 아니라 확인 불가 — 진행하되 미확인을 남긴다."""
    page = _GubunPage(unreadable=True)
    st = _state(page)
    out = await nodes.make_set_gubun_node("카드")(st)
    assert out == {}
    frames = _drain(st["events"])
    assert _steps(frames, "set_gubun")[-1] == "done"
    warns = _logs(frames, "warn")
    assert warns and "결의구분" in warns[0] and "확인 불가" in warns[0]
    assert "결의구분 = 카드 (반영 미확인)" in _logs(frames)  # '완료'로 단정하지 않는다.


async def test_set_gubun_fails_when_option_missing():
    """옵션 자체가 없으면 세팅 단계에서 단락(기존 계약 보존)."""
    page = _GubunPage()
    st = _state(page)
    out = await nodes.make_set_gubun_node("없는구분")(st)
    assert "error" in out and "없는구분" in out["error"]
    assert _steps(_drain(st["events"]), "set_gubun")[-1] == "failed"


async def test_set_gubun_keeps_cascade_settle_wait_before_confirm():
    """확인은 화면 재구성(연쇄) 정착 **후**에 읽어야 되돌림을 잡는다 — 정착 대기 유지를 고정."""
    page = _GubunPage()
    await nodes.make_set_gubun_node("카드")(_state(page))
    assert 1_500 in page.waits


# ══════════════════════════════════════════════════════════════════════════════
# 증빙 노드 — doc_steps 의 '확인 불가' warn 을 run 로그로 노출
# ══════════════════════════════════════════════════════════════════════════════
class _InertPage:
    """증빙 노드는 모든 브라우저 조작을 doc_steps 로 위임하므로 evaluate 를 쓰지 않는다."""

    async def wait_for_timeout(self, ms):
        return None


async def test_open_evdn_node_surfaces_stale_popup_warn(monkeypatch):
    async def _open(page):
        return {
            "ok": True,
            "shown": {"ok": True, "idx": 1, "rows": 2},
            "warn": "증빙유형 팝업이 이미 열린 상태에서 시작 — 스테일 팝업일 수 있습니다.",
        }

    monkeypatch.setattr(doc_steps, "open_evdn_editor", _open)
    st = _state(_InertPage())
    out = await nodes.make_open_evdn_node()(st)
    assert out == {}
    frames = _drain(st["events"])
    warns = _logs(frames, "warn")
    assert warns and "증빙유형 팝업" in warns[0] and "스테일" in warns[0]
    assert _steps(frames, "open_evdn")[-1] == "done"


async def test_select_evdn_node_surfaces_popup_close_warn(monkeypatch):
    async def _select(page, code):
        return {
            "ok": True,
            "name": "법인카드",
            "code": code,
            "warn": "증빙유형 팝업 닫힘 확인 실패(기대 '닫힘' / 실제 True)",
        }

    monkeypatch.setattr(doc_steps, "select_evdn_code", _select)
    st = _state(_InertPage())
    out = await nodes.make_select_evdn_node("01")(st)
    assert out == {}
    warns = _logs(_drain(st["events"]), "warn")
    assert warns and "증빙유형 적용 후" in warns[0] and "닫힘" in warns[0]


async def test_evdn_nodes_stay_silent_when_fully_verified(monkeypatch):
    """확인이 끝난 정상 경로에서는 warn 로그가 없어야 한다(경고 인플레 방지)."""

    async def _open(page):
        return {"ok": True, "shown": {"ok": True, "idx": 0, "rows": 1}}

    async def _select(page, code):
        return {"ok": True, "name": "법인카드", "code": code}

    monkeypatch.setattr(doc_steps, "open_evdn_editor", _open)
    monkeypatch.setattr(doc_steps, "select_evdn_code", _select)
    st = _state(_InertPage())
    await nodes.make_open_evdn_node()(st)
    await nodes.make_select_evdn_node("01")(st)
    assert _logs(_drain(st["events"]), "warn") == []
