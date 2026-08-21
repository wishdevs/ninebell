/**
 * 구매발주 계획서 — 거래처·프로젝트 검색 카탈로그(CatalogCombobox 재료, model.ts 에서 분리).
 *
 * 전부 로컬 정적/BOM 파생 목록이다 — 실연동 시 ERP 카탈로그 검색으로 교체한다.
 * model.ts ↔ catalog.ts 는 상호 참조하되 런타임 순환은 없다 — 이쪽의 model 의존은
 * type-only 이고, model 은 예외 거래처명→코드 해석(vendorCategoryOf)만 값으로 쓴다
 * (패턴 v2, 2026-08-21). 거래처는 분류별 고정 목록, 프로젝트 목록만 BOM 파생.
 */

import type { ComboOption } from '@/components/live/pre-run/catalog-combobox';
import type { PlanBom, UnifiedVendors } from './model';

// ── 거래처 ───────────────────────────────────────────────────────────────────

/** 교체 가능한 거래처 분류 1종 — 선택지는 고정 목록이고 첫 진입값이 기본 거래처다. */
export interface VendorCategory {
  /** BOM 품목거래처명(vendorClass)과 같은 값 — 그룹 행이 이 키로 카테고리를 찾는다. */
  vendorClass: string;
  /** 통합 지정·그룹 행 콤보박스의 고정 선택지(isDefault 가 기본 거래처). */
  options: readonly ComboOption[];
}

/**
 * 통합 업체 지정 3분류(사용자 확정 2026-08-21) — 선택지는 이 목록으로 닫혀 있다.
 * 종전 자유 검색(BOM 등장 실거래처 풀)은 분류별 고정 목록으로 대체됐다.
 * 코드는 자리표시용 합성값(V-11xx 가공품 · V-12xx 판금품 · V-13xx 오텍)이다.
 */
export const VENDOR_CATEGORIES: readonly VendorCategory[] = [
  {
    vendorClass: '가공품',
    options: [
      { code: 'V-1101', name: '우신테크' },
      { code: 'V-1102', name: '제이테크' },
      { code: 'V-1103', name: '한국메카트로닉스' },
      { code: 'V-1104', name: '해룡엔지니어링', isDefault: true },
    ],
  },
  {
    vendorClass: '판금품',
    options: [
      { code: 'V-1201', name: '알파테크', isDefault: true },
      { code: 'V-1202', name: '부성엘티에스' },
      { code: 'V-1203', name: '브이피시스템' },
      { code: 'V-1204', name: '이레코리아' },
    ],
  },
  {
    vendorClass: '주식회사 오텍',
    options: [
      { code: 'V-1301', name: '주식회사 오텍', isDefault: true },
      { code: 'V-1302', name: '피르스트' },
      { code: 'V-1303', name: '훈원테크' },
    ],
  },
];

export function vendorCategoryOf(vendorClass: string): VendorCategory | undefined {
  return VENDOR_CATEGORIES.find((c) => c.vendorClass === vendorClass);
}

/** 계획서 첫 진입의 통합 지정 — 분류마다 기본 거래처. 키 집합이 곧 교체 가능한 분류다. */
export function defaultUnifiedVendors(): UnifiedVendors {
  return Object.fromEntries(
    VENDOR_CATEGORIES.map((c) => {
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
