'use client';

import { DatePicker } from '@/components/ui/date-picker';
import { Label } from '@/components/ui/label';
import { CatalogCombobox } from '@/components/live/pre-run/catalog-combobox';
import { BASE_DATE_KEYS, type BaseDateKey, type BaseDates } from '@/lib/purchase/order-patterns';
import { searchVendors, type VendorCategory } from './catalog';
import type { UnifiedVendors } from './model';
import { SimSectionHeader } from './ui';

interface PlanUnifiedPanelProps {
  baseDates: BaseDates;
  onBaseDateChange: (key: BaseDateKey, date: string) => void;
  unifiedVendors: UnifiedVendors;
  onUnifiedVendorChange: (
    vendorClass: string,
    vendor: { code: string; name: string } | undefined,
  ) => void;
  /** 분류별 거래처 후보(agents.settings.vendor_options 파생) — 관리 > 통합 지정 거래처에서 편집. */
  vendorCategories: readonly VendorCategory[];
}

/**
 * 통합 지정 — 납기 기준일 3종과 거래처 3분류를 계획서 상단에서 한 번에 정한다.
 *
 * 기준일은 패턴으로 편성된 발주단위의 납기를 **최초 세팅**하는 값이다(패턴의 납기 규칙을
 * 해석해 채운다). 발주단위 카드에서 납기를 직접 고치면 그 단위는 여기서 다시 바꿔도
 * 덮이지 않는다. 거래처도 같은 결 — 여기서 정한 값이 기본값이고, 발주단위·거래처그룹의
 * 개별 지정이 우선한다.
 */
export function PlanUnifiedPanel({
  baseDates,
  onBaseDateChange,
  unifiedVendors,
  onUnifiedVendorChange,
  vendorCategories,
}: PlanUnifiedPanelProps) {
  return (
    <section className="flex flex-col gap-3">
      <SimSectionHeader
        step={1}
        title="통합 지정 — 납기 기준일·거래처"
        prompt="여기서 한 번 정하면 아래 발주단위에 기본값으로 깔립니다. 발주단위에서 직접 고친 값은 여기를 다시 바꿔도 유지됩니다."
      />

      <div className="border-border bg-muted/20 flex flex-col gap-3 rounded-[var(--radius-md)] border p-4">
        {/* 필드 규격 통일(사용자 지적 2026-08-26) — 날짜·거래처 둘 다 w-52 + 기본 높이(h-10). */}
        <FieldGroup
          title="납기 기준일"
          caption="패턴 발주단위의 납기예정일을 이 날짜로 세팅합니다('FRAME 납품 1주 전' 같은 규칙은 영업일로 환산)."
        >
          {BASE_DATE_KEYS.map((key) => (
            <div key={key} className="grid w-52 gap-1.5">
              <Label>{key}</Label>
              <DatePicker
                value={baseDates[key] ?? ''}
                onChange={(v) => onBaseDateChange(key, v)}
                ariaLabel={`${key} 납기 기준일`}
              />
            </div>
          ))}
        </FieldGroup>

        <FieldGroup
          title="거래처"
          caption="분류별 기본 거래처입니다. 후보 목록은 관리 > 통합 지정 거래처에서 추가/삭제합니다."
        >
          {vendorCategories.map((category) => (
            <div key={category.vendorClass} className="grid w-52 gap-1.5">
              <Label>{category.vendorClass}</Label>
              <CatalogCombobox
                value={unifiedVendors[category.vendorClass] ?? { code: '', name: '' }}
                placeholder="거래처 지정"
                favorites={[...category.options]}
                search={(q) => Promise.resolve(searchVendors(category.options, q))}
                onSelect={(opt) =>
                  onUnifiedVendorChange(category.vendorClass, { code: opt.code, name: opt.name })
                }
                onClear={() => onUnifiedVendorChange(category.vendorClass, undefined)}
              />
            </div>
          ))}
        </FieldGroup>
      </div>
    </section>
  );
}

/** 통합 지정 한 묶음 — 소제목 + 캡션 + 인플레이스 필드 행. */
function FieldGroup({
  title,
  caption,
  children,
}: {
  title: string;
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
          {title}
        </span>
        <span className="text-foreground-tertiary text-[11px]">{caption}</span>
      </div>
      <div className="flex flex-wrap items-end gap-3">{children}</div>
    </div>
  );
}
