'use client';

import { useState } from 'react';
import { AlertTriangle, Archive, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { ACTIVE_WORKSPACE } from '@/lib/data/workspace';

type DangerAction = 'archive' | 'delete';

export function DangerTab() {
  const [open, setOpen] = useState<DangerAction | null>(null);

  return (
    <section
      aria-labelledby="danger-heading"
      className="border-danger/40 bg-danger/5 flex flex-col gap-6 rounded-[var(--radius-lg)] border p-6"
    >
      <header className="flex items-center gap-2">
        <AlertTriangle size={18} strokeWidth={1.75} className="text-danger" aria-hidden />
        <div className="grid gap-0.5">
          <p className="text-danger text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
            위험 구역
          </p>
          <h2 id="danger-heading" className="text-lg font-semibold tracking-tight">
            되돌릴 수 없는 작업
          </h2>
        </div>
      </header>

      <div className="border-border-subtle bg-surface flex flex-col gap-3 rounded-[var(--radius-md)] border p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="grid gap-1">
          <span className="text-foreground text-sm font-medium">조직 보관</span>
          <span className="text-muted-foreground max-w-prose text-xs leading-relaxed">
            보관하면 모든 멤버가 이 조직에 접근할 수 없게 되고 사이드바에서 사라집니다. 슬러그는
            계속 예약됩니다.
          </span>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="shrink-0"
          onClick={() => setOpen('archive')}
        >
          <Archive size={14} strokeWidth={1.75} aria-hidden />
          <span className="ml-1.5">조직 보관</span>
        </Button>
      </div>

      <div className="border-danger/30 bg-surface flex flex-col gap-3 rounded-[var(--radius-md)] border p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="grid gap-1">
          <span className="text-foreground text-sm font-medium">조직 삭제</span>
          <span className="text-muted-foreground max-w-prose text-xs leading-relaxed">
            조직과 모든 데이터가 영구히 삭제됩니다. 이 작업은 되돌릴 수 없습니다.
          </span>
        </div>
        <Button
          type="button"
          variant="danger"
          size="sm"
          className="shrink-0"
          onClick={() => setOpen('delete')}
        >
          <Trash2 size={14} strokeWidth={1.75} aria-hidden />
          <span className="ml-1.5">조직 삭제</span>
        </Button>
      </div>

      <ConfirmDialog
        open={open === 'archive'}
        onClose={() => setOpen(null)}
        title="조직을 보관할까요?"
        message={
          <span>
            <span className="text-foreground font-medium">{ACTIVE_WORKSPACE.name}</span> 조직을
            보관하면 모든 멤버가 즉시 이 조직에 접근할 수 없게 됩니다.
          </span>
        }
        confirmLabel="보관"
        variant="primary"
        onConfirm={() => {
          toast.success('조직을 보관했습니다');
        }}
      />

      <ConfirmDialog
        open={open === 'delete'}
        onClose={() => setOpen(null)}
        title="조직을 삭제할까요?"
        message={
          <span>
            <span className="text-foreground font-medium">{ACTIVE_WORKSPACE.name}</span> 조직과 모든
            데이터가 영구히 삭제됩니다. 계속하려면 아래에 조직 슬러그를 입력하세요.
          </span>
        }
        confirmWord={ACTIVE_WORKSPACE.slug}
        confirmLabel="삭제"
        onConfirm={() => {
          toast.success('조직을 삭제했습니다');
        }}
      />
    </section>
  );
}
