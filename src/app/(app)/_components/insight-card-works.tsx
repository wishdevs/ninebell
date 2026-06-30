import type { WorksInsight } from '@/lib/data/home';
import { cn } from '@/lib/utils';
import { InsightCardShell } from './insight-card-shell';

interface InsightCardWorksProps {
  data: WorksInsight;
}

type MetricTone = 'default' | 'info' | 'success' | 'danger' | 'muted';

const TONE_CLASS: Record<MetricTone, string> = {
  default: 'text-foreground',
  info: 'text-info',
  success: 'text-success',
  danger: 'text-danger',
  muted: 'text-foreground-tertiary',
};

/**
 * 업무 — 4지표 스트립(전체 / 진행 / 완료 / 지연).
 * 지연 카운트가 0이 아니면 톤을 danger로 떨어뜨려 즉시 보이게 한다.
 */
export function InsightCardWorks({ data }: InsightCardWorksProps) {
  return (
    <InsightCardShell label={data.label} caption={data.caption} href={data.href} hint={data.hint}>
      <dl className="grid grid-cols-4 gap-2">
        <Metric label="전체" value={data.total} />
        <Metric label="진행" value={data.inProgress} tone="info" />
        <Metric label="완료" value={data.done} tone="success" />
        <Metric label="지연" value={data.overdue} tone={data.overdue > 0 ? 'danger' : 'muted'} />
      </dl>
    </InsightCardShell>
  );
}

function Metric({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: number;
  tone?: MetricTone;
}) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-foreground-tertiary text-[10px] tracking-[0.06em] uppercase">{label}</dt>
      <dd
        className={cn(
          'font-display text-xl leading-none font-semibold tabular-nums',
          TONE_CLASS[tone],
        )}
      >
        {value}
      </dd>
    </div>
  );
}
