'use client';

import { Check, ChevronsUpDown, Mail, Settings } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { ACTIVE_WORKSPACE, ROLE_LABEL, WORKSPACES, type Workspace } from '@/lib/data/workspace';
import { cn } from '@/lib/utils';

function orgInitial(name: string): string {
  const trimmed = name.trim();
  return trimmed ? trimmed[0].toUpperCase() : '?';
}

const MANAGER_ROLES = new Set(['owner', 'admin']);

/**
 * 워크스페이스(조직) 전환기. 사이드바 상단에 고정.
 *
 * 기본형은 선택 상태를 실제로 전환하지 않고(백엔드 없음) 활성 워크스페이스를
 * 정적으로 보여준다 — 디자인/상호작용 형태 전달이 목적.
 */
export function WorkspaceSwitcher() {
  const current = ACTIVE_WORKSPACE;
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const closePanel = useCallback(() => setOpen(false), []);
  const canManage = MANAGER_ROLES.has(current.role);

  return (
    <div ref={rootRef} className="relative px-4 pt-4 pb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={panelId}
        className={cn(
          'border-border bg-surface-raised flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5 text-left shadow-[var(--shadow-card)] transition-colors duration-[var(--duration-fast)]',
          open ? 'bg-muted ring-accent/30 ring-2' : 'hover:bg-muted/60',
        )}
      >
        <OrgColorBar color={current.color} />
        <span className="min-w-0 flex-1">
          <span
            className="text-foreground block truncate text-[length:var(--text-body)] leading-tight font-semibold"
            title={current.name}
          >
            {current.name}
          </span>
          <span className="text-foreground-tertiary block truncate text-[length:var(--text-caption)] leading-tight">
            {ROLE_LABEL[current.role]}
          </span>
        </span>
        <ChevronsUpDown
          size={11}
          strokeWidth={1.75}
          aria-hidden
          className="text-foreground-tertiary shrink-0"
        />
      </button>

      {open ? (
        <div
          id={panelId}
          role="menu"
          className="border-border bg-surface absolute top-full left-3 z-20 mt-1.5 flex w-[320px] flex-col overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-overlay)]"
        >
          <header className="flex items-center gap-2.5 px-3 py-3">
            <OrgAvatar name={current.name} />
            <div className="min-w-0 flex-1">
              <p
                className="text-foreground truncate text-[length:var(--text-body)] leading-tight font-semibold"
                title={current.name}
              >
                {current.name}
              </p>
              <p className="text-foreground-tertiary truncate text-[length:var(--text-caption)] leading-tight">
                {current.memberCount}명
              </p>
            </div>
          </header>

          {canManage ? (
            <div className="flex flex-col gap-2 px-3 py-2">
              <div className="grid grid-cols-2 gap-2">
                <PanelLink
                  href="/settings"
                  icon={<Settings size={14} strokeWidth={1.75} aria-hidden />}
                  label="조직 설정"
                  onNavigate={closePanel}
                />
                <PanelLink
                  href="/members"
                  icon={<Mail size={14} strokeWidth={1.75} aria-hidden />}
                  label="멤버 초대"
                  onNavigate={closePanel}
                />
              </div>
            </div>
          ) : null}

          <div className="border-border border-t" />

          <p className="text-foreground-tertiary px-3 pt-2.5 pb-1 text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
            워크스페이스 전환
          </p>
          <ul className="flex flex-col py-1">
            {WORKSPACES.map((org) => (
              <li key={org.id}>
                <OrgMenuItem org={org} selected={org.id === current.id} onSelect={closePanel} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function OrgColorBar({ color }: { color: string | null }) {
  return (
    <span
      aria-hidden
      className="h-5 w-1 shrink-0 rounded-full"
      style={{ backgroundColor: color ?? 'var(--color-accent)' }}
    />
  );
}

function OrgAvatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="from-accent to-accent/70 text-accent-foreground flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-gradient-to-br text-[length:var(--text-body)] font-semibold tracking-tight"
    >
      {orgInitial(name)}
    </span>
  );
}

interface PanelLinkProps {
  href: string;
  icon: React.ReactNode;
  label: string;
  onNavigate: () => void;
}

function PanelLink({ href, icon, label, onNavigate }: PanelLinkProps) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      role="menuitem"
      className="border-border bg-surface-raised text-foreground hover:bg-muted flex items-center justify-start gap-2 rounded-[var(--radius-sm)] border px-2.5 py-2 text-[length:var(--text-caption)] font-medium transition-colors duration-[var(--duration-fast)]"
    >
      <span className="text-foreground-tertiary shrink-0">{icon}</span>
      <span className="truncate">{label}</span>
    </Link>
  );
}

function OrgMenuItem({
  org,
  selected,
  onSelect,
}: {
  org: Workspace;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        'flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors duration-[var(--duration-fast)]',
        selected ? 'bg-muted' : 'hover:bg-muted',
      )}
    >
      <OrgColorBar color={org.color} />
      <span className="min-w-0 flex-1">
        <span
          className="text-foreground block truncate text-[length:var(--text-body)] leading-tight font-medium"
          title={org.name}
        >
          {org.name}
        </span>
        <span className="text-foreground-tertiary block truncate text-[length:var(--text-caption)] leading-tight">
          {ROLE_LABEL[org.role]}
        </span>
      </span>
      {selected ? (
        <Check size={14} strokeWidth={2.25} aria-hidden className="text-accent shrink-0" />
      ) : null}
    </button>
  );
}
