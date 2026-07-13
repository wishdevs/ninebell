# 단계 5·7 — 테스트 스위트 + 실저장 E2E 사이클

두 계층으로 검증한다. 유닛은 항상, 라이브 사이클은 무결 확정용.

## 계층 1 — 유닛/그래프 (backend/tests/, pytest)

부작용 없음. `test_trip_overseas.py` 등을 본. 새 에이전트는 최소:

- `params.py` 정규화·파생·각 한국어 `ValueError` 검증.
- validate 노드 코루틴 직접 호출(가짜 state `{"events": asyncio.Queue(), "params": {...}}`).
- `test_graph_compiles`(build 팩토리 non-None).
- `test_registered_in_workflow_registry`(`get_spec("<kebab-id>")` → needs_browser·delay_scale).
- `test_fixture_promoted_from_dummy`(픽스처 `steps` 키가 그래프 노드 순서와 **정확히 일치** —
  `agent_fixtures.py` flow_graph·steps 를 그래프와 lockstep 유지하는 회귀 가드).
- State 계약: 노드가 반환하는 키가 State TypedDict 에 전부 선언됐는지(`tests/support/state_contract.py`).

```bash
cd backend && .venv/bin/pytest tests/test_<name>.py -q
```

## 계층 2 — 라이브 실저장 사이클 (backend/e2e/<name>_smoke_cycle.py)

정책(사용자 지시 2026-07-07): **저장 없는 반복은 무의미.** 실저장(F7)→검증→삭제 사이클로 테스트.
`trip_smoke_cycle.py` 가 레퍼런스 구현. 한 사이클 = **register → verify persisted → F6 delete →
잔존 0 확인.** 이 사이클 러너가 단계 7 flakiness 테스트도 겸한다(N 반복).

### 사이클 구조 (trip_smoke_cycle.py 기준)

1. `_cycle_params(cycle)` — 사이클마다 값을 흔들어 픽스처 생성(회귀 다양성).
2. `_drive_graph(page, params)` — 러너 state 미러 주입 후 `graph.ainvoke`(실저장 F7, 몽키패치 없음).
   events 큐에서 스텝 ms·실패·에러 수집.
3. save_ok 판정 — error 없음 + `save_doc` 스텝 존재 + 실패 목록에 없음.
4. `_verify_and_delete(page, cycle)`:
   - 조회(F2) → 마스터 rowcount 안정화 폴링.
   - `MASTER_DUMP_JS` 로 행 덤프, `ABDOCU_NO` 수집.
   - **가드레일**: `_row_is_ours(r)` = 결의자(WRT_EMP_NM)=USERID + 결의구분(ABDOCU_FG_CD)=코드 +
     미결(DOCU_NO 공백). 하나라도 아니면 **삭제 중단·스크린샷·보고**.
   - 전체선택 → F6(또는 BTN_DELETE 좌표클릭) → 확인 모달 폴링 처리("예/확인/삭제").
   - 재조회 → **after==0** 이어야 `deleted=True`. 아니면 잔존 전표번호와 함께 실패.
5. 사이클 요약: `PASS/N · avg run · aborted` + 잔존 전표 0 확인. 리포트 JSON:
   `backend/e2e/artifacts/<name>_smoke_cycle.json`.

### 파생값 정합 검증 (중요 — 경조금 실측 선례)

사이클은 `save_ok`·`deleted` 만 보지 말고, **계산·파생 필드가 저장된 문서에 기대값으로 들어갔는지**
까지 재조회로 확인한다. 유닛테스트 통과 ≠ 실 저장값 정합. 예: 근속<1년 50% 공급가액을 넣으면 저장된
detail `SPPRC_AMT2` == 기대값(`ROUND_HALF_UP`)인지 대조. 사이클마다 입력값을 흔들어(.5 경계 포함)
파생 로직이 **실 저장까지 매번** 맞는지 검증한다.

### 안전 규칙 (사이클 docstring 에 명시)

- **삭제까지가 한 사이클** — 삭제 검증(잔존 0) 없이 다음 사이클 진행 금지.
- **상신(결재) 절대 금지** — F7(저장)·F6(삭제)만. 삭제 불가 상태를 만들지 않는다.
- 삭제 가드레일 불일치 → 즉시 중단(테스트 계정 외 전표 보호).
- 삭제가 한 번이라도 실패 → 사이클 중단하고 **전표번호와 함께 즉시 보고**.
- 스크립트 안정화 초기에는 저장 게이트를 닫고 검증해도 되지만, **최종 10회는 실저장 사이클**.

### 실행 (먼저 1회로 검증)

```bash
cd backend
E2E_USERID=<테스트계정> E2E_PASSWORD=<pw> <NAME>_SMOKE_CYCLES=1 .venv/bin/python e2e/<name>_smoke_cycle.py
# 1회 무결 확인 후 10회
E2E_USERID=<테스트계정> E2E_PASSWORD=<pw> <NAME>_SMOKE_CYCLES=10 .venv/bin/python e2e/<name>_smoke_cycle.py
```

## 단계 7 — flakiness / 안정성 지표

- N회 반복(기본 10) 실저장 사이클로 flakiness 측정. 목표: **PASS 10/10, 잔존 전표 0.**
- avg run(초) 기록 → delay_scale 튜닝 근거(`__init__.py` register_workflow 주석 참조).
- 회귀: 계층 1 유닛 + 계층 2 사이클을 코드 변경마다 재실행.
- 사이클 러너 실행은 시간이 길다(에이전트당 수 분×N) → **prober/Bash 에 위임하고 메인엔 요약만.**

## teardown 원칙

create→verify→**delete**. 테스트 전표를 절대 남기지 않는다. 삭제 실패 시 사람이 정리할 수 있게
전표번호를 리포트에 남기고 즉시 중단. `record_video_dir`+`slow_mo` 는 디버깅 스토리보드용(옵션).
