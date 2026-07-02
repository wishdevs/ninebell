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
 *   GET    /me/catalog?kind=&q=&dept=&limit=&offset=   → {items,total,syncedAt}
 *   POST   /me/catalog/sync {kind}                     → 202 {started:true} | 409(한글 detail)
 *   GET    /me/catalog/sync-status?kind=               → SyncStatus
 */

import { api } from './client';

/** 코드 종류 — 예산단위 / 프로젝트. */
export type CatalogKind = 'budget_unit' | 'project';

/** 부가 데이터 — 백엔드 JSON 객체.
 * 예산단위 = {bizplanCd, bizplanNm, bgacctCd, bgacctNm} (선택 단위 = BG×사업계획×예산계정 조합 행),
 * 프로젝트 = {useYn, partnerNm}. deptNm 은 과거 데이터 하위호환. */
export interface CodeExtra {
  deptNm?: string;
  useYn?: string;
  partnerNm?: string;
  bizplanCd?: string;
  bizplanNm?: string;
  bgacctCd?: string;
  bgacctNm?: string;
}

/** 자주쓰는(즐겨찾기) 한 항목. extra 는 부서명 등 부가 표시(예산단위=deptNm). */
export interface Favorite {
  id: string;
  kind: CatalogKind;
  code: string;
  name: string;
  extra: CodeExtra | null;
  sortOrder: number;
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
