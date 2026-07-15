/**
 * 내 코드(예산단위·프로젝트) REST 클라이언트 — 자주쓰는 즐겨찾기 + ERP 카탈로그 동기화.
 *
 * 모든 호출은 CurrentUser(세션 쿠키) 스코프이며 응답은 camelCase 다. 공용 {@link api}
 * 래퍼가 credentials·에러 정규화를 처리한다. 백엔드가 아직 없을 수 있으므로(병렬 트랙)
 * 호출부는 실패를 관대히 다뤄야 한다 — 이 모듈은 계약(shape)만 고정한다.
 *
 * 백엔드 계약(고정):
 *   GET    /me/favorites?kind=budget_unit|project      → {items: Favorite[]}
 *   POST   /me/favorites   {kind,code,name,extra?}     → Favorite (중복 멱등)
 *   DELETE /me/favorites/{id}                          → 204
 *   POST   /me/favorites/reorder {kind, orderedIds}    → 204
 *   POST   /me/favorites/{id}/default                  → Favorite (기존 default 해제)
 *   GET    /me/catalog?kind=&q=&dept=&limit=&offset=   → {items,total,syncedAt}
 *   POST   /me/catalog/sync {kind}                     → 202 {started:true} | 409(한글 detail)
 *   GET    /me/catalog/sync-status?kind=               → SyncStatus
 */

import { api } from './client';

/** 코드 종류 — 예산단위 / 프로젝트 / 거래처 / 에이전트(즐겨찾기 전용 — 카탈로그·동기화 없음). */
export type CatalogKind = 'budget_unit' | 'project' | 'partner' | 'agent' | 'org_unit';

/** 부가 데이터 — 백엔드 JSON 객체.
 * 예산단위 = {bizplanCd, bizplanNm, bgacctCd, bgacctNm} (선택 단위 = BG×사업계획×예산계정 조합 행),
 * 프로젝트 = {pjtNo, wbsNo, wbsNm, loc, useYn, partnerNm} (선택 단위 = WBS 행, code=PJT_NO|WBS_NO),
 * 거래처 = {bizNo} (선택 단위 = 거래처 행, code=거래처코드·name=거래처명).
 * deptNm 은 과거 데이터 하위호환. */
export interface CodeExtra {
  deptNm?: string;
  useYn?: string;
  partnerNm?: string;
  bizplanCd?: string;
  bizplanNm?: string;
  bgacctCd?: string;
  bgacctNm?: string;
  pjtNo?: string;
  wbsNo?: string;
  wbsNm?: string;
  loc?: string;
  bizNo?: string;
}

/** 자주쓰는(즐겨찾기) 한 항목. extra 는 부서명 등 부가 표시(예산단위=deptNm). */
export interface Favorite {
  id: string;
  kind: CatalogKind;
  code: string;
  name: string;
  extra: CodeExtra | null;
  sortOrder: number;
  /** (kind 당 1개) '기본' 지정 여부. 후속 AI 추천이 폴백으로 쓴다. */
  isDefault: boolean;
}

/** 카탈로그(전체 코드) 한 항목. */
export interface CatalogItem {
  code: string;
  name: string;
  extra: CodeExtra | null;
}

/** 카탈로그 페이지 — 행 + 스코프 전체 건수 + 마지막 동기화 시각. */
export interface CatalogPage {
  items: CatalogItem[];
  total: number;
  syncedAt: string | null;
}

/** 조직도(org_unit) 동기화 시 org_units 반영 요약 — 백엔드 org_apply.apply_org_tree 반환.
 * 키는 백엔드 서비스 dict 그대로(snake_case): 추가/갱신/미포함은 라벨 목록, unchanged·total_erp 는 수. */
export interface OrgApplySummary {
  added: string[];
  updated: string[];
  unchanged: number;
  local_only: string[];
  total_erp: number;
}

/** 조직도 반영 후 department 기준 재배치된 사용자 1건 — 백엔드 org_apply.reconcile_users 반환. */
export interface OrgReassign {
  userid: string;
  from: string | null;
  to: string;
  department: string | null;
  org_label: string;
}

/** ERP 동기화 진행 상태. */
export interface SyncStatus {
  running: boolean;
  lastSyncedAt: string | null;
  count: number;
  /** 직전 동기화 실패 사유(있을 때). */
  error?: string;
  /** org_unit 동기화에서만 채워진다 — 조직구분 반영 요약. */
  applied?: OrgApplySummary | null;
  /** org_unit 동기화에서만 채워진다 — 재배치된 사용자 목록. */
  reassigned?: OrgReassign[] | null;
}

export interface AddFavoriteInput {
  kind: CatalogKind;
  code: string;
  name: string;
  extra?: CodeExtra | null;
}

export interface CatalogQuery {
  kind: CatalogKind;
  /** 이름/코드 검색어. */
  q?: string;
  /** 부서 필터. 'all' 이면 부서 제한 해제(기본은 내 부서). */
  dept?: string;
  /** 최대 200. */
  limit?: number;
  offset?: number;
}

/** `GET /me/favorites?kind` — 자주쓰는 목록(sortOrder 순). */
export async function fetchFavorites(kind: CatalogKind): Promise<Favorite[]> {
  const res = await api.get<{ items?: Favorite[] }>(`/me/favorites?kind=${kind}`);
  return res.items ?? [];
}

/** `POST /me/favorites` — 자주쓰는 추가(중복이면 기존 반환). */
export function addFavorite(input: AddFavoriteInput): Promise<Favorite> {
  return api.post<Favorite>('/me/favorites', {
    kind: input.kind,
    code: input.code,
    name: input.name,
    extra: input.extra ?? null,
  });
}

/** `DELETE /me/favorites/{id}` — 자주쓰는 제거. */
export function removeFavorite(id: string): Promise<void> {
  return api.delete<void>(`/me/favorites/${encodeURIComponent(id)}`);
}

/** `POST /me/favorites/reorder` — 자주쓰는 순서 변경(전체 id 순서 전달). */
export function reorderFavorites(kind: CatalogKind, orderedIds: string[]): Promise<void> {
  return api.post<void>('/me/favorites/reorder', { kind, orderedIds });
}

/** `POST /me/favorites/{id}/default` — 그 (kind) 의 '기본'으로 지정(기존 default 해제). */
export function setDefaultFavorite(id: string): Promise<Favorite> {
  return api.post<Favorite>(`/me/favorites/${encodeURIComponent(id)}/default`, {});
}

/** `GET /me/catalog` — 전체 코드 페이지(예산단위는 기본 내 부서, dept=all 로 해제). */
export async function fetchCatalog(query: CatalogQuery): Promise<CatalogPage> {
  const qs = new URLSearchParams({ kind: query.kind });
  if (query.q) qs.set('q', query.q);
  if (query.dept) qs.set('dept', query.dept);
  if (query.limit != null) qs.set('limit', String(query.limit));
  if (query.offset != null) qs.set('offset', String(query.offset));
  const res = await api.get<{ items?: CatalogItem[]; total?: number; syncedAt?: string | null }>(
    `/me/catalog?${qs.toString()}`,
  );
  return { items: res.items ?? [], total: res.total ?? 0, syncedAt: res.syncedAt ?? null };
}

/** 출장 기본 프로젝트(팀 비용구분 매칭) — code=PJT_NO|WBS_NO 합성. */
export interface TripDefaultProject {
  code: string;
  name: string;
  wbsNo: string;
  wbsNm: string;
}

/** `GET /me/trip-defaults` 응답 — 소속 팀 비용구분(판/제) + 그에 맞는 기본 프로젝트. */
export interface TripDefaults {
  costType: string | null;
  department: string | null;
  defaultProject: TripDefaultProject | null;
}

/**
 * `GET /me/trip-defaults` — 출장 실행 전 폼 기본값. 소속 팀 비용구분(제조원가→500/판관비→800)에
 * 맞는 기본 프로젝트를 서버가 카드 자동화와 동일 규칙으로 해석해 내려준다. 미배정·미존재면 null.
 */
export async function fetchTripDefaults(): Promise<TripDefaults> {
  const res = await api.get<Partial<TripDefaults>>('/me/trip-defaults');
  return {
    costType: res.costType ?? null,
    department: res.department ?? null,
    defaultProject: res.defaultProject ?? null,
  };
}

/**
 * `POST /me/catalog/sync` — ERP 동기화 시작. 이미 실행 중이거나 ERP 자격증명이 없으면
 * 409(한글 detail)를 던진다 — 호출부가 errorMessage 로 토스트한다.
 */
export function startCatalogSync(kind: CatalogKind): Promise<{ started: boolean }> {
  return api.post<{ started: boolean }>('/me/catalog/sync', { kind });
}

/** `GET /me/catalog/sync-status?kind` — 동기화 진행 상태(폴링용). */
export function fetchSyncStatus(kind: CatalogKind): Promise<SyncStatus> {
  return api.get<SyncStatus>(`/me/catalog/sync-status?kind=${kind}`);
}

// ── 개입 학습(디버그) ────────────────────────────────────────────────────────
export interface LearnedSelection {
  id: string;
  merchant: string;
  normMerchant: string;
  budget: { code: string; name: string; bizplanNm?: string; bgacctNm?: string } | null;
  project: { code: string; name: string; wbsNo?: string; wbsNm?: string } | null;
  note: string | null;
  count: number;
  lastUsedAt: string | null;
}

export async function fetchCardLearning(): Promise<LearnedSelection[]> {
  const res = await api.get<{ items?: LearnedSelection[] }>('/me/card-learning');
  return res.items ?? [];
}

/** `DELETE /me/card-learning/{id}` — 개인 학습 1건 삭제(본인 것만). */
export function deleteCardLearning(id: string): Promise<void> {
  return api.delete<void>(`/me/card-learning/${encodeURIComponent(id)}`);
}

/** `DELETE /me/card-learning` — 개인 학습 전체 삭제. 반환 삭제 건수. */
export async function clearCardLearning(): Promise<number> {
  const res = await api.delete<{ deleted?: number }>('/me/card-learning');
  return res?.deleted ?? 0;
}

// ── 전사 기초자료(seed, 공통) ─────────────────────────────────────────────────
export interface SeedSelection {
  id: string;
  merchant: string;
  normMerchant: string;
  acctCode: string | null;
  acctName: string | null;
  note: string | null;
  count: number;
  dominance: number;
  lastYear: number | null;
}

export interface SeedResult {
  total: number;
  limit: number;
  offset: number;
  items: SeedSelection[];
}

export async function fetchCardSeed(
  opts: { q?: string; limit?: number; offset?: number } = {},
): Promise<SeedResult> {
  const p = new URLSearchParams();
  if (opts.q && opts.q.trim()) p.set('q', opts.q.trim());
  if (opts.limit != null) p.set('limit', String(opts.limit));
  if (opts.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  const res = await api.get<Partial<SeedResult>>(`/me/card-learning/seed${qs ? `?${qs}` : ''}`);
  return {
    total: res.total ?? 0,
    limit: res.limit ?? opts.limit ?? 50,
    offset: res.offset ?? opts.offset ?? 0,
    items: res.items ?? [],
  };
}

// ── 계정 인지 적요 추천(note-suggest) ─────────────────────────────────────────
/** `GET /me/note-suggest` 응답 — note 없으면 null, source 는 matched tier
 * (learned=개인학습 · seed=전사관례 · ai=계정 맞춤 생성 · category=계정최빈 · heuristic=키워드 · null=없음). */
export interface NoteSuggestResult {
  note: string | null;
  source: string | null;
}

/**
 * `GET /me/note-suggest?merchant=&acct=&acctName=` — 가맹점(+예산계정)에 맞는 적요 추천.
 * 카드 개입 그리드에서 사람이 예산단위(=계정)를 바꾸면 그 계정 맞춤 적요를 즉시 재추천한다.
 * learned/seed 에 실이력이 없는 미학습 조합은 계정 이름(acctName)으로 AI 가 생성한다 —
 * acctName 을 넘겨야 AI tier 가 돈다(없으면 통계·휴리스틱만). acct 생략 시 계정 무관 키워드만.
 * 실패는 호출부가 관대히 다룬다(기존 적요 유지).
 */
export async function fetchNoteSuggest(params: {
  merchant: string;
  acct?: string;
  acctName?: string;
}): Promise<NoteSuggestResult> {
  const qs = new URLSearchParams({ merchant: params.merchant });
  if (params.acct && params.acct.trim()) qs.set('acct', params.acct.trim());
  if (params.acctName && params.acctName.trim()) qs.set('acctName', params.acctName.trim());
  const res = await api.get<Partial<NoteSuggestResult>>(`/me/note-suggest?${qs.toString()}`);
  return { note: res.note ?? null, source: res.source ?? null };
}
