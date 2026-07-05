import { PageHeader } from '@/components/ui/page-header';
import { SectionCard } from '@/components/ui/section-card';
import { cn } from '@/lib/utils';

/* ── Colour swatches ──────────────────────────────────────────────────────
   Each swatch fills with the design-token-backed `bg-*` utility directly so
   the guide stays honest: if a token drifts in globals.css the swatch follows.
   Class strings are kept literal so Tailwind's JIT can see them. */
interface ColorToken {
  name: string;
  bg: string;
  cssVar: string;
}

const SURFACE_TOKENS: ReadonlyArray<ColorToken> = [
  { name: 'background', bg: 'bg-background', cssVar: '--color-background' },
  { name: 'surface', bg: 'bg-surface', cssVar: '--color-surface' },
  { name: 'surface-raised', bg: 'bg-surface-raised', cssVar: '--color-surface-raised' },
  { name: 'muted', bg: 'bg-muted', cssVar: '--color-muted' },
  { name: 'border', bg: 'bg-border', cssVar: '--color-border' },
  { name: 'foreground', bg: 'bg-foreground', cssVar: '--color-foreground' },
  {
    name: 'foreground-secondary',
    bg: 'bg-foreground-secondary',
    cssVar: '--color-foreground-secondary',
  },
  {
    name: 'foreground-tertiary',
    bg: 'bg-foreground-tertiary',
    cssVar: '--color-foreground-tertiary',
  },
];

/* 상태 토큰 — 인앱 실사용은 풀채도 블록이 아니라 "bg-{token}/10 + text-{token}" 틴트 칩이다.
   가이드도 틴트 칩을 1차 스펙으로 보여주고, 풀채도 원색은 raw token 참조로 강등한다.
   (Tailwind JIT가 클래스를 인식하도록 문자열은 리터럴로 유지.) */
interface StatusToken extends ColorToken {
  /** 인앱 실사용 형태: /10 틴트 배경 + 본색 텍스트 */
  chip: string;
  /** 칩 안에 보여줄 실사용 라벨 예시 */
  sample: string;
}

const STATUS_TOKENS: ReadonlyArray<StatusToken> = [
  {
    name: 'accent',
    bg: 'bg-accent',
    chip: 'bg-accent/10 text-accent',
    sample: '진행 중',
    cssVar: '--color-accent',
  },
  {
    name: 'success',
    bg: 'bg-success',
    chip: 'bg-success/10 text-success',
    sample: '성공',
    cssVar: '--color-success',
  },
  {
    name: 'warning',
    bg: 'bg-warning',
    chip: 'bg-warning/10 text-warning',
    sample: '경고',
    cssVar: '--color-warning',
  },
  {
    name: 'danger',
    bg: 'bg-danger',
    chip: 'bg-danger/10 text-danger',
    sample: '오류',
    cssVar: '--color-danger',
  },
  {
    name: 'info',
    bg: 'bg-info',
    chip: 'bg-info/10 text-info',
    sample: '정보',
    cssVar: '--color-info',
  },
];

const SENTIMENT_TOKENS: ReadonlyArray<ColorToken> = [
  { name: 'sentiment-positive', bg: 'bg-sentiment-positive', cssVar: '--color-sentiment-positive' },
  { name: 'sentiment-neutral', bg: 'bg-sentiment-neutral', cssVar: '--color-sentiment-neutral' },
  { name: 'sentiment-negative', bg: 'bg-sentiment-negative', cssVar: '--color-sentiment-negative' },
  { name: 'sentiment-mixed', bg: 'bg-sentiment-mixed', cssVar: '--color-sentiment-mixed' },
];

/* 지식그래프 감정/추세선/토픽 공유 팔레트 — 분석 탭 --sentiment-* 와 분리 운용
   (긍정/언급 = teal, 부정/미언급 = rose). globals.css 주석 참조. */
const GRAPH_SENTIMENT_TOKENS: ReadonlyArray<ColorToken> = [
  {
    name: 'graph-sentiment-positive',
    bg: 'bg-graph-sentiment-positive',
    cssVar: '--color-graph-sentiment-positive',
  },
  {
    name: 'graph-sentiment-neutral',
    bg: 'bg-graph-sentiment-neutral',
    cssVar: '--color-graph-sentiment-neutral',
  },
  {
    name: 'graph-sentiment-negative',
    bg: 'bg-graph-sentiment-negative',
    cssVar: '--color-graph-sentiment-negative',
  },
  {
    name: 'graph-sentiment-mixed',
    bg: 'bg-graph-sentiment-mixed',
    cssVar: '--color-graph-sentiment-mixed',
  },
];

function Swatch({ name, bg, cssVar }: ColorToken) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span
        aria-hidden
        className={cn('border-border h-14 w-full rounded-[var(--radius-md)] border', bg)}
      />
      <span className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
        {name}
      </span>
      <span className="text-foreground-tertiary truncate font-mono text-[10px]">{cssVar}</span>
    </div>
  );
}

/** 상태 토큰 스와치 — 1차: 실사용 틴트 칩, 2차: raw 원색 스트립(참조용). */
function StatusSwatch({ name, bg, chip, sample, cssVar }: StatusToken) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span
        aria-hidden
        className={cn(
          'border-border flex h-14 w-full items-center justify-center rounded-[var(--radius-md)] border',
          chip,
        )}
      >
        <span className="text-[length:var(--text-body-sm)] font-semibold">{sample}</span>
      </span>
      {/* raw token(풀채도) — 배경 대면적 사용 금지, 텍스트·아이콘·틴트의 원료로만 */}
      <span aria-hidden className={cn('h-1.5 w-full rounded-full', bg)} />
      <span className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
        {name}
      </span>
      <span className="text-foreground-tertiary truncate font-mono text-[10px]">{cssVar}</span>
    </div>
  );
}

function SwatchGroup({ label, tokens }: { label: string; tokens: ReadonlyArray<ColorToken> }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
        {label}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {tokens.map((t) => (
          <Swatch key={t.name} {...t} />
        ))}
      </div>
    </div>
  );
}

export function ColorSection() {
  return (
    <SectionCard
      caption="토큰"
      title="의미 기반 팔레트"
      description="색상은 언제나 의미 토큰으로 사용합니다. oklch 색공간으로 정의되어 라이트/다크 두 테마에서 일관된 대비를 유지합니다."
      density="comfortable"
    >
      <SwatchGroup label="표면 · 텍스트 계열" tokens={SURFACE_TOKENS} />
      <div className="flex flex-col gap-3">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          액센트 · 상태 계열 — 실사용은 /10 틴트 칩
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {STATUS_TOKENS.map((t) => (
            <StatusSwatch key={t.name} {...t} />
          ))}
        </div>
        <p className="text-foreground-tertiary text-[length:var(--text-caption)]">
          상태색은 <code className="font-mono">bg-*/10 text-*</code> 틴트 형태가 1차 스펙입니다.
          풀채도 원색(아래 스트립)은 raw token으로, 대면적 배경에 직접 쓰지 않습니다.
        </p>
      </div>
      <SwatchGroup label="감정 데이터 팔레트 (분석 탭)" tokens={SENTIMENT_TOKENS} />
      <SwatchGroup
        label="그래프 감정 팔레트 (지식그래프 · 추세선 공유)"
        tokens={GRAPH_SENTIMENT_TOKENS}
      />
      <p className="text-muted-foreground border-border-subtle border-t pt-4 text-xs leading-relaxed">
        규칙 — 상태 색(accent/success/warning/danger/info)은 <strong>의미가 있을 때만</strong>{' '}
        사용하고, 데이터 시각화에는 채도를 낮춘 sentiment 계열을 씁니다. 컴포넌트에서 hex·oklch 값을
        직접 쓰지 마세요: 토큰을 우회하면 다크 테마에서 즉시 깨집니다.
      </p>
    </SectionCard>
  );
}

/* ── Typography scale ─────────────────────────────────────────────────────── */
interface TypeToken {
  name: string;
  cssVar: string;
  sample: string;
  cls: string;
  /** 어디에 쓰는 크기인지 — 한 줄 용도 규칙. */
  usage: string;
}

const TYPE_SCALE: ReadonlyArray<TypeToken> = [
  {
    name: 'hero',
    cssVar: '--text-hero',
    sample: 'Aa 안녕하세요',
    cls: 'text-[length:var(--text-hero)] font-semibold leading-none tracking-tight',
    usage: '인증 화면 · 랜딩의 단일 헤드라인 — 앱 내부에선 쓰지 않음',
  },
  {
    name: 'section',
    cssVar: '--text-section',
    sample: 'Aa 디자인 시스템',
    cls: 'text-[length:var(--text-section)] font-semibold tracking-tight',
    usage: '페이지 타이틀(h1) — PageHeader 가 소유',
  },
  {
    name: 'heading',
    cssVar: '--text-heading',
    sample: 'Aa 섹션 제목',
    cls: 'text-[length:var(--text-heading)] font-semibold',
    usage: '큰 카운터 · 강조 수치 헤더',
  },
  {
    name: 'heading-sm',
    cssVar: '--text-heading-sm',
    sample: 'Aa 서브 제목',
    cls: 'text-[length:var(--text-heading-sm)] font-semibold',
    usage: '카드 그룹 제목 · 다이얼로그 타이틀',
  },
  {
    name: 'body-lg',
    cssVar: '--text-body-lg',
    sample: '본문 16px — 여유로운 가독성',
    cls: 'text-[length:var(--text-body-lg)]',
    usage: '카드 타이틀(h3) · 읽기 중심 본문',
  },
  {
    name: 'body',
    cssVar: '--text-body',
    sample: '본문 14px — 대시보드 기본 크기',
    cls: 'text-[length:var(--text-body)]',
    usage: '기본 본문 — body 태그 기본값(14px)',
  },
  {
    name: 'body-sm',
    cssVar: '--text-body-sm',
    sample: '보조 정보 13px',
    cls: 'text-[length:var(--text-body-sm)]',
    usage: '테이블 본문 · 보조 설명',
  },
  {
    name: 'caption',
    cssVar: '--text-caption',
    sample: 'KICKER · 11PX',
    cls: 'text-[length:var(--text-caption)] font-medium uppercase tracking-[0.08em]',
    usage: '아이브로우(캡션) — uppercase + tracking 0.08em 고정 조합',
  },
];

export function TypographySection() {
  return (
    <SectionCard
      caption="토큰"
      title="타이포그래피 스케일"
      description="Pretendard(본문 · 한글) · Geist(숫자 · 영문 디스플레이). 본문 기본 14px, 섹션/히어로는 clamp() 반응형."
      density="comfortable"
    >
      <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
        {TYPE_SCALE.map((t) => (
          <div key={t.name} className="flex items-baseline gap-4 px-4 py-3.5">
            <span className="text-foreground-tertiary w-32 shrink-0 font-mono text-[11px]">
              {t.cssVar}
            </span>
            <span className={cn('min-w-0 flex-1 truncate', t.cls)}>{t.sample}</span>
            <span className="hidden shrink-0 flex-col items-end sm:flex">
              <span className="text-foreground-tertiary font-mono text-[11px]">{t.name}</span>
              <span className="text-foreground-tertiary max-w-[15rem] text-right text-[10px] leading-snug">
                {t.usage}
              </span>
            </span>
          </div>
        ))}
      </div>

      {/* 페이지 헤더 3단 구조 — 실제 PageHeader 컴포넌트 렌더(살아있는 문서) */}
      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          페이지 헤더 3단 구조 — 캡션 → 타이틀 → 설명
        </p>
        <div className="border-border bg-background rounded-[var(--radius-md)] border p-5">
          <PageHeader
            caption="캡션 · --text-caption uppercase"
            title="타이틀 · --text-section"
            description="설명 · text-sm text-muted-foreground max-w-2xl — 페이지가 무엇을 하는 곳인지 한두 문장."
          />
        </div>
        <p className="text-muted-foreground text-xs leading-relaxed">
          모든 페이지 상단은 이 3단(캡션 → 타이틀 → 설명)을 <strong>PageHeader 컴포넌트</strong>로
          조립합니다 — 페이지에서 h1 · 캡션을 직접 만들지 마세요. 우측 액션이 필요하면{' '}
          <code className="font-mono text-[11px]">action</code> 슬롯을 사용합니다.
        </p>
        <p className="text-muted-foreground text-xs leading-relaxed">
          <strong>예외 — (auth) 레이아웃</strong>: 로그인·회원가입은 사이드바 없는 별도 레이아웃(
          <code className="font-mono text-[11px]">max-w-md</code> 고정폭 카드)이라{' '}
          <code className="font-mono text-[11px]">PageHeader</code>를 쓰지 않습니다. 타이틀 토큰{' '}
          <code className="font-mono text-[11px]">--text-section</code>은 뷰포트 폭 기준 `clamp()`라
          대시보드의 넓은 캔버스에 맞춰져 있고, 고정폭 카드에선 큰 화면에서 카드 대비 제목이
          과도하게 커진다. 대신{' '}
          <code className="font-mono text-[11px]">(auth)/_components/auth-page-header.tsx</code>의
          전용 <code className="font-mono text-[11px]">AuthPageHeader</code>(고정 크기{' '}
          <code className="font-mono text-[11px]">--text-heading</code>)를 두 페이지가 공유한다.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="border-border bg-background flex flex-col gap-2 rounded-[var(--radius-md)] border p-4">
          <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
            font-sans · Pretendard
          </p>
          <p className="font-sans text-[length:var(--text-heading-sm)]">
            뚜렷한 정보 위계와 차분한 리듬 Aa 0123
          </p>
        </div>
        <div className="border-border bg-background flex flex-col gap-2 rounded-[var(--radius-md)] border p-4">
          <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
            font-display · Geist
          </p>
          <p className="font-display text-[length:var(--text-heading-sm)] tracking-tight">
            Editorial Display Aa 0123
          </p>
        </div>
      </div>
    </SectionCard>
  );
}

/* ── Radius ───────────────────────────────────────────────────────────────── */
const RADII = [
  { name: 'sm', cssVar: '--radius-sm', px: '4px', usage: '인풋 · 버튼 · 칩' },
  { name: 'md', cssVar: '--radius-md', px: '8px', usage: '배너 · 인라인 컨테이너' },
  { name: 'lg', cssVar: '--radius-lg', px: '12px', usage: '카드 · 다이얼로그' },
  { name: 'xl', cssVar: '--radius-xl', px: '16px', usage: '강조 블록' },
] as const;

export function RadiusSection() {
  return (
    <SectionCard caption="토큰" title="라운딩 스케일" density="comfortable">
      <div className="grid grid-cols-2 gap-3">
        {RADII.map((r) => (
          <div
            key={r.name}
            className="border-border bg-background flex flex-col gap-3 rounded-[var(--radius-md)] border p-4"
          >
            <span
              aria-hidden
              className="border-border-strong bg-muted h-14 w-full border"
              style={{ borderRadius: `var(${r.cssVar})` }}
            />
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium">{r.name}</span>
              <span className="text-foreground-tertiary font-mono text-[11px]">{r.px}</span>
            </div>
            <span className="text-muted-foreground text-xs">{r.usage}</span>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

/* ── Shadow ───────────────────────────────────────────────────────────────── */
const SHADOWS = [
  { name: 'card', cssVar: '--shadow-card', usage: '일반 카드' },
  { name: 'card-raised', cssVar: '--shadow-card-raised', usage: 'hover 승격' },
  { name: 'elevated', cssVar: '--shadow-elevated', usage: '팝오버 · 드롭다운' },
  { name: 'overlay', cssVar: '--shadow-overlay', usage: '다이얼로그' },
] as const;

export function ShadowSection() {
  return (
    <SectionCard
      caption="토큰"
      title="그림자 레벨"
      description="4단계 엘리베이션 — 낮은 단계에서 높은 단계로 hover 시 승격합니다."
      density="comfortable"
    >
      <div className="grid grid-cols-2 gap-4">
        {SHADOWS.map((s) => (
          <div
            key={s.name}
            className="bg-background flex flex-col items-center gap-3 rounded-[var(--radius-md)] p-5"
          >
            <span
              aria-hidden
              className="bg-surface h-16 w-full rounded-[var(--radius-md)]"
              style={{ boxShadow: `var(${s.cssVar})` }}
            />
            <div className="flex w-full items-baseline justify-between gap-2">
              <span className="text-sm font-medium">{s.name}</span>
              <span className="text-foreground-tertiary font-mono text-[10px]">{s.usage}</span>
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
