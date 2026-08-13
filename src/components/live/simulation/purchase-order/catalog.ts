/**
 * 구매발주 계획서 — 거래처·프로젝트 검색 카탈로그(CatalogCombobox 재료, model.ts 에서 분리).
 *
 * 전부 로컬 정적 목록이다 — 실연동 시 ERP 카탈로그 검색으로 교체한다.
 * model.ts → catalog.ts 방향 의존만 있다(모델은 카탈로그를 모른다).
 */

import type { ComboOption } from '@/components/live/pre-run/catalog-combobox';
import { BOM, MODULES, isPseudoVendor } from './model';

// ── 거래처 ───────────────────────────────────────────────────────────────────

/**
 * 실거래처 지정의 자주쓰는 후보 — 기본 거래처(해룡·알파테크) 포함.
 * 코드는 model.ts DEFAULT_VENDOR_BY_CLASS 와 같은 V-xxxx 체계를 공유한다.
 */
export const VENDOR_FAVORITES: readonly ComboOption[] = [
  { code: 'V-1001', name: '한국메카' },
  { code: 'V-1002', name: '알파테크' },
  { code: 'V-1003', name: '해룡' },
];

/** 검색 풀 = 자주쓰는 후보 + 픽스처에 등장하는 실거래처(의사 거래처 제외, 중복 제거). */
export const VENDOR_SEARCH_POOL: readonly ComboOption[] = [
  ...VENDOR_FAVORITES,
  ...[...new Set(MODULES.flatMap((m) => m.parts.map((p) => p.vendorClass)))]
    .filter((v) => !isPseudoVendor(v))
    .map((name, i) => ({ code: `V-2${String(i + 1).padStart(3, '0')}`, name })),
];

/** 로컬 정적 목록 필터 — CatalogCombobox 의 search(async)에 감싸서 넘긴다. */
export function searchVendors(q: string): ComboOption[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  return VENDOR_SEARCH_POOL.filter((v) => v.name.toLowerCase().includes(needle));
}

// ── 프로젝트 ─────────────────────────────────────────────────────────────────

/** 프로젝트 즐겨찾기 — 데모는 BOM 픽스처의 1건뿐. */
export const PROJECT_FAVORITES: readonly ComboOption[] = [
  {
    code: BOM.project.code,
    name: BOM.project.name,
    codeLabel: BOM.project.code,
    sub: `WBS ${BOM.project.wbs}`,
  },
];

/** 로컬 정적 목록 필터 — 검색 풀 = 즐겨찾기와 동일(데모 프로젝트 1건). */
export function searchProjects(q: string): ComboOption[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  return PROJECT_FAVORITES.filter(
    (p) => p.name.toLowerCase().includes(needle) || p.code.toLowerCase().includes(needle),
  );
}
