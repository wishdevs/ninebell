'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RiAddLine, RiDeleteBinLine, RiPlayLine, RiSearchLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { fetchCatalog, fetchFavorites } from '@/lib/api/me-codes';
import {
  CAR_CLASS_EFF_KEY,
  CAR_CLASSES,
  CAR_CLASS_LABEL,
  FUEL_UNIT_PRICE_KEY,
  fuelSupportAmount,
  type CarClass,
} from '@/lib/trip/fuel-calc';
import { fetchPartnerCatalog, fetchPartnerFavorites } from '@/lib/trip/partner-catalog';
import { cn } from '@/lib/utils';
import type { PreRunFormProps } from './index';

const DEFAULT_TOLL_NOTE = '통행료(현금)';
const DEFAULT_FUEL_NOTE = '국내출장 자차 유류비 지원';
const MAX_ROWS = 20;
// 합리적 상한(오타·단위 실수 방지) — 금액 1억 원, 주행거리 10,000km.
const MAX_AMOUNT = 100_000_000;
const MAX_KM = 10_000;

type RowType = 'toll' | 'fuel';

interface DraftRow {
  id: string;
  type: RowType;
  // 통행료
  partnerCode: string;
  partnerName: string;
  amount: string;
  // 유류비
  km: string;
  carClass: CarClass;
  // 공통
  projectCode: string;
  projectName: string;
  note: string;
}

/** 콤보박스 옵션(거래처·프로젝트 공용). */
interface ComboOption {
  code: string;
  name: string;
  /** 보조 표기(프로젝트 WBS명 등). */
  sub?: string;
  isDefault?: boolean;
}

let rowSeq = 0;
function newRowId(): string {
  rowSeq += 1;
  return `r${rowSeq}`;
}

/** 로컬 오늘(UTC 오프셋으로 하루 밀리지 않게 로컬 기준 yyyy-mm-dd). */
function todayLocal(): string {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
}

function emptyRow(type: RowType, partnerDefault?: ComboOption): DraftRow {
  return {
    id: newRowId(),
    type,
    partnerCode: type === 'toll' ? (partnerDefault?.code ?? '') : '',
    partnerName: type === 'toll' ? (partnerDefault?.name ?? '') : '',
    amount: '',
    km: '',
    carClass: 'under1600',
    projectCode: '',
    projectName: '',
    note: type === 'toll' ? DEFAULT_TOLL_NOTE : DEFAULT_FUEL_NOTE,
  };
}

/** 양의 정수 + 상한 검증(빈값·소수·NaN·초과는 무효). ERP 금액/거리는 모두 정수다. */
function isPositiveIntWithin(value: string, max: number): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 && n <= max;
}

function isRowValid(row: DraftRow): boolean {
  if (!row.projectCode.trim() || !row.note.trim()) return false;
  if (row.type === 'toll') {
    return !!row.partnerCode.trim() && isPositiveIntWithin(row.amount, MAX_AMOUNT);
  }
  return isPositiveIntWithin(row.km, MAX_KM);
}

/** 마지막 제출 params(초기값 복원용)를 DraftRow 목록으로 되돌린다. 없으면 빈 결과. */
function seedFromParams(initial: Record<string, unknown> | undefined): {
  acctDate?: string;
  rows?: DraftRow[];
} {
  const trip = initial?.trip as { acctDate?: string; rows?: unknown[] } | undefined;
  if (!trip || !Array.isArray(trip.rows) || trip.rows.length === 0) return {};
  const rows = trip.rows.map((raw): DraftRow => {
    const r = raw as Record<string, unknown>;
    const project = (r.project ?? {}) as { code?: string; name?: string };
    const common = {
      id: newRowId(),
      projectCode: project.code ?? '',
      projectName: project.name ?? '',
      note: typeof r.note === 'string' ? r.note : '',
    };
    if (r.type === 'fuel') {
      return {
        ...common,
        type: 'fuel',
        partnerCode: '',
        partnerName: '',
        amount: '',
        km: r.km != null ? String(r.km) : '',
        carClass: (r.carClass as CarClass) ?? 'under1600',
      };
    }
    return {
      ...common,
      type: 'toll',
      partnerCode: typeof r.partnerCode === 'string' ? r.partnerCode : '',
      partnerName: typeof r.partnerName === 'string' ? r.partnerName : '',
      amount: r.amount != null ? String(r.amount) : '',
      km: '',
      carClass: 'under1600',
    };
  });
  return { acctDate: trip.acctDate, rows };
}

export function TripPreRunForm({ agent, disabled, initialParams, onStart }: PreRunFormProps) {
  // 마지막 제출값 복원(실패 후 값 수정 재실행) — 부모가 key 로 remount 하면 초기값이 다시 시드된다.
  const seed = useMemo(() => seedFromParams(initialParams), [initialParams]);
  const [acctDate, setAcctDate] = useState(() => seed.acctDate ?? todayLocal());
  const [rows, setRows] = useState<DraftRow[]>(() => seed.rows ?? [emptyRow('toll')]);

  // 거래처·프로젝트 자주쓰는 — 폼 진입 시 1회 로드(백엔드 미배포면 빈 배열).
  const [partnerFavs, setPartnerFavs] = useState<ComboOption[]>([]);
  const [projectFavs, setProjectFavs] = useState<ComboOption[]>([]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const favs = await fetchPartnerFavorites();
        if (alive) {
          setPartnerFavs(favs.map((f) => ({ code: f.code, name: f.name, isDefault: f.isDefault })));
        }
      } catch {
        /* 백엔드 미배포 — 검색만 사용 */
      }
      try {
        const favs = await fetchFavorites('project');
        if (alive) {
          setProjectFavs(
            favs.map((f) => ({
              code: f.code,
              name: f.name,
              sub: f.extra?.wbsNm ?? f.extra?.wbsNo ?? undefined,
              isDefault: f.isDefault,
            })),
          );
        }
      } catch {
        /* 무시 */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const partnerDefault = useMemo(() => partnerFavs.find((p) => p.isDefault), [partnerFavs]);

  // 현재 유효 연비/단가 — 스키마 기본값 위에 관리자 저장값 오버레이(유류비 미리보기용).
  const effSettings = useMemo<Record<string, number | string | boolean>>(() => {
    const base: Record<string, number | string | boolean> = {};
    for (const d of agent.settingsSchema ?? []) base[d.key] = d.default;
    return { ...base, ...(agent.settings ?? {}) };
  }, [agent.settingsSchema, agent.settings]);

  const updateRow = useCallback((id: string, patch: Partial<DraftRow>) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const setRowType = useCallback(
    (id: string, type: RowType) => {
      setRows((rs) =>
        rs.map((r) => {
          if (r.id !== id || r.type === type) return r;
          // 유형 전환 시 유형별 필드 초기화 + 적요를 유형 기본값으로.
          return {
            ...r,
            type,
            partnerCode: type === 'toll' ? (partnerDefault?.code ?? '') : '',
            partnerName: type === 'toll' ? (partnerDefault?.name ?? '') : '',
            amount: '',
            km: '',
            note: type === 'toll' ? DEFAULT_TOLL_NOTE : DEFAULT_FUEL_NOTE,
          };
        }),
      );
    },
    [partnerDefault],
  );

  const addRow = useCallback(() => {
    setRows((rs) => (rs.length >= MAX_ROWS ? rs : [...rs, emptyRow('toll', partnerDefault)]));
  }, [partnerDefault]);

  const removeRow = useCallback((id: string) => {
    setRows((rs) => (rs.length <= 1 ? rs : rs.filter((r) => r.id !== id)));
  }, []);

  const canSubmit = !disabled && !!acctDate && rows.length > 0 && rows.every(isRowValid);

  const submit = () => {
    if (!canSubmit) return;
    const payloadRows = rows.map((r) => {
      const project: Record<string, string> = { code: r.projectCode, name: r.projectName };
      if (r.type === 'toll') {
        return {
          type: 'toll' as const,
          partnerCode: r.partnerCode,
          partnerName: r.partnerName,
          amount: Number(r.amount),
          project,
          note: r.note,
        };
      }
      // 유류비: amount 미포함(백엔드가 계산).
      return {
        type: 'fuel' as const,
        km: Number(r.km),
        carClass: r.carClass,
        project,
        note: r.note,
      };
    });
    onStart({ trip: { acctDate, rows: payloadRows } });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title="출장(국내/자차) 결의서"
      description="회계일자와 통행료·유류비 지원 행을 입력한 뒤 실행하면 무개입으로 채워 저장합니다."
      density="comfortable"
    >
      <FormField id="trip-acct-date" label="회계일자 — 마지막 자차 사용일" required>
        <Input
          id="trip-acct-date"
          type="date"
          value={acctDate}
          disabled={disabled}
          onChange={(e) => setAcctDate(e.target.value)}
          className="max-w-56"
        />
      </FormField>

      <div className="flex flex-col gap-3">
        {rows.map((row, idx) => (
          <RowEditor
            key={row.id}
            row={row}
            index={idx}
            canRemove={rows.length > 1}
            disabled={disabled}
            effSettings={effSettings}
            partnerFavs={partnerFavs}
            projectFavs={projectFavs}
            onType={(t) => setRowType(row.id, t)}
            onChange={(patch) => updateRow(row.id, patch)}
            onRemove={() => removeRow(row.id)}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={addRow}
          disabled={disabled || rows.length >= MAX_ROWS}
        >
          <RiAddLine size={15} aria-hidden />행 추가
        </Button>
        <Button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          title={canSubmit ? undefined : '모든 필수 입력을 완료하면 실행할 수 있습니다.'}
        >
          <RiPlayLine size={15} aria-hidden />
          실행
        </Button>
      </div>
    </SectionCard>
  );
}

// ── 행 편집기 ────────────────────────────────────────────────────────────────
interface RowEditorProps {
  row: DraftRow;
  index: number;
  canRemove: boolean;
  disabled?: boolean;
  effSettings: Record<string, number | string | boolean>;
  partnerFavs: ComboOption[];
  projectFavs: ComboOption[];
  onType: (type: RowType) => void;
  onChange: (patch: Partial<DraftRow>) => void;
  onRemove: () => void;
}

function RowEditor({
  row,
  index,
  canRemove,
  disabled,
  effSettings,
  partnerFavs,
  projectFavs,
  onType,
  onChange,
  onRemove,
}: RowEditorProps) {
  const kmValid = isPositiveIntWithin(row.km, MAX_KM);
  const fuelPreview =
    row.type === 'fuel' && kmValid
      ? fuelSupportAmount(Number(row.km), row.carClass, effSettings)
      : null;

  return (
    <div className="border-border bg-background/40 flex flex-col gap-3 rounded-[var(--radius-md)] border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-foreground-tertiary text-xs font-semibold tabular-nums">
            #{index + 1}
          </span>
          <TypeSegment value={row.type} disabled={disabled} onChange={onType} />
        </div>
        {canRemove ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-foreground-tertiary hover:text-danger"
            onClick={onRemove}
            disabled={disabled}
            aria-label={`${index + 1}번째 행 삭제`}
          >
            <RiDeleteBinLine size={15} aria-hidden />
          </Button>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {row.type === 'toll' ? (
          <>
            <FormField id={`${row.id}-partner`} label="거래처" required>
              <CatalogCombobox
                value={{ code: row.partnerCode, name: row.partnerName }}
                placeholder="거래처 선택"
                favorites={partnerFavs}
                disabled={disabled}
                search={fetchPartnerCatalog}
                onSelect={(o) => onChange({ partnerCode: o.code, partnerName: o.name })}
                onClear={() => onChange({ partnerCode: '', partnerName: '' })}
              />
            </FormField>
            <FormField
              id={`${row.id}-amount`}
              label="금액(공급가액)"
              required
              error={
                row.amount && !isPositiveIntWithin(row.amount, MAX_AMOUNT)
                  ? `1 이상 ${MAX_AMOUNT.toLocaleString('ko-KR')} 이하의 정수를 입력하세요.`
                  : undefined
              }
            >
              <Input
                id={`${row.id}-amount`}
                type="number"
                min={1}
                max={MAX_AMOUNT}
                step={1}
                inputMode="numeric"
                value={row.amount}
                disabled={disabled}
                placeholder="예: 15400"
                onChange={(e) => onChange({ amount: e.target.value })}
              />
            </FormField>
          </>
        ) : (
          <>
            <FormField id={`${row.id}-car`} label="차량종류" required>
              <CarClassSelect
                value={row.carClass}
                disabled={disabled}
                effSettings={effSettings}
                onChange={(carClass) => onChange({ carClass })}
              />
            </FormField>
            <FormField
              id={`${row.id}-km`}
              label="주행거리"
              required
              error={
                row.km && !kmValid
                  ? `1 이상 ${MAX_KM.toLocaleString('ko-KR')} 이하의 정수를 입력하세요.`
                  : undefined
              }
              hint={
                fuelPreview != null
                  ? `지원 금액 미리보기: ${fuelPreview.toLocaleString('ko-KR')}원`
                  : '주행거리를 입력하면 지원 금액이 표시됩니다.'
              }
            >
              <div className="relative">
                <Input
                  id={`${row.id}-km`}
                  type="number"
                  min={1}
                  max={MAX_KM}
                  step={1}
                  inputMode="numeric"
                  value={row.km}
                  disabled={disabled}
                  placeholder="예: 320"
                  className="pr-10"
                  onChange={(e) => onChange({ km: e.target.value })}
                />
                <span className="text-foreground-tertiary pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs">
                  km
                </span>
              </div>
            </FormField>
          </>
        )}

        <FormField id={`${row.id}-project`} label="프로젝트" required>
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
                sub: c.extra?.wbsNm ?? c.extra?.wbsNo ?? undefined,
              }));
            }}
            onSelect={(o) => onChange({ projectCode: o.code, projectName: o.name })}
            onClear={() => onChange({ projectCode: '', projectName: '' })}
          />
        </FormField>

        <FormField id={`${row.id}-note`} label="적요" required>
          <Input
            id={`${row.id}-note`}
            value={row.note}
            disabled={disabled}
            onChange={(e) => onChange({ note: e.target.value })}
          />
        </FormField>
      </div>
    </div>
  );
}

// ── 유형 세그먼트(통행료/유류비 지원) ────────────────────────────────────────
function TypeSegment({
  value,
  disabled,
  onChange,
}: {
  value: RowType;
  disabled?: boolean;
  onChange: (type: RowType) => void;
}) {
  const opts: readonly { key: RowType; label: string }[] = [
    { key: 'toll', label: '통행료' },
    { key: 'fuel', label: '유류비 지원' },
  ];
  return (
    <div className="border-border bg-surface inline-flex rounded-[var(--radius-sm)] border p-0.5">
      {opts.map((o) => (
        <button
          key={o.key}
          type="button"
          disabled={disabled}
          aria-pressed={value === o.key}
          onClick={() => onChange(o.key)}
          className={cn(
            'rounded-[calc(var(--radius-sm)-2px)] px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50',
            value === o.key
              ? 'bg-accent text-accent-foreground'
              : 'text-foreground-secondary hover:text-foreground',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── 차량종류 셀렉트(현재 연비 라벨) ──────────────────────────────────────────
function CarClassSelect({
  value,
  disabled,
  effSettings,
  onChange,
}: {
  value: CarClass;
  disabled?: boolean;
  effSettings: Record<string, number | string | boolean>;
  onChange: (v: CarClass) => void;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as CarClass)}
      className={cn(
        'border-border bg-surface text-foreground h-10 w-full appearance-none rounded-sm border px-3 text-sm',
        'focus-visible:border-accent focus-visible:ring-accent focus-visible:ring-2 focus-visible:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-50',
      )}
    >
      {CAR_CLASSES.map((c) => {
        const eff = effSettings[CAR_CLASS_EFF_KEY[c]];
        const price = effSettings[FUEL_UNIT_PRICE_KEY];
        const suffix = eff != null ? ` (${eff}km/L · ${price}원/L)` : '';
        return (
          <option key={c} value={c}>
            {CAR_CLASS_LABEL[c]}
            {suffix}
          </option>
        );
      })}
    </select>
  );
}

// ── 카탈로그 콤보박스(거래처·프로젝트 공용) ──────────────────────────────────
function CatalogCombobox({
  value,
  placeholder,
  favorites,
  disabled,
  search,
  onSelect,
  onClear,
}: {
  value: { code: string; name: string };
  placeholder: string;
  favorites: ComboOption[];
  disabled?: boolean;
  search: (q: string) => Promise<ComboOption[]>;
  onSelect: (opt: ComboOption) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<ComboOption[] | null>(null);
  const [searchError, setSearchError] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const q = text.trim().toLowerCase();
  const filteredFavs = q
    ? favorites.filter((p) => p.name.toLowerCase().includes(q) || p.code.toLowerCase().includes(q))
    : favorites;

  const pick = (opt: ComboOption) => {
    onSelect(opt);
    setOpen(false);
    setText('');
    setResults(null);
    setSearchError(false);
  };

  const runSearch = useCallback(async () => {
    const query = text.trim();
    if (!query || searching) return;
    setSearching(true);
    setSearchError(false);
    try {
      // 검색 실패(네트워크·서버)와 '결과 없음'은 구분한다 — 실패는 재시도 유도, 빈 배열은 없음 표시.
      setResults(await search(query));
    } catch {
      setSearchError(true);
      setResults(null);
    } finally {
      setSearching(false);
    }
  }, [text, searching, search]);

  return (
    <div ref={wrapRef} className="relative min-w-0">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'border-border bg-surface flex h-10 w-full items-center justify-between gap-1 rounded-sm border px-3 text-left text-sm outline-none',
          'focus-visible:border-accent focus-visible:ring-accent focus-visible:ring-2 disabled:opacity-50',
        )}
      >
        <span className={cn('truncate', value.code ? 'text-foreground' : 'text-muted-foreground')}>
          {value.code ? value.name || value.code : placeholder}
        </span>
      </button>

      {open ? (
        <div className="border-border bg-surface absolute left-0 z-20 mt-1 w-[300px] max-w-[calc(100vw-3rem)] rounded-[var(--radius-md)] border p-2 shadow-[var(--shadow-card)]">
          <div className="flex items-center gap-1.5">
            <input
              autoFocus
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void runSearch();
                }
                if (e.key === 'Escape') setOpen(false);
              }}
              placeholder="자주쓰는 필터 / ERP 검색어"
              className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 min-w-0 flex-1 rounded-sm border px-2 text-xs outline-none focus-visible:ring-2"
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="h-8 shrink-0 px-2"
              disabled={!text.trim() || searching}
              onClick={() => void runSearch()}
            >
              {searching ? <Spinner size={13} /> : <RiSearchLine size={13} aria-hidden />}
              검색
            </Button>
          </div>

          <div className="mt-2 max-h-56 overflow-y-auto">
            {value.code ? (
              <button
                type="button"
                onClick={() => {
                  onClear();
                  setOpen(false);
                }}
                className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-sm px-2 py-1.5 text-left text-xs"
              >
                선택 해제
              </button>
            ) : null}

            {filteredFavs.length > 0 ? (
              <>
                <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                  자주쓰는
                </p>
                {filteredFavs.map((o) => (
                  <OptionRow key={`f-${o.code}`} option={o} onClick={() => pick(o)} />
                ))}
              </>
            ) : null}

            {searchError ? (
              <div className="flex items-center justify-between gap-2 px-2 py-2">
                <p className="text-danger text-xs">검색에 실패했습니다.</p>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="h-7 shrink-0 px-2"
                  disabled={searching}
                  onClick={() => void runSearch()}
                >
                  다시 시도
                </Button>
              </div>
            ) : results && results.length > 0 ? (
              <>
                <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                  ERP 검색결과
                </p>
                {results.map((o) => (
                  <OptionRow key={`s-${o.code}`} option={o} onClick={() => pick(o)} />
                ))}
              </>
            ) : results && results.length === 0 ? (
              <p className="text-foreground-tertiary px-2 py-2 text-xs">검색 결과가 없습니다.</p>
            ) : null}

            {filteredFavs.length === 0 && !results && !searchError ? (
              <p className="text-foreground-tertiary px-2 py-2 text-xs">
                검색어를 입력해 ERP 에서 찾으세요.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function OptionRow({ option, onClick }: { option: ComboOption; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-muted/60 flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-xs"
    >
      <span className="text-foreground truncate">
        {option.name || option.code}
        {option.isDefault ? (
          <span className="text-accent ml-1.5 text-[10px] font-semibold">기본</span>
        ) : null}
      </span>
      {option.sub ? (
        <span className="text-foreground-tertiary shrink-0 truncate">{option.sub}</span>
      ) : null}
    </button>
  );
}
