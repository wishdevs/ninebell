import type { Metadata } from 'next';
import { LogsClient } from './_components/logs-client';

export const metadata: Metadata = {
  title: '로깅',
};

/**
 * 로깅(Logging) 화면 — 에이전트 사용 내역(실행 로그). 어떤 에이전트를 누가 언제 돌렸고
 * 어떤 상태로 끝났는지, 실패했다면 어느 단계에서 멈췄는지(`GET /runs`)를 보여준다. 행을
 * 펼치면 단계별 로그 + 입력값(selections/chat) + 실패 단계로 "무엇을 입력했고 어디서
 * 실패했는지"를 파악해 추후 보완에 쓴다.
 *
 * 서버 컴포넌트는 metadata만 소유하고, 권한 게이팅과 데이터 로드는 클라이언트 자식이
 * 담당한다(세션 쿠키 기반 fetch). logs:read(admin+) 전용.
 */
export default function LogsPage() {
  return <LogsClient />;
}
