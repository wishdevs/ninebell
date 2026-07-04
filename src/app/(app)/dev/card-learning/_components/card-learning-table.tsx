'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { Td, Th } from '@/components/ui/table-cell';
import { errorMessage } from '@/lib/api/client';
import { fetchCardLearning, type LearnedSelection } from '@/lib/api/me-codes';
import { formatDateTime } from '@/lib/data/format';

const LEARNED_APPLY_MIN = 3;

/** 개입 학습 목록(빈도·최근순) — 개발 디버그 표. 결정적 적용(≥3회) 행은 강조. */
export function CardLearningTable() {
  const [rows, setRows] = useState<LearnedSelection[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCardLearning()
      .then(setRows)
      .catch((err) => toast.error(errorMessage(err, '학습 목록을 불러오지 못했습니다.')))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size={20} />
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        title="학습된 선택이 없습니다"
        description="에이전트 그리드 개입에서 예산단위·프로젝트·적요를 확정하면 가맹점 단위로 여기 쌓입니다."
      />
    );
  }

  return (
    <SectionCard>
      <div className="overflow-x-auto">
        <table className="w-full text-[length:var(--text-body-sm)]">
          <thead>
            <tr>
              <Th>가맹점</Th>
              <Th>예산단위 · 예산계정</Th>
              <Th>프로젝트</Th>
              <Th>적요</Th>
              <Th className="text-right">빈도</Th>
              <Th>최근</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const applied = r.count >= LEARNED_APPLY_MIN;
              return (
                <tr key={r.id} className="border-border/60 border-t">
                  <Td className="font-medium">{r.merchant || r.normMerchant}</Td>
                  <Td>
                    {r.budget ? (
                      <span>
                        {r.budget.name}
                        {r.budget.bgacctNm ? (
                          <span className="text-foreground-tertiary"> · {r.budget.bgacctNm}</span>
                        ) : null}
                      </span>
                    ) : (
                      <span className="text-foreground-tertiary">—</span>
                    )}
                  </Td>
                  <Td>
                    {r.project ? (
                      `${r.project.name}${r.project.wbsNo ? ` (${r.project.wbsNo})` : ''}`
                    ) : (
                      <span className="text-foreground-tertiary">—</span>
                    )}
                  </Td>
                  <Td className="text-foreground-secondary">{r.note ?? '—'}</Td>
                  <Td className="text-right">
                    <span
                      className={
                        applied
                          ? 'bg-accent/10 text-accent inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold'
                          : 'text-foreground-tertiary tabular-nums'
                      }
                      title={applied ? 'AI 없이 결정적 프리필' : undefined}
                    >
                      {r.count}회{applied ? ' · 결정적' : ''}
                    </span>
                  </Td>
                  <Td className="text-foreground-tertiary">
                    {r.lastUsedAt ? formatDateTime(r.lastUsedAt) : '—'}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
