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

/** 가공품 외 거래처 선행 리드타임(일) — 발주단위 납기의 1주일 전. */
const LEAD_DAYS = 7;

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

/** 구간 [from, to) 의 평일(월~금) 공휴일 수. */
function weekdayHolidaysBetween(fromMs: number, toMs: number): number {
  let n = 0;
  for (let t = fromMs; t < toMs; t += DAY_MS) if (isWeekday(t) && isHoliday(t)) n += 1;
  return n;
}

/**
 * 발주단위 납기(unitDue)의 1주일 전 영업일 — 가공품 외 그룹(판금품·실거래처)의 기본 납기.
 *
 * 사유: 가공품 외 거래처가 먼저 제작해 가공품 제작처로 보내고, 거기서 함께 조립해
 * 모듈 단위로 납품받기 위한 선행 리드타임이다.
 *
 * 규칙 — ① 후보 D = unitDue − 7일. ② 구간 [D, unitDue) 의 평일 공휴일 n일만큼 D 를
 * 더 앞당기고, 구간이 넓어져 새로 편입된 평일 공휴일이 있으면 고정점까지 반복.
 * ③ 최종 D 가 토·일 또는 공휴일이면 직전 영업일로 이동.
 *
 * 검산 — unitDue 2026-10-12(월): 후보 10-05(월·대체공휴일), [10-05,10-12) 평일 공휴일
 * 10-05·10-09 로 2일 앞당겨 10-03(토), 신규 편입 없음(고정점), 토요일이라 직전 영업일
 * → 2026-10-02(금). 공휴일 없는 주: 2026-11-16 → 2026-11-09. 설연휴 낀 주: 2026-02-23
 * → 후보 02-16, 연휴(02-16~18) 3일 앞당겨 → 2026-02-13(금).
 */
export function subtractLeadDays(unitDue: string): string {
  const due = parseUtc(unitDue);
  if (due == null) return '';
  let d = due - LEAD_DAYS * DAY_MS;
  for (;;) {
    const next = due - (LEAD_DAYS + weekdayHolidaysBetween(d, due)) * DAY_MS;
    if (next === d) break; // 고정점 — 구간을 더 넓혀도 평일 공휴일 수가 그대로.
    d = next;
  }
  while (!isWeekday(d) || isHoliday(d)) d -= DAY_MS;
  return toIso(d);
}
