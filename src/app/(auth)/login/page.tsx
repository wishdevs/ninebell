import type { Metadata } from 'next';
import { LoginForm } from './_components/login-form';

export const metadata: Metadata = {
  title: '로그인',
};

export default function LoginPage() {
  return (
    <div className="animate-page-enter grid gap-6">
      <header className="grid gap-3">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          환영합니다
        </p>
        <h1 className="text-[length:var(--text-heading)] leading-[1.15] font-semibold tracking-[-0.01em]">
          로그인
        </h1>
        <p className="text-muted-foreground text-[length:var(--text-body)] leading-relaxed">
          옴니솔 계정으로 계속하기
        </p>
      </header>
      <LoginForm />
    </div>
  );
}
