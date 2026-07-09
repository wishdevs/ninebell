'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RiAddLine, RiDeleteBinLine, RiPlayLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import { fetchCatalog, fetchFavorites, fetchTripDefaults } from '@/lib/api/me-codes';
import { CatalogCombobox, type ComboOption, projectCodeLabel } from './catalog-combobox';
import {
  DEFAULT_FUEL_CLASSES,
  FUEL_UNIT_PRICE_KEY,
  fuelClassesFromSettings,
  fuelSupportAmount,
  type FuelClass,
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
// 차량종류 폴백 id — 설정 로드 전/목록이 비었을 때의 기본 선택(기본 목록 첫 항목).
const FALLBACK_CAR_CLASS = DEFAULT_FUEL_CLASSES[0].id;

// 표(그리드) 열 템플릿 — 헤더행과 데이터행이 공유한다.
// # · 유형 · 프로젝트 · 계산서일 · 거래처|차량 · 금액|주행거리 · 적요 · 삭제
// 거래처/차량 열은 좁게(minmax 7rem,1fr) — 이름/차량 라벨은 셀 안에서 truncate.
// 유형 열은 '유류비 지원'(6자)이 한 줄에 들어가도록 7.5rem.
const ROW_GRID =
  'grid grid-cols-[1.75rem_7.5rem_minmax(9rem,1.4fr)_8.5rem_minmax(7rem,1fr)_minmax(7.5rem,1fr)_minmax(8rem,1.1fr)_1.75rem] items-start gap-x-2 gap-y-1';

type RowType = 'toll' | 'fuel';

interface DraftRow {
  id: string;
  type: RowType;
  // (세금)계산서일 = 증빙일(통행료/유류비 결제일). 행별 입력. yyyy-mm-dd.
  invoiceDate: string;
  // 통행료
  partnerCode: string;
  partnerName: string;
  amount: string;
  // 유류비
  km: string;
  carClass: string; // 차량종류 id(관리자 동적 목록의 안정 식별자)
  // 공통
  projectCode: string;
  projectName: string;
  note: string;
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

/** 새 행 기본값. 거래처(통행료)·프로젝트·차량종류는 직전 선택/기본지정을 이어받는다(반복 입력 편의). */
function emptyRow(
  type: RowType,
  opts?: { partnerDefault?: ComboOption; projectDefault?: ComboOption; carClass?: string },
): DraftRow {
  return {
    id: newRowId(),
    type,
    invoiceDate: todayLocal(),
    partnerCode: type === 'toll' ? (opts?.partnerDefault?.code ?? '') : '',
    partnerName: type === 'toll' ? (opts?.partnerDefault?.name ?? '') : '',
    amount: '',
    km: '',
    carClass: opts?.carClass ?? FALLBACK_CAR_CLASS,
    projectCode: opts?.projectDefault?.code ?? '',
    projectName: opts?.projectDefault?.name ?? '',
    note: type === 'toll' ? DEFAULT_TOLL_NOTE : DEFAULT_FUEL_NOTE,
  };
}

/** 양의 정수 + 상한 검증(빈값·소수·NaN·초과는 무효). ERP 금액/거리는 모두 정수다. */
function isPositiveIntWithin(value: string, max: number): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 && n <= max;
}

function isRowValid(row: DraftRow): boolean {
  if (!row.invoiceDate.trim() || !row.projectCode.trim() || !row.note.trim()) return false;
  if (row.type === 'toll') {
    return !!row.partnerCode.trim() && isPositiveIntWithin(row.amount, MAX_AMOUNT);
  }
  return isPositiveIntWithin(row.km, MAX_KM);
}

/** 마지막 제출 params(초기값 복원용)를 DraftRow 목록으로 되돌린다. 없으면 빈 결과. */
function seedFromParams(initial: Record<string, unknown> | undefined): {
  rows?: DraftRow[];
} {
  const trip = initial?.trip as { rows?: unknown[] } | undefined;
  if (!trip || !Array.isArray(trip.rows) || trip.rows.length === 0) return {};
  const rows = trip.rows.map((raw): DraftRow => {
    const r = raw as Record<string, unknown>;
    const project = (r.project ?? {}) as { code?: string; name?: string };
    const common = {
      id: newRowId(),
      invoiceDate: typeof r.invoiceDate === 'string' ? r.invoiceDate : todayLocal(),
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
        carClass: typeof r.carClass === 'string' ? r.carClass : FALLBACK_CAR_CLASS,
      };
    }
    return {
      ...common,
      type: 'toll',
      partnerCode: typeof r.partnerCode === 'string' ? r.partnerCode : '',
      partnerName: typeof r.partnerName === 'string' ? r.partnerName : '',
      amount: r.amount != null ? String(r.amount) : '',
      km: '',
      carClass: FALLBACK_CAR_CLASS,
    };
  });
  return { rows };
}

export function TripPreRunForm({ agent, disabled, initialParams, onStart }: PreRunFormProps) {
  // 마지막 제출값 복원(실패 후 값 수정 재실행) — 부모가 key 로 remount 하면 초기값이 다시 시드된다.
  const seed = useMemo(() => seedFromParams(initialParams), [initialParams]);
  const [rows, setRows] = useState<DraftRow[]>(() => seed.rows ?? [emptyRow('toll')]);
  // 직전에 고른 차량종류 — 보통 한 차량으로 신청하므로 다음 유류비 행에 같은 값을 기본으로.
  const [lastCarClass, setLastCarClass] = useState<string>(
    () => seed.rows?.find((r) => r.type === 'fuel')?.carClass ?? FALLBACK_CAR_CLASS,
  );

  // 거래처·프로젝트 자주쓰는 — 폼 진입 시 1회 로드(백엔드 미배포면 빈 배열). favsLoaded 로 완료 신호.
  const [partnerFavs, setPartnerFavs] = useState<ComboOption[]>([]);
  const [projectFavs, setProjectFavs] = useState<ComboOption[]>([]);
  const [favsLoaded, setFavsLoaded] = useState(false);
  // 팀 비용구분(판/제)에 맞춘 기본 프로젝트 — 서버가 카드 자동화와 동일 규칙으로 해석(500/800).
  // null = 아직 로드 전(기본값 적용을 이 로드 완료까지 대기시켜 비용구분 우선을 보장).
  const [tripDefaultProject, setTripDefaultProject] = useState<ComboOption | null | undefined>(
    undefined,
  );

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const favs = await fetchPartnerFavorites();
        if (alive) {
          setPartnerFavs(
            favs.map((f) => ({
              code: f.code,
              name: f.name,
              codeLabel: f.code,
              isDefault: f.isDefault,
            })),
          );
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
              codeLabel: projectCodeLabel(f.code, f.extra?.pjtNo ?? undefined),
              sub: f.extra?.wbsNm ?? f.extra?.wbsNo ?? undefined,
              isDefault: f.isDefault,
            })),
          );
        }
      } catch {
        /* 무시 */
      }
      if (alive) setFavsLoaded(true);
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 팀 비용구분 기본 프로젝트 로드(별도 비동기). 실패/미배정이면 null → isDefault 즐겨찾기로 폴백.
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

  const partnerDefault = useMemo(() => partnerFavs.find((p) => p.isDefault), [partnerFavs]);
  // 기본 프로젝트 = **소속 팀 비용구분(조직 설정) 프로젝트 우선**, 없으면 기본지정(★) 즐겨찾기 폴백.
  // 판관비 팀인데 제조원가 프로젝트가 기본으로 잡히던 문제 → 조직 설정과 일치시킨다.
  const projectDefault = useMemo(
    () => tripDefaultProject ?? projectFavs.find((p) => p.isDefault),
    [tripDefaultProject, projectFavs],
  );

  // 기본값 1회 적용 — 세 비동기 소스(즐겨찾기·트립 기본 프로젝트)가 모두 확정된 뒤 아직 비어 있는
  // 행의 거래처·프로젝트를 채운다. 복원(seed)·사용자가 이미 고른 값은 덮지 않는다(빈 값만). ref 가드.
  const defaultsApplied = useRef(false);
  useEffect(() => {
    if (defaultsApplied.current) return;
    if (!favsLoaded || tripDefaultProject === undefined) return; // 모든 소스 확정 대기(비용구분 우선 보장).
    defaultsApplied.current = true;
    setRows((rs) =>
      rs.map((r) => {
        const patch: Partial<DraftRow> = {};
        if (projectDefault && !r.projectCode) {
          patch.projectCode = projectDefault.code;
          patch.projectName = projectDefault.name;
        }
        if (partnerDefault && r.type === 'toll' && !r.partnerCode) {
          patch.partnerCode = partnerDefault.code;
          patch.partnerName = partnerDefault.name;
        }
        return Object.keys(patch).length ? { ...r, ...patch } : r;
      }),
    );
  }, [favsLoaded, tripDefaultProject, projectDefault, partnerDefault]);

  // 현재 유효 설정(단가 + 차량종류 목록) — 스키마 기본값 위에 관리자 저장값(실효값) 오버레이.
  const effSettings = useMemo<Record<string, unknown>>(() => {
    const base: Record<string, unknown> = {};
    for (const d of agent.settingsSchema ?? []) base[d.key] = d.default;
    return { ...base, ...(agent.settings ?? {}) };
  }, [agent.settingsSchema, agent.settings]);

  const updateRow = useCallback((id: string, patch: Partial<DraftRow>) => {
    // 차량종류를 고르면 다음 유류비 행 기본값으로 기억한다(같은 차량 반복 신청 편의).
    if (patch.carClass) setLastCarClass(patch.carClass);
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const setRowType = useCallback(
    (id: string, type: RowType) => {
      setRows((rs) =>
        rs.map((r) => {
          if (r.id !== id || r.type === type) return r;
          // 유형 전환 시 유형별 필드 초기화 + 적요를 유형 기본값으로. 유류비로 바꾸면 직전 차량종류 이어받기.
          return {
            ...r,
            type,
            partnerCode: type === 'toll' ? (partnerDefault?.code ?? '') : '',
            partnerName: type === 'toll' ? (partnerDefault?.name ?? '') : '',
            amount: '',
            km: '',
            carClass: type === 'fuel' ? lastCarClass : r.carClass,
            note: type === 'toll' ? DEFAULT_TOLL_NOTE : DEFAULT_FUEL_NOTE,
          };
        }),
      );
    },
    [partnerDefault, lastCarClass],
  );

  const addRow = useCallback(() => {
    setRows((rs) => {
      if (rs.length >= MAX_ROWS) return rs;
      // 새 행은 직전(마지막) 행과 같은 유형으로 — 보통 같은 성격의 건을 연속 입력한다.
      const lastType = rs[rs.length - 1]?.type ?? 'toll';
      return [
        ...rs,
        emptyRow(lastType, { partnerDefault, projectDefault, carClass: lastCarClass }),
      ];
    });
  }, [partnerDefault, projectDefault, lastCarClass]);

  const removeRow = useCallback((id: string) => {
    setRows((rs) => (rs.length <= 1 ? rs : rs.filter((r) => r.id !== id)));
  }, []);

  const canSubmit = !disabled && rows.length > 0 && rows.every(isRowValid);

  // 회계일자 = 계산서일(증빙일) 중 가장 마지막일(따로 입력받지 않고 파생 — 백엔드도 동일 규칙).
  const acctPreview = useMemo(() => {
    const dates = rows
      .map((r) => r.invoiceDate)
      .filter(Boolean)
      .sort();
    return dates.length > 0 ? dates[dates.length - 1] : '';
  }, [rows]);

  // 금액 총합 미리보기 — 통행료=입력 금액, 유류비=백엔드와 동일 규칙(fuelSupportAmount). 무효 행은 0.
  const grandTotal = useMemo(
    () =>
      rows.reduce((sum, r) => {
        if (r.type === 'toll') {
          return isPositiveIntWithin(r.amount, MAX_AMOUNT) ? sum + Number(r.amount) : sum;
        }
        if (!isPositiveIntWithin(r.km, MAX_KM)) return sum;
        const amt = fuelSupportAmount(Number(r.km), r.carClass, effSettings);
        return amt != null ? sum + amt : sum;
      }, 0),
    [rows, effSettings],
  );

  const submit = () => {
    if (!canSubmit) return;
    const payloadRows = rows.map((r) => {
      const project: Record<string, string> = { code: r.projectCode, name: r.projectName };
      if (r.type === 'toll') {
        return {
          type: 'toll' as const,
          invoiceDate: r.invoiceDate,
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
        invoiceDate: r.invoiceDate,
        km: Number(r.km),
        carClass: r.carClass,
        project,
        note: r.note,
      };
    });
    // 회계일자는 보내지 않는다 — 백엔드가 계산서일 최댓값으로 파생한다.
    onStart({ trip: { rows: payloadRows } });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title="출장(국내/자차) 결의서"
      description="행마다 계산서일(증빙일)과 통행료·유류비 지원을 표에 입력하면 무개입으로 채워 저장합니다. 회계일자는 계산서일 중 가장 마지막일로 자동 지정됩니다."
      density="comfortable"
    >
      <div className="max-sm:overflow-x-auto">
        <div className="flex min-w-[52rem] flex-col gap-1 sm:min-w-0">
          {/* 표 헤더(sm 이상에서만; 모바일은 각 셀 aria-label 로 대체) */}
          <div
            className={cn(
              ROW_GRID,
              'border-border/60 text-foreground-tertiary border-b px-1 pb-1.5 text-[10px] font-semibold tracking-wider uppercase',
            )}
          >
            <span aria-hidden />
            <span>유형</span>
            <span>프로젝트</span>
            <span>계산서일</span>
            <span>거래처 / 차량</span>
            <span>금액 / 주행거리</span>
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
              effSettings={effSettings}
              partnerFavs={partnerFavs}
              projectFavs={projectFavs}
              onType={(t) => setRowType(row.id, t)}
              onChange={(patch) => updateRow(row.id, patch)}
              onRemove={() => removeRow(row.id)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            size="sm"
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
        <div className="flex items-center gap-3">
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
            title={canSubmit ? undefined : '모든 필수 입력을 완료하면 실행할 수 있습니다.'}
          >
            <RiPlayLine size={15} aria-hidden />
            실행
          </Button>
        </div>
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
  effSettings: Record<string, unknown>;
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
    <div className={cn(ROW_GRID, 'border-border/50 border-b py-1.5 last:border-b-0')}>
      {/* # */}
      <span className="text-foreground-tertiary pt-2.5 text-center text-xs font-semibold tabular-nums">
        {index + 1}
      </span>

      {/* 유형 */}
      <div className="min-w-0">
        <TypeSelect value={row.type} disabled={disabled} onChange={onType} />
      </div>

      {/* 프로젝트 */}
      <div className="min-w-0">
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
      <div className="min-w-0">
        <DatePicker
          ariaLabel={`${index + 1}행 계산서일`}
          value={row.invoiceDate}
          disabled={disabled}
          onChange={(v) => onChange({ invoiceDate: v })}
        />
      </div>

      {/* 거래처 / 차량종류 */}
      <div className="min-w-0">
        {row.type === 'toll' ? (
          <CatalogCombobox
            value={{ code: row.partnerCode, name: row.partnerName }}
            placeholder="거래처 선택"
            favorites={partnerFavs}
            disabled={disabled}
            search={async (q) =>
              (await fetchPartnerCatalog(q)).map((o) => ({ ...o, codeLabel: o.code }))
            }
            onSelect={(o) => onChange({ partnerCode: o.code, partnerName: o.name })}
            onClear={() => onChange({ partnerCode: '', partnerName: '' })}
          />
        ) : (
          <CarClassSelect
            value={row.carClass}
            disabled={disabled}
            classes={fuelClassesFromSettings(effSettings)}
            unitPrice={Number(effSettings[FUEL_UNIT_PRICE_KEY]) || null}
            onChange={(carClass) => onChange({ carClass })}
          />
        )}
      </div>

      {/* 금액 / 주행거리 */}
      <div className="flex min-w-0 flex-col gap-1">
        {row.type === 'toll' ? (
          <>
            <Input
              type="number"
              min={1}
              max={MAX_AMOUNT}
              step={1}
              inputMode="numeric"
              aria-label={`${index + 1}행 금액(공급가액)`}
              value={row.amount}
              disabled={disabled}
              placeholder="예: 15400"
              onChange={(e) => onChange({ amount: e.target.value })}
            />
            {row.amount && !isPositiveIntWithin(row.amount, MAX_AMOUNT) ? (
              <p className="text-danger text-[11px]">
                1 ~ {MAX_AMOUNT.toLocaleString('ko-KR')} 정수
              </p>
            ) : null}
          </>
        ) : (
          <>
            <div className="relative">
              <Input
                type="number"
                min={1}
                max={MAX_KM}
                step={1}
                inputMode="numeric"
                aria-label={`${index + 1}행 주행거리`}
                value={row.km}
                disabled={disabled}
                placeholder="예: 320"
                className="pr-9"
                onChange={(e) => onChange({ km: e.target.value })}
              />
              <span className="text-foreground-tertiary pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-xs">
                km
              </span>
            </div>
            {row.km && !kmValid ? (
              <p className="text-danger text-[11px]">1 ~ {MAX_KM.toLocaleString('ko-KR')} 정수</p>
            ) : fuelPreview != null ? (
              <p className="text-foreground-tertiary text-[11px]">
                지원 {fuelPreview.toLocaleString('ko-KR')}원
              </p>
            ) : null}
          </>
        )}
      </div>

      {/* 적요 */}
      <div className="min-w-0">
        <Input
          aria-label={`${index + 1}행 적요`}
          value={row.note}
          disabled={disabled}
          onChange={(e) => onChange({ note: e.target.value })}
        />
      </div>

      {/* 삭제 */}
      {canRemove ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-foreground-tertiary hover:text-danger mt-1 px-0"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`${index + 1}번째 행 삭제`}
        >
          <RiDeleteBinLine size={15} aria-hidden />
        </Button>
      ) : (
        <span aria-hidden />
      )}
    </div>
  );
}

// ── 유형 셀렉트(통행료/유류비 지원) — 디자인 셀렉트(Radix, 표 셀 폭) ───────────
function TypeSelect({
  value,
  disabled,
  onChange,
}: {
  value: RowType;
  disabled?: boolean;
  onChange: (type: RowType) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as RowType)} disabled={disabled}>
      <SelectTrigger aria-label="행 유형" className="h-10 w-full min-w-0 rounded-sm text-sm">
        <SelectValue className="min-w-0 flex-1 truncate text-left" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="toll">통행료</SelectItem>
        <SelectItem value="fuel">유류비 지원</SelectItem>
      </SelectContent>
    </Select>
  );
}

// ── 차량종류 셀렉트(관리자 동적 목록) — 디자인 셀렉트(Radix) ──────────────────
function CarClassSelect({
  value,
  disabled,
  classes,
  unitPrice,
  onChange,
}: {
  value: string;
  disabled?: boolean;
  classes: readonly FuelClass[];
  unitPrice: number | null;
  onChange: (v: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger aria-label="차량종류" className="h-10 w-full min-w-0 rounded-sm text-sm">
        <SelectValue className="min-w-0 flex-1 truncate text-left" />
      </SelectTrigger>
      <SelectContent>
        {classes.map((c) => (
          // 트리거엔 라벨만, 연비·단가는 목록에서만(hint = ItemText 밖).
          <SelectItem
            key={c.id}
            value={c.id}
            hint={unitPrice != null ? `${c.kmPerL}km/L · ${unitPrice}원/L` : `${c.kmPerL}km/L`}
          >
            {c.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
