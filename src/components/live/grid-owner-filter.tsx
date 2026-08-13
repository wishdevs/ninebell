'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { RiSearchLine } from '@remixicon/react';
import type { LiveGridRow } from '@/lib/live/types';
import { cn } from '@/lib/utils';

/**
 * 그리드 개입 — 카드 소유자(사용자) 단위 **보기 필터**와 **처리 대상 선택** 도우미.
 *
 * 소유자 = 카드명 괄호 안 이름('국민법인카드(최동원)-9858' → '최동원').
 * 괄호 안이 부서·공용 표기('제조본부' 등)여도 그대로 하나의 값으로 취급하고,
 * 괄호가 없거나 비어 있으면 UNKNOWN_OWNER('기타') 그룹으로 묶는다.
 *
 * 처리 범위는 두 겹이다(사용자 확정 2026-08-13):
 *   ① 사용자 선택(검색형 콤보박스) — 고른 사용자의 행만 보이고, **저장도 그 범위뿐**이다.
 *   ② 행별 '제외' 체크 — 범위 **안**에서 개별로 더 뺀다(그룹헤더 토글은 그 단축).
 * ①은 edits 를 건드리지 않고 제출 시점에만 skip 으로 나가므로 '전체'로 되돌리면 원상복구된다.
 */

export const UNKNOWN_OWNER = '기타';

/** 카드명 → 소유자. 마지막 괄호 그룹을 취한다(카드명 뒤 번호·중간 괄호 변형에 관대). */
export function cardOwnerOf(card?: string): string {
  const groups = (card ?? '').match(/\([^()]*\)/g);
  const last = groups?.[groups.length - 1];
  const name = last?.slice(1, -1).trim() ?? '';
  return name || UNKNOWN_OWNER;
}

/** 표시용 금액('12,345원') → 정수. '-'·빈값·비숫자는 null(합계에서 제외). */
export function parseWonAmount(amount?: string): number | null {
  const s = (amount ?? '').replace(/[,원\s]/g, '');
  if (!/^-?\d+$/.test(s)) return null;
  return Number(s);
}

const WON_FMT = new Intl.NumberFormat('ko-KR');

export function formatWonSum(n: number): string {
  return `${WON_FMT.format(n)}원`;
}

export interface OwnerGroup {
  owner: string;
  rows: LiveGridRow[];
  /** 금액 파싱 가능한 행들의 승인액 합(승인취소 음수 포함). */
  amountSum: number;
}

/** 입력 순서(호출부의 표시 정렬)를 그룹 안에서 유지하며 소유자별로 묶는다.
 * 그룹 순서 = 소유자 가나다순, '기타'는 항상 마지막. */
export function groupRowsByOwner(rows: readonly LiveGridRow[]): OwnerGroup[] {
  const byOwner = new Map<string, LiveGridRow[]>();
  for (const r of rows) {
    const owner = cardOwnerOf(r.card);
    const list = byOwner.get(owner);
    if (list) list.push(r);
    else byOwner.set(owner, [r]);
  }
  return [...byOwner.entries()]
    .map(([owner, groupRows]) => ({
      owner,
      rows: groupRows,
      amountSum: groupRows.reduce((sum, r) => sum + (parseWonAmount(r.amount) ?? 0), 0),
    }))
    .sort((a, b) => {
      if (a.owner === UNKNOWN_OWNER) return 1;
      if (b.owner === UNKNOWN_OWNER) return -1;
      return a.owner.localeCompare(b.owner, 'ko');
    });
}

// ── 소유자 바(보기 선택 + 처리 대상 단축) ────────────────────────────

/**
 * 사용자 한 줄 — 검색형 콤보박스 하나가 **보기와 처리 범위를 함께** 정한다.
 *
 * ⚠ 설계 변경 이력(사용자 피드백 2026-08-13, 3단계 — 매번 더 줄였다):
 *   ① 칩 rail(40명 × 3줄) → 예산단위·프로젝트와 같은 **검색형 선택** 하나로 축소.
 *   ② '보기 필터 + 별도 처리 버튼' → **선택 = 처리 범위**. 사용자를 고르면 그 사용자 행만
 *      저장되고 나머지는 이번 실행에서 처리되지 않는다(제출 payload 에 skip 으로 나간다).
 *      범위 밖 행의 '제외' 체크는 건드리지 않으므로 '전체'로 되돌리면 원상복구된다.
 *   ③ 일괄 제외/해제 버튼 제거 — 이 줄은 **선택 + 건수 표시**만 한다.
 * 범위 **안**에서 더 빼려면 행별 '제외' 체크(또는 그룹헤더 토글)를 쓴다.
 */
export function OwnerBar({
  groups,
  owner,
  totalCount,
  scopedCount,
  manualExcludedCount,
  onOwnerChange,
}: {
  groups: OwnerGroup[];
  /** 선택한 소유자. '' = 전체. */
  owner: string;
  /** 전체 행 수('전체' 옵션 라벨). */
  totalCount: number;
  /** 이번에 실제로 저장될 행 수(범위 안 · 제외 미체크). */
  scopedCount: number;
  /** 현재 화면(범위 안)에서 '제외' 체크된 행 수 — 0 초과면 건수만 알린다. */
  manualExcludedCount: number;
  onOwnerChange: (owner: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
        처리 대상
      </span>
      <OwnerCombobox
        groups={groups}
        owner={owner}
        totalCount={totalCount}
        onChange={onOwnerChange}
      />
      <span className="text-foreground-secondary text-[11px] tabular-nums">
        저장 {scopedCount}행
      </span>

      {manualExcludedCount > 0 ? (
        <span className="text-foreground-tertiary text-[11px] tabular-nums">
          제외 {manualExcludedCount}행
        </span>
      ) : null}
    </div>
  );
}

/**
 * 사용자 검색형 선택 — 예산단위/프로젝트 콤보박스와 **같은 패턴**(트리거 버튼 + 돋보기,
 * 열면 검색 입력에 autoFocus, ↑↓·Enter·Esc 키보드 이동, 바깥 클릭 닫기).
 * 사용자가 수십 명이라 일반 select 로는 못 찾는다(피드백 2026-08-13).
 */
function OwnerCombobox({
  groups,
  owner,
  totalCount,
  onChange,
}: {
  groups: OwnerGroup[];
  owner: string;
  totalCount: number;
  onChange: (owner: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const q = text.toLowerCase().replace(/\s+/g, '');
  const matched = q ? groups.filter((g) => g.owner.toLowerCase().includes(q)) : groups;
  // 옵션 목록 = '전체'(검색어 없을 때만) + 매칭 사용자. 키보드 인덱스는 이 배열 기준.
  const options: { value: string; label: string; count: number; sum: number }[] = [
    ...(q ? [] : [{ value: '', label: '전체', count: totalCount, sum: NaN }]),
    ...matched.map((g) => ({
      value: g.owner,
      label: g.owner,
      count: g.rows.length,
      sum: g.amountSum,
    })),
  ];
  const active = options.length === 0 ? -1 : Math.min(activeIdx, options.length - 1);

  useEffect(() => {
    if (!open || active < 0) return;
    document.getElementById(`${listId}-opt-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [open, active, listId]);

  const close = () => {
    setOpen(false);
    setText('');
    setActiveIdx(0);
  };
  const pick = (value: string) => {
    onChange(value);
    close();
  };

  const selected = owner ? groups.find((g) => g.owner === owner) : undefined;
  const triggerLabel = owner ? `${owner} ${selected?.rows.length ?? 0}행` : `전체 ${totalCount}행`;

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="사용자 선택(보기)"
        onClick={() => (open ? close() : setOpen(true))}
        className={cn(
          'border-border bg-surface flex h-8 w-52 items-center justify-between gap-1.5 rounded-[var(--radius-sm)] border px-2 text-left text-[11px] outline-none',
          'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2',
          owner && 'border-accent text-accent font-semibold',
        )}
      >
        <span className="min-w-0 truncate">{triggerLabel}</span>
        <RiSearchLine size={13} aria-hidden className="text-foreground-tertiary shrink-0" />
      </button>

      {open ? (
        <div className="border-border bg-surface absolute left-0 z-20 mt-1 w-[260px] rounded-[var(--radius-md)] border p-2 shadow-[var(--shadow-card)]">
          <input
            autoFocus
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={active >= 0 ? `${listId}-opt-${active}` : undefined}
            value={text}
            onChange={(ev) => {
              setText(ev.target.value);
              setActiveIdx(0);
            }}
            onKeyDown={(ev) => {
              if (ev.key === 'ArrowDown') {
                ev.preventDefault();
                setActiveIdx(Math.min(active + 1, options.length - 1));
              } else if (ev.key === 'ArrowUp') {
                ev.preventDefault();
                setActiveIdx(Math.max(active - 1, 0));
              } else if (ev.key === 'Enter') {
                ev.preventDefault();
                if (active >= 0) pick(options[active].value);
              } else if (ev.key === 'Escape') {
                ev.preventDefault();
                close();
              }
            }}
            placeholder="사용자 검색"
            className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-full rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2"
          />

          <div
            id={listId}
            role="listbox"
            aria-label="사용자"
            className="mt-2 max-h-60 overflow-y-auto"
          >
            {options.map((o, idx) => (
              <button
                key={o.value || '__all'}
                type="button"
                id={`${listId}-opt-${idx}`}
                role="option"
                aria-selected={o.value === owner}
                onClick={() => pick(o.value)}
                onMouseEnter={() => setActiveIdx(idx)}
                className={cn(
                  'flex w-full items-baseline gap-1.5 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px]',
                  idx === active && 'bg-muted/60',
                )}
              >
                <span
                  className={cn(
                    'min-w-0 truncate',
                    o.value === owner ? 'text-accent font-semibold' : 'text-foreground',
                  )}
                >
                  {o.label}
                </span>
                <span className="text-foreground-tertiary ml-auto shrink-0 tabular-nums">
                  {o.count}행{Number.isNaN(o.sum) ? '' : ` · ${formatWonSum(o.sum)}`}
                </span>
              </button>
            ))}
            {options.length === 0 ? (
              <p className="text-foreground-tertiary px-2 py-2 text-[11px]">
                일치하는 사용자가 없습니다.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 바·그룹헤더 공용 소형 버튼 — 테두리+배경(포커스링 없음, 프로젝트 UI 규율). */
function BarButton({
  children,
  title,
  disabled,
  onClick,
  className,
}: {
  children: React.ReactNode;
  title: string;
  disabled?: boolean;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'border-border bg-surface text-foreground-secondary hover:bg-muted/60 focus-visible:border-accent focus-visible:ring-accent/40 h-7 cursor-pointer rounded-[var(--radius-sm)] border px-2.5 text-[11px] transition-colors outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
    >
      {children}
    </button>
  );
}

// ── 소유자 그룹 헤더 행 ──────────────────────────────────────────────

/**
 * 그룹 구분 헤더 행 — 왼쪽은 소유자명 · 건수 · 승인액 합, 오른쪽은 **처리 대상 토글**.
 * (사용자 단위로 '제외' 체크를 한 번에 켜고 끄는 단축 — 행별 체크가 여전히 단일 소스다.)
 */
export function OwnerGroupHeaderRow({
  group,
  colSpan,
  includedCount,
  disabled = false,
  onToggleAll,
}: {
  group: OwnerGroup;
  colSpan: number;
  /** 이 그룹에서 저장 대상인 행 수(제외되지 않은 행). */
  includedCount: number;
  disabled?: boolean;
  /** include=true 면 그룹 전체 제외 해제, false 면 전체 제외. */
  onToggleAll: (include: boolean) => void;
}) {
  const total = group.rows.length;
  const allExcluded = includedCount === 0;
  return (
    <tr className="bg-muted/50 border-border/50 border-t">
      <td colSpan={colSpan} className="px-2 py-1.5">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'font-semibold',
              allExcluded ? 'text-foreground-tertiary line-through' : 'text-foreground',
            )}
          >
            {group.owner}
          </span>
          <span className="text-foreground-tertiary tabular-nums">
            · {total}행 · {formatWonSum(group.amountSum)}
          </span>
          <BarButton
            disabled={disabled}
            onClick={() => onToggleAll(allExcluded)}
            title={
              allExcluded
                ? `${group.owner} ${total}행의 '제외'를 해제합니다.`
                : `${group.owner} ${total}행을 '제외'로 표시합니다(저장에서 빠집니다).`
            }
            className="ml-auto h-6 px-2 text-[10px]"
          >
            {allExcluded ? '포함' : '제외'}
          </BarButton>
        </div>
      </td>
    </tr>
  );
}
