/**
 * 유류비 지원 금액 — 실행 전 폼의 미리보기 전용 계산.
 *
 * 확정 금액은 백엔드 `fuel_support_amount`(Decimal + ROUND_HALF_UP)가 계산하며 폼은 그 값을
 * 전송하지 않는다. 여기서는 사용자가 입력하는 동안 예상 금액을 보여주기 위한 미리보기만
 * 담당한다. 양수 입력에서 `Math.round`(= half-up)는 백엔드 ROUND_HALF_UP 과 일치한다.
 */

/** 차량종류 — 백엔드 CarClass 와 동일 리터럴. */
export type CarClass = 'under1000' | 'under1600' | 'under2000' | 'over2000';

/** 차량종류 → 기준연비 설정 키(백엔드 CAR_CLASS_EFF_KEY 미러). */
export const CAR_CLASS_EFF_KEY: Record<CarClass, string> = {
  under1000: 'fuel_eff_under_1000',
  under1600: 'fuel_eff_under_1600',
  under2000: 'fuel_eff_under_2000',
  over2000: 'fuel_eff_over_2000',
};

/** 기준단가 설정 키. */
export const FUEL_UNIT_PRICE_KEY = 'fuel_unit_price';

/** 차량종류 한국어 라벨(폼 셀렉트 옵션). */
export const CAR_CLASS_LABEL: Record<CarClass, string> = {
  under1000: '1,000cc 미만',
  under1600: '1,600cc 미만',
  under2000: '2,000cc 미만',
  over2000: '2,000cc 이상',
};

/** 셀렉트 렌더 순서. */
export const CAR_CLASSES: readonly CarClass[] = ['under1000', 'under1600', 'under2000', 'over2000'];

type Settings = Record<string, number | string | boolean>;

function asPositiveNumber(value: number | string | boolean | undefined): number | null {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * km ÷ 기준연비 × 기준단가 → 원 단위(half-up). 설정이 없거나 비양수면 null(미리보기 생략).
 */
export function fuelSupportAmount(
  km: number,
  carClass: CarClass,
  settings: Settings,
): number | null {
  if (!Number.isFinite(km) || km <= 0) return null;
  const eff = asPositiveNumber(settings[CAR_CLASS_EFF_KEY[carClass]]);
  const unitPrice = asPositiveNumber(settings[FUEL_UNIT_PRICE_KEY]);
  if (eff == null || unitPrice == null) return null;
  // 곱셈 먼저(km×단가) 후 나눗셈 — 백엔드 fuel_support_amount 와 동일 순서(정확한 .5 경계 일치).
  return Math.round((km * unitPrice) / eff);
}
