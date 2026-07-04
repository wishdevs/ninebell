'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { Td, Th } from '@/components/ui/table-cell';
import { errorMessage } from '@/lib/api/client';
import { fetchCardSeed, type SeedSelection } from '@/lib/api/me-codes';

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
 */
const PAGE_SIZE = 50;

export function CardSeedTable() {
  const [rows, setRows] = useState<SeedSelection[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);

  // 검색어가 바뀌면 1페이지로 되돌린다(다른 결과 집합).
  useEffect(() => {
    setPage(0);
  }, [q]);

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true);
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
                  <Th>계정과목</Th>
                  <Th>적요</Th>
                  <Th className="text-right">거래</Th>
                  <Th className="text-right">지배율</Th>
                  <Th className="text-right">최근</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-border/60 border-t">
                    <Td className="font-medium">{r.merchant || r.normMerchant}</Td>
                    <Td>
                      {r.acctName ? (
                        <span>
                          {r.acctName}
                          {r.acctCode ? (
                            <span className="text-foreground-tertiary"> · {r.acctCode}</span>
                          ) : null}
                        </span>
                      ) : (
                        <span className="text-foreground-tertiary">—</span>
                      )}
                    </Td>
                    <Td className="text-foreground-secondary">{r.note ?? '—'}</Td>
                    <Td className="text-right tabular-nums">{r.count}</Td>
                    <Td className="text-right">
                      <DominanceBadge value={r.dominance} />
                    </Td>
                    <Td className="text-foreground-tertiary text-right tabular-nums">
                      {r.lastYear ?? '—'}
                    </Td>
                  </tr>
                ))}
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
