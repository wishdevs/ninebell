# 외상매출금 전표 결재 — 프로세스 정의 (voucher-receivable)

> 회계전표 그룹 에이전트. **결의서입력(GLDDOC00300)이 아니라** 총계정원장 > 전표관리 >
> **전표조회승인** 화면을 다룬다(신규 화면·신규 아키타입 — 문서 생성이 아니라 조회+결재).
> 상태: **v1 — 헤드리스 라이브 프로브 완료(2026-07-20), 배치(3건) 라이브 스모크 그린(2026-07-21).
> 진입·조회 8필드·결과그리드·결제창(별도 팝업 Page)·취소 비영속·배치순회(D7) ✅.
> 미해소: EAP draft 잔존·보관버튼 동작(❓).**
> 형제(같은 화면, 전표유형만 다름 — 향후): 외상매입금(`voucher-trade-payable`),
> 미지급금 법인카드(`voucher-card-payable`).

## 개요

전표조회승인 화면에서 **미결·전자결재저장 상태의 매출전표(국내/해외)**를 조회한 뒤,
목록을 한 건씩 돌며 **결제(결재) 창을 열어** 상신 대기 상태를 확인한다. 실제 상신은
**하지 않는다** — 상신은 최종 단계에서 일괄로 사람이 처리할 예정이므로, 이 에이전트는
결제창이 뜨면 **"가상 상신" 로그만 남기고 창을 닫고 다음 건으로 이동**한다.

- 입력 방식: 실행 전 폼(조회 조건은 대부분 고정, 회계일만 월 선택). HITL 개입 없음(무개입 완주).
- 완주 조건: 조회된 전 건에 대해 (선택→결제창 열기→가상 상신 로그→닫기) 루프 완료.
- **영속 없음**: F7 저장·F6 삭제·실제 상신 모두 없음. 결제창을 열었다가 **취소로 닫는다**
  (취소가 비영속임을 프로브로 확정해야 함 — 아래 ❓).

## ⚠ 비가역 / 절대 안전

- **실제 상신(전자결재 상신) 절대 금지.** 결제창(EAP) 상단 우측 **상신**(파란 체크, ~922,30)은
  누르지 않는다. 대신 가상 상신 메시지를 로깅한 뒤 `child.close()`로 창을 닫는다.
- **보관 버튼(~860,30)도 누르지 않는다** — 실제 저장/제출 여부 미확정(❓). 안전하게 미클릭 유지.
- 결제창 열기→닫기(`close()`)는 FI 전표에 **비영속 확정 ✅**(프로브 3회: DOCU_NO=FI2026070100000010
  이 미결/저장 불변). 이 화면엔 F7 저장·F6 삭제 자체가 없다.
- ⚠ **EAP draft 잔존 이슈(미해소)**: 결제창을 **여는 것만으로** 전자결재(EAP, `uc.ninebell.co.kr`)
  시스템에 새 임시문서(docID 1013899→1013905→1013906 매 오픈 증가)가 생기는 것으로 관찰됨. FI
  전표는 불변이나 EAP 임시/진행문서함에 draft 가 쌓일 수 있다. **배치 순회 전 도메인 담당자
  확인 필요** — 문제면 (a) 순회 안 함, (b) 열지 않고 목록만, (c) EAP draft 정리 로직 추가 중 택일.
- 테스트는 격리 계정(이트라이브2/1111)에서만.
- ⚠ **처리 범위: 전체 진행(사용자 결정 2026-07-21)** — max_rows 게이트/`allow_batch` 제거, 기본이
  조회된 **전 건 순회**다(params.max_rows=None). 즉 한 실행이 대상 건수만큼 EAP draft 를 만든다
  (예 31건이면 31 draft). 실제 상신은 여전히 안 함(가상 상신). EAP draft 잔존 처리(위 이슈)는
  담당자 확인 대기 상태로 남는다 — 노출·실행은 사용자 지시로 열려 있다.

## 확정된 업무 결정(사용자, 2026-07-20)

- **D1 화면**: 총계정원장 → 전표관리 → **전표조회승인**. menu_id **`GLDDOC00700`** /
  deeplink **`/FI/GLDDOC00700`**(재무회계 모듈) — ✅ 2026-07-20 프로브. `nbkit/omnisol/menu_schemas.py`
  `VOUCHER_RECEIVABLE` 등록됨. 사용자유형 **회계**. 진입판정 `.dews-ui-grid` ≥2(기존 로직 재사용). ✅
- **D2 조회 조건(고정)** — ✅ 2026-07-20 프로브. 8필드 셀렉터·세팅방식:
  - 회계단위: codepicker `#s_pc_cd`. 기본값 **"(주)나인벨"** 이미 선택 → **변경 불필요**. ✅
  - 작성부서 **전체**: multicodepicker `#s_wdept_cd` 돋보기→팝업 RealGrid `checkAll()`→적용(46건). ✅
  - 회계일 **당월**: periodpicker `#s_period`, 앱 API **`dewsControl.setMonth()`**(이번달 1일~말일 자동).
    ⚠ `YYYYMMDD` 타이핑 아님(GLDDOC00300 규칙과 다름). ✅
  - 작성자 **비움**: multicodepicker `#s_wrt_emp_no`, 앱 API **`dewsControl.clear()`**로 기본선택 제거. ✅
  - 역분개여부 **전체**: native kendo `select#s_revjrnz_yn` 기본값(value="") = 전체 → **변경 불필요**. ✅
  - 전표상태 **미결**: native kendo `select#s_docu_st_cd`, 기존 `KENDO_SET_DROPDOWN_BY_TEXT_JS`
    (text='미결', value="2") 재사용. ✅
  - 전자결재상태 **저장**: multicodepicker `#s_gwaprvlst_cd`(MA/P01300) 돋보기→팝업 `SYSDEF_NM==='저장'`
    checkRow→적용(code=1). ✅
  - 전표유형 **국내매출+해외매출**: multicodepicker `#s_docu_cd`(MA/P00620, **optional-area**).
    ⚠ 팝업 RealGrid 컬럼은 **`SYSDEF_NM`/`SYSDEF_CD`**(전자결재상태 팝업과 동일 범용 코드테이블,
    n=62) — 2026-07-20 프로브의 `DOCU_NM`/`DOCU_CD` 기록은 오기(라이브 스모크로 정정). checkRow
    는 `SYSDEF_NM=='국내매출'/'해외매출'`. **optional-area 라 열기 직전 `ensure_field_visible`
    (결과검증형: 보이는 `.dews-condition-panel-expand-button`을 좌→우로 하나씩, 전표유형이 보일
    때까지 시도, 이미 보이면 미클릭)로 가시성 보장** — 고정 1회 expand 는 다른 필드 조작 중 패널
    재접힘 레이스로 불안정. ✅ 2026-07-21 라이브 스모크
  - (전표번호 `#s_docu_no`: 8필드 아님, 공란 유지)
- **D3 조회 실행**: 기존 `selectors.BTN_LOOKUP`("button.main-button.lookup", F2) 재사용. 결과
  마스터그리드(index 0) 28컬럼 — 핵심: **DOCU_NO**·DOCU_ST_NM·GWAPRVLST_NM·DOCU_NM·ACTG_NO·
  DOCU_AM_SUM·WRT_DEPT_NM. 성공 = rowcount ≥ 0(0이면 처리대상 없음 → 정상완료). 실측 31행. ✅
- **D4 행 선택**: **체크박스 필요** — `grid.checkRow(idx, true)`(`__UUID` 기반). `setCurrent`만으론
  결재 대상으로 인식 안 됨. ✅
- **D5 결제창(자식창)**: 결재 버튼 **`button.main-button.approval`**(innerText "결재", ~1317,72) →
  **별도 팝업 브라우저 창**(`window.open`, cross-origin `uc.ninebell.co.kr` EAP/전자결재, SSO 경유) =
  **진짜 새 Playwright Page**(모달/iframe 아님). ✅ 감지: 결재 클릭 **전에** `context.on("page")`
  리스너 등록 → 새 Page 캡처. 렌더완료: 고정대기 금지 → 상단 버튼(미리보기/보관/상신) 텍스트가 뜰
  때까지 1s 폴링(상한 25s, SSO 리다이렉트+SPA 마운트 1~12s 편차). ✅
- **D6 가상 상신**: 결제창에서 **상신·보관 미클릭**. "가상 상신: 전표 {DOCU_NO}" 로그만 남기고
  **`child.close()`** → 다음 행. 상신(~922,30)·보관(~860,30) = ⚠ 미클릭. 창닫기는 FI전표 비영속 ✅.
  단 EAP draft 잔존 이슈(위 안전섹션) 인지.
- **D7 순서/재개**: 인덱스 0..n-1 진행. ✅ 2026-07-21 배치 3건 라이브 스모크로 확정.
  - **행/팝업 정합성 하드체크 구현**(`nodes/approvals.py:loop_approvals`): (1) 결제 열기 직전
    체크된 행이 정확히 1개인지(`steps.checked_row_indexes`), (2) 결제창에 표시된 전표번호가
    대상 행 DOCU_NO 와 확정적으로(매치 1개) 일치하는지(`steps.read_child_docu_no`, 정규식
    `\bFI\d{8,}\b` 리프텍스트 스캔) — 확정 불일치 시 배치 즉시 중단(모호 0/2개+ 는 경고만).
  - ⚠ **근본원인(2번째 이상 반복에서 결제창 미출현)**: 도메인전문가 확정 — "결제 팝업을
    닫으면 본창에서 별도 처리가 진행되고 로딩이 걸린다. 그 로딩이 끝나기 전에 다음 행을
    체크하고 결제를 다시 호출해서 안 되는 것." 읽기전용 진단(`e2e/voucher_receivable_parent_loading_diag.py`)
    으로 재현: `close_child()` 직후 `.dews-loading-container`(자식: `.dews-loading-img`/
    `.dews-loading-text`) 스피너가 뜬다(관측 ~0~0.6s). 별도 진단(`e2e/voucher_receivable_open_approval_diag.py`)
    으로 `check_row`(setCurrent)가 트리거하는 `.dews-loading-bg` 도 결재 버튼 클릭을 가로챈다는
    것도 확인(elementFromPoint 실측). **수정**: `steps.settle_parent_after_child_close`(close 직후
    호출)가 `child.is_closed()` 확인 → **로딩 인디케이터 소거 대기**(`wait_loading_overlay_gone`,
    `.dews-loading-bg`/`.dews-loading-container`/`.k-loading-mask`/`.k-loading`/`.dews-loading`
    전부 체크) → `bring_to_front()` → 결재버튼 rect 재가시 확인 순서로 정착. `steps.open_approval`
    도 매 시도(기본 2회, 결과검증형)마다 로딩 소거 대기 + rect **fresh 재평가**(캐시 금지) 후
    클릭. ✅ 3건 배치 3/3 성공(재발 없음).

## 신규 프론트 요구 — 라이브뷰 부모/자식 창 탭

라이브 브라우저 화면 **우측 상단**에 부모창/자식창을 나타내는 **탭(버튼)**을 두고 번갈아 볼 수
있게 한다. **결제창이 뜨면(결제 진행 중) 자식창 탭을 자동 활성화**해 결제창을 보여준다.
자식창이 닫히면 부모창으로 복귀(활성 탭 원복).

### 라이브 프레임 아키텍처 실측(탐색 2026-07-20)
현재 파이프라인은 **단일 페이지** 캡처다 — `app/live/runner.py`가 헤드리스 Chromium 페이지 1개를
열고, `app/live/screencast.py:screencast_pump(page, events)`가 그 페이지에 CDP 세션 1개를 바인딩.
프레임은 `{"screenshot": "data:image/jpeg;base64,..."}`(events.py)로 **창 식별자 없음**. 기존
"팝업"은 전부 같은 페이지의 Kendo `.k-window` DOM 오버레이(이미 스크린샷에 포함). **실제 새
브라우저 창(window.open→별도 Playwright Page)을 다루는 코드는 전무**(`context.on("page")` 0건).

→ 결제창이 **(B) 진짜 새 창**이면(사용자 표현 "새 시스템 윈도우" = 유력) 신규 플러밍 필요:
1. `runner.py`: `context.on("page")`로 새 페이지 감지 + 페이지별 `screencast_pump` 기동(창 role/id 태깅).
2. 프레임 프로토콜: `{"screenshot", "window": "parent"|"child", "windowId"}` 키 추가
   (`app/live/events.py`, `nbkit/patterns/__init__.py:emit_shot`, `src/lib/live/types.ts`).
3. `app/live/session.py`: `latest_shot` 단일 슬롯 → 창별 맵(부모/자식 덮어쓰기 방지).
4. 프론트 `use-live-run.ts` 리듀서: `screenshot` 단일값 → `{parent, child}` + `activeWindow`
   (자식 프레임 첫 등장 시 자동 전환).
5. 프론트 `live-browser-stage.tsx`: 브라우저 크롬바(우측 상단 StatusBadge 옆)에 탭 토글 추가.
→ 결제창이 **(A) `.k-window` 모달**이면 캡처 변경 불필요, `{"window": ...}` 신호만 추가하면 됨.
**A/B 판정은 프로버 결과로 확정**(❓).

## 진입/신규 스텝(초안 — 프로브 전)

| 스텝 | 내용 | 성공 | 실패 | 검증 |
|---|---|---|---|---|
| login | 옴니솔 인증(공유 프리미티브) | 세션 확보 | 인증 실패 팝업 → 중단 | ✅(기존) |
| user_type | 사용자유형 '회계' 전환(공유) | 회계 모듈 접근 | — | ✅(기존) |
| menu_nav | 총계정원장>전표관리>전표조회승인 진입 | 조회 폼·그리드 표출 | 메뉴 없음/권한 | ❓ menu_id |
| set_query | 조회 조건 세팅(D2) | 전 필드 반영 | 필드 부재 | ❓ 각 필드 셀렉터·값 |
| run_query | 조회 버튼 | 결과 그리드 로딩 | 로딩 실패 | ❓ 버튼 좌표 |
| loop_row | 행 선택 | 행 활성 | — | ❓ 선택 방식 |
| open_pay | 결제 버튼 → 자식창 | 자식창 표출 | 창 안뜸 | ❓ 버튼·창유형 |
| virtual_submit | 가상 상신 로그 + 창 취소닫기 | 자식창 닫힘·부모 복귀 | 창 안닫힘 | ❓ 취소 방식·비영속 |

## 남은 작업

- [x] 결제창 유형 확정 = **별도 팝업 Page**(scenario B). ✅
- [x] menu_id/deeplink, 조회 8필드 셀렉터·세팅, 조회 버튼, 결과 그리드 컬럼·행선택(checkRow). ✅
- [x] 결제 버튼·결제창 상신/취소, 취소 FI전표 비영속 확인. ✅
- [x] 그래프 코드화(entry 재사용 + set_query + run_query + loop). ✅
- [x] 배치 3건 순차 스모크로 D7(행/팝업 정합성) 확정. ✅ 2026-07-21
- [ ] **사용자 확인 필요**: (1) EAP draft 잔존 허용/정리 여부 (2) '보관' 버튼 금지 여부.
- [ ] 프론트 부모/자식 창 탭(scenario B 멀티페이지 플러밍) — 별도 라이브뷰 아키텍처 참조.

## 검증 로그

- 2026-07-21 배치 라이브 스모크 `e2e/voucher_receivable_smoke.py`(delay_scale=0.4, max_rows=3
  기본값): **최종 그린** — processed=3, DOCU_NO 3건 모두 상이(FI2026070100000010/11/12), D7
  정합성 확인 3/3 ✅(모호·불일치 0), D7 체크행수 확인 3/3 ✅, 자식 스크린샷 401프레임(3세트)·
  닫힘 전이 3회, 최종 result 성공(에러 0). 과정에서 3회 실패 후 근본원인 2건 확정·수정
  (전표유형 팝업 필드 `DOCU_NM`→`SYSDEF_NM` 오기 정정, 반복 결제 오픈 시 로딩 미대기) — 상세는
  위 D2·D7 항목. `pytest -k voucher` 59 passed.
- 2026-07-20 프로브 `e2e/voucher_receivable_probe.py`(3회 그린, delay_scale=0.4): 진입(GLDDOC00700)·
  조회 8필드·결과그리드(31행)·행 checkRow·결재버튼·결제창(별도 팝업 Page, EAP cross-origin)·창닫기
  FI전표 비영속(3회 불변) 확정. 미해소: EAP draft 매 오픈 증가(1013899→1013905→1013906), '보관'
  동작 미확인, 배치 순회 미검증. 아티팩트 `e2e/artifacts/voucher_receivable_probe_*.{png,json}`.
- 2026-07-21 관리자 단건 라이브 스모크 `e2e/voucher_receivable_smoke.py`(run_workflow 종단, 4회:
  3실패→분류→수정→PASS): **EAP 결제창이 라이브 러너 부모/자식 캡처로 잡힘**(context.on("page")→
  자식 프레임 172개), 가상 상신 로그 "가상 상신: 전표 FI2026070100000010", 자식 닫힘 전이 1회,
  최종 성공(에러 0), EAP draft 1건(max_rows=1 게이트 유지), 상신/보관 미클릭. 근본원인 2건 수정:
  (1) 전표유형 팝업 필드명 `DOCU_NM`→`SYSDEF_NM`, (2) 패널 재접힘 레이스 → `ensure_field_visible`.
  아티팩트 `e2e/artifacts/voucher_receivable_smoke_{parent,child}.png`·`_frames.json`.
