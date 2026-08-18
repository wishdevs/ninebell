'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { RiAddLine, RiDeleteBinLine, RiErrorWarningLine, RiPlayLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { fetchCatalog, fetchFavorites, fetchTripDefaults } from '@/lib/api/me-codes';
import { cn } from '@/lib/utils';
import { CatalogCombobox, type ComboOption, projectCodeLabel } from './catalog-combobox';
import type { PreRunFormProps } from './index';

const MAX_ROWS = 20;
// 합리적 상한(오타·단위 실수 방지) — 공급가액 1억 원.
const MAX_AMOUNT = 100_000_000;

// 표(그리드) 열 템플릿 — md 이상에서 헤더행과 데이터행이 공유한다. md 미만은 행당 카드 스택.
// # · 프로젝트 · 계산서일 · 공급가액 · 적요 · 삭제 (유형·거래처 없음 — 국내보다 단순)
// 삭제 열은 아이콘 버튼이 드는 2.5rem.
const ROW_GRID =
  'md:grid md:grid-cols-[1.75rem_minmax(10rem,1.6fr)_9rem_minmax(8rem,1fr)_minmax(9rem,1.3fr)_2.5rem] md:items-start md:gap-x-2 md:gap-y-1';

interface DraftRow {
  id: string;
  // (세금)계산서일 = 증빙일. yyyy-mm-dd.
  invoiceDate: string;
  // 공급가액(총 금액).
  amount: string;
  projectCode: string;
  projectName: string;
  // 적요(자유 입력).
  note: string;
}

let rowSeq = 0;
function newRowId(): string {
  rowSeq += 1;
  return `o${rowSeq}`;
}

/** 로컬 오늘(UTC 오프셋으로 하루 밀리지 않게 로컬 기준 yyyy-mm-dd). */
function todayLocal(): string {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
}

function emptyRow(projectDefault?: ComboOption): DraftRow {
  return {
    id: newRowId(),
    invoiceDate: todayLocal(),
    amount: '',
    projectCode: projectDefault?.code ?? '',
    projectName: projectDefault?.name ?? '',
    note: '',
  };
}

/** 양의 정수 + 상한 검증(빈값·소수·NaN·초과는 무효). ERP 금액은 정수다. */
function isPositiveIntWithin(value: string, max: number): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 && n <= max;
}

function isRowValid(row: DraftRow): boolean {
  return (
    !!row.invoiceDate.trim() &&
    !!row.projectCode.trim() &&
    !!row.note.trim() &&
    isPositiveIntWithin(row.amount, MAX_AMOUNT)
  );
}

/** 마지막 제출 params(초기값 복원용)를 DraftRow 목록으로 되돌린다. 없으면 빈 결과. */
function seedFromParams(initial: Record<string, unknown> | undefined): { rows?: DraftRow[] } {
  const trip = initial?.trip as { rows?: unknown[] } | undefined;
  if (!trip || !Array.isArray(trip.rows) || trip.rows.length === 0) return {};
  const rows = trip.rows.map((raw): DraftRow => {
    const r = raw as Record<string, unknown>;
    const project = (r.project ?? {}) as { code?: string; name?: string };
    return {
      id: newRowId(),
      invoiceDate: typeof r.invoiceDate === 'string' ? r.invoiceDate : todayLocal(),
      amount: r.amount != null ? String(r.amount) : '',
      projectCode: project.code ?? '',
      projectName: project.name ?? '',
      note: typeof r.note === 'string' ? r.note : '',
    };
  });
  return { rows };
}

export function OverseasPreRunForm({ disabled, initialParams, onStart }: PreRunFormProps) {
  const seed = useMemo(() => seedFromParams(initialParams), [initialParams]);
  const [rows, setRows] = useState<DraftRow[]>(() => seed.rows ?? [emptyRow()]);

  // 프로젝트 자주쓰는 + 팀 비용구분(판/제) 기본 프로젝트 — 국내 폼과 동일 규칙.
  const [projectFavs, setProjectFavs] = useState<ComboOption[]>([]);
  const [favsLoaded, setFavsLoaded] = useState(false);
  const [tripDefaultProject, setTripDefaultProject] = useState<ComboOption | null | undefined>(
    undefined,
  );

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const favs = await fetchFavorites('project');
        if (alive) {
          setProjectFavs(
            favs.map((f) => ({
              code: f.code,
              name: f.name,
              codeLabel: projectCodeLabel(f.code, f.extra?.pjtNo ?? undefined),
              sub: f.extra?.wbsNm ?? f.extra?.wbsNo ?? undefined,
              isDefault: f.isDefault,
            })),
          );
        }
      } catch {
        /* 백엔드 미배포 — 검색만 사용 */
      }
      if (alive) setFavsLoaded(true);
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const d = await fetchTripDefaults();
        if (!alive) return;
        const p = d.defaultProject;
        setTripDefaultProject(
          p ? { code: p.code, name: p.name, codeLabel: projectCodeLabel(p.code) } : null,
        );
      } catch {
        if (alive) setTripDefaultProject(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 기본 프로젝트 = 팀 비용구분 프로젝트 우선, 없으면 기본지정(★) 즐겨찾기 폴백(국내와 동일).
  const projectDefault = useMemo(
    () => tripDefaultProject ?? projectFavs.find((p) => p.isDefault),
    [tripDefaultProject, projectFavs],
  );

  // 기본 프로젝트 1회 백필 — 두 비동기 소스 확정 후, 비어 있는 행에만 채운다.
  const defaultsApplied = useRef(false);
  useEffect(() => {
    if (defaultsApplied.current) return;
    if (!favsLoaded || tripDefaultProject === undefined) return;
    defaultsApplied.current = true;
    if (!projectDefault) return;
    setRows((rs) =>
      rs.map((r) =>
        r.projectCode
          ? r
          : { ...r, projectCode: projectDefault.code, projectName: projectDefault.name },
      ),
    );
  }, [favsLoaded, tripDefaultProject, projectDefault]);

  const updateRow = useCallback((id: string, patch: Partial<DraftRow>) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const addRow = useCallback(() => {
    setRows((rs) => (rs.length >= MAX_ROWS ? rs : [...rs, emptyRow(projectDefault)]));
  }, [projectDefault]);

  const removeRow = useCallback((id: string) => {
    setRows((rs) => (rs.length <= 1 ? rs : rs.filter((r) => r.id !== id)));
  }, []);

  const canSubmit = !disabled && rows.length > 0 && rows.every(isRowValid);

  // 회계일자 = 계산서일(증빙일) 중 가장 마지막일(자동 파생 — 백엔드도 동일 규칙).
  const acctPreview = useMemo(() => {
    const dates = rows
      .map((r) => r.invoiceDate)
      .filter(Boolean)
      .sort();
    return dates.length > 0 ? dates[dates.length - 1] : '';
  }, [rows]);

  const grandTotal = useMemo(
    () =>
      rows.reduce(
        (sum, r) => (isPositiveIntWithin(r.amount, MAX_AMOUNT) ? sum + Number(r.amount) : sum),
        0,
      ),
    [rows],
  );

  const submit = () => {
    if (!canSubmit) return;
    const payloadRows = rows.map((r) => ({
      invoiceDate: r.invoiceDate,
      amount: Number(r.amount),
      project: { code: r.projectCode, name: r.projectName },
      note: r.note,
    }));
    // 회계일자는 보내지 않는다 — 백엔드가 계산서일 최댓값으로 파생한다.
    onStart({ trip: { rows: payloadRows } });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title="출장(해외/정산서) 결의서"
      description="행마다 계산서일(증빙일)·공급가액(총액)·프로젝트·적요를 입력하면 무개입으로 채워 저장합니다. 거래처·상대계정은 작성자 본인, 회계일자는 계산서일 중 가장 마지막일로 자동 지정됩니다."
      density="comfortable"
    >
      {/* 저장·상신 주의 — 월이 바뀌는 일비는 나눠 실행 */}
      <div className="border-warning/40 bg-warning/5 flex gap-2 rounded-[var(--radius-md)] border p-3">
        <RiErrorWarningLine size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
        <div className="text-xs">
          <p className="text-foreground-secondary font-semibold">
            저장·상신 주의 — 월이 바뀌는 일비는 나눠 실행하세요
          </p>
          <p className="text-foreground-tertiary mt-1 leading-relaxed">
            해외출장 일비가 두 달에 걸치면(예: 3/30~4/6) 회계일자별로 <b>별도 결의서</b>로 나눠
            실행·상신하세요. 회계일자 3/31자(3/30~3/31분)와 4/6 이후자(4/1~4/6분)를 각각 따로
            실행하면 됩니다. 회계일자는 이 폼의 계산서일 중 마지막일로 자동 지정됩니다.
          </p>
        </div>
      </div>

      {/* md 이상 표: 최소폭 미달 시 가로 스크롤 상시 허용(sm 대역에서 트랙 최소합이 카드 밖으로
          넘치던 오버플로 방지). md 미만은 카드 스택이라 min-w 없음. */}
      <div className="overflow-x-auto">
        <div className="flex flex-col gap-3 md:min-w-[44rem] md:gap-1">
          {/* 표 헤더(md 이상 표 전용) — md 미만 카드는 셀마다 인라인 라벨(FieldLabel)을 붙인다 */}
          <div
            className={cn(
              ROW_GRID,
              'border-border/60 text-foreground-tertiary hidden border-b px-1 pb-1.5 text-[10px] font-semibold tracking-wider uppercase',
            )}
          >
            <span aria-hidden />
            <span>프로젝트</span>
            <span>계산서일</span>
            <span>공급가액</span>
            <span>적요</span>
            <span aria-hidden />
          </div>

          {rows.map((row, idx) => (
            <RowEditor
              key={row.id}
              row={row}
              index={idx}
              canRemove={rows.length > 1}
              disabled={disabled}
              projectFavs={projectFavs}
              onChange={(patch) => updateRow(row.id, patch)}
              onRemove={() => removeRow(row.id)}
            />
          ))}
        </div>
      </div>

      {/* md 미만은 contents 로 풀어 행 추가는 흐름에 두고 합계·실행만 sticky 하단 바로 분리 */}
      <div className="flex flex-wrap items-center justify-between gap-2 max-md:contents">
        <div className="flex items-center gap-3 max-md:flex-wrap">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="max-md:h-10"
            onClick={addRow}
            disabled={disabled || rows.length >= MAX_ROWS}
          >
            <RiAddLine size={15} aria-hidden />행 추가
          </Button>
          {acctPreview ? (
            <span className="text-foreground-tertiary text-xs">
              회계일자{' '}
              <span className="text-foreground-secondary font-semibold">{acctPreview}</span> (마지막
              계산서일)
            </span>
          ) : null}
        </div>
        {/* 합계+실행 — md 미만은 페이지 스크롤 기준 sticky(SectionCard 조상 체인에 overflow 제약 없음) */}
        <div
          className={cn(
            'flex items-center gap-3',
            'max-md:sticky max-md:bottom-0 max-md:z-10 max-md:-mx-6 max-md:flex-col max-md:items-stretch max-md:gap-2',
            'max-md:border-border/60 max-md:bg-surface/95 max-md:border-t max-md:px-6 max-md:pt-3 max-md:pb-[max(0.75rem,env(safe-area-inset-bottom))] max-md:backdrop-blur',
          )}
        >
          {!canSubmit && !disabled ? (
            <p className="text-foreground-tertiary text-xs">
              모든 필수 입력을 완료하면 실행할 수 있습니다.
            </p>
          ) : null}
          <span className="text-foreground-secondary text-sm">
            합계{' '}
            <span className="text-foreground text-base font-semibold tabular-nums">
              {grandTotal.toLocaleString('ko-KR')}
            </span>
            원
          </span>
          <Button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="max-md:h-11 max-md:w-full"
          >
            <RiPlayLine size={15} aria-hidden />
            실행
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

// ── 인라인 필드 라벨 — md 미만 카드에서만 표시(md 이상은 표 헤더가 라벨) ────────
function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-foreground-tertiary block text-[11px] font-medium md:hidden">
      {children}
    </span>
  );
}

// ── 행 편집기 ────────────────────────────────────────────────────────────────
function RowEditor({
  row,
  index,
  canRemove,
  disabled,
  projectFavs,
  onChange,
  onRemove,
}: {
  row: DraftRow;
  index: number;
  canRemove: boolean;
  disabled?: boolean;
  projectFavs: ComboOption[];
  onChange: (patch: Partial<DraftRow>) => void;
  onRemove: () => void;
}) {
  return (
    <div
      className={cn(
        ROW_GRID,
        'max-md:border-border/60 max-md:relative max-md:flex max-md:flex-col max-md:gap-2.5 max-md:rounded-[var(--radius-md)] max-md:border max-md:p-3',
        'md:border-border/50 md:border-b md:py-1.5 md:last:border-b-0',
      )}
    >
      {/* # — md 미만 카드에선 'N행' 헤더 */}
      <span className="text-foreground-tertiary text-center text-xs font-semibold tabular-nums max-md:text-left md:pt-2.5">
        {index + 1}
        <span className="md:hidden">행</span>
      </span>

      {/* 프로젝트 */}
      <div className="min-w-0 max-md:space-y-1">
        <FieldLabel>프로젝트</FieldLabel>
        <CatalogCombobox
          value={{ code: row.projectCode, name: row.projectName }}
          placeholder="프로젝트 선택"
          favorites={projectFavs}
          disabled={disabled}
          search={async (q) => {
            const page = await fetchCatalog({ kind: 'project', q, dept: 'all', limit: 25 });
            return page.items.map((c) => ({
              code: c.code,
              name: c.name,
              codeLabel: projectCodeLabel(c.code, c.extra?.pjtNo ?? undefined),
              sub: c.extra?.wbsNm ?? c.extra?.wbsNo ?? undefined,
            }));
          }}
          onSelect={(o) => onChange({ projectCode: o.code, projectName: o.name })}
          onClear={() => onChange({ projectCode: '', projectName: '' })}
        />
      </div>

      {/* 계산서일(증빙일) */}
      <div className="min-w-0 max-md:space-y-1">
        <FieldLabel>계산서일</FieldLabel>
        <DatePicker
          ariaLabel={`${index + 1}행 계산서일`}
          value={row.invoiceDate}
          disabled={disabled}
          onChange={(v) => onChange({ invoiceDate: v })}
        />
      </div>

      {/* 공급가액(총액) */}
      <div className="flex min-w-0 flex-col gap-1">
        <FieldLabel>공급가액</FieldLabel>
        <Input
          type="number"
          min={1}
          max={MAX_AMOUNT}
          step={1}
          inputMode="numeric"
          aria-label={`${index + 1}행 공급가액`}
          value={row.amount}
          disabled={disabled}
          placeholder="예: 50000"
          onChange={(e) => onChange({ amount: e.target.value })}
        />
        {row.amount && !isPositiveIntWithin(row.amount, MAX_AMOUNT) ? (
          <p className="text-danger text-[11px]">1 ~ {MAX_AMOUNT.toLocaleString('ko-KR')} 정수</p>
        ) : null}
      </div>

      {/* 적요(자유) */}
      <div className="min-w-0 max-md:space-y-1">
        <FieldLabel>적요</FieldLabel>
        <Input
          aria-label={`${index + 1}행 적요`}
          value={row.note}
          disabled={disabled}
          placeholder="예: 해외출장 일비 / 해외출장 경비"
          onChange={(e) => onChange({ note: e.target.value })}
        />
      </div>

      {/* 삭제 — md 미만 카드에선 우상단 44px 터치 타겟 */}
      {canRemove ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="text-foreground-tertiary hover:text-danger max-md:absolute max-md:top-1.5 max-md:right-1.5 max-md:h-11 max-md:w-11 md:mt-0.5"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`${index + 1}번째 행 삭제`}
        >
          <RiDeleteBinLine size={15} aria-hidden />
        </Button>
      ) : (
        <span aria-hidden className="max-md:hidden" />
      )}
    </div>
  );
}
