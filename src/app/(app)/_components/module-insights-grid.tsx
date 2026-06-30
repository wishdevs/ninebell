import { BentoCell, BentoGrid } from '@/components/ui/bento-grid';
import { EmptyState } from '@/components/ui/empty-state';
import type { ModuleInsight } from '@/lib/data/home';
import { InsightCardGa } from './insight-card-ga';
import { InsightCardGeo } from './insight-card-geo';
import { InsightCardMonitoring } from './insight-card-monitoring';
import { InsightCardPlaybook } from './insight-card-playbook';
import { InsightCardWorks } from './insight-card-works';

interface ModuleInsightsGridProps {
  insights: readonly ModuleInsight[];
}

/**
 * 모듈별 Bento. 카드마다 데이터 형태가 다르며(스파크라인 / 4지표 스트립 / 버전 핀)
 * `module` 필드로 판별되는 유니온이라 TypeScript가 각 카드에 맞는 페이로드를 보장한다.
 *
 * lg 브레이크포인트 레이아웃:
 * - GEO + 업무가 1행을 나눠 가짐 (6 + 6)
 * - GA + 모니터링이 2행을 나눠 가짐 (6 + 6)
 * - 플레이북이 3행 전체를 차지 (12) — 더 넓은 힌트 + 버전 핀
 *
 * lg 미만에서는 모든 셀이 세로로 쌓인다. 비활성 모듈은 상위 `getModuleInsights(enabled)`
 * 에서 이미 걸러지므로 이 레이아웃은 항상 이동 가능한 모듈만 렌더한다.
 */
export function ModuleInsightsGrid({ insights }: ModuleInsightsGridProps) {
  if (insights.length === 0) {
    return (
      <EmptyState
        title="활성화된 모듈이 없습니다"
        description="조직 설정 → 사용 모듈에서 사용할 모듈을 활성화하면 이 영역에 모듈별 요약이 표시됩니다."
        compact
      />
    );
  }

  return (
    <BentoGrid>
      {insights.map((insight) => (
        <BentoCell key={insight.module} span={insight.module === 'playbook' ? 12 : 6}>
          {renderInsightCard(insight)}
        </BentoCell>
      ))}
    </BentoGrid>
  );
}

function renderInsightCard(insight: ModuleInsight) {
  switch (insight.module) {
    case 'geo':
      return <InsightCardGeo data={insight} />;
    case 'work':
      return <InsightCardWorks data={insight} />;
    case 'ga':
      return <InsightCardGa data={insight} />;
    case 'monitoring':
      return <InsightCardMonitoring data={insight} />;
    case 'playbook':
      return <InsightCardPlaybook data={insight} />;
  }
}
