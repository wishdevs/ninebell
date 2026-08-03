'use client';

import { useMemo, useState } from 'react';
import { RiFlaskLine } from '@remixicon/react';
import { SectionCard } from '@/components/ui/section-card';
import { cn } from '@/lib/utils';
import type { SimulationPanelProps } from '../index';
import {
  INVOICE_ROWS,
  emptyEntry,
  newSplitRow,
  parseAmount,
  type EntryValues,
  type SplitMode,
  type SplitRow,
} from './model';
import { QuestionsStep, emptyAnswers, type QuestionAnswers } from './questions-step';
import { InvoiceListStep } from './invoice-list-step';
import { EntryStep, type SelectionSummary } from './entry-step';
import { SplitStep } from './split-step';
import { SummaryStep } from './summary-step';

type Stage = 'questions' | 'list' | 'entry' | 'split' | 'summary';

/**
 * 세금계산서 결의서 — 프론트 더미 시뮬레이션(백엔드 자동화 그래프 미연결).
 *
 * 흐름: 1단계 질문(점진적 노출) → (발행 후면) 리스트에서 행 선택 → 입력항목 → (분할이면) 비용분할
 *       → 요약. 어떤 단계에서도 서버로 나가지 않는다 — 실행 API(`POST /runs/collect`)를 타지 않고
 *       프론트 상태만으로 끝까지 흐른다. 마지막 요약에 '실제 저장 없음'을 명시한다.
 */
export function TaxInvoiceSimulation({ agent }: SimulationPanelProps) {
  const [stage, setStage] = useState<Stage>('questions');
  const [answers, setAnswers] = useState<QuestionAnswers>(emptyAnswers);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set<number>());
  const [entry, setEntry] = useState<EntryValues>(emptyEntry);
  const [splitRows, setSplitRows] = useState<readonly SplitRow[]>([]);
  const [splitMode, setSplitMode] = useState<SplitMode>('amount');

  const isAfter = answers.issue === 'after';
  const isSplit = answers.split === 'split';

  // 발행 후 경로에서 선택된 행 — 기간 밖 행이 남아 있지 않도록 기간 필터를 함께 적용한다.
  const selectedRows = useMemo(
    () =>
      INVOICE_ROWS.filter(
        (r) =>
          selected.has(r.no) &&
          (!answers.invoiceFrom || r.invoiceDate >= answers.invoiceFrom) &&
          (!answers.invoiceTo || r.invoiceDate <= answers.invoiceTo),
      ),
    [selected, answers.invoiceFrom, answers.invoiceTo],
  );

  const selection = useMemo<SelectionSummary | null>(() => {
    if (!isAfter || selectedRows.length === 0) return null;
    return {
      count: selectedRows.length,
      partnerNames: [...new Set(selectedRows.map((r) => r.partnerName))],
      supplyTotal: selectedRows.reduce((s, r) => s + r.supplyAmount, 0),
      taxTotal: selectedRows.reduce((s, r) => s + r.taxAmount, 0),
      // 회계일 기본값 — 선택 행의 (세금)계산서일 중 마지막 날짜.
      lastInvoiceDate: selectedRows.map((r) => r.invoiceDate).sort()[selectedRows.length - 1],
    };
  }, [isAfter, selectedRows]);

  /** 분할 대상 총액 — 발행 후는 선택 행 합계, 발행 전은 입력한 공급가액. */
  const splitTotal = selection ? selection.supplyTotal : (parseAmount(entry.supplyAmount) ?? 0);

  const toggle = (no: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(no)) next.delete(no);
      else next.add(no);
      return next;
    });

  const toggleAll = (nos: readonly number[], on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      for (const no of nos) {
        if (on) next.add(no);
        else next.delete(no);
      }
      return next;
    });

  const reset = () => {
    setStage('questions');
    setAnswers(emptyAnswers());
    setSelected(new Set<number>());
    setEntry(emptyEntry());
    setSplitRows([]);
    setSplitMode('amount');
  };

  /** 리스트 → 입력항목. 회계일은 (세금)계산서일과 동일해야 하므로 선택 결과로 덮어쓴다. */
  const goEntryFromList = () => {
    if (selection) setEntry((e) => ({ ...e, acctDate: selection.lastInvoiceDate }));
    setStage('entry');
  };

  /** 입력항목 → 분할(또는 요약). 분할 첫 진입이면 2행으로 시작한다. */
  const goAfterEntry = () => {
    if (!isSplit) {
      setStage('summary');
      return;
    }
    if (splitRows.length === 0) setSplitRows([newSplitRow(), newSplitRow()]);
    setStage('split');
  };

  const stages: { key: Stage; label: string }[] = [
    { key: 'questions', label: '질문' },
    ...(isAfter ? [{ key: 'list' as const, label: '리스트' }] : []),
    { key: 'entry', label: '입력항목' },
    ...(isSplit ? [{ key: 'split' as const, label: '비용분할' }] : []),
    { key: 'summary', label: '요약' },
  ];

  return (
    <SectionCard
      caption="화면 시뮬레이션"
      title={`${agent.name} — 결의서 입력 흐름`}
      description="백엔드 자동화는 아직 연결되지 않았습니다. 실제 옴니솔 조회·저장 없이 화면 흐름만 확인하는 더미 시뮬레이션입니다."
      density="comfortable"
      className="lg:h-full lg:min-h-0 lg:overflow-hidden"
      action={
        <span className="border-warning/30 bg-warning/10 text-warning inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase">
          <RiFlaskLine size={11} aria-hidden />
          시뮬레이션
        </span>
      }
    >
      {/* 단계 표시 — 발행 전/후·분할 여부에 따라 단계 수 자체가 달라진다. */}
      <ol className="text-foreground-tertiary flex shrink-0 flex-wrap items-center gap-1.5 text-[11px]">
        {stages.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1.5">
            {i > 0 ? <span aria-hidden>›</span> : null}
            <span
              aria-current={stage === s.key ? 'step' : undefined}
              className={cn(
                'rounded-full px-2 py-0.5',
                stage === s.key
                  ? 'bg-accent/10 text-accent font-semibold'
                  : 'text-foreground-tertiary',
              )}
            >
              {s.label}
            </span>
          </li>
        ))}
      </ol>

      <div className="min-h-0 flex-1">
        {stage === 'questions' ? (
          <QuestionsStep
            value={answers}
            onChange={setAnswers}
            onNext={() => setStage(isAfter ? 'list' : 'entry')}
          />
        ) : null}

        {stage === 'list' ? (
          <InvoiceListStep
            from={answers.invoiceFrom}
            to={answers.invoiceTo}
            selected={selected}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onBack={() => setStage('questions')}
            onNext={goEntryFromList}
          />
        ) : null}

        {stage === 'entry' && answers.issue && answers.tax ? (
          <EntryStep
            issue={answers.issue}
            tax={answers.tax}
            nondeduct={answers.nondeduct}
            selection={selection}
            value={entry}
            onChange={setEntry}
            onBack={() => setStage(isAfter ? 'list' : 'questions')}
            onNext={goAfterEntry}
            nextLabel={isSplit ? '비용분할 입력' : '요약 보기'}
          />
        ) : null}

        {stage === 'split' ? (
          <SplitStep
            total={splitTotal}
            rows={splitRows}
            onRowsChange={setSplitRows}
            mode={splitMode}
            onModeChange={setSplitMode}
            onBack={() => setStage('entry')}
            onNext={() => setStage('summary')}
          />
        ) : null}

        {stage === 'summary' ? (
          <SummaryStep
            answers={answers}
            entry={entry}
            selection={selection}
            splitRows={splitRows}
            total={splitTotal}
            onBack={() => setStage(isSplit ? 'split' : 'entry')}
            onReset={reset}
          />
        ) : null}
      </div>
    </SectionCard>
  );
}
