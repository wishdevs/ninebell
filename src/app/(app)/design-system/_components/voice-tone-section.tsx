import { SectionCard } from '@/components/ui/section-card';
import {
  formatDateTime,
  formatInteger,
  formatRelativeKorean,
  formatSeconds,
  relativeFromNow,
} from '@/lib/data/format';
import { DoDont } from './showcase';

/* ── 보이스 & 톤 ─────────────────────────────────────────────────────
   시간·숫자·에러 문구의 제품 규칙 요약. 시간 예시는 실제 lib/data/format.ts
   포매터를 호출해 렌더한다(살아있는 문서) — 규칙이 코드에서 바뀌면 여기도 따라간다. */

const TIME_EXAMPLES = [
  {
    fn: 'formatRelativeKorean',
    input: '12분 전 시각',
    output: formatRelativeKorean(relativeFromNow({ minutes: 12 })),
    rule: '목록의 "최근 실행" — 분/시간/일/주 거친 단위만',
  },
  {
    fn: 'formatRelativeKorean',
    input: '3시간 전 시각',
    output: formatRelativeKorean(relativeFromNow({ hours: 3 })),
    rule: '초 단위 갱신 금지(하이드레이션 불일치 원인 — format.ts 주석 참조)',
  },
  {
    fn: 'formatDateTime',
    input: '하루 전 시각',
    output: formatDateTime(relativeFromNow({ days: 1 })),
    rule: '감사 로그 등 정확한 시각 — Asia/Seoul 고정으로 서버/클라이언트 동일 문자열',
  },
  {
    fn: 'formatSeconds',
    input: '154',
    output: formatSeconds(154),
    rule: '소요시간 — "M분 SS초" 한국어 단위',
  },
  {
    fn: 'formatInteger',
    input: '1234567',
    output: formatInteger(1_234_567),
    rule: '건수·금액 — ko-KR 천단위 콤마',
  },
] as const;

export function VoiceToneSection() {
  return (
    <SectionCard
      caption="규칙"
      title="보이스 & 톤"
      description="시간은 lib/data/format.ts 의 포매터만 사용합니다(아래 출력은 실제 함수 호출 결과). 숫자 열은 tabular-nums 로 정렬하고, 에러 문구는 반드시 '다음 행동'을 포함합니다."
      density="comfortable"
    >
      {/* 시간 표기 — 실제 포매터 호출 결과 */}
      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          시간 · 숫자 표기 (lib/data/format.ts 실호출)
        </p>
        <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
          {TIME_EXAMPLES.map((e, i) => (
            <div key={i} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-2.5">
              <span className="text-foreground-tertiary w-44 shrink-0 font-mono text-[11px]">
                {e.fn}
              </span>
              <span className="text-foreground w-36 shrink-0 text-[13px] font-medium tabular-nums">
                {e.output}
              </span>
              <span className="text-muted-foreground min-w-0 flex-1 text-xs">{e.rule}</span>
            </div>
          ))}
        </div>
      </div>

      {/* tabular-nums 정렬 데모 */}
      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          숫자 열은 tabular-nums — 자릿수가 달라도 세로줄이 흔들리지 않게
        </p>
        <div className="border-border bg-background grid max-w-sm grid-cols-2 gap-x-8 rounded-[var(--radius-md)] border p-4 text-[13px]">
          <div className="flex flex-col gap-1">
            <span className="text-foreground-tertiary text-[11px]">tabular-nums ✓</span>
            {[1_234_567, 89_012, 345].map((n) => (
              <span key={n} className="text-foreground text-right font-medium tabular-nums">
                {formatInteger(n)}
              </span>
            ))}
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-foreground-tertiary text-[11px]">기본 숫자 ✕</span>
            {[1_234_567, 89_012, 345].map((n) => (
              <span
                key={n}
                className="text-foreground-tertiary text-right font-medium [font-variant-numeric:normal]"
              >
                {formatInteger(n)}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* 에러 문구 규칙 */}
      <DoDont
        doItems={[
          <>
            원인 + 다음 행동:{' '}
            <em>&ldquo;서버에 연결할 수 없습니다. 네트워크 확인 후 다시 시도하세요.&rdquo;</em>
          </>,
          <>
            기대치를 먼저 알려주기: StatusBadge 의 batch_submitted 라벨은{' '}
            <em>&ldquo;처리 중 — 24시간 내 완료 예정&rdquo;</em> — 멈춘 게 아님을 문구가 설명합니다.
          </>,
          '빈 상태(EmptyState)에는 가능한 한 action 버튼으로 다음 행동을 제공합니다.',
        ]}
        dontItems={[
          <>
            행동 없는 통보: <em>&ldquo;오류가 발생했습니다.&rdquo;</em>
          </>,
          <>
            원문 노출: <em>&ldquo;Error: fetch failed&rdquo;</em> — 사용자 문구는 한국어로, 상세는
            서버 로그로.
          </>,
          '상대시간을 초 단위로 실시간 갱신 — 하이드레이션 불일치와 시선 분산만 남습니다.',
        ]}
      />
    </SectionCard>
  );
}
