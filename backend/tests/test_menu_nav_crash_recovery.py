"""menu_nav 노드 — 크래시 복구로 교체된 page 의 state 전파 + 진입 노드 관측성.

라이브 실증(2026-07-31, gyeongjo-grant) 후속: 노드가 예외를 {"error": ...} 로 삼켜
서버 로그에 트레이스백이 전혀 없었다. 고정하는 계약:
  - navigate_schema 가 다른 page 를 돌려주면(크래시 복구) 노드가 {"page": 새 page} 로
    반환해 후속 노드에 전파되고, 진입 후 정리(close_foreign_pages)도 새 page 로 한다.
  - page 미교체(또는 스텁의 None 반환)면 기존과 동일하게 {} — 하위호환.
  - login/user_type/menu_nav 의 예외 삼킴 지점은 logger.exception 으로 서버 로그에
    트레이스백을 남기되, 사용자 노출 error 메시지는 불변.
"""

from __future__ import annotations

import asyncio
import logging
from typing import get_type_hints

import pytest

from app.agents.common import nodes as common_nodes
from app.agents.common.state import BaseAgentState

pytestmark = pytest.mark.asyncio

_LOGGER_NAME = "app.agents.common.nodes"


def _state(page) -> dict:
    return {"events": asyncio.Queue(), "page": page}


# ── page 교체 전파 ───────────────────────────────────────────────────────────
async def test_menu_nav_propagates_replaced_page(monkeypatch):
    old, new = object(), object()
    seen: dict = {}

    async def _navigate(pg, schema, base, *, emit=None):
        return new  # 크래시 복구로 교체된 페이지.

    async def _close(pg, base):
        seen["cleanup_page"] = pg
        return []

    monkeypatch.setattr(common_nodes, "navigate_schema", _navigate)
    monkeypatch.setattr(common_nodes, "close_foreign_pages", _close)
    out = await common_nodes.make_menu_nav_node()(_state(old))
    assert out == {"page": new}  # 후속 노드가 state["page"] 로 새 페이지를 받는다.
    assert seen["cleanup_page"] is new  # 진입 후 정리도 새 페이지 기준.


async def test_menu_nav_returns_empty_when_page_unchanged(monkeypatch):
    page = object()

    async def _navigate(pg, schema, base, *, emit=None):
        return pg  # 정상 경로 — 원본 그대로.

    async def _close(pg, base):
        return []

    monkeypatch.setattr(common_nodes, "navigate_schema", _navigate)
    monkeypatch.setattr(common_nodes, "close_foreign_pages", _close)
    out = await common_nodes.make_menu_nav_node()(_state(page))
    assert out == {}  # 기존 계약 불변.


async def test_menu_nav_tolerates_none_return(monkeypatch):
    """구식/테스트 스텁이 None 을 돌려줘도 기존 page 를 유지한다(하위호환)."""
    page = object()
    seen: dict = {}

    async def _navigate(pg, schema, base, *, emit=None):
        return None

    async def _close(pg, base):
        seen["cleanup_page"] = pg
        return []

    monkeypatch.setattr(common_nodes, "navigate_schema", _navigate)
    monkeypatch.setattr(common_nodes, "close_foreign_pages", _close)
    out = await common_nodes.make_menu_nav_node()(_state(page))
    assert out == {}
    assert seen["cleanup_page"] is page


async def test_page_key_declared_in_base_state():
    """LangGraph silent-drop 가드 — page 미선언이면 교체 전파가 조용히 유실된다."""
    assert "page" in get_type_hints(BaseAgentState)


# ── 관측성(logger.exception) ─────────────────────────────────────────────────
async def test_menu_nav_logs_traceback_and_keeps_user_message(monkeypatch, caplog):
    async def _boom(pg, schema, base, *, emit=None):
        raise RuntimeError("Page.goto: Page crashed")

    monkeypatch.setattr(common_nodes, "navigate_schema", _boom)
    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
        out = await common_nodes.make_menu_nav_node()(_state(object()))
    assert out == {"error": "메뉴 진입 실패: Page.goto: Page crashed"}  # 사용자 메시지 불변.
    recs = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert recs and recs[0].exc_info  # 트레이스백이 서버 로그에 남는다.


async def test_login_node_logs_traceback(monkeypatch, caplog):
    async def _boom(pg, userid, password, base, *, emit=None):
        raise RuntimeError("bang")

    monkeypatch.setattr(common_nodes, "ensure_logged_in", _boom)
    st = _state(object())
    st.update({"userid": "u", "password": "p"})
    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
        out = await common_nodes.make_login_node()(st)
    assert out == {"error": "로그인 실패: bang"}
    recs = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert recs and recs[0].exc_info


async def test_user_type_node_logs_traceback(monkeypatch, caplog):
    async def _close(pg, base):
        return []

    async def _boom(pg, target, *, emit=None):
        raise RuntimeError("bang")

    monkeypatch.setattr(common_nodes, "close_foreign_pages", _close)
    monkeypatch.setattr(common_nodes, "ensure_user_type", _boom)
    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
        out = await common_nodes.make_user_type_node("회계")(_state(object()))
    assert out == {"error": "사용자유형 전환 실패: bang"}
    recs = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert recs and recs[0].exc_info
