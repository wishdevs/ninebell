/**
 * 거래처(partner) 카탈로그 — 실행 전 폼 전용의 얇은 읽기 클라이언트.
 *
 * partner kind 는 Track B(me-codes.ts `CatalogKind` 확장)가 병합 중이라, 그때까지 폼이
 * `CatalogKind` 유니언에 결합되지 않도록 여기서 REST 를 직접 부른다(문자열 캐스트 없이 tsc
 * 안전). Track B 가 'partner' 를 유니언에 넣으면 이 모듈은 `fetchFavorites('partner')` /
 * `fetchCatalog({kind:'partner'})` 호출로 흡수(대체)할 수 있다.
 *
 * 백엔드 계약(고정, me-codes.ts 와 동일 엔드포인트):
 *   GET /me/favorites?kind=partner          → {items: Favorite[]}
 *   GET /me/catalog?kind=partner&q=&dept=all → {items: CatalogItem[]}
 * partner 카탈로그는 dept="" 전사 공용이라 dept=all 로 부서 제한을 해제한다.
 */

import { api } from '@/lib/api/client';
import type { CatalogItem, Favorite } from '@/lib/api/me-codes';

const PARTNER_CATALOG_LIMIT = 25;

/** partner 자주쓰는 목록(기본지정 포함, sortOrder 순). 백엔드 미배포 시 빈 배열. */
export async function fetchPartnerFavorites(): Promise<Favorite[]> {
  const res = await api.get<{ items?: Favorite[] }>('/me/favorites?kind=partner');
  return res.items ?? [];
}

/** partner 카탈로그 검색(이름/코드). 빈 질의는 상위 N건. */
export async function fetchPartnerCatalog(q: string): Promise<CatalogItem[]> {
  const qs = new URLSearchParams({ kind: 'partner', dept: 'all' });
  if (q.trim()) qs.set('q', q.trim());
  qs.set('limit', String(PARTNER_CATALOG_LIMIT));
  const res = await api.get<{ items?: CatalogItem[] }>(`/me/catalog?${qs.toString()}`);
  return res.items ?? [];
}
