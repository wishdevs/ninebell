import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { SectionCard } from '@/components/ui/section-card';
import {
  BadgeShowcaseSection,
  ButtonShowcaseSection,
  EmptyShowcaseSection,
} from './_components/component-sections';
import { InteractiveDemos } from './_components/interactive-demos';
import {
  ColorSection,
  RadiusSection,
  ShadowSection,
  TypographySection,
} from './_components/token-sections';

export const metadata: Metadata = {
  title: '디자인 시스템',
};

export default function DesignSystemPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="스타일 가이드"
        title="디자인 시스템"
        description={
          <>
            NINEBELL의 시각 언어 · 컴포넌트 표준. 모든 토큰은{' '}
            <span className="font-mono text-xs">globals.css</span>에 정의되며 라이트/다크를 동시에
            지원합니다. 우측 상단 사용자 메뉴의 테마 토글로 두 테마를 확인하세요.
          </>
        }
      />

      <ColorSection />
      <TypographySection />

      <div className="grid gap-8 lg:grid-cols-2">
        <RadiusSection />
        <ShadowSection />
      </div>

      <ButtonShowcaseSection />
      <BadgeShowcaseSection />
      <EmptyShowcaseSection />

      <SectionCard
        caption="인터랙션"
        title="폼 컨트롤 · 탭"
        description="상태를 가진 컴포넌트 데모입니다. 클라이언트 컴포넌트(_components/interactive-demos.tsx)로 분리되어 page.tsx 는 서버 컴포넌트로 유지됩니다."
        density="comfortable"
      >
        <InteractiveDemos />
      </SectionCard>
    </div>
  );
}
