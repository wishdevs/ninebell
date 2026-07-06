import type { Metadata } from 'next';
import { AgentSettingsClient } from './_components/agent-settings-client';

export const metadata: Metadata = { title: '에이전트 관리' };

/**
 * 에이전트 관리(관리자 전용) — 에이전트별 세부설정을 스키마 기반 폼으로 편집한다.
 *
 * 서버 컴포넌트는 metadata만 소유하고, 데이터 로드(`GET /agents`)와 저장
 * (`PATCH /agents/{id}/settings`)은 클라이언트 자식이 담당한다(organizations 화면과
 * 동일 아키타입). 접근 게이트는 minRole=admin — 사이드바 노출과 화면 내 게이트가 같다.
 */
export default function ManageAgentsPage() {
  return <AgentSettingsClient />;
}
