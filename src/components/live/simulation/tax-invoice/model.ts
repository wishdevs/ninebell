/**
 * 세금계산서 결의서 — 프론트 더미 시뮬레이션 모델(타입·더미데이터·선택지·포맷터).
 *
 * 백엔드 자동화 그래프는 아직 없다. 이 화면은 "무엇을 물어보고 무엇을 입력받아야 하는가"를
 * 먼저 확정하기 위한 화면 시뮬레이션이며, 실행 API(`POST /runs/collect`)를 타지 않는다.
 * 실제 연동 시 이 파일의 선택지(예산단위·프로젝트·자금과목…)는 `/me/codes` 카탈로그로,
 * INVOICE_ROWS 는 옴니솔 세금계산서 조회 결과로 교체한다.
 */

// ── 1단계 질문 값 ────────────────────────────────────────────────────────────

/** 세금계산서 발행 전/후 — 이후 경로(바로 입력 vs 리스트 선택)를 가른다. */
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

// ── 증빙유형 ────────────────────────────────────────────────────────────────
// 1단계 질문의 답이 곧 ERP 증빙유형 코드다(발행 여부 × 과세성격 × 불공사유 → 코드 1개).
// 요약 화면이 params 스키마의 출발점이므로 여기서 코드를 확정해 보여준다.

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
  /** 표시할 주의 문구(없으면 undefined) — 코드 체계가 조합을 다 담지 못하는 자리. */
  caution?: string;
}

/**
 * 답 조합 → 증빙유형. 아직 못 정하면 null(질문이 덜 끝났다는 뜻).
 *
 * **비용분할은 원증빙으로 넣는다**(사용자 확정 2026-08-03) — 분할이면 과세 11 · 비과세 13.
 * 불공은 애초에 분할할 수 없으므로 분할 × 불공 조합은 존재하지 않는다.
 *
 * ⚠ 발행 전 불공은 코드가 **24(차량용) 하나뿐**이라 차량 외 사유를 담을 자리가 없다.
 *   업무 확인 전까지 코드는 24 로 두되 그 사실을 화면에 드러낸다(조용히 뭉개지 않는다).
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
      caution: '발행 전 불공 코드는 24(차량용) 하나뿐입니다 — 차량 외 사유는 담을 코드가 없습니다.',
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

// ── 세금계산서 리스트(더미) ──────────────────────────────────────────────────

export interface TaxInvoiceRow {
  no: number;
  /** (세금)계산서일 — yyyy-mm-dd. */
  invoiceDate: string;
  bizNo: string;
  bizName: string;
  subBizNo: string;
  partnerCode: string;
  partnerBizNo: string;
  partnerName: string;
  partnerSubBizNo: string;
  /** 공급가액 — 취소분은 음수. */
  supplyAmount: number;
  /** 세액 — 취소분은 음수. */
  taxAmount: number;
}

/**
 * 옴니솔 세금계산서 조회 화면 실측 더미(사용자 제공 스크린샷 그대로).
 * 4번 행은 3번 행의 취소분(음수) — 음수 행도 리스트에 정상 표시되고 선택 가능해야 한다.
 */
export const INVOICE_ROWS: readonly TaxInvoiceRow[] = [
  row(1, '2026-07-01', '15745', '543-86-02659', '노무법인 좋은', 400_000, 40_000),
  row(2, '2026-07-01', '20326', '143-81-32507', '법무법인 비트', 1_000_000, 100_000),
  row(3, '2026-07-03', '10117', '114-86-62779', '(주) 에스테크엘', 214_000, 21_400),
  row(4, '2026-07-03', '10117', '114-86-62779', '(주) 에스테크엘', -214_000, -21_400),
  row(5, '2026-07-03', '15311', '109-83-02763', '인천공항세관', 5_476_039, 547_600),
  row(6, '2026-07-03', '10042', '129-29-40129', '유앤아이관세사무소', 103_830, 10_383),
  row(7, '2026-07-06', '10132', '102-81-42945', '주식회사 케이티', 537_554, 53_755),
  row(8, '2026-07-06', '30140', '220-05-53810', '특허사무소 시선', 1_500_000, 150_000),
  row(9, '2026-07-06', '10132', '102-81-42945', '주식회사 케이티', 34_000, 3_400),
  row(10, '2026-07-09', '15892', '222-82-75825', '르네상스대표자회', 145_990, 14_600),
  row(11, '2026-07-10', '10168', '202-81-00978', '중소기업은행', 136_363, 13_637),
];

/** 자사(사업장) 정보는 전 행 동일 — 반복을 줄이려 팩토리로 만든다. */
function row(
  no: number,
  invoiceDate: string,
  partnerCode: string,
  partnerBizNo: string,
  partnerName: string,
  supplyAmount: number,
  taxAmount: number,
): TaxInvoiceRow {
  return {
    no,
    invoiceDate,
    bizNo: '123-81-44708',
    bizName: '(주)나인벨',
    subBizNo: '',
    partnerCode,
    partnerBizNo,
    partnerName,
    partnerSubBizNo: '',
    supplyAmount,
    taxAmount,
  };
}

/** 더미 리스트가 덮는 (세금)계산서일 범위 — 기간 힌트 표시용. */
export const INVOICE_DATE_MIN = '2026-07-01';
export const INVOICE_DATE_MAX = '2026-07-10';

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * 기간 기본값 — **한 달 전부터 오늘까지**(사용자 확정 2026-08-03).
 *
 * 실무 조회는 대개 최근 한 달이라 발행 후를 고르는 즉시 채워 두고, 필요하면 사용자가 바꾼다.
 * 말일 보정: setMonth 는 3/31→2/31 같은 없는 날짜를 다음 달로 넘기므로, 넘어갔으면 그 달의
 * 말일로 당긴다(3/31 → 2/28).
 */
export function defaultInvoiceRange(): { from: string; to: string } {
  const today = new Date();
  const from = new Date(today);
  const day = from.getDate();
  from.setMonth(from.getMonth() - 1);
  if (from.getDate() !== day) from.setDate(0);
  return { from: isoDate(from), to: isoDate(today) };
}

// ── 입력항목 선택지(더미) ────────────────────────────────────────────────────

export const BUDGET_UNITS: readonly string[] = [
  '지급수수료-경영지원팀(판)',
  '지급수수료-개발팀(판)',
  '세금과공과-경영지원팀(판)',
  '통신비-경영지원팀(판)',
  '수출제비용-영업팀(판)',
  '소모품비-개발팀(제)',
];

/** 프로젝트 — 500/800(공통비 배부) 또는 개별 프로젝트 선택. */
export const PROJECTS: readonly string[] = [
  '500',
  '800',
  'PJT-2026-011 옴니솔 자동화',
  'PJT-2026-024 해외영업 확대',
  'PJT-2025-097 사내 인프라 개선',
];

/** 거래처 — 발행 전 경로의 직접 선택용. 더미 리스트의 거래처명을 그대로 재사용한다. */
export const PARTNER_NAMES: readonly string[] = [
  ...new Set(INVOICE_ROWS.map((r) => r.partnerName)),
];

export const FUND_ACCOUNTS: readonly string[] = ['일반경비', '급여', '외주비', '설비투자'];

export const PAY_TERMS: readonly string[] = ['당월결제', '익월결제', '즉시결제'];

/** 비과세일 때만 노출되는 사유구분. */
export const EXEMPT_REASONS: readonly string[] = ['일반면세', '면세농산물', '기타면세'];

/** 비용분할 행의 비용센터. */
export const COST_CENTERS: readonly string[] = [
  '경영지원팀',
  '개발팀',
  '영업팀',
  '해외사업팀',
  '생산팀',
];

// ── 입력값 ───────────────────────────────────────────────────────────────────

export interface EntryValues {
  /** 거래처 — 발행 전 전용(발행 후는 선택한 리스트 행이 거래처를 가진다). */
  partner: string;
  /** 공급가액 — 발행 전 전용(발행 후는 선택 행 합계). 원 단위 정수 문자열. */
  supplyAmount: string;
  budgetUnit: string;
  note: string;
  project: string;
  /** 회계일 — 발행 후면 (세금)계산서일과 동일하게 자동 세팅된다. */
  acctDate: string;
  fundAccount: string;
  payTerm: string;
  fundDueDate: string;
  /** 사유구분 — 비과세일 때만 사용. */
  exemptReason: string;
}

export function emptyEntry(): EntryValues {
  return {
    partner: '',
    supplyAmount: '',
    budgetUnit: '',
    note: '',
    project: '',
    acctDate: '',
    // 3-1 고정 기본값(사용자 정의) — 자금과목 일반경비 · 결제조건 당월결제.
    fundAccount: FUND_ACCOUNTS[0],
    payTerm: PAY_TERMS[0],
    fundDueDate: '',
    exemptReason: EXEMPT_REASONS[0],
  };
}

// ── 비용분할 ─────────────────────────────────────────────────────────────────

export interface SplitRow {
  id: string;
  budgetUnit: string;
  note: string;
  project: string;
  /** 원 단위 정수 문자열(음수 허용 — 취소분 분할). 검증·잔액 계산의 단일 원천. */
  amount: string;
  /** 퍼센트 입력값(퍼센트 모드에서 amount 를 파생시킨다). */
  percent: string;
  costCenter: string;
}

let splitSeq = 0;
export function newSplitRow(): SplitRow {
  splitSeq += 1;
  return {
    id: `s${splitSeq}`,
    budgetUnit: '',
    note: '',
    project: '',
    amount: '',
    percent: '',
    costCenter: '',
  };
}

/** 분할 입력 방식 — 금액 직접 입력 ↔ 퍼센트 입력(금액 자동 계산). */
export type SplitMode = 'amount' | 'percent';

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
