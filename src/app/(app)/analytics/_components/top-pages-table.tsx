import { TOP_PAGES } from '@/lib/data/analytics';
import { formatInteger, formatPercent, formatSeconds } from '@/lib/data/format';
import { cn } from '@/lib/utils';

const TH = 'text-foreground-tertiary px-2 py-2.5 text-[length:var(--text-caption)] font-medium tracking-[0.06em] uppercase';

/** 인기 페이지 표 — 경로/제목 · 조회수 · 평균 시간 · 이탈률. */
export function TopPagesTable() {
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-border border-b">
            <th className={cn(TH, 'text-left')}>페이지</th>
            <th className={cn(TH, 'text-right')}>조회수</th>
            <th className={cn(TH, 'text-right')}>평균 시간</th>
            <th className={cn(TH, 'text-right')}>이탈률</th>
          </tr>
        </thead>
        <tbody>
          {TOP_PAGES.map((row) => (
            <tr key={row.path} className="border-border-subtle row-hover border-b last:border-0">
              <td className="px-2 py-3">
                <div className="flex flex-col">
                  <span className="text-foreground font-medium">{row.title}</span>
                  <span className="text-foreground-tertiary font-mono text-[11px]">{row.path}</span>
                </div>
              </td>
              <td className="text-foreground px-2 py-3 text-right tabular-nums">
                {formatInteger(row.views)}
              </td>
              <td className="text-foreground-secondary px-2 py-3 text-right tabular-nums">
                {formatSeconds(row.avgSeconds)}
              </td>
              <td className="px-2 py-3 text-right tabular-nums">
                <span className={bounceTone(row.bounceRate)}>{formatPercent(row.bounceRate)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 이탈률 색: 낮으면 좋음(success) → 보통(secondary) → 높으면 주의(warning). */
function bounceTone(rate: number): string {
  if (rate >= 50) return 'text-warning';
  if (rate >= 40) return 'text-foreground-secondary';
  return 'text-success';
}
