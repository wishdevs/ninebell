'use client';

import { useState } from 'react';
import { RiBookmarkLine, RiCheckLine, RiCloseLine, RiLoader4Line } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import {
  extractSelections,
  fetchRunDetail,
  saveTemplate,
  type ChatSelection,
} from '@/lib/live/runs-api';

interface SaveTemplateButtonProps {
  /** 방금 완료된 대화형 런의 id — 여기서 selections 를 읽어 온다. */
  runId: string;
  /** 저장할 워크플로우(agentId) — 재생 시 같은 워크플로우로 회수된다. */
  agentId: string;
  /** 저장 성공 시 상위가 템플릿 목록을 새로고침하도록 알린다. */
  onSaved: () => void;
}

type Phase = 'idle' | 'loading' | 'naming' | 'saving' | 'saved' | 'empty' | 'error';

/**
 * '템플릿으로 저장' — 완료된 대화형 런의 selections 를 이름 붙여 저장한다.
 *
 * 클릭 시 런 상세(GET /runs/{id})에서 selections 를 읽고, 있으면 인라인 입력으로 이름을
 * 받아 POST /runs/templates 로 저장한다. 저장할 선택이 없으면(데모/비대화형) 안내만 한다.
 * 모든 실패는 조용히 문구로 표시한다(흐름을 막지 않는다).
 */
export function SaveTemplateButton({ runId, agentId, onSaved }: SaveTemplateButtonProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [selections, setSelections] = useState<ChatSelection[]>([]);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function begin(): Promise<void> {
    setPhase('loading');
    setError(null);
    try {
      const detail = await fetchRunDetail(runId);
      const sel = extractSelections(detail);
      if (sel.length === 0) {
        setPhase('empty');
        return;
      }
      setSelections(sel);
      setName(defaultName(detail.resultSummary));
      setPhase('naming');
    } catch (err) {
      setError(messageOf(err));
      setPhase('error');
    }
  }

  async function commit(): Promise<void> {
    const trimmed = name.trim();
    if (!trimmed || phase === 'saving') return;
    setPhase('saving');
    setError(null);
    try {
      await saveTemplate({ agentId, name: trimmed, selections });
      setPhase('saved');
      onSaved();
    } catch (err) {
      setError(messageOf(err));
      setPhase('error');
    }
  }

  if (phase === 'saved') {
    return (
      <p className="text-success flex items-center gap-1.5 text-[12px] font-medium">
        <RiCheckLine size={14} aria-hidden />
        템플릿으로 저장했습니다.
      </p>
    );
  }

  if (phase === 'empty') {
    return (
      <p className="text-foreground-tertiary text-[12px]">
        이 실행에는 템플릿으로 저장할 선택이 없습니다.
      </p>
    );
  }

  if (phase === 'naming' || phase === 'saving') {
    const saving = phase === 'saving';
    return (
      <div className="flex flex-col gap-2">
        <label className="text-foreground-secondary text-[11px] font-medium">템플릿 이름</label>
        <div className="border-border bg-surface-raised flex items-center gap-2 rounded-[var(--radius-md)] border p-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && name.trim()) {
                e.preventDefault();
                void commit();
              }
            }}
            autoFocus
            disabled={saving}
            placeholder="예: 6월 법인카드 정기 처리"
            className="text-foreground placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-[length:var(--text-body-sm)] outline-none disabled:opacity-50"
          />
          <Button size="sm" onClick={() => void commit()} disabled={!name.trim() || saving}>
            {saving ? (
              <RiLoader4Line size={14} className="animate-spin" aria-hidden />
            ) : (
              <RiBookmarkLine size={14} aria-hidden />
            )}
            {saving ? '저장 중…' : '저장'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="취소"
            onClick={() => setPhase('idle')}
            disabled={saving}
          >
            <RiCloseLine size={14} aria-hidden />
          </Button>
        </div>
        {error ? <span className="text-danger text-[12px]">{error}</span> : null}
      </div>
    );
  }

  // idle / loading / error
  return (
    <div className="flex flex-col gap-1.5">
      <Button
        size="sm"
        variant="secondary"
        onClick={() => void begin()}
        disabled={phase === 'loading'}
        className="border-accent/30 text-accent hover:bg-accent/10 w-fit"
      >
        {phase === 'loading' ? (
          <RiLoader4Line size={14} className="animate-spin" aria-hidden />
        ) : (
          <RiBookmarkLine size={14} aria-hidden />
        )}
        템플릿으로 저장
      </Button>
      {error ? <span className="text-danger text-[12px]">{error}</span> : null}
    </div>
  );
}

function defaultName(summary: string | null): string {
  const base = (summary ?? '').trim();
  if (!base) return '';
  return base.length > 40 ? base.slice(0, 40) : base;
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return '세션이 만료되었습니다. 다시 로그인해 주세요.';
    return err.message;
  }
  return '템플릿 저장에 실패했습니다.';
}
