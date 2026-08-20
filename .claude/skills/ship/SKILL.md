---
name: ship
description: 커밋→릴리스 판정→main 반영→푸시를 한 번에 처리하는 배포 파이프라인 원커맨드. Use when the user says 커밋하고 푸시 / origin/main에 푸시 / 배포해 / ship — 단문 배포 지시 전반. 릴리스 컷 판정은 release 스킬에 위임한다.
---

# /ship — 배포 파이프라인 원커맨드

"커밋", "푸시", "main에 반영" 류 단문 지시를 받았을 때 아래 절차를 한 번에 처리한다.
릴리스 노트 규약·버전 판정의 단일 소스는 스킬 `release` 이며, 이 스킬은 순서만 소유한다.

## 절차

1. **커밋** — 미커밋 변경을 확인하고 `<type>: <description>` 형식으로 커밋한다.
   - 임시/검증용 파일은 커밋 전 `.recycles/` 로 이동 (rm 금지 규칙).
   - 커밋 전 tsc(프론트 변경 시)·pytest(백엔드 로직 변경 시)가 아직 안 돌았다면 여기서 돌린다 — CLAUDE.md 완료 조건.
2. **릴리스 컷 판정** — 마지막 `v*` 태그 이후 커밋에 사용자 체감 타입(feat/fix/perf)이 있으면
   스킬 `release` 절차로 버전 판정(사용자 한 줄 확인) → `backend/app/data/releases/<v>.md` 작성 →
   `docs(release)` 커밋 + 태그. docs/ci/chore/test/refactor 만 있으면 컷 없이 진행.
3. **main 반영** — dev 에서 작업했으면 `git push origin dev && git push origin dev:main`
   (main 이 dev 조상이면 fast-forward). 충돌·발산 시 임의로 force 하지 말고 상태를 보고한다.
4. **태그 푸시** — 릴리스를 컷했다면 `git push origin --tags`.
5. **배포 확인·보고** — 커밋 해시, 푸시된 브랜치, 트리거된 배포(AWS)를 보고한다.

## 푸시 대상 규칙

- **기본 = origin 만** (GitHub → AWS 배포). 사용자가 "origin/main에 푸시"라고 하면 origin 만이다.
- **온프렘(ax 리모트)은 사용자가 명시할 때만** 푸시한다 — ax 는 의도적으로 구버전에 머물러 있을 수 있다
  (2026-08-19 기준 v2.5.1). ax 푸시 전에 `git ls-remote ax refs/heads/main` 으로 현재 위치를 확인하고,
  여러 릴리스를 건너뛰게 되면 마이그레이션 다수 적용을 경고한 뒤 확인받는다.
- "aws만" = origin 만, "온프렘도/양쪽" = origin + ax.

## 전제

- pre-push 훅(`.githooks/pre-push`)이 릴리스 게이트다 — `git config core.hooksPath .githooks` 가
  풀려 있으면 다시 설정한다. 우회는 `SKIP_RELEASE_CHECK=1` (핫픽스 전용).
- main 푸시 = 실배포 트리거다. 사용자 지시 없이 이 스킬을 선제 실행하지 않는다.
