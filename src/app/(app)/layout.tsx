import { DashboardShell } from '@/components/shell/dashboard-shell';

/**
 * 인증된 앱 셸 레이아웃. 기본형은 실제 인증 가드 없이 항상 셸을 렌더한다.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <DashboardShell>{children}</DashboardShell>;
}
