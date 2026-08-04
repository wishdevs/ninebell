'use client';

import { RiArrowRightLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { ChoiceOption, QuestionBlock, SimStepHeader } from './ui';
import {
  defaultInvoiceRange,
  evidenceFor,
  RANGE_PRESETS,
  INVOICE_DATE_MAX,
  INVOICE_DATE_MIN,
  ISSUE_LABEL,
  NONDEDUCT_LABEL,
  SPLIT_LABEL,
  TAX_LABEL,
  type IssueState,
  type NondeductReason,
  type SplitChoice,
  type TaxKind,
} from './model';

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

/** 다음 단계로 갈 수 있는가 — 점진적 노출의 마지막 질문까지 답이 채워졌는지. */
export function answersComplete(a: QuestionAnswers): boolean {
  if (!a.issue || !a.tax) return false;
  if (a.issue === 'before') return true; // 발행 전은 분할 질문 자체가 없다(아래 주석).
  if (!a.split) return false;
  if (!a.invoiceFrom || !a.invoiceTo || a.invoiceFrom > a.invoiceTo) return false;
  if (a.tax === 'nondeduct' && !a.nondeduct) return false;
  return true;
}

interface QuestionsStepProps {
  value: QuestionAnswers;
  onChange: (next: QuestionAnswers) => void;
  onNext: () => void;
}

/**
 * 1단계 — 점진적 노출 질문. 앞 질문에 답해야 다음 질문이 나타난다.
 *
 * 분할↔불공 상호배제: 불공은 분할할 수 없다. 분할 질문이 과세여부 질문보다 **앞**에 있으므로
 * 자연스러운 방향은 "분할을 켜면 과세여부 목록에서 불공이 사라지는" 쪽이다. 이미 불공을 고른
 * 뒤에 되돌아와 분할을 켜면 과세여부 선택을 해제해 다시 고르게 한다(잘못된 조합이 남지 않게).
 */
export function QuestionsStep({ value, onChange, onNext }: QuestionsStepProps) {
  const set = (patch: Partial<QuestionAnswers>) => onChange({ ...value, ...patch });

  const pickIssue = (issue: IssueState) => {
    if (value.issue === issue) return;
    // 경로가 바뀌면 뒤 질문은 무효 — 전부 비운다(발행 전은 기간 자체가 없다).
    // 발행 전은 **비용분할이 불가**(사용자 확정 2026-08-03)라 split 을 'single' 로 고정한다
    // — 질문을 숨기기만 하고 null 로 두면 뒤 단계가 '미답' 으로 막힌다.
    // 발행 후는 기간을 **한 달 전~오늘**로 미리 채운다 — 필요하면 달력이나 빠른 선택으로 바꾼다.
    const range = issue === 'after' ? defaultInvoiceRange() : { from: '', to: '' };
    onChange({
      ...emptyAnswers(),
      issue,
      split: issue === 'before' ? 'single' : null,
      invoiceFrom: range.from,
      invoiceTo: range.to,
    });
  };

  const pickSplit = (split: SplitChoice) => {
    // 분할을 켜면 불공 조합은 성립하지 않는다 → 과세여부를 해제해 다시 고르게 한다.
    const invalidates = split === 'split' && value.tax === 'nondeduct';
    set({ split, ...(invalidates ? { tax: null, nondeduct: null } : {}) });
  };

  const pickTax = (tax: TaxKind) => {
    set({ tax, nondeduct: tax === 'nondeduct' ? value.nondeduct : null });
  };

  // 과세여부 선택지 — 분할이면 불공을 목록에서 제외한다(미노출).
  const taxOptions: TaxKind[] =
    value.split === 'split' ? ['taxable', 'exempt'] : ['taxable', 'exempt', 'nondeduct'];

  const rangeInvalid =
    !!value.invoiceFrom && !!value.invoiceTo && value.invoiceFrom > value.invoiceTo;
  // 비용분할은 **발행 후 전용**(사용자 확정 2026-08-03: "세금발행전일때는 비용분할이 안됩니다").
  // 발행 전은 이 질문을 건너뛰고 과세여부로 바로 간다(split 은 pickIssue 가 'single' 로 고정).
  const showSplitQuestion =
    value.issue === 'after' && !!value.invoiceFrom && !!value.invoiceTo && !rangeInvalid;
  const showTaxQuestion = value.issue === 'before' || (showSplitQuestion && value.split !== null);
  const showNondeductQuestion =
    showTaxQuestion && value.issue === 'after' && value.tax === 'nondeduct';

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <SimStepHeader
        title="세금계산서 결의서 — 어떤 건인가요?"
        prompt="답을 고르면 다음 질문이 나타납니다. 모든 질문에 답해야 입력 단계로 넘어갑니다."
      />

      <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto pr-1">
        <QuestionBlock step={1} label="세금계산서 발행 전인가요?">
          <ChoiceOption
            label={ISSUE_LABEL.before}
            description="아직 발행되지 않아 리스트가 없습니다 — 바로 입력항목을 채웁니다."
            active={value.issue === 'before'}
            onClick={() => pickIssue('before')}
          />
          <ChoiceOption
            label={ISSUE_LABEL.after}
            description="이미 발행되어 조회됩니다 — 리스트에서 처리할 항목을 고릅니다."
            active={value.issue === 'after'}
            onClick={() => pickIssue('after')}
          />
        </QuestionBlock>

        {value.issue === 'after' ? (
          <QuestionBlock
            step={2}
            label="세금계산서일을 선택하세요"
            hint={`기본값은 한 달 전부터 오늘까지입니다. 선택한 기간의 (세금)계산서만 리스트에 나타납니다 — 더미 데이터는 ${INVOICE_DATE_MIN} ~ ${INVOICE_DATE_MAX} 범위입니다.`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <DatePicker
                ariaLabel="세금계산서일 시작"
                value={value.invoiceFrom}
                onChange={(v) => set({ invoiceFrom: v })}
              />
              <span className="text-foreground-tertiary text-xs">~</span>
              <DatePicker
                ariaLabel="세금계산서일 종료"
                value={value.invoiceTo}
                onChange={(v) => set({ invoiceTo: v })}
              />
            </div>
            {/* 빠른 선택 — 달력을 열지 않고 흔히 쓰는 기간을 한 번에 넣는다.
                이번 달만 1일 기준이고 나머지는 오늘 기준 롤링(사용자 확정 2026-08-04). */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-foreground-tertiary text-[11px]">빠른 선택</span>
              {RANGE_PRESETS.map((p) => {
                const r = p.range();
                const active = value.invoiceFrom === r.from && value.invoiceTo === r.to;
                return (
                  <button
                    key={p.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => set({ invoiceFrom: r.from, invoiceTo: r.to })}
                    className={
                      active
                        ? 'border-accent bg-accent/10 text-accent rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] font-semibold'
                        : 'border-border text-foreground-secondary hover:border-accent hover:text-foreground rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] transition-colors'
                    }
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>
            {rangeInvalid ? (
              <p role="alert" className="text-danger text-[11px]">
                시작일이 종료일보다 늦을 수 없습니다.
              </p>
            ) : null}
          </QuestionBlock>
        ) : null}

        {showSplitQuestion ? (
          <QuestionBlock step={value.issue === 'after' ? 3 : 2} label="비용분할이 필요한가요?">
            <ChoiceOption
              label={SPLIT_LABEL.single}
              description="한 건으로 전액 처리합니다."
              active={value.split === 'single'}
              onClick={() => pickSplit('single')}
            />
            <ChoiceOption
              label={SPLIT_LABEL.split}
              description="예산단위·프로젝트·비용센터별로 금액을 나눠 담습니다."
              active={value.split === 'split'}
              onClick={() => pickSplit('split')}
            />
          </QuestionBlock>
        ) : null}

        {showTaxQuestion ? (
          <QuestionBlock
            step={value.issue === 'after' ? 4 : 2}
            label="과세 / 비과세 / 불공 중 어떤 것인가요?"
          >
            {taxOptions.map((t) => (
              <ChoiceOption
                key={t}
                label={TAX_LABEL[t]}
                active={value.tax === t}
                onClick={() => pickTax(t)}
              />
            ))}
          </QuestionBlock>
        ) : null}

        {showNondeductQuestion ? (
          <QuestionBlock step={5} label="불공 사유를 선택하세요">
            {(Object.keys(NONDEDUCT_LABEL) as NondeductReason[]).map((r) => (
              <ChoiceOption
                key={r}
                label={NONDEDUCT_LABEL[r]}
                active={value.nondeduct === r}
                onClick={() => set({ nondeduct: r })}
              />
            ))}
          </QuestionBlock>
        ) : null}
      </div>

      {/* 선택되는 증빙유형 — 요약까지 가지 않아도 지금 답이 어떤 코드가 되는지 바로 보인다
          (문서 시뮬레이터 docs/tax-invoice-flow.html 과 같은 규칙). */}
      {(() => {
        const ev = evidenceFor(value.issue, value.split, value.tax, value.nondeduct);
        // 아직 코드가 정해지지 않았으면 무엇을 더 골라야 하는지 알린다 — 자리를 비우지 않아야
        // 답을 채우는 동안 화면이 흔들리지 않는다.
        const pending = !value.issue ? '발행 여부' : !value.tax ? '과세여부' : '불공 사유';
        return (
          <div className="border-border-subtle bg-muted/40 flex shrink-0 flex-wrap items-baseline gap-x-2.5 gap-y-1 rounded-[var(--radius-md)] border px-3 py-2">
            <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
              증빙유형
            </span>
            {ev ? (
              <>
                <span className="text-accent font-mono text-lg leading-none font-bold tabular-nums">
                  {ev.code}
                </span>
                <span className="text-foreground text-[11px] font-semibold">{ev.label}</span>
                {ev.note ? (
                  <span className="text-foreground-tertiary w-full text-[11px]">{ev.note}</span>
                ) : null}
              </>
            ) : (
              <span className="text-foreground-tertiary text-[11px]">
                {pending}를 고르면 증빙유형이 정해집니다.
              </span>
            )}
          </div>
        );
      })()}

      <div className="flex shrink-0 items-center justify-end gap-2">
        <Button
          size="sm"
          onClick={onNext}
          disabled={!answersComplete(value)}
          title={answersComplete(value) ? undefined : '모든 질문에 답하면 다음으로 넘어갑니다.'}
        >
          {value.issue === 'after' ? '리스트 보기' : '입력항목 채우기'}
          <RiArrowRightLine size={14} aria-hidden />
        </Button>
      </div>
    </div>
  );
}
