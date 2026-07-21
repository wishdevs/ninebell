'use client';

import { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import {
  RiArrowDownSLine,
  RiCheckLine,
  RiCloseLine,
  RiLoader4Line,
  RiSparkling2Fill,
  RiUserLine,
} from '@remixicon/react';
import { Spinner } from '@/components/ui/spinner';
import type { WorkflowStep } from '@/lib/data/agents';
import { formatEta } from '@/lib/data/format';
import type { LiveRunStatus, LiveStepProgress, LiveStepState } from '@/lib/live/types';
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
  /** 스킬 카탈로그 키 — 'ai-recommend' 스텝은 진행 헤더에서 특별 AI 표시를 켠다. */
  skillKey?: string;
  detail?: string;
  intervention?: boolean;
  /** 예상 소요(ms, 계획 스텝에서). 자동 스텝 전부에 있어야 예상 시간 UI 를 켠다. */
  expectedMs?: number;
  /** 반복 스텝 진행 카운트(라이브) — 예: 결재 순회 {done,total} → "2/5". */
  progress?: LiveStepProgress;
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
      step: { id: s.step, label: s.step, status: s.status, ms: s.ms, progress: s.progress },
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
      skillKey: d.skillKey,
      detail: d.detail,
      intervention: d.intervention,
      expectedMs: d.expectedMs,
      progress: byId.get(d.id)?.progress,
    },
    phase: d.phase ?? FALLBACK_PHASE,
  }));
  const extra = liveSteps
    .filter((s) => !known.has(s.step))
    .map((s) => ({
      step: { id: s.step, label: s.step, status: s.status, ms: s.ms, progress: s.progress },
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

// ── 예상 시간 세그먼트 타임라인 (승인 시안) ──────────────────────────
//
// 런 전체를 하나의 가로 바로 본다: 연속된 자동 스텝 묶음 = 자동 세그먼트(accent,
// 폭 = expectedMs 합 비례) · 개입 스텝 = 개입 세그먼트(warning 줄무늬, 폭 고정 —
// 사람 시간은 예측에서 제외) + 현재 위치 마커. 자동 스텝 중 expectedMs 가 하나라도
// 없으면 타임라인·예고 전체를 숨긴다(부분 데이터로 엉터리 합계 금지).

/** 개입 세그먼트 고정폭(%). 사람 시간은 예측 불가라 비례 배분에서 뺀다. */
const INTERVENTION_SEG_PCT = 12;
/** 실행 중 스텝의 세그먼트 내부 부분 채움 상한 — 실측이 예상보다 길어져도 안 넘친다. */
const RUNNING_FILL_CAP = 0.95;

interface EtaSegment {
  id: string;
  kind: 'auto' | 'intervention';
  steps: DisplayStep[];
  /** 전체 바 대비 폭(%). */
  widthPct: number;
  /** 0..1 채움 비율(자동=expectedMs 기준 진행, 개입=완료 여부). */
  fill: number;
}

/** 실행 중 자동 스텝의 진행분(ms) — 로컬 타이머 경과를 expectedMs×상한으로 캡. */
function runningProgressMs(step: DisplayStep, runningElapsedMs: number): number {
  return Math.min(runningElapsedMs, (step.expectedMs ?? 0) * RUNNING_FILL_CAP);
}

/** planSteps(표시 스텝)로 세그먼트를 만든다 — 연속 자동 묶음 + 개입 고정폭. */
function buildEtaSegments(steps: readonly DisplayStep[], runningElapsedMs: number): EtaSegment[] {
  const raw: { kind: 'auto' | 'intervention'; steps: DisplayStep[] }[] = [];
  for (const s of steps) {
    const last = raw[raw.length - 1];
    if (s.intervention) raw.push({ kind: 'intervention', steps: [s] });
    else if (last?.kind === 'auto') last.steps.push(s);
    else raw.push({ kind: 'auto', steps: [s] });
  }
  const interventionCount = raw.filter((r) => r.kind === 'intervention').length;
  // 개입 고정폭을 뺀 나머지를 자동 세그먼트가 expectedMs 합 비례로 나눠 갖는다.
  const autoTotalPct = Math.max(100 - interventionCount * INTERVENTION_SEG_PCT, 0);
  const sumExpected = (ss: readonly DisplayStep[]) =>
    ss.reduce((acc, s) => acc + (s.expectedMs ?? 0), 0);
  const autoTotalMs = raw.reduce(
    (acc, r) => (r.kind === 'auto' ? acc + sumExpected(r.steps) : acc),
    0,
  );
  return raw.map((r, i) => {
    if (r.kind === 'intervention') {
      return {
        id: `seg-${i}`,
        kind: r.kind,
        steps: r.steps,
        widthPct: INTERVENTION_SEG_PCT,
        fill: r.steps[0].status === 'done' ? 1 : 0,
      };
    }
    const expected = sumExpected(r.steps);
    const doneMs = r.steps.reduce((acc, s) => {
      if (s.status === 'done') return acc + (s.expectedMs ?? 0);
      if (s.status === 'running') return acc + runningProgressMs(s, runningElapsedMs);
      return acc;
    }, 0);
    return {
      id: `seg-${i}`,
      kind: r.kind,
      steps: r.steps,
      widthPct: autoTotalMs > 0 ? (expected / autoTotalMs) * autoTotalPct : 0,
      fill: expected > 0 ? Math.min(doneMs / expected, 1) : 0,
    };
  });
}

/** 미완료 자동 스텝의 남은 예상 합(ms) — 실행 중 스텝은 진행분을 뺀다. */
function remainingAutoMs(steps: readonly DisplayStep[], runningElapsedMs: number): number {
  return steps.reduce((acc, s) => {
    if (s.intervention || s.expectedMs == null || s.status === 'done') return acc;
    if (s.status === 'running')
      return acc + Math.max(s.expectedMs - runningProgressMs(s, runningElapsedMs), 0);
    return acc + s.expectedMs;
  }, 0);
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

  // ── 예상 시간 타임라인 데이터 ──
  // 계획(planSteps)에서 온 표시 스텝만 대상 — 계획에 없는 라이브 스텝(뒤에 붙는 extra)은
  // 예상치가 없으므로 타임라인 축에 넣지 않는다.
  const planDisplaySteps = useMemo(
    () =>
      planSteps && planSteps.length > 0
        ? entries.slice(0, planSteps.length).map((e) => e.step)
        : [],
    [entries, planSteps],
  );
  const autoPlanSteps = planDisplaySteps.filter((s) => !s.intervention);
  // 자동 스텝 전부에 expectedMs 가 있어야 켠다(이력 없는 에이전트 = 기존 진행 바 그대로).
  const etaReady = autoPlanSteps.length > 0 && autoPlanSteps.every((s) => s.expectedMs != null);

  // 실행 중 자동 스텝의 로컬 타이머(1초 틱) — 세그먼트 내부를 expectedMs 기준으로 부분
  // 채운다. waiting_input(개입 대기)이면 진행 중 자동 스텝이 없으므로 자연히 정지한다.
  const runningAutoStep =
    etaReady && runStatus === 'running'
      ? planDisplaySteps.find((s) => s.status === 'running' && !s.intervention)
      : undefined;
  const runningAutoStepId = runningAutoStep?.id ?? null;
  const [runningElapsedMs, setRunningElapsedMs] = useState(0);
  useEffect(() => {
    setRunningElapsedMs(0);
    if (runningAutoStepId == null) return;
    const timer = setInterval(() => setRunningElapsedMs((v) => v + 1000), 1000);
    return () => clearInterval(timer);
  }, [runningAutoStepId]);

  const etaSegments = useMemo(
    () => (etaReady ? buildEtaSegments(planDisplaySteps, runningElapsedMs) : []),
    [etaReady, planDisplaySteps, runningElapsedMs],
  );
  const etaRemainingMs = etaReady ? remainingAutoMs(planDisplaySteps, runningElapsedMs) : 0;

  // 시점별 상태 메시지 — 개입 전 예고 / 개입 완료 후 마무리 안내.
  // 개입 중(waiting_input)엔 생략(개입 카드가 이미 말한다), 계획 보기·종료 상태도 생략.
  let etaMessage: string | null = null;
  if (etaReady && runStatus === 'running') {
    // '다가오는' 개입 = pending 만. running 인 개입 스텝(제출 직후 서버가 닫는 찰나 포함)은
    // 예고 대상이 아니다 — 제출했는데도 "곧 입력을 요청합니다"가 남던 버그 수정(2026-07-06).
    const interventionRunning = planDisplaySteps.some(
      (s) => s.intervention && s.status === 'running',
    );
    const firstUpcomingIntervention = planDisplaySteps.findIndex(
      (s) => s.intervention && s.status === 'pending',
    );
    if (interventionRunning) {
      etaMessage = null;
    } else if (firstUpcomingIntervention >= 0) {
      const beforeMs = remainingAutoMs(
        planDisplaySteps.slice(0, firstUpcomingIntervention),
        runningElapsedMs,
      );
      etaMessage = `곧 입력을 요청합니다 — ${formatEta(beforeMs)} 후`;
    } else if (planDisplaySteps.some((s) => s.intervention)) {
      etaMessage = '남은 단계는 자동 — 완료되면 알려드립니다';
    }
  }

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
                runningStep?.skillKey === 'ai-recommend' ? (
                  /* AI 작업 중 특별 표시 — 반짝임 + 흐르는 그라데이션 텍스트. 화면 변화가
                     없는 긴 AI 콜 구간이 멈춰 보이지 않게 눈에 띄는 신호를 준다. */
                  <span className="inline-flex min-w-0 items-center gap-1.5">
                    <RiSparkling2Fill
                      size={14}
                      aria-hidden
                      className="animate-ai-sparkle text-accent shrink-0"
                    />
                    <span className="ai-working-text truncate">
                      {currentStep.label} — AI가 계산하는 중…
                    </span>
                  </span>
                ) : (
                  <>
                    <span className="text-foreground-tertiary font-medium">지금: </span>
                    {currentStep.label}
                    {/* 반복 스텝(결재 순회 등) 진행 카운트 — 몇 건 중 몇 건 처리됐는지. */}
                    {currentStep.progress ? (
                      <span className="text-foreground-tertiary tabular-nums">
                        {' '}
                        · {currentStep.progress.done}/{currentStep.progress.total}
                      </span>
                    ) : null}
                    {/* 진행 중 시각 신호 — 화면 변화 없는 긴 자동 구간에서 멈춘 게 아님을
                        보여준다(사용자 피드백 2026-07-06). */}
                    {runningStep ? (
                      <Spinner size={12} className="text-accent ml-1.5 inline-block align-[-2px]" />
                    ) : null}
                  </>
                )
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
        {etaReady ? (
          /* 세그먼트 타임라인 — 자동(accent, 폭=expectedMs 비례)·개입(warning 줄무늬,
             고정폭) 구간 + 현재 위치 마커. expectedMs 가 갖춰진 에이전트에서만 진행 바를
             대체한다(없으면 아래 기존 바 그대로 — 회귀 없음). */
          <EtaTimeline
            segments={etaSegments}
            runStatus={runStatus}
            isPlanOnly={isPlanOnly}
            remainingMs={etaRemainingMs}
            message={etaMessage}
          />
        ) : (
          /* 굵은 진행 바 — 실패는 danger, 개입 대기는 warning 으로 상태를 색으로도 말한다. */
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
        )}
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

// ── 예상 시간 세그먼트 타임라인(진행 헤더용) ─────────────────────────

interface EtaTimelineProps {
  segments: readonly EtaSegment[];
  runStatus: LiveRunStatus;
  /** 실행 전 계획 보기 — 채움·마커 없이 구간 구조만 보여준다. */
  isPlanOnly: boolean;
  /** 미완료 자동 스텝의 남은 예상 합(ms). */
  remainingMs: number;
  /** 타임라인 아래 한 줄 상태 메시지(개입 예고 등). 없으면 생략. */
  message: string | null;
}

/** 개입 세그먼트 줄무늬 — warning 토큰 기반(라이트/다크 공용). */
const INTERVENTION_STRIPES = {
  backgroundImage:
    'repeating-linear-gradient(135deg, color-mix(in oklab, var(--warning) 45%, transparent) 0 3px, transparent 3px 7px)',
} as const;

/**
 * 세그먼트 타임라인 — 색 의미는 기존 어휘 그대로(accent=진행, warning=개입, success=완료).
 * 개입 대기 펄스(animate-pulse)는 globals.css 의 prefers-reduced-motion 전역 블록이
 * 자동으로 무력화하므로 여기서 별도 분기하지 않는다.
 */
function EtaTimeline({ segments, runStatus, isPlanOnly, remainingMs, message }: EtaTimelineProps) {
  const succeeded = runStatus === 'succeeded';
  const failed = runStatus === 'failed';
  const waiting = runStatus === 'waiting_input';
  // 마커 위치 = 각 세그먼트 폭×채움의 합(채움은 항상 앞에서부터 차므로 누적이 곧 위치).
  const markerPct = segments.reduce((acc, seg) => acc + seg.widthPct * seg.fill, 0);
  const showMarker = !isPlanOnly && !succeeded && !failed;
  return (
    <>
      <div
        className="relative mt-2 flex h-2 gap-px overflow-hidden rounded-full"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(succeeded ? 100 : markerPct)}
        aria-label="실행 예상 타임라인"
      >
        {segments.map((seg) => {
          const isWaitingHere =
            waiting && seg.kind === 'intervention' && seg.steps[0].status === 'running';
          // 실행 중인 자동 세그먼트 — 채움 위에 shimmer 를 흘려 "일하는 중"을 보여준다
          // (AI 추천처럼 화면 변화 없는 긴 구간의 정지감 해소, 사용자 피드백 2026-07-06).
          const isRunningAuto =
            runStatus === 'running' &&
            seg.kind === 'auto' &&
            seg.steps.some((s) => s.status === 'running');
          return (
            <div
              key={seg.id}
              className={cn(
                'relative h-full overflow-hidden',
                seg.kind === 'intervention' ? 'bg-warning/10' : 'bg-muted',
                // 개입 대기 중인 개입 세그먼트 펄스 — reduced-motion 은 전역 블록이 차단.
                isWaitingHere && 'animate-pulse',
              )}
              style={{
                width: `${seg.widthPct}%`,
                ...(seg.kind === 'intervention' && !succeeded ? INTERVENTION_STRIPES : null),
              }}
              title={seg.kind === 'intervention' ? '사용자 개입 구간(예상시간 제외)' : undefined}
            >
              <div
                className={cn(
                  'relative h-full overflow-hidden transition-[width] duration-500 ease-out',
                  succeeded
                    ? 'bg-success'
                    : failed
                      ? 'bg-danger'
                      : waiting
                        ? // 개입 대기 — 채움 전체를 warning 으로(구 진행 바의 '입력 대기 = 바
                          // 전체 호박색' 관례 복원, 사용자 피드백 2026-07-06).
                          'bg-warning'
                        : seg.kind === 'intervention'
                          ? 'bg-warning/60'
                          : 'bg-accent',
                )}
                style={{ width: `${(succeeded ? 1 : seg.fill) * 100}%` }}
              >
                {isRunningAuto ? (
                  <span
                    aria-hidden
                    className="animate-eta-shimmer absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-transparent via-white/45 to-transparent"
                  />
                ) : null}
              </div>
            </div>
          );
        })}
        {showMarker ? (
          <span
            aria-hidden
            className="bg-foreground absolute top-0 h-full w-0.5 rounded-full transition-[left] duration-500 ease-out"
            style={{ left: `calc(${Math.min(markerPct, 99.5)}% - 1px)` }}
          />
        ) : null}
      </div>
      {/* 타임라인 캡션 — 좌: 시점별 메시지, 우: 남은 예상(개입 대기면 일시정지 표시). */}
      <div className="mt-1.5 flex items-baseline justify-between gap-2">
        <p className="text-foreground-tertiary min-w-0 truncate text-[11px] tracking-[0.04em]">
          {message ?? ''}
        </p>
        <p className="text-foreground-tertiary shrink-0 text-[11px] tracking-[0.04em] tabular-nums">
          {succeeded ? (
            <span className="text-success font-semibold">완료</span>
          ) : failed ? null : waiting ? (
            <span className="text-warning font-semibold">입력 중 ⏸ — 예상시간 일시정지</span>
          ) : (
            <>
              {isPlanOnly ? '총 예상 ' : '남은 예상 '}
              <span className="text-foreground-secondary font-semibold">
                {formatEta(remainingMs)}
              </span>
            </>
          )}
        </p>
      </div>
    </>
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
          <span className="flex shrink-0 items-center gap-1.5">
            {step.progress ? (
              <span
                className="text-foreground-secondary bg-muted rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
                title="처리 진행(완료/전체 건수)"
              >
                {step.progress.done}/{step.progress.total}
              </span>
            ) : null}
            <span
              className={cn(
                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
                STEP_DOT[step.status],
              )}
            >
              {STEP_LABEL[step.status]}
            </span>
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
