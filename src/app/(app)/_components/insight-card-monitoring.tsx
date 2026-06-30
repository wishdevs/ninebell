import { RiPulseLine, RiShieldLine } from '@remixicon/react';
import type { MonitoringInsight } from '@/lib/data/home';
import { formatPercent } from '@/lib/data/format';
import { InsightCardShell } from './insight-card-shell';

interface InsightCardMonitoringProps {
  data: MonitoringInsight;
}

/**
 * 모니터링 — 평균 가동률 + 사이트 수 + 다운 수.
 * 다운이 1건 이상이면 힌트 톤을 danger로 떨어뜨려 즉시 보이게 한다.
 */
export function InsightCardMonitoring({ data }: InsightCardMonitoringProps) {
  const hasIncident = data.downCount > 0;
  const hint = hasIncident ? (
    <span className="text-danger inline-flex items-center gap-1">
      <RiShieldLine size={11} aria-hidden />
      현재 다운 {data.downCount}건 — 즉시 확인 필요
    </span>
  ) : (
    data.hint
  );

  return (
    <InsightCardShell label={data.label} caption={data.caption} href={data.href} hint={hint}>
      <div className="flex items-end justify-between gap-4">
        <div className="grid gap-1.5">
          <p className="text-foreground-tertiary text-[10px] tracking-[0.06em] uppercase">
            평균 가동률
          </p>
          <p className="font-display text-2xl leading-none font-semibold tracking-tight tabular-nums">
            {formatPercent(data.avgUptimePct, 2)}
          </p>
        </div>
        <div className="text-foreground-tertiary inline-flex items-center gap-1.5 text-xs">
          <RiPulseLine size={12} aria-hidden />
          사이트 {data.siteCount}개
        </div>
      </div>
    </InsightCardShell>
  );
}
