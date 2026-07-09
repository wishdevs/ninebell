'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { RiSearchLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/utils';

/** 콤보박스 옵션(거래처·프로젝트 공용). */
export interface ComboOption {
  code: string;
  name: string;
  /** 표시용 코드(거래처=거래처코드, 프로젝트=PJT_NO). code 는 프로젝트의 경우 PJT_NO|WBS_NO 합성이라 별도. */
  codeLabel?: string;
  /** 보조 표기(프로젝트 WBS명 등). */
  sub?: string;
  isDefault?: boolean;
}

/** 프로젝트 표시 코드 = PJT_NO. 카탈로그 code 는 PJT_NO|WBS_NO 합성이라 앞부분만 쓴다. */
export function projectCodeLabel(code: string, pjtNo?: string): string {
  return pjtNo ?? code.split('|')[0] ?? code;
}

/**
 * 카탈로그 콤보박스(거래처·프로젝트 공용) — 자주쓰는 필터 + ERP 검색(Enter/버튼) 팝오버.
 * 트리거는 돋보기 어포던스(목록 select 와 구분). 출장 국내/해외 폼이 공유한다.
 */
export function CatalogCombobox({
  value,
  placeholder,
  favorites,
  disabled,
  search,
  onSelect,
  onClear,
}: {
  value: { code: string; name: string };
  placeholder: string;
  favorites: ComboOption[];
  disabled?: boolean;
  search: (q: string) => Promise<ComboOption[]>;
  onSelect: (opt: ComboOption) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<ComboOption[] | null>(null);
  const [searchError, setSearchError] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const q = text.trim().toLowerCase();
  const filteredFavs = q
    ? favorites.filter((p) => p.name.toLowerCase().includes(q) || p.code.toLowerCase().includes(q))
    : favorites;

  const pick = (opt: ComboOption) => {
    onSelect(opt);
    setOpen(false);
    setText('');
    setResults(null);
    setSearchError(false);
  };

  const runSearch = useCallback(async () => {
    const query = text.trim();
    if (!query || searching) return;
    setSearching(true);
    setSearchError(false);
    try {
      // 검색 실패(네트워크·서버)와 '결과 없음'은 구분한다 — 실패는 재시도 유도, 빈 배열은 없음 표시.
      setResults(await search(query));
    } catch {
      setSearchError(true);
      setResults(null);
    } finally {
      setSearching(false);
    }
  }, [text, searching, search]);

  return (
    <div ref={wrapRef} className="relative min-w-0">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        title="검색하여 선택"
        className={cn(
          'border-border bg-surface flex h-10 w-full items-center justify-between gap-2 rounded-sm border px-3 text-left text-sm outline-none',
          'focus-visible:border-accent focus-visible:ring-accent focus-visible:ring-2 disabled:opacity-50',
        )}
      >
        <span
          className={cn(
            'min-w-0 truncate',
            value.code ? 'text-foreground' : 'text-muted-foreground/60',
          )}
        >
          {value.code ? value.name || value.code : placeholder}
        </span>
        {/* 검색형 선택(돋보기) — 목록 select(꺾쇠)와 구분되는 어포던스. */}
        <RiSearchLine size={15} aria-hidden className="text-foreground-tertiary shrink-0" />
      </button>

      {open ? (
        <div className="border-border bg-surface absolute left-0 z-20 mt-1 w-[300px] max-w-[calc(100vw-3rem)] rounded-[var(--radius-md)] border p-2 shadow-[var(--shadow-card)]">
          <div className="flex items-center gap-1.5">
            <input
              autoFocus
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void runSearch();
                }
                if (e.key === 'Escape') setOpen(false);
              }}
              placeholder="자주쓰는 필터 / ERP 검색어"
              className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 min-w-0 flex-1 rounded-sm border px-2 text-xs outline-none focus-visible:ring-2"
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="h-8 shrink-0 px-2"
              disabled={!text.trim() || searching}
              onClick={() => void runSearch()}
            >
              {searching ? <Spinner size={13} /> : <RiSearchLine size={13} aria-hidden />}
              검색
            </Button>
          </div>

          <div className="mt-2 max-h-56 overflow-y-auto">
            {value.code ? (
              <button
                type="button"
                onClick={() => {
                  onClear();
                  setOpen(false);
                }}
                className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-sm px-2 py-1.5 text-left text-xs"
              >
                선택 해제
              </button>
            ) : null}

            {filteredFavs.length > 0 ? (
              <>
                <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                  자주쓰는
                </p>
                {filteredFavs.map((o) => (
                  <OptionRow key={`f-${o.code}`} option={o} onClick={() => pick(o)} />
                ))}
              </>
            ) : null}

            {searchError ? (
              <div className="flex items-center justify-between gap-2 px-2 py-2">
                <p className="text-danger text-xs">검색에 실패했습니다.</p>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="h-7 shrink-0 px-2"
                  disabled={searching}
                  onClick={() => void runSearch()}
                >
                  다시 시도
                </Button>
              </div>
            ) : results && results.length > 0 ? (
              <>
                <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                  ERP 검색결과
                </p>
                {results.map((o) => (
                  <OptionRow key={`s-${o.code}`} option={o} onClick={() => pick(o)} />
                ))}
              </>
            ) : results && results.length === 0 ? (
              <p className="text-foreground-tertiary px-2 py-2 text-xs">검색 결과가 없습니다.</p>
            ) : null}

            {filteredFavs.length === 0 && !results && !searchError ? (
              <p className="text-foreground-tertiary px-2 py-2 text-xs">
                검색어를 입력해 ERP 에서 찾으세요.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function OptionRow({ option, onClick }: { option: ComboOption; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-muted/60 flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-xs"
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {option.codeLabel ? (
          <span className="text-foreground-tertiary bg-muted/60 shrink-0 rounded-[3px] px-1 py-px font-mono text-[10px] tabular-nums">
            {option.codeLabel}
          </span>
        ) : null}
        <span className="text-foreground truncate">{option.name || option.code}</span>
        {option.isDefault ? (
          <span className="text-accent shrink-0 text-[10px] font-semibold">기본</span>
        ) : null}
      </span>
      {option.sub ? (
        <span className="text-foreground-tertiary shrink-0 truncate">{option.sub}</span>
      ) : null}
    </button>
  );
}
