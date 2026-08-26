/**
 * 구매발주 계획서 — 거래처·프로젝트 검색 카탈로그(CatalogCombobox 재료, model.ts 에서 분리).
 *
 * 거래처 후보는 관리자 설정(agents.settings.vendor_options, 2026-08-26 이관)에서 오고,
 * 프로젝트 목록만 BOM 파생이다. model 의존은 type-only(런타임 순환 없음).
 */

import type { ComboOption } from '@/components/live/pre-run/catalog-combobox';
import { VENDOR_CLASSES, type VendorOptions } from '@/lib/purchase/vendor-options';
import type { PlanBom, UnifiedVendors } from './model';

// ── 거래처 ───────────────────────────────────────────────────────────────────

/** 교체 가능한 거래처 분류 1종 — 선택지는 관리자 목록이고 isDefault 가 기본 거래처다. */
export interface VendorCategory {
  /** BOM 품목거래처명(vendorClass)과 같은 값 — 그룹 행이 이 키로 카테고리를 찾는다. */
  vendorClass: string;
  /** 통합 지정·그룹 행 콤보박스의 선택지(isDefault 가 기본 거래처). */
  options: readonly ComboOption[];
}

/**
 * 관리자 거래처 후보(agents.settings.vendor_options) → 계획서 카테고리 목록.
 * 종전 하드코딩 목록(자리표시 코드 V-11xx)은 2026-08-26 설정으로 이관 — ERP 로 나가는 값이
 * 거래처명뿐이라 **콤보박스 코드도 이름 자체**를 쓴다(코드 필드는 선택 하이라이트 키).
 */
export function vendorCategoriesFrom(options: VendorOptions): VendorCategory[] {
  return VENDOR_CLASSES.map((vendorClass) => ({
    vendorClass,
    options: options[vendorClass].map((r) => ({
      code: r.name,
      name: r.name,
      isDefault: r.isDefault,
    })),
  }));
}

/** 계획서 첫 진입의 통합 지정 — 분류마다 기본 거래처. 키 집합이 곧 교체 가능한 분류다. */
export function defaultUnifiedVendors(categories: readonly VendorCategory[]): UnifiedVendors {
  return Object.fromEntries(
    categories.map((c) => {
      const fallback = c.options.find((o) => o.isDefault) ?? c.options[0];
      return [c.vendorClass, fallback ? { code: fallback.code, name: fallback.name } : undefined];
    }),
  );
}

/** 분류 목록 내 필터 — CatalogCombobox 의 search(async)에 감싸서 넘긴다. */
export function searchVendors(options: readonly ComboOption[], q: string): ComboOption[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  return options.filter((v) => v.name.toLowerCase().includes(needle));
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
