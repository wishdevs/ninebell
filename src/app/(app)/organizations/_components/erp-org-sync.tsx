'use client';

import { useState } from 'react';
import { RiDownloadCloud2Line } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { MetaChip } from '@/components/ui/meta-chip';
import { Spinner } from '@/components/ui/spinner';
import {
  fetchCatalog,
  fetchSyncStatus,
  startCatalogSync,
  type SyncStatus,
} from '@/lib/api/me-codes';
import { errorMessage } from '@/lib/api/client';

/** 조직 카탈로그 행의 extra(백엔드 org_sync 저장). */
interface OrgExtra {
  type?: 'hq' | 'team';
  hq?: string | null;
  memberCount?: number | null;
  sortOrder?: number;
}

interface HqGroup {
  hq: string;
  memberCount: number | null;
  teams: { name: string; memberCount: number | null }[];
}

const POLL_MS = 1500;
const POLL_MAX = 60; // ~90s (헤드리스 로그인+스크레이프 여유)

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/** 조직 카탈로그(flat 행) → 본부▸팀 그룹. sortOrder 로 정렬. */
async function loadErpOrg(): Promise<HqGroup[]> {
  const page = await fetchCatalog({ kind: 'org_unit', dept: 'all', limit: 300 });
  const rows = page.items.map((i) => ({
    name: i.name,
    extra: (i.extra ?? {}) as unknown as OrgExtra,
  }));
  const hqs = rows
    .filter((r) => r.extra.type === 'hq')
    .sort((a, b) => (a.extra.sortOrder ?? 0) - (b.extra.sortOrder ?? 0));
  const teams = rows
    .filter((r) => r.extra.type === 'team')
    .sort((a, b) => (a.extra.sortOrder ?? 0) - (b.extra.sortOrder ?? 0));
  return hqs.map((h) => ({
    hq: h.name,
    memberCount: h.extra.memberCount ?? null,
    teams: teams
      .filter((t) => t.extra.hq === h.name)
      .map((t) => ({ name: t.name, memberCount: t.extra.memberCount ?? null })),
  }));
}

/** 반영 요약(status.applied·reassigned) → "추가 N · 갱신 M · ERP 미포함 K · 사용자 재배치 J명". */
function summarize(status: SyncStatus): string {
  const a = status.applied;
  const added = a?.added?.length ?? 0;
  const updated = a?.updated?.length ?? 0;
  const localOnly = a?.local_only?.length ?? 0;
  const reassigned = status.reassigned?.length ?? 0;
  return `조직구분 반영: 추가 ${added} · 갱신 ${updated} · ERP 미포함 ${localOnly} · 사용자 재배치 ${reassigned}명`;
}

interface ErpOrgSyncProps {
  /** 조직도 반영 성공 후 상위 목록(조직구분 탭)을 재조회하도록 호출한다. */
  onApplied?: () => void;
}

/**
 * ERP 조직도 불러오기 — 옴니솔 우상단 조직도를 헤드리스로 스크레이프해 본부▸팀으로 가져와
 * org_units(조직구분)에 멱등 반영하고 department 기준 사용자를 재배치한다. 결과 요약을 토스트·
 * 팝업으로 보여주고, 반영된 실제 조직을 미리보기(팝업)한다.
 */
export function ErpOrgSync({ onApplied }: ErpOrgSyncProps) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<HqGroup[] | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    try {
      await startCatalogSync('org_unit'); // 409/자격증명·로컬admin 400 오류는 catch 로.
      let final: SyncStatus | null = null;
      for (let i = 0; i < POLL_MAX; i += 1) {
        await sleep(POLL_MS);
        const st = await fetchSyncStatus('org_unit');
        if (!st.running) {
          if (st.error) throw new Error(st.error);
          final = st;
          break;
        }
      }
      if (!final) throw new Error('시간 초과 — 잠시 후 다시 시도하세요.');
      const line = summarize(final);
      setSummary(line);
      setGroups(await loadErpOrg());
      setOpen(true);
      toast.success('ERP 조직도를 조직구분에 반영했습니다.', { description: line });
      onApplied?.(); // 조직구분 목록 재조회(반영분 즉시 반영).
    } catch (err) {
      toast.error(errorMessage(err, 'ERP 조직도를 불러오지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  }

  const teamTotal = groups?.reduce((n, g) => n + g.teams.length, 0) ?? 0;

  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => void run()} disabled={busy}>
        {busy ? <Spinner size={14} /> : <RiDownloadCloud2Line size={14} aria-hidden />}
        {busy ? '불러오는 중…' : 'ERP 조직도 불러오기'}
      </Button>

      {open && groups ? (
        <Dialog
          open
          onClose={() => setOpen(false)}
          title="ERP 조직도 (옴니솔)"
          description={`옴니솔 조직도에서 가져온 실제 조직입니다 — 본부 ${groups.length} · 팀 ${teamTotal}. 우리 조직구분과 대조해 정렬하세요.`}
          size="lg"
          footer={
            <div className="flex justify-end">
              <Button onClick={() => setOpen(false)}>닫기</Button>
            </div>
          }
        >
          <DialogBody>
            {summary ? (
              <div className="border-border/60 bg-surface text-foreground-secondary mb-3 rounded-[var(--radius-md)] border px-3 py-2 text-xs">
                {summary}
              </div>
            ) : null}
            <div className="flex flex-col gap-3">
              {groups.map((g) => (
                <div key={g.hq} className="border-border/60 rounded-[var(--radius-md)] border p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-foreground font-semibold">{g.hq}</span>
                    {g.memberCount != null ? (
                      <MetaChip className="tabular-nums">{g.memberCount}명</MetaChip>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {g.teams.map((t) => (
                      <span
                        key={t.name}
                        className="border-border bg-surface text-foreground-secondary inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-2 py-1 text-xs"
                      >
                        {t.name}
                        {t.memberCount != null ? (
                          <span className="text-foreground-tertiary tabular-nums">
                            {t.memberCount}
                          </span>
                        ) : null}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </DialogBody>
        </Dialog>
      ) : null}
    </>
  );
}
