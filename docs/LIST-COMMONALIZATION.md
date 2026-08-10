# 리스트 화면 공통화 — 통합 설계·로드맵

> 2026-07-22 확정. 실측(8-agent 전수 판독: FE 6화면 + BE 라우터 10개·모델 22개) 기반.
> 상세 원문: [FE 설계](./LIST-COMMONALIZATION-FE.md) · [BE 설계](./LIST-COMMONALIZATION-BE.md) — 본 문서의 채택 결정이 원문보다 우선한다.

## 배경 · 목표

멤버·감사·로깅·예산단위·프로젝트·거래처 등 "필터 + 페이징 + 테이블(카드)" 리스트 화면이 늘고 있고,
**한 화면에 생기는 새 기능(내보내기·저장 필터·폴링·Skeleton 등)은 대개 전 리스트 화면 공통 기능**이다.
목표는 코드 축소가 아니라 **변경 비용의 1/N화** — 한 곳에 추가하면 전 화면이 받는 구조.

## 실측 진단 요약

### FE (자구 수준 중복 4겹)

| 중복 | 증거 | 규모 |
|---|---|---|
| 서버 페이징 로더 뭉치(Phase 타입+state 5종+loadPage+effect) | audit-client.tsx:55-91 ↔ logs-client.tsx:73-134 | ~35줄×2 |
| loading/error/empty 3분기 삼항(Spinner div 클래스 자구 동일) | members·audit·logs + 잔여 9파일 | ~28줄×3+ |
| 툴바 셸+검색 인풋+초기화 버튼 | members-filter-bar·audit·logs·code-catalog | ~25줄×3.5 |
| 테이블 카드 셸(wrapper/thead 클래스 동일) | members-table:95-97·audit:187-189·logs:230-232 | ~5줄×3 |

부재(grep 0건): 리스트 상태 훅, URL searchParams 동기화(전 화면 새로고침 시 필터 소실 — URL-as-state 규칙 위반 상태), 디바운스 훅, 공용 페이지 응답 타입. skeleton.tsx·filter-chip-bar.tsx·select.tsx 는 importer 0건 방치.

### BE

- envelope 7종 난립: bare list / `{items}` / `{items,total,limit,offset}` / `{logs,total}` / `{runs,total}` / `{items,total,syncedAt}` / `{templates}` — 공용 페이지 스키마 부재(schemas/common.py 는 CamelModel 뿐)
- limit/offset 수동 clamp 3중복(상한 200/200/100 제각각), count+rows 이중 필터 조립 반복
- 횡단 복붙: `_omnisol_password`(runs↔me_codes), reorder 알고리즘, RequireAdmin 별칭, 조직접근 가시성 게이트 이중 구현(runs 가 agents 프라이빗 심볼 직접 import)
- 모델: TimestampMixin 사용처 1곳(3곳 인라인 복붙), UUID PK 보일러플레이트 ~10곳, PK 스타일 4종 혼재, access_logs.status 필터 컬럼 미인덱스
- 테이블 자체가 없는 도메인: 거래처·프로젝트관리·예산단위·업무(전부 FE 픽스처)

## 채택 아키텍처

### FE — 훅 2 + 부품 4 (갓컴포넌트 `<ListPage>`·컬럼정의형 DataTable 기각)

| 파일 | 역할 |
|---|---|
| `src/hooks/use-list-params.ts` | 필터·검색 디바운스(250ms)·페이지 + **URL 동기화 상시**(`window.history.replaceState` — router.replace 는 RSC 재요청 유발로 기각). 필터 변경 시 page 1 자동 리셋. 정렬 없음(첫 요구 시 `sort` 예약 키로 확장) |
| `src/hooks/use-paged-query.ts` | 서버 페이징 로더. 정규형 `Page<T>{rows,total}` — 응답 키 이원화(logs/runs/items)는 화면별 어댑터 1줄로 흡수. fetcher `null`=권한 게이트 |
| `src/components/ui/search-input.tsx` | 검색 인풋+RiSearchLine (자구 중복 3.5곳) |
| `src/components/ui/list-toolbar.tsx` | 툴바 셸+초기화 버튼 — **공통 기능 1차 착지점**(CSV·저장 필터 등) |
| `src/components/ui/table-card.tsx` | 테이블 셸(thead 클래스 소유·a11y) + `tableRowClass`. tbody 는 화면 자유(확장행·체크박스·인라인 편집 수용) |
| `src/components/ui/list-state.tsx` | loading/error/empty 3분기 + LockedEmptyState — Skeleton 전환 시 1파일 수정=전 화면 반영 |

미래 공통 기능 착지 매핑: URL 공유→useListParams · CSV/저장필터→ListToolbar · 폴링→usePagedQuery 옵션 · Skeleton→ListStatePanel · 페이지 크기→Pagination+useListParams · 정렬→`sort` 키+Th(요구 발생 시).

**공통화 금지**(도메인 소유 유지): 멤버 낙관 업데이트·롤백·벌크, logs 행 확장(RunRow), 선택 체크박스, 카탈로그 폴링·즐겨찾기, projects/works 상태 칩(마크업 상이 — 디자인 의도), 검색 매칭 필드 선택, 조직 트리 SelectGroup(members 로컬 추출이 올바른 스코프).

### BE — `app/core/listing.py` 레일 + envelope 표준 + 믹스인

```
PageQuery  = Annotated[PageParams, Depends(page_params)]  # limit/offset Query(ge/le) 검증 통일
paginate(db, stmt, page)   # rows 쿼리에서 count 파생 — 필터 이중 조립의 원인 소멸
page_slice(rows, page)     # 인메모리 경로(/me/catalog) envelope 통일
```

- envelope 표준: `ListOut[T]{items,total}` / `ListPage[T]{items,total,limit,offset}` (schemas/common.py). **limit/offset 확정**(page/size 아님 — 현행 3개 엔드포인트+FE 클라이언트 전부 limit/offset, churn 0)
- 상수: DEFAULT_LIMIT=50, MAX_LIMIT=200. **/runs 상한 100→200 통일(의도 결정)**
- 모델: `UuidPkMixin` 신설, 인라인 타임스탬프 3곳 TimestampMixin 수렴 — **DDL no-op, `alembic check` 빈 diff 검증 강제**. PK 정책 3종 공인(신규 기본=UUID surrogate, 슬러그 PK·클라 생성 id 신규 도입은 설계 리뷰 필수). boolean server_default 신규는 `sa.false()`
- 서비스 3버킷: 레일 위 ~15줄 조회=라우터 유지 / 2개 라우터 이상 공유=서비스 승격(가시성 게이트 1순위) / 도메인 무관 횡단=core(RequireAdmin→core/deps, 옴니솔 자격증명→core/creds, reorder→services/ordering)
- 인덱스 규칙(신규 테이블 체크리스트): 필터 where 대상→단독 인덱스 검토, 정렬 키→인덱스 필수, 소유자 스코프→(user_id,…) 복합

## 채택하지 않은 것 (비평 반영 — 근거 포함)

1. **정렬 레일(apply_sort) 보류** — 정렬 UI/파라미터 사용처가 전 스택 0. 표기법만 합의: 도입 시 wire 는 `sort=-camelCase` 단일 파라미터(예: `-loggedAt`), 화이트리스트+인덱스 필수.
2. **bare list 4종(/users·/org-units·/agent-access·/agents) envelope 소급 전환 취소** — 실익이 형태 통일뿐, 비용은 파괴 변경+이중배포 조율. 신규 엔드포인트부터 ListOut/ListPage 적용.
3. **useClientPage 공용 훅 취소** — 사용처 1곳(members)+서버 페이징 전환 시 소멸 예정. members 로컬 유틸로.
4. **필터 조립 DSL·Repository 계층·컬럼정의형 DataTable·SoftDeleteMixin·기존 테이블 타임스탬프/CHECK 소급** — 전부 투기적 일반화로 기각.
5. **page/size 페이지네이션 스킴** — 기각. limit/offset 이 기존 계약.

## 이행 로드맵 (각 Phase 독립 배포·롤백 단위)

| Phase | 작업 | 상태 |
|---|---|---|
| P0 | FE 훅2+부품4 신설 + BE core/listing.py·ListOut/ListPage 신설(기존 무접촉) | 2026-07-22 착수 |
| P1 | /audit 첫 적용 + BE /logs paginate 편입·`items` 키 병기(dual-key, 구 키 유지) | 〃 |
| P2 | /logs 화면 적용 + /runs `items` 병기 → FE 는 `items ?? 구키` 관용 리더로 전환 | 〃 |
| P3 | /members: useListParams(URL)+로컬 슬라이스, 낙관·벌크·드로어 불변 | 〃 |
| P4 | BE 횡단 정리(deps·creds·ordering·visibility) + 모델 믹스인 수렴(no-op 검증) | 〃 |
| P5 | manage 카탈로그 3형제 + 잔여 화면(org-access·agent-access·agent-settings·agents-client 등) ListStatePanel 편입 | 〃 |
| P6 | 신규 도메인 온보딩: 거래처 → 프로젝트관리 → 예산단위(관리 요구 확정 시). 레일 위 라우터 ~25줄 | 대기 |

구 키(`logs`/`runs`) 제거는 FE 전환 배포 확인 후 별도 커밋으로(이중 배포 혼재 윈도 보호).

## 구현 기록 · 의도된 편차 (2026-07-22 P0~P5 구현분)

교차 리뷰(FE 7건·BE 3건)에서 확인·수용된 계약 변화. 전부 의도된 결정이다:

1. **/runs 계약 변화**: 수동 clamp→422(범위 밖 거절), 상한 100→200, **기본 limit 20→50** — 레일 통일(DEFAULT_LIMIT=50/MAX_LIMIT=200). 리포 내 FE 소비처는 전부 limit 명시라 실해 없음.
2. **에러 패널 시맨틱**: 교체 전 audit/logs 는 에러 시 기존 rows 가 있으면 스테일 테이블을 무통지 유지했으나, ListStatePanel 은 항상 에러 패널+다시 시도를 표시 — 재시도 접근성 개선으로 채택.
3. **검색 인풋 시각 통일**: works·manage 카탈로그의 검색창이 SearchInput 필 형태(h-9 rounded-full)로 정규화됨(교체 전엔 h-10 사각) — 의도된 통일.
4. **usePagedQuery 내장 보강 2건**: 요청 세대 카운터(reload 포함 전 경로의 늦은 응답 무시), 스테일 URL page 오버플로 시 마지막 페이지 자동 클램프(opts.setPage 전달 시).
5. **members**: 클라이언트 매칭 화면이라 `searchDebounceMs: 0`(즉시 필터 체감 보존). effectivePage 클램프는 데이터 도착 후에만(URL page 복원 보호).
6. **URL 필터값은 미검증**: 조작/오타 URL(`?role=x`)은 매칭 0건으로 무해 강등, 초기화 버튼으로 복구 — 허용값 검증은 첫 실요구 시.
7. **P5b 미편입 화면과 사유**: org-access(에러 문구가 errorMessage 403 매핑 + 빈 상태가 툴바 중첩 구조), agent-settings·manage-agents-group·agent-access(에러 문구 불일치·이중 리소스 합성 로딩) — 권한 게이트만 LockedEmptyState 채택. 문구 정책 통일 후 재편입 후보.
8. **알려진 별도 과제**: (a) DB↔모델 선언 드리프트 8건(유니크 제약·인덱스 — 이번 변경과 무관, `alembic check` 상시 FAILED 원인. autogenerate 사용 전 반드시 대사 정리). (b) logs 화면 WORKFLOW_LABEL 하드코딩 맵(라벨 소스 이원화). (c) members invite-dialog.tsx 고아 파일.

## 신규 리스트 화면/엔드포인트 작성 규칙 (요약)

- FE: useListParams + (서버 페이징이면) usePagedQuery + ListToolbar/SearchInput/ListStatePanel/TableCard 조합. 행 렌더·도메인 로직만 화면 소유.
- BE: 모델은 `UuidPkMixin+TimestampMixin`, 응답은 `ListPage[Out]`(페이지) 또는 `ListOut[Out]`(전량), 라우터는 `PageQuery`+`paginate` 레일 사용. 수제 clamp·수제 camelCase dict 금지.
