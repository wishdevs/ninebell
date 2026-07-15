'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { Spinner } from '@/components/ui/spinner';
import { ApiError, api } from '@/lib/api/client';

/** 로그인 단계에서 넘어온 pending 정보 키. login-form과 동일해야 한다. */
const SIGNUP_STORAGE_KEY = 'nb_signup';

/** sessionStorage에 저장된 pending 회원가입 정보 형태. */
interface PendingSignup {
  signupToken: string;
  displayName: string;
  department: string | null;
}

function readPending(): PendingSignup | null {
  const raw = sessionStorage.getItem(SIGNUP_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PendingSignup>;
    if (!parsed.signupToken) return null;
    return {
      signupToken: parsed.signupToken,
      displayName: parsed.displayName ?? '',
      department: parsed.department ?? null,
    };
  } catch {
    return null;
  }
}

/**
 * 회원가입 폼.
 *
 * 로그인이 첫 접속으로 판정하면 signupToken+prefill을 sessionStorage에 넣고
 * 이 화면으로 보낸다. pending 정보가 없으면(직접 URL 접근 등) `/login`으로
 * 되돌린다. 이름·부서는 ERP 프로필값 읽기전용(부서는 조직구분 자동배정 키),
 * 이메일은 선택 입력(추후 필수화)이며
 * 약관 동의 후 `POST /auth/signup`으로 계정을 생성하고 세션을 발급받아 홈으로 이동한다.
 */
export function SignupForm() {
  const router = useRouter();
  const [signupToken, setSignupToken] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [department, setDepartment] = useState('');
  const [email, setEmail] = useState('');
  const [agreedTerms, setAgreedTerms] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const pending = readPending();
    if (!pending) {
      router.replace('/login');
      return;
    }
    setSignupToken(pending.signupToken);
    setDisplayName(pending.displayName);
    setDepartment(pending.department ?? '');
    setReady(true);
  }, [router]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setError(null);

    if (!displayName.trim()) {
      setError('이름을 입력해주세요.');
      return;
    }
    // 이메일은 선택 입력(추후 필수화) — 비어 있어도 제출 허용.
    if (!agreedTerms) {
      setError('약관에 동의해주세요.');
      return;
    }

    setSubmitting(true);
    try {
      await api.post('/auth/signup', {
        signupToken,
        displayName: displayName.trim(),
        department: department.trim(),
        // 빈값이면 email 키 생략(EmailStr("") 검증 회피) — 백엔드가 선택으로 처리.
        ...(email.trim() ? { email: email.trim() } : {}),
        agreedTerms: true,
      });
      sessionStorage.removeItem(SIGNUP_STORAGE_KEY);
      router.replace('/');
      router.refresh();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 0) {
        setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');
      } else if (err instanceof ApiError) {
        // 400/만료 등 — 백엔드 detail을 그대로 노출(예: 만료된 signupToken).
        setError(err.message || '회원가입을 완료하지 못했습니다.');
      } else {
        setError('회원가입 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
      }
      setSubmitting(false);
    }
  }

  // pending 확인 전에는 폼을 그리지 않는다(없으면 곧 /login으로 리다이렉트).
  if (!ready) {
    return (
      <div className="grid place-items-center py-10">
        <Spinner size={22} label="불러오는 중" className="text-foreground-tertiary" />
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-5" noValidate>
      <FormField
        id="displayName"
        label="이름"
        hint="옴니솔 프로필에서 불러왔어요. 직접 수정할 수 없어요."
      >
        <Input
          id="displayName"
          name="displayName"
          type="text"
          autoComplete="name"
          placeholder="이름"
          value={displayName}
          readOnly
          aria-readonly
          tabIndex={-1}
          className="cursor-not-allowed opacity-70"
        />
      </FormField>

      <FormField
        id="department"
        label="부서"
        hint="옴니솔 프로필의 소속이에요. 조직구분 자동 배정에 쓰여 직접 수정할 수 없어요."
      >
        <Input
          id="department"
          name="department"
          type="text"
          autoComplete="organization-title"
          placeholder="부서"
          value={department}
          readOnly
          aria-readonly
          tabIndex={-1}
          className="cursor-not-allowed opacity-70"
        />
      </FormField>

      <FormField id="email" label="이메일" hint="선택 입력" error={error ?? undefined}>
        <Input
          id="email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="name@ninebell.co.kr"
          value={email}
          aria-invalid={error ? true : undefined}
          onChange={(event) => {
            setEmail(event.target.value);
            if (error) setError(null);
          }}
        />
      </FormField>

      <div className="border-border bg-surface grid gap-3 rounded-[var(--radius-md)] border p-4">
        <p className="text-foreground text-[length:var(--text-body-sm)] font-medium">
          서비스 이용약관
        </p>
        {/* TODO: 실제 약관 문구는 추후 확정. 현재는 플레이스홀더. */}
        <div className="text-muted-foreground max-h-28 overflow-y-auto text-[length:var(--text-caption)] leading-relaxed">
          <p>
            본 서비스는 나인벨 내부 임직원을 대상으로 제공됩니다. 계정 정보와 활동 로그는 서비스
            운영·보안 목적으로 수집·이용되며, 관련 법령과 사내 정책에 따라 관리됩니다. 실제 약관
            문구는 추후 확정되어 갱신될 예정입니다.
          </p>
        </div>
        <label className="text-foreground flex cursor-pointer items-start gap-2.5 text-[length:var(--text-body-sm)]">
          <input
            type="checkbox"
            className="accent-accent mt-0.5 h-4 w-4 cursor-pointer"
            checked={agreedTerms}
            onChange={(event) => {
              setAgreedTerms(event.target.checked);
              if (error) setError(null);
            }}
          />
          <span>위 서비스 이용약관 및 개인정보 처리방침에 동의합니다.</span>
        </label>
      </div>

      <Button type="submit" disabled={submitting}>
        {submitting ? (
          <>
            <Spinner size={16} />
            가입 처리 중…
          </>
        ) : (
          '가입 완료'
        )}
      </Button>

      <p className="text-foreground-tertiary mt-1 text-center text-[length:var(--text-caption)] leading-relaxed">
        문제가 있나요?{' '}
        <Link
          href="/login"
          className="text-foreground hover:text-accent underline-offset-4 hover:underline"
        >
          다시 로그인
        </Link>
      </p>
    </form>
  );
}
