/**
 * 세금계산서 결의서 — 실행 전 폼 모델(타입·증빙유형 매핑·기간·분할 계산·포맷터).
 *
 * 시뮬레이션(`src/components/live/simulation/tax-invoice/` — .recycles/ 이동)에서 승격.
 * 백엔드 계약 `params["tax_invoice"]` 와 짝이다 — 특히 evidenceFor 는 서버의
 * evidence_for(issue, split, tax, nondeduct_reason) 와 **같은 매핑**이어야 한다
 * (두 구현이 어긋나면 안 된다. 계약: 03/04/05/06/07/11/13/22/23/24).
 */

// ── 1단계 질문 값 ────────────────────────────────────────────────────────────

/** 세금계산서 발행 전/후 — 이후 경로(바로 입력 vs 라이브 리스트 선택)를 가른다. */
export type IssueState = 'before' | 'after';

/** 비용분할 여부. */
export type SplitChoice = 'single' | 'split';

/** 과세여부. 불공은 분할이 불가능해 분할 선택 시 목록에서 제외된다. */
export type TaxKind = 'taxable' | 'exempt' | 'nondeduct';

/** 불공 사유 — 발행 후 + 불공일 때만 묻는다. */
export type NondeductReason = 'no-business' | 'small-car' | 'exempt-business';

export const ISSUE_LABEL: Record<IssueState, string> = {
  before: '세금계산서 발행 전',
  after: '세금계산서 발행 후',
};

export const SPLIT_LABEL: Record<SplitChoice, string> = {
  single: '분할 없음',
  split: '비용분할',
};

export const TAX_LABEL: Record<TaxKind, string> = {
  taxable: '과세',
  exempt: '비과세',
  nondeduct: '불공',
};

export const NONDEDUCT_LABEL: Record<NondeductReason, string> = {
  'no-business': '사업과 관련없는 지출',
  'small-car': '비영업용소형승용차구입, 유지 및 임차',
  'exempt-business': '면세사업과 관련된분',
};

// ── 백엔드 계약 값 매핑 ──────────────────────────────────────────────────────
// params["tax_invoice"] 의 문자열 값. tax 는 UI 값과 동일 문자열이라 매핑이 필요 없다.

/** UI 발행 여부 ↔ 계약 issue("pre"|"post"). */
export const API_ISSUE: Record<IssueState, 'pre' | 'post'> = { before: 'pre', after: 'post' };

/** UI 불공 사유 ↔ 계약 nondeduct_reason("none_biz"|"car"|"exempt_biz"). */
export const API_NONDEDUCT: Record<NondeductReason, 'none_biz' | 'car' | 'exempt_biz'> = {
  'no-business': 'none_biz',
  'small-car': 'car',
  'exempt-business': 'exempt_biz',
};

/** 계약값 → UI 값 역매핑(마지막 제출 params 복원용). 모르는 값은 null. */
export function issueFromApi(v: unknown): IssueState | null {
  return v === 'pre' ? 'before' : v === 'post' ? 'after' : null;
}

export function taxFromApi(v: unknown): TaxKind | null {
  return v === 'taxable' || v === 'exempt' || v === 'nondeduct' ? v : null;
}

export function nondeductFromApi(v: unknown): NondeductReason | null {
  const entry = (Object.entries(API_NONDEDUCT) as [NondeductReason, string][]).find(
    ([, api]) => api === v,
  );
  return entry ? entry[0] : null;
}

// ── 증빙유형 ────────────────────────────────────────────────────────────────
// 1단계 질문의 답이 곧 ERP 증빙유형 코드다(발행 여부 × 과세성격 × 불공사유 → 코드 1개).
// 코드 도출 자체는 서버(evidence_for)가 하지만, 폼이 같은 매핑으로 미리 보여준다.

export const EVIDENCE_LABEL: Record<string, string> = {
  '03': '세금계산서',
  '04': '계산서',
  '05': '세금계산서(불공) 사업과 관련없는 지출',
  '06': '세금계산서(불공) 비영업용소형승용차구입, 유지 및 임차',
  '07': '세금계산서(불공) 면세사업과 관련된분',
  '11': '세금계산서(원증빙)',
  '13': '계산서(원증빙)',
  '22': '세금계산서 발행 전 입력(과세)',
  '23': '세금계산서 발행 전 입력(비과세)',
  '24': '세금계산서 발행 전 (과세)불공 차량용',
};

const NONDEDUCT_EVIDENCE: Record<NondeductReason, string> = {
  'no-business': '05',
  'small-car': '06',
  'exempt-business': '07',
};

export interface EvidenceType {
  code: string;
  label: string;
  /** 코드 선택 근거를 덧붙일 때(없으면 undefined) — 조합이 한 코드로 접히는 자리 등. */
  note?: string;
}

/**
 * 답 조합 → 증빙유형. 아직 못 정하면 null(질문이 덜 끝났다는 뜻).
 *
 * **비용분할은 원증빙으로 넣는다**(사용자 확정 2026-08-03) — 분할이면 과세 11 · 비과세 13.
 * 불공은 애초에 분할할 수 없으므로 분할 × 불공 조합은 존재하지 않는다.
 *
 * 발행 전 불공은 코드 **24 하나**다(사용자 확정 2026-08-04) — 발행 후는 사유별로 05·06·07 로
 * 갈리지만 발행 전은 사유를 나누지 않는다. 그래서 발행 전 경로는 불공 사유를 묻지 않는다.
 */
export function evidenceFor(
  issue: IssueState | null,
  split: SplitChoice | null,
  tax: TaxKind | null,
  nondeduct: NondeductReason | null,
): EvidenceType | null {
  if (!issue || !tax) return null;
  if (issue === 'before') {
    if (tax === 'taxable') return { code: '22', label: EVIDENCE_LABEL['22'] };
    if (tax === 'exempt') return { code: '23', label: EVIDENCE_LABEL['23'] };
    return {
      code: '24',
      label: EVIDENCE_LABEL['24'],
      note: '발행 전 불공은 사유를 나누지 않고 이 코드 하나로 넣습니다.',
    };
  }
  // 발행 후 — 분할이면 원증빙 계열로 갈린다.
  if (split === 'split') {
    if (tax === 'taxable') return { code: '11', label: EVIDENCE_LABEL['11'] };
    if (tax === 'exempt') return { code: '13', label: EVIDENCE_LABEL['13'] };
    return null; // 불공 × 분할은 성립하지 않는다(질문 단계에서 이미 막힌다)
  }
  if (tax === 'taxable') return { code: '03', label: EVIDENCE_LABEL['03'] };
  if (tax === 'exempt') return { code: '04', label: EVIDENCE_LABEL['04'] };
  if (!nondeduct) return null; // 불공은 사유까지 골라야 코드가 정해진다
  const code = NONDEDUCT_EVIDENCE[nondeduct];
  return { code, label: EVIDENCE_LABEL[code] };
}

// ── 바로 선택(숙련자 지름길) ─────────────────────────────────────────────────
// 증빙유형 코드는 질문 답 조합과 1:1 이라 **역방향 채움**이 성립한다 — 코드를 알면 질문을
// 건너뛰고 바로 고른다. evidenceFor 와 같은 파일에 두는 이유: 정방향(답→코드)과 역방향
// (코드→답)이 어긋나면 안 되는 한 쌍의 규칙이기 때문이다.

export interface QuickPick {
  code: string;
  /** 그룹 라벨이 문맥을 제공하므로 짧게(예: '발행 전' 그룹의 '과세'). */
  label: string;
  issue: IssueState;
  split: SplitChoice;
  tax: TaxKind;
  nondeduct: NondeductReason | null;
}

export const QUICK_PICK_GROUPS: readonly { name: string; picks: readonly QuickPick[] }[] = [
  {
    name: '발행 후',
    picks: [
      {
        code: '03',
        label: '세금계산서',
        issue: 'after',
        split: 'single',
        tax: 'taxable',
        nondeduct: null,
      },
      {
        code: '04',
        label: '계산서',
        issue: 'after',
        split: 'single',
        tax: 'exempt',
        nondeduct: null,
      },
      {
        code: '05',
        label: '불공·사업무관',
        issue: 'after',
        split: 'single',
        tax: 'nondeduct',
        nondeduct: 'no-business',
      },
      {
        code: '06',
        label: '불공·차량',
        issue: 'after',
        split: 'single',
        tax: 'nondeduct',
        nondeduct: 'small-car',
      },
      {
        code: '07',
        label: '불공·면세사업',
        issue: 'after',
        split: 'single',
        tax: 'nondeduct',
        nondeduct: 'exempt-business',
      },
    ],
  },
  {
    name: '발행 후·분할',
    picks: [
      {
        code: '11',
        label: '과세',
        issue: 'after',
        split: 'split',
        tax: 'taxable',
        nondeduct: null,
      },
      {
        code: '13',
        label: '비과세',
        issue: 'after',
        split: 'split',
        tax: 'exempt',
        nondeduct: null,
      },
    ],
  },
  {
    name: '발행 전',
    picks: [
      {
        code: '22',
        label: '과세',
        issue: 'before',
        split: 'single',
        tax: 'taxable',
        nondeduct: null,
      },
      {
        code: '23',
        label: '비과세',
        issue: 'before',
        split: 'single',
        tax: 'exempt',
        nondeduct: null,
      },
      {
        code: '24',
        label: '불공',
        issue: 'before',
        split: 'single',
        tax: 'nondeduct',
        nondeduct: null,
      },
    ],
  },
];

// ── 조회기간 ─────────────────────────────────────────────────────────────────

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export interface DateRange {
  from: string;
  to: string;
}

/** 이번 달 1일 ~ 오늘. */
export function thisMonthToToday(): DateRange {
  const t = new Date();
  return { from: isoDate(new Date(t.getFullYear(), t.getMonth(), 1)), to: isoDate(t) };
}

/**
 * 오늘 기준 N개월 전 ~ 오늘(롤링). 오늘이 8/5면 한 달 전은 7/5 부터다.
 *
 * 말일 보정: setMonth 는 3/31→2/31 같은 없는 날짜를 다음 달로 넘기므로 그 달 말일로 당긴다.
 */
export function monthsAgoToToday(months: number): DateRange {
  const t = new Date();
  const f = new Date(t);
  const day = f.getDate();
  f.setMonth(f.getMonth() - months);
  if (f.getDate() !== day) f.setDate(0);
  return { from: isoDate(f), to: isoDate(t) };
}

/**
 * 기간 빠른 선택(사용자 확정 2026-08-04) — 이번 달만 1일 기준이고 나머지는 오늘 기준 롤링이다.
 * 날짜는 달력으로 직접 고를 수도 있으며, 그 경우 어떤 프리셋도 활성이 아니다.
 */
export const RANGE_PRESETS: readonly { id: string; label: string; range: () => DateRange }[] = [
  { id: 'this-month', label: '이번 달', range: thisMonthToToday },
  { id: 'months-1', label: '한 달 전', range: () => monthsAgoToToday(1) },
  { id: 'months-2', label: '두 달 전', range: () => monthsAgoToToday(2) },
];

/** 기간 기본값 — 계약 기본과 동일하게 이번 달 1일~오늘(period_from/to 기본값). */
export function defaultInvoiceRange(): DateRange {
  return thisMonthToToday();
}

// ── 비용분할 계획 ────────────────────────────────────────────────────────────

/** 계약 split_rows 한 행의 편집 상태. amount 는 원 단위 정수 문자열(마지막 행은 차액반영=미입력). */
export interface SplitRow {
  id: string;
  note: string;
  /** 프로젝트 — 카탈로그 선택(code = 'PJT_NO|WBS_NO' 합성, 제출은 WBS 만). */
  projectCode: string;
  projectName: string;
  costCenter: string;
  /** 원 단위 정수 문자열(음수 허용 — 취소분 분할). 마지막 행은 차액반영이라 비워 둔다. */
  amount: string;
  /** 퍼센트 입력값(퍼센트 모드에서 amount 를 파생시킨다 — 참고 총액이 있을 때만). */
  percent: string;
}

let splitSeq = 0;
export function newSplitRow(): SplitRow {
  splitSeq += 1;
  return {
    id: `s${splitSeq}`,
    note: '',
    projectCode: '',
    projectName: '',
    costCenter: '',
    amount: '',
    percent: '',
  };
}

/** 분할 입력 방식 — 금액 직접 입력 ↔ 퍼센트 입력(금액 자동 계산). */
export type SplitMode = 'amount' | 'percent';

/** 분할 행 수 제한(계약: 2~20행). */
export const MIN_SPLIT_ROWS = 2;
export const MAX_SPLIT_ROWS = 20;

// ── 포맷·파싱 ────────────────────────────────────────────────────────────────

/** 천단위 구분 문자열(원 단위). */
export function formatWon(n: number): string {
  return n.toLocaleString('ko-KR');
}

/** '−214,000' 같은 입력을 정수로. 형식이 안 맞으면 null(빈 문자열 포함). */
export function parseAmount(raw: string): number | null {
  const s = raw.replace(/,/g, '').trim();
  if (!/^-?\d+$/.test(s)) return null;
  return Number(s);
}

/** 퍼센트 문자열 → 숫자(소수 2자리까지). 형식 불일치는 null. */
export function parsePercent(raw: string): number | null {
  const s = raw.trim();
  if (!/^-?\d*\.?\d*$/.test(s) || s === '' || s === '-' || s === '.') return null;
  return Number(s);
}

/** 퍼센트 → 금액(원 단위 반올림). 총액이 음수여도 부호가 유지된다. */
export function amountFromPercent(total: number, percent: number): number {
  return Math.round((total * percent) / 100);
}

/** 금액 → 퍼센트(소수 2자리). 총액 0 이면 계산 불가 → null. */
export function percentFromAmount(total: number, amount: number): number | null {
  if (total === 0) return null;
  return Math.round(((amount / total) * 100 + Number.EPSILON) * 100) / 100;
}
