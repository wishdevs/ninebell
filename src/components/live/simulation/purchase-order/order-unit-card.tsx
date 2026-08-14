'use client';

import { useMemo, useState } from 'react';
import {
  RiArrowDownSLine,
  RiArrowRightSLine,
  RiCloseLine,
  RiDeleteBinLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { StatusPill } from '@/components/ui/status-pill';
import { CatalogCombobox, type ComboOption } from '@/components/live/pre-run/catalog-combobox';
import { formatInteger } from '@/lib/data/format';
import { VENDOR_FAVORITES, searchVendors, vendorSearchPoolOf } from './catalog';
import {
  defaultNoteOf,
  effectiveVendorOf,
  modulesOf,
  moduleLabel,
  unitModuleSummary,
  unitTotals,
  vendorDueOf,
  vendorGroupsOf,
  type OrderUnit,
  type PlanBom,
  type VendorEdit,
  type VendorGroup,
} from './model';
import { PartsTable, Td, Th } from './ui';

interface OrderUnitCardProps {
  /** 주입된 BOM 컨텍스트 — 모듈 조회·거래처 검색 풀의 원천. */
  bom: PlanBom;
  unit: OrderUnit;
  /** 구매사유·납기 등 단순 필드 패치(불변 업데이트는 호출부 소유). */
  onPatch: (patch: Partial<Pick<OrderUnit, 'purchaseReason' | 'dueDate'>>) => void;
  /** 거래처 그룹 오버라이드 패치 — vendorEdits[vendorClass] 에 병합된다. */
  onVendorPatch: (vendorClass: string, patch: VendorEdit) => void;
  /** 모듈을 풀로 복귀 — 마지막 모듈 제거 시 호출부가 카드 자체를 지운다. */
  onRemoveModule: (code: string) => void;
  onRemove: () => void;
}

/**
 * C. 발주단위 카드 — 구매요청 저장 1회(발주번호 1건)에 해당하는 묶음.
 *
 * 인플레이스 1행 폼(구매사유·납기 — 위저드 없음) + 모듈 칩 + 거래처 그룹 테이블.
 * 거래처 그룹은 카드 모듈들의 부품을 vendorClass 로 렌더 시 파생하며, 그룹 편집값
 * (실거래처·납기 오버라이드·비고)만 vendorEdits 에 저장한다(기본값 복제 저장 금지).
 */
export function OrderUnitCard({
  bom,
  unit,
  onPatch,
  onVendorPatch,
  onRemoveModule,
  onRemove,
}: OrderUnitCardProps) {
  const modules = useMemo(() => modulesOf(bom, unit), [bom, unit]);
  const groups = useMemo(() => vendorGroupsOf(modules), [modules]);
  const totals = useMemo(() => unitTotals(bom, unit), [bom, unit]);
  // 실거래처 검색 풀 — 주입된 BOM 에서 파생(자주쓰는 + 등장 실거래처).
  const vendorPool = useMemo(() => vendorSearchPoolOf(bom.modules), [bom]);

  return (
    // ⚠ 카드 경계(사용자 리포트 2026-08-14): 종전엔 얇은 테두리 하나뿐이라 발주1·발주2 가
    // 이어져 보였다. 헤더를 별도 밴드(bg-muted/50 + 하단 구분선)로 띄우고 카드에 그림자를
    // 줘 '한 발주 = 한 덩어리'가 눈에 먼저 들어오게 한다.
    <section className="border-border bg-surface overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-card)]">
      {/* 헤더 밴드 — 발주 N + 모듈 요약 + 합계 + 삭제. */}
      <div className="bg-muted/50 border-border/70 flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <StatusPill label={`발주 ${unit.seq}`} variant="info" />
        <span className="text-foreground text-[length:var(--text-body)] font-semibold">
          {unitModuleSummary(bom, unit)}
        </span>
        <span className="text-foreground-tertiary text-[11px] tabular-nums">
          부품 {totals.parts} · {formatInteger(totals.amount)}원
        </span>
        {/* 삭제는 확인 없이 즉시(사용자 요청 2026-08-14) — 모듈이 풀로 돌아갈 뿐이라
            되돌리기 쉽고, 발주단위를 여러 번 다시 묶는 작업에서 확인 단계가 방해가 된다. */}
        <div className="ml-auto shrink-0">
          <Button size="sm" variant="ghost" aria-label={`발주 ${unit.seq} 삭제`} onClick={onRemove}>
            <RiDeleteBinLine size={14} aria-hidden />
            삭제
          </Button>
        </div>
      </div>

      {/* 본문 — 헤더 밴드와 같은 좌우 여백을 유지한다(밴드가 카드 폭을 꽉 채우므로 여기서 준다). */}
      <div className="flex flex-col gap-3 p-4">
        {/* 인플레이스 1행 폼 — 구매사유·납기예정일(둘 다 필수, 납기는 거래처 그룹 기본값). */}
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid min-w-[220px] flex-1 gap-1.5">
            <Label htmlFor={`${unit.id}-reason`}>
              구매사유 <span className="text-danger">*</span>
            </Label>
            <Input
              id={`${unit.id}-reason`}
              value={unit.purchaseReason}
              onChange={(e) => onPatch({ purchaseReason: e.target.value })}
              placeholder="예: 12CH PROCESS 1차 발주"
              maxLength={200}
              className="h-9 text-[12px]"
            />
          </div>
          <div className="grid w-40 gap-1.5">
            <Label htmlFor={`${unit.id}-due`}>
              납기예정일 <span className="text-danger">*</span>
            </Label>
            <DatePicker
              value={unit.dueDate}
              onChange={(v) => onPatch({ dueDate: v })}
              ariaLabel={`발주 ${unit.seq} 납기예정일`}
              className="h-9 text-[12px]"
            />
          </div>
        </div>

        {/* 모듈 칩 — 제거하면 풀로 복귀. 마지막 모듈 제거 시 호출부가 카드를 지운다. */}
        <ul className="flex flex-wrap gap-1.5">
          {modules.map((m) => (
            <li
              key={m.itemCode}
              className="border-border bg-muted/40 text-foreground-secondary inline-flex items-center gap-0.5 rounded-full border py-0.5 pr-1 pl-2.5 text-[11px]"
            >
              <span>{moduleLabel(m)}</span>
              <button
                type="button"
                aria-label={`${moduleLabel(m)} 을 풀로 되돌리기`}
                onClick={() => onRemoveModule(m.itemCode)}
                className="text-foreground-tertiary hover:text-danger flex size-5 items-center justify-center rounded-full transition-colors"
              >
                <RiCloseLine size={13} aria-hidden />
              </button>
            </li>
          ))}
        </ul>

        {/* 거래처 그룹 — 구매발주일괄입력 단계의 거래처별 편집(실거래처·납기·비고)을 미리 정한다. */}
        <div className="border-border overflow-x-auto rounded-[var(--radius-md)] border">
          <table className="w-full min-w-[880px] border-collapse text-[11px]">
            <thead className="bg-muted/70 text-foreground-tertiary">
              <tr>
                <Th className="w-8" />
                <Th>거래처</Th>
                <Th className="text-right">부품 수</Th>
                <Th className="text-right">금액</Th>
                <Th className="w-36">납기예정일</Th>
                <Th className="w-44">비고</Th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <VendorGroupRow
                  key={g.vendorClass}
                  unit={unit}
                  group={g}
                  defaultNote={defaultNoteOf(unit, g.vendorClass, groups)}
                  vendorPool={vendorPool}
                  onVendorPatch={onVendorPatch}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

interface VendorGroupRowProps {
  unit: OrderUnit;
  group: VendorGroup;
  /** 비고 기본 문구(파생) — 오버라이드가 없을 때 표시되고 페이로드에도 접힌다. */
  defaultNote: string;
  /** 실거래처 검색 풀(BOM 파생) — 의사 거래처 지정 콤보박스 재료. */
  vendorPool: readonly ComboOption[];
  onVendorPatch: (vendorClass: string, patch: VendorEdit) => void;
}

function VendorGroupRow({
  unit,
  group: g,
  defaultNote,
  vendorPool,
  onVendorPatch,
}: VendorGroupRowProps) {
  const [expanded, setExpanded] = useState(false);
  const edit = unit.vendorEdits[g.vendorClass];
  // 유효 거래처 = 오버라이드 ?? 기본값(가공품 → 해룡, 판금품 → 알파테크) — 파생만, 저장 안 함.
  const vendor = g.isPseudo ? effectiveVendorOf(unit, g.vendorClass) : undefined;
  return (
    <>
      <tr className="border-border/50 border-t align-middle">
        {/* [부품 보기] — 그룹에 속한 부품 목록 확장. */}
        <Td className="py-0 text-center">
          <button
            type="button"
            aria-expanded={expanded}
            aria-label={`${g.vendorClass} 부품 목록 ${expanded ? '접기' : '펼치기'}`}
            onClick={() => setExpanded((v) => !v)}
            className="text-foreground-tertiary hover:text-foreground flex size-6 items-center justify-center"
          >
            {expanded ? (
              <RiArrowDownSLine size={15} aria-hidden />
            ) : (
              <RiArrowRightSLine size={15} aria-hidden />
            )}
          </button>
        </Td>
        <Td>
          {g.isPseudo ? (
            // 의사 거래처 — '가공품 → (거래처 지정)'. 지정 전에는 warning 배지로 남은 일을 표시.
            <span className="flex items-center gap-1.5">
              <span className="text-foreground-secondary shrink-0 whitespace-nowrap">
                {g.vendorClass} <span aria-hidden>→</span>
              </span>
              <span className="w-44 min-w-0 shrink-0">
                <CatalogCombobox
                  value={vendor ?? { code: '', name: '' }}
                  placeholder="거래처 지정"
                  favorites={[...VENDOR_FAVORITES]}
                  search={(q) => Promise.resolve(searchVendors(vendorPool, q))}
                  onSelect={(opt) =>
                    onVendorPatch(g.vendorClass, { vendor: { code: opt.code, name: opt.name } })
                  }
                  onClear={() => onVendorPatch(g.vendorClass, { vendor: undefined })}
                />
              </span>
              {!vendor ? <StatusPill label="미지정" variant="warn" /> : null}
            </span>
          ) : (
            <span className="text-foreground-secondary whitespace-nowrap">{g.vendorClass}</span>
          )}
        </Td>
        <Td className="text-foreground-secondary text-right tabular-nums">{g.parts.length}</Td>
        <Td className="text-foreground-secondary text-right whitespace-nowrap tabular-nums">
          {formatInteger(g.amount)}
        </Td>
        <Td>
          {/* 기본값 = vendorDueOf 파생(가공품 = 발주단위 납기, 그 외 = 1주 전 영업일 —
              공휴일 보정). 그룹에서 고르면 오버라이드로만 저장된다. */}
          <DatePicker
            value={edit?.dueDate || vendorDueOf(unit.dueDate, g.vendorClass)}
            onChange={(v) => onVendorPatch(g.vendorClass, { dueDate: v })}
            ariaLabel={`${g.vendorClass} 납기예정일`}
            className="h-9 text-[12px]"
          />
        </Td>
        <Td>
          {/* 기본값 = 가공품 거래처 직배송 문구(가공품 외 그룹) — 수정·삭제하면 오버라이드. */}
          <Input
            value={edit?.note ?? defaultNote}
            onChange={(e) => onVendorPatch(g.vendorClass, { note: e.target.value })}
            aria-label={`${g.vendorClass} 비고`}
            placeholder="예: 직배송"
            maxLength={200}
            className="h-9 text-[12px]"
          />
        </Td>
      </tr>
      {expanded ? (
        <tr className="border-border/50 border-t">
          <td colSpan={6} className="p-0">
            <PartsTable parts={g.parts} />
          </td>
        </tr>
      ) : null}
    </>
  );
}
