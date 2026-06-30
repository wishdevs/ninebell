'use client';

import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { TRAFFIC_TREND } from '@/lib/data/analytics';
import { formatInteger } from '@/lib/data/format';

const SERIES = [
  { key: 'activeUsers', label: '활성 사용자', color: 'oklch(62% 0.18 250)' },
  { key: 'sessions', label: '세션', color: 'oklch(70% 0.15 200)' },
] as const;

function labelOf(key: string): string {
  return SERIES.find((s) => s.key === key)?.label ?? key;
}

/** `YYYY-MM-DD` → `M/D` (축 틱). */
function monthDay(iso: string): string {
  const [, mm, dd] = iso.split('-');
  return `${Number(mm)}/${Number(dd)}`;
}

/** `YYYY-MM-DD` → `2026년 6월 1일` (툴팁 라벨). */
function fullDate(iso: string): string {
  const [yyyy, mm, dd] = iso.split('-');
  return `${yyyy}년 ${Number(mm)}월 ${Number(dd)}일`;
}

/** 일별 활성 사용자 · 세션 추이 영역 차트. */
export function TrafficTrendChart() {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={[...TRAFFIC_TREND]} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <defs>
          {SERIES.map((s) => (
            <linearGradient key={s.key} id={`trend-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.32} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="date"
          tickFormatter={monthDay}
          tick={{ fontSize: 11, fill: 'var(--foreground-tertiary)' }}
          axisLine={{ stroke: 'var(--border)' }}
          tickLine={false}
          minTickGap={24}
        />
        <YAxis
          tickFormatter={(v: number) => formatInteger(v)}
          tick={{ fontSize: 11, fill: 'var(--foreground-tertiary)' }}
          axisLine={false}
          tickLine={false}
          width={48}
        />
        <Tooltip
          contentStyle={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            fontSize: 12,
            color: 'var(--foreground)',
          }}
          formatter={(value: number, name: string) => [formatInteger(value), labelOf(name)]}
          labelFormatter={fullDate}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
          formatter={(name: string) => labelOf(name)}
        />
        {SERIES.map((s) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.key}
            stroke={s.color}
            strokeWidth={2}
            fill={`url(#trend-${s.key})`}
            dot={false}
            activeDot={{ r: 3, strokeWidth: 0 }}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
