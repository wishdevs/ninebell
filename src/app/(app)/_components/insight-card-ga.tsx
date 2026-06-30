import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import { Sparkline } from '@/components/ui/sparkline';
import type { GaInsight } from '@/lib/data/home';
import { formatInteger } from '@/lib/data/format';
import { cn } from '@/lib/utils';
import { InsightCardShell } from './insight-card-shell';

interface InsightCardGaProps {
  data: GaInsight;
}

/**
 * GA — 최근 7일 세션 + 전주 대비 증감% + 7포인트 스파크라인.
 * delta가 양수면 success, 음수면 danger, 0이면 무채색 톤.
 */
export function InsightCardGa({ data }: InsightCardGaProps) {
  const isUp = data.deltaPct > 0;
  const isDown = data.deltaPct < 0;
  const Arrow = isDown ? ArrowDownRight : ArrowUpRight;
  const tone = isUp ? 'text-success' : isDown ? 'text-danger' : 'text-foreground-tertiary';

  return (
    <InsightCardShell label={data.label} caption={data.caption} href={data.href} hint={data.hint}>
      <div className="flex items-end justify-between gap-3">
        <div className="grid gap-1.5">
          <p className="font-display text-2xl leading-none font-semibold tracking-tight tabular-nums">
            {formatInteger(data.sessions7d)}
          </p>
          <span
            className={cn('inline-flex items-center gap-0.5 text-xs font-semibold tabular-nums', tone)}
          >
            <Arrow size={11} strokeWidth={2} aria-hidden />
            {isUp ? '+' : ''}
            {data.deltaPct.toFixed(1)}%
            <span className="text-foreground-tertiary ml-1 font-normal">전주 대비</span>
          </span>
        </div>
        <Sparkline values={data.sparkline} ariaLabel="최근 7일 세션 추이" className={tone} />
      </div>
    </InsightCardShell>
  );
}
