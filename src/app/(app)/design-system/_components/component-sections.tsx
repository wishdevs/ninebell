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
import { EmptyNote } from '@/components/ui/empty-note';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { SentimentBadge } from '@/components/ui/sentiment-badge';
import { Spinner } from '@/components/ui/spinner';
import { StatusBadge } from '@/components/ui/status-badge';
import { StatusDotPill, StatusPill } from '@/components/ui/status-pill';
import { Td, Th } from '@/components/ui/table-cell';
import { Showcase, Snippet } from './showcase';

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

      <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
        {(
          [
            ['primary', '화면당 원칙적으로 1개 — 가장 중요한 다음 행동'],
            ['secondary', '보조 행동 · 취소 · 필터 등 대부분의 버튼'],
            ['ghost', '툴바 · 테이블 행처럼 시각 소음을 줄여야 하는 곳'],
            ['danger', '파괴적 액션 전용(삭제 · 종료) — 확인 다이얼로그와 함께'],
          ] as const
        ).map(([variant, usage]) => (
          <div key={variant} className="flex items-baseline gap-4 px-4 py-2.5">
            <span className="w-24 shrink-0 font-mono text-[11px]">{variant}</span>
            <span className="text-muted-foreground min-w-0 text-[13px]">{usage}</span>
          </div>
        ))}
      </div>

      <Snippet
        code={`import { Button } from '@/components/ui/button'; // <Button variant="secondary" size="sm">…</Button>`}
      />
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
      <Showcase label="상태 배지 · StatusBadge — 배치/런 라이프사이클 어휘 전체(7종)">
        <StatusBadge status="completed" />
        <StatusBadge status="running" isRunning completedRuns={3} totalRuns={5} />
        <StatusBadge status="failed" />
        <StatusBadge status="cancelled" />
        <StatusBadge status="pending" />
        <StatusBadge status="paused" />
        <StatusBadge status="batch_submitted" />
        <StatusBadge status="completed" size="md" />
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

      <Snippet code="import { StatusBadge } from '@/components/ui/status-badge'; // 라이프사이클 — StatusPill 은 임시 안내 전용" />
    </SectionCard>
  );
}

export function EmptyShowcaseSection() {
  return (
    <SectionCard
      caption="컴포넌트"
      title="빈 상태"
      description="규모에 따라 단계로 사용합니다. 페이지·섹션은 EmptyState(가능하면 action 으로 다음 행동 제공), 사이드 패널·하위 카드는 EmptyHint, 인라인 리스트·패널 내부의 가벼운 안내는 EmptyNote, 테이블 셀 단위 결측은 '—' 대시 하나."
      density="comfortable"
    >
      <div className="grid items-start gap-5 md:grid-cols-3">
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
        <div className="border-border-subtle bg-surface rounded-[var(--radius-md)] border p-4">
          <EmptyNote>아직 로그가 없습니다.</EmptyNote>
        </div>
      </div>
    </SectionCard>
  );
}

/* ── 테이블 · 로딩 ────────────────────────────────────────────────────
   관리 테이블 공용 규격(Th/Td)과 로딩 어휘(Spinner). 셀 결측은 '—',
   숫자 열은 tabular-nums + 우측 정렬, 행 hover 는 .row-hover 클래스. */

const TABLE_ROWS = [
  { name: '결의서입력-카드', runs: 128, avg: '2분 34초', status: 'completed' },
  { name: '전표 승인', runs: 42, avg: '58초', status: 'running' },
  { name: '증빙 수집', runs: 7, avg: '—', status: 'failed' },
] as const;

export function TableLoadingSection() {
  return (
    <SectionCard
      caption="컴포넌트"
      title="테이블 · 로딩"
      description="관리 테이블은 공용 Th/Td(패딩·정렬 규격 단일 소유)로 만듭니다. 숫자 열은 tabular-nums + 우측 정렬, 행 hover 는 .row-hover, 셀 결측은 '—' 하나."
      density="comfortable"
    >
      <div className="border-border bg-background overflow-x-auto rounded-[var(--radius-md)] border">
        <table className="w-full text-[length:var(--text-body-sm)]">
          <thead>
            <tr className="text-foreground-tertiary text-left">
              <Th>에이전트</Th>
              <Th className="text-right">실행 수</Th>
              <Th className="text-right">평균 소요</Th>
              <Th>상태</Th>
            </tr>
          </thead>
          <tbody>
            {TABLE_ROWS.map((row) => (
              <tr key={row.name} className="row-hover border-border/60 border-t">
                <Td className="text-foreground font-medium">{row.name}</Td>
                <Td className="text-right tabular-nums">{row.runs}</Td>
                <Td className="text-foreground-secondary text-right tabular-nums">{row.avg}</Td>
                <Td>
                  <StatusBadge status={row.status} />
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Showcase label="스피너 · Spinner — label 이 있으면 role=status, 없으면 aria-hidden(인접 텍스트가 상태를 설명할 때)">
        <Spinner size={14} label="불러오는 중" />
        <Spinner size={20} label="크게 · 페이지 로딩" />
        <span className="text-muted-foreground flex items-center gap-1.5 text-sm">
          <Spinner size={14} /> 저장 중… (텍스트가 설명 — label 생략)
        </span>
      </Showcase>

      <Snippet code="import { Td, Th } from '@/components/ui/table-cell'; // 패딩·정렬 규격을 복제하지 말 것" />
    </SectionCard>
  );
}
