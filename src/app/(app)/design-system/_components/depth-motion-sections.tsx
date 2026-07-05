import { SectionCard } from '@/components/ui/section-card';
import { DoDont } from './showcase';

/* ── 깊이 · 레이어링 ──────────────────────────────────────────────────
   최근 깊이 처방: 캔버스 `--background` 를 surface(100%)보다 톤 다운해
   (라이트 기준 95.5% 그레이) 흰 카드가 실제로 떠 보이게 한다. 카드는
   보더 + 낮은 그림자를 "병용" — 그림자는 보더의 대체재가 아니다. */

const LAYERS = [
  {
    token: 'bg-background',
    role: '캔버스',
    rule: '페이지 배경 · 카드 내부의 한 단계 낮은 우물(showcase · 코드블록)',
  },
  {
    token: 'bg-surface',
    role: '카드 표면',
    rule: '항상 border-border + shadow-card 병용 · radius-lg',
  },
  {
    token: 'bg-surface-raised',
    role: '승격 표면',
    rule: '행 hover(.row-hover) · 카드 내부의 한 단계 높은 층',
  },
] as const;

export function DepthSection() {
  return (
    <SectionCard
      caption="규칙"
      title="깊이 · 레이어링"
      description="캔버스(bg-background)는 surface보다 톤 다운되어 있어 카드가 실제로 떠 보입니다. 카드 표면은 보더와 그림자를 항상 함께 사용합니다 — 다크 테마에서 그림자가 거의 사라지므로 보더가 형태를 지키고, 그림자는 높이만 더합니다."
      density="comfortable"
    >
      {/* 살아있는 3층 데모 — 캔버스 → surface 카드 → 내부 우물 */}
      <div className="border-border bg-background rounded-[var(--radius-md)] border p-5">
        <p className="text-foreground-tertiary mb-3 font-mono text-[11px]">
          캔버스 · bg-background
        </p>
        <div className="border-border bg-surface rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)]">
          <p className="text-foreground-tertiary mb-3 font-mono text-[11px]">
            카드 · bg-surface + border + shadow-card
          </p>
          <div className="border-border bg-background rounded-[var(--radius-md)] border p-4">
            <p className="text-foreground-tertiary font-mono text-[11px]">
              내부 우물 · bg-background (한 단계 아래로)
            </p>
          </div>
        </div>
      </div>

      <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
        {LAYERS.map((l) => (
          <div key={l.token} className="flex items-baseline gap-4 px-4 py-3">
            <span className="text-foreground w-40 shrink-0 font-mono text-[11px]">{l.token}</span>
            <span className="text-foreground w-20 shrink-0 text-[13px] font-medium">{l.role}</span>
            <span className="text-muted-foreground min-w-0 text-[13px]">{l.rule}</span>
          </div>
        ))}
      </div>

      <DoDont
        doItems={[
          <>
            카드는 <code className="font-mono text-[11px]">bg-surface</code> +{' '}
            <code className="font-mono text-[11px]">border-border</code> +{' '}
            <code className="font-mono text-[11px]">shadow-[var(--shadow-card)]</code> 세 가지를
            함께 — SectionCard 가 이 조합을 소유합니다.
          </>,
          <>
            클릭 가능한 카드의 hover 승격은{' '}
            <code className="font-mono text-[11px]">.card-interactive</code>(translateY(-2px) +
            shadow-card-raised) 하나로 통일합니다.
          </>,
          '팝오버·드롭다운은 shadow-elevated, 다이얼로그는 shadow-overlay — 높이 사다리를 건너뛰지 않습니다.',
        ]}
        dontItems={[
          '그림자만으로 카드 경계를 표현 — 다크 테마에서 그림자가 소실되어 형태가 무너집니다.',
          '보더만 있는 평면 카드 위에 또 평면 카드 — 층이 구분되지 않으면 bg-background 우물로 내려가거나 surface-raised 로 올립니다.',
          '컴포넌트마다 임의의 box-shadow 값 — 반드시 4단계 --shadow-* 토큰만 사용합니다.',
        ]}
      />
    </SectionCard>
  );
}

/* ── 모션 ────────────────────────────────────────────────────────────── */

const MOTION_TOKENS = [
  { token: '--duration-fast', value: '150ms', usage: '색 · 보더 · 배경 전환(hover tint)' },
  { token: '--duration-normal', value: '200ms', usage: '트랜스폼 · 그림자 · 페이지 등장' },
  {
    token: '--ease-out',
    value: 'cubic-bezier(0.16, 1, 0.3, 1)',
    usage: '모든 등장/승격 — 빠르게 출발해 부드럽게 정지',
  },
] as const;

export function MotionSection() {
  return (
    <SectionCard
      caption="토큰 · 규칙"
      title="모션"
      description="움직임은 흐름을 설명할 때만 씁니다. 애니메이션은 컴포지터 속성(transform · opacity)에 한정하고, 지속시간·이징은 반드시 토큰을 사용합니다. prefers-reduced-motion 은 globals.css 전역 블록이 일괄 차단합니다."
      density="comfortable"
    >
      <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
        {MOTION_TOKENS.map((m) => (
          <div key={m.token} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3">
            <span className="text-foreground w-40 shrink-0 font-mono text-[11px]">{m.token}</span>
            <span className="text-foreground-tertiary w-56 shrink-0 font-mono text-[11px]">
              {m.value}
            </span>
            <span className="text-muted-foreground min-w-0 text-[13px]">{m.usage}</span>
          </div>
        ))}
      </div>

      {/* 살아있는 데모 — hover 시 fast/normal 지속시간 비교 (transform 만 사용) */}
      <div className="group border-border bg-background flex flex-col gap-4 rounded-[var(--radius-md)] border p-5">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          hover 해 보세요 — 지속시간 비교 (transform 전용)
        </p>
        <div className="flex items-center gap-3">
          <span className="text-foreground-tertiary w-32 shrink-0 font-mono text-[11px]">
            fast · 150ms
          </span>
          <span
            aria-hidden
            className="bg-accent size-4 rounded-full transition-transform duration-[var(--duration-fast)] ease-[var(--ease-out)] group-hover:translate-x-32"
          />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-foreground-tertiary w-32 shrink-0 font-mono text-[11px]">
            normal · 200ms
          </span>
          <span
            aria-hidden
            className="bg-info size-4 rounded-full transition-transform duration-[var(--duration-normal)] ease-[var(--ease-out)] group-hover:translate-x-32"
          />
        </div>
      </div>

      {/* card-interactive 실물 */}
      <div className="border-border bg-background rounded-[var(--radius-md)] border p-5">
        <p className="text-foreground-tertiary mb-3 text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          .card-interactive — hover 승격 실물
        </p>
        <div className="card-interactive border-border bg-surface max-w-xs cursor-pointer rounded-[var(--radius-lg)] border p-4 shadow-[var(--shadow-card)]">
          <p className="text-foreground text-sm font-semibold">클릭 가능한 카드</p>
          <p className="text-muted-foreground mt-1 text-xs">
            hover: translateY(-2px) + shadow-card-raised · active: scale(0.995)
          </p>
        </div>
      </div>

      <DoDont
        doItems={[
          'transform · opacity 만 애니메이션 — 컴포지터에서 처리되어 리플로우가 없습니다.',
          <>
            지속시간·이징은{' '}
            {/* ⚠ 와일드카드(-*) 문자열은 Tailwind JIT 가 클래스로 오인해 잘못된 CSS 를
                생성하므로(빌드 실패 실측 2026-07-05) 구체 토큰 예시로 표기한다. */}
            <code className="font-mono text-[11px]">duration-[var(--duration-fast)]</code> +{' '}
            <code className="font-mono text-[11px]">ease-[var(--ease-out)]</code> 토큰으로.
          </>,
          '무한 루프 애니메이션은 스피너(animate-spin)와 라이브 인디케이터(animate-pulse) 두 곳에만 허용합니다.',
        ]}
        dontItems={[
          'width · height · top · margin · padding 애니메이션 — 레이아웃을 매 프레임 다시 계산합니다.',
          '300ms 이상의 장식성 트랜지션 — 대시보드에선 반응이 느리다고 느껴집니다.',
          '컴포넌트별 임의 duration 하드코딩(예: duration-500) — 토큰 스케일을 깨뜨립니다.',
        ]}
      />
    </SectionCard>
  );
}
