# 리스트 공통화 — FE 상세 설계 (원문)

> 2026-07-22 실측 기반 설계 원문. 채택 결정·수정사항은 [LIST-COMMONALIZATION.md](./LIST-COMMONALIZATION.md) 가 우선한다.
> 원문 대비 채택 변경: useClientPage 훅은 공용 훅이 아니라 members 로컬 유틸로 강등, useListParams 의 syncToUrl 옵션 제거(상시 on), URL 기록은 router.replace 가 아니라 window.history.replaceState.

# 리스트 화면 공통화 아키텍처 제안

> 대상: /members·/audit·/logs·/manage/*(카탈로그 3형제)·/works·/projects
> 핵심 요구: **"멤버에 새 기능이 생기면 대개 전 리스트 화면 공통 기능이다 — 한 곳에 추가하면 전 화면이 받는 구조."**
> 원칙: 이 리포의 KISS/YAGNI 규칙에 따라 **자구 수준 중복이 실측된 것만** 추상화한다. 패턴만 유사한 것은 화면 소유로 남긴다.

---

## 0. 진단 요약 (직접 검증 완료)

세 운영 화면(멤버·감사·로깅)의 중복은 크게 4겹이다. 전부 파일을 직접 읽어 확인했다.

| 중복 계층 | 증거 | 규모 |
|---|---|---|
| 서버 페이징 로더 보일러플레이트 (Phase 타입+상태 5종+loadPage+effect) | audit-client.tsx:46,55-61,63-91 ↔ logs-client.tsx:41,73-80,108-134 — 거의 자구 동일 | ~35줄×2 |
| loading/error/empty 3분기 삼항 (Spinner div 클래스 문자열까지 동일) | members-client.tsx:291-312,340-350 · audit-client.tsx:157-184 · logs-client.tsx:200-227 | ~28줄×3 |
| 툴바 셸+검색 인풋+초기화 버튼 (클래스 문자열 자구 동일) | members-filter-bar.tsx:57-71,127-136 · audit-client.tsx:115-129,144-153 · logs-client.tsx:157,188-197 · code-catalog-manager.tsx:362-374 | ~25줄×3.5 |
| 테이블 카드 셸 (wrapper/table/thead 클래스 동일, min-w만 상이) | members-table.tsx:95-97 · audit-client.tsx:187-189 · logs-client.tsx:230-232 | ~5줄×3 |

부재 확인(grep 0건): `useSearchParams`, `DataTable`, `Paginated`, 디바운스 훅. `src/hooks/`에는 use-permissions.ts 1개뿐.

---

## 1. 리스트 상태 훅 — 3개로 분리 소유

한 개의 만능 훅이 아니라 **파라미터 소유 / 서버 페칭 / 클라 슬라이스**를 분리한다. 이유: members는 낙관적 편집 때문에 데이터를 로컬 useState로 복제 소유하고(members-client.tsx:56,68-70), audit/logs는 서버가 데이터를 소유한다. 데이터 소유권이 다른 화면에 같은 페칭 훅을 강제하면 낙관 업데이트와 충돌한다.

### 1-a. `useListParams` — 필터·검색 디바운스·페이지 + URL 동기화

`src/hooks/use-list-params.ts` (신규)

```ts
interface ListParamsConfig<F extends Record<string, string>> {
  /** 필터 키와 기본값 — 예: { status: 'all', agent: 'all' }. 기본값과 같으면 URL에서 제거. */
  filters: F;
  /** 검색어 디바운스 ms. 기본 250. 검색이 없는 화면은 searchInput을 안 쓰면 됨. */
  searchDebounceMs?: number;
  /** URL searchParams 동기화. 기본 true. */
  syncToUrl?: boolean;
}

interface ListParams<F extends Record<string, string>> {
  /** 인풋 즉시값 — <SearchInput value>에 바인딩. */
  searchInput: string;
  setSearchInput: (v: string) => void;
  /** 디바운스 안정화된 검색어 — 요청/필터링에 쓰는 값. */
  search: string;
  filters: F;
  setFilter: <K extends keyof F>(key: K, value: F[K]) => void;
  page: number;               // 1-indexed, Pagination과 동일 규약(pagination.tsx:7-8)
  setPage: (page: number) => void;
  /** 기본값과 다른 조건이 하나라도 있는가 — 초기화 버튼 노출·빈 상태 문구 분기에 사용. */
  isFiltered: boolean;
  reset: () => void;
}

export function useListParams<F extends Record<string, string>>(
  config: ListParamsConfig<F>,
): ListParams<F>;
```

**내장 규칙 (지금 화면들이 손으로 하던 것):**
- 필터 변경·검색 안정화 시 page를 1로 자동 리셋 — members-client.tsx:88-90의 effect, audit/logs의 "loadPage 재생성→1페이지 재조회"(logs-client.tsx:131-134)를 대체.
- 검색 디바운스 내장 — audit의 effect 인라인 250ms(audit-client.tsx:87-91), 카탈로그의 queryInput/query 분리+300ms(code-catalog-manager.tsx:94-95,170-176)를 흡수. 별도 useDebounce 훅은 만들지 않는다(사용처가 이 훅 내부뿐 — YAGNI).
- **정렬은 넣지 않는다.** 실측상 6개 화면 전부 정렬 UI/로직이 없다(멤버 "정렬 없음", audit/logs는 서버 최신순 고정 — audit-client.tsx:50-51 주석, runs-api.ts:156 주석). 첫 정렬 요구가 생길 때 filters와 같은 방식의 `sort` 예약 키로 확장한다. 지금 넣는 것은 명백한 투기적 일반화.

**URL 동기화 판단: 한다(기본 on).** 근거:
1. 이 리포의 web/patterns.md 규칙이 "URL As State: filters·sort·pagination·active tab·search query"를 명시한다.
2. 현재 `useSearchParams` 사용 0건(grep 확인) — 모든 목록 상태가 새로고침/공유 시 소실되는 것은 규칙 위반 상태다.
3. 구현: 초기값은 searchParams에서 읽고, 변경은 `router.replace(pathname+'?'+qs, { scroll: false })` — push가 아닌 replace로 히스토리 오염 방지. 기본값과 같은 키는 URL에서 제거해 깨끗한 URL 유지. **검색은 디바운스 안정화 후에만 URL에 기록**(타이핑마다 라우터 호출 금지).
4. 주의: useSearchParams는 Suspense 경계를 요구한다. 현재 page.tsx는 클라이언트를 직접 렌더하므로(audit/page.tsx:15-17 확인) 마이그레이션하는 page.tsx마다 `<Suspense>` 래핑이 1줄 추가된다.
5. `syncToUrl:false` 옵션은 남긴다 — 드로어 내부 목록 등 URL을 오염시키면 안 되는 향후 사용처 대비 최소 탈출구.
6. 선택 상태(selectedIds)·드로어 detailId는 URL에 넣지 않는다 — 일시 상태이며 공유 가치가 낮다.

### 1-b. `usePagedQuery` — 서버 페이징 로더 (audit/logs의 자구 중복 흡수)

`src/hooks/use-paged-query.ts` (신규)

```ts
import type { ApiError } from '@/lib/api/client';

/** 서버 페이지 응답의 정규형. 응답 키가 화면마다 달라(logs/runs/items) 어댑터에서 통일한다. */
export interface Page<T> {
  rows: T[];
  total: number;
}

export type ListPhase = 'loading' | 'ready' | 'error';

interface PagedQueryResult<T> {
  rows: T[];
  total: number;
  phase: ListPhase;
  error: ApiError | null;
  /** 현재 파라미터로 재요청 — '다시 시도' 버튼에 연결. */
  reload: () => void;
}

export function usePagedQuery<T>(
  /** null이면 요청하지 않음 — 권한 게이트(useApiResource의 path:null 관례를 계승, use-api-resource.ts:13). */
  fetcher: ((args: { limit: number; offset: number }) => Promise<Page<T>>) | null,
  opts: { page: number; pageSize: number },
): PagedQueryResult<T>;
```

- 화면은 `useCallback`으로 fetcher를 만들고 검색어/필터를 클로저에 넣는다. fetcher 정체성이 바뀌면 훅이 재조회한다 — 현재 audit/logs의 "loadPage useCallback 재생성 → effect 재조회" 구조(audit-client.tsx:63-91, logs-client.tsx:108-134)와 정확히 같은 시맨틱을 한 곳에서 소유.
- 응답 키 이원화(`/logs`→`{logs,total}` audit-client.tsx:74, fetchRuns→`{runs,total}` logs-client.tsx:119-120, me-codes→`{items,total}`)는 백엔드를 건드리지 않고 화면별 어댑터 한 줄로 `Page<T>`에 정규화한다:

```ts
const fetchPage = useCallback(
  async ({ limit, offset }: { limit: number; offset: number }): Promise<Page<AccessLog>> => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search) params.set('q', search);
    if (filters.status !== 'all') params.set('status', filters.status);
    const res = await api.get<{ logs: AccessLog[]; total: number }>(`/logs?${params}`);
    return { rows: res.logs, total: res.total };
  },
  [search, filters.status],
);
const { rows, total, phase, error, reload } = usePagedQuery(canRead ? fetchPage : null, { page, pageSize: PAGE_SIZE });
```

- 언마운트/경쟁 방지 active 플래그는 useApiResource(use-api-resource.ts:42-58)와 동일 패턴으로 내장.
- **useApiResource는 이동·개정하지 않는다.** 단일 GET 전용이라는 역할이 명확하고 사용처 8곳의 임포트 변경은 이번 과제 이득이 없다(수술적 변경 원칙).

### 1-c. `useClientPage` — 클라이언트 슬라이스 (멤버 방식)

`src/hooks/use-client-page.ts` (신규)

```ts
export function useClientPage<T>(
  /** 이미 필터링된 배열 — 필터링 자체는 화면 소유(화면마다 매칭 필드가 다름). */
  items: readonly T[],
  params: Pick<ListParams<Record<string, string>>, 'page' | 'setPage'>,
  pageSize: number,
): {
  rows: T[];            // 현재 페이지 슬라이스
  total: number;        // items.length — Pagination의 total로 그대로 전달
  effectivePage: number; // 렌더 시점 유효 페이지(아래 참조)
};
```

- members-client.tsx:92-105의 **effectivePage 파생 보정을 그대로 이식**한다: 렌더 시점 `min(page, lastPage)` 파생으로 stale 페이지의 빈 테이블 깜빡임을 막고, effect에서는 조용히 setPage만 동기화(:98-100). 이 주석에 적힌 이유("setPage를 effect에서 하면 페인트 이후라 한 프레임 깜빡")가 훅 문서 주석으로 승격되어 재발명을 방지한다.

### 서버 페이징 전환 전략 (과제 3번 답)

- 화면 코드에서 두 훅의 **출력 형태를 동일하게** 맞췄다(`rows`/`total` + Pagination에 그대로 꽂히는 값). 렌더 계층(ListStatePanel·TableCard·Pagination)은 어느 쪽인지 모른다.
- 멤버가 서버 페이징(`GET /users?limit&offset&q&role&...`)으로 전환하는 날: ① `useClientPage` 호출을 `usePagedQuery`+fetcher 어댑터로 교체, ② 클라 필터 useMemo(members-client.tsx:72-85) 삭제 — **렌더 JSX는 무변경**. useListParams는 양쪽 공통이라 손대지 않는다.
- 낙관적 편집은 서버 페이징에서도 성립: `usePagedQuery`에 `mutateRows(updater)` 를 v2로 추가할 수 있으나, 지금은 멤버가 클라 모드라 **넣지 않는다**(YAGNI — 전환 시점에 추가).

---

## 2. 컴포넌트 계층: 조합형 headless 부품 선택 (갓컴포넌트 기각)

**판단: `<ListPage>` 완전 조립형은 기각. 조합 가능한 부품 4개 + 훅 3개.**

근거 — 화면 실제 편차가 조립형의 슬롯 수용 한계를 즉시 넘는다:
- projects는 테이블이 아니라 **카드 그리드**(projects-client.tsx:96-100), 페이지네이션 없음.
- works는 **마스터/디테일 2열 전환**(works-client.tsx:129-147), 페이지네이션 없음.
- members는 테이블 위에 **조건부 벌크 바**(members-client.tsx:328-338)+드로어+확인 다이얼로그가 얹힘.
- logs는 tbody 안 **행 확장**(logs-client.tsx:330-345), members는 **선택 체크박스+인라인 편집 셀렉트**.

같은 이유로 **컬럼정의형 DataTable도 만들지 않는다.** 테이블 계층에서 실제 자구 중복은 셸 3줄(wrapper/table/thead 클래스 — members-table.tsx:95-97 ↔ audit-client.tsx:187-189 ↔ logs-client.tsx:230-232)뿐이고, tbody는 세 화면이 전혀 다르다(확장행/체크박스/인라인 셀렉트). 컬럼정의 API로 이 셋을 수용하려면 renderExpanded·selection·cellEditor 옵션이 줄줄이 필요해진다 — 이 리포가 금지하는 투기적 일반화의 전형이다.

### 신규 부품 4개 (전부 `src/components/ui/`, kebab-case — 리포 관례)

**① `search-input.tsx` — SearchInput** (자구 중복 3.5곳 흡수: members-filter-bar.tsx:58-71, audit-client.tsx:116-129, code-catalog-manager.tsx:362-374, works-client.tsx:112-125 근사)

```ts
interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  /** 래퍼 폭 제어 — 기본 'w-full sm:w-72'. */
  className?: string;
}
```
내부: relative 래퍼 + RiSearchLine 절대배치 + `Input className=\"h-9 rounded-full pl-9\"`. 기존 공용 Input(input.tsx) 재사용.

**② `list-toolbar.tsx` — ListToolbar** (툴바 셸+초기화 버튼 자구 중복 3곳 흡수)

```ts
interface ListToolbarProps {
  /** useListParams().isFiltered — true일 때만 초기화 버튼 노출. */
  isFiltered: boolean;
  onReset: () => void;
  /** SearchInput·FilterPill 등 자유 배치. */
  children: ReactNode;
}
```
셸 `flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center`(members-filter-bar.tsx:57 등 3곳 동일)과 rounded-full 초기화 버튼(members-filter-bar.tsx:127-136 = audit-client.tsx:144-153 = logs-client.tsx:188-197 자구 동일)을 소유. **여기가 "전 화면 공통 기능"의 1차 착지 지점** — 예: 내보내기 버튼·저장된 필터 등이 생기면 이 컴포넌트의 슬롯/기능으로 추가하면 세 화면이 동시에 받는다.

**③ `table-card.tsx` — TableCard + tableRowClass** (테이블 셸 자구 중복 3곳 흡수)

```ts
interface TableCardProps {
  /** 가로 스크롤 최소폭(px) — members 1000 / logs 900 / audit 820. */
  minWidth: number;
  /** <tr><Th>…</Th></tr> — thead 클래스는 TableCard가 소유. */
  head: ReactNode;
  /** <tbody> 행들 — 확장행·체크박스·인라인 셀렉트 등 화면 자유. */
  children: ReactNode;
}
/** 행 공통 클래스 'border-border-subtle row-hover border-b last:border-0' — 화면이 cn()으로 확장. */
export const tableRowClass: string;
```
카드 래퍼·table·thead 클래스 문자열(3곳 하드코딩 동일)을 단일 소유. tr 렌더는 화면에 남긴다(members는 `selected && 'bg-accent/5'` members-table.tsx:130-133, logs는 `cursor-pointer`+aria-expanded logs-client.tsx:290-293 — 각자 tableRowClass에 cn으로 덧댐). Th/Td(table-cell.tsx)는 무변경 재사용.

**④ `list-state.tsx` — ListStatePanel + LockedEmptyState** (3분기 삼항 3곳 + 권한 게이트 2곳 흡수)

```ts
interface ListStatePanelProps {
  phase: ListPhase;                    // usePagedQuery 결과 또는 useApiResource status 매핑
  error: ApiError | null;
  loadingLabel: string;                // '접속 기록을 불러오는 중…'
  errorTitle: string;                  // '접속 기록을 불러오지 못했습니다'
  onRetry: () => void;                 // reload
  /** phase==='ready'인데 rows가 0건. */
  isEmpty: boolean;
  empty: { icon?: ReactNode; title: string; description?: string; action?: ReactNode };
  /** 정상 상태 렌더 — 테이블이든 카드 그리드든 무엇이든. */
  children: ReactNode;
}

interface LockedEmptyStateProps { description: string } // RiLockLine EmptyState 프리셋
```
- Spinner div(동일 클래스 문자열 `text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm` — 3곳 확인), RiErrorWarningLine EmptyState+다시 시도, 빈 상태 EmptyState를 단일 소유. `error.status===0 → '서버에 연결할 수 없습니다'` 분기(audit-client.tsx:167, logs-client.tsx:210 동일)도 내장.
- children이 자유이므로 **projects 카드 그리드·works 마스터디테일도 실 API 전환 시 그대로 수용**된다.
- LockedEmptyState는 audit-client.tsx:107-112 ↔ logs-client.tsx:149-154의 자구 중복 흡수.
- **여기가 공통 기능의 2차 착지 지점** — 예: 로딩을 Spinner→Skeleton으로 바꾸는 결정을 하면 이 파일 한 곳 수정으로 전 화면 반영(현재 skeleton.tsx는 importer 0건으로 방치 — 이 구조가 생기면 채택 비용이 1파일로 줄어든다).

### 계층 요약 — "한 곳에 추가하면 전 화면이 받는" 매핑

| 미래 공통 기능 예시 | 착지 지점 |
|---|---|
| URL 공유·새로고침 유지 | useListParams (이번에 해결) |
| 저장된 필터·필터 프리셋 | useListParams + ListToolbar |
| 내보내기(CSV) 버튼 | ListToolbar 슬롯 |
| 자동 새로고침/폴링 | usePagedQuery 옵션 |
| Skeleton 로딩 전환 | ListStatePanel |
| 페이지 크기 선택 | Pagination + useListParams |
| 정렬 | useListParams `sort` 키 + Th 확장(요구 발생 시) |

---

## 3. 기존 부품 재사용/개정 계획 (과제 4번)

| 부품 | 처분 | 근거 |
|---|---|---|
| pagination.tsx | **그대로** | page/pageSize/total/onPageChange API(pagination.tsx:6-12)가 서버·클라 페이징 양쪽에 이미 중립적. 4개 화면 사용 중. 개정 불필요 |
| filter-pill.tsx | **그대로** | FilterPill(label/value/active/onValueChange, filter-pill.tsx:7-17)은 이미 올바른 추상화. '상태 FilterPill 블록 반복' 실측은 옵션 목록 차이일 뿐이라 추가 래핑은 이득 없음 |
| table-cell.tsx (Th/Td) | **그대로** | 8곳 사용, TableCard의 head/children 안에서 그대로 사용 |
| empty-state.tsx / spinner.tsx | **그대로** | ListStatePanel의 내부 구현 재료. 19곳/25곳 사용 |
| drawer.tsx | **그대로** | API(drawer.tsx:13-22) 충분. 사용처 1곳(멤버)뿐이라 개정 근거 없음 |
| input.tsx / select-dropdown.tsx / status-pill.tsx | **그대로** | SearchInput·FilterPill의 재료 |
| use-api-resource.ts | **그대로(이동 안 함)** | 단일 GET 역할 명확. src/hooks 이전은 8곳 임포트 변경 대비 이득 없음 — 수술적 변경 원칙 |
| filter-chip-bar.tsx | **방치(도입 안 함)** | importer 0건 확인. FilterPill 노선과 경쟁하는 대체 UI — 이번 공통화에 편입하면 필터 UI 이원화. 삭제는 별도 정리 과제(Recycle 규칙) |
| select.tsx(네이티브) / skeleton.tsx | **방치** | importer 0건 확인. skeleton은 ListStatePanel 완성 후 채택 여부만 1파일 결정으로 남김 |
| **신규** | search-input.tsx · list-toolbar.tsx · table-card.tsx · list-state.tsx · use-list-params.ts · use-paged-query.ts · use-client-page.ts | 위 §1·§2 |

---

## 4. 마이그레이션 순서와 예상 삭제 줄 수 (과제 5번)

각 Phase는 독립 배포 가능. 검증: 훅 단위 테스트 + Playwright 스크린샷(전후 비교) + 기존 수동 시나리오.

| Phase | 화면 | 작업 | 대체(삭제) 줄 수 | 리스크 |
|---|---|---|---|---|
| 0 | (없음) | 훅 3종+부품 4종 신설, 훅 단위 테스트. 기존 화면 무변경 | 0 | 없음 |
| 1 | /audit | 전 부품 첫 적용. 로더(:46,55-61,63-91)·검색(:116-129)·툴바(:115,144-153)·게이트(:107-112)·3분기(:157-184)·셸(:187-189) 교체 + page.tsx Suspense | **~100줄** (순삭감 ~60) | 낮음 — 단일 파일 255줄, 기능 최소 |
| 2 | /logs | 동일 세트(:41,73-80,108-134 / :149-154 / :157,188-197 / :200-227 / :230-232). RunRow 불변 | **~90줄** (순삭감 ~55) | 낮음 |
| 3 | /members | useListParams(URL)+useClientPage(:59-105,113-118), filter-bar를 ListToolbar+SearchInput로(:57-71,127-136), 3분기(:291-312,340-350), 셸(members-table.tsx:95-97). 낙관·벌크·드로어 불변 | **~85줄** (순삭감 ~50) | 중간 — effectivePage 시맨틱 보존 필수 |
| 4 | /manage/* ×3 | 디바운스(:94-95,170-176)→useListParams, 검색(:362-374)→SearchInput, 3분기(:376-399)→ListStatePanel. sticky 셸·폴링 유지 | **~50줄** | 낮음 — 1파일 수정으로 3라우트 수혜 |
| 5(선택) | /works /projects | works 검색(works-client.tsx:112-125)→SearchInput만. 상태 칩·그리드는 불변 | **~14줄** | 없음 |

합계 대체 약 **340줄**, 신규 공용 코드 약 350~400줄(테스트 제외). 줄 수 손익은 중립이지만 목적은 축소가 아니라 **변경 비용의 1/N화** — Phase 3 완료 시점부터 "멤버에 생기는 공통 기능"이 훅/부품 7파일 중 한 곳에 착지한다.

순서 근거: audit이 가장 작고(255줄 단일 파일) 서버 페이징이 이미 완성돼 있어 부품 검증 비용이 최소 → logs는 audit과 자구 동일 구조라 즉시 복제 적용 → members는 가장 크고 낙관 편집이 얽혀 있어 부품이 검증된 뒤에 → manage는 이미 자체 공용화(1파일 3라우트)돼 있어 급하지 않음 → 데모 2종은 실 API 전환 때가 진짜 마이그레이션 시점.

---

## 5. 공통화 금지 목록 (과제 6번 — 상세 근거는 doNotAbstract 필드)

1. **멤버 낙관적 업데이트·롤백·벌크 러너** (members-client.tsx:142-284) — 변경 기능이 있는 리스트가 멤버뿐. 자기보호(me.id 제외 :258,273)·부분 실패 토스트는 도메인 로직.
2. **logs 행 확장 RunRow/RunDetailBody** (logs-client.tsx:264-504) — 유일 사용처. 이것 때문에 DataTable을 만들면 안 된다.
3. **멤버 선택 체크박스·selectedIds** (members-client.tsx:107-140, members-table.tsx:99-106) — 두 번째 사용처가 생길 때.
4. **카탈로그 동기화 폴링·즐겨찾기** (code-catalog-manager.tsx:41,179-203) — ERP 전용 플로우.
5. **조직 트리 SelectGroup 렌더** (members-filter-bar.tsx:98-109 ↔ members-table.tsx:205-216) — 화면 내부 중복이므로 members/_components/ 로컬 추출이 올바른 스코프.
6. **projects/works 상태 칩** — 세그먼트 컨트롤(projects-client.tsx:57-87) vs 필 버튼(works-client.tsx:81-110)으로 마크업이 실제 다름(직접 대조). 자구 중복이 아닌 패턴 유사 — 통일 금지.
7. **검색 매칭 필드 선택** — members는 name+email(:83), works는 title+담당+프로젝트(works-client.tsx:42-49). 훅은 문자열만 준다.
8. **WORKFLOW_LABEL 맵** (logs-client.tsx:44-47) — 공통화가 아니라 라벨 소스 이원화 해소가 필요한 별도 결함.

---

## 6. 마이그레이션 후 화면 골격 (audit 기준 예시)

```tsx
export function AuditClient() {
  const canRead = useCan(PERMISSIONS.LOGS_READ);
  const { searchInput, setSearchInput, search, filters, setFilter, page, setPage, isFiltered, reset } =
    useListParams({ filters: { status: 'all' } });

  const fetchPage = useCallback(/* §1-b 어댑터 */, [search, filters.status]);
  const { rows, total, phase, error, reload } = usePagedQuery(canRead ? fetchPage : null, { page, pageSize: PAGE_SIZE });

  if (!canRead) return <PageShell><LockedEmptyState description="감사 로그는 관리자 이상만 열람할 수 있습니다." /></PageShell>;

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader caption="운영" title="감사" description="…" />
      <ListToolbar isFiltered={isFiltered} onReset={reset}>
        <SearchInput value={searchInput} onChange={setSearchInput} placeholder="옴니솔 아이디 검색" ariaLabel="감사 로그 검색" />
        <FilterPill label="상태" ariaLabel="상태 필터" value={filters.status} active={filters.status !== 'all'}
          onValueChange={(v) => setFilter('status', v)}>
          <SelectItem value="all">전체</SelectItem>
          <SelectItem value="success">성공</SelectItem>
          <SelectItem value="failed">실패</SelectItem>
        </FilterPill>
      </ListToolbar>
      <ListStatePanel phase={phase} error={error} onRetry={reload}
        loadingLabel="접속 기록을 불러오는 중…" errorTitle="접속 기록을 불러오지 못했습니다"
        isEmpty={rows.length === 0}
        empty={{ icon: <RiHistoryLine size={18} aria-hidden />, title: '접속 기록이 없습니다',
                 description: isFiltered ? '검색·필터 조건에 맞는 접속 기록이 없습니다.' : '아직 기록된 로그인 접속 이벤트가 없습니다.' }}>
        <div className="flex flex-col gap-3">
          <TableCard minWidth={820} head={<tr><Th>사용자</Th><Th>롤</Th><Th>접속시각</Th><Th>IP</Th><Th>상태</Th></tr>}>
            {rows.map((log) => (<tr key={log.id} className={tableRowClass}>…기존 셀 그대로…</tr>))}
          </TableCard>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </div>
      </ListStatePanel>
    </div>
  );
}
```

행 셀 렌더(도메인)는 전부 화면에 남고, 상태 배선과 셸은 전부 공용으로 올라간다.