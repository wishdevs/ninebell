/**
 * 1단계 질문의 답 모델 + 경로 규칙.
 *
 * 화면(questions-step.tsx)이 어떤 질문 행을 보여줄지는 경로(questionPath)가 정한다 — 규칙이
 * JSX 안 조건문으로 흩어지면 발행 전/후 분기가 두 곳에서 어긋나기 때문에 여기 모아 둔다.
 *
 * 답 타입(QuestionAnswers)과 완료 판정(answersComplete)은 뒤 단계들이 쓰는 계약이라
 * 여기 두고 questions-step.tsx 가 그대로 다시 내보낸다(기존 import 경로 유지).
 */

import { defaultInvoiceRange } from './model';
import type { IssueState, NondeductReason, SplitChoice, TaxKind } from './model';

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

/**
 * 빈 답 — **무효화 프리미티브**다. 발행 여부를 바꿀 때 뒤 답을 지우는 데 재사용되므로
 * (questions-step 의 pickIssue) 여기에 프리셋을 넣으면 안 된다. 시작 상태는 defaultAnswers.
 */
export function emptyAnswers(): QuestionAnswers {
  return { issue: null, invoiceFrom: '', invoiceTo: '', split: null, tax: null, nondeduct: null };
}

/**
 * 시작 상태 — 가장 흔한 증빙유형 **03 세금계산서** 조합을 미리 골라 둔다
 * (발행 후 · 비용분할 안 함 · 과세, 사용자 확정 2026-08-11).
 * 코드 그리드부터 고르게 하면 코드를 아는 사람만 빨랐다. 이제 질문 화면이 답이 채워진 채
 * 열리고, 다른 건이면 해당 행만 눌러 바꾸면 된다.
 */
export function defaultAnswers(): QuestionAnswers {
  const range = defaultInvoiceRange();
  return {
    issue: 'after',
    invoiceFrom: range.from,
    invoiceTo: range.to,
    split: 'single',
    tax: 'taxable',
    nondeduct: null,
  };
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

// ── 질문 경로 ───────────────────────────────────────────────────────────────

/** 화면에 행으로 눕는 질문. */
export type QuestionKey = 'issue' | 'period' | 'split' | 'tax' | 'nondeduct';

/** 질문 행 라벨처럼 좁은 자리에 쓰는 짧은 이름. */
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
