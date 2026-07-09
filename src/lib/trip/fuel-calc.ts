/**
 * 유류비 지원 금액 — 실행 전 폼의 미리보기 전용 계산.
 *
 * 확정 금액은 백엔드 `fuel_support_amount`(Decimal + ROUND_HALF_UP)가 계산하며 폼은 그 값을
 * 전송하지 않는다. 여기서는 사용자가 입력하는 동안 예상 금액을 보여주기 위한 미리보기만
 * 담당한다. 양수 입력에서 `Math.round`(= half-up)는 백엔드 ROUND_HALF_UP 과 일치한다.
 *
 * 차량종류는 **관리자가 추가/삭제하는 동적 목록**(agent.settings.fuel_classes)이다. 각 행 =
 * {id, label, kmPerL}. 차량종류는 ERP 로 전송되지 않고 유류비 금액 계산 조회용이다(백엔드 동일).
 */

/** 차량종류 한 행 — 백엔드 fuel_classes 행과 동일 형태. */
export interface FuelClass {
  id: string;
  label: string;
  kmPerL: number;
}

/** 설정 키(백엔드와 동일). */
export const FUEL_CLASSES_KEY = 'fuel_classes';
export const FUEL_UNIT_PRICE_KEY = 'fuel_unit_price';

/** 저장값이 없을 때의 기본 차량종류(백엔드 DEFAULT_FUEL_CLASSES 미러). */
export const DEFAULT_FUEL_CLASSES: readonly FuelClass[] = [
  { id: 'under1000', label: '1,000cc 미만', kmPerL: 14 },
  { id: 'under1600', label: '1,600cc 미만', kmPerL: 9 },
  { id: 'under2000', label: '2,000cc 미만', kmPerL: 7 },
  { id: 'over2000', label: '2,000cc 이상', kmPerL: 6 },
];

type Settings = Record<string, unknown>;

function isFuelClass(v: unknown): v is FuelClass {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as FuelClass).id === 'string' &&
    typeof (v as FuelClass).label === 'string' &&
    typeof (v as FuelClass).kmPerL === 'number'
  );
}

/** 실효 설정에서 차량종류 목록을 읽는다(유효하면). 없으면 기본 4종. */
export function fuelClassesFromSettings(settings: Settings | undefined): FuelClass[] {
  const raw = settings?.[FUEL_CLASSES_KEY];
  if (Array.isArray(raw) && raw.length > 0 && raw.every(isFuelClass)) {
    return raw.map((c) => ({ id: c.id, label: c.label, kmPerL: c.kmPerL }));
  }
  return DEFAULT_FUEL_CLASSES.map((c) => ({ ...c }));
}

function asPositiveNumber(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * km ÷ 기준연비 × 기준단가 → 원 단위(half-up). 차량종류 id 를 목록에서 찾아 kmPerL 을 쓴다.
 * 설정이 없거나 비양수, 미지의 차량종류면 null(미리보기 생략).
 */
export function fuelSupportAmount(km: number, classId: string, settings: Settings): number | null {
  if (!Number.isFinite(km) || km <= 0) return null;
  const cls = fuelClassesFromSettings(settings).find((c) => c.id === classId);
  const eff = cls ? asPositiveNumber(cls.kmPerL) : null;
  const unitPrice = asPositiveNumber(settings[FUEL_UNIT_PRICE_KEY]);
  if (eff == null || unitPrice == null) return null;
  // 곱셈 먼저(km×단가) 후 나눗셈 — 백엔드 fuel_support_amount 와 동일 순서(정확한 .5 경계 일치).
  return Math.round((km * unitPrice) / eff);
}
