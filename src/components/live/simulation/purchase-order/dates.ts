/**
 * 구매발주 계획서 — 납기 파생 날짜 유틸(순수 함수, model.ts 에서 분리).
 *
 * 모든 계산은 'yyyy-mm-dd' 문자열 입력만 쓴다 — new Date() 현재시각을 쓰지 않고,
 * Date.UTC 기반 ms 연산이라 로컬 타임존/DST 에 흔들리지 않는다.
 */

/**
 * 한국 공휴일·대체공휴일 — 데모용 정적 데이터, 실연동 시 공공데이터 API(특일 정보)로 교체.
 * 2026년 확정분 + 2027-01-01 만 수록 — 범위 밖 연도는 공휴일 보정 없이 주말 보정만 적용된다.
 */
const HOLIDAYS: ReadonlySet<string> = new Set([
  '2026-01-01', // 신정
  '2026-02-16', // 설연휴
  '2026-02-17', // 설날
  '2026-02-18', // 설연휴
  '2026-03-01', // 삼일절
  '2026-03-02', // 삼일절 대체공휴일
  '2026-05-05', // 어린이날
  '2026-05-24', // 부처님오신날
  '2026-05-25', // 부처님오신날 대체공휴일
  '2026-06-03', // 지방선거
  '2026-06-06', // 현충일
  '2026-08-15', // 광복절
  '2026-08-17', // 광복절 대체공휴일
  '2026-09-24', // 추석연휴
  '2026-09-25', // 추석
  '2026-09-26', // 추석연휴
  '2026-09-28', // 추석 대체공휴일
  '2026-10-03', // 개천절
  '2026-10-05', // 개천절 대체공휴일
  '2026-10-09', // 한글날
  '2026-12-25', // 성탄절
  '2027-01-01', // 신정
]);

const DAY_MS = 86_400_000;

/**
 * '1주 전'의 정의 = **영업일 5일 전**(사용자 확정 2026-08-21). 공휴일이 끼면 그만큼 —
 * 이동이 주말을 가로지르면 주말까지 건너뛰며 — 더 앞으로 가서 영업일 5일을 보존한다.
 */
const LEAD_BUSINESS_DAYS = 5;

/** 'yyyy-mm-dd' → UTC ms. 형식 불일치는 null. */
function parseUtc(iso: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

/** UTC ms → 'yyyy-mm-dd'. */
function toIso(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`;
}

/** 월~금 여부(UTC 요일 기준). */
function isWeekday(ms: number): boolean {
  const dow = new Date(ms).getUTCDay();
  return dow >= 1 && dow <= 5;
}

function isHoliday(ms: number): boolean {
  return HOLIDAYS.has(toIso(ms));
}

/** 영업일 여부 — 월~금이면서 공휴일이 아님. */
function isBusinessDay(ms: number): boolean {
  return isWeekday(ms) && !isHoliday(ms);
}

/**
 * date 에서 **영업일 n일 전** — 하루씩 거슬러 영업일만 세므로 주말·공휴일이 몇 번을
 * 가로막든 정확히 n영업일의 리드타임이 보존되고, 결과 자체도 항상 영업일이다.
 */
export function subtractBusinessDays(date: string, n: number): string {
  const start = parseUtc(date);
  if (start == null) return '';
  let d = start;
  for (let remain = n; remain > 0;) {
    d -= DAY_MS;
    if (isBusinessDay(d)) remain -= 1;
  }
  return toIso(d);
}

/**
 * 발주단위 납기(unitDue)의 '1주일 전' — 가공품 외 그룹(판금품·실거래처)의 기본 납기이자
 * 패턴 'N주 전' 규칙의 1회분. **1주 = 영업일 5일**(사용자 확정 2026-08-21) — 종전의
 * '달력 7일 − 평일 공휴일 보정' 방식은 이동이 주말을 가로지르면 영업일이 모자랐다.
 *
 * 사유: 가공품 외 거래처가 먼저 제작해 가공품 제작처로 보내고, 거기서 함께 조립해
 * 모듈 단위로 납품받기 위한 선행 리드타임이다.
 *
 * 검산 — 공휴일 없는 주: 2026-11-16(월) → 2026-11-09(월). 개천절·한글날 낀 주:
 * 2026-10-12(월) → 10-08·07·06·02·01 의 5영업일 → 2026-10-01(목). 설연휴(02-16~18) 낀 주:
 * 2026-02-23(월) → 20·19·13·12·11 → 2026-02-11(수).
 */
export function subtractLeadDays(unitDue: string): string {
  return subtractBusinessDays(unitDue, LEAD_BUSINESS_DAYS);
}
