'use client';

import { useEffect, useState } from 'react';
import { RiArrowRightSLine } from '@remixicon/react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { Td, Th } from '@/components/ui/table-cell';
import { errorMessage } from '@/lib/api/client';
import {
  fetchCardSeed,
  fetchCardSeedNotes,
  type SeedNote,
  type SeedSelection,
} from '@/lib/api/me-codes';
import { cn } from '@/lib/utils';

/** 지배율(dominance) → 신뢰도 배지. ≥0.8 고신뢰(강한 힌트), 그 미만은 참고. */
function DominanceBadge({ value }: { value: number }) {
  const high = value >= 0.8;
  return (
    <span
      className={
        high
          ? 'bg-info/10 text-info inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold'
          : 'text-foreground-tertiary tabular-nums'
      }
      title={high ? '최빈계정 지배율 높음 — 강한 힌트' : '분산 있음 — 참고용'}
    >
      {Math.round(value * 100)}%
    </span>
  );
}

/**
 * 전사 기초자료(seed) 목록 — 개발 디버그 표. 공용 데이터(user 무관, 가맹점→계정·적요).
 * 1,048행이라 검색(가맹점명) + 상위 200 제한. total 로 잘림을 표시한다.
 * 각 행은 가맹점당 **최상위 1건**(card_seed_selections)이며, 펼치면 그 가맹점의 **계정별 순위
 * 적요**(card_seed_notes — 계정을 바꾸면 그 계정 적요가 채워지는 근거)를 보여준다.
 */
const PAGE_SIZE = 50;

export function CardSeedTable() {
  const [rows, setRows] = useState<SeedSelection[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);

  // 펼침 상태 — 한 번에 한 가맹점만 펼친다. 계정별 적요는 norm_merchant 로 캐시(재펼침 시 재요청 없음).
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [notesByNorm, setNotesByNorm] = useState<Record<string, SeedNote[]>>({});
  const [loadingNorm, setLoadingNorm] = useState<string | null>(null);

  // 검색어가 바뀌면 1페이지로 되돌린다(다른 결과 집합).
  useEffect(() => {
    setPage(0);
  }, [q]);

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true);
      setExpandedId(null); // 새 결과셋 — 펼침 초기화(펼친 행이 목록에서 사라질 수 있음).
      fetchCardSeed({ q, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
        .then((r) => {
          setRows(r.items);
          setTotal(r.total);
        })
        .catch((err) => toast.error(errorMessage(err, '전사 기초자료를 불러오지 못했습니다.')))
        .finally(() => setLoading(false));
    }, 250); // 검색 디바운스
    return () => clearTimeout(t);
  }, [q, page]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rangeStart = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const rangeEnd = page * PAGE_SIZE + rows.length;

  function toggleExpand(row: SeedSelection) {
    if (expandedId === row.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(row.id);
    if (notesByNorm[row.normMerchant]) return; // 캐시 있음.
    setLoadingNorm(row.normMerchant);
    fetchCardSeedNotes(row.normMerchant)
      .then((items) => setNotesByNorm((prev) => ({ ...prev, [row.normMerchant]: items })))
      .catch((err) => toast.error(errorMessage(err, '계정별 적요를 불러오지 못했습니다.')))
      .finally(() => setLoadingNorm(null));
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="가맹점명 검색…"
          className="max-w-xs"
        />
        <span className="text-foreground-tertiary text-[length:var(--text-body-sm)] tabular-nums">
          {loading ? '조회 중…' : total === 0 ? '0건' : `${rangeStart}–${rangeEnd} / 총 ${total}건`}
        </span>
      </div>

      <p className="text-foreground-tertiary text-[length:var(--text-caption)]">
        행을 클릭하면 그 가맹점의 <b>계정별 순위 적요</b>가 펼쳐집니다(계정을 바꾸면 그 계정에 맞는
        적요가 채워지는 근거). <span className="text-info font-medium">계정 N</span> 배지 =
        구분(계정)이 여럿인 가맹점. 적요는 추천과 동일하게 정규화되어 표시됩니다 — 사람이름 적요는{' '}
        <b>제외</b>, <span className="text-foreground-secondary">+판매/제조</span> 표시는 접속자
        소속 비용구분(판관비→판매 / 제조원가→제조)에 따라 붙는 구분입니다.
      </p>

      {loading && rows.length === 0 ? (
        <div className="flex justify-center py-16">
          <Spinner size={20} />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          title={q ? '검색 결과가 없습니다' : '전사 기초자료가 없습니다'}
          description={
            q
              ? '다른 가맹점명으로 검색해 보세요.'
              : 'scripts/import_card_seed.py 로 기초자료 엑셀을 임포트하면 여기 표시됩니다.'
          }
        />
      ) : (
        <SectionCard>
          <div className="overflow-x-auto">
            <table className="w-full text-[length:var(--text-body-sm)]">
              <thead>
                <tr>
                  <Th>가맹점</Th>
                  <Th>계정과목 (1순위)</Th>
                  <Th>적요</Th>
                  <Th className="text-right">거래</Th>
                  <Th className="text-right">지배율</Th>
                  <Th className="text-right">최근</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const expanded = expandedId === r.id;
                  const multi = (r.noteCount ?? 0) > 1;
                  return (
                    <SeedRowFragment
                      key={r.id}
                      row={r}
                      expanded={expanded}
                      multi={multi}
                      notes={notesByNorm[r.normMerchant]}
                      loadingNotes={loadingNorm === r.normMerchant}
                      onToggle={() => toggleExpand(r)}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {pageCount > 1 ? (
        <div className="flex items-center justify-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || loading}
            className="border-border text-foreground-secondary hover:bg-muted/60 rounded-[var(--radius-sm)] border px-3 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40"
          >
            이전
          </button>
          <span className="text-foreground-tertiary min-w-24 text-center text-[length:var(--text-body-sm)] tabular-nums">
            {page + 1} / {pageCount}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={page >= pageCount - 1 || loading}
            className="border-border text-foreground-secondary hover:bg-muted/60 rounded-[var(--radius-sm)] border px-3 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40"
          >
            다음
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** 정규화된 적요 표시 — 사람이름 적요는 '제외' 표기, 판/제 구분 적요는 '+판매/제조' 칩. */
function NoteDisplay({
  note,
  costDivided,
  excluded,
}: {
  note: string | null;
  costDivided?: boolean;
  excluded?: boolean;
}) {
  if (excluded) {
    return <span className="text-foreground-tertiary italic">사람이름 — 추천 제외</span>;
  }
  if (!note) return <span className="text-foreground-tertiary">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span>{note}</span>
      {costDivided ? (
        <span
          className="text-foreground-tertiary bg-muted inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium"
          title="추천 시 접속자 비용구분(판관비→판매 / 제조원가→제조)이 붙습니다"
        >
          +판매/제조
        </span>
      ) : null}
    </span>
  );
}

/** 요약 행(가맹점 최상위 1건) + 펼침 시 계정별 순위 적요. */
function SeedRowFragment({
  row,
  expanded,
  multi,
  notes,
  loadingNotes,
  onToggle,
}: {
  row: SeedSelection;
  expanded: boolean;
  multi: boolean;
  notes: SeedNote[] | undefined;
  loadingNotes: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={cn(
          'border-border/60 hover:bg-muted/40 cursor-pointer border-t transition-colors',
          expanded && 'bg-muted/30',
        )}
      >
        <Td className="font-medium">
          <span className="flex items-center gap-1.5">
            <RiArrowRightSLine
              size={15}
              aria-hidden
              className={cn(
                'text-foreground-tertiary shrink-0 transition-transform',
                expanded && 'rotate-90',
              )}
            />
            <span className="truncate">{row.merchant || row.normMerchant}</span>
            {multi ? (
              <span className="bg-info/10 text-info inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums">
                계정 {row.noteCount}
              </span>
            ) : null}
          </span>
        </Td>
        <Td>
          {row.acctName ? (
            <span>
              {row.acctName}
              {row.acctCode ? (
                <span className="text-foreground-tertiary"> · {row.acctCode}</span>
              ) : null}
            </span>
          ) : (
            <span className="text-foreground-tertiary">—</span>
          )}
        </Td>
        <Td className="text-foreground-secondary">
          <NoteDisplay note={row.note} costDivided={row.costDivided} excluded={row.excluded} />
        </Td>
        <Td className="text-right tabular-nums">{row.count}</Td>
        <Td className="text-right">
          <DominanceBadge value={row.dominance} />
        </Td>
        <Td className="text-foreground-tertiary text-right tabular-nums">{row.lastYear ?? '—'}</Td>
      </tr>

      {expanded ? (
        <tr className="border-border/60 border-t">
          <td colSpan={6} className="bg-muted/20 px-4 py-3">
            {loadingNotes ? (
              <div className="flex items-center gap-2 py-2 text-[length:var(--text-body-sm)]">
                <Spinner size={14} /> 계정별 적요 불러오는 중…
              </div>
            ) : !notes || notes.length === 0 ? (
              <p className="text-foreground-tertiary py-1 text-[length:var(--text-body-sm)]">
                계정별 적요 데이터가 없습니다.
              </p>
            ) : (
              <div className="flex flex-col gap-1.5">
                <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.04em] uppercase">
                  계정별 순위 적요 · {notes.length}개
                </p>
                <table className="w-full text-[length:var(--text-body-sm)]">
                  <thead>
                    <tr className="text-foreground-tertiary text-[length:var(--text-caption)]">
                      <th className="w-14 py-1 pr-2 text-left font-medium">순위</th>
                      <th className="py-1 pr-3 text-left font-medium">계정과목</th>
                      <th className="py-1 pr-3 text-left font-medium">적요</th>
                      <th className="w-16 py-1 pr-2 text-right font-medium">건수</th>
                      <th className="w-16 py-1 text-right font-medium">지배율</th>
                    </tr>
                  </thead>
                  <tbody>
                    {notes.map((n, i) => (
                      <tr key={n.id} className="border-border/40 border-t">
                        <td className="py-1.5 pr-2">
                          <span
                            className={cn(
                              'inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
                              i === 0
                                ? 'bg-accent/10 text-accent'
                                : 'text-foreground-tertiary bg-muted',
                            )}
                          >
                            {i + 1}순위
                          </span>
                        </td>
                        <td className="py-1.5 pr-3">
                          {n.acctName ?? '—'}
                          {n.acctCode ? (
                            <span className="text-foreground-tertiary"> · {n.acctCode}</span>
                          ) : null}
                        </td>
                        <td className="text-foreground-secondary py-1.5 pr-3">
                          <NoteDisplay
                            note={n.note}
                            costDivided={n.costDivided}
                            excluded={n.excluded}
                          />
                        </td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">{n.count}</td>
                        <td className="py-1.5 text-right">
                          <DominanceBadge value={n.dominance} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}
