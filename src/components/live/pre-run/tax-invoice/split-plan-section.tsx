'use client';

import type { ReactNode } from 'react';
import { RiAddLine, RiDeleteBinLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { CatalogCombobox, type ComboOption } from '../catalog-combobox';
import { AmountInput, StatTile } from './ui';
import {
  MAX_SPLIT_ROWS,
  MIN_SPLIT_ROWS,
  amountFromPercent,
  formatWon,
  newSplitRow,
  parseAmount,
  parsePercent,
  percentFromAmount,
  type SplitMode,
  type SplitRow,
} from './model';

/**
 * 비용분할 계획 섹션 — 시뮬레이션 분할 계산기 승격판.
 *
 * 실행 전에는 실제 총 공급가액을 모른다(발행 후 행 선택이 라이브 개입에서 일어난다) —
 * 그래서 **마지막 행은 금액을 입력하지 않고 차액반영**(ERP 분할 팝업의 차액반영 버튼)으로
 * 잔액을 흡수한다(계약: 마지막 행 amount=null). 앞 행들만 금액을 확정한다.
 *
 * 비율(%) 입력은 총액을 알아야 환산이 성립하므로, 선택 입력인 **참고 총액**(제출되지 않는
 * 계산 보조값)을 넣었을 때만 켜진다 — 시뮬레이션의 "총액 0이면 비율 불가" 규칙의 승격판.
 */

/** 행 금액(파싱 실패·빈값은 0으로 취급 — 배분 합계 계산이 항상 성립하게). */
function rowAmount(r: SplitRow): number {
  return parseAmount(r.amount) ?? 0;
}

/** 마지막 행(차액반영)을 제외한 확정 금액 합계. */
export function splitFixedSum(rows: readonly SplitRow[]): number {
  return rows.slice(0, -1).reduce((s, r) => s + rowAmount(r), 0);
}

/** 공통 필드(적요·프로젝트·비용센터)가 채워졌는지 — 마지막 행 포함 전 행 공통. */
function rowCommonValid(r: SplitRow): boolean {
  return !!r.note.trim() && !!r.projectCode && !!r.costCenter.trim();
}

/** 행이 유효한지 — 마지막 행은 차액반영이라 금액을 요구하지 않는다. */
function isRowValid(r: SplitRow, isLast: boolean): boolean {
  if (!rowCommonValid(r)) return false;
  if (isLast) return true;
  const amt = parseAmount(r.amount);
  return amt !== null && amt !== 0;
}

/** 분할 계획이 제출 가능한가 — 2~20행 + 전 행 유효. */
export function splitPlanComplete(rows: readonly SplitRow[]): boolean {
  return (
    rows.length >= MIN_SPLIT_ROWS &&
    rows.length <= MAX_SPLIT_ROWS &&
    rows.every((r, i) => isRowValid(r, i === rows.length - 1))
  );
}

// md 이상 표 열 템플릿 — #, 적요, 프로젝트, 비용센터, 비율, 금액, 삭제. md 미만은 행당 카드.
const ROW_GRID =
  'md:grid md:grid-cols-[1.75rem_minmax(8rem,1.2fr)_minmax(8.5rem,1.2fr)_minmax(7rem,1fr)_3.5rem_7.5rem_2.5rem] md:items-start md:gap-x-2 md:gap-y-1';

interface SplitPlanSectionProps {
  rows: readonly SplitRow[];
  onRowsChange: (rows: SplitRow[]) => void;
  mode: SplitMode;
  onModeChange: (mode: SplitMode) => void;
  /** 참고 총액(원 단위 정수 문자열) — 제출되지 않는 계산 보조값. 비율 모드·잔액 미리보기용. */
  refTotal: string;
  onRefTotalChange: (v: string) => void;
  projectFavs: ComboOption[];
  searchProjects: (q: string) => Promise<ComboOption[]>;
  disabled?: boolean;
}

export function SplitPlanSection({
  rows,
  onRowsChange,
  mode,
  onModeChange,
  refTotal,
  onRefTotalChange,
  projectFavs,
  searchProjects,
  disabled,
}: SplitPlanSectionProps) {
  const total = parseAmount(refTotal) ?? 0;
  const percentDisabled = total === 0;
  const fixedSum = splitFixedSum(rows);
  /** 참고 총액 기준 마지막 행이 흡수할 잔액 미리보기. */
  const absorbed = total - fixedSum;

  const setRow = (id: string, patch: Partial<SplitRow>) =>
    onRowsChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  /** 금액 입력 → 비율 파생(참고 총액이 있을 때만). */
  const setAmount = (r: SplitRow, raw: string) => {
    const amt = parseAmount(raw);
    const pct = amt === null ? null : percentFromAmount(total, amt);
    setRow(r.id, { amount: raw, percent: pct === null ? '' : String(pct) });
  };

  /** 비율 입력 → 금액 파생(원 단위 반올림). 잔돈은 어차피 마지막 행(차액반영)이 흡수한다. */
  const setPercent = (r: SplitRow, raw: string) => {
    const pct = parsePercent(raw);
    setRow(r.id, {
      percent: raw,
      amount: pct === null ? '' : String(amountFromPercent(total, pct)),
    });
  };

  /**
   * 참고 총액 변경 → 기존 행 재파생. 총액이 바뀌면 금액↔비율 환산이 통째로 달라지므로
   * 입력 방식에서 사용자가 확정한 쪽을 기준으로 반대쪽을 다시 계산한다(안 하면 % 열이 거짓이 된다).
   */
  const changeRefTotal = (raw: string) => {
    onRefTotalChange(raw);
    const next = parseAmount(raw) ?? 0;
    onRowsChange(
      rows.map((r) => {
        if (mode === 'percent') {
          const pct = parsePercent(r.percent);
          return { ...r, amount: pct === null ? '' : String(amountFromPercent(next, pct)) };
        }
        const amt = parseAmount(r.amount);
        const pct = amt === null ? null : percentFromAmount(next, amt);
        return { ...r, percent: pct === null ? '' : String(pct) };
      }),
    );
  };

  const addRow = () => {
    if (rows.length >= MAX_SPLIT_ROWS) return;
    onRowsChange([...rows, newSplitRow()]);
  };

  const removeRow = (id: string) => {
    if (rows.length <= MIN_SPLIT_ROWS) return;
    onRowsChange(rows.filter((r) => r.id !== id));
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="text-foreground text-[length:var(--text-body-lg)] leading-snug font-semibold">
          비용분할 계획
        </p>
        <p className="text-foreground-secondary mt-0.5 text-[length:var(--text-body-sm)] leading-relaxed">
          행마다 적요·프로젝트·비용센터를 채우고 앞 행들의 공급가액을 확정합니다.{' '}
          <b className="text-foreground">마지막 행은 차액반영</b> — 실제 총액에서 앞 행들을 뺀
          잔액을 자동으로 흡수합니다(총액은 실행 중 선택한 계산서 합계로 정해집니다).
        </p>
      </div>

      {/* 참고 총액 — 제출 안 되는 계산 보조값. 넣으면 비율(%) 입력과 잔액 미리보기가 켜진다. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-foreground-secondary text-[11px] font-semibold tracking-wide">
          참고 총액
        </span>
        <div className="w-36">
          <AmountInput
            ariaLabel="참고 총액(계산 보조)"
            value={refTotal}
            onChange={changeRefTotal}
            disabled={disabled}
            placeholder="선택 입력"
          />
        </div>
        <span aria-hidden className="bg-border mx-1 h-5 w-px" />
        <span className="text-foreground-secondary text-[11px] font-semibold tracking-wide">
          입력 방식
        </span>
        <div className="border-border-subtle bg-muted/40 inline-flex gap-1 rounded-[var(--radius-md)] border p-0.5">
          {(['amount', 'percent'] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              disabled={disabled || (m === 'percent' && percentDisabled)}
              onClick={() => onModeChange(m)}
              className={cn(
                'h-7 cursor-pointer rounded-[var(--radius-sm)] px-3 text-[length:var(--text-body-sm)] font-medium transition-colors outline-none disabled:cursor-not-allowed disabled:opacity-40 pointer-coarse:h-11',
                mode === m
                  ? 'bg-accent text-accent-foreground'
                  : 'text-foreground-secondary hover:bg-muted',
              )}
            >
              {m === 'amount' ? '금액으로' : '비율(%)로'}
            </button>
          ))}
        </div>
        {percentDisabled ? (
          <span className="text-foreground-tertiary text-[11px]">
            비율(%) 입력은 참고 총액을 넣어야 쓸 수 있습니다.
          </span>
        ) : null}
      </div>

      {total !== 0 ? (
        <div className="grid grid-cols-3 gap-2">
          <StatTile label="참고 총액" value={`${formatWon(total)}원`} />
          <StatTile label="확정 금액(앞 행)" value={`${formatWon(fixedSum)}원`} />
          <StatTile
            label="차액반영 예상(마지막 행)"
            value={`${formatWon(absorbed)}원`}
            tone={absorbed === 0 ? 'warning' : 'neutral'}
            sub={
              absorbed === 0 ? '마지막 행 금액이 0원이 됩니다' : '실제 총액 기준으로 재계산됩니다'
            }
          />
        </div>
      ) : null}

      {/* md 이상 표: 폼 열이 그리드 최소폭(42rem)보다 좁아지면 가로 스크롤 — min-w 를 풀면 고정폭
          열들이 카드 밖으로 삐져나간다(스크롤 없이 clip 되던 버그). md 미만은 카드 스택이라 min-w 없음. */}
      <div className="overflow-x-auto">
        <div className="flex flex-col gap-3 md:min-w-[42rem] md:gap-1">
          {/* 표 헤더(md 이상 표 전용) — md 미만 카드는 셀마다 인라인 라벨을 붙인다 */}
          <div
            className={cn(
              ROW_GRID,
              'border-border/60 text-foreground-tertiary hidden border-b px-1 pb-1.5 text-[10px] font-semibold tracking-wider uppercase md:grid',
            )}
          >
            <span aria-hidden />
            <span>적요</span>
            <span>프로젝트</span>
            <span>비용센터</span>
            <span className="text-right">비율</span>
            <span className="text-right">공급가액</span>
            <span aria-hidden />
          </div>

          {rows.map((r, idx) => {
            const isLast = idx === rows.length - 1;
            const invalid = !isRowValid(r, isLast);
            return (
              <div
                key={r.id}
                className={cn(
                  ROW_GRID,
                  'max-md:border-border/60 max-md:relative max-md:flex max-md:flex-col max-md:gap-2.5 max-md:rounded-[var(--radius-md)] max-md:border max-md:p-3',
                  'md:border-border/50 md:border-b md:py-1.5 md:last:border-b-0',
                  invalid && 'md:bg-danger/[0.03]',
                )}
              >
                {/* 행 번호 — md 미만 카드 헤더(차액반영 배지 동반), md 이상은 그리드 첫 셀 */}
                <div className="flex items-center gap-2 pr-10 md:contents">
                  <span className="text-foreground-tertiary text-center text-xs font-semibold tabular-nums md:pt-2.5">
                    {idx + 1}
                    <span className="md:hidden">행</span>
                  </span>
                  {isLast ? (
                    <span className="bg-accent/10 text-accent rounded-full px-2 py-0.5 text-[11px] font-semibold md:hidden">
                      차액반영 — 잔액 흡수
                    </span>
                  ) : null}
                </div>

                {/* 적요 */}
                <div className="min-w-0 max-md:space-y-1">
                  <FieldLabel>적요</FieldLabel>
                  <Input
                    aria-label={`${idx + 1}행 적요`}
                    value={r.note}
                    maxLength={200}
                    disabled={disabled}
                    placeholder="적요"
                    onChange={(e) => setRow(r.id, { note: e.target.value })}
                  />
                </div>

                {/* 프로젝트 */}
                <div className="min-w-0 max-md:space-y-1">
                  <FieldLabel>프로젝트</FieldLabel>
                  <CatalogCombobox
                    value={{ code: r.projectCode, name: r.projectName }}
                    placeholder="프로젝트 선택"
                    favorites={projectFavs}
                    disabled={disabled}
                    search={searchProjects}
                    onSelect={(o) => setRow(r.id, { projectCode: o.code, projectName: o.name })}
                    onClear={() => setRow(r.id, { projectCode: '', projectName: '' })}
                  />
                </div>

                {/* 비용센터 */}
                <div className="min-w-0 max-md:space-y-1">
                  <FieldLabel>비용센터</FieldLabel>
                  <Input
                    aria-label={`${idx + 1}행 비용센터`}
                    value={r.costCenter}
                    disabled={disabled}
                    placeholder="예: 경영지원팀"
                    onChange={(e) => setRow(r.id, { costCenter: e.target.value })}
                  />
                </div>

                {/* 비율 — 앞 행 + 비율 모드 + 참고 총액이 있을 때만 입력 가능 */}
                <div className="min-w-0 max-md:space-y-1">
                  <FieldLabel>비율(%)</FieldLabel>
                  {isLast ? (
                    <span aria-hidden className="max-md:hidden" />
                  ) : (
                    <input
                      value={r.percent}
                      onChange={(e) => setPercent(r, e.target.value.replace(/[^\d.]/g, ''))}
                      disabled={disabled || mode !== 'percent' || percentDisabled}
                      inputMode="decimal"
                      aria-label={`${idx + 1}행 비율`}
                      placeholder="%"
                      className={cn(
                        'border-border bg-surface text-foreground placeholder:text-muted-foreground h-10 w-full min-w-0 rounded-[var(--radius-sm)] border px-2 text-right text-sm tabular-nums outline-none',
                        'focus-visible:border-accent',
                        'disabled:bg-muted/40 disabled:opacity-60',
                      )}
                    />
                  )}
                </div>

                {/* 공급가액 — 마지막 행은 차액반영(제출 시 amount=null) */}
                <div className="min-w-0 max-md:space-y-1">
                  <FieldLabel>공급가액</FieldLabel>
                  {isLast ? (
                    <div className="border-border-subtle bg-muted/40 text-foreground-secondary flex h-10 items-center justify-end rounded-[var(--radius-sm)] border px-2.5 text-sm tabular-nums">
                      {total !== 0 ? formatWon(absorbed) : '차액반영'}
                    </div>
                  ) : (
                    <AmountInput
                      ariaLabel={`${idx + 1}행 공급가액`}
                      value={r.amount}
                      onChange={(v) => setAmount(r, v)}
                      disabled={disabled || mode !== 'amount'}
                      invalid={
                        !!r.amount &&
                        (parseAmount(r.amount) === null || parseAmount(r.amount) === 0)
                      }
                      placeholder="공급가액"
                      className={cn(
                        mode !== 'amount' && 'disabled:bg-muted/40 disabled:opacity-60',
                      )}
                    />
                  )}
                </div>

                {/* 삭제 — md 미만 카드에선 우상단 44px 터치 타겟 */}
                {rows.length > MIN_SPLIT_ROWS ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="text-foreground-tertiary hover:text-danger max-md:absolute max-md:top-1.5 max-md:right-1.5 max-md:h-11 max-md:w-11 md:mt-0.5"
                    onClick={() => removeRow(r.id)}
                    disabled={disabled}
                    aria-label={`${idx + 1}행 삭제`}
                  >
                    <RiDeleteBinLine size={15} aria-hidden />
                  </Button>
                ) : (
                  <span aria-hidden className="max-md:hidden" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="max-md:h-11"
          onClick={addRow}
          disabled={disabled || rows.length >= MAX_SPLIT_ROWS}
        >
          <RiAddLine size={14} aria-hidden />행 추가
        </Button>
        <span className="text-foreground-tertiary text-[11px]">
          {MIN_SPLIT_ROWS}~{MAX_SPLIT_ROWS}행 · 마지막 행이 잔액을 흡수합니다
        </span>
      </div>
    </div>
  );
}

// ── 인라인 필드 라벨 — md 미만 카드에서만 표시(md 이상은 표 헤더가 라벨) ────────
function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-foreground-tertiary block text-[11px] font-medium md:hidden">
      {children}
    </span>
  );
}
