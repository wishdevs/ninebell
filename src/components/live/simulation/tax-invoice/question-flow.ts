/**
 * 1단계 질문의 답 모델 + "한 번에 한 질문" 위저드 진행 규칙.
 *
 * 화면(questions-step.tsx)이 질문을 하나씩만 보여주려면 "지금 어느 질문인가 / 다음은 무엇인가 /
 * 이 경로의 질문은 모두 몇 개인가"를 알아야 한다. 그 판단을 전부 여기 모아 둔다 — 규칙이
 * JSX 안 조건문으로 흩어지면 발행 전/후 분기가 두 곳에서 어긋나기 때문이다.
 *
 * 답 타입(QuestionAnswers)과 완료 판정(answersComplete)은 뒤 단계들이 쓰는 계약이라
 * 여기 두고 questions-step.tsx 가 그대로 다시 내보낸다(기존 import 경로 유지).
 */

import {
  ISSUE_LABEL,
  NONDEDUCT_LABEL,
  SPLIT_LABEL,
  TAX_LABEL,
  type IssueState,
  type NondeductReason,
  type SplitChoice,
  type TaxKind,
} from './model';

// ── 답 ──────────────────────────────────────────────────────────────────────

/** 1단계에서 모으는 답 — 이후 모든 화면의 분기 근거. */
export interface QuestionAnswers {
  issue: IssueState | null;
  /** 세금계산서일 조회기간 — 발행 후에만 사용(리스트 필터). */
  invoiceFrom: string;
  invoiceTo: string;
  split: SplitChoice | null;
  tax: TaxKind | null;
  nondeduct: NondeductReason | null;
}

export function emptyAnswers(): QuestionAnswers {
  return { issue: null, invoiceFrom: '', invoiceTo: '', split: null, tax: null, nondeduct: null };
}

/** 다음 단계로 갈 수 있는가 — 이 경로의 마지막 질문까지 답이 채워졌는지. */
export function answersComplete(a: QuestionAnswers): boolean {
  if (!a.issue || !a.tax) return false;
  if (a.issue === 'before') return true; // 발행 전은 분할 질문 자체가 없다(아래 questionPath 주석).
  if (!a.split) return false;
  if (!a.invoiceFrom || !a.invoiceTo || a.invoiceFrom > a.invoiceTo) return false;
  if (a.tax === 'nondeduct' && !a.nondeduct) return false;
  return true;
}

// ── 위저드 스텝 ─────────────────────────────────────────────────────────────

/** 위저드가 한 번에 하나씩 보여주는 질문. */
export type QuestionKey = 'issue' | 'period' | 'split' | 'tax' | 'nondeduct';

/** 질문이 모두 끝나면 'done'(확인 화면) — 질문 자리를 비우지 않고 마무리를 보여준다. */
export type WizardStep = QuestionKey | 'done';

/** 질문 화면에 크게 거는 문장. */
export const QUESTION_TITLE: Record<QuestionKey, string> = {
  issue: '세금계산서 발행 전인가요?',
  period: '세금계산서일을 선택하세요',
  split: '비용분할이 필요한가요?',
  tax: '과세 / 비과세 / 불공 중 어떤 것인가요?',
  nondeduct: '불공 사유를 선택하세요',
};

/** 진행 표시·답 요약처럼 좁은 자리에 쓰는 짧은 이름. */
export const QUESTION_SHORT: Record<QuestionKey, string> = {
  issue: '발행 여부',
  period: '계산서일',
  split: '비용분할',
  tax: '과세여부',
  nondeduct: '불공 사유',
};

/**
 * 지금 답 기준의 질문 경로 — 경로에 따라 질문 수 자체가 달라진다.
 *
 * - 발행 **전**: 비용분할이 불가(사용자 확정 2026-08-03)라 분할을 묻지 않고, 불공도 코드가
 *   24 하나뿐이라 사유를 묻지 않는다 → 질문 2개.
 * - 발행 **후**: 계산서일·비용분할·과세여부 3개가 더 붙고, 불공을 고르면 사유까지 5개.
 * - 발행 여부를 아직 안 골랐으면 경로가 정해지지 않았다 → 첫 질문 하나만.
 */
export function questionPath(a: QuestionAnswers): readonly QuestionKey[] {
  if (a.issue === 'before') return ['issue', 'tax'];
  if (a.issue === 'after') {
    return a.tax === 'nondeduct'
      ? ['issue', 'period', 'split', 'tax', 'nondeduct']
      : ['issue', 'period', 'split', 'tax'];
  }
  return ['issue'];
}

/** 이 질문에 유효한 답이 있는가 — 기간은 역전(시작>종료)이면 답으로 치지 않는다. */
export function isAnswered(a: QuestionAnswers, k: QuestionKey): boolean {
  switch (k) {
    case 'issue':
      return a.issue !== null;
    case 'period':
      return !!a.invoiceFrom && !!a.invoiceTo && a.invoiceFrom <= a.invoiceTo;
    case 'split':
      return a.split !== null;
    case 'tax':
      return a.tax !== null;
    case 'nondeduct':
      return a.nondeduct !== null;
  }
}

/** 답 요약에 한 줄로 적는 값(미답이면 '—'). */
export function answerText(a: QuestionAnswers, k: QuestionKey): string {
  switch (k) {
    case 'issue':
      return a.issue ? ISSUE_LABEL[a.issue] : '—';
    case 'period':
      return a.invoiceFrom && a.invoiceTo ? `${a.invoiceFrom} ~ ${a.invoiceTo}` : '—';
    case 'split':
      return a.split ? SPLIT_LABEL[a.split] : '—';
    case 'tax':
      return a.tax ? TAX_LABEL[a.tax] : '—';
    case 'nondeduct':
      return a.nondeduct ? NONDEDUCT_LABEL[a.nondeduct] : '—';
  }
}

/**
 * `from` 질문 다음에 보여줄 스텝. 경로는 **답이 바뀐 뒤 기준**으로 계산해야 하므로
 * 호출부는 갱신된 답을 넘긴다(예: 과세여부를 불공으로 바꾸면 그때서야 사유 질문이 생긴다).
 */
export function stepAfter(a: QuestionAnswers, from: QuestionKey): WizardStep {
  const path = questionPath(a);
  const i = path.indexOf(from);
  if (i < 0) return 'done';
  return path[i + 1] ?? 'done';
}

/** `from` 질문 앞 질문(첫 질문이면 null). 'done' 에서는 경로의 마지막 질문으로 돌아간다. */
export function stepBefore(a: QuestionAnswers, from: WizardStep): QuestionKey | null {
  const path = questionPath(a);
  if (from === 'done') return path[path.length - 1] ?? null;
  const i = path.indexOf(from);
  return i > 0 ? path[i - 1] : null;
}

/**
 * 처음 열 때 보여줄 스텝 — 아직 답이 없으면 첫 질문, 뒤 단계에서 되돌아온 것이면 확인 화면.
 * (부모가 답을 들고 있어 리스트→'이전'으로 돌아오면 이미 다 채워진 상태로 다시 마운트된다.)
 */
export function initialStep(a: QuestionAnswers): WizardStep {
  for (const k of questionPath(a)) {
    if (!isAnswered(a, k)) return k;
  }
  return 'done';
}
