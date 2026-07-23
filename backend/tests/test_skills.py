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

# 노드 내부(intra-node) 스텝 — 그래프 노드는 아니지만 노드 안에서 emit_step 으로 별도 방출되는
# 가시화 스텝. key = 스텝, value = (방출 노드, 'before'|'after'). 둘 다 collect_rows 안의
# 정체 구간 분리(2026-07-06): prefill = 그리드 전 AI 추천 콜, fill_rows = 제출 후 그리드 실입력.
CARD_COLLECT_INTRA_NODE_STEPS: dict[str, tuple[str, str]] = {
    "prefill": ("collect_rows", "before"),
    "fill_rows": ("collect_rows", "after"),
}

# 픽스처 스텝 기대 순서 = 그래프 노드 순서에 intra-node 스텝을 소속 노드 앞/뒤에 삽입한 것.
CARD_COLLECT_EXPECTED_STEPS = [
    key
    for node in CARD_COLLECT_NODES
    for key in (
        [k for k, (owner, pos) in CARD_COLLECT_INTRA_NODE_STEPS.items() if owner == node and pos == "before"]
        + [node]
        + [k for k, (owner, pos) in CARD_COLLECT_INTRA_NODE_STEPS.items() if owner == node and pos == "after"]
    )
]


# ── 카탈로그 정합성 ───────────────────────────────────────────────────────────
def test_every_fixture_step_skill_is_in_catalog():
    for fx in AGENT_FIXTURES:
        for step in fx["steps"]:
            skill = step.get("skill")
            assert skill in SKILLS, f"{fx['id']}.{step['key']} 스킬 '{skill}' 이 카탈로그에 없음"


def test_card_collect_fixture_step_keys_match_graph_nodes():
    fx = next(f for f in AGENT_FIXTURES if f["id"] == "card-chat")
    assert [s["key"] for s in fx["steps"]] == CARD_COLLECT_EXPECTED_STEPS


def test_skill_label_falls_back_to_raw_key():
    assert skill_label("codepicker") == "코드피커"
    assert skill_label("과거 자유 문자열") == "과거 자유 문자열"


def test_every_fixture_step_has_phase():
    """모든 스텝에 phase(큰 단계 카테고리)가 있고, 순서대로 연속 구간을 이룬다."""
    for fx in AGENT_FIXTURES:
        phases = [s.get("phase") for s in fx["steps"]]
        assert all(phases), f"{fx['id']} 에 phase 없는 스텝이 있음"
        # 같은 phase 는 연속 구간이어야 아코디언 그룹핑이 순서를 보존한다.
        seen: list[str] = []
        for p in phases:
            if not seen or seen[-1] != p:
                assert p not in seen, f"{fx['id']} phase '{p}' 가 비연속으로 재등장"
                seen.append(p)


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
    assert {"id": "card-chat", "name": "법인카드"} in by_key["codepicker"]["agents"]
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
    # phase(큰 단계)가 직렬화에 노출된다 — Phase 아코디언 그룹핑 소스.
    assert steps["login"]["phase"] == "접속"
    assert steps["collect_rows"]["phase"] == "건별 입력"
    assert steps["save_final"]["phase"] == "저장"
    assert all(s.get("phase") for s in steps.values())


async def test_seed_replaces_stale_step_set(sm):
    """스텝 키 셋이 픽스처와 다르면(옛 flow_graph 기반 잔존) 시드가 전체 교체한다.

    회귀(2026-07-05): 키 매칭 보강만으로는 낡은 스텝(access/kind/…)이 영구 잔존해
    워크플로우 탭이 '옛 플랜 + raw 영어 라이브 스텝' 이중 표시됐다.
    """
    from sqlalchemy import select as sa_select

    from app.models import AgentStep
    from app.services.seed import seed_agents

    async with sm() as s:
        # 낡은 스텝 셋 시뮬레이션: card-chat 스텝을 옛 키로 통째로 바꿔치기.
        rows = (
            await s.execute(sa_select(AgentStep).where(AgentStep.agent_id == "card-chat"))
        ).scalars().all()
        for r in rows:
            await s.delete(r)
        s.add(AgentStep(agent_id="card-chat", key="access", label="결의서 입력 접속",
                        skill="로그인·메뉴 이동", status="done", position=0))
        s.add(AgentStep(agent_id="card-chat", key="kind", label="결의구분 = 카드",
                        skill="필드 입력", status="done", position=1))
        await s.commit()

    async with sm() as s:
        await seed_agents(s)
        await s.commit()

    async with sm() as s:
        keys = [
            r.key
            for r in (
                await s.execute(
                    sa_select(AgentStep)
                    .where(AgentStep.agent_id == "card-chat")
                    .order_by(AgentStep.position)
                )
            ).scalars()
        ]
    assert keys[0] == "login" and "access" not in keys  # 낡은 셋 → 픽스처(실행 그래프)로 교체
    assert "collect_rows" in keys and len(keys) == len(CARD_COLLECT_EXPECTED_STEPS)
