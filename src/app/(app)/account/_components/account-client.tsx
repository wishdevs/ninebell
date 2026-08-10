'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { SectionCard } from '@/components/ui/section-card';
import { useCurrentUser, useSetCurrentUser } from '@/app/(app)/providers/user-provider';
import { errorMessage, updateMe } from '@/lib/api/client';
import { MEMBER_ROLE_LABEL } from '@/lib/data/members';

/**
 * 계정 설정 폼 — 본인의 이메일을 수정한다(`PATCH /auth/me`).
 * 이름·부서는 옴니솔(ERP) 프로필 동기화 값이라 로그인 식별자·역할과 함께 읽기 전용으로만 표시한다.
 */
export function AccountClient() {
  const user = useCurrentUser();
  const setUser = useSetCurrentUser();

  const [email, setEmail] = useState(user.email ?? '');
  const [saving, setSaving] = useState(false);

  const dirty = email.trim() !== (user.email ?? '');

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await updateMe({
        email: email.trim() || null,
      });
      setUser(updated);
      setEmail(updated.email ?? '');
      toast.success('저장했습니다');
    } catch (err) {
      toast.error(errorMessage(err, '저장하지 못했습니다.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="개인"
        title="계정 설정"
        description="내 이메일을 관리합니다. 이름·부서는 옴니솔 프로필과 동기화되며, 로그인 아이디와 역할은 관리자만 변경할 수 있습니다."
      />

      <SectionCard
        density="comfortable"
        caption="프로필"
        title="기본 정보"
        description="사이드바와 멤버 목록에 표시되는 정보입니다."
      >
        <FormField id="account-userid" label="로그인 아이디" hint="더존 옴니솔 계정 아이디입니다.">
          <Input id="account-userid" value={user.omnisolUserid} readOnly disabled />
        </FormField>

        <FormField id="account-role" label="역할">
          <Input id="account-role" value={MEMBER_ROLE_LABEL[user.role]} readOnly disabled />
        </FormField>

        <FormField id="account-name" label="이름" hint="옴니솔 프로필과 동기화됩니다.">
          <Input id="account-name" value={user.displayName} readOnly disabled />
        </FormField>

        <FormField id="account-department" label="부서" hint="옴니솔 프로필과 동기화됩니다.">
          <Input id="account-department" value={user.department ?? ''} readOnly disabled />
        </FormField>

        <FormField id="account-email" label="이메일" hint="알림·초대 수신에 사용됩니다.">
          <Input
            id="account-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            maxLength={320}
            placeholder="name@company.com"
          />
        </FormField>

        <div className="border-border-subtle flex justify-end border-t pt-5">
          <Button type="button" onClick={() => void handleSave()} disabled={!dirty || saving}>
            {saving ? '저장 중…' : '변경 사항 저장'}
          </Button>
        </div>
      </SectionCard>
    </div>
  );
}
