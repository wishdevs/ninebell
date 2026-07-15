# 학자금신청서 결의서입력 — 프로세스 정의 (hakjagum-grant)

> 결의서입력(GLDDOC00300) 문서 종류 중 **학자금신청서**. 패밀리 인덱스: [../RESOLUTIONS.md](../RESOLUTIONS.md).
> 상태: **v1.0 — 완성. 단계 0~8 완주(2026-07-15). 라이브 실저장 10/10 PASS·avg 40.0s·잔존 0,
> 프론트 pre-run 폼(hakjagum-grant) 등록, D12 상대계정 미사용 확정, 픽스처 hidden 해제(노출).
> 유닛 508+ pass. 남은 상시작업: 운영 모니터링(단계 8).**
> 형제(기본틀 동일): [../gyeongjo_grant/PROCESS.md](../gyeongjo_grant/PROCESS.md) · [../trip_domestic/PROCESS.md](../trip_domestic/PROCESS.md).

## 개요

**경조금신청서(gyeongjo-grant)와 기본틀 동일** — 모든 입력이 사용자 제공이라 **실행 전 폼**으로
params 를 받고, 그래프는 HITL 없이 무개입 완주(폼값 채움 → F7 저장)한다. 회계(FI) 사용자유형,
딥링크 `/FI/GLDDOC00300`, 진입 앞단 `common/nodes` 재사용. **단건**(학자금 1건 = 결의서 1장,
사용자 확정). 경조금과의 델타: 결의구분 라벨 '학자금신청서'·예산계정 base '복리후생비-기타'·
적요 '학자금-{본인이름}'·**공급가액 = 사용자 입력 금액 그대로(근속<1년 50% 규칙 없음)**.

## 확정된 업무 결정(사용자, 2026-07-15)

- **D1 입력 방식**: ✅ 실행 전 폼(무개입). params 네임스페이스 `hakjagum`.
- **D2 행 구조**: ✅ 단건(1행) — 학자금 1건 = 결의서 1장.
- **D3 결의구분**: **"학자금신청서"** — 라벨 텍스트로 세팅(경조금 55·국내출장 53 과 형제 카탈로그).
  value 코드는 코드에서 미사용 — 검증: ✅ 실측(2026-07-15) **value="56"**(경조금신청서 55 바로 다음),
  라벨 정확 존재·set_result ok. 전체 옵션: 51 세금계산서 ~ 61 클레임보상수익 + 15 수입결의서.
- **D4 회계일자(ACTG_DT)**: ✅ **증빙일자 = 계산서일 = 사용자 입력 단일 날짜** 그대로(단건이라
  max 파생 불필요). compact 'YYYYMMDD'.
- **D5 증빙유형**: ✅ 코드 **10** = **"규정에의한 비용정산"** — 실측(2026-07-15) 팝업 25종 목록에서
  코드/라벨 확인(trip_domestic/경조금 25종 목록과 완전 동일).
- **D6 거래처**: ✅ **작성자 본인 이름 런타임 검색**(경조금 D6 동일 패턴).
- **D7 적요**: ✅ 템플릿 **`학자금-{본인이름}`**(본인이름은 거래처 본인검색 결과 표시명).
- **D8 예산단위/계정**: 부서=신청자 본인 팀(BG_NM) × cost_type (제)/(판) 팀설정, 계정 base
  **"복리후생비-기타"**(경조금 D8 로직 `pick_budget_row` 그대로, base 상수만 교체).
  검증: ✅ 실측(2026-07-15) **(제)복리후생비-기타=BGACCT_CD 511010600 · (판)복리후생비-기타=811010600**
  (계정코드는 부서(BG_CD) 무관 고정 — 부서별로 (제)/(판) 여부만 갈림, 매칭 43행). 피커 검색어 kw는
  초기값 "기타"(270행 중 226행이 여비교통비-기타 등 무관 계정으로 오염) 대신 **"복리후생비"**(444행
  전량 복리후생비-* 계열)로 확정 — `pick_budget_row` 정확매칭이 후필터를 담당.
- **D9 (세금)계산서일**: detail 셀 **`START_DT`** = 증빙일. 검증: ✅ 실측(2026-07-15) detail 컬럼에
  `START_DT`(header "(세금)계산서일", visible) 존재 — 경조금·trip 동형.
- **D10 공급가액(거래금액)**: ✅ **사용자 입력 금액 그대로**(baseAmount → SPPRC_AMT2). **경조금의
  근속<1년 50% 규칙 없음** — 설계판단: 학자금은 규정상 감액 규칙이 없어 계산 함수(supply_amount
  상당)를 아예 두지 않는다(사용자 확정 2026-07-15). 금액 필드 `SPPRC_AMT2` 검증: ✅ 실측(2026-07-15)
  detail 컬럼에 존재(header "공급가액 (거래금액)", visible), 에디터 오버레이도 경조금·trip 동일 함정
  패턴 — 진짜 입력칸 `…_gridDetail_number`(98×29) vs decoy `…_gridDetail_line`(1×1). 쓰기 시
  **실타이핑+Tab+예산현황 확인**(setValue 금지).
- **D11 프로젝트**: ✅ **실행 전 폼 피커 선택**(경조금 동일 — 피커/카탈로그, WBS_NO 정확매칭).
- **D12 상대계정거래처**: ✅ **미사용 확정(2026-07-15 라이브)** — 실저장 11/11 사이클(스모크 1+10)
  모두 상대계정거래처 스텝 없이 F7 저장·영속·삭제가 정상이었고 저장 detail 스트레이 빈 행 0(rows_clean).
  프로브 실측(2026-07-15)에서 `BFC_PARTNER_CD` 는 detail dataSource/컬럼에 visible=false·header 미번역
  "숨은 백킹필드"로만 존재 — 경조금과 동일 패턴. fill 노드는 trip 의 `register_counter_partner`·빈행삭제
  스텝을 쓰지 않는다(경조금 동형). 회귀는 스모크의 `rows_clean`(detail rowcount==1)로 감지.
- **D13 저장**: ✅ F7 저장까지 자동. ⚠ **비가역**. 상신은 사용자가 ERP 에서 직접(**절대 금지**).

## ⚠ 저장·상신·비가역 표시

| 액션 | 비가역 | 게이트 |
|---|---|---|
| F7 저장 `.main-button.save` | ⚠ 비가역 | 전용 save 노드 `confirm=True` 에서만. `BTN_SAVE` 클릭 금지 |
| 증빙/코드피커 모달 **확정 '적용'** 이후 | ⚠ 비가역 | 적용 직전까지 자동, 이후 게이트 |
| F6 삭제·전표취소 | ⚠ 비가역 | 테스트 정리 전용, 가드레일 필수 |
| 상신(결재) | ⚠ 비가역 | **절대 금지** — 사용자 직접 |

## 측정된 셀렉터·필드 표 (v1 — 2026-07-15 읽기 프로브 실측)

| 스텝 | 셀렉터/필드/값 | 검증 | 비가역 |
|---|---|---|---|
| set_gubun | 결의구분 라벨 "학자금신청서" = **value "56"** | ✅ 실측 | |
| 증빙유형 | 코드 10 = "규정에의한 비용정산"(팝업 25종, 경조금·trip 목록과 동일) | ✅ 실측 | |
| 예산단위 | BGACCT_NM "(제)복리후생비-기타"=**511010600** · "(판)…"=**811010600**, kw **"복리후생비"** | ✅ 실측 | |
| 계산서일 | detail `START_DT`(visible, "(세금)계산서일") | ✅ 실측 | |
| 공급가액 | detail `SPPRC_AMT2`, 진짜칸 `…_gridDetail_number`(98×29, decoy `…_line` 1×1) | ✅ 실측 | |
| 상대계정거래처 | **미사용 확정** — fill 에 스텝 없음, 라이브 11/11 저장 정상·스트레이 빈 행 0(`BFC_PARTNER_CD` 숨은 백킹필드) | ✅ 해소(불필요) | |
| detail 그리드 | 84표시컬럼(dataSource 134키) — trip/경조금 기록과 필드 수 일치, SPPRC_AMT2·START_DT·BFC_PARTNER_CD 동일 → trip steps/js 재사용 | ✅ 실측(개수·핵심필드) | |
| save | F7 `.main-button.save` | ✅(공통) | ⚠ 비가역 |

## 남은 작업(flow-buildout 표준절차)

- [x] **단계 2 헤드리스 읽기 프로브**(2026-07-15): D3 value 56·detail 84필드·D5 증빙 10·
      D8 BGACCT_CD 511010600/811010600·kw "복리후생비" 확정·D10 SPPRC_AMT2 확인. D12 만 ❓ 잔존.
- [x] **프로브 결과로 이 MD 보완**(2026-07-15): D3/D5/D8/D9/D10 ❓→✅, D12 증거 기록, `검증 로그` 실측 기록.
      코드 반영: graph.py 주석(value 56)·steps.py `BUDGET_SEARCH_KW="복리후생비"`·smoke `HAKJAGUM_FG="56"`.
- [x] **유닛 그린 유지**: params(passthrough)·bgacct·validate·라벨/그래프/등록·픽스처 lockstep.
- [x] **단계 3 쓰기 프로브 1사이클**(2026-07-15, `hakjagum_smoke_cycle`, 이트라이브2 격리 계정, 게이트
      1회 저장→F6 삭제): **PASS**(run 42.6s, 전표 RN202607150004, SPPRC_AMT2=100001 일치, rowcount=1, 잔존 0).
- [x] **단계 7 라이브 10사이클**(2026-07-15): 실저장→검증→F6 삭제 **10/10 PASS**, avg 40.0s, 전표
      RN202607150005~014, 전 사이클 금액일치·rowcount=1·잔존 0. D12 미사용 확정.
- [x] **픽스처 hidden 해제**(2026-07-15, 경조금 관례): `_HAKJAGUM_GRANT_FIXTURE hidden=False` → 목록/상세
      노출. 프론트 pre-run 폼 `PRE_RUN_FORMS['hakjagum-grant']` 등록 확인.
- [ ] **단계 8 운영**(상시): 셀렉터 드리프트 감지·트레이스·PROCESS.md 버전관리.

## 검증 로그

- 2026-07-15 v0: 사용자 확정(경조금 형제·단건·결의구분 라벨 '학자금신청서'·예산단위 복리후생비-기타·
  적요 학자금-{본인이름}·증빙 10·회계일=계산서일=사용자 입력 단일 날짜·**공급가액=사용자 입력
  그대로, 50% 규칙 없음**·프로젝트 폼 피커·F7 저장/상신 금지). 기술 항목(결의구분 value·detail
  그리드 동형·예산계정 코드·검색어 kw·SPPRC_AMT2·상대계정 유무)은 전부 ❓ — 라이브 프로브 대기.
  코드는 gyeongjo_grant 를 정독 후 클론(js/save 전량 재수출, steps 예산 델타만 재정의,
  params 는 supply_amount/under1Year 제거).
- 2026-07-15 단계 2 읽기 프로브(`hakjagum_probe.py`, read-only, 부작용 0 — F7/적용/더블클릭/행삭제/
  상신 전량 미실행, 저장 없이 close. 계정 이트라이브2, delay_scale 0.4, status **PASS**):
  - **D3 ✅**: 라벨 "학자금신청서" 정확 존재, **value="56"**(경조금 55 바로 다음), set_result ok.
    전체 옵션 12종(51~61 + 15 수입결의서).
  - **D5 ✅**: 증빙 코드 **10="규정에의한 비용정산"**(팝업 25종, trip/경조금 목록과 완전 동일).
    attempt 1 은 고정 600ms wait 직후 덤프해 rows=0(팝업 '데이터 로딩 중' 스피너 — 타이밍,
    SKILL.md #4) → 20회×300ms 조건폴링으로 교체 후 attempt 2 에서 n=25 해소.
  - **D8 ✅**: **(제)복리후생비-기타=BGACCT_CD 511010600 · (판)복리후생비-기타=811010600**(부서
    무관 고정, 부서별 (제)/(판)만 갈림, 매칭 43행). kw "복리후생비"=444행 전량 복리후생비-* 계열 vs
    kw "기타"=270행 중 226행 무관 계정(여비교통비-기타 등) 오염 → **BUDGET_SEARCH_KW="복리후생비"
    확정**(초기값 "기타" 폐기), 정확매칭은 `pick_budget_row` 담당.
  - **D9/D10/컬럼셋 ✅**: detail 84표시컬럼(dataSource 134키) — 경조금 PROCESS.md 기록("trip 과
    84필드 완전 동일")과 개수 일치, `START_DT`·`SPPRC_AMT2`·`BFC_PARTNER_CD` 동일 field/header/
    visible 존재. 단 gyeongjo_probe_results.json 원본이 artifacts 에 남아있지 않아 필드명 1:1 diff 는
    재확인 불가(개수+핵심필드 간접 확인). SPPRC_AMT2 에디터: 진짜칸 `…_gridDetail_number`(98×29,
    value '0') vs decoy `…_gridDetail_line`(1×1) — trip/경조금 함정 패턴 재확인, Escape 로 미커밋 종료.
  - **D12 ❓ 잔존**: `BFC_PARTNER_CD` 숨은 백킹필드(visible=false·header 미번역) 존재, 상대계정
    라벨은 행 추가 전/프로브 종료 시점 모두 미렌더. read-only 라 행 데이터 미채움 — trip 선례상
    위젯은 행 채움 후 렌더되므로 부재 단정 금지. 경조금처럼 **업무 플로우 확인(사용자)** 으로 해소
    필요 — 스모크 단계에서 병행.
  - **부수 실측**: master_grid 21컬럼 덤프(ABDOCU_FG_CD·WRT_EMP_NM 등) — 스모크 삭제 가드레일
    (결의자=로그인계정 + ABDOCU_FG_CD=56 + DOCU_NO 공백) 참조 근거. 아티팩트:
    `e2e/artifacts/hakjagum_probe_*`(results.json·d5_evdn_popup·d8_search_복리후생비/기타·d10_amount_editor).
  - **코드 반영**: graph.py 주석(value 56, 라벨 불변)·steps.py `BUDGET_SEARCH_KW="기타"→"복리후생비"`·
    `hakjagum_smoke_cycle.py` `HAKJAGUM_FG="TODO_PROBE"→"56"`. HAKJAGUM_BGACCT_BASE("복리후생비-기타")
    는 실측 명칭과 정확 일치라 불변. 유닛 그린 재확인.
- 2026-07-15 단계 3 쓰기 프로브 1사이클(`hakjagum_smoke_cycle.py`, 이트라이브2 격리 계정, headless,
  게이트 1회 저장→F6 삭제): **1/1 PASS**(run 42.6s). fill_rows→save_doc 전 스텝 성공·F7 저장→재조회
  지속(전표 **RN202607150004**, 팬텀 저장 아님)·detail `SPPRC_AMT2`=**100001** 입력값과 완전 일치
  (50% 규칙 없음 확인)·detail rowcount=1(스트레이 빈 행 0)·F6 삭제 후 재조회 잔존 0 ✅.
- 2026-07-15 단계 7 라이브 10사이클(`hakjagum_smoke_cycle.py`, `HAKJAGUM_SMOKE_CYCLES=10`, 이트라이브2
  격리 계정, headless): **10/10 PASS**, avg run 40.0s(범위 36.7~45.0s). 전표 **RN202607150005~
  RN202607150014** 채번 — 전 사이클 amount_match=True·detail rowcount=1(스트레이 빈 행 0)·F6 삭제 후
  재조회 잔존 0 ✅(전표 전량 정리 완료, 수동 정리 불필요). 실패 스크린샷 0건, 자가수정 0회.
  아티팩트: `e2e/artifacts/hakjagum_smoke_cycle.json`(11사이클 누적).
- 2026-07-15 **D12 상대계정거래처 미사용 확정**: 스모크 11/11 사이클(1+10) 전부 상대계정거래처 스텝
  없이 저장 성공 + 스트레이 빈 행 0(rows_clean=True) → 상대계정 미사용 결정적 확정(경조금 동형).
  ❓→✅ 승격, fill 노드 무변경(애초 스텝 없음), 회귀는 `rows_clean`(detail rowcount==1)로 감지.
- 2026-07-15 픽스처 hidden 해제(노출, 경조금 관례): `_HAKJAGUM_GRANT_FIXTURE hidden=True→False` →
  목록/상세 노출. 학자금 노출로 hidden=True 픽스처가 0이 돼 숨김 회귀 테스트를 `_HIDDEN_AGENT_IDS`
  주입 방식으로 재구성(픽스처 플래그가 사라져도 라우터 게이트 커버리지 유지) + `test_hakjagum_grant`
  hidden 단언 flip + agents.py/test_permissions.py stale 주석 갱신. 유닛 전체 GREEN.
