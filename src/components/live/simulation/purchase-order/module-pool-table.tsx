'use client';

import { useMemo, useState } from 'react';
import { RiArrowDownSLine, RiArrowRightSLine, RiStackLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import { cn } from '@/lib/utils';
import { formatInteger } from '@/lib/data/format';
import { MODULES, moduleAmount, selectionTotals, vendorMixOf, type BomModule } from './model';
import { MiniChip, PartsTable, RowCheckbox, SimSectionHeader, Td, Th } from './ui';

interface ModulePoolTableProps {
  /** 모듈 itemCode → 배정된 발주 seq(파생) — 배정된 모듈은 선택 불가. */
  assigned: ReadonlyMap<string, number>;
  selected: ReadonlySet<string>;
  onToggle: (code: string) => void;
  onToggleAll: (codes: readonly string[], next: boolean) => void;
  /** 선택된 모듈들을 발주단위로 묶는다(호출부가 선택 해제까지 처리). */
  onGroup: () => void;
}

/**
 * B. 모듈 풀 — BOM 3레벨 모듈 트리 테이블. 행 확장으로 부품 목록을 펼치고, 미배정 모듈을
 * 체크해 발주단위로 묶는다(옴니솔 반복 루프의 '모듈 선택 → 저장 1회 = 발주 1건'을 대체).
 *
 * 행 전체 클릭이 체크 토글(미배정 행만) — 확장 토글은 별도 버튼이라 stopPropagation 한다.
 * 이미 배정된 모듈은 체크박스 비활성 + '발주 N' 배지로 상태를 보인다.
 */
export function ModulePoolTable({
  assigned,
  selected,
  onToggle,
  onToggleAll,
  onGroup,
}: ModulePoolTableProps) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set<string>());

  const toggleExpand = (code: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  // 전체선택 대상 = 미배정 모듈만.
  const freeCodes = useMemo(
    () => MODULES.filter((m) => !assigned.has(m.itemCode)).map((m) => m.itemCode),
    [assigned],
  );
  const allChecked = freeCodes.length > 0 && freeCodes.every((c) => selected.has(c));
  const someChecked = !allChecked && freeCodes.some((c) => selected.has(c));

  const sel = useMemo(() => selectionTotals(selected), [selected]);

  return (
    <section className="flex flex-col gap-3">
      <SimSectionHeader
        title="모듈 풀 — 발주단위로 묶을 모듈 선택"
        prompt="함께 저장할 3레벨 모듈을 체크해 발주단위로 묶으세요. 한 발주단위가 구매요청 저장 1회 = 발주번호 1건이 됩니다."
      />

      <div className="border-border max-h-[440px] min-h-0 overflow-auto rounded-[var(--radius-md)] border">
        <table className="w-full min-w-[960px] border-collapse text-[11px]">
          <thead className="bg-muted/70 text-foreground-tertiary sticky top-0 z-10">
            <tr>
              <Th className="w-10 py-0 text-center">
                <RowCheckbox
                  checked={allChecked}
                  indeterminate={someChecked}
                  disabled={freeCodes.length === 0}
                  onClick={() => onToggleAll(freeCodes, !allChecked)}
                  label="미배정 모듈 전체 선택"
                />
              </Th>
              <Th>모듈</Th>
              <Th className="text-right">부품 수</Th>
              <Th>거래처 구성</Th>
              <Th className="text-right">요청금액 합</Th>
              <Th>상태</Th>
            </tr>
          </thead>
          <tbody>
            {MODULES.map((m) => (
              <ModuleRow
                key={m.itemCode}
                module={m}
                assignedSeq={assigned.get(m.itemCode)}
                checked={selected.has(m.itemCode)}
                expanded={expanded.has(m.itemCode)}
                onToggle={() => onToggle(m.itemCode)}
                onToggleExpand={() => toggleExpand(m.itemCode)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* 선택 툴바 — 선택 요약 + 묶기. 묶으면 호출부가 카드 생성 + 선택 해제한다. */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <p className="text-foreground-secondary text-[11px]">
          모듈{' '}
          <span
            className={cn(
              'font-semibold tabular-nums',
              sel.modules > 0 ? 'text-success' : 'text-foreground-tertiary',
            )}
          >
            {sel.modules}개
          </span>
          {sel.modules > 0 ? (
            <span className="text-foreground-tertiary">
              {' '}
              · 부품{' '}
              <span className="text-foreground-secondary font-semibold tabular-nums">
                {sel.parts}개
              </span>{' '}
              · 금액{' '}
              <span className="text-foreground-secondary font-semibold tabular-nums">
                {formatInteger(sel.amount)}
              </span>
              원 선택
            </span>
          ) : (
            <span className="text-foreground-tertiary"> 선택</span>
          )}
        </p>
        <Button size="sm" onClick={onGroup} disabled={sel.modules === 0}>
          <RiStackLine size={14} aria-hidden />
          발주단위로 묶기
        </Button>
      </div>
    </section>
  );
}

interface ModuleRowProps {
  module: BomModule;
  /** 배정돼 있으면 그 발주 seq — 체크 불가 + '발주 N' 배지. */
  assignedSeq: number | undefined;
  checked: boolean;
  expanded: boolean;
  onToggle: () => void;
  onToggleExpand: () => void;
}

function ModuleRow({
  module: m,
  assignedSeq,
  checked,
  expanded,
  onToggle,
  onToggleExpand,
}: ModuleRowProps) {
  const isAssigned = assignedSeq != null;
  const mix = vendorMixOf(m);
  return (
    <>
      <tr
        className={cn(
          'border-border/50 border-t align-middle',
          !isAssigned && 'row-hover cursor-pointer',
          checked && 'bg-accent/5',
        )}
        onClick={isAssigned ? undefined : onToggle}
      >
        <Td className="py-0 text-center">
          <RowCheckbox
            checked={checked}
            disabled={isAssigned}
            onClick={onToggle}
            label={`${m.name} · ${m.spec} 선택`}
          />
        </Td>
        <Td>
          <span className="flex items-center gap-1.5">
            <button
              type="button"
              aria-expanded={expanded}
              aria-label={`${m.name} 부품 목록 ${expanded ? '접기' : '펼치기'}`}
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpand();
              }}
              className="text-foreground-tertiary hover:text-foreground flex size-6 shrink-0 items-center justify-center"
            >
              {expanded ? (
                <RiArrowDownSLine size={15} aria-hidden />
              ) : (
                <RiArrowRightSLine size={15} aria-hidden />
              )}
            </button>
            <span className="flex min-w-0 flex-col">
              <span className="text-foreground font-medium">
                {m.name} <span className="text-foreground-secondary font-normal">· {m.spec}</span>
              </span>
              <span className="text-foreground-tertiary font-mono text-[10px]">{m.itemCode}</span>
            </span>
          </span>
        </Td>
        <Td className="text-foreground-secondary text-right tabular-nums">{m.parts.length}</Td>
        <Td>
          <span className="flex flex-wrap items-center gap-1">
            {mix.pseudoCounts.map((p) => (
              <MiniChip key={p.vendorClass} tone="warn">
                {p.vendorClass} {p.count}
              </MiniChip>
            ))}
            {mix.realKinds > 0 ? <MiniChip>실거래처 {mix.realKinds}종</MiniChip> : null}
          </span>
        </Td>
        <Td className="text-foreground-secondary text-right whitespace-nowrap tabular-nums">
          {formatInteger(moduleAmount(m))}
        </Td>
        <Td className="whitespace-nowrap">
          {isAssigned ? (
            <StatusPill label={`발주 ${assignedSeq}`} variant="info" />
          ) : (
            <span className="text-foreground-tertiary">미배정</span>
          )}
        </Td>
      </tr>
      {expanded ? (
        <tr className="border-border/50 border-t">
          <td colSpan={6} className="p-0">
            <PartsTable parts={m.parts} />
          </td>
        </tr>
      ) : null}
    </>
  );
}
