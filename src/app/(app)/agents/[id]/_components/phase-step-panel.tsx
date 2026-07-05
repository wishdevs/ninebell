'use client';

import { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import {
  RiArrowDownSLine,
  RiCheckLine,
  RiCloseLine,
  RiLoader4Line,
  RiUserLine,
} from '@remixicon/react';
import type { WorkflowStep } from '@/lib/data/agents';
import type { LiveRunStatus, LiveStepState } from '@/lib/live/types';
import { cn } from '@/lib/utils';

/**
 * Phase 스텝 패널 — 워크플로우 탭의 단계 표시 대개편.
 *
 * 단계 계획(백엔드 steps)을 큰 단계(phase)로 묶어 아코디언으로 보여준다:
 * - 상단 고정 헤더: 전체 진행 바 + N/전체 단계 + 경과 + "지금: ○○" 현재 단계.
 * - phase 헤더: 번호·제목·상태·내부 진행(n/m)·소요합·사용 스킬 칩 요약.
 * - 활성(진행/개입) phase 만 자동 확장 + 자동 스크롤, 나머지는 접힘(클릭 토글).
 * - 개입 대기(waiting_input + intervention 스텝 진행 중)면 해당 phase 를
 *   accent ring + pulse + 대형 배지로 강제 확장해 개입 필요를 확실히 알린다.
 *
 * 라이브 단계 병합: plan 에 없는 raw 스텝은 마지막 "기타" phase 로 붙는다.
 * 실행 전(liveSteps 비어 있음)에는 전 단계 '대기'로 계획 구조만 보여준다.
 */

interface PhaseStepPanelProps {
  /** 에이전트의 단계 계획(백엔드 `/agents/{id}` steps — 단일 소스). */
  planSteps?: readonly WorkflowStep[];
  /** 라이브 런에서 도착한 단계(없으면 실행 전 계획 보기). */
  liveSteps?: readonly LiveStepState[];
  runStatus: LiveRunStatus;
}

type DisplayStepStatus = 'running' | 'done' | 'failed' | 'pending';

interface DisplayStep {
  id: string;
  label: string;
  status: DisplayStepStatus;
  ms?: number;
  skill?: string;
  detail?: string;
  intervention?: boolean;
}

type PhaseStatus = DisplayStepStatus;

interface PhaseGroup {
  /** phase 라벨 + 등장 인덱스(라벨 중복 안전) — 확장 상태·스크롤 키. */
  id: string;
  title: string;
  steps: DisplayStep[];
  status: PhaseStatus;
  doneCount: number;
  /** 완료 스텝 ms 합. 없으면 undefined. */
  elapsedMs?: number;
  /** phase 내 사용 스킬(중복 제거, 등장 순서). */
  skills: string[];
  /** 개입(HITL) 스텝 포함 여부 — 접혀 있어도 어디서 멈출지 보이게. */
  hasIntervention: boolean;
}

const FALLBACK_PHASE = '기타';

/** 라이브 단계(도착분)를 단계 계획과 병합 — 계획에 없는 스텝은 뒤에 붙인다. */
function buildDisplaySteps(
  planSteps: readonly WorkflowStep[] | undefined,
  liveSteps: readonly LiveStepState[],
): { step: DisplayStep; phase: string }[] {
  if (!planSteps || planSteps.length === 0) {
    // 계획 없는 에이전트(DB 스텝 없는 데모 등) — 도착한 라이브 단계 id 그대로 폴백.
    return liveSteps.map((s) => ({
      step: { id: s.step, label: s.step, status: s.status, ms: s.ms },
      phase: FALLBACK_PHASE,
    }));
  }
  const byId = new Map(liveSteps.map((s) => [s.step, s] as const));
  const known = new Set(planSteps.map((d) => d.id));
  const merged = planSteps.map((d) => ({
    step: {
      id: d.id,
      label: d.label,
      status: byId.get(d.id)?.status ?? ('pending' as const),
      ms: byId.get(d.id)?.ms,
      skill: d.skill,
      detail: d.detail,
      intervention: d.intervention,
    },
    phase: d.phase ?? FALLBACK_PHASE,
  }));
  const extra = liveSteps
    .filter((s) => !known.has(s.step))
    .map((s) => ({
      step: { id: s.step, label: s.step, status: s.status, ms: s.ms },
      phase: FALLBACK_PHASE,
    }));
  return [...merged, ...extra];
}

/** phase 상태 도출 — 실패 > 진행(부분 완료 포함) > 전부 완료 > 대기. */
function derivePhaseStatus(steps: readonly DisplayStep[]): PhaseStatus {
  if (steps.some((s) => s.status === 'failed')) return 'failed';
  if (steps.some((s) => s.status === 'running')) return 'running';
  if (steps.every((s) => s.status === 'done')) return 'done';
  if (steps.some((s) => s.status === 'done')) return 'running';
  return 'pending';
}

/** 연속 구간 기준으로 phase 그룹을 만든다(같은 라벨이라도 끊기면 별도 그룹). */
function buildPhaseGroups(entries: readonly { step: DisplayStep; phase: string }[]): PhaseGroup[] {
  const groups: PhaseGroup[] = [];
  for (const { step, phase } of entries) {
    const last = groups[groups.length - 1];
    if (!last || last.title !== phase) {
      groups.push({
        id: `${groups.length}-${phase}`,
        title: phase,
        steps: [step],
        status: 'pending',
        doneCount: 0,
        skills: [],
        hasIntervention: false,
      });
    } else {
      last.steps.push(step);
    }
  }
  return groups.map((g) => {
    const doneMs = g.steps.reduce(
      (acc, s) => (s.status === 'done' && s.ms != null ? acc + s.ms : acc),
      0,
    );
    return {
      ...g,
      status: derivePhaseStatus(g.steps),
      doneCount: g.steps.filter((s) => s.status === 'done').length,
      elapsedMs: doneMs > 0 ? doneMs : undefined,
      skills: [...new Set(g.steps.map((s) => s.skill).filter((s): s is string => !!s))],
      hasIntervention: g.steps.some((s) => s.intervention),
    };
  });
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}초`;
}

const STEP_DOT: Record<DisplayStepStatus, string> = {
  running: 'bg-accent/15 text-accent',
  done: 'bg-success/15 text-success',
  failed: 'bg-danger/15 text-danger',
  pending: 'bg-muted text-muted-foreground',
};

const STEP_LABEL: Record<DisplayStepStatus, string> = {
  running: '진행 중',
  done: '완료',
  failed: '실패',
  pending: '대기',
};

export function PhaseStepPanel({ planSteps, liveSteps = [], runStatus }: PhaseStepPanelProps) {
  const entries = useMemo(() => buildDisplaySteps(planSteps, liveSteps), [planSteps, liveSteps]);
  const groups = useMemo(() => buildPhaseGroups(entries), [entries]);

  const allSteps = entries.map((e) => e.step);
  const total = allSteps.length;
  const doneCount = allSteps.filter((s) => s.status === 'done').length;
  const percent = total > 0 ? Math.round((doneCount / total) * 100) : 0;
  const elapsedMs = allSteps.reduce(
    (acc, s) => (s.status === 'done' && s.ms != null ? acc + s.ms : acc),
    0,
  );
  // 시작 전 = 라이브 단계가 하나도 안 왔고 세션도 idle(계획 보기).
  const isPlanOnly = runStatus === 'idle' && liveSteps.length === 0;

  // 현재 단계: 진행 중 스텝 우선, 없으면 마지막 비-대기 스텝.
  const runningStep = allSteps.find((s) => s.status === 'running');
  const lastTouched = [...allSteps].reverse().find((s) => s.status !== 'pending');
  const currentStep = runningStep ?? lastTouched;

  // 개입 대기: HITL 스텝이 진행 중 + 런이 입력 대기 상태 → 해당 phase 를 강하게 알린다.
  const urgentGroupId =
    runStatus === 'waiting_input'
      ? (groups.find((g) => g.steps.some((s) => s.intervention && s.status === 'running'))?.id ??
        null)
      : null;
  const activeGroupId =
    urgentGroupId ??
    groups.find((g) => g.status === 'running' || g.status === 'failed')?.id ??
    null;

  // 확장 상태: 활성 phase 자동 확장(활성 변경 시 사용자 토글 초기화), 개입 phase 는 강제 확장.
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  useEffect(() => {
    setOverrides({});
  }, [activeGroupId]);
  const isOpen = (g: PhaseGroup) =>
    g.id === urgentGroupId ? true : (overrides[g.id] ?? g.id === activeGroupId);
  const toggle = (g: PhaseGroup) => {
    if (g.id === urgentGroupId) return; // 개입 대기 phase 는 접을 수 없다.
    const next = !isOpen(g);
    setOverrides((prev) => ({ ...prev, [g.id]: next }));
  };

  // 활성/개입 phase 로 자동 스크롤 — 진행 위치가 항상 화면에 보이게.
  const activeRef = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [activeGroupId, urgentGroupId, runningStep?.id]);

  if (total === 0) {
    return (
      <p className="text-foreground-tertiary py-6 text-center text-[12px]">
        {runStatus === 'connecting' ? '세션에 연결하는 중…' : '아직 단계가 없습니다.'}
      </p>
    );
  }

  return (
    <div className="flex flex-col">
      {/* ── 전체 진행 헤더(스크롤 고정) ─────────────────────────────── */}
      <header className="bg-surface/95 border-border-subtle sticky top-0 z-10 border-b px-4 pt-4 pb-3 backdrop-blur">
        <div className="flex items-baseline justify-between gap-2">
          {isPlanOnly ? (
            <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
              대기 — {total}단계 계획
            </p>
          ) : (
            <p className="text-foreground min-w-0 truncate text-[length:var(--text-body-sm)] font-semibold">
              {runStatus === 'succeeded' ? (
                <span className="text-success">전체 완료</span>
              ) : runStatus === 'failed' ? (
                <span className="text-danger">
                  실패{currentStep ? ` — ${currentStep.label}` : ''}
                </span>
              ) : runStatus === 'waiting_input' && currentStep ? (
                <>
                  <span className="text-warning">개입 대기</span>
                  <span className="text-foreground"> · {currentStep.label}</span>
                </>
              ) : currentStep ? (
                <>
                  <span className="text-foreground-tertiary font-medium">지금: </span>
                  {currentStep.label}
                </>
              ) : (
                '시작하는 중…'
              )}
            </p>
          )}
          <p className="text-foreground-tertiary shrink-0 text-[11px] tabular-nums">
            <span className="text-foreground font-semibold">{doneCount}</span>/{total} 단계 ·{' '}
            {percent}%{elapsedMs > 0 ? <span> · {formatMs(elapsedMs)}</span> : null}
          </p>
        </div>
        {/* 굵은 진행 바 — 실패는 danger, 개입 대기는 warning 으로 상태를 색으로도 말한다. */}
        <div
          className="bg-muted mt-2 h-2 overflow-hidden rounded-full"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-label="전체 진행률"
        >
          <div
            className={cn(
              'h-full rounded-full transition-[width] duration-500 ease-out',
              runStatus === 'failed'
                ? 'bg-danger'
                : runStatus === 'waiting_input'
                  ? 'bg-warning'
                  : runStatus === 'succeeded'
                    ? 'bg-success'
                    : 'bg-accent',
            )}
            style={{ width: `${isPlanOnly ? 0 : Math.max(percent, runningStep ? 3 : 0)}%` }}
          />
        </div>
      </header>

      {/* ── Phase 아코디언 ──────────────────────────────────────────── */}
      <ol className="flex flex-col gap-2 p-4">
        {groups.map((group, gi) => (
          <PhaseCard
            key={group.id}
            ref={group.id === (urgentGroupId ?? activeGroupId) ? activeRef : undefined}
            group={group}
            index={gi}
            open={isOpen(group)}
            urgent={group.id === urgentGroupId}
            runningStepId={runningStep?.id ?? null}
            onToggle={() => toggle(group)}
          />
        ))}
      </ol>
    </div>
  );
}

// ── Phase 카드(아코디언 1칸) ─────────────────────────────────────────

interface PhaseCardProps {
  group: PhaseGroup;
  index: number;
  open: boolean;
  /** 개입 대기 중인 phase — ring + pulse + 대형 배지로 강조, 접기 불가. */
  urgent: boolean;
  runningStepId: string | null;
  onToggle: () => void;
}

const MAX_SKILL_CHIPS = 3;

const PhaseCard = forwardRef<HTMLLIElement, PhaseCardProps>(function PhaseCard(
  { group, index, open, urgent, runningStepId, onToggle },
  ref,
) {
  const { title, steps, status, doneCount, elapsedMs, skills, hasIntervention } = group;
  const detailId = `phase-steps-${group.id}`;
  return (
    <li
      ref={ref}
      className={cn(
        'overflow-hidden rounded-[var(--radius-md)] border transition-shadow duration-300',
        urgent
          ? 'border-warning/60 ring-warning/30 ring-2'
          : status === 'running'
            ? 'border-accent/40'
            : status === 'failed'
              ? 'border-danger/40'
              : 'border-border',
        status === 'pending' && !urgent && 'opacity-80',
      )}
    >
      {/* 개입 대기 대형 배지 — phase 헤더 위에 풀폭으로 얹어 절대 못 놓치게. */}
      {urgent ? (
        <div className="bg-warning/15 text-warning flex items-center gap-2 px-3 py-2">
          <span className="relative flex size-2.5 shrink-0" aria-hidden>
            <span className="bg-warning absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" />
            <span className="bg-warning relative inline-flex size-2.5 rounded-full" />
          </span>
          <span className="text-[length:var(--text-body-sm)] font-bold">
            개입 필요 — 입력해 주세요
          </span>
          <RiUserLine size={14} aria-hidden className="ml-auto shrink-0" />
        </div>
      ) : null}

      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={detailId}
        className={cn(
          'hover:bg-muted/40 flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors',
          urgent && 'cursor-default hover:bg-transparent',
        )}
      >
        {/* 단계 번호 + 상태 아이콘 */}
        <span
          className={cn(
            'flex size-7 shrink-0 items-center justify-center rounded-full text-[12px] font-bold tabular-nums',
            STEP_DOT[status],
          )}
        >
          {status === 'done' ? (
            <RiCheckLine size={15} aria-hidden />
          ) : status === 'failed' ? (
            <RiCloseLine size={15} aria-hidden />
          ) : status === 'running' ? (
            <RiLoader4Line size={15} className="animate-spin" aria-hidden />
          ) : (
            index + 1
          )}
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span
              className={cn(
                'truncate text-[length:var(--text-body-sm)] font-semibold',
                status === 'pending' ? 'text-foreground-secondary' : 'text-foreground',
              )}
            >
              {title}
            </span>
            {/* 평상시 개입 예고 — 계획 단계에서도 어디서 멈출지 보이게. */}
            {hasIntervention && !urgent ? (
              <span
                className="bg-warning/15 text-warning inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                title="이 단계에서 사용자 개입이 필요합니다"
              >
                <RiUserLine size={10} aria-hidden />
                개입
              </span>
            ) : null}
          </span>
          {/* phase 사용 스킬 칩 요약(중복 제거, 최대 3+N) */}
          {skills.length > 0 ? (
            <span className="mt-1 flex flex-wrap items-center gap-1">
              {skills.slice(0, MAX_SKILL_CHIPS).map((skill) => (
                <span
                  key={skill}
                  className="text-foreground-tertiary border-border-subtle bg-surface rounded border px-1.5 py-0.5 text-[10px]"
                >
                  {skill}
                </span>
              ))}
              {skills.length > MAX_SKILL_CHIPS ? (
                <span className="text-foreground-tertiary text-[10px]">
                  +{skills.length - MAX_SKILL_CHIPS}
                </span>
              ) : null}
            </span>
          ) : null}
        </span>

        <span className="flex shrink-0 items-center gap-2">
          <span className="text-foreground-tertiary text-[11px] tabular-nums">
            {doneCount}/{steps.length}
            {elapsedMs != null ? <span> · {formatMs(elapsedMs)}</span> : null}
          </span>
          <RiArrowDownSLine
            size={16}
            aria-hidden
            className={cn(
              'text-foreground-tertiary transition-transform duration-200',
              open && 'rotate-180',
            )}
          />
        </span>
      </button>

      {/* 세부 스텝 타임라인 */}
      {open ? (
        <ol id={detailId} className="border-border-subtle border-t px-3 py-3">
          {steps.map((step, i) => (
            <StepRow
              key={step.id}
              step={step}
              isLast={i === steps.length - 1}
              isRunning={step.id === runningStepId}
            />
          ))}
        </ol>
      ) : null}
    </li>
  );
});

// ── 세부 스텝 1행 ────────────────────────────────────────────────────

function StepRow({
  step,
  isLast,
  isRunning,
}: {
  step: DisplayStep;
  isLast: boolean;
  isRunning: boolean;
}) {
  return (
    <li
      className={cn(
        'relative flex gap-3 pb-3.5 pl-2 last:pb-0',
        // 현재 실행 중 스텝 강조 — accent 좌측 바.
        isRunning && 'border-accent -ml-3 border-l-2 pl-[18px]',
      )}
    >
      {!isLast ? (
        <span
          aria-hidden
          className={cn(
            'bg-border absolute top-6 h-[calc(100%-1rem)] w-px',
            // 점(size-6) 중심 정렬 — 실행 중 행은 좌측 accent 바(-ml-3+border 2px+pl 18px)만큼 밀린다.
            isRunning ? 'left-[31px]' : 'left-[19px]',
          )}
        />
      ) : null}
      <span
        className={cn(
          'relative z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full',
          STEP_DOT[step.status],
        )}
      >
        {step.status === 'done' ? (
          <RiCheckLine size={12} aria-hidden />
        ) : step.status === 'failed' ? (
          <RiCloseLine size={12} aria-hidden />
        ) : step.status === 'running' ? (
          <RiLoader4Line size={12} className="animate-spin" aria-hidden />
        ) : (
          <span className="bg-muted-foreground/50 size-1.5 rounded-full" aria-hidden />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5">
            <span
              className={cn(
                'truncate text-[length:var(--text-body-sm)]',
                step.status === 'pending'
                  ? 'text-foreground-secondary font-medium'
                  : 'text-foreground font-semibold',
              )}
            >
              {step.label}
            </span>
            {step.intervention ? (
              <span
                className={cn(
                  'inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
                  isRunning
                    ? 'bg-warning/20 text-warning animate-pulse'
                    : 'bg-warning/10 text-warning',
                )}
              >
                <RiUserLine size={10} aria-hidden />
                개입
              </span>
            ) : null}
          </span>
          <span
            className={cn(
              'shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
              STEP_DOT[step.status],
            )}
          >
            {STEP_LABEL[step.status]}
          </span>
        </div>
        {step.skill || step.ms != null ? (
          <div className="mt-0.5 flex items-center gap-1.5">
            {step.skill ? (
              <span className="text-foreground-tertiary border-border-subtle inline-block rounded border px-1.5 py-0.5 text-[10px]">
                {step.skill}
              </span>
            ) : null}
            {step.ms != null ? (
              <span className="text-foreground-tertiary text-[10px] tabular-nums">
                {formatMs(step.ms)}
              </span>
            ) : null}
          </div>
        ) : null}
        {step.detail ? (
          <p className="text-muted-foreground mt-1 text-[11px] leading-relaxed">{step.detail}</p>
        ) : null}
      </div>
    </li>
  );
}
