'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { RiArrowLeftSLine, RiCheckLine, RiErrorWarningLine, RiPencilLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { LockedEmptyState } from '@/components/ui/list-state';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { useUnsavedGuard } from '@/app/(app)/_lib/use-unsaved-guard';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, api, errorMessage } from '@/lib/api/client';
import {
  buildOrgUnitForest,
  descendantOwnMemberIds,
  hasOwnMembers,
  ownMemberUnits,
  type AgentAccess,
  type OrgUnit,
  type OrgUnitNode,
} from '@/lib/data/org-units';
import { cn } from '@/lib/utils';

/** '미지정'(조직 미배정 사용자 허용) wire 센티널 — 백엔드 ORG_NONE_SENTINEL·멤버 화면과 동일. */
const ORG_NONE = '__none__';

/**
 * 에이전트 접근 관리 — /manage/agents/access. 에이전트별로 실행을 허용할 조직(팀)을 체크박스로
 * 지정한다. 백엔드 `/agent-access`(+ 조직 트리는 `/org-units`). 원래 조직구분 관리 화면의 탭이었으나
 * 에이전트 설정과 같은 화면군으로 옮기고, 조직구분 탭(OrgUnitsTab)과 동일한 스테이징+저장 모델로
 * 재설계했다(자동저장 없음 — 두 화면의 편집 UX를 통일). 최초 설정(access_configured=false)은
 * 백엔드가 전체 반환한다.
 */
export function AgentAccessClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const orgs = useApiResource<OrgUnit[]>('/org-units');
  const access = useApiResource<AgentAccess[]>('/agent-access');

  const reloadAll = () => {
    orgs.reload();
    access.reload();
  };

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Link
          href="/manage/agents"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          <RiArrowLeftSLine size={15} aria-hidden />
          에이전트 관리
        </Link>
        <PageHeader
          caption="운영"
          title="에이전트 접근"
          description="에이전트별로 실행을 허용할 조직(팀)을 지정합니다. 저장해야 반영됩니다."
        />
      </div>

      {!isAdmin ? (
        <LockedEmptyState description="에이전트 접근 관리는 관리자 이상만 사용할 수 있습니다." />
      ) : orgs.status !== 'success' || access.status !== 'success' ? (
        <LoadState error={access.error ?? orgs.error} onReload={reloadAll} />
      ) : (
        <AgentAccessBody
          orgUnits={orgs.data ?? []}
          accessData={access.data ?? []}
          onReload={access.reload}
        />
      )}
    </div>
  );
}

// ── 로딩/에러 공통 ───────────────────────────────────────────────────────────
function LoadState({ error, onReload }: { error: ApiError | null; onReload: () => void }) {
  if (error) {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title="불러오지 못했습니다"
        description={errorMessage(error)}
        action={
          <Button variant="secondary" size="sm" onClick={onReload}>
            다시 시도
          </Button>
        }
      />
    );
  }
  return (
    <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
      <Spinner size={18} label="불러오는 중" />
      불러오는 중…
    </div>
  );
}

/** 두 조직 id 집합(순서 무관)이 같은지. 스테이징 시 서버값과 같아지면 초안에서 제거하는 데 쓴다. */
function sameSet(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((id) => set.has(id));
}

// ── 본문 — 조직·접근 데이터가 모두 로드된 뒤에만 렌더 ─────────────────────────────
interface AgentAccessBodyProps {
  orgUnits: OrgUnit[];
  accessData: AgentAccess[];
  onReload: () => void;
}

function AgentAccessBody({ orgUnits, accessData, onReload }: AgentAccessBodyProps) {
  const serverSel = useMemo<Record<string, string[]>>(
    () => Object.fromEntries(accessData.map((a) => [a.agentId, a.orgUnitIds])),
    [accessData],
  );
  // 접근 초안(agentId→변경 선택). 서버값과 다른 에이전트만 담는다(즉시저장 아님 — 저장 버튼으로 일괄).
  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [saving, setSaving] = useState(false);
  // 편집 팝업 대상(에이전트 id) — 목록은 요약 행만, 상세 조직 선택은 다이얼로그에서.
  const [editingId, setEditingId] = useState<string | null>(null);
  useEffect(() => {
    setDraft({}); // 새 목록(서버 갱신·저장 후 재조회) 도착 시 초안 리셋.
  }, [accessData]);

  const dirtyIds = Object.keys(draft);
  const dirty = dirtyIds.length > 0;
  useUnsavedGuard(dirty); // 변경 있으면 새로고침·앱내 이동 시 이탈 확인.

  // 직접 소속원을 가진 노드만 접근 대상 — 말단 팀 + 직속 인원이 있는 중간 그룹. 순수 컨테이너는 제외.
  const forest = buildOrgUnitForest(orgUnits);
  const assignableUnits = ownMemberUnits(forest);

  // 체크 옵션 = 배정 대상 노드 전체 + '미지정'(조직 미배정 사용자 허용, 항상 마지막).
  const options: { id: string; label: string }[] = [
    ...assignableUnits.map((unit) => ({ id: unit.id, label: unit.label })),
    { id: ORG_NONE, label: '미지정' },
  ];
  const teamOptions = options.filter((o) => o.id !== ORG_NONE);

  if (accessData.length === 0) {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title="에이전트가 없습니다"
        description="접근을 관리할 실 에이전트가 없습니다."
      />
    );
  }

  const effective = (agentId: string): string[] => draft[agentId] ?? serverSel[agentId] ?? [];

  // 스테이징 — 서버값과 같아지면 초안에서 제거(변경 없음 처리).
  const stage = (agentId: string, nextIds: string[]) => {
    setDraft((prev) => {
      const server = serverSel[agentId] ?? [];
      const next = { ...prev };
      if (sameSet(server, nextIds)) delete next[agentId];
      else next[agentId] = nextIds;
      return next;
    });
  };

  // 옵션 순서로 정규화(로컬 집합에 옵션 외 값이 섞여도 견고).
  const canonical = (ids: Iterable<string>): string[] => {
    const set = new Set(ids);
    return options.filter((o) => set.has(o.id)).map((o) => o.id);
  };

  const toggle = (agentId: string, orgId: string) => {
    const s = new Set(effective(agentId));
    if (s.has(orgId)) s.delete(orgId);
    else s.add(orgId);
    stage(agentId, canonical(s));
  };

  // 그룹 헤더 '전체' 토글 — 그 노드 하위(자기 포함) 배정 대상 전부 선택/해제(on=true 선택).
  const toggleParent = (agentId: string, unitIds: string[], on: boolean) => {
    const s = new Set(effective(agentId));
    for (const id of unitIds) {
      if (on) s.add(id);
      else s.delete(id);
    }
    stage(agentId, canonical(s));
  };

  // 요약 문구/톤 — 목록 행에 접근 상태를 한 줄로. 전체=모든 조직, 0=접근 없음, 그 외 팀 수(+미지정).
  const summarize = (sel: Set<string>): { text: string; tone: 'all' | 'some' | 'none' } => {
    const teamCount = teamOptions.filter((o) => sel.has(o.id)).length;
    const hasNone = sel.has(ORG_NONE);
    if (teamCount === teamOptions.length && hasNone) return { text: '모든 조직 허용', tone: 'all' };
    if (teamCount === 0 && !hasNone) return { text: '접근 조직 없음', tone: 'none' };
    const parts: string[] = [];
    if (teamCount > 0) parts.push(`${teamCount}개 팀`);
    if (hasNone) parts.push('미지정 포함');
    return { text: parts.join(' · '), tone: 'some' };
  };

  const save = async () => {
    setSaving(true);
    try {
      await Promise.all(
        dirtyIds.map((id) => api.patch(`/agent-access/${id}`, { orgUnitIds: draft[id] })),
      );
      toast.success(`에이전트 접근 ${dirtyIds.length}건 저장했습니다`);
      setDraft({});
      onReload();
    } catch (err) {
      toast.error(errorMessage(err, '저장하지 못했습니다.'));
    } finally {
      setSaving(false);
    }
  };

  const editing = accessData.find((a) => a.agentId === editingId) ?? null;
  const editingSel = editing ? new Set(effective(editing.agentId)) : new Set<string>();
  // 모두 선택 여부는 옵션 멤버십으로 판정(선택 집합에 옵션 외 값이 섞여도 견고).
  const allSelected = options.every((o) => editingSel.has(o.id));

  return (
    <div className="flex flex-col gap-4">
      {/* 상단 툴바 — 안내·저장 컨트롤을 한 줄에(조직구분 탭과 동일 레이아웃). 저장/되돌리기는
          항상 렌더하되 변경 없음·저장 중엔 비활성. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-muted-foreground min-w-0 flex-1 text-[length:var(--text-body-sm)]">
          각 행의 <b>편집</b>에서 조직을 선택한 뒤 저장하세요. 지정하지 않으면 모든 조직이 실행할 수
          있습니다.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {dirty ? (
            <span className="text-foreground-secondary text-xs whitespace-nowrap">
              <b className="text-foreground tabular-nums">{dirtyIds.length}개</b> 에이전트 변경
            </span>
          ) : null}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setDraft({})}
            disabled={!dirty || saving}
          >
            되돌리기
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={!dirty || saving}>
            {saving ? (
              <>
                <Spinner size={14} /> 저장 중…
              </>
            ) : (
              '저장'
            )}
          </Button>
        </div>
      </div>

      {/* 요약 행 목록 — 에이전트당 한 줄(이름 + 접근 요약 + 편집). */}
      <div className="border-border bg-surface divide-border-subtle flex flex-col divide-y rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
        {accessData.map((agent) => {
          const s = summarize(new Set(effective(agent.agentId)));
          const staged = agent.agentId in draft;
          return (
            <div key={agent.agentId} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-foreground truncate font-medium">{agent.agentName}</p>
                  {staged ? (
                    <span className="text-accent inline-flex shrink-0 items-center gap-1 text-[10px] font-semibold">
                      <span className="bg-accent size-1.5 rounded-full" aria-hidden />
                      변경됨
                    </span>
                  ) : null}
                </div>
                <p
                  className={cn(
                    'mt-0.5 text-xs',
                    s.tone === 'all'
                      ? 'text-success'
                      : s.tone === 'none'
                        ? 'text-danger'
                        : 'text-foreground-secondary',
                  )}
                >
                  {s.text}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                className="shrink-0"
                onClick={() => setEditingId(agent.agentId)}
              >
                <RiPencilLine size={14} aria-hidden />
                편집
              </Button>
            </div>
          );
        })}
      </div>

      {/* 편집 팝업 — 조직 트리(상위 노드 전체 토글) + 미지정. 변경은 초안에만 담기고 저장 버튼을
          눌러야 반영된다. */}
      {editing ? (
        <Dialog
          open
          onClose={() => setEditingId(null)}
          title={`${editing.agentName} — 접근 조직`}
          description="이 에이전트를 실행할 수 있는 조직(팀)을 선택하세요. 저장 버튼을 눌러야 반영됩니다."
          size="lg"
          footer={
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => stage(editing.agentId, allSelected ? [] : options.map((o) => o.id))}
                className="border-border text-foreground-secondary hover:bg-muted hover:text-foreground rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors"
              >
                {allSelected ? '모두 해제' : '모두 선택'}
              </button>
              <Button onClick={() => setEditingId(null)}>닫기</Button>
            </div>
          }
        >
          <DialogBody>
            <AgentAccessEditor
              forest={forest}
              selected={editingSel}
              noneChecked={editingSel.has(ORG_NONE)}
              onToggle={(id) => toggle(editing.agentId, id)}
              onToggleParent={(unitIds, on) => toggleParent(editing.agentId, unitIds, on)}
            />
          </DialogBody>
        </Dialog>
      ) : null}
    </div>
  );
}

// ── 편집 팝업 내용 — 조직 트리(상위 노드 전체 토글) + 팀 체크박스 + 미지정 ──────────
function AgentAccessEditor({
  forest,
  selected,
  noneChecked,
  onToggle,
  onToggleParent,
}: {
  forest: OrgUnitNode[];
  selected: Set<string>;
  noneChecked: boolean;
  onToggle: (orgId: string) => void;
  onToggleParent: (unitIds: string[], on: boolean) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {forest.map((node) => (
        <AgentAccessNode
          key={node.unit.id}
          node={node}
          selected={selected}
          onToggle={onToggle}
          onToggleParent={onToggleParent}
        />
      ))}

      <div className="mt-1">
        <OrgAccessCheckbox
          label="미지정 (조직 미배정 사용자 허용)"
          checked={noneChecked}
          onClick={() => onToggle(ORG_NONE)}
        />
      </div>
    </div>
  );
}

/**
 * 접근 편집 트리 노드(재귀).
 * - 자식이 없는 노드: 직접 소속원이 있으면 단일 체크박스, 없으면(0명 말단) 렌더하지 않는다.
 * - 자식이 있는 노드: 하위(자기 포함) 배정 대상 전체 토글(tri-state) 헤더 + 중첩 자식.
 *   직접 소속원을 가진 그룹은 자기 id도 헤더 토글/집계에 포함되어, 헤더 선택 시 그룹 자체도 선택된다.
 *   배정 대상이 하나도 없는 가지는 렌더하지 않는다.
 */
function AgentAccessNode({
  node,
  selected,
  onToggle,
  onToggleParent,
}: {
  node: OrgUnitNode;
  selected: Set<string>;
  onToggle: (orgId: string) => void;
  onToggleParent: (unitIds: string[], on: boolean) => void;
}) {
  const hasChildren = node.children.length > 0;

  if (!hasChildren) {
    if (!hasOwnMembers(node)) return null; // 직속 인원 0인 말단은 배정 대상 아님.
    return (
      <OrgAccessCheckbox
        label={node.unit.label}
        checked={selected.has(node.unit.id)}
        onClick={() => onToggle(node.unit.id)}
      />
    );
  }

  // 자식이 있는 노드 = 그룹 헤더. unitIds 는 하위(자기 포함) 배정 대상 전부 — 직접 소속원 그룹은 자기 id도 포함.
  const unitIds = descendantOwnMemberIds(node);
  if (unitIds.length === 0) return null; // 배정 대상이 없는 컨테이너는 숨김.
  const selCount = unitIds.filter((id) => selected.has(id)).length;
  const allOn = selCount === unitIds.length;

  return (
    <div className="border-border/60 overflow-hidden rounded-[var(--radius-md)] border">
      <div className="bg-muted/30 flex items-center gap-1.5 px-2 py-1.5">
        <button
          type="button"
          role="checkbox"
          aria-checked={allOn ? true : selCount > 0 ? 'mixed' : false}
          onClick={() => onToggleParent(unitIds, !allOn)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span
            aria-hidden
            className={cn(
              'flex size-[18px] shrink-0 items-center justify-center rounded-[6px] border transition-colors',
              allOn
                ? 'border-accent bg-accent text-white'
                : selCount > 0
                  ? 'border-accent bg-accent/20 text-accent'
                  : 'border-border-strong bg-surface',
            )}
          >
            {allOn ? <RiCheckLine size={13} /> : selCount > 0 ? '–' : null}
          </span>
          <span className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
            {node.unit.label}
          </span>
        </button>
        <span className="text-foreground-tertiary shrink-0 text-xs tabular-nums">
          {selCount}/{unitIds.length}
        </span>
      </div>
      <div className="flex flex-col gap-1.5 p-2 pl-3">
        {node.children.map((child) => (
          <AgentAccessNode
            key={child.unit.id}
            node={child}
            selected={selected}
            onToggle={onToggle}
            onToggleParent={onToggleParent}
          />
        ))}
      </div>
    </div>
  );
}

function OrgAccessCheckbox({
  label,
  checked,
  onClick,
}: {
  label: string;
  checked: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onClick}
      className={cn(
        'group flex items-center gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5 text-left transition-colors',
        'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none',
        checked
          ? 'border-accent/50 bg-accent/5'
          : 'border-border bg-surface hover:border-border-strong hover:bg-muted/40',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'flex size-[18px] shrink-0 items-center justify-center rounded-[6px] border transition-colors',
          checked ? 'border-accent bg-accent text-white' : 'border-border-strong bg-surface',
        )}
      >
        {checked ? <RiCheckLine size={13} /> : null}
      </span>
      <span
        className={cn(
          'text-[length:var(--text-body-sm)] font-medium',
          checked ? 'text-foreground' : 'text-foreground-secondary',
        )}
      >
        {label}
      </span>
    </button>
  );
}
