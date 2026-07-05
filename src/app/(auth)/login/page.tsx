import type { Metadata } from 'next';
import { AuthPageHeader } from '../_components/auth-page-header';
import { LoginForm } from './_components/login-form';

export const metadata: Metadata = {
  title: '로그인',
};

export default function LoginPage() {
  return (
    <div className="animate-page-enter grid gap-6">
      <AuthPageHeader
        caption="환영합니다"
        title="로그인"
        description="옴니솔 계정으로 계속하기"
      />
      <LoginForm />
    </div>
  );
}
