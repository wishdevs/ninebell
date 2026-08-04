# CLAUDE.md

나인벨(NINEBELL) 자동화 대시보드 — 더존 옴니솔(ERP) 반복업무를 헤드리스 브라우저(Playwright)로 대신 처리한다.
프론트 = Next.js 16 App Router(pnpm) `src/`, 백엔드 = FastAPI + SQLAlchemy async + Alembic + LangGraph `backend/`.

## 개발 환경
- PostgreSQL 17 도커 컨테이너 `dashboard-pg` = localhost:5434 (5432/8000 은 다른 프로젝트가 점유)
- 백엔드 uvicorn :8010 — `--reload` 아님. 백엔드 코드를 고치면 재기동해야 반영된다
- 프론트 dev :3101, `NEXT_PUBLIC_API_BASE=http://localhost:8010` (.env.local)
- LLM 키/모델은 `backend/.env` (GEMINI_API_KEY 등, gitignore)
- 로컬 부트스트랩 관리자 = admin/1111 (super_admin, env `LOCAL_ADMIN_PASSWORD` 로 교체)
- 실 옴니솔 테스트 계정 = 이트라이브2/1111 (e2e 프로브 전용)

## 안전 경계
- 실제 전표 저장(F7/BTN_SAVE)은 원칙적으로 미실행 — 폼 채움·적용까지만. 예외는 사용자가 저장 자동화를 명시 승인한 플로우(card_collect 등)뿐이다
- 상신(결재)은 어떤 경우에도 클릭하지 않는다. 회계전표(voucher) 계열은 가상 상신 로그만 남긴다
- e2e 반복 테스트는 실저장→검증→삭제(F6)→잔존 0 확인 사이클로 한다. 삭제 수단이 없는 화면은 비가역 동사 직전에서 멈춘다

## 플로우 구축 절차
- 새 옴니솔 화면 자동화는 프로젝트 스킬 `omnisol-flow-buildout` 절차로 진행한다 (MD 명세 → 헤드리스 실측 → 스크립트화 → 게이트된 반복 테스트 → LangGraph 통합). 코드부터 짜지 않는다
- 저수준 그리드 함정(캔버스 그리드·숨김 필드·setValue 부작용 등)은 스킬 `erp-headless-grid-automation` 이 소유한다

## 에이전트 구조
- 결의서입력(GLDDOC00300) 계열은 진입 앞단(login→회계 유저타입→메뉴 진입)을 expense_card 노드로 공유하고, 문서 종류별 에이전트(card_collect·trip_domestic·trip_overseas 등)로 분리한다 — `backend/app/agents/RESOLUTIONS.md`
- 회계전표 3종(외상매출/외상매입/미지급금카드)은 `voucher_receivable` 의 `build_voucher_graph(docu_types)` 백본을 공유하며 전표유형(SYSDEF_CD)만 다르다: 외상매출 = 국내매출 21 + 해외매출 23, 외상매입 = 내수구매 31, 미지급금 법인카드 = 일반 11
- 새 워크플로우는 `registry.register_workflow(agent_id, graph_factory)` 로 등록하고 agents.workflow_id 가 프론트 실행 진입점과 연결한다

## 배포
- main 푸시는 두 배포를 동시에 트리거한다: GitHub Actions → AWS ECR/ECS (ninebell.hynro.com) + GitLab `ax` 리모트 → 온프렘 (nb.hynro.com)
- 온프렘은 기동 시 alembic upgrade 자동, AWS 는 마이그레이션 수동 — 신규 마이그레이션이 있으면 서비스와 같은 VPC 에서 일회성 ECS 태스크로 `alembic stamp <현재 스키마 rev>` 후 `alembic upgrade head` 를 돌려야 앱 크래시를 막는다 (AWS CLI 프로파일 `ax-prod`, 클러스터 ninebell-dashboard-test)
- 루트 `.dockerignore` 는 backend/ 를 제외하므로 AWS api 빌드는 `infra/aws/docker/api.Dockerfile.dockerignore` 로 우회한다 — 지우지 말 것

## 커밋 후 절차
- 의미 있는 작업을 커밋한 뒤에는 `POST /changelog` 로 릴리스 노트를 등록한다 — 화면 폼이 아니라 API 가 정해진 작성 경로다 (`docs/CHANGELOG-ENTRY.md`)
- main 푸시 전 릴리스 컷은 스킬 `release` 절차를 따른다

## 테스트 관례
- 백엔드 로직 변경은 `backend/tests/` pytest 를 동반한다 — 노드/스텝은 페이지·LLM 을 fake 로 주입해 단위 검증
- `backend/e2e/` 프로브 스크립트는 실 ERP 대상 검증 도구라 pytest 대상이 아니다. 단, 에이전트의 파라미터 계약이 바뀌면 해당 e2e 하네스도 함께 갱신한다
