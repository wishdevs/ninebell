import { Suspense } from 'react';
import type { Metadata } from 'next';
import { Spinner } from '@/components/ui/spinner';
import { AuthPageHeader } from '../_components/auth-page-header';
import { LoginForm } from './_components/login-form';

export const metadata: Metadata = {
  title: '로그인',
};

export default function LoginPage() {
  return (
    <div className="animate-page-enter grid gap-6">
      <AuthPageHeader caption="환영합니다" title="로그인" description="옴니솔 계정으로 계속하기" />
      {/* ⚠ Suspense 필수 — LoginForm 이 useSearchParams(?next=)를 읽는다. 경계가 없으면 이
          페이지의 프리렌더가 통째로 클라이언트 렌더로 떨어진다(Next 문서: 개발 모드에선
          on-demand 렌더라 없어도 되는 것처럼 보이지만 빌드에서 드러난다). */}
      <Suspense
        fallback={
          <div className="grid h-72 place-items-center">
            <Spinner size={20} label="불러오는 중" className="text-foreground-tertiary" />
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}
