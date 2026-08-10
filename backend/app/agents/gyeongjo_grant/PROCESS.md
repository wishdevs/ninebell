# 경조금신청서 결의서입력 — 프로세스 정의 (gyeongjo-grant)

> 결의서입력(GLDDOC00300) 문서 종류 중 **경조금신청서**. 패밀리 인덱스: [../RESOLUTIONS.md](../RESOLUTIONS.md).
> 상태: **v1.0 — 완성. 단계 0~8 완주(2026-07-13). 라이브 실저장 10/10 PASS·avg 38.3s·잔존 0,
> 프론트 pre-run 폼(gyeongjo-pre-run-form) 등록·params/50%(ROUND_HALF_UP) 백엔드 일치 검증,
> 픽스처 hidden 해제(노출). 유닛 463 pass. 남은 상시작업: 운영 모니터링(단계 8).**
> 형제(기본틀 동일): [../trip_domestic/PROCESS.md](../trip_domestic/PROCESS.md) · [../trip_overseas/PROCESS.md](../trip_overseas/PROCESS.md).

## 개요

**국내 출장(trip-domestic)과 기본틀 동일** — 모든 입력이 사용자 제공이라 **실행 전 폼**으로 params 를
받고, 그래프는 HITL 없이 무개입 완주(폼값 채움 → F7 저장)한다. 회계(FI) 사용자유형, 딥링크
`/FI/GLDDOC00300`, 진입 앞단 `common/nodes` 재사용. **단건**(경조사 1건 = 결의서 1장)으로 가정 —
검증: ❓(다건 배치 필요 여부 사용자 확인).

## 확정된 업무 결정(사용자, 2026-07-13)

- **D1 입력 방식**: ✅ 실행 전 폼(무개입). params 네임스페이스 `gyeongjo`.
- **D2 행 구조**: ✅ 단건(1행, 사용자 확정) — 경조사 1건 = 결의서 1장.
- **D3 결의구분**: "경조금신청서" = **value 55** ✅(2026-07-13 실측 `gyeongjo_probe.py`, 라벨 완전일치).
- **D4 회계일자(ACTG_DT)**: ✅ **증빙일자 = 사용자 입력**(출장처럼 max 파생 아님, 단건이라 그 값 그대로). compact 'YYYYMMDD'.
- **D5 증빙유형**: ✅ 코드 **10** = **"규정에의한 비용정산"**(2026-07-13 실측, trip 25종 목록과 동일).
- **D6 거래처**: ✅ **작성자 본인 이름 런타임 검색**(출장 해외 D6 동일 패턴).
- **D7 적요**: ✅ 템플릿 **`경조금-{본인이름}`**.
- **D8 예산단위/계정**: ✅ **본인 팀 기준(출장과 완전 동일, 사용자 확정 2026-07-13)** — 부서=신청자
  본인 팀(BG_NM) × cost_type (제)/(판) 팀설정, 계정 base **"복리후생비-경조"**. 출장 D8 로직
  (`pick_budget_row` 등) 그대로, `TRIP_BGACCT_BASE` 상당 상수만 `"복리후생비-경조"`로 교체.
  (실측: "2005"는 계정코드 아닌 부서코드(회계팀)였고 사용자 확인 결과 **예시** — 실제 계정
  (제)511007600 / (판)811007600 은 본인 팀별로 달라짐. 검색어 kw="경조".)
- **D9 (세금)계산서일**: detail 셀 **`START_DT`** = 증빙일 ✅(2026-07-13 실측, detail 컬럼 trip과 완전 동일).
- **D10 공급가액(거래금액)**: ✅ **총 금액 입력**. **근속 1년 미만 → 50%**(아래 D10-a). 금액 필드
  = **`SPPRC_AMT2`** ✅(2026-07-13 실측, trip 동일 — 진짜칸 `…_gridDetail_number` vs decoy `…_line`).
  쓰기 시 **실타이핑+Tab+예산현황 확인**(setValue 금지 §1).
  - **D10-a 근속 1년 미만 50% 처리** ✅(사용자 확정 2026-07-13): 폼 입력 = ①경조금 정액(총액,
    **사용자 입력** — 규정표 자동 아님) + ②`근속 1년 미만?` 예/아니오(기본 아니오). 처리:
    아니오 → 공급가액=정액 / 예 → 공급가액 = **정액 × 0.5, 원 단위 사사오입(Decimal ROUND_HALF_UP)**
    — 파이썬 내장 round()(은행가) 금지, trip `fuel_support_amount` 와 동일. 예: 100001→50001.
    **params.py 에서 계산**(국내출장 유류비 계산과 동일 위치), 폼 요약에 최종 공급가액 미리 표시.
    단위테스트로 예→반값·원단위 반올림 검증. **라이브 실측(2026-07-13, `gyeongjo_smoke_cycle.py` 1
    사이클)**: baseAmount 100001·under1Year True 입력 → 저장된 detail `SPPRC_AMT2`=50001 로 기대값과
    완전 일치 ✅(팬텀 저장 아님, F2 재조회로 영속 확인). 실저장 경로까지 확정.
- **D11 프로젝트**: ✅ **국내 출장과 동일** — 피커/카탈로그, WBS_NO 정확매칭. 기본값=팀 비용구분
  프로젝트(제조원가→500 / 판관비→800, `/me/trip-defaults`), 다른 프로젝트 선택 가능.
- **D12 상대계정거래처**: ✅ **경조금엔 불필요(2026-07-13 사용자 확정)** — 사용자 플로우 목록에
  상대계정거래처가 없었고(거래처=본인만, D6), 1사이클 실측에서 상대계정 없이 F7 저장·영속·삭제가
  정상이었다. fill 노드에서 trip 상속분(`register_counter_partner` + 그 부작용 빈행 삭제
  `delete_blank_row`)을 **제거**(유닛 30 pass). (참고: 1사이클에서 `BFC_PARTNER_CD` 공란이었던 것은
  애초 이 필드가 확인 대상이 아니었고 경조금이 상대계정을 안 쓰기 때문 — 이슈 아님.)
- **D13 저장**: ✅ F7 저장까지 자동. ⚠ **비가역**. 상신은 사용자가 ERP 에서 직접. **라이브 실측
  (2026-07-13, `gyeongjo_smoke_cycle.py` 1사이클)**: F7 저장 성공(`save_document confirm=True` 게이트)
  → F2 재조회 지속(팬텀 저장 아님, ABDOCU_NO 채번 RN202607130004) → 가드레일 통과(WRT_EMP_NM=
  이트라이브2·ABDOCU_FG_CD=55·DOCU_NO 공백) → F6 삭제 → 재조회 잔존 0 ✅.

## 확정 플로우(사용자 구술, 2026-07-13)

1. **추가**(add_row, 공유 진입 앞단).
2. **결의구분**: 경조금신청서(D3).
3. **회계일**: 증빙일자 = 사용자 입력(D4).
4. **증빙선택**: 코드 10(D5).
5. **거래처**: 본인 이름 선택(D6).
6. **적요**: `경조금-{본인이름}`(D7).
7. **예산단위**: 2005 복리후생비-경조, 제조/판관 팀설정(D8).
8. **공급가액**: 총 금액(근속 1년 미만 시 50% — D10/D10-a).
9. **프로젝트**: 국내출장과 동일, 기본 500/800(D11).
10. **저장**: F7(D13). ⚠ 비가역.

## ⚠ 저장·상신·비가역 표시

| 액션 | 비가역 | 게이트 |
|---|---|---|
| F7 저장 `.main-button.save` | ⚠ 비가역 | 전용 save 노드 `confirm=True` 에서만. `BTN_SAVE` 클릭 금지 |
| 증빙/코드피커 모달 **확정 '적용'** 이후 | ⚠ 비가역 | 적용 직전까지 자동, 이후 게이트 |
| F6 삭제·전표취소 | ⚠ 비가역 | 테스트 정리 전용, 가드레일 필수 |
| 상신(결재) | ⚠ 비가역 | **절대 금지** — 사용자 직접 |

## 측정된 셀렉터·필드 표 (2026-07-13 단계 2 프로브 실측 — `e2e/gyeongjo_probe.py`)

| 스텝 | 셀렉터/필드/값 | 검증 | 비가역 |
|---|---|---|---|
| set_gubun | 결의구분 "경조금신청서" = **value 55** | ✅ 실측 | |
| 증빙유형 | 코드 10 = **"규정에의한 비용정산"**(trip 25종 동일) | ✅ 실측 | |
| 예산단위 | BGACCT_NM **"(제)/(판)복리후생비-경조"**(511007600/811007600). ⚠ "2005"=부서코드(회계팀), 계정코드 아님 | ◐ D8 매칭키 사용자 확인 | |
| 계산서일 | detail `START_DT` | ✅ trip 컬럼 동일 | |
| 공급가액 | detail **`SPPRC_AMT2`**, 진짜칸 `…_gridDetail_number`(decoy `…_line`) | ✅ 실측(trip 동일) | |
| 상대계정거래처 | **경조금 불필요** — fill 에서 제거(register_counter_partner·빈행삭제, 사용자 확정) | ✅ 해소(불필요) | |
| detail 그리드 | trip_domestic과 **84필드 완전 동일**(동일 GLDDOC00300 스키마) → trip steps/js 재사용 | ✅ 실측 | |
| save | F7 `.main-button.save` | ✅(공통) | ⚠ 비가역 |

## 남은 작업(flow-buildout 표준절차)

- [x] **필수 입력 마감**: 계정 `이트라이브2`/`1111`(읽기 프로브 + 쓰기 테스트 계정, 사용자 확정 2026-07-13).
- [x] **D10-a 확정**: 50% 예/아니오 + 원 단위 반올림, 정액 사용자 입력(사용자 확정 2026-07-13).
- [x] **단계 2 헤드리스 프로브**(2026-07-13, read-only): D3=55·detail trip 완전동일·D5·D10 SPPRC_AMT2·
      D8 계정명·D12 BFC_PARTNER_CD 존재 확인. trip_domestic·nbkit·common/nodes 프리미티브 재사용.
- [x] **D8 매칭키 확정**: 본인 팀 기준(출장 동일), 계정 base "복리후생비-경조", kw="경조"(2026-07-13 사용자 확정).
- [x] **단계 3 쓰기 프로브 1사이클**(2026-07-13, prober, 테스트 계정, 게이트 1회 저장→F6 삭제):
      영속 검증 완료. D10-a 반올림 저장 일치 ✅, D12 미해소(❓) — 아래 검증 로그.
- [x] **단계 4 자가수정**(1사이클분): D10-a·D13 ❓→✅ 승격, D12 는 새 증거로 ◐→❓ 재분류, 이 MD 보완.
- [x] **단계 5-6 코드**(2026-07-13): params(50%·단건·회계일=증빙일)·steps·js·nodes·graph·
      register_workflow("gyeongjo-grant", delay_scale=0.4)·agent_fixtures(hidden=True) + tests.
      유닛 28 + 전체 457 pass. trip 프리미티브 최대 재사용(js/save 전량 재수출).
- [x] **코드리뷰·수정**(2026-07-13): HIGH 2(반올림 ROUND_HALF_UP·fill 노드테스트 3건)+MED 1(_COST_PREFIX 중복) 해소. 유닛 30 + 전체 463 pass. CRITICAL 0.
- [x] **D12 확정**: 경조금 상대계정거래처 불필요(사용자 확정 2026-07-13) — fill 스텝 제거, 유닛 30 pass.
- [x] **단계 7 라이브 10사이클**(2026-07-13): `e2e/gyeongjo_smoke_cycle.py`(`GYEONGJO_SMOKE_CYCLES=10`)
      실저장→검증→F6 삭제 **10/10 PASS**, avg run 38.3s, 잔존 전표 0. 사이클별 .5 경계값(50%)·정액
      그대로(반올림 미적용) 저장값 전량 일치, detail 행수 전 사이클 1(스트레이 빈 행 0).
- [x] **프론트 pre-run 폼**(2026-07-13): `gyeongjo-pre-run-form.tsx`(증빙일+정액+근속토글+**50% 미리보기**
      +프로젝트 catalog-combobox) 작성, `PRE_RUN_FORMS['gyeongjo-grant']` 등록. overseas 포팅. params 형태·
      50% ROUND_HALF_UP 백엔드 일치(워크플로우 검증 0건). typecheck·`next build` green. dept/cost_type 은
      서버 세션 주입(클라 strip)이라 폼은 `{gyeongjo}`만 전송.
- [x] **픽스처 hidden 해제**(2026-07-13): `_GYEONGJO_GRANT_FIXTURE hidden=False` → 목록/상세 노출.
      숨김 회귀 테스트를 학자금 기준으로 갱신, 유닛 463 pass. (라이브 검증·프론트 폼 완료 후 노출.)
- [ ] **단계 8 운영**(상시): 셀렉터 드리프트 감지·트레이스·PROCESS.md 버전관리.

## 검증 로그

- 2026-07-13 v0: 사용자가 업무 플로우 전체 구술(국내출장 형제·단건·예산단위 2005 복리후생비-경조·
  적요 경조금-{이름}·증빙10·회계일=증빙일·근속<1년 50%). 화면=회계 결의서입력 확정(가정 아님).
  기술 항목(결의구분 value·컬럼·금액필드·예산명칭·상대계정 유무)은 전부 ❓ — 단계 2 프로브 대기.
- 2026-07-13 확정: D2 단건 ✅ · D10-a 50% 예/아니오+원단위 반올림·정액 사용자입력 ✅ · 계정
  이트라이브2/1111 ✅. → 단계 2 읽기 프로브 착수(omnisol-flow-prober 위임).
- 2026-07-13 단계 2 읽기 프로브(`gyeongjo_probe.py`, read-only, 부작용 0, F7·적용·삭제 미실행):
  D3=55 · detail 84필드 trip 완전동일 · 증빙10="규정에의한 비용정산" · 공급가액 `SPPRC_AMT2` ·
  `BFC_PARTNER_CD` 존재 ✅. **재사용**: trip_domestic 진입앞단·nbkit js_lib(OPEN_DETAIL_CELL_EDITOR_JS·
  DETAIL_EDITOR_MAGNIFIER_JS·PICKER_*·OPEN_EVDN_EDITOR_JS)·common/nodes 그대로, 결의구분만 교체.
  **미해소**: D8 "2005"=부서코드(회계팀)로 실측 → 사용자 확인 대기. D12 UI 렌더는 단계 3으로 이관.
  아티팩트: `e2e/artifacts/gyeongjo_probe_*`.
- 2026-07-13 단계 5-6 코드화(trip_domestic 포팅, 위임): gyeongjo_grant 패키지 + register_workflow
  + agent_fixtures(_GYEONGJO_GRANT_FIXTURE, hidden=True) + tests. 유닛 28 + 전체 457 pass, 0 실패.
  **재사용**: js.py·nodes/save.py trip 전량 재수출, steps.py 예산 델타(GYEONGJO_BGACCT_BASE="복리후생비-경조"
  ·kw"경조")만 재정의. **신규**: params(단건·supply_amount 50% round)·fill(단건 축약·적요 경조금-{이름})·
  graph(value55). GyeongjoGrantState 전 반환키 선언 확인. **미해결**: D12 UI 렌더·단계 3/7 라이브 대기.
- 2026-07-13 코드리뷰(code-reviewer)→수정: HIGH#1 50% 반올림이 내장 round()(은행가)라 사사오입과
  갈림 → Decimal ROUND_HALF_UP 로 교체(trip fuel_support_amount 동일, 100001→50001 강제 테스트).
  HIGH#2 fill 노드 유닛테스트 3건 추가(성공·필드실패단락·self_name 가드, assert_keys_declared).
  MED _COST_PREFIX trip import 재사용. 유닛 30 + 전체 463 pass, CRITICAL 0. supply_amount 직접 검증 완료.
- 2026-07-13 단계 3/7 라이브 쓰기 프로브 1사이클(`gyeongjo_smoke_cycle.py` 포팅, trip_smoke_cycle.py
  구조·안전수칙 그대로, 위임): 계정 이트라이브2/1111·GYEONGJO_FG=55·baseAmount 100001·under1Year
  True(기대 supply 50001)·department 인사/기획팀·cost_type 판관비. **결과 1/1 PASS**(run 42.6s):
  fill_rows→save_doc 전 스텝 성공(errors=[])·F7 저장→F2 재조회 지속(ABDOCU_NO RN202607130004,
  팬텀 저장 아님)·detail `SPPRC_AMT2`=50001 **기대값과 완전 일치**(D10-a 라이브 확정 ✅)·가드레일
  통과(WRT_EMP_NM=이트라이브2·ABDOCU_FG_CD=55·DOCU_NO 공백)·F6 삭제→재조회 잔존 0 ✅(전표 정리 완료,
  수동 정리 불필요). **미해소(D12)**: 저장된 detail 행 `BFC_PARTNER_CD`=''(공란) — 원인분류 "숨은
  백킹필드"(SKILL.md #2)로 추정: 코드 확인 결과 gyeongjo fill 노드는 애초 `register_counter_partner`
  (하단 부가선택 DOM 위젯 🔍→검색→더블클릭)만 호출하고 `set_counter_partner`(BFC_PARTNER_CD
  setValue)는 trip_domestic 자체 문서상 폐기 경로라 미사용 — `BFC_PARTNER_CD` 검사 자체가 잘못된
  신호일 가능성 높음. `fill_rows`가 info 로그를 방출하지 않아(에러 레벨만 캡처) skip 여부 미분리,
  이미 삭제되어 재확인 불가. **다음 시도**: 같은 1사이클을 (1) info 레벨 이벤트 캡처 추가 (2) 저장
  직후·삭제 전 `js.COUNTER_VALS_JS` 로 화면표시값(본인 이름) 판독 추가해 재실행 — 사용자 승인 후
  진행(1사이클 STOP 지시 준수, 브루트포스 금지). 10사이클 확장도 사용자 승인 대기.
  재사용: trip_smoke_cycle.py 구조 100%(query_master/verify_and_delete/e2e_smoke 덤프 JS·
  MODALS_SNAPSHOT_JS), trip_smoke_cycle 의 detail 덤프 JS(SPPRC_AMT2/BFC_PARTNER_CD 포함) 그대로.
  아티팩트: `e2e/artifacts/gyeongjo_smoke_cycle.json`. 신규 파일: `e2e/gyeongjo_smoke_cycle.py`.
- 2026-07-13 사용자 확정: **경조금 상대계정거래처 불필요** → fill 노드에서 `register_counter_partner`
  ·`delete_blank_row` 제거(유닛 30 pass 유지). D12 검증 필요성 자체가 소멸(BFC_PARTNER_CD 판독 불요).
- 2026-07-13 단계 7 라이브 10사이클(`gyeongjo_smoke_cycle.py`, `GYEONGJO_SMOKE_CYCLES=10`, 위임):
  스크립트 델타 — (1) `_DETAIL_DUMP_JS`에서 BFC_PARTNER_CD/PARTNER_NM 제거(더 이상 의미있는 신호
  아님) (2) `_cycle_params`를 `_CYCLE_PLAN`(baseAmount·under1Year 10쌍) 기반으로 재작성 — under1Year
  True 5쌍은 **.5 반올림 경계값**(100001→50001·300001→150001·250001→125001 은 사용자 지정 예시,
  71001→35501·133333→66667 추가) ROUND_HALF_UP 검증, False 5쌍(84000·125000·99999·200002·64001)은
  정액 그대로 저장 검증 (3) `rows_clean = detail.get("n")==1` 로 스트레이 빈 행 0 검증(D12 스텝 제거
  회귀 감지) (4) cycle 1 안전 게이트(금액 불일치·스트레이 행 시 즉시 중단) 추가. project 는 코드베이스
  전역에서 라이브 검증된 유일한 값(1310|1310·포장개선, trip_smoke_cycle 등과 공유)으로 고정 — 대체
  프로젝트(비용구분 기본값 800 계열)는 DB 카탈로그 조회일 뿐 ERP 피커 검색 실측이 없어 회귀와 무관한
  실패 위험 때문에 도입하지 않음(신규 발명 금지, trip_smoke_cycle 도 project 고정).
  **결과: 10/10 PASS**(run 36.6~40.0s, avg 38.3s). 사이클별 `SPPRC_AMT2` 전량 기대값과 일치(50001·
  84000·150001·125000·125001·99999·35501·200002·66667·64001) · detail 행수 전 사이클 정확히 1
  (스트레이 빈 행 0, D12 제거 확인) · 가드레일 전량 통과(WRT_EMP_NM=이트라이브2·ABDOCU_FG_CD=55·
  DOCU_NO 공백) · F6 삭제 후 재조회 잔존 0 ✅(전표 RN202607130006~015 전량 정리 완료, 수동 정리
  불필요) · cycle 1 안전 게이트 미발동(정상 통과) · 사이클 중단 0회.
  아티팩트: `e2e/artifacts/gyeongjo_smoke_cycle.json`. **D12는 이제 검증 대상에서 제외**(불필요로
  확정) — 남은 것은 프론트 pre-run 폼 + 픽스처 hidden 해제.
