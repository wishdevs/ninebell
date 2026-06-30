import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { ACTIVE_WORKSPACE } from '@/lib/data/workspace';
import { HOME_ALERTS, getModuleInsights } from '@/lib/data/home';
import { ModuleInsightsGrid } from './_components/module-insights-grid';
import { WelcomeAlertFeed } from './_components/welcome-alert-feed';

export const metadata: Metadata = {
  title: '개요',
};

/**
 * 대시보드 홈(개요). 상단은 조치가 필요한 고-신호 알림 피드, 하단은 활성 모듈별
 * 요약 Bento. 인터랙션이 없는 순수 표시 화면이라 전체를 서버 컴포넌트로 둔다.
 */
export default function HomePage() {
  const insights = getModuleInsights(ACTIVE_WORKSPACE.enabledModules);

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption={ACTIVE_WORKSPACE.name}
        title="안녕하세요"
        description="확인이 필요한 항목과 모듈 요약입니다. 좌측 사이드바에서 모듈을 직접 열 수도 있습니다."
      />
      <WelcomeAlertFeed alerts={HOME_ALERTS} />
      <ModuleInsightsGrid insights={insights} />
    </div>
  );
}
