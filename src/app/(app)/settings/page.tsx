import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { IS_DEV_ENV } from '@/lib/env';
import { SettingsClient } from './_components/settings-client';

export const metadata: Metadata = { title: '조직 설정' };

/**
 * 조직 설정 (탭 폼) — 서버 컴포넌트.
 *
 * metadata export를 위해 page는 서버로 두고, 폼 상태/스위치/탭 전환 등
 * 인터랙티브 로직은 클라이언트 자식(SettingsClient)에 위임한다.
 */
export default function SettingsPage() {
  // 정적 픽스처 기반 목업 — 비개발 환경에선 직접 URL 접근을 404 로 막는다(nav devOnly 규약).
  if (!IS_DEV_ENV) notFound();
  return <SettingsClient />;
}
