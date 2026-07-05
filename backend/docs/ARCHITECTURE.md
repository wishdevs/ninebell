# 에이전트 플랫폼 아키텍처 — 분석·규칙·확장 레시피

> 2026-07-05 스케일링 리뷰(에이전트 2개 → 20개+ 대비) 결과 문서.
> 대상 독자: 새 에이전트를 추가하거나 공통 계층을 수정하는 개발자.

## 1. 계층 구조

```
┌─────────────────────────────────────────────────────────────┐
│ frontend (Next.js)                                           │
│   /agents/[id] — 데이터 주도(에이전트별 페이지 코드 없음)          │
│   lib/live — SSE·HITL 공용 배관(use-live-run, types)           │
└──────────────────────────┬──────────────────────────────────┘
                           │ SSE + REST
┌──────────────────────────┴──────────────────────────────────┐
│ app/live — 워크플로우 무관 실행 엔진                             │
│   registry(WorkflowSpec) · runner(브라우저·state 주입)          │
│   session(SSE 세션·재접속) · hitl(결정 큐) · events(프레임 계약)  │
│   store(런/템플릿 영속) · screencast                            │
├──────────────────────────────────────────────────────────────┤
│ app/agents — 에이전트(LangGraph 그래프)                         │
│   common/  진입 체인 7노드·gemini 디스패처·BaseAgentState        │
│   card_collect/  expense_card/  <새 에이전트>/                  │
├──────────────────────────────────────────────────────────────┤
│ nbkit — 브라우저 자동화 라이브러리(재사용, 앱 비의존)               │
│   browser/ 앱-불문 프리미티브 → grid/ dews 그리드                │
│   → omnisol/ 더존 특화(셀렉터·js_lib·코드피커·모달)               │
│   → patterns/ 조합 플로우(login·user_type·menu·grid_read)      │
└──────────────────────────────────────────────────────────────┘
```

**의존 방향은 항상 아래로만**: `app/live`는 그래프 내부를 모르고(`.ainvoke(state)` 계약뿐),
`app/agents`는 nbkit을 쓰며, nbkit은 app을 절대 import 하지 않는다.

## 2. 러너 ↔ 그래프 계약 (핵심 계약)

러너(`app/live/runner.py`)가 그래프 state 에 주입하는 키:

```
page, browser, events(asyncio.Queue), userid, password, params, owner, run_id
```

- 그래프는 `.ainvoke(state)`만 있으면 된다 — **LangGraph 는 교체 가능한 구현 디테일**.
- 노드는 `app.live.events` 헬퍼(emit_step/log/hitl/chat/…)로 진행을 방출하고,
  종료는 state 에 `result` 또는 `error` 를 남긴다.
- HITL 은 `app.live.hitl` 의 결정 큐(decision_id)로 — 채널 오픈 시 owner/run_id 바인딩(레이스 차단).

## 3. LangGraph 사용 판단과 관례

**판단: 유지.** 선형 체인 + 조건부 엣지(저장 실패 재시도) + 외부 HITL 큐 조합에 정확히 맞고,
러너 계약이 얇아 락인도 아니다. 20개 규모에 subgraph/checkpointer 는 불필요.

**관례(반드시 지킬 것):**
1. **State TypedDict 미선언 키는 조용히 버려진다.** 노드가 반환하는 모든 키는 State 에 선언
   — 실전 사고 이력 있음("적용할 행이 없습니다"). 모든 에이전트 State 는
   `app/agents/common/state.py::BaseAgentState` 를 상속하고, 에이전트 키만 추가한다.
   `tests/support/state_contract.py::all_declared_keys` 로 회귀 테스트 1개를 반드시 둔다.
2. **루프(조건부 엣지)가 있으면 recursion_limit 을 계산해 상향** — 기본 25는 체인 15노드 × 2회
   재시도에 모자란다(card_collect 는 60).
3. 그래프는 **1회 컴파일 후 재사용**(stateless) — `app/agents/__init__.py` 패턴.
4. 노드 실패는 예외가 아니라 `{"error": ...}` 반환 — 후속 노드는 `state.get("error")` 가드로 no-op.

## 4. 새 에이전트 추가 레시피

### 4-1. 옴니솔 화면 자동화 에이전트 (주류)
1. `app/agents/<name>/` 패키지: `graph.py`(State + 체인) + `nodes/`(페이즈별 파일, §6 규칙).
2. **진입 체인은 새로 짜지 말 것** — `app/agents/common/nodes.py` 의
   `make_login_node → make_user_type_node → make_menu_nav_node …` 재사용.
   메뉴가 다르면 `nbkit/omnisol/menu_schemas.py` 에 `MenuSchema` 추가.
3. 브라우저 조작은 계층 순서로 찾는다: `nbkit/omnisol/codepicker.py`(코드피커) ·
   `nbkit/omnisol/modals.py`(모달) · `nbkit/patterns/*`(플로우) · `nbkit/browser/*`(프리미티브).
   **없을 때만** 에이전트 `steps.py` 에 화면 특화 스텝을 만들고, 범용화되면 nbkit 으로 승격.
4. JS 는 `nbkit/omnisol/js_lib.py` 단일소스(OMNISOL_NOTES §7). 화면 특화 JS만 에이전트 `js.py`.
5. 등록: `app/agents/__init__.py` 에 `register_workflow("<id>", factory, delay_scale=…)`.
6. 노출: `app/services/agent_fixtures.py` 에 Agent+steps(스킬은 `services/skills.py` 카탈로그 키),
   시드 후 프론트는 자동 반영(에이전트별 페이지 코드 불필요).
7. 검증: 유닛(fake page) + state-contract 테스트 + 라이브 스모크(가능하면 e2e/ 패턴 복제).

### 4-2. 타 웹사이트 에이전트
- `register_workflow(..., site="<사이트키>", login_form_selector=<그 사이트 로그인 폼>|None)`.
  웜 세션 캐시는 `(site, userid)` 로 격리되며 selector=None 이면 캐시 비활성.
- nbkit `browser/`·`grid/`·`patterns/` 는 재사용 가능. 사이트 특화 계층은 omnisol 을 본떠
  별도 패키지로(예: `nbkit/<site>/`) — omnisol 모듈에 섞지 말 것.

### 4-3. 순수 API/LLM 에이전트 (브라우저 없음)
- `register_workflow(..., needs_browser=False)` — 러너가 Chromium 런치·스크린캐스트·세션캐시를
  전부 생략한다. state 의 `page`/`browser` 는 None. events/HITL/chat 은 동일하게 동작.

## 5. WorkflowSpec — 에이전트별 실행 노브

실행 노브는 **코드 레지스트리**(`app/live/registry.py::WorkflowSpec`)에 둔다.
DB `Agent` 행은 노출/권한(조직 접근·allowlist) 전용. 이유: 노브는 그래프 코드와 결합돼 있어
(바꾸면 코드 재검증 필요) 코드와 함께 버전되는 것이 맞다.

| 필드 | 기본 | 의미 |
|---|---|---|
| `needs_browser` | True | False 면 브라우저 경로 전체 생략(순수 LLM) |
| `delay_scale` | None(=1.0) | 대기 배율(라이브 검증된 에이전트만 축소, card-collect=0.15). env `CARD_DELAY_SCALE` 이 항상 우선(테스트 override) |
| `site` | "omnisol" | 웜 세션 캐시 네임스페이스 |
| `login_form_selector` | "#userid" | 웜 판정 셀렉터. None=캐시 비활성 |

## 6. 모듈화 규칙 (nodes.py 비대화 방지)

- 에이전트 노드는 **`nodes/` 패키지 + 페이즈별 파일**(≤~400줄):
  card_collect 예 — `query.py`(조회 앞단) `catalog.py`(코드/즐겨찾기 로더) `prefill.py`(추천/프리필)
  `collect.py`(그리드 HITL) `batch.py`(일괄반영) `pass2.py`(2패스) `save.py`(저장) `_shared.py`(소헬퍼).
  `nodes/__init__.py` 가 전 심볼을 재수출해 그래프/테스트 임포트는 `from . import nodes` 유지.
- **형제 모듈 호출은 속성 접근으로**: `from . import batch` 후 `batch._apply_group_fields(...)`.
  `from .sibling import fn` 금지 — 사이클과 몽키패치 깨짐의 원인.
- 브라우저 프리미티브(`steps.py`)와 노드(오케스트레이션)는 분리 유지. 노드는 `steps.X` 속성
  접근으로만 호출(테스트가 `monkeypatch.setattr(steps, ...)` 하는 계약).

## 7. 스킬 카탈로그

- `app/services/skills.py::SKILLS` 가 공용 스킬의 단일소스(key→라벨·설명·계층).
- `agent_fixtures.py` 의 step.skill 은 **카탈로그 키**만 허용(테스트로 강제).
- 프론트 스텝 라벨/스킬은 백엔드 `/agents/{id}` steps 가 단일소스 — 프론트에 스텝 정의를
  복제하지 않는다(과거 3중 복제의 교훈).
- `GET /skills` + `/skills` 페이지: 스킬 목록과 "어떤 에이전트가 쓰는지" 역인덱스.

## 8. 알려진 부채 / 보류 결정 (다음 에이전트 착수 시 처리)

| 항목 | 상태 | 처리 시점 |
|---|---|---|
| HITL 그리드 오케스트레이션 공용화(`common/grid_hitl.py`) | `card_collect/nodes/collect.py` 에 격리됨 | GLDDOC00300 문서군 두 번째 에이전트(출장/경조금/학자금) PR 에서 추출 — 소비자 1개로 추출하면 경계를 잘못 굳힘 |
| `recommend.py` → `common/gemini.py` 통합 | 별도 Gemini 배관 중복 | 두 번째 추천 소비자 생길 때 |
| `expense_card/tools.py` 피커 → nbkit codepicker | 자체 구현(라이브 검증됨) | 다음 수정 기회에. 신규 에이전트는 nbkit 사용 필수 |
| demo-echo 라이브 스텝 라벨 | DB steps 없음 → raw id 표시 | 의도된 수용(데모 전용) |

## 9. 검증 체계

- 유닛: `backend && .venv/bin/python -m pytest -q` — 전 에이전트 fake-page 테스트 + state contract.
- 라이브: `backend/e2e/smoke_cycle.py` — 대시보드 실행→실저장→ERP 확인→삭제 1사이클 + 단계별 ms 리포트.
  공통 계층(runner/registry/nbkit 핫패스)을 건드리면 반드시 1회 돌린다.
- 프론트: `npx tsc --noEmit`.
