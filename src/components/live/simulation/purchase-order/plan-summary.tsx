'use client';

import { RiArrowLeftLine, RiCheckboxCircleLine, RiFileList3Line } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { formatInteger } from '@/lib/data/format';
import type { PlanSubmit } from '@/lib/live/types';
import type { PlanBom, PlanGate, PlanTotals } from './model';
import { PlanUnitsView } from './plan-units-view';

/**
 * A(헤더 컨텍스트)와 D(하단 요약·확정)를 한 파일에 둔다 — 둘 다 계획 상태를
 * 둘러싼 요약 표면이라 재료가 같다.
 *
 * ⚠ 종전 헤더의 요약 스탯 5개(모듈·부품·총 요청금액·발주단위·미배정)는 2026-08-14 사용자
 *   요청으로 **모듈 풀 하단 선택 바**(module-pool-table)로 옮겼다 — 선택 요약 옆에서 같은
 *   글자 크기로 읽는 편이 시선 이동이 짧다.
 * ⚠ 데모 전용이던 프로젝트 picker·①~④ 자동 단계 스트립·고정 설정 칩은 2026-08-26 삭제 —
 *   데모(2026-08-21 제거) 이후 showFlowSteps=false 로만 불려 전부 죽은 경로였다(git 이력 보존).
 */

// ── A. 헤더 — 프로젝트 컨텍스트 ─────────────────────────────────────────────

interface PlanHeaderProps {
  /** 주입된 BOM 컨텍스트(hitl.plannerBom) — 칩(WBS·장비)의 원천. */
  bom: PlanBom;
  /** 확정 프로젝트 — 개입 1(실행 전 폼)이 이미 확정했으므로 표시 전용이다. */
  project: { code: string; name: string };
}

export function PlanHeader({ bom, project }: PlanHeaderProps) {
  const machine = bom.machines[0];
  return (
    // 프로젝트명이 이 계획서의 '문서 제목'이다(body-lg 승격, 디자인 진단 2026-08-26) —
    // 개입 지시는 위 warning 배너가, 문서 정체성은 이 줄이 맡는 계층 분담.
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <span className="text-foreground text-[length:var(--text-body-lg)] font-semibold">
        {project.name}
      </span>
      <ContextChip>{project.code}</ContextChip>
      {/* WBS 는 주입 BOM 이 프로젝트 1건 단위라 BOM 값을 그대로 보인다. */}
      <ContextChip>WBS {bom.project.wbs}</ContextChip>
      {machine ? (
        <ContextChip>
          장비 {machine.name}
          {bom.machines.length > 1 ? ` 외 ${bom.machines.length - 1}` : ''}
        </ContextChip>
      ) : null}
    </div>
  );
}

function ContextChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="border-border bg-muted/40 text-foreground-secondary rounded-full border px-2 py-0.5 text-[11px] whitespace-nowrap">
      {children}
    </span>
  );
}

// ── D. 하단 요약 + 확정 ──────────────────────────────────────────────────────

interface PlanFooterProps {
  bom: PlanBom;
  totals: PlanTotals;
  assignedModules: number;
  gate: PlanGate;
  onConfirm: () => void;
  /** 제출 전송 중(라이브) — 버튼 비활성 + 스피너. 데모는 미전달(즉시 확정). */
  busy?: boolean;
}

export function PlanFooter({
  bom,
  totals,
  assignedModules,
  gate,
  onConfirm,
  busy = false,
}: PlanFooterProps) {
  const unassigned = bom.modules.length - assignedModules;
  return (
    // 계획서가 길어 확정 버튼이 안 보인다(사용자 지적 2026-08-26) — 개입 탭 패딩(p-4)을 먹어
    // 하단 sticky 바로 붙인다. planner 모드는 side-panel 이 overflow-hidden 을 풀어 둔다.
    <div className="border-border bg-surface/95 sticky bottom-0 z-10 -mx-4 -mb-4 flex flex-col gap-2 rounded-b-[var(--radius-lg)] border-t px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-foreground-secondary text-[length:var(--text-body-sm)]">
          발주단위 <b className="text-foreground tabular-nums">{totals.units}</b> · 거래처 그룹{' '}
          <b className="text-foreground tabular-nums">{totals.vendorGroups}</b>
          {totals.unassignedVendors > 0 ? (
            <span className="text-warning"> (미지정 {totals.unassignedVendors})</span>
          ) : null}{' '}
          · 부품 <b className="text-foreground tabular-nums">{totals.parts}</b> · 총{' '}
          <b className="text-foreground tabular-nums">{formatInteger(totals.amount)}</b>원
          {unassigned > 0 ? (
            <span className="text-foreground-tertiary">
              {' '}
              · 미배정 모듈 {unassigned}개 남음(확정 가능)
            </span>
          ) : null}
        </p>
        {/* 확정은 2단계다(사용자 요청 2026-08-14) — 여기서 바로 제출하지 않고 전체 계획서
            검토 화면으로 넘어가, 거기서 '다음 단계로 진행'을 눌러야 제출된다. */}
        <Button size="sm" onClick={onConfirm} disabled={!gate.ready || busy}>
          {busy ? (
            <>
              <Spinner size={14} />
              전송 중…
            </>
          ) : (
            <>
              <RiFileList3Line size={14} aria-hidden />
              전체 계획서 검토
            </>
          )}
        </Button>
      </div>
      {/* 미충족 항목 힌트 — 버튼이 왜 비활성인지 그 자리에서 알려준다. */}
      {!gate.ready ? (
        <ul className="text-warning flex flex-col gap-0.5 text-[11px]">
          {gate.hints.map((h) => (
            <li key={h}>· {h}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ── 검토 뷰 — 전체 계획서(제출 페이로드 그대로) + 다음 단계 진행 ─────────────

interface PlanReviewViewProps {
  /** 제출될 페이로드 자체를 그린다 — '보이는 것 = 전달되는 것' 보장(buildPlanPayload 산출). */
  payload: PlanSubmit;
  totals: PlanTotals;
  onBack: () => void;
  onProceed: () => void;
  /** 제출 전송 중(라이브) — 진행 버튼 비활성 + 스피너. */
  busy?: boolean;
}

/**
 * 전체 계획서 검토(사용자 요청 2026-08-14) — 확정 직전에 작성 내용 전체를 한 번 더 보여주고,
 * [다음 단계로 진행]을 눌러야 제출된다. 편집 상태는 호출부가 들고 있으므로 [수정으로
 * 돌아가기]는 작성 내용을 그대로 보존한다. 라이브·데모가 공유한다.
 */
export function PlanReviewView({
  payload,
  totals,
  onBack,
  onProceed,
  busy = false,
}: PlanReviewViewProps) {
  return (
    <div className="flex flex-col gap-4">
      {/* 배너 문법 통일(2026-08-26) — 다른 배너 4종과 같은 px-3 py-2.5 + 아이콘 16. */}
      <div className="border-accent/30 bg-accent/5 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
        <RiFileList3Line size={16} aria-hidden className="text-accent mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            전체 계획서 검토 — {payload.project.name}
          </p>
          <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">
            아래 내용이 그대로 다음 단계로 전달됩니다. 수정하려면 돌아가세요.
            {payload.wbs ? ` · WBS ${payload.wbs}` : ''}
          </p>
        </div>
      </div>

      <PlanUnitsView payload={payload} />

      {/* 검토 화면도 길다 — 작성 화면의 PlanFooter 와 같은 sticky 하단 바. */}
      <div className="border-border bg-surface/95 sticky bottom-0 z-10 -mx-4 -mb-4 flex flex-wrap items-center justify-between gap-3 rounded-b-[var(--radius-lg)] border-t px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur">
        <p className="text-foreground-secondary text-[length:var(--text-body-sm)]">
          발주단위 <b className="text-foreground tabular-nums">{totals.units}</b> · 거래처 그룹{' '}
          <b className="text-foreground tabular-nums">{totals.vendorGroups}</b> · 부품{' '}
          <b className="text-foreground tabular-nums">{totals.parts}</b> · 총{' '}
          <b className="text-foreground tabular-nums">{formatInteger(totals.amount)}</b>원
        </p>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={onBack} disabled={busy}>
            <RiArrowLeftLine size={14} aria-hidden />
            수정으로 돌아가기
          </Button>
          <Button size="sm" onClick={onProceed} disabled={busy}>
            {busy ? (
              <>
                <Spinner size={14} />
                전송 중…
              </>
            ) : (
              <>
                <RiCheckboxCircleLine size={14} aria-hidden />
                다음 단계로 진행
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
