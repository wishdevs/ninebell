"""DB 성능·정합성 보강 검증 — 통계 SQL/파이썬 경로 동등성, 목록 defer, 원자 upsert, CHECK.

- compute_run_stats: PG 용 단일 SQL 집계(_stats_sql)와 SQLite 폴백(_stats_python)이 같은
  결과를 내는지(성공률·평균·최근실행 포함), TTL 캐시가 재집계를 막는지.
- store.list_runs: logs 대형 컬럼을 목록에서 로드하지 않되(defer), 실패 런만 별도 쿼리로
  logs 를 채워 failedStep 요약이 기존과 동일하게 나오는지. 선택적 session 주입 동작.
- card_learning: 행 단위 원자 upsert — 같은 키 재확정 시맨틱(count++·최신값) 유지 +
  한 행의 실패가 배치의 다른 행을 유실시키지 않는 오류 격리.
- 0033 제약(모델 __table_args__ 동일 반영): status/cost_type CHECK 위반 insert 거부.
  (기본 즐겨찾기 부분 유니크는 me_codes 라우터 flush 선행 후 0034 에서 도입 — test_me_codes 검증.)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from app.live import store
from app.models import AgentRun, OrgUnit, User
from app.services import agents as agents_service
from app.services import card_learning

_T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_stats_cache():
    """compute_run_stats 모듈 전역 TTL 캐시를 테스트 간 격리한다."""
    agents_service._stats_cache.clear()
    yield
    agents_service._stats_cache.clear()


async def _add_run(sm, *, rid, agent_id, user_id, status, started, dur_s, logs=None) -> None:
    async with sm() as s:
        s.add(
            AgentRun(
                id=rid,
                agent_id=agent_id,
                user_id=user_id,
                status=status,
                started_at=started,
                finished_at=(started + timedelta(seconds=dur_s)) if dur_s is not None else None,
                logs=logs if logs is not None else [],
            )
        )
        await s.commit()


# ── compute_run_stats: SQL 집계 경로 ↔ 파이썬 폴백 동등성 ─────────────────────
async def test_stats_sql_and_python_paths_agree(sm, make_user):
    """혼합 상태(성공·실패·진행중·취소)·2개 에이전트에서 두 경로가 같은 결과를 낸다."""
    uid = await make_user("stats-parity", "user")
    a, b = "wf-parity-a", "wf-parity-b"
    await _add_run(sm, rid="p1", agent_id=a, user_id=uid, status="succeeded", started=_T0, dur_s=60)
    await _add_run(sm, rid="p2", agent_id=a, user_id=uid, status="succeeded", started=_T0 + timedelta(hours=1), dur_s=120)
    await _add_run(sm, rid="p3", agent_id=a, user_id=uid, status="failed", started=_T0 + timedelta(hours=2), dur_s=30)
    await _add_run(sm, rid="p4", agent_id=a, user_id=uid, status="running", started=_T0 + timedelta(hours=3), dur_s=None)
    # 취소 런도 finished_at 이 있으면 평균 소요 표본에 든다(성공률에선 제외) — 경로 간 미묘한
    # 시맨틱 차가 나기 쉬운 지점이라 표본에 포함해 동등성을 강제한다.
    await _add_run(sm, rid="p5", agent_id=a, user_id=uid, status="cancelled", started=_T0 + timedelta(hours=4), dur_s=22)
    await _add_run(sm, rid="p6", agent_id=b, user_id=uid, status="failed", started=_T0, dur_s=10)

    async with sm() as s:
        sql = await agents_service._stats_sql(s, [a, b])
        py = await agents_service._stats_python(s, [a, b])
    assert sql == py
    # 계약 값 자체도 고정 검증(회귀 앵커): 성공률=성공/(성공+실패), 평균=완료 런 전체.
    assert py[a]["run_count"] == 5
    assert py[a]["success_rate"] == 66.7
    assert py[a]["avg_seconds"] == round((60 + 120 + 30 + 22) / 4)
    assert py[b] == {"run_count": 1, "success_rate": 0.0, "avg_seconds": 10, "last_run_at": py[b]["last_run_at"]}


async def test_stats_empty_ids_and_no_rows(sm, make_user):
    """빈 agent_ids 는 빈 dict, 이력 없는 에이전트는 키 자체가 없다(폴백 계약 동일)."""
    await make_user("stats-none", "user")
    assert await agents_service.compute_run_stats(None, []) == {}  # 빈 입력은 DB 접근 없음
    async with sm() as s:
        assert await agents_service._stats_sql(s, ["wf-none"]) == {}
        assert await agents_service._stats_python(s, ["wf-none"]) == {}


async def test_compute_run_stats_ttl_cache(sm, make_user):
    """같은 키 재호출은 TTL 내 캐시를 반환(새 런이 끼어도 재집계 안 함) — 캐시 비우면 갱신."""
    uid = await make_user("stats-cache", "user")
    wf = "wf-cache"
    await _add_run(sm, rid="c1", agent_id=wf, user_id=uid, status="succeeded", started=_T0, dur_s=60)
    async with sm() as s:
        first = await agents_service.compute_run_stats(s, [wf])
        assert first[wf]["run_count"] == 1
    await _add_run(sm, rid="c2", agent_id=wf, user_id=uid, status="succeeded", started=_T0 + timedelta(hours=1), dur_s=60)
    async with sm() as s:
        cached = await agents_service.compute_run_stats(s, [wf])
        assert cached[wf]["run_count"] == 1  # TTL 내 — 캐시 그대로
    agents_service._stats_cache.clear()
    async with sm() as s:
        fresh = await agents_service.compute_run_stats(s, [wf])
        assert fresh[wf]["run_count"] == 2  # 캐시 무효화 후 재집계


# ── store.list_runs: logs defer + 실패 런만 별도 로드 ─────────────────────────
async def test_list_runs_defers_logs_except_failed(sm, make_user):
    uid = await make_user("defer-logs", "user")
    ok_logs = [{"ts": i, "level": "info", "message": f"m{i}"} for i in range(50)]
    fail_logs = [
        {"ts": 1, "level": "info", "message": "▶ save (running)", "step": "save", "status": "running"},
        {"ts": 2, "level": "error", "message": "✗ save (failed)", "step": "save", "status": "failed"},
    ]
    await store.create_run(run_id="run-def-ok", agent_id="wf-def", user_id=uid)
    await store.set_terminal("run-def-ok", "succeeded", "ok", ok_logs)
    await store.create_run(run_id="run-def-fail", agent_id="wf-def", user_id=uid)
    await store.set_terminal("run-def-fail", "failed", "boom", fail_logs)

    runs = await store.list_runs(user_id=uid)
    by_id = {r.id: r for r in runs}
    ok, fail = by_id["run-def-ok"], by_id["run-def-fail"]
    # 성공 런: logs 는 로드되지 않았다(defer — 목록 요약에 불필요한 대형 컬럼).
    assert "logs" in sa_inspect(ok).unloaded
    # 실패 런: failedStep 계산용 logs 만 별도 쿼리로 채워져 있다(기존 계약 그대로).
    assert "logs" not in sa_inspect(fail).unloaded
    assert fail.logs == fail_logs
    # 요약에 쓰는 나머지 컬럼(result 포함)은 두 런 모두 로드돼 있다(shape 불변).
    for r in (ok, fail):
        loaded = set(sa_inspect(r).dict)
        assert {"id", "agent_id", "user_id", "status", "started_at", "finished_at", "result"} <= loaded


async def test_list_runs_summary_shape_via_api(client, make_user, auth_as):
    """defer 이후에도 목록 요약 shape·failedStep 이 기존과 동일하다(라우터 경유)."""
    uid = await make_user("defer-api", "user")
    await store.create_run(run_id="run-api-ok", agent_id="wf-api", user_id=uid)
    await store.set_terminal("run-api-ok", "succeeded", "완료", [{"ts": 1, "level": "ok", "message": "✓ echo (done)"}])
    await store.create_run(run_id="run-api-fail", agent_id="wf-api", user_id=uid)
    await store.set_terminal(
        "run-api-fail", "failed", "실패",
        [{"ts": 1, "level": "error", "message": "✗ chat_form (failed)"}],
    )
    auth_as(uid)
    body = (await client.get("/runs")).json()
    by_id = {x["id"]: x for x in body["runs"]}
    ok, fail = by_id["run-api-ok"], by_id["run-api-fail"]
    expected_keys = {
        "id", "agentId", "userId", "userDisplayName", "status",
        "startedAt", "finishedAt", "resultSummary", "failedStep",
    }
    assert set(ok) == expected_keys and set(fail) == expected_keys
    assert ok["failedStep"] is None and ok["resultSummary"] == "완료"
    assert fail["failedStep"] == "chat_form"


async def test_store_read_helpers_accept_injected_session(sm, make_user):
    """조회 헬퍼의 선택적 session 파라미터 — 주입 세션으로 동작(자체 세션 기본값 불변)."""
    uid = await make_user("inject-session", "user")
    await store.create_run(run_id="run-inj", agent_id="wf-inj", user_id=uid)
    async with sm() as s:
        runs = await store.list_runs(user_id=uid, session=s)
        assert [r.id for r in runs] == ["run-inj"]
        assert await store.count_runs(user_id=uid, session=s) == 1
        got = await store.get_run("run-inj", session=s)
        assert got is not None and got.id == "run-inj"


# ── card_learning: 원자 upsert + 행 단위 오류 격리 ───────────────────────────
async def test_record_selections_row_error_does_not_lose_batch(sm, make_user):
    """직렬화 불가 행(오류) 뒤의 정상 행도 저장된다 — 광역 롤백으로 배치 전체가 유실되던
    회귀 방지. 반환값은 성공 행 수만 센다."""
    uid = await make_user("learn-isolate", "user")
    owner = str(uid)
    n = await card_learning.record_selections(
        owner,
        [
            # JSON 직렬화 불가 budget → 이 행만 실패해야 한다.
            {"merchant": "배드상점", "budget": {"x": object()}, "project": None, "note": "bad"},
            {"merchant": "굿상점", "budget": {"code": "B1", "name": "팀"}, "project": None, "note": "good"},
        ],
    )
    assert n == 1
    hits = await card_learning.retrieve_for_merchants(owner, ["굿상점", "배드상점"])
    assert card_learning.norm_merchant("굿상점") in hits
    assert card_learning.norm_merchant("배드상점") not in hits


async def test_record_selections_upsert_semantics_two_calls(sm, make_user):
    """같은 키 2회 upsert: count++ + 최신값 갱신, 빈 새값(note 없음)은 기존값 보존."""
    uid = await make_user("learn-upsert", "user")
    owner = str(uid)
    await card_learning.record_selections(
        owner, [{"merchant": "업서트상점", "budget": {"code": "B1", "name": "팀"}, "project": None, "note": "첫적요"}]
    )
    await card_learning.record_selections(
        owner, [{"merchant": "업서트상점", "budget": {"code": "B2", "name": "새팀"}, "project": None, "note": ""}]
    )
    hits = await card_learning.retrieve_for_merchants(owner, ["업서트상점"])
    row = hits[card_learning.norm_merchant("업서트상점")]
    assert row["count"] == 2
    assert row["budget"]["code"] == "B2"  # 최신 스냅샷
    assert row["note"] == "첫적요"  # 빈 새값은 기존 보존


async def test_record_account_notes_upsert_semantics_two_calls(sm, make_user):
    """(가맹점 × 계정) 같은 키 2회 upsert: count++ + 최신 적요 갱신."""
    uid = await make_user("note-upsert", "user")
    owner = str(uid)
    await card_learning.record_account_notes(
        owner, [{"merchant": "계정상점", "acct_code": "81103", "acct_name": "복리후생비", "note": "첫적요"}]
    )
    n = await card_learning.record_account_notes(
        owner, [{"merchant": "계정상점", "acct_code": "81103", "acct_name": "복리후생비", "note": "둘째적요"}]
    )
    assert n == 1
    from sqlalchemy import select

    from app.models import CardLearnedNote

    async with sm() as s:
        row = (
            await s.execute(
                select(CardLearnedNote).where(
                    CardLearnedNote.user_id == uid, CardLearnedNote.acct_code == "81103"
                )
            )
        ).scalar_one()
    assert row.count == 2 and row.note == "둘째적요"


# ── 0033 제약(모델 __table_args__ 반영분 — sqlite create_all 경로) ────────────
async def test_agent_runs_status_check_rejects_unknown(sm, make_user):
    uid = await make_user("ck-run", "user")
    with pytest.raises(IntegrityError):
        await _add_run(sm, rid="ck-bad", agent_id="wf-ck", user_id=uid, status="bogus", started=_T0, dur_s=None)
    # 실기록 값 전수(cancel 경로 포함)는 허용된다.
    for i, st in enumerate(("running", "waiting", "succeeded", "failed", "cancelled")):
        await _add_run(sm, rid=f"ck-ok-{i}", agent_id="wf-ck", user_id=uid, status=st, started=_T0, dur_s=None)


async def test_users_status_check_rejects_unknown(sm):
    async with sm() as s:
        s.add(User(omnisol_userid="ck-user-bad", status="bogus"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_org_units_cost_type_check(sm):
    async with sm() as s:
        s.add(OrgUnit(id="ck-org-null", label="컨테이너", cost_type=None))  # NULL 허용
        await s.commit()
    async with sm() as s:
        s.add(OrgUnit(id="ck-org-bad", label="이상팀", cost_type="기타"))
        with pytest.raises(IntegrityError):
            await s.commit()


