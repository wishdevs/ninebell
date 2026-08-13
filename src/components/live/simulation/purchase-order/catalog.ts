/**
 * 구매발주 계획서 — 거래처·프로젝트 검색 카탈로그(CatalogCombobox 재료, model.ts 에서 분리).
 *
 * 전부 로컬 정적/BOM 파생 목록이다 — 실연동 시 ERP 카탈로그 검색으로 교체한다.
 * model.ts → catalog.ts 방향 의존만 있다(모델은 카탈로그를 모른다). 검색 풀은 주입된
 * BOM(데모 픽스처 또는 hitl.plannerBom)에서 파생한다 — 정적 전역 의존 없음.
 */

import type { ComboOption } from '@/components/live/pre-run/catalog-combobox';
import { isPseudoVendor, type BomModule, type PlanBom } from './model';

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

/** 검색 풀 = 자주쓰는 후보 + BOM 에 등장하는 실거래처(의사 거래처 제외, 중복 제거). */
export function vendorSearchPoolOf(modules: readonly BomModule[]): ComboOption[] {
  return [
    ...VENDOR_FAVORITES,
    ...[...new Set(modules.flatMap((m) => m.parts.map((p) => p.vendorClass)))]
      .filter((v) => !isPseudoVendor(v))
      .map((name, i) => ({ code: `V-2${String(i + 1).padStart(3, '0')}`, name })),
  ];
}

/** 로컬 목록 필터 — CatalogCombobox 의 search(async)에 감싸서 넘긴다. */
export function searchVendors(pool: readonly ComboOption[], q: string): ComboOption[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  return pool.filter((v) => v.name.toLowerCase().includes(needle));
}

// ── 프로젝트 ─────────────────────────────────────────────────────────────────

/** 프로젝트 즐겨찾기 — 데모는 주입된 BOM 의 프로젝트 1건뿐. */
export function projectFavoritesOf(bom: PlanBom): ComboOption[] {
  return [
    {
      code: bom.project.code,
      name: bom.project.name,
      codeLabel: bom.project.code,
      sub: `WBS ${bom.project.wbs}`,
    },
  ];
}

/** 로컬 목록 필터 — 검색 풀 = 즐겨찾기와 동일(데모 프로젝트 1건). */
export function searchProjects(favorites: readonly ComboOption[], q: string): ComboOption[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  return favorites.filter(
    (p) => p.name.toLowerCase().includes(needle) || p.code.toLowerCase().includes(needle),
  );
}
