'use client';

import { useRef, useState } from 'react';
import {
  RiArrowDownSLine,
  RiCheckLine,
  RiCloseLine,
  RiInformationLine,
  RiPlayLine,
  RiSearchLine,
} from '@remixicon/react';
import { ComboPanel, isDesktopViewport, useOutsideClose } from '@/components/live/combo-popover';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { FormField } from '@/components/ui/form-field';
import { SectionCard } from '@/components/ui/section-card';
import { useDebugMode } from '@/lib/debug-mode';
import { cn } from '@/lib/utils';
import { menuItemsFromSettings, type VoucherMenuItem } from '@/lib/voucher/menu-items';
import type { PreRunFormProps } from './index';

/**
 * 유형별 전표조회 승인(voucher-by-type) 실행 전 폼 — 회계일 조회기간 + 전표유형 다중선택 +
 * 메뉴 필터.
 *
 * 종전 외상매출금(국내매출·해외매출)·외상매입금(내수구매) 두 에이전트를 전표유형 선택으로
 * 통합한 폼이다. 프리셋 버튼(외상매출금/외상매입금)은 종전 두 에이전트와 같은 유형 조합을
 * 한 번에 선택한다.
 *
 * 백엔드 계약: `params["voucher"] = { period_from, period_to, docu_types, menu_filters? }`.
 * docu_types 는 전표유형 라벨(SYSDEF_NM) 배열, menu_filters 는 그리드 '메뉴' 텍스트 배열
 * (미선택 = 키 자체를 보내지 않음 = 필터 없이 전체 메뉴).
 */

// 전표유형(SYSDEF_CD/SYSDEF_NM) 전체 카탈로그 — ERP 피커 실측 62종
// (backend/e2e/artifacts/voucher_receivable_docu_type_diag.json). 백엔드 상수
// `DOCU_TYPE_CATALOG`(app/agents/voucher_receivable/steps.py)와 **패리티 테스트로 잠겨 있다**.
// 백엔드 set_docu_types 는 라벨(SYSDEF_NM)로 피커를 체크하므로 라벨이 곧 계약값이고,
// 코드는 검색·표시용이다(같은 라벨이 없어 라벨만으로도 유일).
const DOCU_TYPE_CATALOG: readonly { code: string; label: string }[] = [
  { code: '11', label: '일반' },
  { code: '12', label: '결산대체' },
  { code: '13', label: '결산역분개' },
  { code: '21', label: '국내매출' },
  { code: '22', label: '국내수금' },
  { code: '23', label: '해외매출' },
  { code: '24', label: '해외수금' },
  { code: '25', label: '선수금' },
  { code: '26', label: '선수금 반제' },
  { code: '27', label: '해외선수금' },
  { code: '28', label: '해외선수금 반제' },
  { code: '31', label: '내수구매' },
  { code: '32', label: '외자구매' },
  { code: '14A', label: '결산손익역분개' },
  { code: '33', label: '선급금' },
  { code: '15A', label: '결산원가역분개' },
  { code: '34', label: '선급금반제' },
  { code: '41', label: '입고전기' },
  { code: '42', label: '출고전기' },
  { code: '43', label: '이동전기' },
  { code: '19', label: '일반전표역분개' },
  { code: '44', label: '이전전기' },
  { code: '51', label: '생산출고' },
  { code: '52', label: '생산입고' },
  { code: '53', label: '연산품입고' },
  { code: '54', label: '부산물입고' },
  { code: '55', label: '연산품출고(취소)' },
  { code: '56', label: '부산물출고(취소)' },
  { code: '61', label: '수출제비용' },
  { code: '62', label: '수입부대비용' },
  { code: '63', label: '미착정산' },
  { code: '29', label: '결산대체(자산)' },
  { code: '71', label: '급여' },
  { code: '72', label: '퇴직금' },
  { code: '73', label: '사업/기타소득' },
  { code: '74', label: '복리후생' },
  { code: '75', label: '교육' },
  { code: '14', label: '결산손익대체' },
  { code: '15', label: '결산원가대체' },
  { code: '35', label: '내수구매비용' },
  { code: '81', label: 'PS정산' },
  { code: '82', label: 'PM정산' },
  { code: '91', label: '리스임차' },
  { code: '16', label: '결산외화평가' },
  { code: '17', label: '결산역분개외화평가' },
  { code: '18', label: '건설중인자산대체' },
  { code: '76', label: '출장' },
  { code: '77', label: '퇴직금추계액' },
  { code: '94', label: '진행매출' },
  { code: '94A', label: '진행매출역분개' },
  { code: '95', label: '결산원가' },
  { code: '96', label: '급여안분' },
  { code: '97', label: '자산이동' },
  { code: '98', label: '리스임대' },
  { code: '99', label: '리스임대수납' },
  { code: '100', label: '자산처분' },
  { code: '101', label: '충당금결산' },
  { code: '102', label: '재고평가' },
  { code: '103', label: '원가정산' },
  { code: '104', label: '전자상거래 국내매출' },
  { code: '105', label: '전자상거래 해외매출' },
  { code: '106', label: 'IU(MIG)' },
] as const;

type DocuType = string;
const ALL_DOCU_TYPES: readonly DocuType[] = DOCU_TYPE_CATALOG.map((t) => t.label);
// 폼 기본 선택 — 병합 전 두 에이전트(외상매출금·외상매입금)와 같은 조합(백엔드 기본값과 동일).
const DEFAULT_DOCU_TYPES: readonly DocuType[] = ['국내매출', '해외매출', '내수구매'];

// 종전 에이전트와 같은 조합을 한 번에 선택하는 프리셋 — 현재 선택을 통째로 교체한다.
const PRESETS: readonly { label: string; types: readonly DocuType[] }[] = [
  { label: '외상매출금', types: ['국내매출', '해외매출'] },
  { label: '외상매입금', types: ['내수구매'] },
];

// 셀렉트 항목 변환 — 토글 키 = 라벨(백엔드 계약값), 코드는 보조 표기·코드 검색용.
const DOCU_COMBO_ITEMS: readonly MultiComboItem[] = DOCU_TYPE_CATALOG.map((t) => ({
  key: t.label,
  label: t.label,
  code: t.code,
}));

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** 로컬 기준 'yyyy-mm-dd'(TZ 밀림 방지 — toISOString 미사용, DatePicker 와 같은 규약). */
function toIso(y: number, m1: number, d: number): string {
  return `${y}-${pad2(m1)}-${pad2(d)}`;
}

/** 이번 달 1일~말일(로컬 기준) — 폼 기본값. */
function currentMonthRange(): { from: string; to: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m1 = now.getMonth() + 1;
  const last = new Date(y, m1, 0).getDate(); // 다음 달 0일 = 이번 달 말일
  return { from: toIso(y, m1, 1), to: toIso(y, m1, last) };
}

/** 'YYYYMMDD' | 'YYYY-MM-DD' → 'YYYY-MM-DD'. 형식 불일치는 undefined(기본값 사용). */
function toDateInput(v: unknown): string | undefined {
  if (typeof v !== 'string') return undefined;
  const digits = v.replace(/-/g, '');
  if (!/^\d{8}$/.test(digits)) return undefined;
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
}

function voucherSeed(initial: Record<string, unknown> | undefined): Record<string, unknown> {
  const v = initial?.voucher;
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

/** 마지막 제출 params → 기간 복원(종료 후 값 수정 재실행). 없으면 이번 달. */
function seedRange(seed: Record<string, unknown>): { from: string; to: string } {
  const fallback = currentMonthRange();
  return {
    from: toDateInput(seed.period_from) ?? fallback.from,
    to: toDateInput(seed.period_to) ?? fallback.to,
  };
}

/** 마지막 제출 params → 전표유형 복원. 시드가 없으면 기본 3종(병합 전 동작)으로 시작한다. */
function seedDocuTypes(seed: Record<string, unknown>): DocuType[] {
  const raw = seed.docu_types;
  if (!Array.isArray(raw)) return [...DEFAULT_DOCU_TYPES];
  const restored = ALL_DOCU_TYPES.filter((t) => raw.includes(t));
  return restored.length > 0 ? restored : [...DEFAULT_DOCU_TYPES];
}

/**
 * 마지막 제출 params → 메뉴 필터 복원. menu_filters 시드가 있으면 defaultSelected 보다
 * 우선하고(라벨 매칭), 없으면 defaultSelected 항목이 초기 체크된다.
 */
function seedMenuIds(
  seed: Record<string, unknown>,
  items: readonly VoucherMenuItem[],
): Set<string> {
  const raw = seed.menu_filters;
  if (Array.isArray(raw)) {
    const labels = new Set(raw.filter((x): x is string => typeof x === 'string'));
    return new Set(items.filter((it) => labels.has(it.label)).map((it) => it.id));
  }
  return new Set(items.filter((it) => it.defaultSelected).map((it) => it.id));
}

export function VoucherTypePreRunForm({
  agent,
  disabled,
  initialParams,
  onStart,
}: PreRunFormProps) {
  const debugMode = useDebugMode();
  const [seed] = useState(() => voucherSeed(initialParams));
  const [range] = useState(() => seedRange(seed));
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const [docuTypes, setDocuTypes] = useState<DocuType[]>(() => seedDocuTypes(seed));

  // 메뉴 필터 — 항목 목록은 관리자가 에이전트 관리에서 관리하는 공유 데이터(settings.menu_items)라
  // 여기서는 읽기 전용이고, 체크 상태만 이 실행 한정으로 고른다.
  const [menuItems] = useState<VoucherMenuItem[]>(() => menuItemsFromSettings(agent.settings));
  const [selectedMenuIds, setSelectedMenuIds] = useState<Set<string>>(() =>
    seedMenuIds(seed, menuItemsFromSettings(agent.settings)),
  );

  const rangeInvalid = !!from && !!to && from > to;
  const canSubmit = !disabled && !!from && !!to && !rangeInvalid && docuTypes.length > 0;

  const toggleDocuType = (t: DocuType) => {
    setDocuTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
  };

  const toggleMenu = (id: string) => {
    setSelectedMenuIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const submit = () => {
    if (!canSubmit) return;
    const selectedTypes = ALL_DOCU_TYPES.filter((t) => docuTypes.includes(t)); // 카탈로그 순서 고정.
    const selectedMenus = menuItems
      .filter((it) => selectedMenuIds.has(it.id))
      .map((it) => it.label);
    // 백엔드 계약: params["voucher"] — 서버가 YYYYMMDD 정규화 + 시작>종료 재검증한다.
    // menu_filters 는 미선택 시 키 자체를 생략한다(= 필터 없음, 전체 메뉴).
    onStart({
      voucher: {
        period_from: from,
        period_to: to,
        docu_types: selectedTypes,
        ...(selectedMenus.length ? { menu_filters: selectedMenus } : {}),
      },
    });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title={`${agent.name} — 조회 조건`}
      description="조회할 회계일 기간과 전표유형을 지정하고 실행하세요. 기본 기간은 이번 달 1일~말일이며, 월 일부 기간(예: 1일~5일)도 지정할 수 있습니다. 나머지 조회 조건(전표상태 미결·전자결재상태 저장)은 고정입니다."
      density="comfortable"
    >
      <div className="border-border/60 bg-muted/30 flex gap-2 rounded-[var(--radius-md)] border p-3">
        <RiInformationLine
          size={16}
          aria-hidden
          className="text-foreground-tertiary mt-0.5 shrink-0"
        />
        <p className="text-foreground-tertiary text-xs leading-relaxed">
          {debugMode ? (
            <>
              <b>디버그 모드 — 상신 버튼을 클릭하지 않습니다.</b> 결제창 확인(가상 상신)까지만
              수행하며, 전표는 목록에 그대로 남습니다.
            </>
          ) : (
            <>
              지정한 기간·전표유형의 대상 전표를 순회하며 결제창을 열어{' '}
              <b>전자결재로 실제 상신합니다.</b> 전표 저장·삭제는 하지 않습니다.
            </>
          )}
        </p>
      </div>

      {/* 필드 배치 — 1열 세로 나열: 회계일 시작 → 종료 → 전표유형 → 메뉴 필터.
        전 필드가 셀렉트/입력 한 줄 컨트롤이라 2단 없이 위→아래 읽기 흐름이 가장 단순하다
        (사용자 확정 2026-08-21). */}
      <div className="grid gap-5">
        <FormField
          id="voucher-period-from"
          label="회계일 시작"
          required
          error={rangeInvalid ? '시작일이 종료일보다 늦을 수 없습니다.' : undefined}
        >
          <DatePicker
            ariaLabel="회계일 시작일"
            value={from}
            disabled={disabled}
            onChange={setFrom}
          />
        </FormField>

        <FormField id="voucher-period-to" label="회계일 종료" required>
          <DatePicker ariaLabel="회계일 종료일" value={to} disabled={disabled} onChange={setTo} />
        </FormField>

        <FormField id="voucher-docu-types" label="전표유형" required>
          <div className="grid gap-1.5">
            {/* 헤더 행 — 좌: 선택 수, 우: 프리셋. */}
            <div className="flex min-h-6 flex-wrap items-center justify-between gap-2">
              <span className="text-foreground-tertiary text-xs tabular-nums">
                {docuTypes.length}종 선택
              </span>
              <div className="flex items-center gap-0.5">
                <span className="text-foreground-tertiary mr-1 text-xs">프리셋</span>
                {PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    disabled={disabled}
                    title={`${preset.types.join('·')} 조합으로 교체`}
                    onClick={() => setDocuTypes([...preset.types])}
                    className="text-accent hover:bg-accent/10 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-xs font-medium transition-colors disabled:opacity-50 max-md:min-h-9 max-md:px-2"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <MultiSelectCombo
              ariaLabel="전표유형 선택"
              disabled={disabled}
              items={DOCU_COMBO_ITEMS}
              selectedKeys={docuTypes}
              onToggle={toggleDocuType}
              placeholder="전표유형 선택"
              searchPlaceholder="검색 — 이름 또는 코드(예: 매출, 31, 결산)"
              unit="종"
            />
          </div>
        </FormField>

        <FormField id="voucher-menu-filters" label="메뉴 필터">
          <div className="grid gap-1.5">
            {/* 헤더 행 — 전표유형 헤더와 같은 높이·톤. */}
            <div className="flex min-h-6 items-center">
              <span className="text-foreground-tertiary text-xs tabular-nums">
                {selectedMenuIds.size === 0
                  ? '선택 없음 — 전체 메뉴 대상'
                  : `${selectedMenuIds.size}개 선택`}
              </span>
            </div>

            <MultiSelectCombo
              ariaLabel="메뉴 필터 선택"
              disabled={disabled}
              items={menuItems.map((it) => ({ key: it.id, label: it.label }))}
              selectedKeys={[...selectedMenuIds]}
              onToggle={toggleMenu}
              placeholder="전체 메뉴 (선택 없음)"
              searchPlaceholder="메뉴 검색"
              unit="개"
              footerHint="체크한 메뉴의 전표만 상신 대상 · 항목 관리는 에이전트 관리에서"
            />
          </div>
        </FormField>
      </div>

      {/* 실행 바 — 데스크톱은 분리선 위 우측 정렬, md 미만은 페이지 스크롤 기준 sticky 하단 바. */}
      <div
        className={cn(
          'flex flex-col gap-2 md:flex-row md:items-center md:justify-end md:gap-3',
          'md:border-border/60 md:border-t md:pt-4',
          'max-md:sticky max-md:bottom-0 max-md:z-10 max-md:-mx-6',
          'max-md:border-border/60 max-md:bg-surface/95 max-md:border-t max-md:px-6 max-md:pt-3 max-md:pb-[max(0.75rem,env(safe-area-inset-bottom))] max-md:backdrop-blur',
        )}
      >
        {/* 비활성 사유 — disabled:pointer-events-none 라 title 툴팁은 안 뜨므로 인라인으로 안내. */}
        {!canSubmit ? (
          <p className="text-foreground-tertiary text-xs md:text-right">
            {docuTypes.length === 0
              ? '전표유형을 1개 이상 선택하면 실행할 수 있습니다.'
              : '회계일 기간을 올바르게 지정하면 실행할 수 있습니다.'}
          </p>
        ) : null}
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
    </SectionCard>
  );
}

// ── 다중선택 셀렉트(검색형) ──────────────────────────────────────────

interface MultiComboItem {
  /** 토글 키(전표유형=라벨(계약값), 메뉴=항목 id). */
  key: string;
  label: string;
  /** 보조 표기 + 코드 접두 검색용(전표유형만). */
  code?: string;
}

/**
 * 폼 스케일 다중선택 셀렉트 — 트리거(선택 요약)를 누르면 검색 + 체크 목록 패널이 열린다.
 * 패널 셸(md 미만 바텀시트 / md+ 팝오버)·바깥 닫기는 combo-popover 공용을 쓰고, 체크
 * 토글이라 항목을 눌러도 닫지 않는다(닫기 = 바깥 클릭·Esc·모바일 완료 버튼).
 */
function MultiSelectCombo({
  ariaLabel,
  items,
  selectedKeys,
  onToggle,
  disabled,
  placeholder,
  searchPlaceholder,
  unit,
  footerHint,
}: {
  ariaLabel: string;
  items: readonly MultiComboItem[];
  selectedKeys: readonly string[];
  onToggle: (key: string) => void;
  disabled?: boolean;
  /** 선택 0개일 때 트리거 문구. */
  placeholder: string;
  searchPlaceholder: string;
  /** 개수 단위('종'/'개') — 패널 푸터 카운터에 쓴다. */
  unit: string;
  footerHint?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);

  const close = () => {
    setOpen(false);
    setQuery('');
  };
  useOutsideClose(open, wrapRef, close);

  // 라벨 부분일치 + 코드 접두 일치(사용자가 '31' 같은 코드로도 찾는다).
  const q = query.trim().toLowerCase();
  const visible = q
    ? items.filter(
        (it) =>
          it.label.toLowerCase().includes(q) || (it.code?.toLowerCase().startsWith(q) ?? false),
      )
    : items;

  const selectedSet = new Set(selectedKeys);
  const summary = items
    .filter((it) => selectedSet.has(it.key))
    .map((it) => it.label)
    .join(' · ');

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => (open ? close() : setOpen(true))}
        className={cn(
          // DatePicker 트리거와 같은 폼 스케일(h-10·px-3·text-sm) — 폼 컨트롤 라인 통일.
          'border-border bg-surface flex h-10 w-full items-center justify-between gap-2 rounded-sm border px-3 text-left text-sm outline-none',
          'focus-visible:border-accent disabled:opacity-50',
          open && 'border-accent',
        )}
      >
        <span
          className={cn('min-w-0 truncate', summary ? 'text-foreground' : 'text-muted-foreground')}
        >
          {summary || placeholder}
        </span>
        <RiArrowDownSLine
          size={16}
          aria-hidden
          className={cn(
            'text-foreground-tertiary shrink-0 transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open ? (
        <ComboPanel onClose={close} className="md:w-full">
          <div className="border-border bg-surface focus-within:border-accent flex h-9 shrink-0 items-center gap-2 rounded-[var(--radius-sm)] border px-2">
            <RiSearchLine size={14} aria-hidden className="text-foreground-tertiary shrink-0" />
            <input
              autoFocus={isDesktopViewport()}
              value={query}
              placeholder={searchPlaceholder}
              aria-label={`${ariaLabel} 검색`}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.preventDefault();
                  close();
                }
              }}
              className="text-foreground placeholder:text-muted-foreground h-full w-full bg-transparent text-sm outline-none"
            />
            {query ? (
              <button
                type="button"
                aria-label="검색어 지우기"
                onClick={() => setQuery('')}
                className="text-foreground-tertiary hover:text-foreground flex size-5 shrink-0 items-center justify-center rounded-full transition-colors"
              >
                <RiCloseLine size={13} aria-hidden />
              </button>
            ) : null}
          </div>

          <div
            role="group"
            aria-label={ariaLabel}
            className="mt-2 grid min-h-0 flex-1 gap-0.5 overflow-y-auto overscroll-contain md:max-h-60 md:flex-none"
          >
            {visible.length === 0 ? (
              <p className="text-foreground-tertiary px-2 py-3 text-xs">
                {`'${query}' 와 일치하는 항목이 없습니다.`}
              </p>
            ) : (
              visible.map((it) => {
                const active = selectedSet.has(it.key);
                return (
                  <button
                    key={it.key}
                    type="button"
                    role="checkbox"
                    aria-checked={active}
                    disabled={disabled}
                    onClick={() => onToggle(it.key)}
                    className={cn(
                      'flex items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-sm transition-colors disabled:opacity-50 max-md:min-h-11',
                      active
                        ? 'bg-accent/10 text-foreground font-medium'
                        : 'text-foreground-secondary hover:bg-muted/60',
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        'flex size-4 shrink-0 items-center justify-center rounded-[5px] border transition-colors',
                        active
                          ? 'border-accent bg-accent text-white'
                          : 'border-border-strong bg-surface',
                      )}
                    >
                      {active ? <RiCheckLine size={11} /> : null}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{it.label}</span>
                    {it.code ? (
                      <span className="text-foreground-tertiary shrink-0 font-mono text-[11px] tabular-nums">
                        {it.code}
                      </span>
                    ) : null}
                  </button>
                );
              })
            )}
          </div>

          <div className="border-border/60 text-foreground-tertiary mt-1 shrink-0 border-t px-1 pt-1.5 text-[11px] leading-relaxed">
            <span className="tabular-nums">
              {q
                ? `${items.length}${unit} 중 ${visible.length}${unit} 표시`
                : `전체 ${items.length}${unit}`}
            </span>
            {footerHint ? <> · {footerHint}</> : null}
          </div>

          <button
            type="button"
            onClick={close}
            className="border-border bg-surface text-foreground mt-2 h-11 w-full shrink-0 rounded-[var(--radius-sm)] border text-sm font-medium md:hidden"
          >
            완료
          </button>
        </ComboPanel>
      ) : null}
    </div>
  );
}
