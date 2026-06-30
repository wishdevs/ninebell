'use client';

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { DEVICES } from '@/lib/data/analytics';
import { formatInteger } from '@/lib/data/format';

const DEVICE_COLORS = [
  'oklch(62% 0.18 250)',
  'oklch(70% 0.15 200)',
  'oklch(75% 0.15 140)',
] as const;

/** 디바이스 카테고리별 세션 — 도넛 + 범례. */
export function DevicesChart() {
  const data = [...DEVICES];
  const total = data.reduce((sum, d) => sum + d.sessions, 0);

  return (
    <div className="grid grid-cols-[1fr] items-center gap-4 sm:grid-cols-[160px_1fr]">
      <div className="relative mx-auto h-[160px] w-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="sessions"
              nameKey="device"
              innerRadius={48}
              outerRadius={72}
              paddingAngle={2}
              stroke="var(--surface)"
              strokeWidth={2}
            >
              {data.map((d, i) => (
                <Cell key={d.device} fill={DEVICE_COLORS[i % DEVICE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                fontSize: 12,
                color: 'var(--foreground)',
              }}
              formatter={(value: number) => formatInteger(value)}
            />
          </PieChart>
        </ResponsiveContainer>
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"
        >
          <span className="text-foreground-tertiary text-[10px] tracking-[0.08em] uppercase">
            총 세션
          </span>
          <span className="font-display text-base font-semibold tabular-nums">
            {formatInteger(total)}
          </span>
        </div>
      </div>

      <ul className="grid gap-2.5 self-center text-xs">
        {data.map((d, i) => (
          <li key={d.device} className="flex items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: DEVICE_COLORS[i % DEVICE_COLORS.length] }}
              />
              <span className="text-foreground truncate">{d.device}</span>
            </span>
            <span className="tabular-nums">
              <span className="text-foreground font-medium">{d.share.toFixed(1)}%</span>
              <span className="text-foreground-tertiary ml-2">{formatInteger(d.sessions)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
