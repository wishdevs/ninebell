'use client';

import { useCallback, useEffect, useState } from 'react';
import { RiDeleteBinLine, RiLoader4Line, RiPlayMiniLine, RiRefreshLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyNote } from '@/components/ui/empty-note';
import { ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/lib/data/format';
import { deleteTemplate, fetchTemplates, type RunTemplate } from '@/lib/live/runs-api';
import { cn } from '@/lib/utils';

export interface RunsPanelProps {
  /** 워크플로우(agentId) — 템플릿을 이 키로 조회한다. */
  agentId: string;
  /** 증가하면 템플릿을 다시 불러온다(템플릿 저장·삭제 시 상위가 올린다). */
  refreshKey: number;
  /** 템플릿 재생(회수) 시작 — 상위가 templateId 로 새 라이브 런을 띄운다. */
  onReplay: (templateId: string) => void;
  /** 진행 중 라이브 런이 있어 새 재생을 시작할 수 없을 때 true. */
  replayDisabled: boolean;
}

/**
 * 템플릿 탭 — 저장된 재생 묶음을 나열하고 재생/회수·삭제를 제공한다. 우측 사이드 패널의 한 탭.
 * (실행 이력은 top-level 로깅 페이지(/logs)와 중복이라 상세에서는 노출하지 않는다.)
 */
export function TemplatesTab({ agentId, refreshKey, onReplay, replayDisabled }: RunsPanelProps) {
  const [templates, setTemplates] = useState<RunTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setError(null);
    try {
      setTemplates(await fetchTemplates(agentId));
    } catch (err) {
      setError(messageOf(err));
      setTemplates([]);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  return (
    <div className="flex flex-col gap-2">
      <TabToolbar
        label={templates ? `템플릿 ${templates.length}개` : '템플릿'}
        onRefresh={() => void load()}
      />
      <TemplateList
        templates={templates}
        error={error}
        replayDisabled={replayDisabled}
        onReplay={onReplay}
        onDeleted={load}
      />
    </div>
  );
}

function TabToolbar({ label, onRefresh }: { label: string; onRefresh: () => void }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-foreground-tertiary text-[11px] font-medium">{label}</span>
      <Button size="sm" variant="ghost" aria-label="새로고침" onClick={onRefresh}>
        <RiRefreshLine size={14} aria-hidden />
      </Button>
    </div>
  );
}

// ── 템플릿 ───────────────────────────────────────────────────────────

interface TemplateListProps {
  templates: RunTemplate[] | null;
  error: string | null;
  replayDisabled: boolean;
  onReplay: (templateId: string) => void;
  onDeleted: () => Promise<void> | void;
}

function TemplateList({
  templates,
  error,
  replayDisabled,
  onReplay,
  onDeleted,
}: TemplateListProps) {
  if (error) return <Notice tone="danger">{error}</Notice>;
  if (templates === null) return <Notice>템플릿을 불러오는 중…</Notice>;
  if (templates.length === 0) {
    return (
      <EmptyNote>
        저장된 템플릿이 없습니다. 대화형 실행을 완료한 뒤 결과에서 &lsquo;템플릿으로 저장&rsquo;할
        수 있습니다.
      </EmptyNote>
    );
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {templates.map((t) => (
        <TemplateRow
          key={t.id}
          template={t}
          replayDisabled={replayDisabled}
          onReplay={onReplay}
          onDeleted={onDeleted}
        />
      ))}
    </ul>
  );
}

function TemplateRow({
  template,
  replayDisabled,
  onReplay,
  onDeleted,
}: {
  template: RunTemplate;
  replayDisabled: boolean;
  onReplay: (templateId: string) => void;
  onDeleted: () => Promise<void> | void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove(): Promise<void> {
    if (deleting) return;
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`'${template.name}' 템플릿을 삭제할까요?`)
    ) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await deleteTemplate(template.id);
      await onDeleted();
    } catch (err) {
      setError(messageOf(err));
      setDeleting(false);
    }
  }

  return (
    <li className="border-border flex items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2.5">
      <span className="min-w-0 flex-1">
        <span className="text-foreground block truncate text-[length:var(--text-body-sm)] font-medium">
          {template.name}
        </span>
        <span className="text-foreground-tertiary block text-[11px] tabular-nums">
          {formatDateTime(template.createdAt)}
        </span>
        {error ? <span className="text-danger mt-0.5 block text-[11px]">{error}</span> : null}
      </span>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button
          size="sm"
          onClick={() => onReplay(template.id)}
          disabled={replayDisabled || deleting}
          title={replayDisabled ? '진행 중인 실행을 종료한 뒤 재생할 수 있습니다.' : undefined}
        >
          <RiPlayMiniLine size={14} aria-hidden />
          재생
        </Button>
        <Button
          size="sm"
          variant="ghost"
          aria-label="템플릿 삭제"
          onClick={() => void remove()}
          disabled={deleting}
          className="text-danger hover:bg-danger/10 hover:text-danger"
        >
          {deleting ? (
            <RiLoader4Line size={14} className="animate-spin" aria-hidden />
          ) : (
            <RiDeleteBinLine size={14} aria-hidden />
          )}
        </Button>
      </div>
    </li>
  );
}

// ── 공통 ─────────────────────────────────────────────────────────────

function Notice({
  children,
  tone = 'muted',
}: {
  children: React.ReactNode;
  tone?: 'muted' | 'danger';
}) {
  return (
    <p
      className={cn(
        'py-6 text-center text-[12px]',
        tone === 'danger' ? 'text-danger' : 'text-foreground-tertiary',
      )}
    >
      {children}
    </p>
  );
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return '세션이 만료되었습니다. 다시 로그인해 주세요.';
    return err.message;
  }
  return '요청을 처리하지 못했습니다.';
}
