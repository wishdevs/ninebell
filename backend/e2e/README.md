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
2. `/agents/corporate-card` 이동 → **실행** 버튼 클릭.
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


## 결의서입력 그룹 실저장 사이클 — **제품 경로**(2026-08-03 전환)

**우리 시스템(대시보드 UI)에서 작성하고 ERP 에서 삭제**한다. 종전에는 스크립트가
`build_*_graph()` 를 직접 `ainvoke` 해서 ERP 에서 작성하고 ERP 에서 지웠고, 그래서 프론트
pre-run 폼 → `runs.py` collect 의 서버 권위 params 주입(`department`·`cost_type`·`fuel_*`) →
러너(세마포어·SSE·스크린캐스트·시간예산 워치독) → `agent_runs` 기록이 **전부 미검증**이었다.
지금은 법인카드 `e2e_smoke.py` 와 같은 2페이즈다(공통 모듈 `product_cycle.py`).

- **phase1(제품)** — 대시보드(:3101) 로그인 → `/agents/<id>` → **실행 전 입력 폼을 실제 위젯으로
  조작**(행 추가·유형 셀렉트·달력 팝오버·거래처/프로젝트 콤보박스 검색) → 실행 → 종료 대기 →
  `agent_runs` 행 생성 확인(**제품 경로를 탔다는 증거**).
  ⚠ params 를 코드로 주입하지 않는다. 서버 권위 키는 `runs.py` 가 채운다.
- **phase2(ERP)** — 별도 브라우저로 ERP 직접 로그인 → GLDDOC00300 → 결의구분 필터 → 조회 →
  **3중 가드** → 상세 대조(행수·행별 금액·거래처·적요·합계) → F6 → 잔존 0.

결의구분별로 스크립트가 하나씩 있고, 삭제 가드레일이 **자기 결의구분만** 대상으로 삼는다.
단, 제품 경로는 같은 계정의 러너 슬롯·ERP 세션을 공유하므로 **하나씩 순차로** 돌린다.

| 스크립트 | 대시보드 에이전트 | 결의구분 | 사이클 수 env | 리포트 |
|---|---|---|---|---|
| `trip_smoke_cycle.py` | `/agents/trip-domestic` | 출장(국내·자차) 53 | `TRIP_SMOKE_CYCLES` | `artifacts/trip_product_cycle.json` |
| `trip_overseas_smoke_cycle.py` | `/agents/trip-overseas` | 출장(해외·정산서) 54 | `TRIP_OVERSEAS_SMOKE_CYCLES` | `artifacts/trip_overseas_product_cycle.json` |
| `gyeongjo_smoke_cycle.py` | `/agents/family-event` | 경조금신청서 55 | `GYEONGJO_SMOKE_CYCLES` | `artifacts/gyeongjo_product_cycle.json` |
| `hakjagum_smoke_cycle.py` | `/agents/scholarship` | 학자금신청서 56 | `HAKJAGUM_SMOKE_CYCLES` | `artifacts/hakjagum_product_cycle.json` |

공통 env: `E2E_FRONTEND`(기본 `http://localhost:3101`) · `E2E_USERID` · `E2E_PASSWORD` ·
`E2E_HEADLESS=0` 이면 브라우저 창 표시 · `E2E_RUN_TIMEOUT_S`(종료 대기 상한, 기본 600).

### 해외출장 — `trip_overseas_smoke_cycle.py`

```bash
cd backend
TRIP_OVERSEAS_SMOKE_CYCLES=1 .venv/bin/python e2e/trip_overseas_smoke_cycle.py   # 단발 검증(기본 1)
TRIP_OVERSEAS_SMOKE_CYCLES=10 .venv/bin/python e2e/trip_overseas_smoke_cycle.py  # 10사이클
```

국내(`trip_smoke_cycle.py`) 포팅 + 해외 델타 검증. 사이클마다 폼에 1~3행을 넣어 저장한 뒤
아래를 대조하고, **여기에 더해** `agent_runs` 기록(제품 경로 증거)·DB 최종 상태 `succeeded`·
삭제 잔존 0 까지 전부 맞아야 PASS 다.

- `amount_match` — 입력 공급가액이 detail `SPPRC_AMT2` 로 **행 순서까지** 그대로 저장(해외는 국내
  유류비 같은 금액 계산 규칙이 없어, 불일치는 곧 채움 회귀다).
- `rows_clean` — detail 행수 = 입력 행수. 해외 정산서(54)에는 **부가선택에 상대계정거래처 항목이
  없어** `register_counter_partner` 가 스킵되고, 그 스텝의 부작용인 **스트레이 빈 행이 생기지 않는다**.
- `partner_match` — 거래처가 전 행 작성자 본인(`PARTNER_NM`).
- `note_match` — 적요(`NOTE_DC`) 자유 입력이 행별로 그대로 저장.
- `total_match` — 마스터 `DETAIL_SUM_AMT` = 전 행 합계.

회계일자는 계산서일(`START_DT`) 최댓값으로 파생되므로, 한 사이클의 행 날짜는 **같은 달**로
클램프한다(월이 걸치는 건은 결의서를 나눠 상신해야 한다 — `app/agents/trip_overseas/PROCESS.md`).

안전 수칙은 형제 스크립트와 동일하다. **삭제까지가 한 사이클**(잔존 0 확인 전 다음 사이클 금지),
**상신 절대 금지**(F7·F6 만), 삭제 가드레일 = 결의자 = 로그인 계정 + 결의구분 54 + 미결(전표번호
공백). 하나라도 어긋나면 삭제를 중단하고 덤프를 남긴다. **cycle 1 안전 게이트**로 첫 사이클이
PASS 가 아니면 나머지 사이클을 돌리지 않는다(회귀 상태에서 전표 양산 방지). 전체 진단은
`artifacts/trip_overseas_product_cycle.json` 에 남는다.

---

# 회계전표(전표조회승인 GLDDOC00700) 계열 스모크

위(결의서입력 계열)와 **아키타입이 다르다.** 이 그룹은 전표를 **만들지 않는다** — 이미 있는
전표를 조회하고 결재창을 열어 확인만 한다.

## ⚠ 이 그룹에는 삭제 단계가 없다

결의서입력 계열 스모크는 `실저장(F7) → 검증 → 삭제(F6)` 사이클을 돈다. 회계전표 계열은
**그 사이클을 흉내내면 안 된다.**

- **ERP 에 회계전표를 삭제하는 로직 자체가 없다.** 만들면 되돌릴 수단이 없다.
- 그래서 이 계열 에이전트는 `app/agents/ACTIONS.md` 기준 **`확정`(저장·승인)·`발신` 등급 동사를
  한 줄도 쓰지 않는다.** 미지급금 법인카드의 `FLOW.md` 는 확정이 0줄이고 `금지` 가 둘이다 —
  `[상신]`(가상 상신 로그만)과 `[문서반영]`(참조문서 '확인' 미클릭).
- 스모크의 역할은 **그 게이트가 실제로 닫힌 채 종단 완주하는지 관찰**하는 것이다. 스모크가
  게이트를 여는 인자를 넘기거나 그래프를 직접 조립하지 않는다 — 등록된 팩토리를 그대로 태운다.

**되돌릴 수 없는 부작용: 0건.** 유일한 잔여물은 결재창을 여는 것만으로 생기는
**EAP 임시문서(draft)** 이며(각 PROCESS.md 기지 이슈, 사용자 승인 범위), draft 수 = **결제창을
연 횟수**다(묶음 결재는 1회에 N건 처리 → 1 draft). 실제 상신은 사용자가 전자결재에서 직접 한다.

### draft 를 어떻게 최소화하는가 — 제품 폼엔 `max_rows` 노브가 없다

3종은 결의서입력 4종과 같이 **제품 경로**(대시보드 폼 → 실행)로 돈다(2026-08-03 전환). 그런데
제품 폼 `VoucherPreRunForm` 이 받는 값은 **회계일 기간 하나뿐**이고 서버 기본값은
`max_rows=None`(=조회된 전 건 순회, `voucher_receivable/params.py:30`)이다 — 즉 제품 경로에는
건수를 묶는 노브 자체가 없고, **기간이 유일한 레버**다. 기본 기간(당월)으로 돌리면 실측
2026-07 매출 **181건**이 그대로 대상이 된다.

그래서 각 스모크는 phase0 에서 **읽기 전용 ERP 조회**로 기간을 이분 탐색해 대상이
1~`VOUCHER_MAX_TARGET_ROWS`(기본 3)건인 부분기간을 **실측으로** 찾아 폼에 넣는다. phase0 은
조회(F2)만 하고 결재 버튼을 누르지 않으므로 draft 를 1건도 만들지 않는다. 못 찾으면 실행하지
않고 중단한다.

> ⚠ 날짜 필드를 추정해 그룹핑하지 않는다. 결과 그리드의 `ACTG_DT` 도 `WRT_DT` 도 회계일 필터
> 대상이 아니다(2026-08-03 실측: 20260701~20260731 결과에 `ACTG_DT=20260630` 행이 섞였고,
> `WRT_DT` 로 좁힌 하루는 실제 조회 0건). 필드를 짚어 그룹핑하면 "하루로 좁혔다"고 **믿고**
> 대량 처리하게 된다 — 실제로 1건인 줄 알고 11건을 처리한 회귀가 났다.

## 3종

| 스크립트 | 에이전트 | 전표유형 | 특징 |
|---|---|---|---|
| `voucher_receivable_smoke.py` | `voucher-by-type` | 국내매출·해외매출(폼 선택) | **배치 결재**(묶음 1개 = 결제창 1개) · EAP 자식창 캡처 · D7 정합성 |
| `voucher_payable_smoke.py` | `voucher-by-type` | 내수구매(폼 선택) | 위 하네스 재사용(동일 배치 백본) |
| `voucher_card_smoke.py` | `voucher-card` | 일반 | 위 하네스 재사용 + **카드 3대 델타**(아래) |

> 병합(2026-08-20): 외상매출금/외상매입금 에이전트는 '유형별 전표조회 승인'(`voucher-by-type`)
> 하나로 통합됐다 — 전표유형은 실행 전 폼의 다중 선택(`params.voucher.docu_types`), 메뉴(MENU_NM)
> 필터는 `params.voucher.menu_filters`. 두 스모크는 각 유형 선택 시나리오로 남긴다(폼 셀렉터
> 확정 후 fill 에 전표유형 선택 스텝 추가 — 각 파일 TODO 참조).

공통 골격은 `voucher_product.py`(phase0 기간 선별 · SSE 탭 · `agent_runs.logs` 파서)이고,
제품 UI 조작(로그인 → 폼 → 실행 → 종료 판정 → `agent_runs` 확인)은 결의서입력 4종과 같은
`product_cycle.run_product()` 를 공유한다.

```bash
cd backend
.venv/bin/python e2e/voucher_receivable_smoke.py
.venv/bin/python e2e/voucher_payable_smoke.py
.venv/bin/python e2e/voucher_card_smoke.py
```

셋 다 **제품 UI(:3101)** 에서 실행하므로 프론트 폼 → `runs.py` collect → 세션/SSE →
러너 → `agent_runs` 기록까지 전 구간을 탄다. 그래프를 직접 조립하지 않는다.

### 관측 경로 — 프레임을 직접 못 받는 대신 두 갈래로 복원한다

종전 하네스는 `run_workflow` 가 yield 하는 프레임을 파이썬이 직접 받아 검증했다. 제품 경로에서는
프레임이 러너 → 세션 → SSE → 브라우저로 흐르므로 직접 받을 수 없다.

| 무엇을 보는가 | 종전 | 지금 |
|---|---|---|
| 로그 메시지(D7·가상 상신·rowcount·전표유형·참조문서·커버리지·제외회계) | `log` 프레임 | **`agent_runs.logs`** — 세션이 종료 시 전량 영속(`app/live/session.py:167`) |
| 단계 상태/순서 | `step` 프레임 | 같은 `agent_runs.logs`(step·status·ms 보존) |
| 최종 결과 · 오류 | `result`/`error` 프레임 | `agent_runs.status`/`result` + SSE 탭 |
| 자식창(EAP) 스크린샷 · 닫힘 전이 | `screenshot`/`closed` 프레임 | **SSE 탭** — `window.fetch` 래핑 + `body.tee()` 로 제품 스트림을 **복제만** 해서 센다(소비·변형 없음) |

SSE 탭은 종전보다 강한 증거다 — 프레임이 러너에서 났다는 것뿐 아니라 **브라우저까지 실제로
도달했다**는 것까지 확인된다. 다만 세션 stream 은 스크린샷을 **창별 최신 1장으로 합쳐** 보내므로
(`session.py:238`) 자식 스크린샷 **개수**는 러너 방출수와 다르다 — `>=1`(도달 여부)만 유효하고
개수 비교는 의미가 없다. 자식창 **닫힘 전이**는 커서 버퍼라 유실 없이 전량 도달하므로, 결제창
개봉 횟수와의 일치 검증은 그대로 유지된다.

> ⚠ 셋은 같은 ERP 계정을 쓴다. **동시 실행 금지** — 세션이 서로를 밀어낸다.

## 미지급금 법인카드 — `voucher_card_smoke.py`

형제 하네스를 그대로 재사용하고 카드 델타 3가지를 추가로 파싱·검증한다.

| Δ | 내용 | 근거 |
|---|---|---|
| Δ1 | 전표유형 = **일반**(SYSDEF_CD=11) — 공유 `set_query` 재사용 | PROCESS.md D1 |
| Δ2 | **결의서조회승인(GLDDOC00400) 2nd 메뉴 탭** 진입 → 결의부서 전체·결의자 비움·회계일·**결의구분=카드** → 일괄 조회 → `ABDOCU_NO→GWDOCU_NO(결재번호)` 맵 수집 → 전표조회승인 탭 복귀 | 프로브 `voucher_card_discover_probe.py` / `voucher_card_collect_filter_probe.py` |
| Δ3 | 결제창(EAP) 안 **참조문서 선택** — 문서번호=이 행 `GWDOCU_NO` 조회 → 1건이면 선택 → 아래(↓) 버튼으로 '선택된 문서 목록' 이동. **확인 미클릭** | 프로브 `voucher_card_refdoc_dom_probe.py` / `voucher_card_refdoc_verify_probe.py` |

검증 항목(무엇이 맞아야 성공인가):

- 공통 — 파라미터 로그가 '실제 상신·참조문서 확인 없음' 선언 / 전표유형 **일반** 세팅 확인 /
  조회 rowcount 관측 / `collect_payments` 정상 종료 / error 프레임 0 / 결과 문구가 '가상만' 선언 /
  **참조문서 '확인' 클릭 흔적 0** / D7 확정 불일치 0.
- 결재 대상 ≥1 — 자식창 스크린샷·닫힘 프레임 방출 / 연 만큼만 닫힘(3단 창 정리) /
  처리 건수 = 선별된 결재 대상 건수 / 전표번호 중복 없음 / `max_rows` 준수 /
  **결재번호 맵 커버리지 ≥1**(2026-07-27 '맵 4건·커버 0건' 회귀 가드) /
  결제창을 연 행마다 참조문서 종결 로그 정확히 1건 / D7 체크행수 확인.
- 결재 대상 0건 — 자식창을 하나도 열지 않았고 커버리지 0% 경고가 없다.
  (조회 0건, 전 행 결의서번호 없음(직접 전표) 둘 다 **정상 경로**다.)

참조문서 검색 **0건도 현재 정상**이다 — 테스트 계정의 시스템 승인 이슈이며 `FLOW.md`
'알려진 제약'이 그 상태를 정상 경로로 흡수한다. 스모크가 보는 것은 "첨부에 성공했는가"가 아니라
"훅이 행마다 도달해 판정까지 갔는가"다.

env:

```bash
E2E_USERID / E2E_PASSWORD            # 자격증명(기본 이트라이브2/1111)
E2E_HEADLESS=0                       # 헤드풀
E2E_DELAY_SCALE=0.4                  # 대기 배율(등록 워크플로우와 동일)
VOUCHER_MAX_TARGET_ROWS=3            # phase0 기간 선별 상한(= 최대 EAP draft 수)
VOUCHER_SCAN_MONTHS=3                # 대상이 있는 달을 찾을 때 역방향 탐색 개월
VOUCHER_QUERY_BUDGET=16              # phase0 이분 탐색 조회 횟수 상한
```

아티팩트: `artifacts/voucher_{receivable,payable,card}_product{,_parent,_child}.png` ·
`voucher_*_product.json`(기간 선별 이력 · 어설션 · 관측치 · `agent_runs.logs` 원문 포함).
