'use client';

import { useState } from 'react';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import type { Role } from '@/lib/auth/permissions';
import { MEMBER_ROLE_LABEL } from '@/lib/data/members';

export interface InviteInput {
  email: string;
  role: Role;
}

interface InviteDialogProps {
  open: boolean;
  onClose: () => void;
  onInvite: (input: InviteInput) => void;
}

/** 가벼운 형식 검증 — 실제 전송이 없으므로 모양만 확인한다. */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** 초대 시 부여 가능한 역할 — 최고관리자는 초대로 만들 수 없다. */
const INVITABLE_ROLES: readonly Role[] = ['admin', 'user'];

export function InviteDialog({ open, onClose, onInvite }: InviteDialogProps) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('user');
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setEmail('');
    setRole('user');
    setError(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  function handleSubmit() {
    const value = email.trim();
    if (!EMAIL_PATTERN.test(value)) {
      setError('유효한 이메일 주소를 입력해주세요.');
      return;
    }
    onInvite({ email: value, role });
    reset();
    onClose();
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="멤버 초대"
      description="이메일로 워크스페이스 초대를 보냅니다."
      size="sm"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={handleClose}>
            취소
          </Button>
          <Button variant="primary" size="sm" onClick={handleSubmit}>
            초대 보내기
          </Button>
        </>
      }
    >
      <DialogBody>
        <FormField
          id="invite-email"
          label="이메일"
          required
          error={error ?? undefined}
          hint={error ? undefined : '초대 링크가 이 주소로 전송됩니다.'}
        >
          <Input
            id="invite-email"
            type="email"
            inputMode="email"
            autoComplete="off"
            placeholder="name@ninebell.co.kr"
            value={email}
            aria-invalid={error ? true : undefined}
            onChange={(e) => {
              setEmail(e.target.value);
              if (error) setError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmit();
            }}
          />
        </FormField>

        <FormField id="invite-role" label="역할" hint="초대된 멤버에게 부여할 권한입니다.">
          <Select value={role} onValueChange={(value) => setRole(value as Role)}>
            {/* z-[200]: 다이얼로그(z-100) 위로 팝업이 떠야 가려지지 않는다. */}
            <SelectTrigger id="invite-role" className="h-9 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="z-[200]">
              {INVITABLE_ROLES.map((value) => (
                <SelectItem key={value} value={value}>
                  {MEMBER_ROLE_LABEL[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </DialogBody>
    </Dialog>
  );
}
