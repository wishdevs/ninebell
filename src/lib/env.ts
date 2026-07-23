/**
 * 배포 환경 판정 — 빌드 타임 명시값(NEXT_PUBLIC_APP_ENV) 우선, 미설정이면 NODE_ENV 폴백.
 *
 * 배포 매트릭스(2026-07-23 확정): AWS 테스트 클러스터는 deploy.yml 이 development 로 빌드해
 * 개발 기능(devOnly 메뉴·AI 모델 스위처)을 노출하고, 온프렘(GitLab)은 미설정(프로덕션 빌드
 * 폴백)이라 전부 은닉된다. 로컬 `next dev` 는 NODE_ENV 폴백으로 항상 개발 환경.
 * ⚠ NEXT_PUBLIC_* 은 빌드 타임 인라인 — 반드시 리터럴 참조를 유지할 것.
 */
export const IS_DEV_ENV =
  process.env.NEXT_PUBLIC_APP_ENV === 'development' ||
  (!process.env.NEXT_PUBLIC_APP_ENV && process.env.NODE_ENV !== 'production');
