'use client';

import { useMemo, useState } from 'react';
import { RiArrowDownSLine, RiArrowRightSLine, RiStackLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import { cn } from '@/lib/utils';
import { formatInteger } from '@/lib/data/format';
import { moduleAmount, selectionTotals, vendorMixOf, type BomModule, type PlanBom } from './model';
import { MiniChip, PartsTable, RowCheckbox, SimSectionHeader, Td, Th } from './ui';

interface ModulePoolTableProps {
  /** 주입된 BOM 컨텍스트(데모 픽스처 또는 hitl.plannerBom) — 모듈 풀의 원천. */
  bom: PlanBom;
  /** 모듈 itemCode → 배정된 발주 seq(파생) — 배정된 모듈은 선택 불가. */
  assigned: ReadonlyMap<string, number>;
  selected: ReadonlySet<string>;
  onToggle: (code: string) => void;
  onToggleAll: (codes: readonly string[], next: boolean) => void;
  /** 선택된 모듈들을 발주단위로 묶는다(호출부가 선택 해제까지 처리). */
  onGroup: () => void;
  /** 만들어진 발주단위 수 — 하단 요약(발주단위 스탯)용. */
  unitCount: number;
}

/**
 * B. 모듈 풀 — BOM 3레벨 모듈 트리 테이블. 행 확장으로 부품 목록을 펼치고, 미배정 모듈을
 * 체크해 발주단위로 묶는다(옴니솔 반복 루프의 '모듈 선택 → 저장 1회 = 발주 1건'을 대체).
 *
 * 행 전체 클릭이 체크 토글(미배정 행만) — 확장 토글은 별도 버튼이라 stopPropagation 한다.
 * 이미 배정된 모듈은 체크박스 비활성 + '발주 N' 배지로 상태를 보인다.
 */
export function ModulePoolTable({
  bom,
  assigned,
  selected,
  onToggle,
  onToggleAll,
  onGroup,
  unitCount,
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
    () => bom.modules.filter((m) => !assigned.has(m.itemCode)).map((m) => m.itemCode),
    [bom, assigned],
  );
  const allChecked = freeCodes.length > 0 && freeCodes.every((c) => selected.has(c));
  const someChecked = !allChecked && freeCodes.some((c) => selected.has(c));

  const sel = useMemo(() => selectionTotals(bom, selected), [bom, selected]);

  // 전체 요약(BOM 기준) — 종전 헤더의 스탯 타일 5개를 하단 선택 바로 옮긴 값(사용자 요청
  // 2026-08-14). 선택 요약과 같은 글자 크기로, 구분선 오른쪽에 붙인다.
  const bomTotals = useMemo(
    () => ({
      parts: bom.modules.reduce((s, m) => s + m.parts.length, 0),
      amount: bom.modules.reduce((s, m) => s + m.parts.reduce((a, p) => a + p.amount, 0), 0),
    }),
    [bom],
  );
  const unassigned = bom.modules.length - assigned.size;

  return (
    <section className="flex flex-col gap-3">
      <SimSectionHeader
        step={2}
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
            {bom.modules.map((m) => (
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
          {/* 전체 요약 — 선택 요약과 같은 크기로, 세로 구분선 오른쪽에 잇는다. */}
          <span aria-hidden className="text-border-strong mx-2">
            |
          </span>
          <span className="text-foreground-tertiary">
            모듈 <SummaryNum>{bom.modules.length}</SummaryNum> · 부품{' '}
            <SummaryNum>{bomTotals.parts}</SummaryNum> · 총 요청금액{' '}
            <SummaryNum>{formatInteger(bomTotals.amount)}</SummaryNum>원 · 발주단위{' '}
            <SummaryNum>{unitCount}</SummaryNum> · 미배정{' '}
            <span
              className={cn(
                'font-semibold tabular-nums',
                unassigned > 0 ? 'text-warning' : 'text-success',
              )}
            >
              {unassigned}
            </span>
          </span>
        </p>
        <Button size="sm" onClick={onGroup} disabled={sel.modules === 0}>
          <RiStackLine size={14} aria-hidden />
          발주단위로 묶기
        </Button>
      </div>
    </section>
  );
}

/** 하단 요약의 숫자 — 선택 요약과 같은 톤·굵기(글자 크기는 부모가 정한다). */
function SummaryNum({ children }: { children: React.ReactNode }) {
  return <span className="text-foreground-secondary font-semibold tabular-nums">{children}</span>;
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
      {/* 행 상태 3단(사용자 요청 2026-08-14) — 진하기 순서로 읽히게 한다:
          배정됨(가장 흐림·클릭 불가) < 기본 < 호버 < 선택됨(가장 진함).
          종전엔 선택이 bg-accent/5, 호버가 surface-raised 로 둘 다 거의 안 보였고
          배정된 행은 기본 행과 색이 같아 '왜 안 눌리지'가 되기 쉬웠다. */}
      <tr
        className={cn(
          'border-border/50 border-t align-middle transition-colors',
          isAssigned
            ? 'bg-muted/40 text-foreground-tertiary cursor-not-allowed'
            : checked
              ? 'bg-accent/10 hover:bg-accent/15 cursor-pointer'
              : 'hover:bg-muted/60 cursor-pointer',
        )}
        aria-selected={checked}
        aria-disabled={isAssigned || undefined}
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
              <span
                className={cn(
                  'font-medium',
                  isAssigned ? 'text-foreground-tertiary' : 'text-foreground',
                )}
              >
                {m.name}{' '}
                <span
                  className={cn(
                    'font-normal',
                    isAssigned ? 'text-foreground-tertiary' : 'text-foreground-secondary',
                  )}
                >
                  · {m.spec}
                </span>
              </span>
              <span className="text-foreground-tertiary font-mono text-[10px]">{m.itemCode}</span>
            </span>
          </span>
        </Td>
        <Td
          className={cn(
            'text-right tabular-nums',
            isAssigned ? 'text-foreground-tertiary' : 'text-foreground-secondary',
          )}
        >
          {m.parts.length}
        </Td>
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
        <Td
          className={cn(
            'text-right whitespace-nowrap tabular-nums',
            isAssigned ? 'text-foreground-tertiary' : 'text-foreground-secondary',
          )}
        >
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
