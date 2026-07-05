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

/** 코드 종류 — 예산단위 / 프로젝트 / 에이전트(즐겨찾기 전용 — 카탈로그·동기화 없음). */
export type CatalogKind = 'budget_unit' | 'project' | 'agent';

/** 부가 데이터 — 백엔드 JSON 객체.
 * 예산단위 = {bizplanCd, bizplanNm, bgacctCd, bgacctNm} (선택 단위 = BG×사업계획×예산계정 조합 행),
 * 프로젝트 = {pjtNo, wbsNo, wbsNm, loc, useYn, partnerNm} (선택 단위 = WBS 행, code=PJT_NO|WBS_NO).
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

/** ERP 동기화 진행 상태. */
export interface SyncStatus {
  running: boolean;
  lastSyncedAt: string | null;
  count: number;
  /** 직전 동기화 실패 사유(있을 때). */
  error?: string;
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
