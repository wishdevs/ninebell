"""GET/PUT /dev/llm-provider — 로컬 dev 런타임 LLM 프로바이더 전환 계약 검증.

- 게이트(LLM_PROVIDER_TOGGLE) off → GET/PUT 모두 404(기능 자체가 없는 것처럼)
- on → GET shape {"active","source","options"}(라벨은 settings 모델명 동적)
- PUT 전환 → source="override" + read-site 실반영(effective_llm_provider·디스패처
  _is_etribe 경유 4경로·assistant build_llm 의 EtribeProvider 선택)
- 미지 값 → 422, None 리셋 → source="env"(env 기본으로 복귀)
- 오버라이드는 프로세스 전역이라 fixture teardown 에서 반드시 해제(타 테스트 오염 금지)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.agents.common.llm as LLM
from app.config import get_settings
from app.core.llm_runtime import (
    effective_llm_provider,
    llm_provider_source,
    set_llm_provider_override,
)
from app.llm.etribe import EtribeProvider
from app.llm.gemini import GeminiProvider
from app.routers.assistant import build_llm


@pytest.fixture(autouse=True)
def _reset_override():
    """오버라이드 누수 방지 — 전/후 모두 해제(프로세스 전역이라 타 테스트 오염 금지)."""
    set_llm_provider_override(None)
    yield
    set_llm_provider_override(None)


@pytest.fixture
def gate_on(monkeypatch):
    """lru_cache 된 settings 인스턴스의 게이트를 켠다(monkeypatch 가 원복)."""
    monkeypatch.setattr(get_settings(), "llm_provider_toggle", True)


@pytest.fixture
def gate_off(monkeypatch):
    """게이트를 명시적으로 끈다 — 로컬 .env 의 LLM_PROVIDER_TOGGLE 값과 무관하게 결정적."""
    monkeypatch.setattr(get_settings(), "llm_provider_toggle", False)


async def _login(make_user, auth_as, userid: str = "dev1"):
    uid = await make_user(userid, "user")
    auth_as(uid)


def _fake_request():
    """build_llm 이 요구하는 최소 Request 대역 — app.state.http 만 있으면 된다."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http=object())))


# ── 게이트 off → 404 ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_gate_off_returns_404_for_get_and_put(client, make_user, auth_as, gate_off):
    await _login(make_user, auth_as)
    assert (await client.get("/dev/llm-provider")).status_code == 404
    r = await client.put("/dev/llm-provider", json={"provider": "etribe"})
    assert r.status_code == 404
    # 404 로 거부됐으니 오버라이드도 설정되지 않아야 한다.
    assert llm_provider_source() == "env"


# ── 게이트 on → GET shape ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_gate_on_get_returns_contract_shape(client, make_user, auth_as, gate_on):
    await _login(make_user, auth_as)
    r = await client.get("/dev/llm-provider")
    assert r.status_code == 200
    settings = get_settings()
    assert r.json() == {
        "active": settings.llm_provider,  # 오버라이드 없음 → env 값 그대로.
        "source": "env",
        "options": [
            {"id": "gemini", "label": f"Gemini ({settings.gemini_model})"},
            {"id": "etribe", "label": "Etribe-LLM (사내)"},
        ],
    }


# ── PUT 전환 → read-site 실반영 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_put_switch_reflects_in_all_llm_read_sites(client, make_user, auth_as, gate_on):
    await _login(make_user, auth_as)
    settings = get_settings()

    r = await client.put("/dev/llm-provider", json={"provider": "etribe"})
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "etribe"
    assert body["source"] == "override"
    assert body["options"] == [
        {"id": "gemini", "label": f"Gemini ({settings.gemini_model})"},
        {"id": "etribe", "label": "Etribe-LLM (사내)"},
    ]

    # 1) 단일 판정 지점 자체.
    assert effective_llm_provider(settings) == "etribe"
    # 2) 에이전트 디스패처(_is_etribe 경유 — llm_ready/llm_model_name/chat_decide/generate_text
    #    4경로 공통 분기). 더미 settings 에 llm_provider 가 있어도 오버라이드가 우선한다.
    dummy = SimpleNamespace(llm_provider="gemini", gemini_model="gm", etribe_model="Etribe-LLM")
    assert LLM._is_etribe(dummy) is True
    assert LLM.llm_model_name(dummy) == "Etribe-LLM"
    assert LLM.llm_ready(SimpleNamespace()) is True  # etribe 는 무인증 — 키 없이도 ready.
    # 3) /assistant 스트림의 빌더 분기 — EtribeProvider 선택.
    assert isinstance(build_llm(_fake_request(), settings), EtribeProvider)

    # gemini 로 되돌려도 source 는 여전히 override(명시 선택 상태).
    r = await client.put("/dev/llm-provider", json={"provider": "gemini"})
    assert r.status_code == 200
    assert r.json()["active"] == "gemini"
    assert r.json()["source"] == "override"
    assert LLM._is_etribe(dummy) is False


@pytest.mark.asyncio
async def test_put_gemini_override_builds_gemini_provider(client, make_user, auth_as, gate_on, monkeypatch):
    """env 가 etribe 여도 오버라이드 gemini 가 이긴다 — 빌더가 GeminiProvider 선택."""
    await _login(make_user, auth_as)
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "etribe")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")  # gemini 빌더는 키 필요.

    r = await client.put("/dev/llm-provider", json={"provider": "gemini"})
    assert r.status_code == 200
    assert r.json()["active"] == "gemini"
    assert r.json()["source"] == "override"
    assert isinstance(build_llm(_fake_request(), settings), GeminiProvider)


# ── 미지 값 → 422 ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_put_unknown_provider_returns_422(client, make_user, auth_as, gate_on):
    await _login(make_user, auth_as)
    r = await client.put("/dev/llm-provider", json={"provider": "gpt4"})
    assert r.status_code == 422
    assert llm_provider_source() == "env"  # 거부된 값은 상태를 바꾸지 않는다.


def test_set_override_rejects_unknown_value():
    """라우터 Literal 뒤의 2차 방어 — 직접 호출도 미지 값이면 즉시 실패."""
    with pytest.raises(ValueError):
        set_llm_provider_override("gpt4")
    assert llm_provider_source() == "env"


# ── None 리셋 → env 복귀 ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reset_none_returns_to_env_source(client, make_user, auth_as, gate_on):
    await _login(make_user, auth_as)
    settings = get_settings()

    await client.put("/dev/llm-provider", json={"provider": "etribe"})
    assert llm_provider_source() == "override"

    set_llm_provider_override(None)  # 해제(프로세스 재시작과 동치) → env 기본으로 복귀.
    r = await client.get("/dev/llm-provider")
    assert r.status_code == 200
    assert r.json()["source"] == "env"
    assert r.json()["active"] == settings.llm_provider
    assert effective_llm_provider(settings) == settings.llm_provider
