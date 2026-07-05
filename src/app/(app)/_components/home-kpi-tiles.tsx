'use client';

import type { ReactNode } from 'react';
import { SectionCard } from '@/components/ui/section-card';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateTime, formatPercent } from '@/lib/data/format';
import type { RunSummary } from '@/lib/live/runs-api';

/**
 * 홈 KPI 타일 — `GET /runs` 최근 표본(최신순)에서 클라이언트 계산한다.
 *
 * - 오늘 실행: Asia/Seoul 기준 오늘 시작된 런 수(표본 내).
 * - 성공률: 표본 중 종료된 런(succeeded+failed)에서 succeeded 비율.
 * - 최근 실패: 표본에서 가장 최근 failed 런의 에이전트명 + 시각.
 * - 누적 실행: 백엔드 total(내 스코프 전체 건수).
 *
 * 이 컴포넌트는 데이터 로드 후에만 실값을 렌더하므로(`loading` 동안 스켈레톤)
 * `new Date()` 사용이 하이드레이션에 안전하다.
 */

/** Asia/Seoul 기준 YYYY-MM-DD(en-CA 로케일이 ISO 날짜 형태를 준다). */
const SEOUL_DAY_FMT = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' });

function seoulDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return SEOUL_DAY_FMT.format(d);
}

interface HomeKpiTilesProps {
  loading: boolean;
  /** 최근 표본(최신순). */
  runs: RunSummary[];
  /** 스코프 전체 건수(백엔드 total). */
  total: number;
  /** 워크플로우 id → 사람이 읽는 에이전트명(모르면 raw id). */
  resolveAgentName: (workflowId: string) => string;
}

export function HomeKpiTiles({ loading, runs, total, resolveAgentName }: HomeKpiTilesProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" role="status" aria-busy>
        {Array.from({ length: 4 }, (_, i) => (
          <SectionCard key={i}>
            <div className="flex flex-col gap-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-7 w-20" />
              <Skeleton className="h-3 w-24" />
            </div>
          </SectionCard>
        ))}
      </div>
    );
  }

  const today = SEOUL_DAY_FMT.format(new Date());
  const todayCount = runs.filter((r) => seoulDay(r.startedAt) === today).length;

  const succeeded = runs.filter((r) => r.status === 'succeeded').length;
  const failed = runs.filter((r) => r.status === 'failed').length;
  const finished = succeeded + failed;

  const lastFailed = runs.find((r) => r.status === 'failed') ?? null;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <KpiTile
        label="오늘 실행"
        value={
          <>
            {todayCount}
            <ValueUnit>건</ValueUnit>
          </>
        }
        sub={`최근 ${runs.length}건 기준`}
      />
      <KpiTile
        label="성공률"
        value={
          finished > 0 ? (
            formatPercent((succeeded / finished) * 100, 0)
          ) : (
            <span className="text-muted-foreground">—</span>
          )
        }
        sub={finished > 0 ? `종료된 최근 ${finished}건 기준` : '종료된 실행이 없습니다'}
      />
      <KpiTile
        label="최근 실패"
        value={
          lastFailed ? (
            <span className="text-danger min-w-0 truncate text-base leading-7">
              {resolveAgentName(lastFailed.agentId)}
            </span>
          ) : (
            <span className="text-success text-base leading-7">없음</span>
          )
        }
        sub={
          lastFailed
            ? `${lastFailed.startedAt ? formatDateTime(lastFailed.startedAt) : '시각 미상'}${
                lastFailed.failedStep ? ` · ${lastFailed.failedStep}` : ''
              }`
            : `최근 ${runs.length}건에 실패가 없습니다`
        }
      />
      <KpiTile
        label="누적 실행"
        value={
          <>
            {total}
            <ValueUnit>건</ValueUnit>
          </>
        }
        sub="전체 기간"
      />
    </div>
  );
}

function ValueUnit({ children }: { children: ReactNode }) {
  return <span className="text-muted-foreground ml-0.5 text-sm font-normal">{children}</span>;
}

interface KpiTileProps {
  label: string;
  value: ReactNode;
  sub: ReactNode;
}

function KpiTile({ label, value, sub }: KpiTileProps) {
  return (
    <SectionCard>
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          {label}
        </p>
        <p className="text-foreground flex min-w-0 items-baseline text-2xl font-semibold tracking-tight tabular-nums">
          {value}
        </p>
        <p className="text-muted-foreground truncate text-xs">{sub}</p>
      </div>
    </SectionCard>
  );
}
