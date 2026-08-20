'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RiCheckLine, RiErrorWarningLine, RiTableLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyNote } from '@/components/ui/empty-note';
import { Spinner } from '@/components/ui/spinner';
import { InvoiceBudgetCombobox } from '@/components/live/invoice-budget-combobox';
import { fetchCatalog } from '@/lib/api/me-codes';
import type {
  BudgetUnitOption,
  GridRowSubmit,
  InvoiceGridRow,
  LiveHitl,
  SplitPlanRowSubmit,
} from '@/lib/live/types';
import { cn } from '@/lib/utils';
import { CatalogCombobox, projectCodeLabel, type ComboOption } from './pre-run/catalog-combobox';
import {
  formatWon,
  newSplitRow,
  parseAmount,
  type SplitMode,
  type SplitRow,
} from './pre-run/tax-invoice/model';
import { SplitPlanSection, splitPlanComplete } from './pre-run/tax-invoice/split-plan-section';
import { StatTile } from './pre-run/tax-invoice/ui';

/**
 * 계산서 개입(kind='invoice-grid') — 세금계산서 결의서의 **발행 후** 경로에서 ERP
 * '전자세금계산서/전자계산서' 팝업이 준 계산서 목록을 보여주고, 처리할 행을 고르게 한다.
 *
 * 실행 전 폼이 아니라 여기서 받는 이유(PROCESS.md D1, 사용자 재확정 2026-08-20): 조회 결과가
 * 복수일 수 있어 **어떤 행을 처리할지·행마다 무엇을 넣을지**를 실행 전에 정할 수 없다.
 * 그래서 법인카드 그리드(LiveGridCard)와 같은 개입 모델을 쓰되 계산서에 맞게 단순화했다:
 *  - 행 **선택**(기본 미선택)이 처리 범위 — 고른 행만 결의서에 실린다.
 *  - 고른 행에만 예산단위·프로젝트·적요를 채운다(일괄 지정 지원).
 *  - 분할(증빙 11/13)이면 계산서 **1행**만 고르고 그 아래 분할 계획을 함께 받는다.
 *
 * LiveGridCard 는 법인카드 전용이라 손대지 않는다 — 공용 프리미티브(combo-popover)와
 * 분할 계획 섹션(pre-run/tax-invoice/split-plan-section)만 공유한다.
 */

interface InvoiceGridCardProps {
  hitl: LiveHitl;
  /** 행 + 분할 계획 제출 — 부모가 sendRows(hitl.id, rows, splitPlan) 로 바인딩. */
  onSubmit: (rows: GridRowSubmit[], splitPlan?: SplitPlanRowSubmit[]) => Promise<boolean>;
}

/** 행별 사용자 입력. selected=false 면 이 행은 처리하지 않는다(제출 시 skip). */
interface RowEdit {
  selected: boolean;
  budgetUnitCode: string;
  projectCode: string;
  projectName: string;
  note: string;
}

const EMPTY_EDIT: RowEdit = {
  selected: false,
  budgetUnitCode: '',
  projectCode: '',
  projectName: '',
  note: '',
};

/** 프로젝트 카탈로그 검색 건수(WBS 행 단위라 넉넉히) — 실행 전 폼과 같은 값. */
const PROJECT_SEARCH_LIMIT = 40;

/** 프로젝트 카탈로그 code('PJT_NO|WBS_NO' 합성) → 제출용 WBS. 합성이 아니면 그대로. */
function wbsOf(code: string): string {
  const parts = code.split('|');
  return parts.length > 1 && parts[1] ? parts[1] : code;
}

/** 계산서 취소분인지 — DATA_FG_NM 에 '취소'가 있거나 합계가 음수. */
function isCancelled(r: InvoiceGridRow): boolean {
  return (r.dataKind ?? '').includes('취소') || (r.sumAmount ?? 0) < 0;
}

/** 금액 표시(원 단위 정수). 값이 없으면 빈 칸 — 0 과 미수신을 구분한다. */
function amountText(n?: number): string {
  return typeof n === 'number' ? formatWon(n) : '';
}

function initEdits(rows: readonly InvoiceGridRow[]): Record<number, RowEdit> {
  return Object.fromEntries(rows.map((r) => [r.no, { ...EMPTY_EDIT }]));
}

export function InvoiceGridCard({ hitl, onSubmit }: InvoiceGridCardProps) {
  const rows = hitl.invoiceRows ?? [];
  const split = hitl.split === true;
  const bFavList = hitl.budgetUnits?.favorites ?? [];
  const bMineList = hitl.budgetUnits?.mine ?? [];
  const bAllList = hitl.budgetUnits?.all ?? [];

  const [edits, setEdits] = useState<Record<number, RowEdit>>(() => initEdits(rows));
  const [splitRows, setSplitRows] = useState<readonly SplitRow[]>([]);
  const [splitMode, setSplitMode] = useState<SplitMode>('amount');
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // md 기준으로 표/카드 중 한쪽만 마운트 — CSS 숨김만으로는 두 골격의 행 편집 컨트롤이 모두
  // 살아 있어 콤보 수가 2배가 된다. 첫 렌더(SSR·hydration)는 null 로 두어 CSS 분기에 맡긴다.
  const [isDesktopLayout, setIsDesktopLayout] = useState<boolean | null>(null);
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const sync = () => setIsDesktopLayout(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  // 편집 상태는 hitl.id 기준으로만 초기화 — 같은 개입의 재렌더에선 입력을 유지한다.
  const idRef = useRef<string | null>(null);
  useEffect(() => {
    if (idRef.current === hitl.id) return;
    idRef.current = hitl.id;
    setEdits(initEdits(hitl.invoiceRows ?? []));
    setSplitRows(hitl.split === true ? [newSplitRow(), newSplitRow()] : []);
    setSubmitted(false);
    setError(null);
  }, [hitl.id, hitl.invoiceRows, hitl.split]);

  const disabled = busy || submitted;

  const budgetByCode = useMemo(() => {
    const m = new Map<string, BudgetUnitOption>();
    for (const o of [...bFavList, ...bMineList, ...bAllList]) if (!m.has(o.code)) m.set(o.code, o);
    return m;
  }, [hitl.budgetUnits]); // eslint-disable-line react-hooks/exhaustive-deps

  // 그룹 간 중복 제거: 자주쓰는 → 내 부서 → 전체 순으로 앞 그룹에 나온 코드는 뒤에서 제외.
  const bMineExclFav = useMemo(() => {
    const favCodes = new Set(bFavList.map((o) => o.code));
    return bMineList.filter((o) => !favCodes.has(o.code));
  }, [hitl.budgetUnits]); // eslint-disable-line react-hooks/exhaustive-deps

  const bAllExclFav = useMemo(() => {
    const shown = new Set([...bFavList, ...bMineList].map((o) => o.code));
    return bAllList.filter((o) => !shown.has(o.code));
  }, [hitl.budgetUnits]); // eslint-disable-line react-hooks/exhaustive-deps

  // 프로젝트는 프레임의 자주쓰는 + 카탈로그 API 검색으로 고른다(카드 그리드의 sendQuery
  // 왕복과 달리 ERP 라이브 조회가 필요 없다 — 실행 전 폼과 같은 경로).
  const projectFavs: ComboOption[] = useMemo(
    () =>
      (hitl.projects?.favorites ?? []).map((p) => ({
        code: p.code,
        name: p.name,
        codeLabel: projectCodeLabel(p.code),
        sub: p.wbsNm ?? p.wbsNo ?? undefined,
      })),
    [hitl.projects],
  );

  const searchProjects = useCallback(async (q: string): Promise<ComboOption[]> => {
    const page = await fetchCatalog({
      kind: 'project',
      q,
      dept: 'all',
      limit: PROJECT_SEARCH_LIMIT,
    });
    return page.items.map((c) => ({
      code: c.code,
      name: c.name,
      codeLabel: projectCodeLabel(c.code, c.extra?.pjtNo ?? undefined),
      sub: c.extra?.wbsNm ?? c.extra?.wbsNo ?? undefined,
    }));
  }, []);

  const setRow = useCallback((no: number, patch: Partial<RowEdit>) => {
    setEdits((prev) => ({ ...prev, [no]: { ...(prev[no] ?? EMPTY_EDIT), ...patch } }));
  }, []);

  /**
   * 행 선택. 분할(11/13)은 계산서 **1행**만 처리할 수 있어(ERP 분할처리 팝업이 한 전표의
   * 금액을 쪼개는 구조) 다른 행 선택을 해제한다 — 컨트롤도 라디오로 렌더해 규칙을 드러낸다.
   */
  const setSelected = useCallback(
    (no: number, value: boolean) => {
      setEdits((prev) => {
        if (split && value) {
          return Object.fromEntries(
            Object.entries(prev).map(([k, e]) => [k, { ...e, selected: Number(k) === no }]),
          );
        }
        return { ...prev, [no]: { ...(prev[no] ?? EMPTY_EDIT), selected: value } };
      });
    },
    [split],
  );

  const selectAll = (value: boolean) => {
    setEdits((prev) =>
      Object.fromEntries(Object.entries(prev).map(([k, e]) => [k, { ...e, selected: value }])),
    );
  };

  /** 일괄 지정 — 선택된 행에만 적용한다(미선택 행은 처리 대상이 아니다). */
  const applySelected = (patch: Partial<RowEdit>) => {
    setEdits((prev) => {
      const next = { ...prev };
      for (const r of rows) if (next[r.no]?.selected) next[r.no] = { ...next[r.no], ...patch };
      return next;
    });
  };

  const selectedRows = rows.filter((r) => edits[r.no]?.selected);
  const selectedCount = selectedRows.length;
  const supplySum = selectedRows.reduce((s, r) => s + (r.supplyAmount ?? 0), 0);
  const taxSum = selectedRows.reduce((s, r) => s + (r.taxAmount ?? 0), 0);
  const totalSum = selectedRows.reduce((s, r) => s + (r.sumAmount ?? 0), 0);

  const isRowValid = (no: number): boolean => {
    const e = edits[no];
    return !!e && e.budgetUnitCode !== '' && e.note.trim().length > 0;
  };
  const validCount = selectedRows.filter((r) => isRowValid(r.no)).length;
  const firstInvalidNo = selectedRows.find((r) => !isRowValid(r.no))?.no ?? null;

  // 분할 기준금액 = 선택 행의 공급가액(D7 — VAT 미포함). 선택이 바뀌면 계획의 비율·잔액
  // 미리보기가 실제 금액을 따라가야 하므로 참고 총액을 파생값으로 동기화한다.
  const splitBase = split && selectedCount === 1 ? (selectedRows[0].supplyAmount ?? 0) : 0;
  const [refTotal, setRefTotal] = useState('');
  useEffect(() => {
    setRefTotal(splitBase === 0 ? '' : String(splitBase));
  }, [splitBase]);

  // 선택 컨트롤이 분할일 때 라디오라 selectedCount 는 0 또는 1 — 1행 규칙은 입력 단계에서 지켜진다.
  const splitVisible = split && selectedCount === 1;
  const splitOk = !split || splitPlanComplete(splitRows);
  const rowsOk = selectedCount > 0 && validCount === selectedCount;
  const canSubmit = rowsOk && splitOk && !disabled;

  const blockReason =
    selectedCount === 0
      ? '처리할 계산서 행을 선택하세요.'
      : !rowsOk
        ? null // 행별 미입력은 아래 카운터가 이동 링크와 함께 안내한다.
        : !splitOk
          ? '분할 계획의 모든 행을 채워야 합니다(마지막 행은 차액반영이라 금액 제외).'
          : null;

  const scrollToRow = useCallback((no: number) => {
    // 같은 행이 표(md+)·카드(md 미만) 양쪽 DOM 에 있을 수 있어 보이는 쪽만 잡는다.
    const el = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>(`[data-row-no="${no}"]`) ?? [],
    ).find((x) => x.offsetParent !== null);
    if (!el) return;
    el.scrollIntoView({ block: 'center' });
    el.querySelector<HTMLButtonElement>('[data-budget-trigger]')?.focus({ preventScroll: true });
  }, []);

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    const payload: GridRowSubmit[] = rows.map((r) => {
      const e = edits[r.no] ?? EMPTY_EDIT;
      // 미선택 행은 skip 으로 내려 이번 실행에서 처리되지 않게 한다(카드 그리드와 동일 계약).
      if (!e.selected) {
        return { no: r.no, budgetUnit: null, project: null, note: '', skip: true };
      }
      const b = budgetByCode.get(e.budgetUnitCode);
      return {
        no: r.no,
        budgetUnit: b
          ? { code: b.code, name: b.name, bizplanNm: b.bizplanNm, bgacctNm: b.bgacctNm }
          : { code: e.budgetUnitCode, name: e.budgetUnitCode },
        project: e.projectCode
          ? { code: e.projectCode, name: e.projectName, wbsNo: wbsOf(e.projectCode) }
          : null,
        note: e.note.trim(),
        skip: false,
      };
    });
    const plan: SplitPlanRowSubmit[] | undefined = split
      ? splitRows.map((r, i) => ({
          note: r.note.trim(),
          // 마지막 행 amount=null = ERP 차액반영으로 잔액 흡수(계약).
          amount: i === splitRows.length - 1 ? null : parseAmount(r.amount),
          costCenter: r.costCenter.trim(),
          projectWbs: wbsOf(r.projectCode),
        }))
      : undefined;
    const ok = await onSubmit(payload, plan);
    if (ok) {
      // 성공 시 스트림이 이어받는다(진행 로그·결과). hitl 이 닫히며 카드가 사라진다.
      setSubmitted(true);
    } else {
      setError('적용을 전달하지 못했습니다(흐름이 종료됐을 수 있음).');
      setBusy(false);
    }
  }

  if (rows.length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <InvoiceHeader title={hitl.title} prompt={hitl.prompt} split={split} />
        <EmptyNote py={10}>조회기간에 해당하는 계산서가 없습니다.</EmptyNote>
      </div>
    );
  }

  /** 행 편집 컨트롤 3종 — 표(md+) 셀과 카드(md 미만)가 같은 JSX·핸들러를 공유한다. */
  const rowEditors = (r: InvoiceGridRow, e: RowEdit) => {
    const off = !e.selected || disabled;
    const invalid = e.selected && !isRowValid(r.no);
    return {
      budget: (
        <InvoiceBudgetCombobox
          value={e.budgetUnitCode}
          favorites={bFavList}
          mineExclFav={bMineExclFav}
          allExclFav={bAllExclFav}
          disabled={off}
          invalid={invalid && e.budgetUnitCode === ''}
          onChange={(code) => setRow(r.no, { budgetUnitCode: code })}
        />
      ),
      project: (
        <CatalogCombobox
          value={{ code: e.projectCode, name: e.projectName }}
          placeholder="프로젝트 선택"
          favorites={projectFavs}
          disabled={off}
          search={searchProjects}
          onSelect={(o) => setRow(r.no, { projectCode: o.code, projectName: o.name })}
          onClear={() => setRow(r.no, { projectCode: '', projectName: '' })}
        />
      ),
      note: (
        <input
          value={e.note}
          onChange={(ev) => setRow(r.no, { note: ev.target.value })}
          disabled={off}
          maxLength={200}
          placeholder="적요"
          aria-label={`${r.no}행 적요`}
          aria-invalid={invalid && e.note.trim() === ''}
          className={cn(
            'border-border bg-surface text-foreground placeholder:text-muted-foreground h-8 w-full min-w-0 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none max-md:min-h-11',
            'focus-visible:border-accent',
            'aria-invalid:border-danger disabled:opacity-50',
          )}
        />
      ),
    };
  };

  /** 선택 컨트롤 — 분할이면 라디오(1행만), 아니면 체크박스. */
  const selectControl = (r: InvoiceGridRow, e: RowEdit) => (
    <input
      type={split ? 'radio' : 'checkbox'}
      name={split ? `invoice-pick-${hitl.id}` : undefined}
      checked={e.selected}
      disabled={disabled}
      onChange={(ev) => setSelected(r.no, ev.target.checked)}
      aria-label={`${r.no}행 처리 대상 선택`}
      className="accent-accent size-4 cursor-pointer disabled:cursor-not-allowed"
    />
  );

  return (
    <div ref={rootRef} className="flex h-full min-h-0 flex-col gap-3">
      <InvoiceHeader title={hitl.title} prompt={hitl.prompt} split={split} />

      {/* 재개입 공지 — 직전 저장(F7)이 왜 실패했고 무엇을 고칠지. */}
      {hitl.notice ? (
        <div className="border-danger/30 bg-danger/10 text-danger flex shrink-0 items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
          <RiErrorWarningLine size={16} aria-hidden className="mt-0.5 shrink-0" />
          <p className="text-[length:var(--text-body-sm)] leading-relaxed whitespace-pre-line">
            {hitl.notice}
          </p>
        </div>
      ) : null}

      {/* 선택 범위 바 — 선택 건수 + 선택 합계. 분할이면 1행 규칙을 여기서 고지한다. */}
      <div className="border-border-subtle bg-muted/40 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[var(--radius-md)] border px-2.5 py-2">
        <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
          처리 대상
        </span>
        <span className="text-foreground-secondary text-[11px]">
          {rows.length}건 중{' '}
          <span
            className={cn(
              'font-semibold tabular-nums',
              selectedCount > 0 ? 'text-accent' : 'text-foreground-tertiary',
            )}
          >
            {selectedCount}건
          </span>{' '}
          선택
        </span>
        {split ? (
          <span className="text-warning text-[11px]">비용분할 — 계산서 1행만 선택합니다.</span>
        ) : (
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              className="h-7 px-2 max-md:h-11"
              disabled={disabled || selectedCount === rows.length}
              onClick={() => selectAll(true)}
            >
              전체 선택
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="h-7 px-2 max-md:h-11"
              disabled={disabled || selectedCount === 0}
              onClick={() => selectAll(false)}
            >
              전체 해제
            </Button>
          </div>
        )}
      </div>

      {selectedCount > 0 ? (
        <div className="grid grid-cols-3 gap-2">
          <StatTile label="공급가액 합계" value={`${formatWon(supplySum)}원`} />
          <StatTile label="세액 합계" value={`${formatWon(taxSum)}원`} />
          <StatTile label="합계" value={`${formatWon(totalSum)}원`} />
        </div>
      ) : null}

      {/* 일괄 지정 — 선택된 행에 같은 예산단위·프로젝트·적요를 한 번에 채운다(이후 개별 수정 가능). */}
      <BulkBar
        budgetFavs={bFavList}
        budgetMineExclFav={bMineExclFav}
        budgetAllExclFav={bAllExclFav}
        projectFavs={projectFavs}
        searchProjects={searchProjects}
        disabled={disabled || selectedCount === 0}
        onBulkBudget={(code) => applySelected({ budgetUnitCode: code })}
        onBulkProject={(code, name) => applySelected({ projectCode: code, projectName: name })}
        onBulkNote={(note) => applySelected({ note })}
      />

      {/* md+ — 실 표(가로 스크롤 폴백). md 미만은 아래 카드 스택이 대신한다. */}
      {isDesktopLayout !== false && (
        <div className="border-border min-h-0 flex-1 overflow-auto rounded-[var(--radius-md)] border max-md:hidden">
          <table className="w-full min-w-[1120px] border-collapse text-[11px]">
            <thead className="bg-muted/70 text-foreground-tertiary sticky top-0 z-10">
              <tr>
                <Th className="w-10 text-center">선택</Th>
                <Th className="w-10 text-center">번호</Th>
                <Th className="whitespace-nowrap">계산서일</Th>
                <Th className="min-w-[150px]">거래처명</Th>
                <Th className="text-right">공급가액</Th>
                <Th className="text-right">세액</Th>
                <Th className="text-right">합계</Th>
                <Th className="whitespace-nowrap">승인번호</Th>
                <Th className="min-w-[210px]">예산단위</Th>
                <Th className="min-w-[200px]">프로젝트</Th>
                <Th className="min-w-[170px]">적요</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const e = edits[r.no] ?? EMPTY_EDIT;
                const editors = rowEditors(r, e);
                const rowInvalid = e.selected && !isRowValid(r.no);
                return (
                  <tr
                    key={r.no}
                    data-row-no={r.no}
                    className={cn(
                      'border-border/50 border-t align-middle',
                      !e.selected && 'opacity-55',
                      e.selected && 'bg-accent/[0.03]',
                      rowInvalid && 'bg-danger/[0.04]',
                    )}
                  >
                    <Td className="text-center">{selectControl(r, e)}</Td>
                    <Td className="text-foreground-tertiary text-center tabular-nums">{r.no}</Td>
                    <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
                      {r.invoiceDate ?? ''}
                    </Td>
                    <Td>
                      <span className="text-foreground-secondary flex flex-wrap items-center gap-1.5">
                        <span className="min-w-0">{r.partnerName ?? ''}</span>
                        <DataKindBadge row={r} />
                      </span>
                      {r.itemName ? (
                        <span className="text-foreground-tertiary mt-0.5 block truncate">
                          {r.itemName}
                        </span>
                      ) : null}
                    </Td>
                    <Td className="text-foreground-secondary text-right tabular-nums">
                      {amountText(r.supplyAmount)}
                    </Td>
                    <Td className="text-foreground-secondary text-right tabular-nums">
                      {amountText(r.taxAmount)}
                    </Td>
                    <Td className="text-foreground text-right font-semibold tabular-nums">
                      {amountText(r.sumAmount)}
                    </Td>
                    <Td className="text-foreground-tertiary font-mono whitespace-nowrap">
                      {r.ntsAprvlNo ?? ''}
                    </Td>
                    <Td>
                      <div className="flex">{editors.budget}</div>
                    </Td>
                    <Td>{editors.project}</Td>
                    <Td>{editors.note}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* md 미만 — 행당 카드 스택. 표와 편집 상태·검증을 공유하며 렌더 골격만 다르다. */}
      {isDesktopLayout !== true && (
        <div className="flex min-h-0 flex-col gap-2 md:hidden">
          {rows.map((r) => {
            const e = edits[r.no] ?? EMPTY_EDIT;
            const editors = rowEditors(r, e);
            const rowInvalid = e.selected && !isRowValid(r.no);
            return (
              <div
                key={r.no}
                data-row-no={r.no}
                className={cn(
                  'flex flex-col gap-2.5 rounded-[var(--radius-md)] border p-3',
                  e.selected ? 'border-accent/40 bg-accent/[0.03]' : 'border-border opacity-75',
                  rowInvalid && 'border-danger/30 bg-danger/[0.04]',
                )}
              >
                {/* 선택 — 행 전체 label 로 히트영역 44px 확보. */}
                <label
                  className={cn(
                    'flex min-h-11 cursor-pointer items-start justify-between gap-2',
                    disabled && 'cursor-not-allowed opacity-60',
                  )}
                >
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-foreground truncate text-[13px] font-semibold">
                      {r.partnerName || '(거래처 미상)'}
                    </span>
                    <span className="text-foreground-tertiary flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                      <span className="tabular-nums">#{r.no}</span>
                      {r.invoiceDate ? <span className="tabular-nums">{r.invoiceDate}</span> : null}
                      <DataKindBadge row={r} />
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="text-foreground text-[13px] font-semibold tabular-nums">
                      {amountText(r.sumAmount)}
                    </span>
                    {selectControl(r, e)}
                  </span>
                </label>

                <dl className="text-foreground-tertiary grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px]">
                  <dt>공급가액</dt>
                  <dd className="text-foreground-secondary text-right tabular-nums">
                    {amountText(r.supplyAmount)}
                  </dd>
                  <dt>세액</dt>
                  <dd className="text-foreground-secondary text-right tabular-nums">
                    {amountText(r.taxAmount)}
                  </dd>
                  {r.ntsAprvlNo ? (
                    <>
                      <dt>승인번호</dt>
                      <dd className="text-foreground-secondary truncate text-right font-mono">
                        {r.ntsAprvlNo}
                      </dd>
                    </>
                  ) : null}
                  {r.itemName ? (
                    <>
                      <dt>품목명</dt>
                      <dd className="text-foreground-secondary truncate text-right">
                        {r.itemName}
                      </dd>
                    </>
                  ) : null}
                </dl>

                {/* 편집 컨트롤은 선택한 행에서만 의미가 있어 미선택이면 접어 둔다. */}
                {e.selected ? (
                  <div className="flex flex-col gap-2">
                    <CardField label="예산단위">
                      <div className="flex">{editors.budget}</div>
                    </CardField>
                    <CardField label="프로젝트">{editors.project}</CardField>
                    <CardField label="적요">{editors.note}</CardField>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {/* 분할 계획 — 선택 1행일 때만. 기준금액(참고 총액)은 그 행의 공급가액으로 동기화된다. */}
      {splitVisible ? (
        <div className="border-border rounded-[var(--radius-md)] border p-3">
          <SplitPlanSection
            rows={splitRows}
            onRowsChange={setSplitRows}
            mode={splitMode}
            onModeChange={setSplitMode}
            refTotal={refTotal}
            onRefTotalChange={setRefTotal}
            projectFavs={projectFavs}
            searchProjects={searchProjects}
            disabled={disabled}
          />
        </div>
      ) : null}

      {/* 검증 요약 + 제출(저장 안전 게이트) — md 미만에선 페이지 스크롤 기준 하단 고정 바.
          음수 마진 없이 bottom-0 (음수 하단 마진은 sticky 고정 위치를 스크롤포트 밖으로 민다). */}
      <div
        className={cn(
          'flex flex-col gap-3',
          'max-md:border-border max-md:bg-surface/95 max-md:sticky max-md:bottom-0 max-md:z-20 max-md:rounded-[var(--radius-md)] max-md:border max-md:px-3 max-md:pt-3 max-md:pb-[max(1rem,env(safe-area-inset-bottom))] max-md:backdrop-blur',
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-foreground-secondary text-[11px]">
            선택 {selectedCount}행 중{' '}
            <span
              className={cn('font-semibold tabular-nums', rowsOk ? 'text-success' : 'text-warning')}
            >
              {validCount}행
            </span>{' '}
            입력 완료
            {firstInvalidNo != null ? (
              <>
                {' '}
                ·{' '}
                <button
                  type="button"
                  onClick={() => scrollToRow(firstInvalidNo)}
                  // 모바일은 -m/p 로 히트영역만 확장(시각 크기 유지).
                  className="text-warning cursor-pointer underline underline-offset-2 hover:opacity-80 max-md:-my-2 max-md:inline-block max-md:py-2"
                >
                  예산단위·적요 미입력 {selectedCount - validCount}행
                </button>
              </>
            ) : null}
            {blockReason ? (
              <span className="text-foreground-tertiary"> — {blockReason}</span>
            ) : null}
          </p>

          <div className="flex flex-wrap items-center gap-2">
            {!busy && !submitted && selectedCount > 0 ? (
              <span className="text-foreground-tertiary text-[11px]">
                실 ERP에{' '}
                <span className="text-foreground-secondary font-semibold tabular-nums">
                  {selectedCount}건
                </span>{' '}
                반영·저장
              </span>
            ) : null}
            <Button
              size="sm"
              className="max-md:h-11 max-md:flex-1"
              onClick={() => void submit()}
              disabled={!canSubmit}
            >
              {submitted ? (
                <>
                  <Spinner size={14} />
                  반영·저장 진행 중…
                </>
              ) : busy ? (
                <>
                  <Spinner size={14} />
                  전송 중…
                </>
              ) : (
                <>
                  <RiCheckLine size={14} aria-hidden />
                  입력 완료
                </>
              )}
            </Button>
          </div>
        </div>

        {error ? <span className="text-danger text-[12px]">{error}</span> : null}
      </div>
    </div>
  );
}

// ── 조각 ─────────────────────────────────────────────────────────────

/** 모바일 카드의 라벨+컨트롤 한 행 — 인라인 라벨(고정폭) 뒤에 편집 컨트롤. */
function CardField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-foreground-tertiary w-14 shrink-0 text-[11px]">{label}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function InvoiceHeader({
  title,
  prompt,
  split,
}: {
  title: string;
  prompt?: string;
  split: boolean;
}) {
  return (
    <div className="border-warning/30 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
      <RiTableLine size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
          {title} · 계산서 선택{split ? ' · 비용분할' : ''}
        </p>
        <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">
          {prompt ??
            (split
              ? '분할할 계산서 1행을 고르고, 예산단위·프로젝트·적요와 분할 계획을 채우세요.'
              : '결의서에 넣을 계산서 행을 고르고, 고른 행마다 예산단위·프로젝트·적요를 채우세요.')}
        </p>
      </div>
    </div>
  );
}

/** 전자세금계산서종류 배지 — 취소분이면 경고 톤으로 눈에 띄게 한다(총액 상계 주의). */
function DataKindBadge({ row }: { row: InvoiceGridRow }) {
  const cancelled = isCancelled(row);
  const label = row.dataKind?.trim() || (cancelled ? '취소분' : '');
  if (!label) return null;
  return (
    <span
      className={cn(
        'shrink-0 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[10px] font-semibold tracking-wide',
        cancelled ? 'bg-warning/15 text-warning' : 'bg-muted text-foreground-tertiary',
      )}
    >
      {label}
    </span>
  );
}

// ── 일괄 지정 바 ─────────────────────────────────────────────────────

function BulkBar({
  budgetFavs,
  budgetMineExclFav,
  budgetAllExclFav,
  projectFavs,
  searchProjects,
  disabled,
  onBulkBudget,
  onBulkProject,
  onBulkNote,
}: {
  budgetFavs: BudgetUnitOption[];
  budgetMineExclFav: BudgetUnitOption[];
  budgetAllExclFav: BudgetUnitOption[];
  projectFavs: ComboOption[];
  searchProjects: (q: string) => Promise<ComboOption[]>;
  disabled: boolean;
  onBulkBudget: (code: string) => void;
  onBulkProject: (code: string, name: string) => void;
  onBulkNote: (note: string) => void;
}) {
  const [bulkNote, setBulkNote] = useState('');
  return (
    <div className="border-border-subtle bg-muted/40 flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] border px-2.5 py-2">
      <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
        일괄 지정
      </span>
      <InvoiceBudgetCombobox
        value=""
        favorites={budgetFavs}
        mineExclFav={budgetMineExclFav}
        allExclFav={budgetAllExclFav}
        disabled={disabled}
        placeholder="예산단위 선택 행 적용"
        className="w-52 flex-none max-md:w-full"
        onChange={(code) => {
          if (code) onBulkBudget(code);
        }}
      />
      <div className="w-52 max-md:w-full">
        <CatalogCombobox
          value={{ code: '', name: '' }}
          placeholder="프로젝트 선택 행 적용"
          favorites={projectFavs}
          disabled={disabled}
          search={searchProjects}
          onSelect={(o) => onBulkProject(o.code, o.name)}
          onClear={() => undefined}
        />
      </div>
      <input
        value={bulkNote}
        onChange={(ev) => setBulkNote(ev.target.value)}
        onKeyDown={(ev) => {
          if (ev.key === 'Enter' && bulkNote.trim()) {
            ev.preventDefault();
            onBulkNote(bulkNote);
          }
        }}
        disabled={disabled}
        maxLength={200}
        placeholder="적요 일괄 입력"
        aria-label="적요 일괄 입력"
        className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent h-8 w-40 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none disabled:opacity-50 max-md:h-11 max-md:w-full"
      />
      <Button
        size="sm"
        variant="secondary"
        className="h-8 px-2 max-md:h-11 max-md:w-full"
        disabled={disabled || !bulkNote.trim()}
        onClick={() => onBulkNote(bulkNote)}
      >
        적요 적용
      </Button>
    </div>
  );
}

// ── 표 셀(그리드 전용 컴팩트) ────────────────────────────────────────

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={cn('px-2 py-1.5 font-semibold whitespace-nowrap', className)}>{children}</th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('px-2 py-1.5', className)}>{children}</td>;
}
