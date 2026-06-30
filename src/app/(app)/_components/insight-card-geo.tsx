import { RiNotification3Line } from '@remixicon/react';
import { Sparkline } from '@/components/ui/sparkline';
import type { GeoInsight } from '@/lib/data/home';
import { InsightCardShell } from './insight-card-shell';

interface InsightCardGeoProps {
  data: GeoInsight;
}

/**
 * GEO 모니터링 — 활성 브랜드 + 알람 + 7일 노출 스파크라인.
 * 알람이 1건 이상이면 Bell 아이콘 톤을 warning으로 올려 즉시 보이게 한다.
 */
export function InsightCardGeo({ data }: InsightCardGeoProps) {
  return (
    <InsightCardShell label={data.label} caption={data.caption} href={data.href} hint={data.hint}>
      <div className="flex items-end justify-between gap-3">
        <div className="grid gap-1.5">
          <p className="font-display text-2xl leading-none font-semibold tracking-tight tabular-nums">
            {data.activeBrands}
            <span className="text-muted-foreground ml-1 text-sm font-normal">개 브랜드</span>
          </p>
          <p className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
            <RiNotification3Line
              size={11}
              aria-hidden
              className={data.alarmCount > 0 ? 'text-warning' : 'text-foreground-tertiary'}
            />
            알람 {data.alarmCount}건
          </p>
        </div>
        <Sparkline
          values={data.exposureSparkline}
          ariaLabel="최근 7일 노출 추이"
          className="text-accent"
        />
      </div>
    </InsightCardShell>
  );
}
