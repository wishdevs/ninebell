/**
 * 구매발주 — 통합 지정 거래처 후보(agents.settings.vendor_options) 프론트 미러.
 * 백엔드 단일 소스는 backend/app/services/agent_settings.py 의 동명 상수/검증기다
 * (order_patterns 선례 — 정의·기본값은 코드, DB 에는 관리자 저장값만).
 *
 * 2026-08-26 신설: 종전에는 계획서 콤보박스 선택지가 catalog.ts 에 하드코딩돼 있었다
 * (자리표시 코드 V-11xx). ERP 로 나가는 값은 **거래처명뿐**이라 코드는 저장하지 않고,
 * 콤보박스 코드도 이름 자체를 쓴다.
 */

import rawDefaults from './vendor-options.default.json';

/** 교체 가능한 거래처 분류 — BOM 품목거래처명과 같은 고정 3종(백엔드 VENDOR_CLASSES 미러). */
export const VENDOR_CLASSES = ['가공품', '판금품', '주식회사 오텍'] as const;
export type VendorClass = (typeof VENDOR_CLASSES)[number];

export const VENDOR_OPTIONS_KEY = 'vendor_options';
export const MAX_VENDOR_OPTIONS_PER_CLASS = 30;
export const MAX_VENDOR_NAME_LEN = 60;

/** 후보 1행 — 이름이 곧 ERP 대조 값이다(화면 ③ 변경 거래처 코드피커가 이름으로 검색). */
export interface VendorOptionRow {
  name: string;
  isDefault: boolean;
}

export type VendorOptions = Record<VendorClass, VendorOptionRow[]>;

/**
 * 기본값 단일 소스는 `vendor-options.default.json` — BE 는 자체 리터럴을 유지하고
 * (배포 이미지에 src/ 없음) parity 테스트(test_fe_be_mirror_parity)가 드리프트를 감시한다
 * (order-patterns.default.json 과 같은 관례). JSON 은 isDefault 를 기본행에만 표기하므로
 * 여기서 정규화해 노출한다.
 */
export const DEFAULT_VENDOR_OPTIONS: VendorOptions = Object.fromEntries(
  VENDOR_CLASSES.map((c) => [
    c,
    (rawDefaults as Record<string, { name: string; isDefault?: boolean }[]>)[c].map((r) => ({
      name: r.name,
      isDefault: r.isDefault === true,
    })),
  ]),
) as VendorOptions;

/** 한 분류의 저장 행 파싱 — 형식이 깨진 행만 버리고, 남는 행이 없으면 null(분류 폴백 신호). */
function parseClassRows(raw: unknown): VendorOptionRow[] | null {
  if (!Array.isArray(raw)) return null;
  const out: VendorOptionRow[] = [];
  const seen = new Set<string>();
  for (const row of raw.slice(0, MAX_VENDOR_OPTIONS_PER_CLASS)) {
    if (typeof row !== 'object' || row === null) continue;
    const name = String((row as { name?: unknown }).name ?? '').trim();
    if (!name || name.length > MAX_VENDOR_NAME_LEN || seen.has(name)) continue;
    seen.add(name);
    out.push({ name, isDefault: (row as { isDefault?: unknown }).isDefault === true });
  }
  if (out.length === 0) return null;
  // 기본 거래처는 정확히 1개 — 없으면 첫 행, 여럿이면 첫 지정만 남긴다(백엔드 정규화 미러).
  const firstDefault = out.findIndex((r) => r.isDefault);
  return out.map((r, i) => ({ ...r, isDefault: i === (firstDefault < 0 ? 0 : firstDefault) }));
}

/**
 * agents.settings.vendor_options → 분류별 후보 목록. **분류 단위 관대** 파서 —
 * 한 분류가 깨져도 나머지는 살리고, 깨진 분류만 기본값으로 폴백한다(백엔드 vendor_options_for 미러).
 */
export function vendorOptionsFromSettings(
  settings: Record<string, unknown> | undefined,
): VendorOptions {
  const raw = settings?.[VENDOR_OPTIONS_KEY];
  const dict = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {};
  return Object.fromEntries(
    VENDOR_CLASSES.map((c) => [
      c,
      parseClassRows(dict[c]) ?? DEFAULT_VENDOR_OPTIONS[c].map((r) => ({ ...r })),
    ]),
  ) as VendorOptions;
}
