---
name: release
description: >-
  릴리스를 끊는 표준절차 — main 푸시 전에 미등록 커밋을 분류하고, semver 메이저/마이너/패치를
  판정하고, 릴리스 노트 본문을 작성해 backend/app/data/releases/ 에 커밋하고 태그까지 단다.
  Use this WHENEVER the user says 릴리스 끊자 / 릴리스 등록 / 배포 전 정리 / cut a release,
  or when the pre-push hook blocks a main push asking for a release note. 커밋 메시지를
  그대로 옮기지 말 것 — 사용자 언어로 다시 쓰는 것이 이 절차의 핵심이다.
origin: 나인벨 옴니솔 자동화 대시보드 — 릴리스/버전 관리 표준절차 (2026-07)
version: "1.0.0"
---

# 릴리스 끊기 표준절차

릴리스 노트 작성 규약(6섹션·주요 수정 판정·제외 대상)의 단일 소스는
**`docs/CHANGELOG-ENTRY.md`** 다. 이 문서는 그 위에 **버전 결정과 릴리스 커밋 절차**만 얹는다.

## 0. 언제 도는가

`main` 푸시 = AWS(ECS) + 온프렘 동시 배포 = 릴리스 경계다.
`.githooks/pre-push` 가 미등록 커밋을 감지해 푸시를 막으면 이 절차를 돈다.

> 훅 활성화(1회): `git config core.hooksPath .githooks`
> 우회: `SKIP_RELEASE_CHECK=1 git push` — 핫픽스·되돌리기 전용

## 1. 범위 확정

```bash
last_tag=$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || echo "")
git log --no-merges --pretty='%h %s' ${last_tag:+$last_tag..HEAD}
```

태그가 없으면 `backend/app/data/releases/*.md` 의 마지막 `releasedAt` 이후로 잡는다.

## 2. 커밋 분류

`docs/CHANGELOG-ENTRY.md` 의 6섹션에 배치한다.
**제외**: `ci` · `chore` · `style` · `test` · `docs` · `merge` · 순수 `refactor` · 배포 인프라.

`### 주요 수정` 판정 기준(한 문장):

> 이 버그 때문에 ERP에 잘못된 데이터가 들어갔거나, 작업이 실패했는가?

예면 `### 주요 수정` + frontmatter `hasMajorFix: true`. 둘은 항상 함께 간다.

## 3. 버전 결정 (semver `vX.Y.Z`)

**위에서부터 먼저 걸리는 규칙을 적용한다.**

| 올림 | 조건 | 근거 |
| --- | --- | --- |
| **메이저** `X` | ① 사용자 동작·위치·권한이 바뀜(= `### 변경` 섹션이 있음) — 예: 부서 읽기전용화, 계정 피커 제거, 메뉴 이동<br>② **신규 에이전트 추가** — 에이전트가 이 제품의 핵심 단위 | 쓰던 방식이 달라지거나, 할 수 있는 일이 늘어남 |
| **마이너** `Y` | `### 추가` 또는 `### 개선` 이 있음 (동작 변경·신규 에이전트는 없음) | 기능이 늘거나 좋아짐 |
| **패치** `Z` | `### 수정` / `### 주요 수정` / `### 보안·개인정보` 만 있음 | 고치기만 함 |

- 백필 10건은 날짜식(`2026.07.xx`)이며 **소급 변경하지 않는다.** semver 는 `v1.0.0` 부터 시작.
- 메이저를 올리면 `Y`·`Z` 를 0으로, 마이너를 올리면 `Z` 를 0으로 리셋.
- 판정 근거를 사용자에게 **한 줄로 제시하고 확인받은 뒤** 진행한다.
  예: `신규 에이전트(외상매출금) 추가 → 메이저. v1.2.1 → v2.0.0`

## 4. 릴리스 파일 작성

`backend/app/data/releases/<version>.md`:

```markdown
---
version: v2.0.0
title: 외상매출금 전표결재 에이전트 추가
releasedAt: 2026-08-05
hasMajorFix: false
---

### 추가

- **외상매출금** — 전표조회승인 화면에서 전표를 대신 결재합니다.
```

- `status: draft` 를 넣으면 관리자에게만 보인다(검토 중일 때).
- 파일 위치가 `backend/` 아래인 이유: 백엔드 이미지가 `backend/` 만 복사하므로,
  여기 있어야 AWS·온프렘 양쪽에 배포와 함께 따라간다.

### 문장 규칙 (가장 중요)

커밋 메시지를 그대로 옮기지 않는다. **사용자가 겪는 변화**로 다시 쓴다.

| 커밋 | 릴리스 노트 |
| --- | --- |
| `perf(omnisol): 웜 로그인 판정을 아바타 1순위로 + 프로필 패널 폴링 — login 18s→4-6.5s` | **공통** — 로그인 단계 18초 → 4~6.5초 |
| `fix(card-collect): [시도1] 저장(F7) 인라인 검증 토스트 탐지 — 필수값 누락 미저장을 성공으로 오판하던 팬텀 저장 버그` | **법인카드** — 필수값이 비어 저장되지 않았는데 성공으로 표시되던 문제 수정 |

- 항목은 `- **대상** — 설명` 형식. 대상은 UI 표기 그대로(`법인카드`, `외상매출금`, `공통`).
- 내부 용어(`nbkit`, `WorkflowSpec`, `HITL`, 노드 이름)를 노출하지 않는다.

## 5. 반영

```bash
git add backend/app/data/releases/<version>.md
git commit -m "docs(release): <version> 릴리스 노트"
git tag <version>
git push && git push --tags
```

- 시드(`seed_changelog`)가 **없는 버전만** 추가하므로 배포 시 자동 반영된다.
- 화면에서 고친 내용은 재시작이 덮어쓰지 않는다. 파일을 고쳐 반영하려면
  화면에서 해당 릴리스를 지우고 재시작한다.
- 로컬 dev DB 에 바로 넣고 싶으면 백엔드를 재시작하면 된다(시드가 돈다).

## 6. 확인

```bash
cd backend && .venv/bin/pytest tests/test_changelog_seed.py -q
```

`test_shipped_release_files_all_parse` 가 frontmatter 오타·버전 중복을 잡는다.
화면(`/changelog`)에서 배지·정렬을 눈으로 확인하면 끝.
