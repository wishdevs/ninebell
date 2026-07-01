import type { Metadata } from 'next';
import { SignupForm } from './_components/signup-form';

export const metadata: Metadata = {
  title: '회원가입',
};

export default function SignupPage() {
  return (
    <div className="animate-page-enter grid gap-6">
      <header className="grid gap-3">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          거의 다 왔어요
        </p>
        <h1 className="text-[length:var(--text-heading)] leading-[1.15] font-semibold tracking-[-0.01em]">
          회원가입
        </h1>
        <p className="text-muted-foreground text-[length:var(--text-body)] leading-relaxed">
          옴니솔 계정 확인이 끝났어요. 프로필을 확인하고 가입을 완료해주세요.
        </p>
      </header>
      <SignupForm />
    </div>
  );
}
