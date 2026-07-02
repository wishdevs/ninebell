# LangGraph · HITL 챗 구현 리뷰

옴니솔 자동화 대시보드의 라이브 워크플로우 실행 엔진(LangGraph 기반)과 HITL(human-in-the-loop)
대화형 챗 구현을 사실 기반으로 정리한다. 파일:라인 참조는 리뷰 시점(feat/backend-auth-rbac)
기준이며, 일부 라인은 이 리뷰 패스에서 적용한 수정(아래 "이번 패스에서 적용한 수정")으로
소폭 이동했을 수 있다.

---

## 1. LangGraph 세팅

### 그래프 등록·조립
- **레지스트리**: `backend/app/live/registry.py` — `register_workflow(agent_id, factory)`
  (`registry.py:18`)로 `agent_id → 컴파일된 그래프 팩토리`를 등록한다. `factory()`는 컴파일된
  LangGraph(또는 `.ainvoke(state)`를 가진 객체)를 반환하는 계약.
- **import 시점 등록**: `backend/app/agents/__init__.py` — 모듈 import 시 `expense-card-chat`,
  `card-collect` 두 워크플로우를 1회 컴파일 후 등록(`__init__.py:18-22`). `demo-echo`는
  `registry._register_builtin()`이 기본 등록(`registry.py:32-40`).
- **그래프 정의**:
  - `backend/app/agents/expense_card/graph.py` — `StateGraph(ExpenseCardState)`, 선형 노드 체인
    (login→user_type→menu_nav→set_gubun→add_row→open_evdn→select_evdn→chat_form),
    `g.compile()` (`graph.py:47-67`).
  - `backend/app/agents/card_collect/graph.py` — 동일 앞단 재사용 + card_collect 후단
    (select_all_cards→set_period→query→collect_rows→save), `g.compile()` (`graph.py:50-84`).
  - `backend/app/live/demo_echo.py` — P2 더미(open→greet→confirm→finish) (`demo_echo.py:137-149`).
- **체크포인터 없음**: 세 그래프 모두 `g.compile()`을 인자 없이 호출한다(체크포인터 미지정).

### State 타이핑
- 모든 state 는 `TypedDict, total=False` (`expense_card/graph.py:32`, `card_collect/graph.py:36`,
  `demo_echo.py:24`).
- state 가 **직렬화 불가능한 객체**를 실어 나른다: Playwright `page`/`browser`,
  `asyncio.Queue`(events). 러너가 주입(`runner.py:61-71`). 이 때문에 LangGraph 체크포인터를
  붙일 수 없다(직렬화 불가).

### 러너(실행 오케스트레이션)
- `backend/app/live/runner.py` — `run_workflow()` (`runner.py:35`).
  - fresh 헤드리스 브라우저를 세마포어로 동시 실행 제한하며 띄우고(`runner.py:52-56`), page·events
    큐·자격증명·파라미터를 state 에 주입(`runner.py:61-72`).
  - 그래프를 **단일 `graph.ainvoke(state)` 호출**로 실행(`runner.py:72`) — `astream`/
    `astream_events` 미사용. 진행 이벤트는 그래프 밖 **사이드채널 events 큐**로 흘린다
    (`runner.py:82-93`).
  - 취소는 제너레이터 `aclose()` → runner task `cancel()` + 브라우저 `close()` (`runner.py:94-108`).

### 에러 처리 — 조건부 엣지 대신 노드별 가드 보일러플레이트
- 각 노드가 `if state.get("error"): return {}` 로 앞 노드 실패 시 자기 일을 건너뛴다.
  - `backend/app/agents/common/nodes.py` — 7곳(`nodes.py:38,56,72,89,120,153,198`).
  - `backend/app/agents/card_collect/nodes.py` — 다수(`nodes.py:79,100,131,…`).
  - `expense_card/chat_form.py:285`, `demo_echo.py:128`.
- **함의**: LangGraph 의 conditional edges 를 쓰지 않으므로, 한 노드가 실패해도 **하위 노드가
  전부 no-op 로 계속 실행**된다(그래프가 조기 종료하지 않음). save 노드는 별도로
  `state.get("error")` 시 result 로 전환(`card_collect/nodes.py:506`).

### 동시성
- `login_semaphore` / `run_semaphore` (`backend/app/main.py`, 상한 `config.max_concurrent_erp_runs=2`).
- `run_semaphore` 는 `run_workflow`의 `async with limiter:` 로 **런 전체 구간을 점유**
  (`runner.py:53`) — HITL 대기 구간도 포함. 아이들 챗이 슬롯을 오래 잡는다(아래 리스크 참조).

### 관용적 LangGraph 대비 특이점(사실 목록)
1. **체크포인터가 어디에도 없음** — `grep -rn "checkpointer\|MemorySaver\|Checkpoint" backend/app`
   결과 없음. 세 그래프 모두 `compile()` 무인자.
2. **`interrupt()` / `Command(resume=...)` 미사용** — HITL 을 LangGraph 네이티브 인터럽트가 아니라
   **자체 큐(`app.live.hitl`) + events 사이드채널**로 구현.
3. **`ainvoke` + 사이드채널** — `astream_events` 로 노드 진행을 얻는 대신 노드가 직접 events 큐에
   프레임을 put 한다(`runner.py:72`, `app.live.events` 헬퍼).
4. **직렬화 불가 state** — page/browser/Queue 가 state 에 있어 체크포인팅 자체가 불가.
5. **고정 슬립 폴링 루프** — Playwright 네이티브 wait 대신 `page.wait_for_timeout` 기반 폴링
   (`expense_card/chat_form.py:159-174` `_wait_modal_idle`).
6. **무한(unbounded) 세션 버퍼** — 스크린샷 외 프레임은 상한 없이 누적(`live/session.py:58` `buffer`,
   `_push` `session.py:152-155`). 로그만 `_MAX_RUN_LOGS=2000` 상한(`session.py:36,159`).

---

## 2. HITL 챗 구현

### 큐 모듈 — `backend/app/live/hitl.py`
- **지속(멀티턴) 채널**: `open_hitl_channel(decision_id, *, owner, run_id)` /
  `close_hitl_channel` (`hitl.py:24,45`) — 노드 수명 동안 같은 `decision_id` 큐를 유지해 턴 사이
  공백에도 사용자 입력이 유실되지 않고 큐잉된다. 대화형 노드(chat_form / collect_rows)가 사용.
- **단발(one-shot)**: `wait_hitl(events, *, kind, title, prompt, …, timeout_s, owner, run_id)`
  (`hitl.py:64`) — hitl 프레임 방출 후 한 응답을 timeout 까지 대기. save 확인/demo confirm 이 사용.
- **소유권/런바인딩 등록 시점**: 이번 패스 이전에는 `open_hitl_channel`/`wait_hitl`이 owner/run_id 를
  받지 않고, LiveSession 펌프가 hitl 프레임을 관찰할 때 비로소 `set_hitl_owner` 로 등록했다
  (`session.py:92-95`). 이 사이에 `/runs/hitl` 이 소유권 검사를 건너뛰는 **레이스 창**이 있었다.
  → 이번 패스에서 채널 오픈 시점 바인딩으로 창을 닫음(아래 수정 §3).

### `/runs/hitl` 엔드포인트 — `backend/app/routers/runs.py`
- `@router.post("/hitl")` `hitl()` (`runs.py:236` 부근).
- 소유권 검사는 `decisionId` 키의 owner 맵(`hitl_owner`)에 의존(`runs.py`의 owner 분기).
- 요청 바디의 `runId` 필드(`HitlDecision.runId`, `runs.py:90`)는 이번 패스 이전엔 **수신만 하고
  검증하지 않았다** → 이번 패스에서 채널이 바인딩한 run_id 와 교차검증 추가(§3).

### 소비 노드
- **expense_card** `backend/app/agents/expense_card/chat_form.py` — 지속 채널
  (`open_hitl_channel`, `chat_form.py:390` 부근). 한 턴 도구 상한
  `_MAX_TOOLS_PER_TURN=12`(`chat_form.py:53`). 이번 패스 이전엔 **중복 도구호출 가드 없음**
  → §3 에서 `_sig`/`seen_actions` 포팅.
- **card_collect** `backend/app/agents/card_collect/nodes.py` `collect_rows` — 지속 채널 +
  **중복 도구호출 서명 가드** `_sig`(`nodes.py:319`)/`seen_actions`(`nodes.py:360`), 가드 대상
  `{skip_rows, update_note, apply_fields, show_status}`(`nodes.py:383-388`). 실측에서 Gemini 가
  `skip_rows` 를 12회 반복하던 문제 대응.
- save 노드는 `wait_hitl(kind="choice")` 로 F7 저장 확인(`card_collect/nodes.py:516` 부근).

### 프론트엔드
- `src/lib/live/use-live-run.ts` `useLiveRun` — SSE-over-fetch, 커서 재생, 재연결 backoff,
  `pagehide` 에서 cancel 트리거(F5/네비게이션이 런을 종료 — 네트워크 드롭 재연결 지원과는 별개).
- `src/components/live/LiveChatCard.tsx` — 챗 버블 렌더(마크다운 표), `processing` 상태로 타이핑
  인디케이터 게이팅(`LiveChatCard.tsx:76` 부근). 이번 패스 이전엔 전송 실패한 사용자 말풍선이
  마지막이면 `processing` 이 영구 true 로 남는 버그 → §3 수정.

### 리스크 목록(사실 기반)
1. **인프로세스/단일워커 전용 상태** — 큐(`hitl.py`), 세션(`session.py:41` `_SESSIONS`), 세마포어가
   모두 모듈 레벨 메모리. 영속/재수화 없음 → 다중 워커/재시작에 취약.
2. **HITL 소유권 레이스 창** — (이번 패스에서 수정) 채널 오픈~펌프 관찰 사이 `/runs/hitl` 이
   소유권 검사를 건너뛸 수 있었음.
3. **`/runs/hitl` 의 `runId` 미검증** — (이번 패스에서 수정) 다른 흐름의 `decisionId` 로의 응답 주입
   가능성.
4. **아이들 챗의 런 슬롯 점유** — `run_semaphore`(상한 2)가 HITL 대기(턴당 최대 600s
   `hitl_timeout_s`)를 포함한 런 전체를 점유(`runner.py:53`).
5. **사용자 챗 버블이 SSE 재생 버퍼에 없음** — 어시스턴트 프레임만 버퍼에 쌓이고 사용자 낙관 버블은
   프론트 로컬 상태라, 재연결 시 사용자 말풍선이 사라진다.
6. **F5/pagehide 가 런을 종료** — 네트워크 드롭 재연결은 지원하나 명시적 페이지 이탈은 cancel.
7. **타이핑 인디케이터 멈춤 버그** — (이번 패스에서 수정) 전송 실패 시 "처리 중…"이 영구 표시.
8. **중복 도구호출 가드 불일치** — (이번 패스에서 수정) card_collect 엔 있고 expense_card 엔 없었음.
9. **무한 세션 버퍼** — 스크린샷 외 프레임 무제한 누적(`session.py:152-155`).

---

## 3. 이번 리뷰 패스에서 적용한 수정(3건)

- **Fix 1 — 타이핑 인디케이터 멈춤**: `LiveChatCard.tsx` `processing` 계산에서 마지막 사용자
  말풍선이 `error` 플래그면 처리 중으로 보지 않도록 제외.
- **Fix 2 — HITL 소유권 레이스 + runId 바인딩**: `open_hitl_channel`/`wait_hitl` 에 `owner`/`run_id`
  파라미터 추가(채널 오픈 시점 등록), 러너가 state 에 `owner`(=`str(user.id)`)/`run_id`(=`runId`)
  주입, 3개 state TypedDict 에 필드 추가, 소비 노드(chat_form/collect_rows/save/demo confirm)가
  전달, `set_hitl_owner` 는 이미 바인딩된 소유자를 덮어쓰지 않는 폴백으로 변경, `/runs/hitl` 이
  채널 바인딩 `run_id` 와 요청 `runId` 를 교차검증(불일치 시 403).
- **Fix 3 — expense_card 중복 도구호출 가드**: card_collect 의 `_sig`/`seen_actions` 패턴을
  `chat_form.py` 도구 루프에 포팅(가드 대상 `{set_expense, read_transactions, fill_search,
  fill_dropdown, fill_text}`).

---

## 4. 이번 패스 범위 밖(후속 과제)

아래는 고위험 구조 변경이라 별도 전용 작업으로 다루는 것이 안전하다.

- **LangGraph 체크포인터/`interrupt()` 도입** — state 직렬화 불가(page/browser/Queue) 제약을 먼저
  풀어야 하며, HITL 을 네이티브 인터럽트로 재설계하는 큰 변경.
- **세션 버퍼 상한(capping)** — 재생 정합성(커서)과 메모리 사이 트레이드오프 설계 필요.
- **세마포어 재설계** — HITL 대기 중 슬롯 반납/재획득은 런 수명·브라우저 소유권 모델 전반을 건드림.
- **다중 워커 대비 상태 영속화** — 인프로세스 큐/세션/세마포어를 외부 저장소로 옮기는 아키텍처 변경.
