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
  { name: 'foreground-secondary', bg: 'bg-foreground-secondary', cssVar: '--color-foreground-secondary' },
  { name: 'foreground-tertiary', bg: 'bg-foreground-tertiary', cssVar: '--color-foreground-tertiary' },
];

const ACCENT_TOKENS: ReadonlyArray<ColorToken> = [
  { name: 'accent', bg: 'bg-accent', cssVar: '--color-accent' },
  { name: 'success', bg: 'bg-success', cssVar: '--color-success' },
  { name: 'warning', bg: 'bg-warning', cssVar: '--color-warning' },
  { name: 'danger', bg: 'bg-danger', cssVar: '--color-danger' },
  { name: 'info', bg: 'bg-info', cssVar: '--color-info' },
];

const SENTIMENT_TOKENS: ReadonlyArray<ColorToken> = [
  { name: 'sentiment-positive', bg: 'bg-sentiment-positive', cssVar: '--color-sentiment-positive' },
  { name: 'sentiment-neutral', bg: 'bg-sentiment-neutral', cssVar: '--color-sentiment-neutral' },
  { name: 'sentiment-negative', bg: 'bg-sentiment-negative', cssVar: '--color-sentiment-negative' },
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
      <SwatchGroup label="액센트 · 상태 계열" tokens={ACCENT_TOKENS} />
      <SwatchGroup label="감정 데이터 팔레트" tokens={SENTIMENT_TOKENS} />
    </SectionCard>
  );
}

/* ── Typography scale ─────────────────────────────────────────────────────── */
interface TypeToken {
  name: string;
  cssVar: string;
  sample: string;
  cls: string;
}

const TYPE_SCALE: ReadonlyArray<TypeToken> = [
  {
    name: 'hero',
    cssVar: '--text-hero',
    sample: 'Aa 안녕하세요',
    cls: 'text-[length:var(--text-hero)] font-semibold leading-none tracking-tight',
  },
  {
    name: 'section',
    cssVar: '--text-section',
    sample: 'Aa 디자인 시스템',
    cls: 'text-[length:var(--text-section)] font-semibold tracking-tight',
  },
  {
    name: 'heading',
    cssVar: '--text-heading',
    sample: 'Aa 섹션 제목',
    cls: 'text-[length:var(--text-heading)] font-semibold',
  },
  {
    name: 'heading-sm',
    cssVar: '--text-heading-sm',
    sample: 'Aa 서브 제목',
    cls: 'text-[length:var(--text-heading-sm)] font-semibold',
  },
  {
    name: 'body-lg',
    cssVar: '--text-body-lg',
    sample: '본문 16px — 여유로운 가독성',
    cls: 'text-[length:var(--text-body-lg)]',
  },
  {
    name: 'body',
    cssVar: '--text-body',
    sample: '본문 14px — 대시보드 기본 크기',
    cls: 'text-[length:var(--text-body)]',
  },
  {
    name: 'body-sm',
    cssVar: '--text-body-sm',
    sample: '보조 정보 13px',
    cls: 'text-[length:var(--text-body-sm)]',
  },
  {
    name: 'caption',
    cssVar: '--text-caption',
    sample: 'KICKER · 11PX',
    cls: 'text-[length:var(--text-caption)] font-medium uppercase tracking-[0.08em]',
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
            <span className="text-foreground-tertiary shrink-0 font-mono text-[11px]">{t.name}</span>
          </div>
        ))}
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
