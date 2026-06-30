import {
  RiInboxLine,
  RiInformationLine,
  RiPaletteLine,
  RiAddLine,
  RiSearchLine,
  RiDeleteBinLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Chip } from '@/components/ui/chip-set';
import { EmptyHint } from '@/components/ui/empty-hint';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { SentimentBadge } from '@/components/ui/sentiment-badge';
import { StatusBadge } from '@/components/ui/status-badge';
import { StatusDotPill, StatusPill } from '@/components/ui/status-pill';
import { Showcase } from './showcase';

export function ButtonShowcaseSection() {
  return (
    <SectionCard
      caption="컴포넌트"
      title="버튼"
      description="4 variant × 3 size 매트릭스. rounded-sm · primary/danger 는 hover halo 와 active scale 마이크로 인터랙션을 가집니다. 파괴적 액션은 반드시 danger variant 를 사용합니다."
      density="comfortable"
    >
      <Showcase label="작게 · sm">
        <Button size="sm">Primary</Button>
        <Button size="sm" variant="secondary">
          Secondary
        </Button>
        <Button size="sm" variant="ghost">
          Ghost
        </Button>
        <Button size="sm" variant="danger">
          Danger
        </Button>
      </Showcase>

      <Showcase label="보통 · md">
        <Button>Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
        <Button size="icon" aria-label="아이콘 버튼">
          <RiPaletteLine size={16} />
        </Button>
      </Showcase>

      <Showcase label="크게 · lg">
        <Button size="lg">Primary</Button>
        <Button size="lg" variant="secondary">
          Secondary
        </Button>
        <Button size="lg" variant="ghost">
          Ghost
        </Button>
        <Button size="lg" variant="danger">
          Danger
        </Button>
      </Showcase>

      <Showcase label="아이콘 조합 · 비활성">
        <Button size="sm">
          <RiAddLine size={14} /> 새로 만들기
        </Button>
        <Button size="sm" variant="secondary">
          <RiInformationLine size={14} /> 자세히
        </Button>
        <Button size="sm" variant="danger">
          <RiDeleteBinLine size={14} /> 삭제
        </Button>
        <Button disabled>비활성</Button>
        <Button variant="secondary" disabled>
          비활성
        </Button>
      </Showcase>
    </SectionCard>
  );
}

export function BadgeShowcaseSection() {
  return (
    <SectionCard
      caption="컴포넌트"
      title="배지 · 상태 · 칩"
      description="실행 라이프사이클은 StatusBadge, 임시 안내·경고는 StatusPill, 불리언 상태는 StatusDotPill, 감정 분석은 SentimentBadge 로 어휘를 분리합니다."
      density="comfortable"
    >
      <Showcase label="상태 배지 · StatusBadge">
        <StatusBadge status="completed" />
        <StatusBadge status="running" isRunning completedRuns={3} totalRuns={5} />
        <StatusBadge status="failed" />
        <StatusBadge status="pending" />
      </Showcase>

      <Showcase label="상태 Pill · StatusPill">
        <StatusPill variant="warn" label="검수 대기" />
        <StatusPill variant="info" label="동기화 예약" />
        <StatusPill variant="success" label="게시됨" />
        <StatusPill variant="danger" label="연결 끊김" />
      </Showcase>

      <Showcase label="On/Off · StatusDotPill">
        <StatusDotPill active />
        <StatusDotPill active={false} />
      </Showcase>

      <Showcase label="감정 · SentimentBadge">
        <SentimentBadge sentiment="positive" />
        <SentimentBadge sentiment="neutral" />
        <SentimentBadge sentiment="negative" />
      </Showcase>

      <Showcase label="칩 · Chip">
        <Chip>기획</Chip>
        <Chip shape="badge">디자인</Chip>
        <Chip>프론트엔드</Chip>
        <Chip dashed>카테고리 없음</Chip>
      </Showcase>
    </SectionCard>
  );
}

export function EmptyShowcaseSection() {
  return (
    <SectionCard
      caption="컴포넌트"
      title="빈 상태"
      description="규모에 따라 세 단계로 사용합니다. 페이지·섹션은 EmptyState, 사이드 패널·하위 카드는 EmptyHint."
      density="comfortable"
    >
      <div className="grid items-start gap-5 md:grid-cols-2">
        <EmptyState
          icon={<RiSearchLine size={18} aria-hidden />}
          title="조건에 맞는 결과가 없습니다"
          description="필터를 완화하거나 새 항목을 추가해 시작하세요."
          action={
            <Button variant="secondary" size="sm">
              <RiAddLine size={14} /> 새로 만들기
            </Button>
          }
        />
        <EmptyHint
          icon={<RiInboxLine size={14} aria-hidden />}
          title="알림 없음"
          description="새 활동이 도착하면 이곳에 표시됩니다."
        />
      </div>
    </SectionCard>
  );
}
