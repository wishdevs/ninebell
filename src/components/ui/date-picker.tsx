'use client';

import { RiArrowLeftSLine, RiArrowRightSLine, RiCalendarLine } from '@remixicon/react';
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

/**
 * 디자인 날짜 선택기 — 네이티브 <input type="date"> 대체(디자인 시스템 팔레트/팝오버).
 *
 * 필드는 **텍스트 입력**이다(2026-08-28): 직접 타이핑·붙여넣기·복사가 되고, 클릭하면 값이
 * 전체 선택돼 ⌘C 로 바로 복사된다. 달력 아이콘이 팝오버(월 달력)를 연다.
 * 값/출력은 로컬 기준 'yyyy-mm-dd'(문자열). TZ 밀림 방지 위해 toISOString 을 쓰지 않고
 * 연·월·일을 직접 조합한다. 입력은 yyyy-mm-dd / yyyy.mm.dd / yyyy/mm/dd / yyyymmdd 를 받는다.
 *
 * 다중 선택(엑셀 셀처럼): 한 화면의 DatePicker 는 전부 모듈 레지스트리에 등록되고, 한 필드에서
 * 마우스를 누른 채 다른 필드까지 끌면 DOM 순서로 그 사이 필드가 범위 선택된다. 선택 상태에서
 * ⌘C 는 날짜를 줄바꿈으로 이어 복사하고, ⌘V 는 클립보드 날짜(1개면 전체에 같은 값, 여러 줄이면
 * 순서대로)를 **선택된 필드에만** 넣는다. 선택된 필드의 달력에서 날짜를 고르면 선택 전부에 같은
 * 날짜가 들어간다. Esc·바깥 클릭이면 선택 해제.
 */

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'] as const;

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** 연·월(0-base)·일 → 'yyyy-mm-dd'. */
function toIso(y: number, m0: number, d: number): string {
  return `${y}-${pad2(m0 + 1)}-${pad2(d)}`;
}

/** 'yyyy-mm-dd' → {y, m0, d} | null(형식 불일치). */
function parseIso(v: string): { y: number; m0: number; d: number } | null {
  const mt = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (!mt) return null;
  return { y: Number(mt[1]), m0: Number(mt[2]) - 1, d: Number(mt[3]) };
}

/**
 * 사람이 친 날짜 → 'yyyy-mm-dd' | null. 구분자(-, ., /, 공백) 유무 무관, 월·일 한 자리 허용,
 * 실재하지 않는 날짜(2026-02-30)는 거부.
 */
export function normalizeDateText(raw: string): string | null {
  const s = raw.trim();
  const mt = /^(\d{4})[-./\s]?(\d{1,2})[-./\s]?(\d{1,2})$/.exec(s);
  if (!mt) return null;
  const y = Number(mt[1]);
  const m = Number(mt[2]);
  const d = Number(mt[3]);
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  const dt = new Date(y, m - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null;
  return toIso(y, m - 1, d);
}

// ── 다중 선택 레지스트리(모듈 전역 — 같은 화면의 DatePicker 전부) ────────────────────

interface Entry {
  el: HTMLElement;
  getValue: () => string;
  setValue: (v: string) => void;
}

const registry = new Map<string, Entry>();
let selected = new Set<string>();
let anchorId: string | null = null;
let dragging = false;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

/** 레지스트리를 DOM 순서로 정렬한 id 목록. */
function orderedIds(): string[] {
  return [...registry.entries()]
    .sort(([, a], [, b]) =>
      a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
    )
    .map(([id]) => id);
}

function setSelection(next: Set<string>) {
  selected = next;
  emit();
}

function clearSelection() {
  if (selected.size === 0 && anchorId == null) return;
  anchorId = null;
  setSelection(new Set());
}

/** anchor..target(DOM 순서) 범위를 선택. */
function selectRange(target: string) {
  if (!anchorId) return;
  const ids = orderedIds();
  const a = ids.indexOf(anchorId);
  const b = ids.indexOf(target);
  if (a < 0 || b < 0) return;
  const [lo, hi] = a < b ? [a, b] : [b, a];
  setSelection(new Set(ids.slice(lo, hi + 1)));
}

/** 선택된 필드 전부에 같은 값을 넣는다. */
function applyToSelection(v: string) {
  for (const id of selected) registry.get(id)?.setValue(v);
}

function entryAtPoint(x: number, y: number): string | null {
  for (const [id, e] of registry) {
    const r = e.el.getBoundingClientRect();
    if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return id;
  }
  return null;
}

let docBound = false;

/** 문서 리스너 1회 바인딩 — 드래그 확장·해제·복사/붙여넣기. */
function bindDocument() {
  if (docBound || typeof document === 'undefined') return;
  docBound = true;

  document.addEventListener('mousemove', (e) => {
    if (!dragging || !anchorId) return;
    const id = entryAtPoint(e.clientX, e.clientY);
    if (!id) return;
    if (id === anchorId && selected.size <= 1) return;
    // 다른 필드로 넘어간 순간부터 범위 선택 — 텍스트 선택은 걷어내고 입력 포커스도 뺀다.
    e.preventDefault();
    window.getSelection()?.removeAllRanges();
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    selectRange(id);
  });

  document.addEventListener('mouseup', () => {
    dragging = false;
  });

  document.addEventListener('mousedown', (e) => {
    // 등록된 필드 밖 클릭 → 선택 해제.
    const t = e.target as Node | null;
    for (const { el } of registry.values()) if (t && el.contains(t)) return;
    // 달력 팝오버는 포털(필드 바깥 DOM)이라 별도로 제외 — 선택 상태에서 달력으로 고르는 경로.
    if (t instanceof Element && t.closest('[data-date-picker-popover]')) return;
    clearSelection();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && selected.size > 0) clearSelection();
  });

  document.addEventListener('copy', (e) => {
    if (selected.size < 2) return; // 1개는 입력 자체의 네이티브 복사.
    const text = orderedIds()
      .filter((id) => selected.has(id))
      .map((id) => registry.get(id)?.getValue() ?? '')
      .join('\n');
    e.clipboardData?.setData('text/plain', text);
    e.preventDefault();
  });

  document.addEventListener('paste', (e) => {
    if (selected.size < 2) return; // 1개는 입력 자체의 네이티브 붙여넣기(onChange 파싱).
    const raw = e.clipboardData?.getData('text/plain') ?? '';
    const dates = raw
      .split(/[\r\n\t,;]+/)
      .map((s) => normalizeDateText(s))
      .filter((s): s is string => s != null);
    if (dates.length === 0) return;
    e.preventDefault();
    const targets = orderedIds().filter((id) => selected.has(id));
    targets.forEach((id, i) => {
      // 1개면 전체에 같은 값, 여러 개면 순서대로(부족하면 남는 필드는 그대로).
      const v = dates.length === 1 ? dates[0] : dates[i];
      if (v) registry.get(id)?.setValue(v);
    });
  });
}

let seq = 0;

// ── 컴포넌트 ─────────────────────────────────────────────────────────────────

interface DatePickerProps {
  /** 선택값 'yyyy-mm-dd'(빈 문자열이면 미선택). */
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}

export function DatePicker({ value, onChange, disabled, ariaLabel, className }: DatePickerProps) {
  const [open, setOpen] = useState(false);
  const idRef = useRef<string>('');
  if (!idRef.current) idRef.current = `dp-${(seq += 1)}`;
  const id = idRef.current;
  const rootRef = useRef<HTMLDivElement>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const valueRef = useRef(value);
  valueRef.current = value;

  // 입력 초안 — 타이핑 중 문자열. 값이 바깥에서 바뀌면 초안을 버린다.
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    setDraft(value);
  }, [value]);

  // 레지스트리 등록(다중 선택 대상). disabled 는 제외.
  useEffect(() => {
    if (disabled || !rootRef.current) return;
    bindDocument();
    registry.set(id, {
      el: rootRef.current,
      getValue: () => valueRef.current,
      setValue: (v) => onChangeRef.current(v),
    });
    return () => {
      registry.delete(id);
      if (selected.has(id)) {
        const next = new Set(selected);
        next.delete(id);
        setSelection(next);
      }
    };
  }, [id, disabled]);

  const isSelected = useSyncExternalStore(
    subscribe,
    () => selected.has(id) && selected.size > 1,
    () => false,
  );

  // 보기 기준 월 — 선택값 있으면 그 달, 없으면 오늘.
  const [view, setView] = useState<{ y: number; m0: number }>(() => {
    const p = parseIso(value);
    if (p) return { y: p.y, m0: p.m0 };
    const now = new Date();
    return { y: now.getFullYear(), m0: now.getMonth() };
  });

  const todayIso = useMemo(() => {
    const n = new Date();
    return toIso(n.getFullYear(), n.getMonth(), n.getDate());
  }, []);

  // 이번 달 셀(앞쪽 공백 + 1..말일, 7의 배수로 채움).
  const cells = useMemo(() => {
    const startWeekday = new Date(view.y, view.m0, 1).getDay(); // 0=일
    const daysInMonth = new Date(view.y, view.m0 + 1, 0).getDate();
    const out: (number | null)[] = [];
    for (let i = 0; i < startWeekday; i += 1) out.push(null);
    for (let d = 1; d <= daysInMonth; d += 1) out.push(d);
    while (out.length % 7 !== 0) out.push(null);
    return out;
  }, [view]);

  const openChange = (o: boolean) => {
    setOpen(o);
    if (o) {
      const p = parseIso(value);
      if (p) setView({ y: p.y, m0: p.m0 }); // 열 때 선택월로 동기화.
    }
  };

  const prevMonth = () =>
    setView((v) => (v.m0 === 0 ? { y: v.y - 1, m0: 11 } : { y: v.y, m0: v.m0 - 1 }));
  const nextMonth = () =>
    setView((v) => (v.m0 === 11 ? { y: v.y + 1, m0: 0 } : { y: v.y, m0: v.m0 + 1 }));

  const pick = (d: number) => {
    const iso = toIso(view.y, view.m0, d);
    // 드래그 범위 선택 중인 필드에서 고르면 선택된 필드 전부에 같은 날짜를 넣는다(2026-08-28).
    if (selected.size > 1 && selected.has(id)) applyToSelection(iso);
    else onChange(iso);
    setOpen(false);
  };

  /** 초안 확정 — 유효한 날짜면 반영, 비우면 해제, 그 외는 원래 값으로 되돌린다. */
  const commit = () => {
    const t = draft.trim();
    if (t === '') {
      if (value !== '') onChange('');
      return;
    }
    const iso = normalizeDateText(t);
    if (iso) {
      if (iso !== value) onChange(iso);
      else setDraft(value);
    } else {
      setDraft(value);
    }
  };

  const hasValue = parseIso(value) != null;

  return (
    <div
      ref={rootRef}
      data-date-picker=""
      data-selected={isSelected ? '' : undefined}
      className={cn(
        'border-border bg-surface flex h-10 w-full items-center gap-2 rounded-sm border pr-2 pl-3 text-sm',
        'focus-within:border-accent',
        isSelected ? 'border-accent bg-accent/10' : '',
        disabled ? 'cursor-not-allowed opacity-50' : '',
        className,
      )}
      onMouseDown={(e) => {
        if (disabled) return;
        // 달력 버튼·팝오버 클릭은 드래그 시작이 아니다.
        if ((e.target as HTMLElement).closest('button')) return;
        dragging = true;
        anchorId = id;
        if (selected.size > 0) setSelection(new Set());
      }}
    >
      <input
        type="text"
        value={draft}
        disabled={disabled}
        aria-label={ariaLabel}
        placeholder="날짜 선택"
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => {
          const next = e.target.value;
          setDraft(next);
          // 완성된 날짜(붙여넣기 포함)는 바로 반영 — 블러를 기다리지 않는다.
          const iso = normalizeDateText(next);
          if (iso && iso !== value) onChange(iso);
        }}
        onFocus={(e) => e.currentTarget.select()}
        onMouseUp={(e) => {
          // 클릭으로 포커스가 들어올 때 브라우저가 전체선택을 캐럿으로 되돌리는 것을 막는다.
          const el = e.currentTarget;
          if (el.selectionStart === 0 && el.selectionEnd === el.value.length) e.preventDefault();
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            commit();
            e.currentTarget.blur();
          } else if (e.key === 'Escape') {
            setDraft(value);
            e.currentTarget.blur();
          }
        }}
        className={cn(
          'min-w-0 flex-1 bg-transparent tabular-nums outline-none',
          'placeholder:text-muted-foreground/60 selection:bg-accent/25',
          hasValue || draft ? 'text-foreground' : '',
          disabled ? 'cursor-not-allowed' : '',
        )}
      />
      <Popover open={open} onOpenChange={openChange}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label={ariaLabel ? `${ariaLabel} 달력 열기` : '달력 열기'}
            className="text-foreground-tertiary hover:text-foreground hover:bg-muted/60 shrink-0 rounded-sm p-1 transition-colors outline-none disabled:cursor-not-allowed"
          >
            <RiCalendarLine size={15} aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto p-3" data-date-picker-popover="">
          <div className="mb-2 flex items-center justify-between">
            <button
              type="button"
              onClick={prevMonth}
              aria-label="이전 달"
              className="text-foreground-tertiary hover:text-foreground hover:bg-muted/60 rounded-sm p-1 transition-colors pointer-coarse:p-3"
            >
              <RiArrowLeftSLine size={18} aria-hidden />
            </button>
            <span className="text-foreground text-sm font-semibold tabular-nums">
              {view.y}. {pad2(view.m0 + 1)}
            </span>
            <button
              type="button"
              onClick={nextMonth}
              aria-label="다음 달"
              className="text-foreground-tertiary hover:text-foreground hover:bg-muted/60 rounded-sm p-1 transition-colors pointer-coarse:p-3"
            >
              <RiArrowRightSLine size={18} aria-hidden />
            </button>
          </div>
          <div className="grid grid-cols-7 gap-0.5">
            {WEEKDAYS.map((w, i) => (
              <span
                key={w}
                className={cn(
                  'flex h-7 items-center justify-center text-[11px] font-medium',
                  i === 0
                    ? 'text-danger/80'
                    : i === 6
                      ? 'text-accent/80'
                      : 'text-foreground-tertiary',
                )}
              >
                {w}
              </span>
            ))}
            {cells.map((d, i) => {
              if (d == null) return <span key={`empty-${i}`} />;
              const iso = toIso(view.y, view.m0, d);
              const isPicked = iso === value;
              const isToday = iso === todayIso;
              return (
                <button
                  key={iso}
                  type="button"
                  onClick={() => pick(d)}
                  aria-pressed={isPicked}
                  className={cn(
                    // 터치 셀 h-10 w-10: 7×40px + 6×2px 갭 + 팝오버 p-3 = 318px — 320px 뷰포트 안.
                    'flex h-8 w-8 items-center justify-center rounded-sm text-[13px] tabular-nums transition-colors pointer-coarse:h-10 pointer-coarse:w-10',
                    isPicked
                      ? 'bg-accent text-accent-foreground font-semibold'
                      : 'text-foreground hover:bg-muted/70',
                    !isPicked && isToday ? 'ring-border-strong ring-1' : '',
                  )}
                >
                  {d}
                </button>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
