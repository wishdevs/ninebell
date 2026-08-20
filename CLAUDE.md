# CLAUDE.md

나인벨(NINEBELL) 자동화 대시보드 — 더존 옴니솔(ERP) 반복업무를 헤드리스 브라우저(Playwright)로 대신 처리한다.
프론트 = Next.js 16 App Router(pnpm) `src/`, 백엔드 = FastAPI + SQLAlchemy async + Alembic + LangGraph `backend/`.

## 개발 환경
- PostgreSQL 17 도커 컨테이너 `dashboard-pg` = localhost:5434 (5432/8000 은 다른 프로젝트가 점유)
- 백엔드 uvicorn :8010 — 로컬 개발은 `--reload` 로 띄운다(2026-08-12 전환). `.py` 를 고치면 WatchFiles 가 자동 재기동한다. ⚠ 재기동은 프로세스를 갈아끼우므로 **인메모리 세션·HITL 큐가 날아간다** — 라이브 실행/개입 중에 백엔드 파일을 고치지 말 것<br>  `cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload` (로그: `backend/logs/uvicorn-dev.log`, gitignore)
- 프론트 dev :3101, `NEXT_PUBLIC_API_BASE=http://localhost:8010` (.env.local)
- LLM 키/모델은 `backend/.env` (GEMINI_API_KEY 등, gitignore)
- 로컬 부트스트랩 관리자 = admin/1111 (super_admin, env `LOCAL_ADMIN_PASSWORD` 로 교체)
- 실 옴니솔 테스트 계정 = 이트라이브2/1111 (e2e 프로브 전용)

## 안전 경계
- 실제 전표 저장(F7/BTN_SAVE)은 원칙적으로 미실행 — 폼 채움·적용까지만. 예외는 사용자가 저장 자동화를 명시 승인한 플로우(card_collect 등)뿐이다
- 상신(결재)은 원칙적으로 클릭하지 않는다. 예외는 **회계전표(voucher) 계열 2에이전트**(유형별 전표조회 승인·미지급금카드 — 2026-08-20 외상매출/외상매입을 유형별로 병합)로, 결제창에서 실제 상신까지 실행한다 (2026-08-07 사용자 승인 — `backend/e2e/eap_approval_cancel_probe.py` 로 결재취소→상신취소→임시보관 삭제가 되어 가역이다). 그 외 에이전트는 여전히 상신 금지이며, 보관 버튼은 어느 에이전트도 클릭하지 않는다
- 그 회수 경로는 2026-08-12 부터 에이전트로도 있다 — `eap-approval-cancel`(`backend/app/agents/eap_cancel/`, hidden). 상신문서함 '진행' 목록을 HITL 로 띄우고 **체크한 문서만** 결재취소→상신취소→삭제한다(비가역). 실행 경로는 관리자 + 회계전표 계열 상세의 디버그 버튼뿐이다
- e2e 반복 테스트는 실저장→검증→삭제(F6)→잔존 0 확인 사이클로 한다. 삭제 수단이 없는 화면은 비가역 동사 직전에서 멈춘다

## 플로우 구축 절차
- 새 옴니솔 화면 자동화는 프로젝트 스킬 `omnisol-flow-buildout` 절차로 진행한다 (MD 명세 → 헤드리스 실측 → 스크립트화 → 게이트된 반복 테스트 → LangGraph 통합). 코드부터 짜지 않는다
- 저수준 그리드 함정(캔버스 그리드·숨김 필드·setValue 부작용 등)은 스킬 `erp-headless-grid-automation` 이 소유한다

## 에이전트 구조
- 결의서입력(GLDDOC00300) 계열은 진입 앞단(login→회계 유저타입→메뉴 진입)을 expense_card 노드로 공유하고, 문서 종류별 에이전트(card_collect·trip_domestic·trip_overseas 등)로 분리한다 — `backend/app/agents/RESOLUTIONS.md`
- 회계전표 계열은 `voucher_receivable` 의 `build_voucher_graph(docu_types)` 백본을 공유한다. 2026-08-20 외상매출/외상매입을 **유형별 전표조회 승인(voucher-by-type)** 하나로 병합 — 전표유형(국내매출 21·해외매출 23·내수구매 31, ERP 매칭은 SYSDEF_NM 한글 라벨)은 실행 전 폼의 다중선택이고, 메뉴(MENU_NM) 필터(항목 목록은 agents.settings.menu_items, 관리자 추가/삭제)로 대상을 추린다. 미지급금 법인카드(voucher-card, 일반 11)는 별도 유지
- 새 워크플로우는 `registry.register_workflow(agent_id, graph_factory)` 로 등록하고 agents.workflow_id 가 프론트 실행 진입점과 연결한다

## 배포
- main 푸시는 두 배포를 동시에 트리거한다: GitHub Actions → AWS ECR/ECS (ninebell.hynro.com) + GitLab `ax` 리모트 → 온프렘 (nb.hynro.com)
- 마이그레이션은 **양쪽 다 기동 시 자동**이다 — `backend/docker-entrypoint.sh` 가 `alembic upgrade head` 후 CMD 를 exec 하고, 온프렘·AWS 두 이미지가 이 스크립트를 공유한다(2026-07-29 `bab95a1` 로 비대칭 해소, 2026-08-11 v2.1.0 배포에서 0031·0033·0034 자동 적용 확인). 배포 시 사람이 할 일은 없다
- ⚠ 옛 절차였던 `alembic stamp` 는 **돌리지 말 것** — `DEV_CREATE_ALL=1`(현재 0) 로 테이블만 만들어져 `alembic_version` 이 비었던 초기 부트스트랩 1회용이다. 지금 stamp 하면 리비전이 어긋나 마이그레이션이 건너뛰어진다
- 실패하면 앱이 뜨지 않고 ECS 재시작 루프가 된다(`set -e`) — CloudWatch `/ecs/ninebell-dashboard-test/api` 에서 alembic 로그를 먼저 본다 (AWS CLI 프로파일 `ax-prod`, 클러스터 ninebell-dashboard-test)
- api 는 인메모리 세션·HITL 큐 때문에 `desired_count=1` 고정이다 — 늘리면 마이그레이션 동시 실행 경합이 생기므로, 수평 확장 시 마이그레이션을 배포 파이프라인의 별도 잡으로 빼야 한다
- 루트 `.dockerignore` 는 backend/ 를 제외하므로 AWS api 빌드는 `infra/aws/docker/api.Dockerfile.dockerignore` 로 우회한다 — 지우지 말 것

## 커밋 후 절차
- 의미 있는 작업을 커밋한 뒤에는 `POST /changelog` 로 릴리스 노트를 등록한다 — 화면 폼이 아니라 API 가 정해진 작성 경로다 (`docs/CHANGELOG-ENTRY.md`)
- main 푸시 전 릴리스 컷은 스킬 `release` 절차를 따른다

## 테스트 관례
- 백엔드 로직 변경은 `backend/tests/` pytest 를 동반한다 — 노드/스텝은 페이지·LLM 을 fake 로 주입해 단위 검증
- `backend/e2e/` 프로브 스크립트는 실 ERP 대상 검증 도구라 pytest 대상이 아니다. 단, 에이전트의 파라미터 계약이 바뀌면 해당 e2e 하네스도 함께 갱신한다

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
