'use client';

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { Td, Th } from '@/components/ui/table-cell';
import { errorMessage } from '@/lib/api/client';
import {
  clearCardLearning,
  deleteCardLearning,
  fetchCardLearning,
  type LearnedSelection,
} from '@/lib/api/me-codes';
import { formatDateTime } from '@/lib/data/format';

const LEARNED_APPLY_MIN = 3;

/** 개입 학습 목록(빈도·최근순) — 개발 디버그 표. 결정적 적용(≥3회) 행은 강조. 행별/전체 삭제 지원. */
export function CardLearningTable() {
  const [rows, setRows] = useState<LearnedSelection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    fetchCardLearning()
      .then(setRows)
      .catch((err) => toast.error(errorMessage(err, '학습 목록을 불러오지 못했습니다.')))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function removeOne(id: string) {
    setBusyId(id);
    try {
      await deleteCardLearning(id);
      setRows((prev) => prev.filter((r) => r.id !== id));
      toast.success('학습 항목을 삭제했습니다.');
    } catch (err) {
      toast.error(errorMessage(err, '삭제하지 못했습니다.'));
    } finally {
      setBusyId(null);
    }
  }

  async function clearAll() {
    setConfirmClear(false);
    setBusyId('__all__');
    try {
      const n = await clearCardLearning();
      setRows([]);
      toast.success(`개인 학습 ${n}건을 전체 삭제했습니다.`);
    } catch (err) {
      toast.error(errorMessage(err, '전체 삭제하지 못했습니다.'));
      load();
    } finally {
      setBusyId(null);
    }
  }

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
        description="에이전트 그리드 개입에서 예산단위·프로젝트·적요를 바꾸면 가맹점 단위로 여기 쌓입니다."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-foreground-tertiary text-[length:var(--text-body-sm)] tabular-nums">
          {rows.length}건
        </span>
        {confirmClear ? (
          <div className="flex items-center gap-2 text-[length:var(--text-body-sm)]">
            <span className="text-foreground-secondary">전체 삭제할까요?</span>
            <button
              type="button"
              onClick={clearAll}
              disabled={busyId !== null}
              className="text-danger hover:bg-danger/10 rounded-[var(--radius-sm)] px-2 py-1 font-medium disabled:opacity-40"
            >
              삭제
            </button>
            <button
              type="button"
              onClick={() => setConfirmClear(false)}
              className="text-foreground-secondary hover:bg-muted rounded-[var(--radius-sm)] px-2 py-1"
            >
              취소
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmClear(true)}
            disabled={busyId !== null}
            className="border-border text-danger hover:bg-danger/10 rounded-[var(--radius-sm)] border px-3 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors disabled:opacity-40"
          >
            전체 삭제
          </button>
        )}
      </div>

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
                <Th className="text-right">삭제</Th>
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
                    <Td className="text-right">
                      <button
                        type="button"
                        onClick={() => removeOne(r.id)}
                        disabled={busyId !== null}
                        aria-label={`${r.merchant || r.normMerchant} 학습 삭제`}
                        title="이 학습 삭제"
                        className="text-foreground-tertiary hover:text-danger hover:bg-danger/10 rounded-[var(--radius-sm)] px-2 py-1 transition-colors disabled:opacity-40"
                      >
                        {busyId === r.id ? <Spinner size={12} /> : '✕'}
                      </button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}
