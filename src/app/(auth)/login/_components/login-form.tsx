'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { Spinner } from '@/components/ui/spinner';
import { ApiError, api } from '@/lib/api/client';

/** 회원가입 유도 시 sessionStorage에 넘길 pending 정보 키. */
const SIGNUP_STORAGE_KEY = 'nb_signup';

/**
 * `POST /auth/login` 응답 계약.
 * - 기존 유저/로컬 계정: 세션 발급 후 `{ ok: true }`.
 * - 옴니솔 첫 접속(유저 없음): 세션 미발급, 회원가입 유도 `{ signupRequired, signupToken, prefill }`.
 */
type LoginResponse =
  | { ok: true }
  | {
      signupRequired: true;
      signupToken: string;
      prefill: { displayName: string; department: string | null };
    };

/**
 * 옴니솔(더존 ERP) 자격증명 로그인 폼.
 *
 * 옴니솔이 사실상 IdP라 이메일이 아닌 **옴니솔 아이디 + 비밀번호**로 인증한다.
 * `POST /auth/login`이 자격증명을 검증한 뒤 응답을 분기한다: 세션이 발급되면
 * 홈으로, 첫 접속이면 prefill을 저장하고 회원가입으로 유도한다. 자격증명
 * 오류(401)는 인라인 메시지로 노출한다.
 */
export function LoginForm() {
  const router = useRouter();
  const [userid, setUserid] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.post<LoginResponse>('/auth/login', { userid, password });
      if ('signupRequired' in res && res.signupRequired) {
        // 첫 접속 — 세션 미발급. prefill+토큰을 넘겨 회원가입 단계로 유도한다.
        sessionStorage.setItem(
          SIGNUP_STORAGE_KEY,
          JSON.stringify({
            signupToken: res.signupToken,
            displayName: res.prefill.displayName,
            department: res.prefill.department,
          }),
        );
        router.push('/signup');
        return;
      }
      // 세션 쿠키 발급 완료 → 보호 라우트로. refresh로 미들웨어가 쿠키를 재평가하게 한다.
      router.replace('/');
      router.refresh();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        setError('아이디 또는 비밀번호가 올바르지 않습니다.');
      } else if (err instanceof ApiError && err.status === 0) {
        setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');
      } else {
        setError('로그인 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
      }
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-5" noValidate>
      <FormField id="userid" label="옴니솔 아이디" required error={error ?? undefined}>
        <Input
          id="userid"
          name="userid"
          type="text"
          autoComplete="username"
          placeholder="옴니솔 로그인 아이디"
          value={userid}
          aria-invalid={error ? true : undefined}
          onChange={(event) => {
            setUserid(event.target.value);
            if (error) setError(null);
          }}
          required
        />
      </FormField>

      <FormField id="password" label="비밀번호" required>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          aria-invalid={error ? true : undefined}
          onChange={(event) => {
            setPassword(event.target.value);
            if (error) setError(null);
          }}
          required
        />
      </FormField>

      <Button type="submit" disabled={submitting}>
        {submitting ? (
          <>
            <Spinner size={16} />
            로그인 중…
          </>
        ) : (
          '로그인'
        )}
      </Button>

      <p className="text-foreground-tertiary mt-1 text-center text-[length:var(--text-caption)] leading-relaxed">
        로그인 시{' '}
        <Link
          href="/"
          className="text-foreground hover:text-accent underline-offset-4 hover:underline"
        >
          서비스 약관
        </Link>
        과{' '}
        <Link
          href="/"
          className="text-foreground hover:text-accent underline-offset-4 hover:underline"
        >
          개인정보 보호정책
        </Link>
        에 동의한 것으로 간주됩니다.
      </p>
    </form>
  );
}
