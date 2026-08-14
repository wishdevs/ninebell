import { DashboardShell } from '@/components/shell/dashboard-shell';
import { DebugModeProvider } from '@/lib/debug-mode';
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
      <DebugModeProvider>
        {/* 우하단 AI 어시스턴트 플로팅 런처(ChatLauncher)는 내렸다(사용자 결정 2026-08-11).
            컴포넌트와 /assistant 화면은 그대로 남아 있어 이 한 줄로 되돌릴 수 있다. */}
        <DashboardShell>{children}</DashboardShell>
      </DebugModeProvider>
    </UserProvider>
  );
}
