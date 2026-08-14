'use client';

import { RiArrowLeftLine, RiArrowRightLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { AmountInput, OptionSelect, SimStepHeader } from './ui';
import {
  BUDGET_UNITS,
  EXEMPT_REASONS,
  FUND_ACCOUNTS,
  NONDEDUCT_LABEL,
  PARTNER_NAMES,
  PAY_TERMS,
  PROJECTS,
  TAX_LABEL,
  formatWon,
  parseAmount,
  type EntryValues,
  type IssueState,
  type NondeductReason,
  type TaxKind,
} from './model';

/** 발행 후 경로에서 리스트 선택으로 확정된 값(읽기 전용 표시 + 회계일/총액의 출처). */
export interface SelectionSummary {
  count: number;
  partnerNames: readonly string[];
  supplyTotal: number;
  taxTotal: number;
  /** 선택 행의 (세금)계산서일 중 마지막 날짜 — 회계일 기본값. */
  lastInvoiceDate: string;
}

interface EntryStepProps {
  issue: IssueState;
  tax: TaxKind;
  nondeduct: NondeductReason | null;
  /** 발행 후일 때만 존재. */
  selection: SelectionSummary | null;
  value: EntryValues;
  onChange: (next: EntryValues) => void;
  onBack: () => void;
  onNext: () => void;
  /** 다음 단계가 분할이면 버튼 문구를 바꾼다. */
  nextLabel: string;
}

/** 필수 입력이 모두 채워졌는지. 발행 전은 거래처·공급가액이 추가 필수. */
export function entryComplete(v: EntryValues, issue: IssueState, tax: TaxKind): boolean {
  const commonOk =
    !!v.budgetUnit &&
    !!v.note.trim() &&
    !!v.project &&
    !!v.acctDate &&
    !!v.fundAccount &&
    !!v.payTerm &&
    !!v.fundDueDate;
  if (!commonOk) return false;
  if (tax === 'exempt' && !v.exemptReason) return false;
  if (issue === 'before') {
    const amount = parseAmount(v.supplyAmount);
    return !!v.partner && amount !== null && amount !== 0;
  }
  return true;
}

/**
 * 입력항목 단계 — 발행 전이면 거래처·공급가액을 직접 받고, 발행 후면 리스트 선택분이 그 자리를 대신한다.
 *
 * 회계일은 (세금)계산서일과 동일해야 하므로 발행 후엔 선택 행의 마지막 계산서일로 미리 채운다.
 * 선택 행의 날짜가 여러 개일 수 있어 잠그지 않고 수정 가능하게 두되, 출처를 힌트로 밝힌다.
 */
export function EntryStep({
  issue,
  tax,
  nondeduct,
  selection,
  value,
  onChange,
  onBack,
  onNext,
  nextLabel,
}: EntryStepProps) {
  const set = (patch: Partial<EntryValues>) => onChange({ ...value, ...patch });
  const complete = entryComplete(value, issue, tax);
  const supplyAmount = parseAmount(value.supplyAmount);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <SimStepHeader
        title="입력항목 채우기"
        prompt={
          issue === 'before'
            ? '발행 전 건이라 거래처·공급가액을 직접 입력합니다. 나머지는 공통 항목입니다.'
            : '리스트에서 고른 항목의 공통 항목을 채웁니다. 거래처·공급가액은 선택한 행에서 옵니다.'
        }
      />

      {selection ? (
        <div className="border-border-subtle bg-muted/40 flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-[var(--radius-md)] border px-3 py-2 text-[11px]">
          <span className="text-foreground-tertiary">
            선택{' '}
            <span className="text-foreground-secondary font-semibold tabular-nums">
              {selection.count}건
            </span>
          </span>
          <span className="text-foreground-tertiary min-w-0">
            거래처{' '}
            <span className="text-foreground-secondary font-semibold">
              {selection.partnerNames.join(', ')}
            </span>
          </span>
          <span className="text-foreground-tertiary">
            공급가액{' '}
            <span className="text-foreground font-semibold tabular-nums">
              {formatWon(selection.supplyTotal)}
            </span>
            원
          </span>
          <span className="text-foreground-tertiary">
            세액{' '}
            <span className="text-foreground-secondary font-semibold tabular-nums">
              {formatWon(selection.taxTotal)}
            </span>
            원
          </span>
          <span className="bg-accent/10 text-accent rounded-full px-2 py-0.5 font-semibold">
            {TAX_LABEL[tax]}
            {tax === 'nondeduct' && nondeduct ? ` · ${NONDEDUCT_LABEL[nondeduct]}` : ''}
          </span>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid gap-4 sm:grid-cols-2">
          {issue === 'before' ? (
            <>
              <FormField id="tax-invoice-partner" label="거래처" required>
                <OptionSelect
                  size="form"
                  ariaLabel="거래처"
                  value={value.partner}
                  options={PARTNER_NAMES}
                  onChange={(v) => set({ partner: v })}
                  placeholder="거래처 선택"
                />
              </FormField>

              <FormField
                id="tax-invoice-supply"
                label="공급가액"
                required
                hint={
                  supplyAmount !== null && supplyAmount !== 0
                    ? `${formatWon(supplyAmount)}원`
                    : '원 단위 정수(취소분은 음수)'
                }
              >
                <AmountInput
                  ariaLabel="공급가액"
                  value={value.supplyAmount}
                  onChange={(v) => set({ supplyAmount: v })}
                  placeholder="예: 400000"
                  className="h-10 text-sm"
                  invalid={!!value.supplyAmount && (supplyAmount === null || supplyAmount === 0)}
                />
              </FormField>
            </>
          ) : null}

          <FormField id="tax-invoice-budget" label="예산단위" required>
            <OptionSelect
              size="form"
              ariaLabel="예산단위"
              value={value.budgetUnit}
              options={BUDGET_UNITS}
              onChange={(v) => set({ budgetUnit: v })}
              placeholder="예산단위 선택"
            />
          </FormField>

          <FormField id="tax-invoice-note" label="적요" required>
            <Input
              id="tax-invoice-note"
              value={value.note}
              maxLength={200}
              placeholder="예: 7월 노무자문 수수료"
              onChange={(e) => set({ note: e.target.value })}
            />
          </FormField>

          <FormField
            id="tax-invoice-project"
            label="프로젝트"
            required
            hint="500 / 800 또는 개별 프로젝트를 고릅니다."
          >
            <OptionSelect
              size="form"
              ariaLabel="프로젝트"
              value={value.project}
              options={PROJECTS}
              onChange={(v) => set({ project: v })}
              placeholder="프로젝트 선택"
            />
          </FormField>

          <FormField
            id="tax-invoice-acct-date"
            label="회계일"
            required
            hint={
              selection
                ? '(세금)계산서일과 동일 — 선택 행의 마지막 계산서일로 자동 지정했습니다.'
                : '(세금)계산서일과 동일하게 지정하세요.'
            }
          >
            <DatePicker
              ariaLabel="회계일"
              value={value.acctDate}
              onChange={(v) => set({ acctDate: v })}
            />
          </FormField>

          <FormField id="tax-invoice-fund-account" label="자금과목" required>
            <OptionSelect
              size="form"
              ariaLabel="자금과목"
              value={value.fundAccount}
              options={FUND_ACCOUNTS}
              onChange={(v) => set({ fundAccount: v })}
            />
          </FormField>

          <FormField id="tax-invoice-pay-term" label="결제조건" required>
            <OptionSelect
              size="form"
              ariaLabel="결제조건"
              value={value.payTerm}
              options={PAY_TERMS}
              onChange={(v) => set({ payTerm: v })}
            />
          </FormField>

          <FormField
            id="tax-invoice-fund-due"
            label="자금예정일"
            required
            hint="커스텀 — 직접 지정합니다."
          >
            <DatePicker
              ariaLabel="자금예정일"
              value={value.fundDueDate}
              onChange={(v) => set({ fundDueDate: v })}
            />
          </FormField>

          {/* 과세여부에 따른 추가 항목 — 과세는 추가 없음. */}
          {tax === 'exempt' ? (
            <FormField id="tax-invoice-exempt-reason" label="사유구분" required>
              <OptionSelect
                size="form"
                ariaLabel="사유구분"
                value={value.exemptReason}
                options={EXEMPT_REASONS}
                onChange={(v) => set({ exemptReason: v })}
              />
            </FormField>
          ) : null}

          {tax === 'nondeduct' && nondeduct ? (
            <FormField
              id="tax-invoice-nondeduct"
              label="불공 사유"
              hint="1단계에서 고른 사유가 그대로 반영됩니다."
            >
              <p className="border-border bg-muted/40 text-foreground-secondary flex h-10 items-center rounded-sm border px-3 text-sm">
                {NONDEDUCT_LABEL[nondeduct]}
              </p>
            </FormField>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center justify-end gap-2">
        <Button size="sm" variant="secondary" onClick={onBack}>
          <RiArrowLeftLine size={14} aria-hidden />
          이전
        </Button>
        <Button
          size="sm"
          onClick={onNext}
          disabled={!complete}
          title={complete ? undefined : '필수 항목을 모두 채우면 다음으로 넘어갑니다.'}
        >
          {nextLabel}
          <RiArrowRightLine size={14} aria-hidden />
        </Button>
      </div>
    </div>
  );
}
