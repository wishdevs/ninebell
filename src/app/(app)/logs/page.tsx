import type { Metadata } from 'next';
import { LogsClient } from './_components/logs-client';

export const metadata: Metadata = {
  title: '로깅',
};

/**
 * 접속 로깅 화면 — 로그인 성공/실패 이벤트(언제·누가·어디서)를 보여준다.
 *
 * 서버 컴포넌트는 metadata만 소유하고, 권한 게이팅과 데이터 로드는 클라이언트
 * 자식이 담당한다(세션 쿠키 기반 fetch). admin+ 전용이며 `user` 롤은 접근 불가.
 */
export default function LogsPage() {
  return <LogsClient />;
}
