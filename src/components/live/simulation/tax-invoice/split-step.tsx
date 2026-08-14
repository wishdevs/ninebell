'use client';

import { RiAddLine, RiArrowLeftLine, RiArrowRightLine, RiDeleteBinLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { AmountInput, CellInput, OptionSelect, SimStepHeader, StatTile } from './ui';
import {
  BUDGET_UNITS,
  COST_CENTERS,
  PROJECTS,
  amountFromPercent,
  formatWon,
  newSplitRow,
  parseAmount,
  parsePercent,
  percentFromAmount,
  type SplitMode,
  type SplitRow,
} from './model';

const MAX_SPLIT_ROWS = 20;

/** 행 금액(파싱 실패·빈값은 0으로 취급 — 잔액 계산이 항상 성립하게). */
function rowAmount(r: SplitRow): number {
  return parseAmount(r.amount) ?? 0;
}

/** 배분 합계. */
export function splitAllocated(rows: readonly SplitRow[]): number {
  return rows.reduce((s, r) => s + rowAmount(r), 0);
}

/** 남은 금액 — 0이 되어야 다음으로 넘어갈 수 있다. */
export function splitRemaining(rows: readonly SplitRow[], total: number): number {
  return total - splitAllocated(rows);
}

function isRowValid(r: SplitRow): boolean {
  const amt = parseAmount(r.amount);
  return (
    !!r.budgetUnit && !!r.note.trim() && !!r.project && !!r.costCenter && amt !== null && amt !== 0
  );
}

/** 모든 행이 채워졌고 남은 금액이 정확히 0인가. */
export function splitComplete(rows: readonly SplitRow[], total: number): boolean {
  return rows.length > 0 && rows.every(isRowValid) && splitRemaining(rows, total) === 0;
}

/**
 * 남은 금액의 성격 — 총액이 음수(취소분)면 '남았다/초과다'의 부호가 뒤집힌다.
 * 부호를 총액과 비교해 판단한다(예: 총 -214,000 · 배분 -150,000 → 남은 -64,000 = 아직 남음).
 */
function remainingKind(remaining: number, total: number): 'done' | 'left' | 'over' {
  if (remaining === 0) return 'done';
  if (total === 0) return 'over';
  return Math.sign(remaining) === Math.sign(total) ? 'left' : 'over';
}

const REMAINING_NOTE: Record<'done' | 'left' | 'over', string> = {
  done: '분할 완료',
  left: '아직 남았습니다',
  over: '총액을 초과했습니다',
};

const REMAINING_TONE: Record<'done' | 'left' | 'over', 'success' | 'warning' | 'danger'> = {
  done: 'success',
  left: 'warning',
  over: 'danger',
};

interface SplitStepProps {
  /** 분할 대상 총 공급가액(발행 전=입력값 / 발행 후=선택 행 합계). 음수(취소분)일 수 있다. */
  total: number;
  rows: readonly SplitRow[];
  onRowsChange: (rows: SplitRow[]) => void;
  mode: SplitMode;
  onModeChange: (mode: SplitMode) => void;
  onBack: () => void;
  onNext: () => void;
}

/**
 * 비용분할 단계 — 남은 금액이 0이 될 때까지 행을 나눈다.
 *
 * 금액이 항상 검증의 원천이다. 비율 모드에선 비율 → 금액을 원 단위로 반올림하는데, 그때 생기는
 * **잔돈은 마지막 행에 몰아준다**(사용자 확정 2026-08-04) — 60/40 처럼 나눌 때 1원 때문에
 * 확정이 막히지 않게 한다. 마지막 행 금액 = 총액 − 앞 행들의 합.
 */
export function SplitStep({
  total,
  rows,
  onRowsChange,
  mode,
  onModeChange,
  onBack,
  onNext,
}: SplitStepProps) {
  const allocated = splitAllocated(rows);
  const remaining = total - allocated;
  const complete = splitComplete(rows, total);
  // 총액 0(예: 원거래 + 취소분 동시 선택)이면 비율 환산이 성립하지 않는다.
  const percentDisabled = total === 0;

  const setRow = (id: string, patch: Partial<SplitRow>) =>
    onRowsChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  /** 금액 입력 → 비율 파생. */
  const setAmount = (r: SplitRow, raw: string) => {
    const amt = parseAmount(raw);
    const pct = amt === null ? null : percentFromAmount(total, amt);
    setRow(r.id, { amount: raw, percent: pct === null ? '' : String(pct) });
  };

  /**
   * 비율 입력 → 금액 파생(원 단위 반올림). 반올림 잔돈은 **마지막 행이 흡수**한다 —
   * 마지막 행 금액 = 총액 − 앞 행들의 합. 그래서 비율 합이 100%면 남은 금액이 정확히 0이 된다.
   * (마지막 행 자신을 입력 중일 때는 그 값을 존중하고 보정하지 않는다.)
   */
  const setPercent = (r: SplitRow, raw: string) => {
    const pct = parsePercent(raw);
    const nextRows = rows.map((row) =>
      row.id === r.id
        ? {
            ...row,
            percent: raw,
            amount: pct === null ? '' : String(amountFromPercent(total, pct)),
          }
        : row,
    );
    const lastId = nextRows[nextRows.length - 1]?.id;
    if (lastId && lastId !== r.id) {
      const headSum = nextRows.slice(0, -1).reduce((a, row) => a + rowAmount(row), 0);
      const tail = total - headSum;
      const tailPct = percentFromAmount(total, tail);
      nextRows[nextRows.length - 1] = {
        ...nextRows[nextRows.length - 1],
        amount: String(tail),
        percent: tailPct === null ? '' : String(tailPct),
      };
    }
    onRowsChange(nextRows);
  };

  /** 남은 금액 전액을 이 행에 더한다(반올림 잔돈 흡수). */
  const fillRemaining = (r: SplitRow) => {
    const next = rowAmount(r) + remaining;
    const pct = percentFromAmount(total, next);
    setRow(r.id, { amount: String(next), percent: pct === null ? '' : String(pct) });
  };

  const addRow = () => {
    if (rows.length >= MAX_SPLIT_ROWS) return;
    onRowsChange([...rows, newSplitRow()]);
  };

  const removeRow = (id: string) => {
    if (rows.length <= 1) return;
    onRowsChange(rows.filter((r) => r.id !== id));
  };

  const percentSum = rows.reduce((s, r) => s + (parsePercent(r.percent) ?? 0), 0);
  const kind = remainingKind(remaining, total);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <SimStepHeader
        title="비용분할 — 남은 금액이 0이 될 때까지 나누세요"
        prompt="행마다 예산단위·적요·프로젝트·공급가액·비용센터를 채웁니다. 금액으로 나눠도 되고 비율(%)로 나눠도 됩니다."
      />

      <div className="grid shrink-0 grid-cols-3 gap-2">
        <StatTile label="총 공급가액" value={`${formatWon(total)}원`} />
        <StatTile
          label="배분 금액"
          value={`${formatWon(allocated)}원`}
          sub={percentDisabled ? undefined : `${percentSum.toFixed(2).replace(/\.?0+$/, '')}%`}
        />
        <StatTile
          label="남은 금액"
          value={`${formatWon(remaining)}원`}
          tone={REMAINING_TONE[kind]}
          sub={REMAINING_NOTE[kind]}
        />
      </div>

      {/* 입력 방식 전환 — 어느 쪽을 고르든 금액이 최종 값이다(반대편은 파생 표시). */}
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <span className="text-foreground-secondary text-[11px] font-semibold tracking-wide">
          입력 방식
        </span>
        <div className="border-border-subtle bg-muted/40 inline-flex gap-1 rounded-[var(--radius-md)] border p-0.5">
          {(['amount', 'percent'] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              disabled={m === 'percent' && percentDisabled}
              onClick={() => onModeChange(m)}
              className={cn(
                // h-7(28px) — 예전 py-1 은 실측 23.99px 로 최소 타깃 24×24 를 아슬아슬하게 밑돌았다.
                'h-7 cursor-pointer rounded-[var(--radius-sm)] px-3 text-[length:var(--text-body-sm)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40',
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
            총 공급가액이 0원이라 비율 분할을 쓸 수 없습니다.
          </span>
        ) : null}
      </div>

      {/* 행 목록 — 2줄 행 구조(윗줄 코드 3종 / 아랫줄 적요·비율·공급가액·잔액·삭제).
          예전의 9열 한 줄 그리드(min-w 54rem)는 시뮬레이션 패널이 라이브 스테이지와
          화면을 나눠 쓰게 되면서(≈600px, 2026-08-04) 오른쪽이 잘려 나갔다. 가로 스크롤
          대신 폭에 맞게 접는다 — 열 제목 행도 없애고 위젯 placeholder 가 라벨을 겸한다. */}
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="flex flex-col gap-1">
          {rows.map((r, idx) => {
            const invalid = !isRowValid(r);
            return (
              <div
                key={r.id}
                className={cn(
                  'border-border/50 flex gap-2 border-b py-2 last:border-b-0',
                  invalid && 'bg-danger/[0.03]',
                )}
              >
                <span className="text-foreground-tertiary w-5 shrink-0 pt-2.5 text-center text-[11px] font-semibold tabular-nums">
                  {idx + 1}
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <div className="grid grid-cols-3 gap-1.5">
                    <OptionSelect
                      ariaLabel={`${idx + 1}행 예산단위`}
                      value={r.budgetUnit}
                      options={BUDGET_UNITS}
                      onChange={(v) => setRow(r.id, { budgetUnit: v })}
                      invalid={!r.budgetUnit}
                      placeholder="예산단위"
                    />
                    <OptionSelect
                      ariaLabel={`${idx + 1}행 프로젝트`}
                      value={r.project}
                      options={PROJECTS}
                      onChange={(v) => setRow(r.id, { project: v })}
                      invalid={!r.project}
                      placeholder="프로젝트"
                    />
                    <OptionSelect
                      ariaLabel={`${idx + 1}행 비용센터`}
                      value={r.costCenter}
                      options={COST_CENTERS}
                      onChange={(v) => setRow(r.id, { costCenter: v })}
                      invalid={!r.costCenter}
                      placeholder="비용센터"
                    />
                  </div>
                  <div className="flex items-center gap-1.5">
                    <div className="min-w-0 flex-1">
                      <CellInput
                        ariaLabel={`${idx + 1}행 적요`}
                        value={r.note}
                        onChange={(v) => setRow(r.id, { note: v })}
                        placeholder="적요"
                        invalid={!r.note.trim()}
                      />
                    </div>
                    <input
                      value={r.percent}
                      onChange={(e) => setPercent(r, e.target.value.replace(/[^\d.]/g, ''))}
                      disabled={mode !== 'percent' || percentDisabled}
                      inputMode="decimal"
                      aria-label={`${idx + 1}행 비율`}
                      placeholder="%"
                      className={cn(
                        'border-border bg-surface text-foreground placeholder:text-muted-foreground h-9 w-14 shrink-0 rounded-[var(--radius-sm)] border px-2 text-right text-[12px] tabular-nums outline-none',
                        'focus-visible:border-accent',
                        'disabled:bg-muted/40 disabled:opacity-60',
                      )}
                    />
                    <div className="w-28 shrink-0">
                      <AmountInput
                        ariaLabel={`${idx + 1}행 공급가액`}
                        value={r.amount}
                        onChange={(v) => setAmount(r, v)}
                        disabled={mode !== 'amount'}
                        invalid={parseAmount(r.amount) === null || parseAmount(r.amount) === 0}
                        placeholder="공급가액"
                        className={cn(
                          mode !== 'amount' && 'disabled:bg-muted/40 disabled:opacity-60',
                        )}
                      />
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="text-foreground-tertiary hover:text-accent h-8 shrink-0 px-1 text-[10px]"
                      disabled={remaining === 0}
                      title={
                        remaining === 0
                          ? '남은 금액이 없습니다'
                          : `남은 ${formatWon(remaining)}원을 이 행에 더합니다`
                      }
                      onClick={() => fillRemaining(r)}
                      aria-label={`${idx + 1}행에 남은 금액 채우기`}
                    >
                      잔액
                    </Button>
                    {rows.length > 1 ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="text-foreground-tertiary hover:text-danger h-8 shrink-0 px-1"
                        onClick={() => removeRow(r.id)}
                        aria-label={`${idx + 1}행 삭제`}
                      >
                        <RiDeleteBinLine size={14} aria-hidden />
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={addRow}
          disabled={rows.length >= MAX_SPLIT_ROWS}
        >
          <RiAddLine size={14} aria-hidden />행 추가
        </Button>
        <div className="flex items-center gap-2">
          <span className="text-foreground-secondary text-[11px]">
            남은 금액{' '}
            <span
              className={cn(
                'font-semibold tabular-nums',
                kind === 'done' ? 'text-success' : kind === 'left' ? 'text-warning' : 'text-danger',
              )}
            >
              {formatWon(remaining)}
            </span>
            원
          </span>
          <Button size="sm" variant="secondary" onClick={onBack}>
            <RiArrowLeftLine size={14} aria-hidden />
            이전
          </Button>
          <Button
            size="sm"
            onClick={onNext}
            disabled={!complete}
            title={
              complete
                ? undefined
                : '모든 행을 채우고 남은 금액이 0원이 되어야 다음으로 넘어갑니다.'
            }
          >
            분할 확정
            <RiArrowRightLine size={14} aria-hidden />
          </Button>
        </div>
      </div>
    </div>
  );
}
