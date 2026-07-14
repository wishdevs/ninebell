import { RiCheckLine, RiCloseLine, RiLoader4Line, RiUserLine } from '@remixicon/react';
import { SectionCard } from '@/components/ui/section-card';
import {
  AGENT_STATUS_LABEL,
  AGENT_STATUS_TONE,
  type AgentStatus,
  type AgentStatusTone,
} from '@/lib/data/agents';
import type { SkillLayer } from '@/lib/api/skills';
import type { PrefillSource } from '@/lib/live/types';
import { cn } from '@/lib/utils';
import { Snippet } from './showcase';

/* ════════════════════════════════════════════════════════════════════
   도메인 상태 어휘 — 이 제품 고유의 상태 언어를 한 곳에 문서화한다.
   타입은 전부 실제 도메인 모듈에서 import 하므로(살아있는 문서),
   어휘가 늘어나면 아래 Record 들이 컴파일 에러로 문서 갱신을 강제한다.
   ════════════════════════════════════════════════════════════════════ */

/* ── 1) 런 상태 (REST 이력 — RunStatus) ──────────────────────────────
   렌더 원본: src/app/(app)/logs/_components/logs-client.tsx `STATUS_STYLE`
   (모듈-로컬이라 import 불가). 스타일을 바꿀 땐 반드시 두 곳을 함께 수정. */

type CanonicalRunStatus = 'running' | 'waiting_input' | 'succeeded' | 'failed' | 'cancelled';

const RUN_STATUS_DOC: Record<
  CanonicalRunStatus,
  { label: string; className: string; meaning: string; terminal: boolean }
> = {
  running: {
    label: '실행 중',
    className: 'border-accent/30 bg-accent/10 text-accent',
    meaning: '라이브 세션이 흐름을 진행 중 — accent = "지금 움직이고 있다"',
    terminal: false,
  },
  waiting_input: {
    label: '개입 대기',
    className: 'border-warning/30 bg-warning/10 text-warning',
    meaning: 'HITL — 사람의 선택/입력 없이는 진행 불가. warning = 사용자 행동 필요',
    terminal: false,
  },
  succeeded: {
    label: '완료',
    className: 'border-success/30 bg-success/10 text-success',
    meaning: '결과 수신 후 정상 종료',
    terminal: true,
  },
  failed: {
    label: '실패',
    className: 'border-danger/30 bg-danger/10 text-danger',
    meaning: '오류/연결 실패로 종료 — 이력에 failedStep(멈춘 단계)이 함께 남는다',
    terminal: true,
  },
  cancelled: {
    label: '종료됨',
    className: 'border-border bg-muted text-muted-foreground',
    meaning: '사용자가 즉시 종료(화면 이탈 포함) — 실패가 아니므로 중립 muted',
    terminal: true,
  },
};

const RUN_STATUS_ORDER: ReadonlyArray<CanonicalRunStatus> = [
  'running',
  'waiting_input',
  'succeeded',
  'failed',
  'cancelled',
];

function RunStatusDocBadge({ status }: { status: CanonicalRunStatus }) {
  const doc = RUN_STATUS_DOC[status];
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider',
        doc.className,
      )}
    >
      {doc.label}
    </span>
  );
}

/* ── 2) 에이전트 상태 — 라벨·톤은 lib/data/agents.ts 에서 그대로 가져온다 ── */

const AGENT_TONE_CLASS: Record<AgentStatusTone, string> = {
  info: 'bg-info/10 text-info',
  warning: 'bg-warning/10 text-warning',
  muted: 'bg-muted text-muted-foreground',
  success: 'bg-success/10 text-success',
  danger: 'bg-danger/10 text-danger',
};

const AGENT_STATUS_ORDER: ReadonlyArray<AgentStatus> = [
  'running',
  'waiting_input',
  'paused',
  'completed',
  'failed',
  'idle',
];

/* ── 3) 스텝 상태 — 라이브 단계 목록의 어휘 ──────────────────────────
   렌더 원본: agents/[id]/_components/live-side-panel.tsx `STEP_DOT`/`STEP_LABEL`
   (모듈-로컬이라 import 불가 — 스타일 변경 시 함께 수정). */

type DocStepStatus = 'pending' | 'running' | 'done' | 'failed';

const STEP_DOC: Record<DocStepStatus, { label: string; cls: string; meaning: string }> = {
  pending: {
    label: '대기',
    cls: 'bg-muted text-muted-foreground',
    meaning: '아직 도달하지 않은 계획 단계 — 원 안에 순번 숫자를 표시',
  },
  running: {
    label: '진행 중',
    cls: 'bg-accent/15 text-accent',
    meaning: '현재 실행 중 — 스피너로 하트비트를 보인다',
  },
  done: {
    label: '완료',
    cls: 'bg-success/15 text-success',
    meaning: '단계 종료 — 소요시간(ms)이 함께 남는다',
  },
  failed: {
    label: '실패',
    cls: 'bg-danger/15 text-danger',
    meaning: '이 단계에서 중단 — 런 전체가 failed 로 종료된다',
  },
};

function StepDocRow({
  status,
  index,
  labelText,
  skill,
  intervention,
}: {
  status: DocStepStatus;
  index: number;
  labelText: string;
  skill?: string;
  intervention?: boolean;
}) {
  const doc = STEP_DOC[status];
  return (
    <li className="flex items-start gap-3 py-2">
      <span
        className={cn(
          'mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full',
          doc.cls,
        )}
      >
        {status === 'done' ? (
          <RiCheckLine size={12} aria-hidden />
        ) : status === 'failed' ? (
          <RiCloseLine size={12} aria-hidden />
        ) : status === 'pending' ? (
          <span className="text-[10px] font-bold tabular-nums">{index}</span>
        ) : (
          <RiLoader4Line size={12} className="animate-spin" aria-hidden />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            {labelText}
          </span>
          {intervention ? (
            <span className="bg-warning/15 text-warning inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold">
              <RiUserLine size={10} aria-hidden />
              개입 필요
            </span>
          ) : null}
          <span className={cn('rounded-full px-1.5 py-0.5 text-[10px] font-semibold', doc.cls)}>
            {doc.label}
          </span>
        </div>
        <p className="text-muted-foreground mt-0.5 text-[11px] leading-relaxed">{doc.meaning}</p>
        {skill ? (
          <span className="text-foreground-tertiary border-border-subtle mt-1 inline-block rounded border px-1.5 py-0.5 text-[10px]">
            {skill}
          </span>
        ) : null}
      </div>
    </li>
  );
}

export function RunLifecycleSection() {
  return (
    <SectionCard
      caption="도메인 어휘"
      title="런 · 에이전트 · 스텝 상태"
      description="색은 장식이 아니라 의미입니다 — accent=진행, warning=사람 개입 필요, success=정상 종료, danger=실패 종료, muted=중립(대기·취소). 세 어휘 모두 이 다섯 톤만 사용합니다."
      density="comfortable"
    >
      {/* 런 상태 — 이력(logs)·실행 화면 공용 어휘 */}
      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          런 상태 · RunStatus (lib/live/runs-api.ts)
        </p>
        <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
          {RUN_STATUS_ORDER.map((s) => (
            <div key={s} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
              <span className="w-28 shrink-0 font-mono text-[11px]">{s}</span>
              <span className="w-24 shrink-0">
                <RunStatusDocBadge status={s} />
              </span>
              <span className="text-muted-foreground min-w-0 flex-1 text-[13px]">
                {RUN_STATUS_DOC[s].meaning}
              </span>
              {RUN_STATUS_DOC[s].terminal ? (
                <span className="text-foreground-tertiary shrink-0 font-mono text-[10px]">
                  terminal
                </span>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      {/* 에이전트 상태 — 라벨·톤을 도메인 모듈에서 직접 렌더(살아있는 문서) */}
      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          에이전트 상태 · AGENT_STATUS_LABEL / TONE (lib/data/agents.ts 직접 import)
        </p>
        <div className="border-border bg-background flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border p-4">
          {AGENT_STATUS_ORDER.map((s) => (
            <span key={s} className="flex items-center gap-1.5">
              <span
                className={cn(
                  'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                  AGENT_TONE_CLASS[AGENT_STATUS_TONE[s]],
                )}
              >
                {AGENT_STATUS_LABEL[s]}
              </span>
              <span className="text-foreground-tertiary font-mono text-[10px]">{s}</span>
            </span>
          ))}
        </div>
      </div>

      {/* 스텝 상태 — 라이브 단계 목록 어휘 */}
      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          스텝 상태 · LiveStepStatus + pending (라이브 단계 목록)
        </p>
        <ol className="border-border bg-background divide-border-subtle flex flex-col divide-y rounded-[var(--radius-md)] border px-4 py-1">
          <StepDocRow status="done" index={1} labelText="옴니솔 로그인" skill="옴니솔 로그인" />
          <StepDocRow status="running" index={2} labelText="증빙 적용 판단" intervention />
          <StepDocRow status="pending" index={3} labelText="결의서 저장 (F7)" />
          <StepDocRow status="failed" index={4} labelText="전표 조회" />
        </ol>
        <p className="text-muted-foreground text-xs leading-relaxed">
          &lsquo;개입 필요&rsquo; 배지(warning)는 상태가 아니라 <strong>속성</strong>입니다 — 해당
          단계 도달 시 런이 waiting_input 으로 전환됨을 미리 알립니다. 스텝의 스킬은 회색 보더
          칩으로 병기합니다.
        </p>
      </div>

      <Snippet code="import { AGENT_STATUS_LABEL, AGENT_STATUS_TONE } from '@/lib/data/agents'; // 어휘 원본 — 새 상태는 여기부터" />
    </SectionCard>
  );
}

/* ── 4) 프리필 출처 배지 ─────────────────────────────────────────────
   렌더 원본: src/components/live/LiveGridCard.tsx `SOURCE_META`(모듈-로컬).
   클래스는 그곳과 문자 그대로 동일해야 한다 — 변경 시 두 곳을 함께 수정. */

const PREFILL_DOC: Record<PrefillSource, { label: string; cls: string; meaning: string }> = {
  ai: {
    label: 'AI',
    cls: 'bg-accent/15 text-accent',
    meaning: 'AI 추천으로 미리 선택 — accent = 모델의 제안, 확정 전 검토 대상',
  },
  learned: {
    label: '학습',
    cls: 'bg-success/15 text-success',
    meaning: '과거 이 가맹점에 사용자가 확정했던 선택(개입 학습) — success = 가장 신뢰',
  },
  seed: {
    label: '전사',
    cls: 'bg-info/15 text-info',
    meaning: '전사 기초자료(과거 법인카드 실적)의 가맹점 관례 — info = 조직 차원 근거',
  },
  lookup: {
    label: '추천',
    cls: 'bg-warning/15 text-warning',
    meaning: '예산계정 변경에 맞춰 실시간 재추천된 적요 — warning = 자동 채움, 확인 후 필요시 수정',
  },
  default: {
    label: '기본',
    cls: 'bg-muted text-foreground-tertiary',
    meaning: '기본지정 폴백 — muted = 근거 없음, 반드시 눈으로 확인',
  },
};

const PREFILL_ORDER: ReadonlyArray<PrefillSource> = ['learned', 'seed', 'ai', 'lookup', 'default'];

/* ── 5) 스킬 칩 — 계층 배지(skills 페이지 LayerBadge 와 동일 클래스) ── */

const SKILL_LAYER_DOC: Record<SkillLayer, { label: string; cls: string; meaning: string }> = {
  omnisol: {
    label: '옴니솔',
    cls: 'bg-info/10 text-info',
    meaning: '더존 옴니솔 화면 조작 전용 스킬',
  },
  common: {
    label: '공통',
    cls: 'bg-muted text-muted-foreground',
    meaning: '시스템 무관 공용 스킬(파일 · 정규화 등)',
  },
  llm: { label: 'LLM', cls: 'bg-accent/10 text-accent', meaning: 'LLM 추론이 개입하는 스킬' },
};

const SKILL_LAYER_ORDER: ReadonlyArray<SkillLayer> = ['omnisol', 'common', 'llm'];

export function PrefillSkillSection() {
  return (
    <SectionCard
      caption="도메인 어휘"
      title="프리필 출처 배지 · 스킬 칩"
      description="그리드 개입 화면의 셀 값 옆에는 값이 '어디서 왔는지'를 9px 배지로 병기합니다. 신뢰 순서는 학습 > 전사 > AI > 기본 — 색이 곧 근거의 종류입니다."
      density="comfortable"
    >
      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          프리필 출처 · PrefillSource (LiveGridCard SOURCE_META 와 동일 스타일)
        </p>
        <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
          {PREFILL_ORDER.map((s) => (
            <div key={s} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
              <span className="w-20 shrink-0 font-mono text-[11px]">{s}</span>
              <span className="w-14 shrink-0">
                <span
                  className={cn(
                    'shrink-0 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide',
                    PREFILL_DOC[s].cls,
                  )}
                >
                  {PREFILL_DOC[s].label}
                </span>
              </span>
              <span className="text-muted-foreground min-w-0 flex-1 text-[13px]">
                {PREFILL_DOC[s].meaning}
              </span>
            </div>
          ))}
        </div>
        {/* 실사용 맥락 미니 데모 — 그리드 셀 안의 값 + 출처 배지 */}
        <div className="border-border bg-background flex flex-wrap items-center gap-4 rounded-[var(--radius-md)] border p-4 text-[13px]">
          <span className="flex items-center gap-1.5">
            <span className="text-foreground">복리후생비</span>
            <span className="bg-success/15 text-success rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide">
              학습
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="text-foreground">경영지원본부</span>
            <span className="bg-accent/15 text-accent rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide">
              AI
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="text-foreground">회의비</span>
            <span className="bg-muted text-foreground-tertiary rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide">
              기본
            </span>
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          스킬 계층 배지 · SkillLayer (/skills LayerBadge 와 동일 스타일)
        </p>
        <div className="border-border bg-background divide-border-subtle divide-y rounded-[var(--radius-md)] border">
          {SKILL_LAYER_ORDER.map((l) => (
            <div key={l} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
              <span className="w-20 shrink-0 font-mono text-[11px]">{l}</span>
              <span className="w-16 shrink-0">
                <span
                  className={cn(
                    'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold',
                    SKILL_LAYER_DOC[l].cls,
                  )}
                >
                  {SKILL_LAYER_DOC[l].label}
                </span>
              </span>
              <span className="text-muted-foreground min-w-0 flex-1 text-[13px]">
                {SKILL_LAYER_DOC[l].meaning}
              </span>
            </div>
          ))}
        </div>
        <p className="text-muted-foreground text-xs leading-relaxed">
          워크플로우 스텝에 병기하는 <strong>스킬 이름 칩</strong>은 색 없는 회색 보더 칩(위 스텝
          상태 데모 참조)입니다 — 상태 색과 경쟁하지 않도록 무채색을 유지합니다.
        </p>
      </div>

      <Snippet code="import type { PrefillSource } from '@/lib/live/types'; // 출처 어휘 원본 · 렌더는 LiveGridCard SOURCE_META" />
    </SectionCard>
  );
}
