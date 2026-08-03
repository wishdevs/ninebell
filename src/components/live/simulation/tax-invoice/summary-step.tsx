'use client';

import type { ReactNode } from 'react';
import { RiArrowLeftLine, RiRestartLine, RiShieldCheckLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Td, Th } from './ui';
import {
  ISSUE_LABEL,
  NONDEDUCT_LABEL,
  SPLIT_LABEL,
  TAX_LABEL,
  evidenceFor,
  formatWon,
  parseAmount,
  type EntryValues,
  type SplitRow,
} from './model';
import type { QuestionAnswers } from './questions-step';
import type { SelectionSummary } from './entry-step';

interface SummaryStepProps {
  answers: QuestionAnswers;
  entry: EntryValues;
  selection: SelectionSummary | null;
  splitRows: readonly SplitRow[];
  total: number;
  onBack: () => void;
  onReset: () => void;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-border-subtle flex gap-3 border-b py-1.5 last:border-b-0">
      <span className="text-foreground-tertiary w-28 shrink-0 text-[11px]">{label}</span>
      <span className="text-foreground-secondary min-w-0 flex-1 text-[11px]">{children}</span>
    </div>
  );
}

/**
 * 마지막 단계 — 시뮬레이션 결과 요약. 실제 저장은 하지 않는다.
 *
 * 백엔드 자동화 그래프가 붙기 전까지 이 화면이 "무엇을 ERP에 넣을 것인가"의 계약서 역할을 한다.
 */
export function SummaryStep({
  answers,
  entry,
  selection,
  splitRows,
  total,
  onBack,
  onReset,
}: SummaryStepProps) {
  const isSplit = answers.split === 'split';
  const supplyAmount = selection ? selection.supplyTotal : (parseAmount(entry.supplyAmount) ?? 0);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="border-info/30 bg-info/10 flex shrink-0 items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
        <RiShieldCheckLine size={16} aria-hidden className="text-info mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            시뮬레이션 — 실제 저장 없음
          </p>
          <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">
            아래 내용은 화면 시뮬레이션 결과입니다. 옴니솔에 전송하거나 저장하지 않았습니다. 자동화
            그래프가 연결되면 이 값이 결의서 입력에 그대로 쓰입니다.
          </p>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="flex flex-col gap-4">
          <section className="flex flex-col gap-1">
            <h3 className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
              1단계 — 질문
            </h3>
            <Row label="발행 여부">{answers.issue ? ISSUE_LABEL[answers.issue] : '—'}</Row>
            {answers.issue === 'after' ? (
              <Row label="세금계산서일">
                {answers.invoiceFrom} ~ {answers.invoiceTo}
              </Row>
            ) : null}
            <Row label="비용분할">{answers.split ? SPLIT_LABEL[answers.split] : '—'}</Row>
            <Row label="과세여부">
              {answers.tax ? TAX_LABEL[answers.tax] : '—'}
              {answers.nondeduct ? ` · ${NONDEDUCT_LABEL[answers.nondeduct]}` : ''}
            </Row>
            {/* 답 조합이 접혀 들어가는 최종 값 — ERP 에 실제로 넣는 코드라 굵게 세운다. */}
            {(() => {
              const ev = evidenceFor(answers.issue, answers.split, answers.tax, answers.nondeduct);
              if (!ev) return null;
              return (
                <>
                  <Row label="증빙유형">
                    <span className="font-mono font-semibold tabular-nums">{ev.code}</span>
                    <span className="text-foreground-secondary"> · {ev.label}</span>
                  </Row>
                  {ev.caution ? (
                    <p className="text-warning bg-warning/10 border-warning/25 rounded border px-2 py-1.5 text-[11px] leading-relaxed">
                      확인 필요 — {ev.caution}
                    </p>
                  ) : null}
                </>
              );
            })()}
          </section>

          {selection ? (
            <section className="flex flex-col gap-1">
              <h3 className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
                리스트 선택
              </h3>
              <Row label="선택 건수">{selection.count}건</Row>
              <Row label="거래처">{selection.partnerNames.join(', ')}</Row>
              <Row label="공급가액 합계">
                <span className="tabular-nums">{formatWon(selection.supplyTotal)}원</span>
              </Row>
              <Row label="세액 합계">
                <span className="tabular-nums">{formatWon(selection.taxTotal)}원</span>
              </Row>
            </section>
          ) : null}

          <section className="flex flex-col gap-1">
            <h3 className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
              입력항목
            </h3>
            {answers.issue === 'before' ? (
              <>
                <Row label="거래처">{entry.partner}</Row>
                <Row label="공급가액">
                  <span className="tabular-nums">{formatWon(supplyAmount)}원</span>
                </Row>
              </>
            ) : null}
            <Row label="예산단위">{entry.budgetUnit}</Row>
            <Row label="적요">{entry.note}</Row>
            <Row label="프로젝트">{entry.project}</Row>
            <Row label="회계일">{entry.acctDate}</Row>
            <Row label="자금과목">{entry.fundAccount}</Row>
            <Row label="결제조건">{entry.payTerm}</Row>
            <Row label="자금예정일">{entry.fundDueDate}</Row>
            {answers.tax === 'exempt' ? <Row label="사유구분">{entry.exemptReason}</Row> : null}
            {answers.tax === 'nondeduct' && answers.nondeduct ? (
              <Row label="불공 사유">{NONDEDUCT_LABEL[answers.nondeduct]}</Row>
            ) : null}
          </section>

          {isSplit ? (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
                비용분할 — {splitRows.length}행 · 총 {formatWon(total)}원
              </h3>
              <div className="border-border overflow-x-auto rounded-[var(--radius-md)] border">
                <table className="w-full min-w-[42rem] border-collapse text-[11px]">
                  <thead className="bg-muted/70 text-foreground-tertiary">
                    <tr>
                      <Th className="w-8 text-center">#</Th>
                      <Th>예산단위</Th>
                      <Th>적요</Th>
                      <Th>프로젝트</Th>
                      <Th>비용센터</Th>
                      <Th className="text-right">공급가액</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {splitRows.map((r, i) => {
                      const amt = parseAmount(r.amount) ?? 0;
                      return (
                        <tr key={r.id} className="border-border/50 border-t align-middle">
                          <Td className="text-foreground-tertiary text-center tabular-nums">
                            {i + 1}
                          </Td>
                          <Td className="text-foreground-secondary">{r.budgetUnit}</Td>
                          <Td className="text-foreground-secondary">{r.note}</Td>
                          <Td className="text-foreground-secondary">{r.project}</Td>
                          <Td className="text-foreground-secondary">{r.costCenter}</Td>
                          <Td
                            className={cn(
                              'text-right tabular-nums',
                              amt < 0 ? 'text-danger' : 'text-foreground-secondary',
                            )}
                          >
                            {formatWon(amt)}
                          </Td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center justify-end gap-2">
        <Button size="sm" variant="secondary" onClick={onBack}>
          <RiArrowLeftLine size={14} aria-hidden />
          이전
        </Button>
        <Button size="sm" onClick={onReset}>
          <RiRestartLine size={14} aria-hidden />
          처음부터 다시
        </Button>
      </div>
    </div>
  );
}
