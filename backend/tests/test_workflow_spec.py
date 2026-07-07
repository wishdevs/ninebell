"""WorkflowSpec 레지스트리 — 에이전트별 실행 노브 단일소스 회귀 테스트.

- register_workflow 2-인자 하위호환(기본값: 브라우저 필요, 옴니솔 사이트).
- card-collect 는 delay_scale=0.15 로 등록(라이브 검증된 대기 배율).
- needs_browser=False 면 러너가 browser_factory 를 아예 부르지 않는다(순수 API/LLM 경로).
"""

from __future__ import annotations

import pytest

import app.agents  # noqa: F401 — 워크플로우 등록 트리거
from app.live.registry import WorkflowSpec, get_spec, get_workflow, register_workflow
from app.live.runner import run_workflow

pytestmark = pytest.mark.asyncio


def test_register_two_arg_backcompat_defaults():
    register_workflow("spec-test", lambda: object())
    spec = get_spec("spec-test")
    assert isinstance(spec, WorkflowSpec)
    assert spec.needs_browser is True
    assert spec.delay_scale is None
    assert spec.site == "omnisol" and spec.login_form_selector == "#userid"
    assert get_workflow("spec-test") is spec.factory


def test_card_collect_spec_has_delay_scale():
    spec = get_spec("card-collect")
    assert spec is not None and spec.delay_scale == 0.15
    # demo-echo 는 기본값 그대로.
    assert get_spec("demo-echo").delay_scale is None


def test_trip_domestic_spec_registered_with_defaults():
    # 라이브 실측(Phase 6) 전이라 delay_scale 미지정(None=1.0), 브라우저 필요.
    spec = get_spec("trip-domestic")
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale is None
    assert spec.site == "omnisol"


async def test_runner_skips_browser_when_factory_none():
    """browser_factory=None(needs_browser=False) → 브라우저 미런치, page/browser=None 로 실행."""
    seen: dict = {}

    class _Graph:
        async def ainvoke(self, state):
            seen.update(state)
            return {"result": "done-no-browser"}

    frames = []
    async for ev in run_workflow(_Graph(), None, {"userid": "u"}, {}, screencast=False):
        frames.append(ev)
    assert seen["page"] is None and seen["browser"] is None
    assert seen["userid"] == "u" and "events" in seen
    assert frames[-1] == {"result": "done-no-browser"}
