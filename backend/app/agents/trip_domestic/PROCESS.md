# 출장(국내/자차) 결의서입력 — 프로세스 정의 (trip-domestic)

> 결의서입력(GLDDOC00300) 문서 종류 중 **출장(국내/자차)** 형태. 패밀리 인덱스: [../RESOLUTIONS.md](../RESOLUTIONS.md).
> 상태: **v1 — 헤드리스 프로브 P1~P9 실측 완료(2026-07-06)**. 승인 계획: `~/.claude/plans/eager-knitting-hopper.md`.
> 프로브: `e2e/trip_probe.py`(P1~P9 발견) + `trip_probe2.py`(셀 피커 토폴로지) + `trip_probe3.py`(검색 Enter·조합행).
> card 형제(참고 구조): [../card_collect/PROCESS.md](../card_collect/PROCESS.md).

## 개요

card_collect(다건 리스트 정리형·HITL 그리드)와 달리, 출장은 **모든 입력이 사용자 제공**이다.
따라서 **실행 전 입력 폼**으로 params 를 받고, 그래프는 **HITL 없이 무개입 완주**(폼값 채움 →
F7 저장)한다. 결의서 1장에 **여러 행**(통행료 N건 + 유류비 지원 등)을 F3 반복으로 채운다.

## 확정된 업무 결정(사용자, 계획서 반영)

- **D1 입력 방식**: **실행 전 폼**(개입 없음). params 는 네임스페이스 `trip` 로 감싼다
  (설정 플래튼 `fuel_*` 와 충돌 방지).
- **D2 여러 행 지원**: 결의서 1장에 통행료 N건 + 유류비 지원 등, **F3 반복**으로 행 추가.
- **D3 회계일자(마스터 ACTG_DT)**: **마지막 자차 사용일**(사용자 입력, 문서당 1개).
  compact 'YYYYMMDD' 로만 세팅(대시 형식은 셀을 비우는 함정 — card 실측).
- **D4 증빙유형**: **코드 10 "규정에의한 비용정산"**(❓ 정확 라벨 프로브 P2 확정).
- **D5 통행료 행**:
  - 거래처 = 공공기관(예: 한국도로공사) — **신규 partner 카탈로그**(projects 와 동일 싱크/
    즐겨찾기/기본지정 + `/manage/partners`), `kind="partner"`, `dept=""` 전사 공용.
  - 공급가액 = 입력 금액. 적요 = **"통행료(현금)"**.
- **D6 유류비 지원 행**:
  - 거래처 = **본인 이름 런타임 검색**(카탈로그 미사용, 정확 단건 매칭).
  - 적요 = **"국내출장 자차 유류비 지원"**.
  - 금액 = km ÷ 차량별 기준연비 × 기준단가, **원 단위 ROUND_HALF_UP**(백엔드 권위 계산).
- **D7 유류비 기준(에이전트 관리 설정)**: 차량별 기준연비 4종
  (1,000cc미만=14 / 1,600cc미만=9 / 2,000cc미만=7 / 2,000cc이상=6 km/L) + 기준단가(2000원/L).
  설정 키: `fuel_eff_under_1000/1600/2000`, `fuel_eff_over_2000`, `fuel_unit_price`.
- **D8 예산단위**: **"여비교통비-국내출장" 고정**(조합행 정확매칭 — ❓ 프로브 P6 확정).
- **D9 프로젝트**: 행별. card 와 동일 피커/카탈로그(`pjt_cd`, PJT_NM 검색 → WBS_NO 정확매칭).
- **D10 상대계정거래처**: **작성자 본인 이름**(프로젝트 그리드 하단 왼쪽 — ❓ 필드 정체 프로브 P8).
- **D11 저장**: F7 저장까지 자동, **상신은 사용자가 ERP 에서 직접**.

## 실측 요약(프로브 P1~P9 확정, 2026-07-06)

- **P1** 결의구분 라벨 = **"출장(국내·자차)"**(가운뎃점 `·`, 슬래시 아님), value=`53`.
  `KENDO_SET_DROPDOWN_BY_TEXT_JS`(`#s_abdocu_fg_cd`)로 전환 성공(ok, val 53). ✅
  전체 옵션: 세금계산서/카드/출장(국내·자차)/출장(해외·정산서)/경조금신청서/학자금신청서/
  동호회비신청서/일반/건설중인자산/이전비/클레임보상수익/수입결의서.
- **P2** 증빙유형 코드 **10 = "규정에의한 비용정산"** 존재(팝업 25개 코드). 코드 10 선택·적용 시
  부가 팝업/필수 팝업 없음(EVDN 셀 반영 확인). ✅
- **P3** 마스터 `ACTG_DT` **compact 'YYYYMMDD' 세팅 동작**(입력 `20260706`→표시 `2026-07-06`).
  card 와 동일 — 대시 형식은 셀을 비우는 함정, compact 만 사용. ✅ (`SET_ACCT_DATE_JS` 재사용)
- **P4/P7 핵심** 거래처·예산단위·프로젝트·상대계정거래처·공급가액·적요는 **문서 폼 코드피커가
  아니라 detail RealGrid(그리드 index 1) 셀**이다. 문서 스코프 폼 피커는 헤더(회계단위
  `s_pc_cd`/결의부서 `s_cd_wdept`/결의자 `s_no_emp_write`)뿐. → **card 의 `picker_btn_js`
  (CARD_WIN 스코프) 재사용 불가**, 셀 에디터(showEditor+돋보기) 접근 필요. ✅
- **P4** 거래처 피커: 셀 `PARTNER_NM`/`PARTNER_CD` showEditor+돋보기 → k-window 제목 **"거래처"**,
  검색창 id **`customTextBox`**, 컬럼 `PARTNER_CD`/`PARTNER_NM`/`PARTNER_FG_NM`/`BIZR_NO`…,
  빈검색 상한 **500행**. 검색은 값 세팅 후 **Enter** 필수(값만으론 필터 안 됨). ✅
- **P5** 거래처 검색(customTextBox+Enter): **"이트라이브2"**(본인=거래처 존재) exact 매칭 1건,
  **"한국도로공사"** n=3·exact 1건(통행료 공공기관), "도로공사" 부분검색 n=3. 반환 행 내
  `PARTNER_NM` 완전일치로 단건 확정. ✅
- **P6** 예산단위 피커: 셀 `BG_NM`/`BG_CD` showEditor+돋보기 → k-window 제목 **"예산단위"**,
  검색창 id **`keyword`**(card 와 동일), 컬럼 `BG_CD/BG_NM/BIZPLAN_CD/BIZPLAN_NM/BGACCT_CD/BGACCT_NM`.
  ⚠ **"여비교통비-국내출장"은 단일 예산단위가 아니라 `BGACCT_NM`** = **`(제)여비교통비-국내출장`**
  또는 **`(판)여비교통비-국내출장`**. `BG_NM`=부서(임원실/구매팀/회계팀/인사기획팀…),
  `BIZPLAN_NM`=`운영비`(판)·`운영비 (제조)`(제). "국내출장" 검색 시 **33행**(부서×판/제 조합).
  → 정확 조합 = **사용자 부서(BG_NM) + cost_type 판/제(BGACCT `(판)`/`(제)` 접두) + "여비교통비-국내출장"**
  (card 의 소속팀 비용구분 연결과 동일 모델). 검색은 Enter 필수. ✅
- **P7** 금액 셀 setValue 직접 동작(표시 '12,345'), 적요=**`NOTE_DC`**(`g.setValue` 직접). ✅
  - ⚠ **금액 컬럼 정정(v5, 2026-07-07)**: 금액은 공급가액(SPPRC_AMT)이 아니라 **공급가(거래금액)=
    `SPPRC_AMT2`**(헤더 "공급가액 (거래금액)")에 채운다(사용자 정정). 헤더↔필드(프로브 trip_amount):
    `SPPRC_AMT2`=공급가액(거래금액) / `SPPRC_AMT`=공급가액 / `DOCU_AMT2`=거래금액(현지통화) / `TOTAL_AMT`=합계.
  - ⚠ **자동계산 없음**: `SPPRC_AMT2` setValue 시 SPPRC_AMT/TOTAL_AMT/마스터 DETAIL_SUM_AMT 는 0 유지
    (setValue 가 ERP 변경 핸들러 미발화). 국내 자차는 부가세 0 → 세 값 동일하므로 `set_transaction_amount`
    가 SPPRC_AMT2+SPPRC_AMT+TOTAL_AMT 를 **동일값 병행 세팅·각 반영 검증**한다. 서버가 거래금액에서
    파생하면 값이 같아 무해 — Phase 6 실저장에서 파생 여부 확정 후 축소 가능.
  - 적요=`NOTE_DC` 는 setValue 직접(정상). ✅
- **P8** 상대계정거래처 = detail 셀 **`BFC_PARTNER_CD`/`BFC_PARTNER_NM`**, 피커는 **거래처 팝업(동일)**.
  본인이름 검색·매칭 P5 와 동일. ✅ (텍스트 직접입력 아님 — 코드피커 셀)
- **P9** F3 2행째 **증빙 carry-over 없음**(새 행 `EVDN_TP_NM` 빈칸). 행별로 open_evdn+select_evdn(10)
  재실행 필요. 예산단위/거래처도 행별 독립 세팅. ✅
- **P4-보충** (카탈로그 sync 문맥, `trip_probe4.py`) 거래처 피커는 **결의구분=카드 문맥에서도
  도달 가능**하다. `code_sync._run_entry_chain`(카드+증빙01→CARD_WIN) 이후 CARD_WIN 일괄적용 폼에
  코드피커 필드 `[wrt_emp_no, bg_cd, bizplan_cd, bgacct_cd, acct_cd, **partner_cd**, cc_cd, pjt_cd]`
  존재 → `picker_btn_js("partner_cd")`(CARD_WIN 스코프)로 연다(dump_budget_units 와 동일 패턴).
  팝업 내용 **동일**: 제목 "거래처", 빈검색 n=**500(cap)**, 검색창 `customTextBox`, 컬럼
  `PARTNER_CD/PARTNER_NM/…/BIZR_NO`. "이트라이브2" 검색 n=1·exact 1. → **`dump_partners` 는 기존
  진입 체인을 그대로 재사용**(출장 문맥 불필요). ⚠ 빈검색이 500 cap 이므로 전량 수집은
  projects 처럼 페이징(끝행+ArrowDown) 또는 접두 스윕 필요(총행수 > 500 가능). ✅

## 진입(공유 앞단 — app.agents.common.nodes 재사용, card 와 동일)

| # | 노드 | 역할 | 검증 |
|---|---|---|---|
| 1 | `login` | 옴니솔 인증(이트라이브2/1111, 회계) | ✅ (기존 노드) |
| 2 | `user_type` | 사용자유형 '회계' 전환 | ✅ |
| 3 | `menu_nav` | 결의서입력(GLDDOC00300) 진입 | ✅ |
| 4 | `set_gubun` | 결의구분 = **"출장(국내·자차)"**(value 53) | ✅ P1 |
| 5 | `add_row` | 추가(F3)로 상세행 생성 | ✅ (기존 노드) |
| 6 | `set_acct_date` | 마스터 ACTG_DT = 마지막 자차사용일(compact) | ✅ P3 |
| 7 | `open_evdn` | 증빙 셀 돋보기 → 증빙유형 팝업 | ✅ (기존 노드) |
| 8 | `select_evdn` | 증빙유형 = **10 규정에의한 비용정산** | ✅ P2 |

앞 8노드는 `common/nodes.py`(login/user_type/menu_nav/set_gubun/add_row/open_evdn/select_evdn)와
card 에서 승격할 `set_acct_date` 를 그대로 재사용한다. set_gubun 라벨·select_evdn 코드만 파라미터화.

## 신규 단계(이번 작업 — 본문 문서 폼/그리드 채움)

9. **fill_rows** — `plan_rows` 내부 루프(HITL 없음):
   - `i > 0` 이면 F3 행추가(증빙 carry-over 여부 P9 로 행별 재선택 결정).
   - 행별 채움 순서: 거래처 → 공급가액 → 적요 → 예산단위(고정) → 프로젝트 → 상대계정거래처(본인).
10. **save_doc** — F7 저장(confirm 게이트 + 팬텀저장 방지, card `save_document` 재사용).
    실패 시 retry(menu_nav 재진입), MAX_SAVE_RETRIES=2.

## ⚠ 핵심 기술 분기 — **결정됨: (b) RealGrid detail 셀** (P7 확정)

card 의 코드피커는 **카드팝업(`CARD_WIN`) 스코프 하드코딩**(`picker_btn_js`). 출장은 문서 폼
코드피커가 **아니라** 전부 **detail RealGrid(그리드 index 1) 셀**이다(문서 스코프 폼 피커는
헤더 3개 `s_pc_cd/s_cd_wdept/s_no_emp_write` 뿐). 따라서:

- **금액/텍스트 셀**(공급가액 `SPPRC_AMT`, 적요 `NOTE_DC`): 피커 없이 `g.setValue(row, field, v)`
  직접 세팅(실측 동작, 표시 반영 확인). SET_ACCT_DATE_JS 와 동일 계열의 `g`/`ds` 접근.
- **코드 셀**(거래처 `PARTNER_CD`, 예산단위 `BG_CD`, 프로젝트 `PJT_CD`, 상대계정 `BFC_PARTNER_CD`):
  셀 에디터로 팝업을 연다 → **showEditor(마지막 행, fieldName) → 에디터 input 우측 돋보기(+8px)
  실클릭 → k-window 피커 팝업**. 이후 검색·선택·적용은 card 의 nbkit 피커 프리미티브
  (`PICKER_SEARCH_JS`/`PICKER_READ_MULTI_JS`/`PICKER_SELECT_JS`/`PICKER_APPLY_BTN_JS`)를
  **그대로 재사용**한다(여기선 법인카드 팝업이 없어 "last non-법인카드 k-window" 셀렉터가 곧
  피커 팝업). 검색은 값 세팅 후 **Enter** 필수.

**Track A 구현 방향(계획의 doc_picker_btn_js 대체)**: `picker_btn_js`(CARD_WIN) 대신
**셀 에디터 오픈 프리미티브**를 nbkit 에 추가한다 —
`OPEN_DETAIL_CELL_EDITOR_JS(fieldName)`(= 현 `OPEN_EVDN_EDITOR_JS` 를 fieldName 파라미터화) +
`DETAIL_EDITOR_MAGNIFIER_JS`(input `/gridDetail_line/` 우측 +8px). 그 위에서 기존 `fill_codepicker`
로직(이름/조합 정확매칭)을 재사용하되, 검색창 id 는 팝업별로 다르므로 `PICKER_SEARCH_JS` 의
기존 폴백 체인(`#keyword`→`#s_search_key`→…)에 **`#customTextBox`** 를 추가한다(거래처 팝업).

## 셀렉터/필드 테이블 (실측 확정)

| 요소 | 방법 / 셀렉터 | 상태 |
|---|---|---|
| 결의구분 | `#s_abdocu_fg_cd`, 라벨 **"출장(국내·자차)"**(value 53), `KENDO_SET_DROPDOWN_BY_TEXT_JS` | ✅ P1 |
| 증빙유형 팝업 | `.k-window.dialog`, `EVDN_*` JS, **코드 10 "규정에의한 비용정산"** | ✅ P2 |
| 회계일(마스터) | `SET_ACCT_DATE_JS` — `ds.setValue(0,'ACTG_DT','YYYYMMDD')` compact 전용 | ✅ P3 |
| **필드 토폴로지** | **전부 detail 그리드(index 1) 셀** (문서 폼 피커 아님) | ✅ P7 |
| 거래처 셀 | 셀 `PARTNER_CD`/`PARTNER_NM` → showEditor+돋보기 → k-window "거래처" | ✅ P4 |
| 거래처 피커 검색창 | **`#customTextBox`** (값 세팅 + **Enter**) | ✅ P5 |
| 거래처 피커 컬럼 | `PARTNER_CD`/`PARTNER_NM`(+`PARTNER_FG_NM`/`BIZR_NO`…), 빈검색 상한 500 | ✅ P4 |
| 공급가(거래금액) | detail 셀 **`SPPRC_AMT2`**(헤더 "공급가액 (거래금액)") — 금액 채우는 필드(사용자 정정 2026-07-07). `set_transaction_amount` 가 SPPRC_AMT2+SPPRC_AMT+TOTAL_AMT 동일값 세팅(자동계산 없음) | ✅ v5 |
| 적요 | detail 셀 **`NOTE_DC`** — `g.setValue(row,'NOTE_DC',text)` 직접 | ✅ P7 |
| 예산단위 셀 | 셀 `BG_CD`/`BG_NM` → showEditor+돋보기 → k-window "예산단위", 검색창 **`#keyword`**+Enter | ✅ P6 |
| 예산단위 조합 | **BGACCT_NM=`(제)/(판)여비교통비-국내출장`** × BG_NM(부서) × BIZPLAN(운영비/(제조)) — 사용자 부서+cost_type 로 단건 확정 | ✅ P6 |
| 프로젝트 셀 | 셀 `PJT_CD`/`PJT_NM` → showEditor+돋보기 → k-window "프로젝트", 검색창 `#s_search_key` | ✅ P7(card 동일) |
| 상대계정거래처 | detail 셀 **`BFC_PARTNER_CD`/`BFC_PARTNER_NM`**, 피커=거래처 팝업(동일) | ✅ P8 |
| 저장 | F7 (card `save_document` 재사용, VALIDATION_TOAST+오류모달 감지) | ✅ (card 검증) |

## 남은 작업 체크리스트

- [x] **P1~P9 헤드리스 프로브 실행** → 셀렉터/토폴로지 전량 확정 (`e2e/trip_probe*.py`)
- [x] Track A: nbkit `OPEN_DETAIL_CELL_EDITOR_JS(fieldName)`+`DETAIL_EDITOR_MAGNIFIER_JS` +
      `PICKER_SEARCH_JS` 에 `#customTextBox`+`focus()` 추가 + 셀 에디터 피커 래퍼(`_open_detail_cell_picker`)
- [x] Track A: `steps.py`(fill_partner=거래처 셀 피커·이름 exact, fill_partner_by_search(본인),
      fill_budget_fixed(BGACCT "여비교통비-국내출장" × 부서 × 판/제 정확매칭), set_supply_amount(SPPRC_AMT),
      set_row_note(NOTE_DC), fill_bfc_partner(BFC_PARTNER), fill_project, dump_partners)
- [x] Track A: 코드 셀 apply 메커니즘 실채움 검증(`e2e/trip_fill_probe.py`, 저장 없이) —
      **선택→'적용' 버튼 클릭이 셀에 반영됨**(dblclick 불필요, PARTNER_NM 재독으로 확인)
- [x] Track A: SPPRC_AMT 자동계산 여부 확인 — **자동계산 없음**(setValue 로 SPPRC_AMT=91428 반영되나
      TOTAL_AMT/ABDOCU_AMT/마스터 DETAIL_SUM_AMT 는 0 유지) → Phase 4 에서 TOTAL_AMT 명시 세팅 후보,
      Phase 6 실저장에서 서버 재계산 여부 최종 확인
- [ ] Track B: partner 카탈로그 배관(me_codes/code_sync/manage/partners)
- [ ] Track C: `params.py`(pydantic + fuel_support_amount) + agent_settings + 실행 전 폼
- [ ] Phase 4: nodes/graph.py(TripDomesticState) + registry + fixture 승격
- [x] Phase 5→**실저장 사이클로 개편**(정책 변경 2026-07-07): F7 실저장→검증→F6 삭제 **10회 반복
      10/10 PASS, avg 59.9s, 잔존 전표 0** (`e2e/trip_smoke_cycle.py`). 삭제 가드레일(결의자+fg53+미결).
- [x] **저장 성공 양성 신호**: 결의번호(ABDOCU_NO)는 저장 시점 blank(전기/상신 때 채번) → 신호 아님.
      **재조회 시 문서 지속(persist)**이 양성 신호 → `nodes/save.py` 에 F7 후 조회+마스터 rowcount≥1
      검증 추가(확정 0건이면 팬텀으로 실패 승격, 못 읽으면 판정 보류).
- [x] **합계 정합**: setValue 는 ERP 합계 재계산 미발화 → 마스터 DETAIL_SUM_AMT 가 마지막 detail 행
      누락(F3 때만 갱신). `steps.set_master_total` 로 전 행 합계를 마스터에 명시 세팅(fill_rows 말미).
      실저장 10회 모두 저장값 DETAIL_SUM_AMT = 상세합계 정합 확인.
- [x] **상대계정거래처(업무 필수) = detail 행 `BFC_PARTNER_CD` 직접 setValue**로 해결(2026-07-07).
      작성자 본인(로그인 사용자)의 partner code 를 상대계정으로 입력한다("결국 이름이 입력되어야 해",
      사용자 요구). fill_rows step 8 배선(`lookup_partner_code`+`set_counter_partner`), 실저장 e2e 에서
      3행 모두 BFC_PARTNER_CD=이트라이브2(2026032511)·PARTNER 미덮음·행 추가 없음·삭제 후 잔존 0.
      - 배경: 하단 폼 코드피커 **위젯 UI 경로**는 '적용'이 활성 detail 에디터에 반영돼 빈 행을 추가하는
        함정이라 모든 UI 조작이 실패(위젯이 계정 마스터 상대계정 연결에 의존하는 커스텀 폼). XHR
        (`e-subdetails`)로 상대계정이 **행 서브디테일**임을 규명.
      - 해결: 위젯 우회 — detail dataSource 필드 `BFC_PARTNER_CD` 를 `grid.setValue(row,...,code)` 로
        직접 세팅하면 행 추가 없이 반영되고 **저장 전표에 상대계정거래처로 persist**(실저장+재조회 실증).
        BFC_PARTNER_NM 은 dataSource 필드 아님(서버가 코드로 이름 파생). js `SET_BFC_PARTNER_JS`.

## 알려진 제약

- **작성자 계정ID = 실명 가정**(`nodes/fill.py` fill_rows): 유류비 지원 행의 거래처와 상대계정거래처는
  **작성자 본인 이름(`state["userid"]`)으로 거래처 마스터를 검색**해 완전일치 선택한다. 옴니솔 계정ID가
  실명과 다른 사용자(예 'etribe01')는 거래처 검색이 무매칭돼 유류비 행에서 실패한다. 오류는 한국어로
  명시된다("거래처 '<이름>' 일치 없음"). 통행료 행(거래처=카탈로그 코드)에는 영향 없다.

## 검증 로그

- v0 (2026-07-06): MD 초안 작성. card PROCESS 구조 미러.
- v1 (2026-07-06): 헤드리스 프로브 3종 실행(읽기전용, 저장 없이 종료).
  - `trip_probe.py` — P1(결의구분 옵션·라벨) / P2(증빙 25코드·10 존재) / P3(ACTG_DT compact) /
    P7 발견(detail 그리드 컬럼 전량 + 문서 폼 피커=헤더뿐 + SPPRC_AMT·NOTE_DC setValue 성공).
  - `trip_probe2.py` — 셀 에디터(showEditor+돋보기)로 거래처("거래처" 500행)·예산단위("예산단위")·
    프로젝트·상대계정(BFC_PARTNER=거래처 팝업) 피커 오픈 확인. 검색 미필터(트리거 누락) 발견.
  - `trip_probe3.py` — 검색은 **Enter** 필수 확정. P5(거래처 exact 매칭: 이트라이브2/한국도로공사),
    P6(예산 "여비교통비-국내출장"=BGACCT 레벨, 부서×판/제 33조합) 확정.
  - 아티팩트: `e2e/artifacts/trip_probe*.json` + `*.png`.
- v1 스모크(2026-07-06): `trip_smoke_cycle.py` — 그래프를 직접 ainvoke(runner state 주입 미러),
  저장 직전까지 10회 반복. **10/10 PASS · avg 55.8s**(min 44.6 / max 69.1; fill_rows 통행료1~2행+
  유류비 34~53s, login 웜 ~4-6s). F7 미실행 게이트 = `card_steps.save_document` 몽키패치(스텁 10회
  호출·실저장 0건, 1회차에서 게이트 차단 검증). 파라미터 사이클마다 변형(통행료 1~2행·유류비
  carClass 4종 로테이션·km 75~300). 실측 파라미터: 통행료 거래처 한국도로공사(10512)·프로젝트
  포장개선(1310|1310)·**실부서 인사/기획팀·판관비**(runs.py 주입값과 동일: user.department +
  team.cost_type). 아티팩트: `e2e/artifacts/trip_smoke_cycle.json`(+실패 시 `trip_smoke_c{N}_fail.png`).
  - ⚠ **스모크 검출 버그·수정**: `pick_budget_row` 가 `_norm`(공백만 제거)으로 부서를 비교해
    `user.department` '인사/기획팀' 이 예산 BG_NM '인사기획팀' 과 무매칭(슬래시 잔존)이었다. 회계팀
    등 슬래시 없는 부서만 쓰던 초기 스모크가 이를 가렸다. `_norm_dept`(구분기호 제거)+상호포함
    매칭으로 수정(card `dept_matches_budget_name` 동일 규칙). 회귀 테스트
    `test_pick_budget_department_ignores_separators` 추가.
- v2 (2026-07-06): Track A 스크립트화 + 실채움 검증(`e2e/trip_fill_probe.py`, **F7 저장 없이**).
  - 2행 실채움(통행료 1: 거래처 한국도로공사·예산 회계팀(판)여비교통비-국내출장·프로젝트·상대계정 본인
    / 유류비 1: 거래처=본인 이트라이브2) **전 단계 ok=True**. 코드 셀 apply = **선택→'적용' 버튼**이
    셀에 반영(PARTNER_NM 재독 확인, dblclick 불필요). F3 2행째 증빙 재선택(P9 carry-over 없음) 정상.
  - **자동계산 없음**: SPPRC_AMT setValue 반영(표시 91,428)되나 TOTAL_AMT/ABDOCU_AMT/DETAIL_SUM_AMT=0 유지.
    → Phase 4 TOTAL_AMT 명시 세팅 후보, Phase 6 실저장 확인 필요.
  - `dump_partners` 카드 문맥 실측: **총 3,592 거래처, 47.6s**(끝행+ArrowDown 페이징, 500 cap 초과 정상 수집).
    타이밍: 진입 14.0s / 행1 12.9s / 행2 15.4s.
  - nbkit `PICKER_SEARCH_JS` 에 `kw.focus()` 추가(셀 에디터 팝업은 포커스가 그리드에 있어 Enter 미도달 →
    검색 미트리거였음). card 피커도 focus+Enter 로 동작 유지(회귀 없음, 전체 테스트 통과).
  - 아티팩트: `e2e/artifacts/trip_fill_results.json` + `trip_fill_*.png`.
- v3 (2026-07-06): 적대적 코드리뷰 ERP 스텝/그래프 5건 반영(`steps.py`·`nodes/fill.py`·`nodes/save.py`).
  - [HIGH] `_select_and_apply`: '적용' 버튼 미발견·**셀 반영 미검증** 시에도 ok 였던 것을 —
    apply_box None→실패, `READ_DETAIL_CELL_JS` 로 대상 셀(PARTNER_NM/BG_NM/PJT_NM/BFC_PARTNER_NM)
    반영을 8s 폴링 검증(select_evdn 패턴 미러), 팝업 미닫힘(`_picker_gone` 1.5s)도 실패로 승격.
    마지막 피커(fill_bfc_partner) 적용 미스 시 잔존 팝업이 F7 을 삼키는 팬텀 저장 경로 차단.
  - [MED] `fill.py` TOTAL_AMT warn-후-진행 → fail-fast(`fail(i,"합계금액")`) — 반쪽 결의서 저장 방지.
  - [MED] `pick_budget_row` 부서 매칭: **정규화 완전일치 1순위 → 부분포함은 단건일 때만**(다건 후보
    나열 실패), 부분포함 채택 시 매칭 BG_NM 로그. (v1 스모크 버그 수정의 후속 강화.)
  - [MED] `set_supply_amount`: 세팅 후 셀 재독값(콤마 제거) ≠ 요청금액이면 실패("반영 불일치").
  - [HIGH/MED] `save.py`: 검증성(결정적) 거부는 **재시도 없이 즉시 실패**(trip HITL 없어 동일입력
    재작성 무의미), 재시도는 비결정적 실패에만. 재시도 채팅 문구를 실제 동작(일시적 오류 재작성)에 맞춤.
    **F7 전 활성요소 blur+body 포커스** 강제(잔존 에디터 포커스가 F7 삼킴 방지). 저장 **양성 신호**
    (결의번호) 검증은 Phase 6 실측 항목으로 코드 TODO + 위 '남은 작업' 플래그.
  - [LOW] userid=거래처명 가정을 위 '알려진 제약'에 문서화(오류 메시지 한국어 명시 확인).
  - 회귀 테스트 추가(`test_trip_domestic_steps.py` 부분포함 매칭·set_supply_amount·_select_and_apply
    3케이스 / `test_trip_domestic_nodes.py` fill fail-fast·save 결정적/비결정적 분기). 전체 pytest 회귀 0.
  - ⚠ **셀검증이 잡은 후속 버그 — fill_bfc_partner(상대계정거래처) 비활성화**: 강화된 셀검증이
    BFC 적용 후 `BFC_PARTNER_NM` 미반영을 잡음 → 진단(`trip_bfc_probe.py`) 결과 `BFC_PARTNER_CD/NM`
    은 getValue 불가 컬럼("Invalid field index")이라 `showEditor('BFC_PARTNER_NM')`가 **본 거래처
    (PARTNER) 셀로 폴백** → fill_bfc_partner 가 방금 채운 거래처를 상대계정 이름으로 **덮어씀**
    (실측: PARTNER_NM 한국도로공사→이트라이브2). 문서 스캔(`trip_counter_scan.py`)에서도 별도
    상대계정거래처 입력 필드 없음(VAT_ACCT/FEOTH_ACCT 는 부가세·합계 상대'계정'으로 무관).
    → **P8 판정(BFC_PARTNER=상대계정) 오류 확정**. `fill_rows` 8단계 비활성화(steps.fill_bfc_partner
    는 보존). 상대계정거래처 실필드·필수여부는 Phase 6 실저장에서 사용자 참관하에 확정.
  - 거래처 검색(customTextBox) 클라이언트 필터 레이스(스모크 1/10 '이트라이브2 무매칭') →
    `_fill_partner_cell` 재검색·재독 3회 재시도 추가. **스모크 10/10 PASS · avg 53.2s** 재검증.
- v4 (2026-07-06): 상대계정거래처 **실필드 집중 재프로브**(팀리드 지시, 저장 없음).
  - `trip_bottom_probe.py`: 행 채움 후 문서 하단(뷰포트 아래)에 grid[2](항목)·차변/대변·예산정보와
    함께 **'상대계정거래처' 라벨(≈265,1113)+코드피커** 렌더 확인. F3 직후엔 미렌더(행 데이터 필요).
  - `trip_counter_field_probe.py`: 라벨 기준 좌표 로케이트+스크롤로 피커 오픈→본인 검색·선택·적용.
    **증빙 없이는**: PARTNER 미덮음(한국도로공사 유지) + 하단 입력 반영(2026032511·이트라이브2) 성공.
    **증빙(10) 있는 실 플로우에서는**: 적용 시 detail 행 리셋(PARTNER 소실·라벨 사라짐) 재현 →
    헤드리스 재배선 보류, Phase 6 실측으로 이관. `steps.fill_counter_partner`(+js COUNTER_* 프리미티브)
    는 구현·보존, `fill_rows` step 8 은 비활성(각 행 올바른 단일 거래처 유지).
  - `trip_counter_scan.py`: 문서 라벨 스캔(상대'계정' 컬럼은 VAT_ACCT/FEOTH_ACCT 로 거래처 무관 확인).
  - 최종 스모크 **10/10 PASS**(step 8 비활성), 전체 pytest 회귀 0.
- v5 (2026-07-07): **금액 컬럼 정정 — 공급가(거래금액)=SPPRC_AMT2**(사용자 정정). 프로브 `trip_amount_probe.py`
  로 헤더↔필드 매핑 실측(SPPRC_AMT2=공급가액(거래금액)) + 자동계산 없음 확인(SPPRC_AMT2 세팅해도
  SPPRC_AMT/TOTAL_AMT/DETAIL_SUM_AMT=0). `steps.set_supply_amount`→**`set_transaction_amount`** 개명·
  SPPRC_AMT2 primary + 공급가액 + 합계 동일값 병행 세팅·각 반영 검증. `fill.py` step 6 호출·라벨('거래금액')
  갱신(TOTAL_AMT 별도 세팅은 함수로 흡수). 단위 테스트 갱신. **스모크 10/10 PASS · avg 52.8s**, 전체
  pytest **390 passed**(회귀 0). Phase 6: 서버 파생 여부 확정 후 병행 세팅 축소 검토.
- v6 (2026-07-07): **테스트 정책 변경 — 실저장(F7)→검증→삭제 사이클**(사용자 지시, F7 테스트 승인·
  상신 금지·삭제 필수). `trip_smoke_cycle.py` 개편(몽키패치 제거, 그래프 F7 완주 → 마스터 조회·가드레일
  (결의자=계정+ABDOCU_FG_CD=53+미결) → F6 삭제 → 잔존 0 검증). card `e2e_smoke` phase2 델리트 로직 이식.
  - **10/10 PASS · avg run 59.9s · 잔존 전표 0**(사이클마다 저장→삭제 완결, 삭제 실패 시 즉시 중단 설계).
  - 실측 확정: (a) **상대계정거래처 optional** — 비워도 저장 성공(10/10). (b) **저장 양성 신호 = 재조회
    persist**(ABDOCU_NO 는 저장 시 blank). (c) **합계 정합** — `set_master_total` 로 마스터 DETAIL_SUM_AMT
    정합(저장값 = 상세합계, 10/10 확인). detail 각 행 거래금액=공급가액=합계 정합.
  - 수정: `save.py`(재조회 persist 검증)·`steps.py`(set_master_total)·`js.py`(SET_MASTER_TOTAL_JS)·
    `fill.py`(말미 마스터합계 세팅). 전체 pytest **390 passed**(회귀 0).
- v7 (2026-07-07): **상대계정거래처(업무 필수) 해결 — BFC_PARTNER_CD 직접 setValue**. 사용자 확정으로
  상대계정=로그인 사용자(이트라이브2) 필수. 하단 폼 위젯은 모든 헤드리스 조작(적용버튼/더블클릭/타이핑/
  포커스)이 빈 detail 행 추가·미반영으로 실패 → XHR 관찰(`e-subdetails`)로 **행 서브디테일**임을 규명.
  detail dataSource 필드 `BFC_PARTNER_CD`(getColumns 존재, grid.setValue 동작)에 작성자 partner code를
  직접 세팅하면 **행 추가 없이 저장 전표에 상대계정으로 persist**(실저장+재조회 실증). `lookup_partner_code`
  (거래처 팝업 이름검색→PARTNER_CD, 선택/적용 없이 닫기)+`set_counter_partner`(SET_BFC_PARTNER_JS)로
  `fill_rows` 배선. **단일 실저장 e2e PASS**: 폼→완주(상대계정 포함)→F7→재조회 persist+금액 정합+
  상대계정 3행 반영→F6 삭제→잔존 0. 단위 테스트 set_counter_partner 2건 추가. 전체 pytest **394 passed**.
  진단 프로브: `trip_bfc_dataset_probe.py`·`trip_bfc_save_verify.py`·`trip_counter_flow_probe.py`(위젯 함정 실증).
- v8 (2026-07-07): **상대계정거래처 배선 확정(해결·유지)**. 사용자 원 요구("결국 이름이 입력되어야 해")
  대로 작성자 본인 상대계정 입력 = 필수. `fill_rows` step 8 = `lookup_partner_code`+`set_counter_partner`
  (BFC_PARTNER_CD setValue) 배선 유지. flow_graph bfc 노드·fill_rows 스텝 detail 에 상대계정 포함,
  handoff_note 는 상신 안내만(자동 입력되므로 수동입력 문구 불요). 마무리 검증: 전체 pytest 394 passed·
  프론트 tsc/build PASS·백엔드 재기동·trip-domestic 등록 확인. 논리 단위 커밋.
