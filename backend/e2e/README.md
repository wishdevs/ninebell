# E2E 스모크 테스트 — 결의서입력-카드 에이전트

실제 제품 UI(대시보드 :3101)로 **card-collect 에이전트를 끝까지 실행**하고, 저장된 전표를
ERP(옴니솔)에서 **정리(삭제)**하는 헤드풀(브라우저 보임) Playwright 스모크 테스트다.
백엔드 자동화 코드를 바꾼 뒤 "실행 → 저장 확인 → 삭제 → 수정 → 반복" 루프를 짧게 돌리기 위한
기반 스크립트.

> ⚠ **실동작 테스트다.** Phase 1 은 옴니솔에 **실제 전표(결의서)를 저장**하고, Phase 2 가 그것을
> 삭제한다. 테스트 계정(`이트라이브2`)의 **미결 카드 결의서만** 안전가드로 삭제한다.

## 사전 조건

- 프론트엔드 `:3101`, 백엔드 `:8010`, Postgres `:5434` 실행 중(루트 README 참조).
- 백엔드 venv + Playwright chromium 설치(`backend/README.md`).
- 테스트 계정 자격증명(기본 `이트라이브2`/`1111`). env 로 override 가능.

## 실행

```bash
cd backend
.venv/bin/python e2e/e2e_smoke.py both     # 기본: 실행 + 삭제
.venv/bin/python e2e/e2e_smoke.py run      # 대시보드 실행·저장까지만
.venv/bin/python e2e/e2e_smoke.py delete   # ERP 에서 우리 미결 카드 결의서 삭제만
```

브라우저가 화면에 보이게(`headless=False`, `slow_mo`) 뜬다. 스크린샷·상태는
`backend/e2e/artifacts/`(gitignore)에 저장된다. env override:

```bash
E2E_FRONTEND=http://localhost:3101 E2E_USERID=이트라이브2 E2E_PASSWORD=1111 \
  .venv/bin/python e2e/e2e_smoke.py both
```

## Phase 1 — 대시보드 에이전트 실행 (`phase1()`)

제품 UI(:3101)를 그대로 몬다.

1. `http://localhost:3101` → 로그인 폼(`#userid`/`#password`) 채우고 **로그인**.
2. `/agents/card-chat` 이동 → **실행** 버튼 클릭.
3. 사용자 개입(그리드) 카드가 뜰 때까지 대기(백엔드가 ERP 를 헤드리스로 구동, ~30–90s).
4. **입력 완료** 클릭(프리필된 값 그대로 제출 — "그냥 완료").
5. 종료 상태(다시 실행 버튼) 대기 → 결과 텍스트 파싱.
   - 성공 판정: 결과에 `처리 완료` 포함. `입력·저장`=실저장 / `반영 0건`=미저장.
   - 그라운드 트루스로 `agent_runs` 최신 행도 확인.

반환 dict: `{logged_in, run_started, grid_appeared, submit_clicked, reached_terminal,
result_text, saved, zero_effect, db_check, screenshot, error}`.

**입력 완료가 무저장(반영 0건)이 되는 경우**: 프리필된 예산단위가 없으면(기본지정/학습/비용구분
기본이 모두 비어 있으면) 유효 행이 없어 저장이 0건이 된다. 실저장 스모크를 원하면 관리 화면에서
예산단위 **기본지정**을 두거나 학습 데이터가 쌓인 상태로 돌린다.

## Phase 2 — ERP 검증 + 삭제 (`phase2()`)

별도 컨텍스트로 옴니솔에 직접 로그인해 정리한다(백엔드 로그인 플로우 `ensure_logged_in` 재사용).

1. `https://erp.ninebell.co.kr/FI/GLDDOC00300` 진입.
2. 결의구분 = **카드**(`#s_abdocu_fg_cd` → text '카드', Kendo 드롭다운 JS).
3. **조회**(`button.main-button.lookup`, F2 폴백) → 마스터 그리드(`.dews-ui-grid[0]`) 로드.
4. **삭제 안전가드**(`_row_is_ours`): 그리드 전 행이
   **결의자명 = 로그인 사용자 + 결의구분 = 카드(52) + 미결(전표번호 없음)** 일 때만 진행.
   하나라도 다르면 **중단(ABORT)** 하고 덤프 보고(사람 확인).
   - ⚠ 날짜 문자열 매칭은 쓰지 않는다 — 그리드가 UTC datetime 저장 + 회계일이 기간월 말일이라
     로컬 '오늘'과 안 맞아 오판한다(2026-07-04 실측 후 신원 판정으로 교체).
5. 안전하면 마스터 행 선택 → **삭제(F6/삭제 버튼)** → 확인창(`선택된 미결결의서를 삭제…` → 예)
   → **재조회 → 0건** 확인. `post_delete_count > 0` 이면 실패로 크게 보고.

반환 dict: `{rows, all_ours, deleted, post_delete_count, error, screenshots}`.

## 1사이클 래퍼 — `smoke_cycle.py`

위 5단계(모니터→실행→모니터확인→완료판정→삭제)를 **한 명령**으로 돌리고, 6단계(최적화)를 위해
**단계별 ms·경고·에러**를 구조화해 출력한다.

```bash
cd backend
.venv/bin/python e2e/smoke_cycle.py            # 실행 + (저장됐으면) 삭제 + 리포트
.venv/bin/python e2e/smoke_cycle.py --no-delete # 저장분 남겨두고 리포트만(수동 정리 필요)
```

동작:
1. 실행 전 최신 `agent_runs` id 를 마커로 기록('백엔드 모니터링' 켜기 = 새 런 식별).
2. `phase1()` — 대시보드로 에이전트 실행·저장.
3. 새 런의 `agent_runs.logs`(러너가 종료 시 DB 저장)를 읽어 **단계 running→done ts** 로 단계별
   소요와 warn/error 를 파싱(별도 모니터 프로세스 불필요).
4. 완료·저장 판정.
5. 저장됐으면 `phase2()` 로 삭제.
6. 리포트 출력(느린 순 단계 막대그래프 + 경고/에러) + `artifacts/smoke_cycle.json` 저장.

리포트 예(실측 2026-07-04, 40건 실저장):

```
단계별 소요(총 168.2s) — 느린 순:
  apply_doc         82718ms   ← 과세 40건 문서 반영(카드팝업 적용·모달)
  collect_rows      52361ms   ← 그리드 40행 채움(그룹 피커·일괄적용)
  save_final        14681ms   ← F7 + 저장 모달
  set_gubun/login    ~4000ms
  ...
Phase2(삭제): deleted=True post_delete_count=0
```

이 리포트가 **다음 최적화 대상**(apply_doc/collect_rows/save_final)을 바로 짚어준다.
소스를 고친 뒤 다시 `smoke_cycle.py` 를 돌려 델타를 비교하면 6단계 루프가 짧아진다.
