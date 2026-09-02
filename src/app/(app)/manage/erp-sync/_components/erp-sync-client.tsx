'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { RiArrowDownSLine, RiErrorWarningLine, RiRefreshLine, RiTimeLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LockedEmptyState } from '@/components/ui/list-state';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { StatusDotPill, StatusPill } from '@/components/ui/status-pill';
import { TableCard, tableRowClass } from '@/components/ui/table-card';
import { Td, Th } from '@/components/ui/table-cell';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, errorMessage, toApiError } from '@/lib/api/client';
import {
  fetchErpSyncOverview,
  fetchErpSyncRuns,
  reassignedCount,
  startErpSync,
  startErpSyncAll,
  updateErpSyncInterval,
  type ErpSyncIntervalOption,
  type ErpSyncItem,
  type ErpSyncKind,
  type ErpSyncOverview,
  type ErpSyncRun,
  type ErpSyncRunRow,
  type ErpSyncSchedule,
} from '@/lib/api/erp-sync';
import { formatDateTime } from '@/lib/data/format';
import { cn } from '@/lib/utils';

type Phase = 'loading' | 'ready' | 'error';

const SYNC_POLL_MS = 3000;
const RUNS_LIMIT = 20;

/** 이력 표에서 kind → 한글 라벨(overview items 의 label 과 동일 어휘). */
const KIND_LABEL: Record<ErpSyncKind, string> = {
  budget_unit: '예산단위',
  project: '프로젝트',
  partner: '거래처',
  org_unit: 'ERP 조직',
};

const TRIGGER_LABEL: Record<ErpSyncRun['trigger'], string> = {
  manual: '수동',
  scheduled: '자동',
};

/** 실행 상태 → StatusPill 라벨·톤. running 은 호출부가 스피너를 덧붙인다. */
const RUN_STATUS: Record<
  ErpSyncRun['status'],
  { label: string; variant: 'info' | 'success' | 'danger' | 'warn' }
> = {
  running: { label: '진행 중', variant: 'info' },
  succeeded: { label: '성공', variant: 'success' },
  failed: { label: '실패', variant: 'danger' },
  skipped: { label: '건너뜀', variant: 'warn' },
};

/** org_unit 반영 요약 — "추가 N · 삭제 K · 재배치 J". applied 가 없으면 null. */
function orgApplySummary(run: ErpSyncRun): string | null {
  if (!run.applied && run.reassigned == null) return null;
  const added = run.applied?.added?.length ?? 0;
  const deleted = run.applied?.deleted?.length ?? 0;
  return `추가 ${added} · 삭제 ${deleted} · 재배치 ${reassignedCount(run)}`;
}

/** 조사 '(으)로' — 받침 없음·ㄹ 받침이면 '로', 그 외 '으로'. "6시간으로" / "하루로" / "3일로". */
function roParticle(word: string): string {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  if (code < 0 || code > 11171) return '으로';
  const jong = code % 28;
  return jong === 0 || jong === 8 ? '로' : '으로';
}

/** 스케줄 비활성 사유 — 필 옆 안내 문구. active 면 null. */
function scheduleReason(s: ErpSyncSchedule): string | null {
  if (s.active) return null;
  if (!s.enabled) return '자동 동기화가 꺼져 있습니다(ERP_SYNC_DAILY_ENABLED).';
  if (!s.serviceAccountConfigured)
    return '서비스 계정(ERP_SYNC_USERID/PASSWORD)이 설정되지 않아 자동 실행이 멈춰 있습니다.';
  return '자동 실행이 멈춰 있습니다.';
}

/** 종료 토스트 문구 — 마지막 실행 결과를 kind 라벨과 함께 알린다. */
function notifyFinished(item: ErpSyncItem): void {
  const run = item.lastRun;
  if (!run) return;
  if (run.status === 'succeeded') {
    const count = run.count != null ? ` · ${run.count.toLocaleString('ko-KR')}건` : '';
    toast.success(`${item.label} 동기화를 완료했습니다${count}`);
  } else if (run.status === 'failed') {
    toast.error(`${item.label} 동기화 실패: ${run.error ?? '원인 미상'}`);
  } else if (run.status === 'skipped') {
    toast.warning(`${item.label} 동기화를 건너뛰었습니다${run.error ? `: ${run.error}` : ''}`);
  }
}

/**
 * ERP 동기화 통합 관리(관리자 전용) — `GET /admin/erp-sync` 현황 + 단건/전체 즉시 동기화 +
 * 최근 이력 20건. 어느 항목이든 진행 중이면 3초 폴링하고, 각 항목이 끝나는 시점에 결과를 토스트한다.
 * 게이트는 UX 보조일 뿐이며 백엔드가 RequireAdmin 으로 최종 강제한다(미만 403).
 */
export function ErpSyncClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [overview, setOverview] = useState<ErpSyncOverview | null>(null);
  const [runs, setRuns] = useState<ErpSyncRunRow[]>([]);
  const [runsError, setRunsError] = useState<ApiError | null>(null);
  const [polling, setPolling] = useState(false);
  // 시작 요청 중인 대상 — 응답이 오기 전 이중 클릭 방지('all' 은 전체 버튼).
  const [starting, setStarting] = useState<ErpSyncKind | 'all' | null>(null);
  // 주기 select 의 낙관적 값 — PATCH 응답 전까지만 유지하고, 끝나면 overview 값으로 돌아간다.
  const [intervalDraft, setIntervalDraft] = useState<Partial<Record<ErpSyncKind, number>>>({});
  const [savingInterval, setSavingInterval] = useState<ErpSyncKind | null>(null);
  // kind 별로 결과를 이미 알린 lastRun.id — 새 id 가 종료 상태로 보이면 토스트한다.
  // running→종료 전이만 보면 한 폴링 간격(3초) 안에 시작·종료한 빠른 실행(전체 동기화의 API 경로
  // kind)을 놓친다(2026-09-02 실측: 프로젝트 토스트 누락).
  const announcedRef = useRef<Map<ErpSyncKind, number>>(new Map());

  /** 현재 items 의 lastRun 을 전부 '알린 것'으로 기록 — 진입 시 과거 결과를 토스트하지 않기 위해. */
  const markAllAnnounced = (data: ErpSyncOverview) => {
    for (const item of data.items) {
      if (item.lastRun) announcedRef.current.set(item.kind, item.lastRun.id);
    }
  };

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await fetchErpSyncRuns(undefined, RUNS_LIMIT));
      setRunsError(null);
    } catch (err) {
      setRunsError(toApiError(err));
    }
  }, []);

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      const data = await fetchErpSyncOverview();
      setOverview(data);
      markAllAnnounced(data);
      if (data.items.some((i) => i.running)) setPolling(true);
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  // 진행 중 폴링 — 아직 알리지 않은 종료 실행을 kind 별로 토스트하고, 전부 끝나면 이력을 갱신.
  useEffect(() => {
    if (!polling) return;
    let active = true;
    const tick = async () => {
      try {
        const data = await fetchErpSyncOverview();
        if (!active) return;
        setOverview(data);
        let anyRunning = false;
        for (const item of data.items) {
          if (item.running) anyRunning = true;
          const run = item.lastRun;
          if (!run || run.status === 'running') continue;
          if (announcedRef.current.get(item.kind) === run.id) continue;
          announcedRef.current.set(item.kind, run.id);
          notifyFinished(item);
        }
        if (!anyRunning) {
          setPolling(false);
          void loadRuns();
        }
      } catch {
        /* 일시 오류는 다음 tick 에서 재시도 */
      }
    };
    const t = setInterval(() => void tick(), SYNC_POLL_MS);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [polling, loadRuns]);

  const afterStart = async () => {
    // 시작 직후 현황을 한 번 당겨 running 표시를 즉시 맞춘다(첫 tick 3초를 안 기다림).
    // 여기서 announced 를 갱신하지 않는다 — 새 run 의 결과는 폴링 tick 이 알린다.
    try {
      setOverview(await fetchErpSyncOverview());
    } catch {
      /* 폴링이 이어받는다 */
    }
    setPolling(true);
    void loadRuns();
  };

  const runOne = async (kind: ErpSyncKind) => {
    setStarting(kind);
    try {
      await startErpSync(kind);
      toast.success(`${KIND_LABEL[kind]} 동기화를 시작했습니다.`);
      await afterStart();
    } catch (err) {
      toast.error(errorMessage(err, '동기화를 시작하지 못했습니다.'));
    } finally {
      setStarting(null);
    }
  };

  /** 주기 변경 — 즉시 PATCH. 성공이면 토스트 후 현황 재조회, 실패면 이전 값으로 되돌리고 오류 토스트. */
  const changeInterval = async (item: ErpSyncItem, seconds: number) => {
    if (seconds === item.intervalSeconds) return;
    setIntervalDraft((d) => ({ ...d, [item.kind]: seconds }));
    setSavingInterval(item.kind);
    try {
      await updateErpSyncInterval(item.kind, seconds);
      const label =
        overview?.schedule.intervalOptions.find((o) => o.seconds === seconds)?.label ??
        `${seconds}초`;
      toast.success(`${item.label} 주기를 ${label}${roParticle(label)} 저장했습니다`);
      try {
        setOverview(await fetchErpSyncOverview());
      } catch {
        /* 재조회 실패는 다음 진입/폴링에서 회복 — 저장 자체는 성공 */
      }
    } catch (err) {
      toast.error(errorMessage(err, '주기를 저장하지 못했습니다.'));
    } finally {
      // 성공이면 재조회된 overview 값이, 실패면 원래 item.intervalSeconds 가 다시 보인다.
      setIntervalDraft((d) =>
        Object.fromEntries(Object.entries(d).filter(([k]) => k !== item.kind)),
      );
      setSavingInterval(null);
    }
  };

  const runAll = async () => {
    setStarting('all');
    try {
      await startErpSyncAll();
      toast.success('4종 전체 동기화를 시작했습니다.');
      await afterStart();
    } catch (err) {
      toast.error(errorMessage(err, '전체 동기화를 시작하지 못했습니다.'));
    } finally {
      setStarting(null);
    }
  };

  if (!isAdmin) {
    return <LockedEmptyState description="ERP 동기화 관리는 관리자 이상만 사용할 수 있습니다." />;
  }

  if (phase === 'loading') {
    return (
      <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
        <Spinner size={18} />
        동기화 현황을 불러오는 중…
      </div>
    );
  }

  if (phase === 'error' || !overview) {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title="동기화 현황을 불러오지 못했습니다"
        description={errorMessage(error)}
        action={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            다시 시도
          </Button>
        }
      />
    );
  }

  const { schedule, credentialSource, items } = overview;
  const anyRunning = items.some((i) => i.running);
  const canStart = credentialSource !== null && !anyRunning && starting === null;

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <ScheduleCard schedule={schedule} credentialSource={credentialSource} />

      {/* 4종 현황 — 섹션 제목 + 전체 동기화 */}
      <section aria-labelledby="erp-sync-items" className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="grid gap-0.5">
            <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
              동기화 대상
            </p>
            <h2 id="erp-sync-items" className="text-base font-semibold tracking-tight">
              카탈로그 4종
            </h2>
          </div>
          <Button
            size="sm"
            onClick={() => void runAll()}
            disabled={!canStart}
            title={credentialSource === null ? 'ERP 자격증명이 없어 실행할 수 없습니다' : undefined}
          >
            {starting === 'all' || anyRunning ? (
              <Spinner size={14} />
            ) : (
              <RiRefreshLine size={14} aria-hidden />
            )}
            {anyRunning ? '동기화 진행 중…' : '전체 동기화'}
          </Button>
        </div>

        <TableCard
          minWidth={1000}
          ariaLabel="ERP 동기화 현황"
          head={
            <tr>
              <Th>항목</Th>
              <Th className="text-right">건수</Th>
              <Th>주기</Th>
              <Th>마지막 성공 동기화</Th>
              <Th>최근 실행</Th>
              <Th className="w-28 text-right">
                <span className="sr-only">동기화</span>
              </Th>
            </tr>
          }
        >
          {items.map((item) => (
            <tr key={item.kind} className={cn(tableRowClass, 'align-top')}>
              <Td className="align-top">
                <span className="text-foreground block font-medium">{item.label}</span>
                <span className="text-foreground-tertiary block font-mono text-[11px]">
                  {item.kind}
                </span>
              </Td>
              <Td className="text-foreground text-right align-top tabular-nums">
                {item.count.toLocaleString('ko-KR')}
              </Td>
              <Td className="align-top">
                <IntervalCell
                  item={item}
                  options={schedule.intervalOptions}
                  value={intervalDraft[item.kind] ?? item.intervalSeconds}
                  saving={savingInterval === item.kind}
                  onChange={(seconds) => void changeInterval(item, seconds)}
                />
              </Td>
              <Td className="text-foreground-secondary align-top tabular-nums">
                {item.lastSuccessAt ? (
                  <time dateTime={item.lastSuccessAt} title={item.lastSuccessAt}>
                    {formatDateTime(item.lastSuccessAt)}
                  </time>
                ) : (
                  <span className="text-foreground-tertiary">기록 없음</span>
                )}
              </Td>
              <Td className="align-top">
                <LastRunCell
                  run={item.lastRun}
                  running={item.running}
                  isOrg={item.kind === 'org_unit'}
                />
              </Td>
              <Td className="text-right align-top">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void runOne(item.kind)}
                  disabled={!canStart}
                  title={
                    credentialSource === null ? 'ERP 자격증명이 없어 실행할 수 없습니다' : undefined
                  }
                >
                  {item.running || starting === item.kind ? (
                    <Spinner size={14} />
                  ) : (
                    <RiRefreshLine size={14} aria-hidden />
                  )}
                  {item.running ? '진행 중' : '동기화'}
                </Button>
              </Td>
            </tr>
          ))}
        </TableCard>
      </section>

      <RunsHistory runs={runs} error={runsError} onRetry={() => void loadRuns()} />
    </div>
  );
}

/** 상단 자동 동기화 카드 — 상태 필·실행 방식(항목별 주기)·즉시 동기화 자격증명. 주기 자체는 표의 열이다. */
function ScheduleCard({
  schedule,
  credentialSource,
}: {
  schedule: ErpSyncSchedule;
  credentialSource: ErpSyncOverview['credentialSource'];
}) {
  const reason = scheduleReason(schedule);
  return (
    <SectionCard
      caption="스케줄"
      title="자동 동기화"
      description="항목별 주기로 백그라운드 실행 · 마지막 실행 기준"
      action={<StatusDotPill active={schedule.active} />}
      className="min-w-0"
    >
      {reason ? (
        <p className="border-warning/40 bg-warning/10 text-warning rounded-[var(--radius-md)] border px-3 py-2 text-xs leading-relaxed">
          {reason}
        </p>
      ) : null}
      <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
        <Fact label="실행 방식">
          <span className="text-foreground text-sm leading-relaxed">
            각 항목의 마지막 실행 시작 시각에서 주기가 지나면 다시 실행합니다. 실패해도 주기 뒤에
            재시도하고, 실행 이력이 없으면 즉시 대상입니다. 주기는 아래 표에서 항목마다 고릅니다.
          </span>
          <span className="text-foreground-tertiary block text-xs">{schedule.tz} 기준</span>
        </Fact>
        <Fact label="즉시 동기화 자격증명">
          <CredentialSource source={credentialSource} />
        </Fact>
      </dl>
    </SectionCard>
  );
}

/** 주기 셀 — 네이티브 select(테두리+배경, 포커스 링 없음) + 그 아래 다음 실행 시각. */
function IntervalCell({
  item,
  options,
  value,
  saving,
  onChange,
}: {
  item: ErpSyncItem;
  options: ErpSyncIntervalOption[];
  value: number;
  saving: boolean;
  onChange: (seconds: number) => void;
}) {
  // 저장값이 옵션 밖(서버 기본값 변경 등)이면 그 값도 보여야 select 가 빈 칸이 되지 않는다.
  const known = options.some((o) => o.seconds === value);
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="relative inline-flex w-[7.5rem]">
        <select
          aria-label={`${item.label} 동기화 주기`}
          value={value}
          disabled={saving}
          onChange={(e) => onChange(Number(e.target.value))}
          className={cn(
            'border-border bg-surface text-foreground h-8 w-full appearance-none rounded-sm border py-1 pr-7 pl-2.5 text-xs font-medium transition-colors outline-none',
            'hover:bg-muted focus:border-accent focus:bg-accent/5 focus-visible:outline-none',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
        >
          {!known ? <option value={value}>{value}초</option> : null}
          {options.map((o) => (
            <option key={o.seconds} value={o.seconds}>
              {o.label}
            </option>
          ))}
        </select>
        {saving ? (
          <Spinner
            size={12}
            className="text-foreground-tertiary pointer-events-none absolute top-1/2 right-2 -translate-y-1/2"
          />
        ) : (
          <RiArrowDownSLine
            aria-hidden
            className="text-foreground-tertiary pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2"
          />
        )}
      </span>
      {item.nextRunAt ? (
        <time
          dateTime={item.nextRunAt}
          title={item.nextRunAt}
          className="text-foreground-tertiary flex items-center gap-1 text-[11px] tabular-nums"
        >
          <RiTimeLine size={12} aria-hidden />
          다음 실행 {formatDateTime(item.nextRunAt)}
        </time>
      ) : (
        <span className="text-foreground-tertiary text-[11px]">자동 실행 없음</span>
      )}
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid content-start gap-1">
      <dt className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
        {label}
      </dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

/** 이 관리자가 '동기화'를 누르면 어떤 자격증명이 쓰이는지 — 없으면 버튼이 비활성이라 안내를 붙인다. */
function CredentialSource({ source }: { source: ErpSyncOverview['credentialSource'] }) {
  if (source === 'session') {
    return (
      <>
        <StatusPill label="세션 ERP 계정" variant="info" />
        <span className="text-foreground-tertiary mt-1 block text-xs">
          로그인한 관리자의 ERP 계정으로 실행됩니다.
        </span>
      </>
    );
  }
  if (source === 'service') {
    return (
      <>
        <StatusPill label="서비스 계정" variant="success" />
        <span className="text-foreground-tertiary mt-1 block text-xs">
          자동 동기화와 같은 서비스 계정으로 실행됩니다.
        </span>
      </>
    );
  }
  return (
    <>
      <StatusPill label="없음" variant="danger" />
      <span className="text-foreground-secondary mt-1 block text-xs leading-relaxed">
        ERP 계정으로 로그인하거나 서비스 계정을 설정해야 즉시 동기화를 실행할 수 있습니다.
      </span>
    </>
  );
}

/** 최근 실행 셀 — 상태 필 + 트리거·실행자 + 오류/반영 요약. */
function LastRunCell({
  run,
  running,
  isOrg,
}: {
  run: ErpSyncRun | null;
  running: boolean;
  isOrg: boolean;
}) {
  if (!run) {
    return <span className="text-foreground-tertiary text-xs">실행 이력 없음</span>;
  }
  const status = running ? RUN_STATUS.running : RUN_STATUS[run.status];
  const summary = isOrg ? orgApplySummary(run) : null;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusPill
          label={status.label}
          variant={status.variant}
          className={cn(running && 'gap-1')}
        />
        {running ? <Spinner size={12} className="text-accent" /> : null}
        <span className="text-foreground-secondary text-xs">
          {TRIGGER_LABEL[run.trigger]}
          {run.trigger === 'manual' && run.actorName ? ` · ${run.actorName}` : ''}
        </span>
        <time
          dateTime={run.startedAt}
          title={run.startedAt}
          className="text-foreground-tertiary text-xs tabular-nums"
        >
          {formatDateTime(run.startedAt)}
        </time>
      </div>
      {summary ? <span className="text-foreground-secondary text-xs">{summary}</span> : null}
      {run.error ? (
        <span className="text-danger text-xs leading-relaxed break-words whitespace-pre-line">
          {run.error}
        </span>
      ) : null}
    </div>
  );
}

/** 하단 최근 실행 이력 — 20건, kind·트리거·상태·시작/종료·건수·오류. */
function RunsHistory({
  runs,
  error,
  onRetry,
}: {
  runs: ErpSyncRunRow[];
  error: ApiError | null;
  onRetry: () => void;
}) {
  return (
    <SectionCard
      caption="이력"
      title="최근 실행"
      description={`최근 ${RUNS_LIMIT}건 — 수동·자동 실행이 모두 남습니다.`}
      className="min-w-0"
    >
      {error ? (
        <EmptyState
          compact
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="이력을 불러오지 못했습니다"
          description={errorMessage(error)}
          action={
            <Button variant="secondary" size="sm" onClick={onRetry}>
              다시 시도
            </Button>
          }
        />
      ) : runs.length === 0 ? (
        <EmptyState
          compact
          title="아직 실행 이력이 없습니다"
          description="동기화를 실행하면 여기에 기록됩니다."
        />
      ) : (
        <div className="border-border overflow-x-auto rounded-[var(--radius-md)] border">
          <table
            aria-label="최근 동기화 실행 이력"
            className="w-full min-w-[760px] text-left text-xs"
          >
            <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
              <tr>
                <Th className="py-2">항목</Th>
                <Th className="py-2">트리거</Th>
                <Th className="py-2">상태</Th>
                <Th className="py-2">시작</Th>
                <Th className="py-2">종료</Th>
                <Th className="py-2 text-right">건수</Th>
                <Th className="py-2">오류</Th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const status = RUN_STATUS[r.status];
                return (
                  <tr key={r.id} className={tableRowClass}>
                    <Td className="text-foreground py-2 font-medium whitespace-nowrap">
                      {KIND_LABEL[r.kind] ?? r.kind}
                    </Td>
                    <Td className="text-foreground-secondary py-2 whitespace-nowrap">
                      {TRIGGER_LABEL[r.trigger]}
                      {r.trigger === 'manual' && r.actorName ? ` · ${r.actorName}` : ''}
                    </Td>
                    <Td className="py-2">
                      <StatusPill label={status.label} variant={status.variant} />
                    </Td>
                    <Td className="text-foreground-secondary py-2 whitespace-nowrap tabular-nums">
                      <time dateTime={r.startedAt} title={r.startedAt}>
                        {formatDateTime(r.startedAt)}
                      </time>
                    </Td>
                    <Td className="text-foreground-secondary py-2 whitespace-nowrap tabular-nums">
                      {r.finishedAt ? (
                        <time dateTime={r.finishedAt} title={r.finishedAt}>
                          {formatDateTime(r.finishedAt)}
                        </time>
                      ) : (
                        '-'
                      )}
                    </Td>
                    <Td className="text-foreground py-2 text-right tabular-nums">
                      {r.count != null ? r.count.toLocaleString('ko-KR') : '-'}
                    </Td>
                    <Td className="py-2">
                      {r.error ? (
                        <span className="text-danger block max-w-[360px] leading-relaxed break-words whitespace-pre-line">
                          {r.error}
                        </span>
                      ) : r.kind === 'org_unit' ? (
                        <span className="text-foreground-tertiary">
                          {orgApplySummary(r) ?? '-'}
                        </span>
                      ) : (
                        <span className="text-foreground-tertiary">-</span>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
