'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { RiSearchLine } from '@remixicon/react';
import { ComboPanel, isDesktopViewport, useOutsideClose } from '@/components/live/combo-popover';
import type { BudgetUnitOption } from '@/lib/live/types';
import { cn } from '@/lib/utils';

/**
 * 예산단위 검색형 combobox(계산서 개입 전용) — 프레임에 favorites+mine+all 전체 목록이 실려
 * 오므로 ERP 재검색 없이 클라이언트 필터만 한다. 그룹(자주쓰는 → 내 부서 → 전체)은 유지하고
 * 빈 그룹은 숨긴다. 키보드: ↑↓ 이동 · Enter 선택 · Esc 닫기.
 *
 * ⚠ LiveGridCard 안의 동명 컴포넌트와 상호작용 모델이 같지만 **의도적인 별도 사본**이다 —
 * 법인카드 그리드는 회귀 0 을 지켜야 해 손대지 않는다(공용화는 후속 정리 대상). 여기 사본은
 * 자주쓰는 ★ 토글·프리필 출처 배지를 뺀 단순화판이며, 딤/바텀시트 셸은 combo-popover 를 공유한다.
 */

/** 선택 단위 = (예산단위 × 사업계획 × 예산계정) 조합 행이라 셋을 함께 보여준다. */
function budgetLabel(o: BudgetUnitOption): string {
  return o.bgacctNm || o.bizplanNm
    ? `${o.name} · ${o.bizplanNm || '-'} · ${o.bgacctNm || '-'}`
    : `${o.name} (${o.code})`;
}

/** 검색 정규화 — 소문자화 + 공백 제거(대소문자·공백 관대 부분일치). */
function normalizeQuery(s: string): string {
  return s.toLowerCase().replace(/\s+/g, '');
}

function budgetMatches(o: BudgetUnitOption, q: string): boolean {
  if (!q) return true;
  return normalizeQuery(`${o.name} ${o.bizplanNm ?? ''} ${o.bgacctNm ?? ''} ${o.code}`).includes(q);
}

interface InvoiceBudgetComboboxProps {
  value: string;
  favorites: BudgetUnitOption[];
  /** 내 부서 매칭(자주쓰는 제외분). */
  mineExclFav?: BudgetUnitOption[];
  allExclFav: BudgetUnitOption[];
  disabled?: boolean;
  invalid?: boolean;
  placeholder?: string;
  className?: string;
  onChange: (code: string) => void;
}

export function InvoiceBudgetCombobox({
  value,
  favorites,
  mineExclFav = [],
  allExclFav,
  disabled,
  invalid,
  placeholder = '예산단위 선택',
  className,
  onChange,
}: InvoiceBudgetComboboxProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  useOutsideClose(open, wrapRef, () => setOpen(false));

  const q = normalizeQuery(text);
  const groups = [
    { label: '자주쓰는', items: favorites.filter((o) => budgetMatches(o, q)) },
    { label: '내 부서', items: mineExclFav.filter((o) => budgetMatches(o, q)) },
    { label: '전체', items: allExclFav.filter((o) => budgetMatches(o, q)) },
  ].filter((g) => g.items.length > 0);
  const flat = groups.flatMap((g) => g.items);
  // 필터로 목록이 줄어도 활성 인덱스가 범위를 벗어나지 않게 클램프.
  const active = flat.length === 0 ? -1 : Math.min(activeIdx, flat.length - 1);

  useEffect(() => {
    if (!open || active < 0) return;
    document.getElementById(`${listId}-opt-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [open, active, listId]);

  const current = value
    ? [...favorites, ...mineExclFav, ...allExclFav].find((o) => o.code === value)
    : undefined;
  const triggerLabel = value ? (current ? budgetLabel(current) : value) : null;

  const close = () => {
    setOpen(false);
    setText('');
    setActiveIdx(0);
  };

  const pick = (code: string) => {
    onChange(code);
    close();
  };

  return (
    <div ref={wrapRef} className={cn('relative min-w-0 flex-1', className)}>
      <button
        type="button"
        data-budget-trigger
        disabled={disabled}
        aria-invalid={invalid}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
        className={cn(
          'border-border bg-surface flex h-8 w-full items-center justify-between gap-1.5 rounded-[var(--radius-sm)] border px-2 text-left text-[11px] outline-none max-md:min-h-11',
          'focus-visible:border-accent',
          'aria-invalid:border-danger disabled:opacity-50',
        )}
      >
        <span
          className={cn(
            'min-w-0 truncate',
            triggerLabel ? 'text-foreground' : 'text-muted-foreground',
          )}
        >
          {triggerLabel ?? placeholder}
        </span>
        {/* 검색형 선택(돋보기) — 목록 select(꺾쇠)와 구분되는 어포던스. */}
        <RiSearchLine size={13} aria-hidden className="text-foreground-tertiary shrink-0" />
      </button>

      {open ? (
        <ComboPanel onClose={close} className="md:w-[min(320px,calc(100vw-2rem))]">
          <input
            autoFocus={isDesktopViewport()}
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
                setActiveIdx(Math.min(active + 1, flat.length - 1));
              } else if (ev.key === 'ArrowUp') {
                ev.preventDefault();
                setActiveIdx(Math.max(active - 1, 0));
              } else if (ev.key === 'Enter') {
                ev.preventDefault();
                if (active >= 0) pick(flat[active].code);
              } else if (ev.key === 'Escape') {
                ev.preventDefault();
                close();
              }
            }}
            placeholder="이름·사업계획·예산계정 검색"
            className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent h-8 w-full shrink-0 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none"
          />

          <div
            id={listId}
            role="listbox"
            aria-label="예산단위"
            className="mt-2 min-h-0 flex-1 overflow-y-auto overscroll-contain md:max-h-60 md:flex-none"
          >
            {value !== '' ? (
              <button
                type="button"
                onClick={() => pick('')}
                className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px] max-md:py-2.5"
              >
                선택 해제
              </button>
            ) : null}

            {groups.map((g, gi) => {
              // 그룹 경계를 넘는 전역(flat) 인덱스 — 키보드 활성 표시와 id 매칭에 쓴다.
              const offset = groups.slice(0, gi).reduce((n, x) => n + x.items.length, 0);
              return (
                <div key={g.label} role="group" aria-label={g.label}>
                  <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                    {g.label}
                  </p>
                  {g.items.map((o, i) => {
                    const idx = offset + i;
                    const selected = o.code === value;
                    return (
                      <button
                        key={o.code}
                        type="button"
                        id={`${listId}-opt-${idx}`}
                        role="option"
                        aria-selected={selected}
                        onClick={() => pick(o.code)}
                        onMouseEnter={() => setActiveIdx(idx)}
                        className={cn(
                          'flex w-full flex-col items-start gap-0.5 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px] max-md:py-2.5',
                          idx === active && 'bg-muted/60',
                        )}
                      >
                        <span
                          className={cn(
                            'leading-snug',
                            selected ? 'text-accent font-semibold' : 'text-foreground',
                          )}
                        >
                          {o.name}
                        </span>
                        {o.bizplanNm || o.bgacctNm ? (
                          <span className="text-foreground-tertiary leading-snug">
                            {[o.bizplanNm, o.bgacctNm].filter(Boolean).join(' · ')}
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              );
            })}

            {flat.length === 0 ? (
              <p className="text-foreground-tertiary px-2 py-2 text-[11px]">
                일치하는 예산단위가 없습니다.
              </p>
            ) : null}
          </div>
        </ComboPanel>
      ) : null}
    </div>
  );
}
