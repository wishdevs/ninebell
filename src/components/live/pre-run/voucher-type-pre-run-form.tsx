'use client';

import { useState } from 'react';
import {
  RiAddLine,
  RiCheckLine,
  RiCloseLine,
  RiInformationLine,
  RiPlayLine,
} from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { FormField } from '@/components/ui/form-field';
import { InlineConfirm } from '@/components/ui/inline-confirm';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { patchAgentSettings } from '@/lib/api/agents';
import { errorMessage } from '@/lib/api/client';
import { useDebugMode } from '@/lib/debug-mode';
import { cn } from '@/lib/utils';
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

// 전표유형(SYSDEF_NM) 후보 — 백엔드 set_docu_types 가 이 라벨로 피커를 체크한다.
const ALL_DOCU_TYPES = ['국내매출', '해외매출', '내수구매'] as const;
type DocuType = (typeof ALL_DOCU_TYPES)[number];

// 종전 에이전트와 같은 조합을 한 번에 선택하는 프리셋 — 현재 선택을 통째로 교체한다.
const PRESETS: readonly { label: string; types: readonly DocuType[] }[] = [
  { label: '외상매출금', types: ['국내매출', '해외매출'] },
  { label: '외상매입금', types: ['내수구매'] },
];

/** 메뉴 필터 한 항목 — 에이전트 settings.menu_items 원소(관리자가 공유 관리). */
interface VoucherMenuItem {
  id: string;
  label: string;
  defaultSelected: boolean;
}

// settings 부재/파손 시 폴백 — 백엔드 기본 목록과 동일한 3항목.
const DEFAULT_MENU_ITEMS: readonly VoucherMenuItem[] = [
  { id: 'menu-sales-register', label: '매출등록', defaultSelected: true },
  { id: 'menu-sales-cancel', label: '매출취소', defaultSelected: true },
  { id: 'menu-export-cost', label: '수출비용입력[나인벨]', defaultSelected: false },
];

/** settings.menu_items 를 방어적으로 파싱한다 — 부재·비배열·항목 파손은 폴백/스킵. */
function parseMenuItems(settings: Record<string, unknown> | undefined): VoucherMenuItem[] {
  const raw = settings?.menu_items;
  if (!Array.isArray(raw)) return [...DEFAULT_MENU_ITEMS];
  const items: VoucherMenuItem[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const { id, label, defaultSelected } = entry as Record<string, unknown>;
    if (typeof id !== 'string' || !id || typeof label !== 'string' || !label) continue;
    if (items.some((it) => it.id === id)) continue;
    items.push({ id, label, defaultSelected: defaultSelected === true });
  }
  return items.length > 0 ? items : [...DEFAULT_MENU_ITEMS];
}

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

/** 마지막 제출 params → 전표유형 복원. 없으면 빈 선택(사용자가 직접 고른다). */
function seedDocuTypes(seed: Record<string, unknown>): DocuType[] {
  const raw = seed.docu_types;
  if (!Array.isArray(raw)) return [];
  return ALL_DOCU_TYPES.filter((t) => raw.includes(t));
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

  // 메뉴 필터 — 항목 목록은 관리자 공유 데이터(settings.menu_items), 체크 상태는 이 실행 한정.
  const [menuItems, setMenuItems] = useState<VoucherMenuItem[]>(() =>
    parseMenuItems(agent.settings),
  );
  const [selectedMenuIds, setSelectedMenuIds] = useState<Set<string>>(() =>
    seedMenuIds(seed, parseMenuItems(agent.settings)),
  );
  const [newMenuLabel, setNewMenuLabel] = useState('');
  const [menuSaving, setMenuSaving] = useState(false);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);

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

  /** menu_items 저장(admin 전용 PATCH) → 서버 응답으로 목록 동기화 + 체크 상태 정리. */
  const persistMenuItems = async (nextList: VoucherMenuItem[]) => {
    setMenuSaving(true);
    try {
      const updated = await patchAgentSettings(agent.id, {
        menu_items: nextList.map((it) => ({ ...it })),
      });
      const fromServer = Array.isArray(updated.settings?.menu_items)
        ? parseMenuItems(updated.settings)
        : nextList;
      setMenuItems(fromServer);
      setSelectedMenuIds(
        (prev) => new Set(fromServer.filter((it) => prev.has(it.id)).map((it) => it.id)),
      );
      return true;
    } catch (err) {
      toast.error(errorMessage(err, '메뉴 항목을 저장하지 못했습니다.'));
      return false;
    } finally {
      setMenuSaving(false);
    }
  };

  const addMenuItem = async () => {
    const label = newMenuLabel.trim();
    if (!label || menuSaving) return;
    if (menuItems.some((it) => it.label === label)) {
      toast.error('이미 같은 이름의 메뉴 항목이 있습니다.');
      return;
    }
    const item: VoucherMenuItem = {
      id: `menu-${Date.now().toString(36)}`,
      label,
      defaultSelected: false,
    };
    if (await persistMenuItems([...menuItems, item])) setNewMenuLabel('');
  };

  const deleteMenuItem = async (id: string) => {
    if (menuSaving || menuItems.length <= 1) return;
    if (await persistMenuItems(menuItems.filter((it) => it.id !== id))) {
      setConfirmingDeleteId(null);
    }
  };

  const submit = () => {
    if (!canSubmit) return;
    const selectedTypes = ALL_DOCU_TYPES.filter((t) => docuTypes.includes(t));
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

      <div className="grid gap-5 sm:max-w-md">
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

        <FormField
          id="voucher-docu-types"
          label="전표유형"
          required
          hint="1개 이상 선택하세요. 프리셋은 종전 외상매출금·외상매입금과 같은 조합으로 선택을 교체합니다."
        >
          <div className="grid gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-foreground-tertiary text-xs">프리셋</span>
              {PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  disabled={disabled}
                  onClick={() => setDocuTypes([...preset.types])}
                  className="border-border text-foreground-secondary hover:bg-muted/60 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50 max-md:min-h-11"
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {ALL_DOCU_TYPES.map((t) => {
                const active = docuTypes.includes(t);
                return (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={active}
                    disabled={disabled}
                    onClick={() => toggleDocuType(t)}
                    className={cn(
                      'rounded-[var(--radius-md)] border px-3.5 py-2 text-sm font-medium transition-colors disabled:opacity-50 max-md:min-h-11',
                      active
                        ? 'border-accent bg-accent/10 text-foreground'
                        : 'border-border text-foreground-secondary hover:bg-muted/60',
                    )}
                  >
                    {t}
                  </button>
                );
              })}
            </div>
          </div>
        </FormField>

        <FormField
          id="voucher-menu-filters"
          label="메뉴 필터"
          hint={
            selectedMenuIds.size === 0
              ? '선택 없음 = 필터 없음(전체 메뉴). 체크한 메뉴의 전표만 상신 대상이 됩니다.'
              : '체크한 메뉴의 전표만 상신 대상이 됩니다. 항목 추가·삭제는 모든 사용자에게 공유됩니다(관리자 전용).'
          }
        >
          <div className="grid gap-1.5">
            {menuItems.map((it) => {
              const checked = selectedMenuIds.has(it.id);
              return (
                <div key={it.id} className="flex items-center gap-1.5">
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={checked}
                    disabled={disabled}
                    onClick={() => toggleMenu(it.id)}
                    className={cn(
                      'flex min-w-0 flex-1 items-center gap-2.5 rounded-[var(--radius-md)] border px-3 py-2 text-left transition-colors disabled:opacity-50 max-md:min-h-11',
                      checked
                        ? 'border-accent/50 bg-accent/5'
                        : 'border-border bg-surface hover:border-border-strong hover:bg-muted/40',
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        'flex size-[18px] shrink-0 items-center justify-center rounded-[6px] border transition-colors',
                        checked
                          ? 'border-accent bg-accent text-white'
                          : 'border-border-strong bg-surface',
                      )}
                    >
                      {checked ? <RiCheckLine size={13} /> : null}
                    </span>
                    <span
                      className={cn(
                        'truncate text-[length:var(--text-body-sm)] font-medium',
                        checked ? 'text-foreground' : 'text-foreground-secondary',
                      )}
                    >
                      {it.label}
                    </span>
                  </button>
                  {confirmingDeleteId === it.id ? (
                    <InlineConfirm
                      question="삭제할까요?"
                      confirmLabel="삭제"
                      disabled={menuSaving}
                      onConfirm={() => void deleteMenuItem(it.id)}
                      onCancel={() => setConfirmingDeleteId(null)}
                    />
                  ) : (
                    <button
                      type="button"
                      aria-label={`${it.label} 항목 삭제`}
                      disabled={disabled || menuSaving || menuItems.length <= 1}
                      onClick={() => setConfirmingDeleteId(it.id)}
                      className="text-foreground-tertiary hover:text-danger hover:bg-danger/10 rounded-[var(--radius-sm)] p-1.5 transition-colors disabled:opacity-40 max-md:min-h-11 max-md:min-w-11"
                    >
                      <RiCloseLine size={15} aria-hidden />
                    </button>
                  )}
                </div>
              );
            })}
            <div className="flex items-center gap-2">
              <Input
                value={newMenuLabel}
                disabled={disabled || menuSaving}
                placeholder="추가할 메뉴 이름"
                className="h-8 max-w-56 text-xs max-md:h-11"
                onChange={(e) => setNewMenuLabel(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    void addMenuItem();
                  }
                }}
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="max-md:h-11"
                disabled={disabled || menuSaving || !newMenuLabel.trim()}
                onClick={() => void addMenuItem()}
              >
                <RiAddLine size={15} aria-hidden />
                추가
              </Button>
            </div>
          </div>
        </FormField>
      </div>

      {/* 실행 바 — md 미만은 페이지 스크롤 기준 sticky 하단 바(폼이 길어 실행 버튼 상시 노출). */}
      <div
        className={cn(
          'flex flex-col gap-2 md:flex-row md:items-center md:justify-end md:gap-3',
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
