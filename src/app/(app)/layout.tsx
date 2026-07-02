import { DashboardShell } from '@/components/shell/dashboard-shell';
import { ChatLauncher } from '@/components/assistant/chat-launcher';
import { UserProvider } from './providers/user-provider';

/**
 * 인증된 앱 셸 레이아웃.
 *
 * `UserProvider`가 `GET /auth/me`로 현재 사용자+권한을 로드한 뒤에만 셸을
 * 렌더하고, 미인증(401)이면 `/login`으로 보낸다. 따라서 (app) 하위 화면은
 * `useCurrentUser()`/`usePermissions()`를 안전하게 사용할 수 있다.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <UserProvider>
      <DashboardShell>{children}</DashboardShell>
      <ChatLauncher />
    </UserProvider>
  );
}
