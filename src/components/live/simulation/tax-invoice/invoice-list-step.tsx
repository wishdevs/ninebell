'use client';

import { useMemo, useRef, useEffect } from 'react';
import { RiArrowLeftLine, RiArrowRightLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyNote } from '@/components/ui/empty-note';
import { cn } from '@/lib/utils';
import { SimStepHeader, Td, Th } from './ui';
import { INVOICE_ROWS, formatWon, type TaxInvoiceRow } from './model';

interface InvoiceListStepProps {
  /** 1단계에서 고른 (세금)계산서일 기간 — 리스트 필터. */
  from: string;
  to: string;
  selected: ReadonlySet<number>;
  onToggle: (no: number) => void;
  onToggleAll: (nos: readonly number[], next: boolean) => void;
  onBack: () => void;
  onNext: () => void;
}

/** 기간 안의 행만(경계 포함). 날짜가 'yyyy-mm-dd' 라 문자열 비교로 충분하다. */
function inRange(r: TaxInvoiceRow, from: string, to: string): boolean {
  return (!from || r.invoiceDate >= from) && (!to || r.invoiceDate <= to);
}

/**
 * 발행 후 경로 2단계 — 세금계산서 리스트에서 처리할 행을 고른다(법인카드 그리드 개입과 같은 맥락).
 *
 * 취소분(음수 공급가액) 행도 그대로 보이고 선택할 수 있어야 한다 — 원거래와 함께 선택하면
 * 공급가액 합계가 상계된다. 금액은 천단위 구분 + 우측 정렬(tabular-nums).
 */
export function InvoiceListStep({
  from,
  to,
  selected,
  onToggle,
  onToggleAll,
  onBack,
  onNext,
}: InvoiceListStepProps) {
  const rows = useMemo(() => INVOICE_ROWS.filter((r) => inRange(r, from, to)), [from, to]);
  const nos = useMemo(() => rows.map((r) => r.no), [rows]);
  const selectedRows = useMemo(() => rows.filter((r) => selected.has(r.no)), [rows, selected]);
  const supplyTotal = selectedRows.reduce((s, r) => s + r.supplyAmount, 0);
  const taxTotal = selectedRows.reduce((s, r) => s + r.taxAmount, 0);

  const allChecked = rows.length > 0 && selectedRows.length === rows.length;
  const someChecked = selectedRows.length > 0 && !allChecked;
  const allRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    // indeterminate 는 속성이 아니라 프로퍼티라 ref 로만 세팅된다.
    if (allRef.current) allRef.current.indeterminate = someChecked;
  }, [someChecked]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <SimStepHeader
        title="세금계산서 리스트 — 처리할 항목 선택"
        prompt={`${from} ~ ${to} 기간의 (세금)계산서입니다. 결의서로 만들 행을 체크하세요. 취소분(음수)도 함께 고를 수 있습니다.`}
      />

      {rows.length === 0 ? (
        <EmptyNote py={10}>선택한 기간에 조회된 세금계산서가 없습니다.</EmptyNote>
      ) : (
        <div className="border-border min-h-0 flex-1 overflow-auto rounded-[var(--radius-md)] border">
          <table className="w-full min-w-[1120px] border-collapse text-[11px]">
            <thead className="bg-muted/70 text-foreground-tertiary sticky top-0 z-10">
              <tr>
                <Th className="w-10 text-center">No</Th>
                {/* 체크박스는 24×24 — 예전 16×16 은 최소 타깃(24×24)에 미달했다.
                    셀 세로 여백을 0 으로 낮춰 행 높이는 그대로 둔다(글자 셀이 더 높다). */}
                <Th className="w-10 py-0 text-center">
                  <input
                    ref={allRef}
                    type="checkbox"
                    checked={allChecked}
                    onChange={(e) => onToggleAll(nos, e.target.checked)}
                    aria-label="전체 선택"
                    className="accent-accent size-6 cursor-pointer align-middle"
                  />
                </Th>
                <Th>(세금)계산서일</Th>
                <Th>사업자번호</Th>
                <Th>사업장명</Th>
                <Th>종사업장번호</Th>
                <Th>거래처코드</Th>
                <Th>거래처사업자번호</Th>
                <Th>거래처명</Th>
                <Th>거래처종사업장번호</Th>
                <Th className="text-right">공급가액</Th>
                <Th className="text-right">세액</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const checked = selected.has(r.no);
                const cancelled = r.supplyAmount < 0;
                return (
                  <tr
                    key={r.no}
                    className={cn(
                      'border-border/50 row-hover cursor-pointer border-t align-middle',
                      checked && 'bg-accent/5',
                    )}
                    onClick={() => onToggle(r.no)}
                  >
                    <Td className="text-foreground-tertiary text-center tabular-nums">{r.no}</Td>
                    <Td className="py-0 text-center">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => onToggle(r.no)}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={`${r.no}행 선택 — ${r.partnerName}`}
                        className="accent-accent size-6 cursor-pointer align-middle"
                      />
                    </Td>
                    <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
                      {r.invoiceDate}
                    </Td>
                    <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
                      {r.bizNo}
                    </Td>
                    <Td className="text-foreground-secondary whitespace-nowrap">{r.bizName}</Td>
                    <Td className="text-foreground-secondary whitespace-nowrap">{r.subBizNo}</Td>
                    <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
                      {r.partnerCode}
                    </Td>
                    <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
                      {r.partnerBizNo}
                    </Td>
                    <Td className="text-foreground-secondary whitespace-nowrap">
                      <span className="flex items-center gap-1.5">
                        {r.partnerName}
                        {cancelled ? (
                          <span className="bg-danger/15 text-danger shrink-0 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[9px] font-semibold">
                            취소
                          </span>
                        ) : null}
                      </span>
                    </Td>
                    <Td className="text-foreground-secondary whitespace-nowrap">
                      {r.partnerSubBizNo}
                    </Td>
                    <Td
                      className={cn(
                        'text-right whitespace-nowrap tabular-nums',
                        cancelled ? 'text-danger' : 'text-foreground-secondary',
                      )}
                    >
                      {formatWon(r.supplyAmount)}
                    </Td>
                    <Td
                      className={cn(
                        'text-right whitespace-nowrap tabular-nums',
                        r.taxAmount < 0 ? 'text-danger' : 'text-foreground-secondary',
                      )}
                    >
                      {formatWon(r.taxAmount)}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <p className="text-foreground-secondary text-[11px]">
          {rows.length}건 중{' '}
          <span
            className={cn(
              'font-semibold tabular-nums',
              selectedRows.length > 0 ? 'text-success' : 'text-warning',
            )}
          >
            {selectedRows.length}건
          </span>{' '}
          선택
          {selectedRows.length > 0 ? (
            <span className="text-foreground-tertiary">
              {' '}
              · 공급가액{' '}
              <span className="text-foreground-secondary font-semibold tabular-nums">
                {formatWon(supplyTotal)}
              </span>
              원 · 세액{' '}
              <span className="text-foreground-secondary font-semibold tabular-nums">
                {formatWon(taxTotal)}
              </span>
              원
            </span>
          ) : null}
        </p>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={onBack}>
            <RiArrowLeftLine size={14} aria-hidden />
            이전
          </Button>
          <Button
            size="sm"
            onClick={onNext}
            disabled={selectedRows.length === 0}
            title={selectedRows.length === 0 ? '처리할 행을 하나 이상 선택하세요.' : undefined}
          >
            입력항목 채우기
            <RiArrowRightLine size={14} aria-hidden />
          </Button>
        </div>
      </div>
    </div>
  );
}
