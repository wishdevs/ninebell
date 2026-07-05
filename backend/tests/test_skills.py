"""스킬 카탈로그(app/services/skills.py) + GET /skills 역인덱스 테스트.

- 픽스처 스텝의 skill 은 전부 카탈로그 KEY 여야 한다(자유 문자열 회귀 방지).
- card-chat 픽스처 스텝 key 는 실행 그래프(card-collect) 노드명과 1:1 이어야 한다.
- GET /skills 는 카탈로그 전체 + 스킬별 사용 에이전트 역인덱스를 내려준다.
- GET /agents/{id} 스텝은 skill 라벨(기존 shape) + skillKey + intervention 을 내려준다.
"""

from __future__ import annotations

from app.services.agent_fixtures import AGENT_FIXTURES
from app.services.skills import SKILLS, skill_label

# 실행 그래프(app/agents/card_collect/graph.py)의 노드명 — 다른 트랙이 리팩터링 중이라
# import 하지 않고 알려진 16개 노드를 하드코딩해 비교한다(그래프가 바뀌면 여기도 갱신).
CARD_COLLECT_NODES = [
    "login",
    "user_type",
    "menu_nav",
    "set_gubun",
    "add_row",
    "set_acct_date",
    "open_evdn",
    "select_evdn",
    "select_all_cards",
    "set_period",
    "query",
    "collect_rows",
    "apply_doc",
    "switch_evdn",
    "apply_pass2",
    "save_final",
]


# ── 카탈로그 정합성 ───────────────────────────────────────────────────────────
def test_every_fixture_step_skill_is_in_catalog():
    for fx in AGENT_FIXTURES:
        for step in fx["steps"]:
            skill = step.get("skill")
            assert skill in SKILLS, f"{fx['id']}.{step['key']} 스킬 '{skill}' 이 카탈로그에 없음"


def test_card_collect_fixture_step_keys_match_graph_nodes():
    fx = next(f for f in AGENT_FIXTURES if f["id"] == "card-chat")
    assert [s["key"] for s in fx["steps"]] == CARD_COLLECT_NODES


def test_skill_label_falls_back_to_raw_key():
    assert skill_label("codepicker") == "코드피커"
    assert skill_label("과거 자유 문자열") == "과거 자유 문자열"


# ── GET /skills ───────────────────────────────────────────────────────────────
async def test_list_skills_returns_catalog_with_reverse_index(client, make_user, auth_as):
    uid = await make_user("skills-user", "user")
    auth_as(uid)

    resp = await client.get("/skills")
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_key = {i["key"]: i for i in items}
    # 카탈로그 전체가 그대로 내려온다(사용 에이전트 없는 스킬 포함).
    assert set(by_key) == set(SKILLS)
    for item in items:
        assert item["label"] == SKILLS[item["key"]].label
        assert item["layer"] in ("omnisol", "common", "llm")
        assert item["description"]
    # 역인덱스: 시드된 card-chat 이 codepicker 스킬 사용자로 잡혀야 한다.
    assert {"id": "card-chat", "name": "결의서 입력 - 카드"} in by_key["codepicker"]["agents"]
    # 코드피커는 여러 스텝에서 쓰이지만 distinct 로 에이전트는 1번만 나온다.
    assert [a["id"] for a in by_key["codepicker"]["agents"]].count("card-chat") == 1


async def test_list_skills_requires_auth(client):
    resp = await client.get("/skills")
    assert resp.status_code == 401


# ── GET /agents/{id} 스텝 shape ──────────────────────────────────────────────
async def test_agent_steps_expose_skill_label_key_and_intervention(client, make_user, auth_as):
    uid = await make_user("skills-admin", "super_admin")
    auth_as(uid)

    resp = await client.get("/agents/card-chat")
    assert resp.status_code == 200
    steps = {s["id"]: s for s in resp.json()["steps"]}
    # skill 은 기존대로 한글 라벨, skillKey 는 카탈로그 키.
    assert steps["open_evdn"]["skill"] == "코드피커"
    assert steps["open_evdn"]["skillKey"] == "codepicker"
    # HITL 스텝만 intervention=True.
    assert steps["collect_rows"]["intervention"] is True
    assert all(not s["intervention"] for k, s in steps.items() if k != "collect_rows")
