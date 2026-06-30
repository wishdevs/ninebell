'use client';

import { useState, type ReactNode } from 'react';
import { MoreHorizontal, Trash2, UserCheck, UserX } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import type { WorkspaceMember } from '@/lib/data/members';

interface MemberRowActionsProps {
  member: WorkspaceMember;
  onToggleStatus: (member: WorkspaceMember) => void;
  onRequestRemove: (member: WorkspaceMember) => void;
}

/**
 * 행 우측의 ⋯ 액션 메뉴. 상태에 따라 정지/활성 라벨을 토글하고, 삭제는
 * 부모로 위임(부모가 ConfirmDialog를 띄운다). Radix Popover로 포털 +
 * 바깥 클릭 + ESC를 처리한다.
 */
export function MemberRowActions({
  member,
  onToggleStatus,
  onRequestRemove,
}: MemberRowActionsProps) {
  const [open, setOpen] = useState(false);
  const isSuspended = member.status === 'suspended';

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${member.name} 멤버 액션`}
          className={cn(
            'text-foreground-tertiary hover:text-foreground hover:bg-muted inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] transition-colors',
            'focus-visible:ring-accent/40 focus-visible:ring-2 focus-visible:outline-none',
            'data-[state=open]:bg-muted data-[state=open]:text-foreground',
          )}
        >
          <MoreHorizontal size={16} aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="w-44 p-1">
        <div role="menu" className="grid gap-0.5">
          <MenuItem
            icon={isSuspended ? <UserCheck size={14} aria-hidden /> : <UserX size={14} aria-hidden />}
            label={isSuspended ? '활성화' : '정지'}
            onSelect={() => {
              onToggleStatus(member);
              setOpen(false);
            }}
          />
          <MenuItem
            icon={<Trash2 size={14} aria-hidden />}
            label="삭제"
            danger
            onSelect={() => {
              onRequestRemove(member);
              setOpen(false);
            }}
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}

interface MenuItemProps {
  icon: ReactNode;
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

function MenuItem({ icon, label, onSelect, danger }: MenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onSelect}
      className={cn(
        'flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-left text-[length:var(--text-body-sm)] transition-colors',
        danger ? 'text-danger hover:bg-danger/10' : 'text-foreground hover:bg-muted',
      )}
    >
      <span className="shrink-0">{icon}</span>
      {label}
    </button>
  );
}
