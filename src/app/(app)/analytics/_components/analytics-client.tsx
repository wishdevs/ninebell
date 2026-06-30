'use client';

import { useState } from 'react';
import { PageHeader } from '@/components/ui/page-header';
import { SectionCard } from '@/components/ui/section-card';
import type { AnalyticsRange } from '@/lib/data/analytics';
import { ChannelsChart } from './channels-chart';
import { DevicesChart } from './devices-chart';
import { KpiCards } from './kpi-cards';
import { RangeSegment } from './range-segment';
import { TopPagesTable } from './top-pages-table';
import { TrafficTrendChart } from './traffic-trend-chart';

/**
 * 애널리틱스 대시보드 본문. 기간 세그먼트(7d/28d/90d)는 시각적 활성 상태만
 * 토글한다 — 더미데이터는 정적이라 기본형에서는 데이터를 재계산하지 않는다.
 */
export function AnalyticsClient() {
  const [range, setRange] = useState<AnalyticsRange>('28d');

  return (
    <div className="flex max-w-[var(--content-max)] flex-col gap-8 pb-16">
      <PageHeader
        caption="대시보드"
        title="애널리틱스"
        description="웹사이트 트래픽과 사용자 참여를 한눈에. 기간을 바꿔 추세를 비교하세요."
        action={<RangeSegment value={range} onChange={setRange} />}
      />

      <KpiCards />

      <SectionCard caption="트래픽 추이" title="일별 활성 사용자 · 세션">
        <TrafficTrendChart />
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard caption="유입" title="채널별 세션">
          <ChannelsChart />
        </SectionCard>
        <SectionCard caption="디바이스" title="카테고리별 세션">
          <DevicesChart />
        </SectionCard>
      </div>

      <SectionCard caption="콘텐츠" title="인기 페이지" description="조회수 기준 상위 페이지">
        <TopPagesTable />
      </SectionCard>
    </div>
  );
}
