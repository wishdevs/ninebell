import type { Metadata } from 'next';
import { AuthPageHeader } from '../_components/auth-page-header';
import { SignupForm } from './_components/signup-form';

export const metadata: Metadata = {
  title: '회원가입',
};

export default function SignupPage() {
  return (
    <div className="animate-page-enter grid gap-6">
      <AuthPageHeader
        caption="거의 다 왔어요"
        title="회원가입"
        description="옴니솔 계정 확인이 끝났어요. 프로필을 확인하고 가입을 완료해주세요."
      />
      <SignupForm />
    </div>
  );
}
