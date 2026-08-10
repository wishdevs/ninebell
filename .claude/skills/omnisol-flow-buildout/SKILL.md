---
name: omnisol-flow-buildout
description: >-
  Standard operating procedure for building a new 더존 옴니솔(Douzone OmniEsol)
  browser-automation agent end to end — feasibility gate → PROCESS.md 플로우 명세 →
  headless 읽기/쓰기 경로 검증 → 자가수정 루프 → 실저장 E2E 사이클 → LangGraph 통합 →
  운영. Use this WHENEVER the user asks to build, add, automate, 자동화, or 플로우 구축 a
  new 옴니솔 / 결의서입력(GLDDOC00300) / ERP screen flow in this repo — even if they jump
  straight to "write the agent". Start at the feasibility gate, not at code. Also
  use when debugging or extending an existing agent's PROCESS.md / graph / e2e cycle.
origin: 나인벨 옴니솔 자동화 대시보드 — flow-buildout 표준절차 (2026-07)
version: "1.0.0"
---

# 옴니솔 플로우 구축 표준절차 (flow-buildout SOP)

브라우저 자동화(API 아님)는 데이터를 가져오거나 조작하는 방법이 화면마다 조금씩 달라서
**한 번에 맞지 않는다.** 이 절차는 그 불확실성을 단계별 게이트로 가둬서, 추측이 아니라 실측으로
확정하고, 위험한(비가역) 액션은 항상 게이트 뒤에 둔다. 새 옴니솔 자동화를 만들 때는 코드부터
쓰지 말고 **0 → 8 순서로** 진행하고, 각 단계의 산출물을 리포지토리에 남긴다.

이 스킬은 **오케스트레이션**이다. 저수준 그리드 함정(캔버스 setValue 오염, 숨은 백킹필드,
코드피커 dblclick, time-scaling, 문서종류별 필드 편차)은 여기서 다루지 않는다 — 그건
`erp-headless-grid-automation` 스킬이 소유한다. **필독:**
`~/.claude/skills/erp-headless-grid-automation/SKILL.md`.

## When to Use

- 새 결의서입력 문서종류(경조금·학자금 등) 또는 새 옴니솔 화면 자동화를 만들 때.
- 기존 에이전트(card_collect / trip_domestic / trip_overseas)를 형제 문서종류로 복제·확장할 때.
- 헤드리스 스텝이 "코드상 성공인데 실제로는 틀림"(빈 컬럼·opaque DB 에러·팬텀 저장)일 때.
- PROCESS.md 의 `검증: ❓` 가정을 라이브 프로브로 ✅ 로 승격해야 할 때.

## 이 리포의 사실(먼저 확인)

새로 만들지 말고 **기존 자리에 맞춘다.** 실제 컨벤션:

| 개념 | 위치 | 역할 |
|---|---|---|
| 에이전트 패키지 | `backend/app/agents/<snake_name>/` | 문서종류 1개 = 패키지 1개 |
| 플로우 명세(=flow.md) | `<pkg>/PROCESS.md` | 사람이 읽는 버전관리 SOP. **이게 "에이전트별 flow.md"다** |
| 패밀리 인덱스 | `backend/app/agents/RESOLUTIONS.md` | 결의서 문서종류 ↔ 에이전트 ↔ 상태 표 |
| 입력 파싱/검증 | `<pkg>/params.py` | 폼 payload → 정규화 + 한국어 ValueError |
| 스텝 프리미티브 | `<pkg>/steps.py` | Playwright/ERP 저수준 액션(그리드 채움·피커·save·delete) |
| in-page JS | `<pkg>/js.py` | 그리드 스냅샷·rowcount·모달/토스트·버튼 좌표 JS 상수 |
| 그래프 노드 | `<pkg>/nodes/` | fill/save/validate 노드 팩토리(단계별 파일) |
| 그래프 조립 | `<pkg>/graph.py` | `StateGraph` + State TypedDict + 조건부 엣지 + `build_*_graph()` |
| 상태 계약 | `backend/app/agents/common/state.py` | `BaseAgentState` 상속(러너 주입 키·result/error) |
| 진입 앞단(공유) | `backend/app/agents/common/nodes.py` | login→user_type→menu_nav→set_gubun→add_row→open_evdn |
| 옴니솔 노하우 | `backend/nbkit/OMNISOL_NOTES.md`, `nbkit/omnisol/{js_lib,selectors,menu_schemas}.py` | 캔버스·수집·사용자유형·셀렉터 단일소스 |
| HITL(개입) | `backend/app/live/hitl.py` | 큐 기반 `wait_hitl`/`open_hitl_channel`(LangGraph interrupt 아님) |
| E2E 실저장 사이클 | `backend/e2e/*_smoke_cycle.py`, 아티팩트 `backend/e2e/artifacts/` | register→verify→F6 delete→잔존 0 |
| 프론트 픽스처/flow_graph | `backend/app/services/agent_fixtures.py` | flow 시각화 노드·steps(그래프 노드와 lockstep) |
| 워크플로우 등록 | `backend/app/agents/__init__.py` | `register_workflow("<kebab-id>", …, delay_scale=…)` |

## 절대 안전 규칙 (모든 단계에서 유효)

이걸 어기면 실데이터가 생기거나 조용히 실패한다. 예외 없음.

1. **저장(F7)은 게이트 뒤에만.** F7(`.main-button.save`)은 전용 save 노드에서 `confirm=True`
   일 때만 발화. `selectors.BTN_SAVE` 는 참조용 상수 — **절대 클릭 금지**. 스크립트 안정화 중에는
   게이트를 닫고(실저장 없음) 검증한다.
2. **상신(결재) 절대 금지.** 삭제 불가 상태를 만들지 않는다. 자동화는 F7(저장)·F6(삭제)까지만.
   상신은 언제나 사용자가 ERP 에서 직접(모든 `handoff_note` 가 이걸 안내).
3. **쓰기 검증은 격리된 테스트 계정 + create→verify→delete 사이클로만.** 저장한 건 즉시 F6 삭제,
   잔존 0 확인까지가 한 사이클. 삭제 실패 시 **전표번호와 함께 즉시 중단·보고.**
4. **삭제 가드레일.** 결의자=로그인계정 + 결의구분(ABDOCU_FG_CD) 일치 + 미결(DOCU_NO 공백).
   하나라도 안 맞으면 삭제 중단(테스트 계정 외 전표 보호).
5. **자격증명 비저장.** 매 실행 1회 로그인 → 작업 → 즉시 폐기.
6. **캔버스 현실.** 더존 그리드는 `<canvas>`(RealGrid). DOM/텍스트 셀렉터·`getCellRect` 안 통한다
   → `$(".dews-ui-grid").eq(i).data("dewsControl")._grid`. 성공판정은 URL 아니라 요소/그리드 상태.
7. **라이브 2~3회 실패하면 멈추고 도메인 전문가(사용자)에게 물어라.** 브루트포스보다 빠르다.

## 비가역 액션 목록 (단계 1에서 명시 표시)

플로우 명세에 **비가역**으로 반드시 표시할 것: F7 저장, 코드피커 모달 **확정 '적용'** 이후 단계,
행/전표 삭제(F6·전표취소), 상신. 이 액션들은 그래프에서 게이트(save 노드 confirm) 또는 HITL 승인
뒤에 둔다.

## 9단계 절차

각 단계는 **게이트**다 — 산출물이 없으면 다음으로 못 넘어간다. 탐색·대량읽기·다회 프로브는
**`omnisol-flow-prober` 서브에이전트에 위임**해 메인 컨텍스트를 보호한다(아래 위임 모델).

### 0. 대상 조사 / 실현가능성 게이트 → 진행/중단 판단
로그인 방식·2FA·봇탐지·CAPTCHA·robots/ToS·테스트 계정 확보를 확인. 옴니솔은 사내 ERP 라 대개
통과지만, **테스트 계정 격리**와 **문서종류 진입 경로(딥링크/사용자유형)** 를 여기서 확정한다.
**요청에 대상 화면(어느 메뉴·회계/인사)·계정·사람이 하는 기본 플로우가 없으면, 추측하지 말고
먼저 사용자에게 묻는다** — 새 문서종류가 기존 에이전트(출장·카드)와 같은 화면·사용자유형이라고
가정하지 않는다(`RESOLUTIONS.md` 예정 행은 계획일 뿐 증거 아님). 산출물: 진행/중단 판단 + 진입
경로 메모. → **`references/0-feasibility-gate.md`** (필수 입력 게이트)

### 1. 플로우 명세 md (PROCESS.md 초안) → 구조화된 flow.md
사용자가 구술한 화면/업무 스텝을 그대로 MD 로. 미확정 기술요소(셀렉터·좌표·필드id·컬럼)는
`검증: ❓`. 업무 결정(값 규칙·기본값)은 D1…Dn 으로 명시. **비가역 액션 표시.** 성공조건·실패조건을
스텝마다 적는다. `RESOLUTIONS.md` 에 새 행 등록, 형제 PROCESS.md 크로스링크.
→ **`references/1-process-md-template.md`** (실제 헤딩 스켈레톤 + ❓/✅ 규칙)

### 2. 읽기 경로 검증 (부작용 없음) → 데이터 추출 성공
헤드리스로 실제 화면을 열어 DOM/그리드/버튼/좌표를 **전량 덤프**하고, 각 읽기 스텝을 실행해
동작(데이터 존재 여부 포함)을 확인. 부작용 0. → **prober 에 위임.** prober 는 확정된 셀렉터/컬럼/
데이터 예시를 반환. 기존 프리미티브(nbkit js_lib/selectors, 기존 `*_probe.py`)를 재사용.

### 3. 쓰기 경로 검증 (격리된 테스트 계정에서만) → 등록 성공
게이트를 연 1회 실저장으로 무엇이 실제 영속되는지 확인 → 즉시 F6 삭제. 안전 규칙 3·4 필수.
저수준 쓰기 함정(setValue 오염·피커 dblclick·숨은 백킹필드)은 erp-headless-grid-automation 참조.
→ **prober 에 위임**(쓰기는 명시적으로 게이트/삭제 검증을 요구).

### 4. 자가수정 루프 → 확정된 PROCESS.md
재시도 상한 + 실패 증거(스크린샷/JSON) + 원인 분류(셀렉터 드리프트 / 타이밍 / 필드부재 /
트리거 미발화 / 데이터 없음) + 변경 이력. 성공하면 실측값을 PROCESS.md 에 접고 ❓→✅ 승격.
→ **`references/4-self-correction.md`** (재시도·원인분류·변경이력 규율)

### 5. 테스트 환경 / 픽스처 + E2E → 통과하는 테스트 스위트
유닛(params 정규화·검증·노드 코루틴·그래프 컴파일·등록·픽스처 lockstep)은 `backend/tests/`.
라이브 E2E 는 `backend/e2e/<name>_smoke_cycle.py`: **실저장(F7)→검증→F6 삭제→잔존 0** 사이클.
→ **`references/5-e2e-cycle.md`** (사이클 구조 + 가드레일 + teardown)

### 6. PROCESS.md → LangGraph 그래프 → 그래프 코드
확정된 방법을 단일소스 프리미티브(`js.py`+`steps.py`) + 노드(`nodes/*.py`)로 옮기고 `graph.py`
에서 조립. **State TypedDict 는 `BaseAgentState` 상속 + 노드가 반환하는 키를 전부 선언**
(미선언 키는 LangGraph 가 조용히 버린다 — 실전 회귀). 재시도는 조건부 엣지(`retry_save` 플래그
→ `menu_nav` 되감기 or `END`). **비가역 액션은 save 노드 게이트 / HITL 승인 뒤.** HITL 이 필요하면
`app/live/hitl.py`(interrupt 아님). `agent_fixtures.py` flow_graph·steps 를 그래프 노드와 lockstep
유지(`test_fixture_promoted_from_dummy` 가 검사). `__init__.py` 에 `register_workflow` 등록.
**금액·파생값 반올림은 리포 규칙(`Decimal`+`ROUND_HALF_UP`)** — 파이썬 내장 `round()`(은행가 반올림)
금지(`trip_domestic.fuel_support_amount` 선례). 비가역 저장이라 .5 경계 1원 오차도 영구 확정된다.
**형제 포팅 시 스텝을 단계 1 사용자 플로우에 대조** — 형제(trip 등)가 가진 스텝/필드라도 사용자가
구술하지 않은 건 제거 후보로 표시·확인(예: 경조금은 상대계정거래처 불필요인데 trip 에서 물려받아 헛
구현). 필드 편차(erp §5)의 짝 — **없어야 할 필드**도 실측·정리. **코딩 후 코드리뷰 위임**(code-reviewer)
로 이 함정들(반올림·State 키·F7 게이트·포팅 잔재) 점검 후 라이브 진입 — 이번 빌드에서 리뷰가
비가역-저장 반올림 버그를 라이브 전에 잡았다.

### 7. 그래프 검증 → 안정성 지표
5번 스위트 재사용 + **N회 반복 flakiness 테스트**(기본 10 사이클 실저장, `*_SMOKE_CYCLES` env)
+ 회귀. 지표: PASS/N, avg run, 잔존 전표 0. → 사이클 러너 실행은 **prober/Bash 에 위임**,
메인에는 요약만 회수.

### 8. 운영 → 모니터링
셀렉터 드리프트 감지(옴니솔 리스킨/버전업 시 클래스·id·좌표 변동), 트레이스/아티팩트 저장,
PROCESS.md 버전 관리. → **`references/8-operations.md`**

## 위임 모델 (메인 컨텍스트 보호)

브라우저 자동화의 "여러 번 시도"는 컨텍스트를 오염시킨다. **단계 2·3·4·7의 헤드리스 프로브
반복은 `omnisol-flow-prober` 서브에이전트에 위임**한다:

- **투입**: 대상 PROCESS.md(또는 ❓ 가정 목록), 문서종류/결의구분, delay_scale, 재시도 상한,
  읽기전용 vs 쓰기(게이트) 여부.
- **회수**: 확정된 셀렉터/좌표/필드id/컬럼 표, ❓→✅ 해소, 실패 증거(아티팩트 경로)+원인 분류,
  권장 PROCESS.md 패치. **산문이 아니라 구조화된 사실.**
- prober 는 쓰기 프로브 시 안전 규칙 3·4(게이트·삭제검증·가드레일·상신금지)를 반드시 지킨다.
- 병렬화: 서로 독립인 읽기 프로브(여러 필드/컬럼 확인)는 여러 prober 로 동시에. 쓰기 프로브는
  테스트 계정 경합을 피해 직렬.

메인 에이전트는 오케스트레이터로 남는다: 게이트 판단, PROCESS.md 작성/보완, 그래프 통합,
사용자 승인·HITL 게이트, 최종 보고. **탐색·대량덤프·다회 프로브는 회수된 결론만 받는다.**

## 참조 파일 인덱스

- `references/0-feasibility-gate.md` — 단계 0 체크리스트(로그인·2FA·CAPTCHA·robots·테스트 계정·진입경로)
- `references/1-process-md-template.md` — 단계 1 PROCESS.md 스켈레톤·D결정·❓/✅·비가역 표시
- `references/4-self-correction.md` — 단계 4 재시도 상한·원인 분류·변경 이력
- `references/5-e2e-cycle.md` — 단계 5·7 실저장 사이클·가드레일·teardown·flakiness
- `references/8-operations.md` — 단계 8 셀렉터 드리프트·트레이스·버전관리
- (필수 선행) `~/.claude/skills/erp-headless-grid-automation/SKILL.md` — 저수준 그리드 함정
