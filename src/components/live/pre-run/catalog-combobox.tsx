'use client';

import { useCallback, useState } from 'react';
import { RiSearchLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
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

/** 터치 기기 여부 — 팝오버가 열리자마자 가상 키보드가 목록을 덮지 않게 자동 포커스를 가른다. */
function isCoarsePointer(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches;
}

/**
 * 카탈로그 콤보박스(거래처·프로젝트 공용) — 자주쓰는 필터 + ERP 검색(Enter/버튼) 팝오버.
 * 트리거는 돋보기 어포던스(목록 select 와 구분). 출장 국내/해외 폼이 공유한다.
 *
 * 팝업은 Radix Popover(포털) — 예전 자체 absolute 팝업은 폼의 overflow 스크롤 컨테이너
 * 안에 갇혀 잘렸다(DatePicker 가 Popover 를 쓰는 이유와 동일: 표/그리드 셀 안에서도 안 잘림).
 */
export function CatalogCombobox({
  value,
  placeholder,
  favorites,
  recents = [],
  disabled,
  search,
  onSelect,
  onClear,
}: {
  value: { code: string; name: string };
  placeholder: string;
  favorites: ComboOption[];
  /** 최근 선택 그룹(선택) — '자주쓰는' 위에 나열한다. 채우기·저장은 호출부 소유. */
  recents?: ComboOption[];
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

  const q = text.trim().toLowerCase();
  // 공백 구분 단어 AND — 서버 검색(/me/catalog q)과 같은 규칙('etr 2' → 'ETRIBE ERP TEST 002').
  const terms = q.split(/\s+/).filter(Boolean);
  const matches = (p: ComboOption) =>
    terms.every((t) => p.name.toLowerCase().includes(t) || p.code.toLowerCase().includes(t));
  const filteredRecents = q ? recents.filter(matches) : recents;
  // 최근에 이미 있는 항목은 자주쓰는에서 감춘다 — 두 그룹에 겹쳐 나오면 목록만 길어진다.
  const recentCodes = new Set(filteredRecents.map((r) => r.code));
  const filteredFavs = (q ? favorites.filter(matches) : favorites).filter(
    (p) => !recentCodes.has(p.code),
  );

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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          title="검색하여 선택"
          className={cn(
            'border-border bg-surface flex h-10 w-full min-w-0 items-center justify-between gap-2 rounded-sm border px-3 text-left text-sm outline-none',
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
      </PopoverTrigger>

      <PopoverContent
        className="w-[300px] max-w-[calc(100vw-3rem)] p-2 shadow-[var(--shadow-card)]"
        onOpenAutoFocus={(e) => {
          // 터치에서는 Radix 가 첫 포커서블(검색 input)로 포커스를 옮겨 키보드를 띄우므로 막는다.
          if (isCoarsePointer()) e.preventDefault();
        }}
      >
        <div className="flex items-center gap-1.5">
          <input
            autoFocus={!isCoarsePointer()}
            enterKeyHint="search"
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
            className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 min-w-0 flex-1 rounded-sm border px-2 text-[length:var(--text-body-sm)] outline-none focus-visible:ring-2 pointer-coarse:h-10"
          />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="h-8 shrink-0 px-2 pointer-coarse:h-10"
            disabled={!text.trim() || searching}
            onClick={() => void runSearch()}
          >
            {searching ? <Spinner size={13} /> : <RiSearchLine size={13} aria-hidden />}
            검색
          </Button>
        </div>

        {/* 목록 높이는 dvh 로도 캡 — 가상 키보드가 열려 가시 높이가 줄어도 목록이 밖으로 안 나간다. */}
        <div className="mt-2 max-h-[min(14rem,40dvh)] overflow-y-auto">
          {value.code ? (
            <button
              type="button"
              onClick={() => {
                onClear();
                setOpen(false);
              }}
              className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-sm px-2 py-1.5 text-left text-[length:var(--text-body)] pointer-coarse:py-2.5"
            >
              선택 해제
            </button>
          ) : null}

          {filteredRecents.length > 0 ? (
            <>
              <p className="text-foreground-tertiary px-2 py-1 text-[length:var(--text-caption)] font-semibold tracking-wider uppercase">
                최근
              </p>
              {filteredRecents.map((o) => (
                <OptionRow key={`r-${o.code}`} option={o} onClick={() => pick(o)} />
              ))}
            </>
          ) : null}

          {filteredFavs.length > 0 ? (
            <>
              <p className="text-foreground-tertiary px-2 py-1 text-[length:var(--text-caption)] font-semibold tracking-wider uppercase">
                자주쓰는
              </p>
              {filteredFavs.map((o) => (
                <OptionRow key={`f-${o.code}`} option={o} onClick={() => pick(o)} />
              ))}
            </>
          ) : null}

          {searchError ? (
            <div className="flex items-center justify-between gap-2 px-2 py-2">
              <p className="text-danger text-[length:var(--text-body-sm)]">검색에 실패했습니다.</p>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-7 shrink-0 px-2 pointer-coarse:h-10"
                disabled={searching}
                onClick={() => void runSearch()}
              >
                다시 시도
              </Button>
            </div>
          ) : results && results.length > 0 ? (
            <>
              <p className="text-foreground-tertiary px-2 py-1 text-[length:var(--text-caption)] font-semibold tracking-wider uppercase">
                ERP 검색결과
              </p>
              {results.map((o) => (
                <OptionRow key={`s-${o.code}`} option={o} onClick={() => pick(o)} />
              ))}
            </>
          ) : results && results.length === 0 ? (
            <p className="text-foreground-tertiary px-2 py-2 text-[length:var(--text-body-sm)]">
              검색 결과가 없습니다.
            </p>
          ) : null}

          {filteredFavs.length === 0 && !results && !searchError ? (
            <p className="text-foreground-tertiary px-2 py-2 text-[length:var(--text-body-sm)]">
              검색어를 입력해 ERP 에서 찾으세요.
            </p>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function OptionRow({ option, onClick }: { option: ComboOption; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-muted/60 flex w-full flex-col items-start gap-0.5 rounded-sm px-2 py-1.5 text-left text-[length:var(--text-body)] pointer-coarse:py-2.5"
    >
      {/* 두 줄 구성(모바일 회귀 2026-08-14): 종전엔 이름과 sub(WBS 등)가 한 줄을 나눠 쓰고
          sub 가 shrink-0 라, 좁은 폭에서 정작 식별자인 이름이 '12C…' 로 뭉개졌다. 이름을
          한 줄로 온전히 주고 sub 를 아래 줄로 내린다(형제 BudgetCombobox 와 같은 문법). */}
      <span className="flex w-full min-w-0 items-center gap-1.5">
        {option.codeLabel ? (
          <span className="text-foreground-tertiary bg-muted/60 shrink-0 rounded-[3px] px-1 py-px font-mono text-[length:var(--text-caption)] tabular-nums">
            {option.codeLabel}
          </span>
        ) : null}
        <span className="text-foreground truncate">{option.name || option.code}</span>
        {option.isDefault ? (
          <span className="text-accent shrink-0 text-[length:var(--text-caption)] font-semibold">
            기본
          </span>
        ) : null}
      </span>
      {option.sub ? (
        <span className="text-foreground-tertiary w-full truncate text-[length:var(--text-body-sm)]">
          {option.sub}
        </span>
      ) : null}
    </button>
  );
}
