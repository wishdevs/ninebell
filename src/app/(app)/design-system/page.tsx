import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { SectionCard } from '@/components/ui/section-card';
import {
  BadgeShowcaseSection,
  ButtonShowcaseSection,
  EmptyShowcaseSection,
  TableLoadingSection,
} from './_components/component-sections';
import { DepthSection, MotionSection } from './_components/depth-motion-sections';
import { PrefillSkillSection, RunLifecycleSection } from './_components/domain-vocab-sections';
import { InteractiveDemos } from './_components/interactive-demos';
import { DesignSystemToc } from './_components/toc';
import {
  ColorSection,
  RadiusSection,
  ShadowSection,
  TypographySection,
} from './_components/token-sections';
import { VoiceToneSection } from './_components/voice-tone-section';

export const metadata: Metadata = {
  title: '디자인 시스템',
};

/** 앵커 래퍼 — 목차(toc.tsx TOC_ITEMS)와 id 를 1:1 로 맞춘다. */
function Anchor({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <div id={id} className="flex scroll-mt-6 flex-col gap-8">
      {children}
    </div>
  );
}

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

      <DesignSystemToc />

      <Anchor id="colors">
        <ColorSection />
      </Anchor>

      <Anchor id="typography">
        <TypographySection />
      </Anchor>

      <Anchor id="depth">
        <DepthSection />
      </Anchor>

      <Anchor id="radius-shadow">
        <div className="grid gap-8 lg:grid-cols-2">
          <RadiusSection />
          <ShadowSection />
        </div>
      </Anchor>

      <Anchor id="motion">
        <MotionSection />
      </Anchor>

      <Anchor id="buttons">
        <ButtonShowcaseSection />
      </Anchor>

      <Anchor id="badges">
        <BadgeShowcaseSection />
      </Anchor>

      <Anchor id="domain-vocab">
        <RunLifecycleSection />
        <PrefillSkillSection />
      </Anchor>

      <Anchor id="empty">
        <EmptyShowcaseSection />
      </Anchor>

      <Anchor id="table-loading">
        <TableLoadingSection />
        <SectionCard
          caption="레퍼런스"
          title="테이블 패턴"
          description="새 데모를 만들지 않고 이미 구현된 화면을 그대로 참조합니다."
          density="comfortable"
        >
          <div className="text-foreground-secondary flex flex-col gap-3 text-[length:var(--text-body-sm)] leading-relaxed">
            <p>
              <span className="text-foreground font-semibold">Sticky 헤더 테이블</span> —
              헤더 행에 <span className="font-mono text-xs">sticky top-0 z-10</span>, 스크롤
              컨테이너에 <span className="font-mono text-xs">max-h-[520px] overflow-y-auto</span>를
              적용해 긴 목록에서도 컬럼 라벨이 항상 보이게 한다. 참고 구현:{' '}
              <span className="font-mono text-xs">code-catalog-manager.tsx</span>.
            </p>
            <p>
              <span className="text-foreground font-semibold">셀 내 인라인 Select · Popover 행 메뉴</span>{' '}
              — 테이블 셀 안에서 바로 값을 바꾸는 인라인 Select와, 행 끝의 케밥 버튼에서 여는 Popover
              기반 행 액션 메뉴 조합. 참고 구현:{' '}
              <span className="font-mono text-xs">members-table.tsx</span> /{' '}
              <span className="font-mono text-xs">member-row-actions.tsx</span>.
            </p>
          </div>
        </SectionCard>
      </Anchor>

      <Anchor id="forms">
        <SectionCard
          caption="인터랙션"
          title="폼 컨트롤 · 탭"
          description="상태를 가진 컴포넌트 데모입니다. 클라이언트 컴포넌트(_components/interactive-demos.tsx)로 분리되어 page.tsx 는 서버 컴포넌트로 유지됩니다."
          density="comfortable"
        >
          <InteractiveDemos />
        </SectionCard>
      </Anchor>

      <Anchor id="voice">
        <VoiceToneSection />
      </Anchor>
    </div>
  );
}
