import { StatusPill } from '@/components/ui/status-pill';
import { formatInteger } from '@/lib/data/format';
import type { PlanSubmit } from '@/lib/live/types';
import { Td, Th } from './ui';

/**
 * 계획서 발주단위 읽기 전용 렌더 — 최종검토(PlanReviewView)와 이전 계획서 다이얼로그가
 * 공유한다. 페이로드(PlanSubmit) 그대로 그리므로 '보이는 것 = 저장된 것'이 유지된다.
 */
export function PlanUnitsView({ payload }: { payload: PlanSubmit }) {
  return (
    <>
      {payload.units.map((u) => (
        <section
          key={u.seq}
          className="border-accent/40 rounded-r-[var(--radius-md)] border-l-2 pb-3"
        >
          {/* 발주단위 카드와 같은 문법(2026-08-26) — accent 밴드+레일이 발주 경계다. */}
          <div className="bg-accent/10 flex flex-wrap items-center gap-2 rounded-r-[var(--radius-md)] px-4 py-2.5">
            <StatusPill label={`발주 ${u.seq}`} variant="info" />
            <span className="text-foreground text-[length:var(--text-body)] font-semibold">
              {u.purchaseReason}
            </span>
            <span className="text-foreground-tertiary text-[11px] tabular-nums">
              납기예정일 {u.dueDate}
            </span>
          </div>
          <div className="flex flex-col gap-3 px-4 pt-3">
            <ul className="flex flex-wrap gap-1.5">
              {u.modules.map((m) => (
                <li
                  key={m.itemCode}
                  className="border-border bg-muted/40 text-foreground-secondary inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px]"
                >
                  {m.name}
                  {m.spec ? (
                    <span className="text-foreground-tertiary">&nbsp;· {m.spec}</span>
                  ) : null}
                </li>
              ))}
            </ul>
            <div className="border-border overflow-x-auto rounded-[var(--radius-md)] border">
              <table className="w-full min-w-[640px] border-collapse text-[11px]">
                {/* accent 밴드 아래 내부 표 — 밴드보다 한 단 옅게(order-unit-card 와 동일). */}
                <thead className="bg-muted/50 text-foreground-tertiary">
                  <tr>
                    <Th>거래처</Th>
                    <Th className="text-right">부품 수</Th>
                    <Th className="text-right">금액</Th>
                    <Th className="w-28">납기예정일</Th>
                    <Th>비고</Th>
                  </tr>
                </thead>
                <tbody>
                  {u.vendorGroups.map((g) => (
                    <tr key={g.vendorClass} className="border-border/50 border-t align-middle">
                      <Td>
                        {g.vendor && g.vendor !== g.vendorClass ? (
                          <span className="text-foreground-secondary whitespace-nowrap">
                            {g.vendorClass} <span aria-hidden>→</span>{' '}
                            <b className="text-foreground">{g.vendor}</b>
                          </span>
                        ) : (
                          <span className="text-foreground-secondary whitespace-nowrap">
                            {g.vendor ?? g.vendorClass}
                          </span>
                        )}
                      </Td>
                      <Td className="text-foreground-secondary text-right tabular-nums">
                        {g.parts}
                      </Td>
                      <Td className="text-foreground-secondary text-right whitespace-nowrap tabular-nums">
                        {formatInteger(g.amount)}
                      </Td>
                      <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
                        {g.dueDate}
                      </Td>
                      <Td className="text-foreground-secondary">{g.note || '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ))}
    </>
  );
}
