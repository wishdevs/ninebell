'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // 더미 화면 — 실제 인증 없이 홈으로 이동한다.
    router.push('/');
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-5" noValidate>
      <FormField id="email" label="이메일" required>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="name@etribe.co.kr"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
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
          onChange={(event) => setPassword(event.target.value)}
          required
        />
      </FormField>

      <Button type="submit">로그인</Button>

      <div className="text-muted-foreground flex flex-col items-center gap-2 text-center text-[length:var(--text-body-sm)]">
        <Link
          href="/"
          className="text-muted-foreground hover:text-accent font-medium transition-colors"
        >
          비밀번호를 잊으셨나요?
        </Link>
        <p>
          계정이 없으신가요?{' '}
          <Link href="/" className="text-accent font-medium hover:underline">
            계정 만들기
          </Link>
        </p>
      </div>

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
