# 법인카드 승인내역 정리 — 프로세스 정의 (card-collect)

> 결의서입력 문서 종류 중 **'카드'** 형태. 패밀리 인덱스: [../RESOLUTIONS.md](../RESOLUTIONS.md).
> 상태: **v4 — 부가세구분 2패스 + 최종 저장(F7) 1회, E2E 실저장 검증(2026-07-03)**. 아래 v3(그리드
> HITL, 2026-07-02)·v2(헤드리스 검증, 2026-07-01) 위에 구축.

## v4 — 부가세구분 2패스 + 저장 자동화 확정(2026-07-03)

**최종 그래프(15 노드, `graph.py` 와 1:1)** — `collect_rows` 그리드 1회 제출('입력 완료')이 저장까지의
유일한 승인이다(패스별 확인 HITL 없음):

```
login → user_type(회계) → menu_nav → set_gubun(카드) → add_row → set_acct_date(회계일)
→ open_evdn → select_evdn(01) → select_all_cards → set_period → query → collect_rows(그리드 HITL)
→ apply_doc(과세분 체크·적용) → switch_evdn(F3 새 행·증빙 02·재조회·행 매칭)
→ apply_pass2(불공분 자동 반영·적용) → save_final(F7 1회)
```

- **회계일 규칙(2026-07-04 추가)**: 마스터(결의서) 행의 회계일(`ACTG_DT`) = **수집 기간 월의 말일**
  (전월 수집=전월 말일, 당월 수집=당월 말일). 설정은 `ds.setValue(0,'ACTG_DT','YYYYMMDD')` —
  ⚠ 대시 형식('YYYY-MM-DD')은 오류 없이 셀을 **비운다**(프로브 실측 함정).

- **2패스 규칙**: VAT_TP 표시값 **'과세'만 법인카드(01)**, 나머지(빈칸·비과세)는 **법인카드(불공)(02)**.
  1차는 과세 행만 적용(저장 X) → **F3 새 행** 추가 후 증빙 02 로 전환·재조회 → 1차 입력값을 복합키
  `APRVL_NO|TRAN_DT|TRAN_AMT` 로 재조회 행에 매칭해 자동 반영 → **마지막에 F7 1회만** 저장.
- **승인취소(음수) 행 = 원 승인과 동일 계정 필수**(ERP 규칙). 승인번호별로 묶어 양쪽에 같은 예산단위를
  부여해야 저장이 통과한다(다르면 F7 시 `[오류] 승인 건 계정과 다릅니다` 거부).
- **소속 팀 비용구분 연결**: 실행 사용자의 팀 `cost_type`(판관비/제조원가) → 예산계정 `(판)`/`(제)`
  접두사를 우선 선택(내 부서 목록 정렬 + 기본 폴백 편향). runs.py 가 params 로 주입.

**라이브 검증에서 잡은 실전 버그(모두 회귀 테스트 추가)**

1. **팬텀 저장**: F7 후 `상세그리드에 필수 값이 입력되지 않은 항목이 있습니다` 인라인 **토스트**(모달 아님)로
   거부됐는데 결의번호 blank(미저장)임에도 `save_document` 가 ok 반환. `VALIDATION_TOAST_JS` 로
   실패 문구 스캔 → ok:False. 저장 중 `[오류]` 타이틀 모달도 실패로 처리.
2. **지연 '예산현황' 모달**: 카드팝업 '적용' 후 팝업이 먼저 닫히고 예산현황 모달이 늦게 떠 다음 단계를
   막던 문제 → 적용 후·전환 전·F7 전 3중 `dismiss_blocking_modals`(확인/예만).
3. **증빙 셀 0행 하드코딩**: `OPEN_EVDN_EDITOR_JS`/`DETAIL_EVDN_CELL_JS` 가 itemIndex 0 고정이라
   2패스에서 기존 과세 행의 증빙을 열어 불공(02)이 덮어쓰던 사고 → **마지막 행**(`getRowCount()-1`)
   기준으로 수정(F3 신규 행은 맨 아래 추가).
4. **필수값**: 저장하려면 각 행에 **프로젝트**가 채워져야 한다(빈칸이면 위 토스트로 거부).

**필드/저장 규칙 정정(v2 의 D1·D3 를 대체)**: 증빙유형은 01 고정이 아니라 **부가세구분에 따라 01/02
2패스**. 저장은 패스별이 아니라 **문서 단위 F7 마지막 1회**. 그리드 '입력 완료' = 저장 승인.

## v3 — Gemini 의도파악(ninebell-bak/expense_card.chat_form 패턴 이식)

- **배경**: v2 의 `collect_rows`는 정규식 파서(`_parse_instructions`/`_parse_fields`, `"1번 예산단위 …"`
  형식만 인식)였다. 사용자 요청으로 `ninebell-bak`(`api/app/erp/graph.py`)·기존
  `app/agents/expense_card/chat_form.py`와 동일한 **Gemini function-calling 대화** 패턴으로 교체.
- **공용화**: `app/agents/expense_card/gemini.py::gemini_chat_decide` 가 `tools`(함수선언 목록)를
  파라미터로 받도록 일반화(기존엔 `expense_card.tools.CHAT_TOOLS` 에 하드코딩). `chat_form.py`·
  `card_collect/nodes.py` 둘 다 이 함수를 재사용(중복 없음). `context` 파라미터명도
  "현재 모달 폼 스키마" 같은 expense_card 전용 문구에서 범용 "컨텍스트 데이터"로 일반화.
- **card_collect 전용**: ~~`tools.py::CARD_COLLECT_TOOLS` Gemini 대화 디스패치~~ →
  **2026-07-02 그리드 HITL 로 교체**(사용자 확정). `collect_rows` 는 `kind="grid"` HITL 프레임
  (행 데이터 + 예산단위 후보(라이브 팝업 덤프, 부서필터) + 사용자 즐겨찾기)을 방출하고, 프론트
  그리드에서 행별 예산단위/프로젝트/적요를 채워 일괄 제출(`rows`)하거나 프로젝트 검색(`query`)을
  보낸다. tools.py 는 `.recycles/` 로 이동(미사용). 즐겨찾기/카탈로그는 `user_code_favorites`·
  `erp_code_catalog`(마이그레이션 0009) + `/me/favorites`·`/me/catalog`(동기화 포함) 참조.
- **정규식 파서 제거**: `_parse_fields`/`_expand_item_nums`/`_parse_instructions` 삭제(전량 미사용).
- **history 버그 수정**: 최초 구현 시 사용자 턴마다 `history` 를 초기화하는 실수가 있었다(멀티턴 맥락
  유실). chat_form 처럼 **세션 전체 누적**(최근 40줄만 잘라 전송)으로 수정 — 유닛테스트로 검증.
- **⚠ 라이브 Gemini 테스트로 발견·수정한 실이슈**: 의미 매핑(행 지정·필드 추출·존재하지 않는 행→ask)은
  실 API 테스트에서 정확했으나, **같은 지시를 처리한 뒤 모델이 turn_done 대신 같은 도구를 반복 호출**
  하는 경우가 관측됨(예: skip_rows 를 `_MAX_TOOLS_PER_TURN` 한도(12회)까지 연속 재호출 — 결과는
  틀리지 않았지만 API 호출 낭비). 프롬프트 지시("반복 호출 금지")만으론 신뢰 불가 → **코드 레벨
  가드** 추가: 이번 턴 안에서 동일 (도구,인자) 서명(`_sig`)이 재등장하면 재실행 없이 턴 종료. 수정
  후 재검증(라이브) — 각 지시 정확히 1회만 실행됨 확인.
- **검증**: 유닛(모킹, 도구 디스패치·행번호 해석·멀티턴 history 누적) + 라이브 API(실 Gemini, 자연어→
  올바른 도구/필드 매핑 확인, 반복호출 수정 재검증) + 백엔드 전체 테스트 스위트 84개 통과(기존
  `tests/test_expense_card_gemini.py` 는 신 시그니처(`tools` 추가 인자)로 갱신) + 양쪽 그래프
  (`card-collect`/`expense-card-chat`) 컴파일 확인.
- **알려진 기존 한계(v2부터, 이번 변경으로 도입된 것 아님 — 참고용)**: (1) 이미 `apply_fields` 로
  반영(done)된 행에 대해 `update_note` 만 다시 호출하면 로컬 상태(`notes`)와 처리 현황 표는
  갱신되지만 **브라우저 DOM(그리드 NOTE_DC)에는 재반영되지 않는다**(재적용은 `apply_fields` 재호출로만
  실제 반영됨). (2) 이미 done 인 행을 `apply_fields` 로 다시 처리하면 `filled` 카운트가 중복 증가할
  수 있다(표시용 카운트 이슈, 실제 저장 게이트에는 영향 없음 — 저장은 문서 단위 F7이지 행 단위가 아님).

## 확정된 업무 결정(사용자, 2026-07-01)

- **D1 증빙유형**: **법인카드(01) 고정**. 법인카드(불공)(02)은 별도 종류로 추후.
- **D2 승인일 기간**: **10일 미만(1~9일)이면 전월**(1일~말일), **10일부터는 당월**(1일~오늘) (규칙 변경 2026-07-04: 3일 기준 → 10일 기준으로 환원).
- **D3 입력·적용·저장**: 예산단위/계정/프로젝트/적요 채움 → **일괄적용 자동** → **F7 저장까지 완전 자동**.
  - ⚠️ 이 종류에 한해 **저장 자동화가 명시적으로 승인**됨(기존 expense_card의 '저장 절대금지'와 구분).
- **테스트 정책**: 10회 반복 테스트는 **저장 직전 단계까지만**(실전표 미생성). 실저장은 최종 별도 1회.

## 실측 요약(2026-07-01, headless)

- 계정 이트라이브2에 **법인카드 5장** 존재(이전 세션 "0 cards"는 오류). 카드 서브팝업 gridRows=5.
- 승인일 2025-01-01~2026-12-31 조회 시 **거래내역 77건** 반환. 샘플:
  `2025-12-01 · 코스트코_온라인 · 839,800` / `2025-12-15 · KCP-Tesla Motors · 10,000,000`.
- 증빙유형 코드: **01=법인카드**, **02=법인카드(불공)**, 14=법인카드(불공)(원증빙).

## 목표

더존 옴니솔 **결의서입력(GLDDOC00300)** 화면에서 법인카드 승인내역을 **일괄 조회**한 뒤,
각 승인건에 대해 예산단위·계정·프로젝트·적요를 채워 지출결의 행을 준비한다(저장은 사람이).
현재 `expense-card-chat`(단건 대화형)과 달리, 이건 **다건 리스트 정리형**이다.

## 진입(공유 앞단 — expense_card 노드 재사용)

1. `login` — 옴니솔 인증(이트라이브2/1111, 회계).           검증: ✅ (기존 노드)
2. `user_type` — 사용자유형 '회계' 전환.                    검증: ✅
3. `menu_nav` — 결의서입력(GLDDOC00300) 진입.               검증: ✅
4. `set_gubun` — 결의구분 = **카드**.                        검증: ✅
5. `add_row` — 추가(F3)로 상세행 생성.                       검증: ✅
6. `open_evdn` — 증빙 셀 돋보기 → 증빙유형 팝업.             검증: ✅
7. `select_evdn` — 증빙유형 = **01 법인카드**.               검증: ✅
   → 이 선택 후 **법인카드 거래내역 조회 팝업**(k-window '법인카드')이 뜬다. 검증: ✅(이전 세션)

## 신규 단계(이번 작업 — 법인카드 팝업 내)

8. **증빙유형 선택 = 법인카드(01) 또는 법인카드(불공)(02)**   검증: ✅
   - "불요"는 오기 → **'불공'**(부가세 불공제). 증빙유형에 `법인카드`/`법인카드(불공)` 존재.
   - select_evdn 코드로 선택: 01/02. → **적용** 시 법인카드 거래내역 조회 팝업(k-window '법인카드') 오픈.
9. **카드번호 전체선택 → 적용**   검증: ✅
   - 카드번호 **돋보기**(`dews-multicodepicker-button` 중 `.icon-search`, ≈(619,190)) 실클릭
     → **'카드' 서브팝업**(k-window '카드', 746×535, 카드 5장) 오픈.
   - 서브팝업 그리드 `checkAll(true)`(5/5 체크) → **'적용'** 버튼(≈(685,688)) 실클릭.
10. **승인일 기간 설정**   검증: ✅
    - 위젯 = `dews-periodpicker`(input `period_startinput`/`period_endinput`, 기본=오늘~오늘).
    - value 직접 세팅 + `input/change/blur` 디스패치로 반영됨(조회 결과가 범위 반영 확인).
    - **업무 규칙(확정 필요)**: 오늘이 매월 **10일 이전이면 전월**(1일~말일), 아니면 당월(1일~오늘)?
11. **조회**   검증: ✅
    - 팝업 **우상단 '조회'** 버튼(≈(1319,149)) 실클릭 → 거래내역 그리드 갱신.
12. **리스트 읽기 → 채팅 보고**   검증: ✅
    - 그리드 `.dews-ui-grid` dewsControl `_grid`. 컬럼(field): **승인일=`TRAN_DT`,
      가맹점명=`TRAN_NM`, 승인액=`TRAN_AMT`**, 카드명=`FINPRODUCT_NM`, 카드번호=`FINPRODUCT_NO`,
      공급가액=`SPPRC_AMT`, 세액=`VAT_AMT`, 합계=`SUM_AMT`, 적요=`NOTE_DC`,
      **부가세구분=`VAT_TP`**(원시값 코드 '1' 등 → `getDisplayValuesOfRow(i).VAT_TP`로 라벨
      '과세' 등 획득, 2026-07-02 프로브 실측. 그 외 관리부서=`DEPT_NM`·승인번호=`APRVL_NO`·
      결의번호=`ABDOCU_NO`·카드승인여부=`APRVL_YN` 등 visible 컬럼 존재).
    - `getValue(row, field)` 로 행별 읽기(날짜는 JS Date → `.toISOString().slice(0,10)`).
13. **각 승인건 입력 필드**(예산단위·계정·프로젝트·적요)   검증: ✅ (일괄적용 모델)
    - 하단 **코드피커 폼**에 값 세팅 → 그리드에서 대상 행 체크 → **'일괄적용'** 클릭 → 체크행에 일괄 반영.
    - 필드 id(코드피커, `<id>_text` 입력 + `<id>-wrapper` + `.dews-codepicker-button`):
      예산단위=`bg_cd`, 사업계획=`bizplan_cd`, 예산계정=`bgacct_cd`, 계정=`acct_cd`,
      거래처=`partner_cd`, 비용센터=`cc_cd`, 프로젝트=`proj_cd`(추정), 적요=텍스트입력(추정).
    - 적요는 그리드 **`NOTE_DC`** 컬럼 인라인 편집도 가능(행별 상이값 → 인라인, 공통값 → 일괄적용).
    - **적요는 내용 추천**(가맹점명/업종 기반 초안 → 사용자 수정).
    - ⚠️ **일괄적용은 draft 반영이므로 실행 정책 확정 전까지 자동 클릭 금지**(F7 저장은 절대 금지).

## 확정된 셀렉터/좌표(요약)

| 요소 | 방법 |
|---|---|
| 법인카드 팝업 | `.k-window` 제목=`법인카드` |
| 카드 돋보기 | `.dews-multicodepicker-button` 내 `.icon-search`, ≈(619,190) 실클릭 |
| 카드 서브팝업 | `.k-window` 제목=`카드`, 그리드 `checkAll(true)` + '적용'(≈685,688) |
| 승인일 | `#period_startinput` / `#period_endinput` value set + input/change/blur |
| 조회 | 팝업 내 `button` text=`조회`, ≈(1319,149) |
| 거래내역 그리드 | `.dews-ui-grid` → `jQuery(...).data('dewsControl')._grid` |
| 컬럼 | TRAN_DT/TRAN_NM/TRAN_AMT/FINPRODUCT_NM/NOTE_DC … |
| 일괄적용 폼(코드피커) | 예산단위=`#bg_cd` · 계정=`#acct_cd` · 프로젝트=`#pjt_cd`(+사업계획 `bizplan_cd`·예산계정 `bgacct_cd`·거래처 `partner_cd`·비용센터 `cc_cd`). `#<id>-wrapper .dews-codepicker-button` 클릭→팝업 검색·선택·적용 |
| 적요 | `#note_dc`(**일반 텍스트 input** — value set + input/change/blur) |
| 일괄적용/저장 | 팝업 `button` text=`일괄적용`(체크행 반영), 저장=F7(결의서 저장) |

## 최종 실측 데이터(2026-06 전월 조회)

8건. 예: `2026-06-07 · 법원행정처_LG CNS · 1,000`, `2026-06-10 · 네이버파이낸셜(주) · 45,830`,
`2026-06-10 · 네이버파이낸셜(주) · -45,830`(취소건, 음수 존재 → 처리 시 주의).

## 입력 방식 확정: 건별(per-row) 루프

- **건별로 예산단위/계정/프로젝트/적요가 모두 다를 수 있음**(D4, 사용자 확정).
- 따라서 공통값 '일괄적용' 대신 **행별 입력 루프**:
  1. 행 i 선택(setCurrent/체크 1건).
  2. **적요 추천**(가맹점명 `TRAN_NM`/업종 기반 초안) → 사용자 확인·수정 → `#note_dc`(또는 그리드 `NOTE_DC` 인라인).
  3. 사용자 제시로 **예산단위(`#bg_cd`)·계정(`#acct_cd`)·프로젝트(`#pjt_cd`)** 코드피커 채움.
  4. 해당 행에 반영(단건 '적용' 또는 그 행만 체크한 '일괄적용') — 실제 버튼은 스크립트 1차 테스트에서 확정.
  5. 다음 행 반복.
- 모든 행 처리 후 → **F7 저장**(완전 자동 승인). 테스트에서는 저장 직전까지만.

## 코드피커/인라인 메커니즘(최종 확정)

- **적요**: 그리드 인라인 `_grid.setValue(row, 'NOTE_DC', text)` 로 **행별 세팅 확인**(before=null→after 반영).
- **예산단위/계정/프로젝트 코드피커**: 버튼(`#<id>-wrapper .dews-codepicker-button`) 클릭 → 팝업(제목=필드명,
  컬럼 예: 예산단위 `BG_CD/BG_NM/BIZPLAN_CD/…`). **초기 rows=0 → `#keyword` 입력 + 검색으로 채운 뒤 행 선택**.
  (기존 `expense_card/tools.py do_fill_search` 패턴과 동일 — 재사용/포팅 가능.)

## 통합 방향(⑥, 확정)

- 프론트 **기존 `card-chat` 에이전트("법인카드 지결 — 대화형 폼 채움")를 card_collect 로 교체**(사용자 확정).
  - `WORKFLOW_BY_AGENT['card-chat'] = 'card-collect'` 로 매핑 변경(현재 'expense-card-chat').
  - `register_workflow('card-collect', …)` 등록. `step-defs.ts` 에 card-collect 단계 정의 추가.
  - 에이전트 이름/설명을 다건 정리형에 맞게 갱신. 기존 expense-card-chat 그래프는 보존(다른 종류 재활용 가능).
  - 대화형 UX: 리스트 요약 채팅 보고 → 건별 예산단위/계정/프로젝트 입력 + 적요 추천(HITL 루프) → 일괄적용 → F7 저장.

## 코드피커 컬럼/의존성(실측 확정, probe7/8)

- 예산단위 `bg_cd`: 팝업 컬럼 `BG_CD/BG_NM`. keyword '경영' → 7건(code 2000 '경영 본부').
- 계정 `acct_cd`: 팝업 제목 "회계기표계정(예산계정 연동)", 컬럼 `ACCT_CD/ACCT_NM`.
  ⚠ **예산단위 선택 전에는 0건**. 예산단위(2000) 적용 후 기본 1건(511008 (제)복리후생비-4대보험).
  → **채우기 순서: 예산단위 → 계정 → 프로젝트 필수**(nodes.FIELD_SPEC 순서 유지). keyword 무매칭 시 기본목록 폴백(steps.fill_codepicker).
- 프로젝트 `pjt_cd`: 팝업 "프로젝트(WBS)", 컬럼 `PJT_NO/PJT_NM/WBS_NO/WBS_NM…`. keyword '나인벨' → 500건.

## 다행 처리 + 일괄적용 확인창(해결·통합)

- **근본원인**: `일괄적용` 클릭 시 **'예산현황' 확인 모달**(그리드 없는 소형 k-window, 확인/취소)이 뜬다.
  이걸 dismiss 하지 않으면 다음 행 코드피커가 'last non-법인카드 window' 셀렉터로 이 모달을 읽어 **0건** →
  둘째 행부터 코드피커 실패. **해결**: `js.BUDGET_CONFIRM_JS`로 '확인' 클릭 후 진행(`steps.apply_row`에 통합).
  ⚠ 이 확인은 **draft(메모리) 반영 완료**일 뿐 **F7 저장 아님**(서브에이전트 실측 검증).
- 계정은 keyword 무매칭 시 기본목록 폴백(`steps.fill_codepicker`) — 예산단위로 이미 좁혀진 기본 1건 사용.

## 코드피커 검색창 id 상이(정확성 주의)

- 예산단위/계정 팝업 검색창 = `#keyword`. **프로젝트 팝업 검색창 = `#s_search_key`**(다름).
- 초기 `PICKER_SEARCH_JS`가 `#keyword`만 타겟 → 프로젝트는 필터 안 되고 항상 전체목록 0번(SPARES_ACM) 선택되는
  버그. **수정**: `PICKER_SEARCH_JS`가 `#keyword || #s_search_key || [id$=search_key] || [id*=keyword]` 순으로 타겟
  (반환에 `field` 포함). → 프로젝트도 사용자 keyword로 실필터. (서브에이전트 라이브 재검증 중.)
- 계정: 예산단위 연동으로 보통 1건 자동축소. 다건일 때 `#keyword` 필터 동작은 확인 진행 중.

## 적대적 코드리뷰 반영(Workflow, 13건 확정 → 수정)

- **HIGH #1**: `fill_codepicker` 무매칭 시 임의 index0 선택·성공보고 → **이름매칭만 선택**(0/다건은 실패,
  후보 반환). `allow_default`(계정만 True)로 자동축소 단일만 예외. 성공 메시지는 **실제 선택명** 표시.
- MED #2/#4/#7: `collect_rows`·`save` 의 `wait_hitl` **TimeoutError try/except**(step failed+명확 메시지).
- MED #3: `_parse_fields` **경계 매칭** + 적요는 끝까지(값 안 라벨단어 오분배 방지). 단위검증 통과.
- MED #6: `apply_row` **정확히 1행 체크 검증**(checked!=1이면 일괄적용 중단).
- LOW #8: `run_query` **안정값 폴링**(느린 그리드 0 오인 방지). #11: 적요 실패 **치명화**.
  #12: `params.today` **형식검증**(오류→오늘). #13: filled==0에도 `save` step emit(pending 방지).
  #10: 저장 버튼 **문서 전역 탐색**(+F7 폴백).
- **회귀검증 후 추가 수정(서브에이전트 N=3)**: (1) 예산단위 '경영' 검색은 **이름 동일(경영 본부)·code 동일(2000)
  7행**을 반환 → 이름매칭이 다건 ambiguous로 오판·예산단위 사용불가. **code 로 dedupe**(동일 code 수렴=단일
  확정, 서로 다른 code 다건만 ambiguous). (2) 코드피커 **실패 경로에서 팝업 close**(`PICKER_CLOSE_JS`) — 안
  닫으면 다음 코드피커가 열린 팝업을 읽어 오작동. N=3 3/3 PASS·무매칭 실패 정상·프로젝트 실필터('KINGSTONE_TEST'→7220) 확인.
  UX: keyword 는 **단일 code 로 좁혀질 만큼 구체적**이어야(예 pjt 'SPARES' 39건→ambiguous→되물음).
- **잔여 한계(문서화)**: #5 행 루프가 턴마다 새 `wait_hitl`(chat_form의 지속 큐 아님) — 필드채움 중
  전송은 stale decision으로 거절되나 FE가 오류표시→재전송(무손실 아님/UI 게이트로 완화). #9 '완료'는
  남은 행 전체 종료(의도된 동작, 로그로 안내). #10 저장 경로는 실저장 라이브 미검증(게이트).

## 남은 작업 체크리스트(⑤⑥)

- [x] 계정(`acct_cd`)·프로젝트(`pjt_cd`) 코드피커 keyword/컬럼 확인 (probe7/8)
- [x] 행별 write 루프 — 다행 이슈(예산현황 확인창) 해결·통합
- [x] `apply_row`(일괄적용) + 예산현황 확인창 처리 — 10/10 검증
- [x] 헤드리스 10회 반복 테스트(저장 직전까지) — **10/10 PASS(avg 55s)**
- [x] 리뷰 반영·회귀 수정 후 **최종 코드 10회 재검증 — 10/10 PASS(avg 56.7s, 2026-07-02)**
- [x] LangGraph 노드/그래프(`graph.py`) + registry 등록 (`card-collect`)
- [x] 프론트 매핑(card-chat→card-collect)·step-defs·에이전트 메타 (HITL은 chat/choice 인프라 재사용)
- [~] 리뷰 반영 후 회귀 재검증(갱신 fill_codepicker N=3) — 진행 중
- [ ] 최종 1회 실저장 검증(사람 확인)

## 검증 로그

- v0→v1 (2026-07-01): probe_card/probe2/probe3 3회 — 진입~조회~77건, '불공'=02, 카드 5장·컬럼 확정.
- v1→v2 (2026-07-01): probe4/probe5/probe6 3회 — 일괄적용 폼 id 전수(bg_cd/acct_cd/pjt_cd/note_dc),
  전월(2026-06) 8건, 적요 인라인 setValue 성공, 코드피커=keyword 검색형 확정. **전 과정 메커니즘 실측 완료.**
- v2 스크립트화(2026-07-01): `js.py`(프리미티브)·`steps.py`(스텝 함수, compute_period D2 포함)·`__init__.py` 작성.
  헤드리스 러너로 진입~전체선택~기간(전월)~조회(8건)~리스트~적요인라인~코드피커(KW='경영'→7건 code 2000)
  **저장 전단계까지 PASS**. 남은 것: 계정/프로젝트 keyword, 일괄적용+F7 배선, 10회 반복, LangGraph 통합.
