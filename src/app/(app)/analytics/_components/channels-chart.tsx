'use client';

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { CHANNELS } from '@/lib/data/analytics';
import { formatInteger } from '@/lib/data/format';

/** 채널별 막대 색 — 점유율 순서대로 안정적으로 배정. */
const BAR_COLORS = [
  'oklch(62% 0.18 250)',
  'oklch(70% 0.15 200)',
  'oklch(72% 0.18 320)',
  'oklch(75% 0.15 140)',
  'oklch(72% 0.15 90)',
  'oklch(68% 0.2 30)',
] as const;

/** 채널별 세션 — 가로 막대 차트(layout="vertical"). */
export function ChannelsChart() {
  const data = [...CHANNELS];
  return (
    <ResponsiveContainer width="100%" height={232}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
        barCategoryGap={10}
      >
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="channel"
          width={72}
          tick={{ fontSize: 12, fill: 'var(--foreground-secondary)' }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          cursor={{ fill: 'var(--muted)', opacity: 0.5 }}
          contentStyle={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            fontSize: 12,
            color: 'var(--foreground)',
          }}
          formatter={(value: number) => [formatInteger(value), '세션']}
        />
        <Bar dataKey="sessions" radius={[0, 4, 4, 0]} maxBarSize={22}>
          {data.map((entry, i) => (
            <Cell key={entry.channel} fill={BAR_COLORS[i % BAR_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
