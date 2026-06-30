import { RiArrowRightDownLine, RiArrowRightUpLine, RiSubtractLine } from '@remixicon/react';
import { SectionCard } from '@/components/ui/section-card';
import { KPIS, type KpiDatum } from '@/lib/data/analytics';
import { cn } from '@/lib/utils';

/** KPI 4종 행 — 모바일 2열, lg 이상 4열. */
export function KpiCards() {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {KPIS.map((kpi) => (
        <KpiCard key={kpi.key} kpi={kpi} />
      ))}
    </div>
  );
}

function KpiCard({ kpi }: { kpi: KpiDatum }) {
  return (
    <SectionCard caption={kpi.label} className="gap-3">
      <div className="flex flex-col gap-2.5">
        <p className="font-display text-2xl leading-none font-semibold tracking-tight tabular-nums">
          {kpi.value}
        </p>
        {kpi.delta !== null ? (
          <div className="flex items-center gap-2 text-xs">
            <DeltaChip delta={kpi.delta} tone={kpi.tone} />
            <span className="text-foreground-tertiary">{kpi.deltaLabel}</span>
          </div>
        ) : (
          <div className="text-foreground-tertiary text-xs">{kpi.deltaLabel}</div>
        )}
      </div>
    </SectionCard>
  );
}

/**
 * 증감칩. `positive-up`은 상승이 좋음(success)·하락이 나쁨(danger),
 * `positive-down`(이탈률)은 그 반대, `neutral`은 중립색.
 */
function DeltaChip({ delta, tone }: { delta: number; tone: KpiDatum['tone'] }) {
  if (Math.abs(delta) < 0.05) {
    return (
      <span className="text-foreground-tertiary inline-flex items-center gap-0.5 font-semibold tabular-nums">
        <RiSubtractLine size={12} aria-hidden />
        0.0%
      </span>
    );
  }
  const isUp = delta > 0;
  const Arrow = isUp ? RiArrowRightUpLine : RiArrowRightDownLine;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 font-semibold tabular-nums',
        toneColor(tone, isUp),
      )}
    >
      <Arrow size={12} aria-hidden />
      {isUp ? '+' : ''}
      {delta.toFixed(1)}%
    </span>
  );
}

function toneColor(tone: KpiDatum['tone'], isUp: boolean): string {
  if (tone === 'neutral') return 'text-foreground';
  if (tone === 'positive-up') return isUp ? 'text-success' : 'text-danger';
  return isUp ? 'text-danger' : 'text-success';
}
