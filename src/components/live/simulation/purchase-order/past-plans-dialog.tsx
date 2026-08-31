'use client';

import { useCallback, useEffect, useState } from 'react';
import { RiArrowLeftLine, RiFileList3Line, RiHistoryLine, RiSearchLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { ListStatePanel } from '@/components/ui/list-state';
import { Pagination } from '@/components/ui/pagination';
import { Spinner } from '@/components/ui/spinner';
import { TableCard, tableRowClass } from '@/components/ui/table-card';
import { Td, Th } from '@/components/ui/table-cell';
import { usePagedQuery } from '@/hooks/use-paged-query';
import { errorMessage } from '@/lib/api/client';
import { fetchPlan, fetchPlans, type PlanRecord } from '@/lib/api/purchase-order-plans';
import { formatDateTime, formatInteger } from '@/lib/data/format';
import { cn } from '@/lib/utils';
import { PlanUnitsView } from './plan-units-view';

const PAGE_SIZE = 20;

/**
 * 이전 계획서 — 구매발주 에이전트가 저장한 계획서(PlanSubmit) 목록·상세를 읽기 전용으로
 * 보는 다이얼로그. 버튼이 열림 상태를 소유한다(라이브 여부와 무관, 화면 이동 없음).
 */
export function PastPlansButton() {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => setOpen(true)}
        data-testid="past-plans-button"
      >
        <RiHistoryLine size={14} aria-hidden />
        이전 계획서
      </Button>
      <Dialog
        open={open}
        onClose={close}
        title="이전 계획서"
        description="저장된 구매발주 계획서를 최신순으로 보여줍니다."
        size="xl"
      >
        <DialogBody>{open ? <PastPlansContent /> : null}</DialogBody>
      </Dialog>
    </>
  );
}

function PastPlansContent() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  if (selectedId) {
    return <PlanDetail id={selectedId} onBack={() => setSelectedId(null)} />;
  }
  return <PlanList onSelect={setSelectedId} />;
}

function PlanList({ onSelect }: { onSelect: (id: string) => void }) {
  const [page, setPage] = useState(1);
  // 검색(2026-08-31) — 입력은 즉시, 서버 질의는 400ms 디바운스(프로젝트명·코드·WBS 부분일치).
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [search]);
  const fetchPage = useCallback(
    async (args: { limit: number; offset: number }) => {
      const { items, total } = await fetchPlans({ ...args, q: query });
      return { rows: items, total };
    },
    [query],
  );
  const { rows, total, phase, error, reload } = usePagedQuery(fetchPage, {
    page,
    pageSize: PAGE_SIZE,
    setPage,
  });

  // 날짜별 그루핑(2026-08-31) — 최신순 유지, 저장 일시의 로컬 날짜가 바뀌는 지점에 그룹 헤더 행.
  const dayOf = (iso: string | null) =>
    iso
      ? new Date(iso).toLocaleDateString('ko-KR', {
          year: 'numeric',
          month: 'long',
          day: 'numeric',
          weekday: 'short',
        })
      : '날짜 미상';

  return (
    <div className="flex flex-col gap-3">
      <div className="relative w-full sm:max-w-xs">
        <RiSearchLine
          size={14}
          aria-hidden
          className="text-foreground-tertiary pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2"
        />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="프로젝트명·코드·WBS 검색"
          aria-label="이전 계획서 검색"
          className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-full rounded-sm border pr-2 pl-8 text-[length:var(--text-body-sm)] outline-none focus-visible:ring-2"
        />
      </div>
      <ListStatePanel
        phase={phase}
        error={error}
        loadingLabel="계획서를 불러오는 중…"
        errorTitle="계획서를 불러오지 못했습니다"
        onRetry={reload}
        isEmpty={rows.length === 0}
        empty={{
          icon: <RiFileList3Line size={18} aria-hidden />,
          title: query ? '검색 결과가 없습니다' : '저장된 계획서가 없습니다',
          description: query
            ? '프로젝트명·코드·WBS 로 검색합니다. 검색어를 바꿔 보세요.'
            : '구매발주 실행에서 계획서를 확정하면 여기에 쌓입니다.',
        }}
      >
      <TableCard
        minWidth={760}
        ariaLabel="이전 계획서 목록"
        head={
          <tr>
            <Th>프로젝트</Th>
            <Th>WBS</Th>
            <Th className="text-right">발주단위</Th>
            <Th className="text-right">합계 금액</Th>
            <Th>실행자</Th>
            <Th>저장 일시</Th>
          </tr>
        }
      >
        {rows.map((r, i) => [
          dayOf(r.createdAt) !== dayOf(rows[i - 1]?.createdAt ?? null) || i === 0 ? (
            <tr key={`day-${r.id}`} data-testid="past-plans-day">
              {/* Td 는 colSpan 을 안 받는다 — 그룹 헤더 행만 원시 td. */}
              <td
                colSpan={6}
                className="bg-muted/40 text-foreground-secondary border-border/60 border-t px-3 py-1.5 text-[11px] font-semibold"
              >
                {dayOf(r.createdAt)}
              </td>
            </tr>
          ) : null,
          <tr
            key={r.id}
            data-testid="past-plans-row"
            onClick={() => onSelect(r.id)}
            className={cn(tableRowClass, 'cursor-pointer')}
          >
            <Td>
              <span className="text-foreground font-medium">{r.project.name}</span>
              <span className="text-foreground-tertiary ml-1.5 text-[11px]">{r.project.code}</span>
            </Td>
            <Td className="text-foreground-secondary tabular-nums">{r.wbs || '—'}</Td>
            <Td className="text-foreground-secondary text-right tabular-nums">{r.unitCount}</Td>
            <Td className="text-foreground-secondary text-right whitespace-nowrap tabular-nums">
              {formatInteger(r.totalAmount)}
            </Td>
            <Td className="text-foreground-secondary">{r.userDisplayName ?? r.userId}</Td>
            <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
              {formatDateTime(r.createdAt)}
            </Td>
          </tr>,
        ])}
      </TableCard>
        {total > PAGE_SIZE ? (
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        ) : null}
      </ListStatePanel>
    </div>
  );
}

function PlanDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [record, setRecord] = useState<PlanRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRecord(null);
    setError(null);
    fetchPlan(id)
      .then((r) => {
        if (!cancelled) setRecord(r);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorMessage(e, '계획서를 불러오지 못했습니다.'));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <div className="flex flex-col gap-4" data-testid="past-plan-detail">
      <div>
        <Button variant="secondary" size="sm" onClick={onBack}>
          <RiArrowLeftLine size={14} aria-hidden />
          목록
        </Button>
      </div>
      {error ? (
        <p className="text-danger text-[length:var(--text-body-sm)]">{error}</p>
      ) : !record ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} />
          계획서를 불러오는 중…
        </div>
      ) : (
        <>
          <PlanInfo record={record} />
          <PlanUnitsView payload={record.plan} />
        </>
      )}
    </div>
  );
}

function PlanInfo({ record }: { record: PlanRecord }) {
  const bom = record.bomSummary;
  return (
    <div className="border-border bg-muted/30 rounded-[var(--radius-md)] border px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-foreground text-[length:var(--text-body-lg)] font-semibold">
          {record.project.name}
        </span>
        <span className="text-foreground-tertiary text-[11px]">{record.project.code}</span>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[length:var(--text-body-sm)] sm:grid-cols-3">
        <InfoItem label="WBS" value={record.wbs || '—'} />
        <InfoItem label="저장 일시" value={formatDateTime(record.createdAt)} />
        <InfoItem label="실행자" value={record.userDisplayName ?? record.userId} />
        <InfoItem label="발주단위" value={`${record.unitCount}건`} />
        <InfoItem label="합계 금액" value={`${formatInteger(record.totalAmount)}원`} />
        {bom ? (
          <InfoItem
            label="BOM 요약"
            value={`장비 ${bom.machines} · 모듈 ${bom.modules} · 부품 ${bom.parts} (구매대상 ${bom.purchasableParts})`}
          />
        ) : null}
      </dl>
      {record.runId ? (
        <p className="text-foreground-tertiary mt-2 text-[11px] tabular-nums">run {record.runId}</p>
      ) : null}
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-foreground-tertiary text-[11px]">{label}</dt>
      <dd className="text-foreground tabular-nums">{value}</dd>
    </div>
  );
}
