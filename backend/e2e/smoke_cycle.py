"""E2E 스모크 1사이클 — 모니터→실행→모니터확인→완료판정→삭제를 한 번에 + 분석 리포트.

사용자 루프(백엔드 모니터 켜기 → 테스트 실행 → 모니터 확인 → 완료 확인 → 삭제 → 소스 수정 반복)
의 1~5단계를 한 명령으로 돌리고, 6단계(개선/지연 축소)를 쉽게 하도록 **단계별 ms·경고·에러**를
구조화해 출력한다. e2e_smoke 의 phase1()/phase2() 를 그대로 호출한다.

    cd backend && .venv/bin/python e2e/smoke_cycle.py [--no-delete]

'백엔드 모니터링' = 실행이 만든 agent_runs 행의 logs(단계 running/done ts, warn/error)를 읽는
것이다(러너가 종료 시 DB 에 저장). 별도 프로세스 없이 실행 전후 최신 런을 비교해 새 런을 잡는다.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from e2e.e2e_smoke import phase1, phase2  # noqa: E402

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)


def _psql(sql: str) -> str:
    """dashboard-pg 컨테이너로 psql 단발 실행(-tA). 실패 시 빈 문자열."""
    try:
        out = subprocess.run(
            ["docker", "exec", "dashboard-pg", "psql", "-U", "dashboard", "-d", "dashboard", "-tA", "-c", sql],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[MON] psql 실패: {exc}", flush=True)
        return ""


def _latest_run_id() -> str:
    return _psql("SELECT id FROM agent_runs ORDER BY started_at DESC LIMIT 1;")


def _fetch_run(run_id: str) -> dict:
    """agent_runs 행(status/result/logs) 조회 → dict."""
    row = _psql(
        f"SELECT json_build_object('status',status,'result',result::text,'logs',logs)::text "
        f"FROM agent_runs WHERE id='{run_id}';"
    )
    try:
        return json.loads(row) if row else {}
    except json.JSONDecodeError:
        return {}


def _analyze_logs(logs: list) -> dict:
    """logs 프레임 → 단계별 ms(running→done ts) + 경고/에러 + 총 소요."""
    pending: dict[str, int] = {}
    steps: list[tuple[str, int]] = []
    warns: list[str] = []
    errors: list[str] = []
    ts_all: list[int] = []
    for e in logs or []:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts")
        if isinstance(ts, int):
            ts_all.append(ts)
        step, st = e.get("step"), e.get("status")
        if step and st == "running":
            pending[step] = ts if isinstance(ts, int) else 0
        elif step and st in ("done", "failed"):
            start = pending.pop(step, None)
            if isinstance(start, int) and isinstance(ts, int):
                steps.append((step, ts - start))
        lvl, msg = e.get("level"), (e.get("message") or "")
        # 단계 running/done 의 info/ok 요약 메시지는 노이즈라 제외, 실제 warn/error 만.
        if lvl == "warn" and step is None:
            warns.append(msg)
        elif lvl == "warn":
            warns.append(msg)
        elif lvl == "error":
            errors.append(msg)
    total_ms = (max(ts_all) - min(ts_all)) if ts_all else 0
    return {
        "steps": steps,
        "total_ms": total_ms,
        "warns": [w for w in warns if w],
        "errors": [e for e in errors if e],
    }


def _print_report(cycle: dict) -> None:
    p1, p2, mon = cycle["phase1"], cycle.get("phase2"), cycle.get("monitor") or {}
    print("\n" + "=" * 60, flush=True)
    print("SMOKE CYCLE REPORT", flush=True)
    print("=" * 60, flush=True)
    print(f"Phase1: reached_terminal={p1.get('reached_terminal')} saved={p1.get('saved')} "
          f"zero_effect={p1.get('zero_effect')}", flush=True)
    print(f"  result: {p1.get('result_text')}", flush=True)
    if p1.get("error"):
        print(f"  P1 ERROR: {p1['error']}", flush=True)

    steps = mon.get("steps") or []
    if steps:
        print(f"\n단계별 소요(총 {mon.get('total_ms', 0) / 1000:.1f}s) — 느린 순:", flush=True)
        for step, ms in sorted(steps, key=lambda x: -x[1]):
            bar = "█" * min(40, ms // 250)
            print(f"  {step:<16} {ms:>6}ms {bar}", flush=True)
    if mon.get("warns"):
        print(f"\n⚠ 경고 {len(mon['warns'])}건:", flush=True)
        for w in mon["warns"][:12]:
            print(f"  - {w[:120]}", flush=True)
    if mon.get("errors"):
        print(f"\n✗ 에러 {len(mon['errors'])}건:", flush=True)
        for e in mon["errors"][:12]:
            print(f"  - {e[:160]}", flush=True)

    if p2 is not None:
        print(f"\nPhase2(삭제): deleted={p2.get('deleted')} post_delete_count={p2.get('post_delete_count')} "
              f"rows={p2.get('rows')}", flush=True)
        if p2.get("error"):
            print(f"  P2 NOTE: {p2['error']}", flush=True)
    print("=" * 60, flush=True)


async def main() -> None:
    do_delete = "--no-delete" not in sys.argv

    print("[MON] 실행 전 최신 런 마커 기록…", flush=True)
    before = _latest_run_id()

    p1 = await phase1()

    # 새 런 식별(phase1 종료 시점 최신 런 = 방금 것). before 와 같으면 새 런 미검출.
    run_id = _latest_run_id()
    monitor = {}
    if run_id and run_id != before:
        run = _fetch_run(run_id)
        monitor = _analyze_logs(run.get("logs") or [])
        monitor["run_id"] = run_id
        monitor["db_status"] = run.get("status")
    else:
        print("[MON] 새 런을 찾지 못했습니다(before==after). Phase1 이 런을 못 만들었을 수 있음.", flush=True)

    cycle = {"phase1": p1, "monitor": monitor, "phase2": None}

    # 완료 & 저장됐으면 정리(삭제).
    if do_delete and p1.get("saved"):
        print("\n[CYCLE] 저장 확인됨 → Phase2 삭제 진행.", flush=True)
        cycle["phase2"] = await phase2()
    elif p1.get("saved"):
        print("\n[CYCLE] 저장됐지만 --no-delete → 삭제 생략(수동 정리 필요).", flush=True)
    else:
        print("\n[CYCLE] 저장 없음(반영 0건) → 삭제할 것 없음.", flush=True)

    _print_report(cycle)
    out = ARTIFACTS / "smoke_cycle.json"
    out.write_text(json.dumps(cycle, ensure_ascii=False, indent=1))
    print(f"\n리포트 JSON: {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
