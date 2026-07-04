# NINEBELL — 더존 옴니솔 자동화 대시보드

나인벨의 더존 옴니솔(`erp.ninebell.co.kr`) 업무를 **브라우저 자동화 에이전트**로 대행하는 풀스택 대시보드입니다.
사용자는 웹에서 에이전트를 실행하고, 필요한 순간에만 개입(HITL)하며, 헤드리스 브라우저가 실제 ERP 화면을 조작해 결의서 등을 처리합니다.

> 초기에는 프론트 디자인 골격(더미데이터)으로 시작했으나, 현재는 **FastAPI 백엔드 + LangGraph 에이전트 + Playwright ERP 자동화 + 인증/RBAC**를 갖춘 실동작 시스템입니다.

## 아키텍처

```
브라우저(Next.js)  ──SSE──▶  FastAPI  ──▶  LangGraph 그래프(에이전트)
      ▲  개입(HITL)              │              │
      └──── /runs/hitl ──────────┘              ▼
                                        Playwright(헤드리스 Chromium)
                                                │
                                                ▼
                                      더존 옴니솔(erp.ninebell.co.kr)
```

- **인증**: 로그인 = 더존 옴니솔 헤드리스 검증(로컬 비밀번호 저장 없음). 세션은 httpOnly 쿠키(JWT HS256).
- **RBAC**: super_admin / admin / user. 조직구분(팀) 단위로 에이전트 접근을 제어.
- **에이전트 실행**: `/runs/collect` 가 LangGraph 그래프를 라이브 세션으로 구동하고 단계·로그·개입을 **SSE**로 스트리밍. 연결이 끊겨도 서버 세션은 유지되어 재접속 시 커서 이후만 재생.
- **HITL(사용자 개입)**: 그리드/대화/선택 3종. 그래프 노드가 프레임을 방출하면 사용자가 응답할 때까지 대기.
- **AI 보조**: Gemini 로 그리드 행별 예산단위·프로젝트 추천(신뢰도 임계값 이상만 자동 프리필).

## 기술 스택

**프론트엔드** — Next.js 16(App Router) · React 19 · Tailwind CSS v4 · Radix UI · recharts · next-themes.
폰트: Pretendard(한글) + Geist(영문/숫자).

**백엔드** — Python 3.13 · FastAPI · SQLAlchemy 2.0 async(asyncpg) · Alembic · **LangGraph** · **Playwright**(Chromium) · PyJWT · PostgreSQL.

## 빠른 시작

로컬 규약 포트: 프론트 **:3101** · 백엔드 **:8010** · Postgres **:5434**(도커).

### 1) Postgres (도커)

```bash
docker run -d --name dashboard-pg -p 5434:5432 \
  -e POSTGRES_USER=dashboard -e POSTGRES_PASSWORD=dashboard -e POSTGRES_DB=dashboard postgres:16
```

### 2) 백엔드

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium        # 실제 옴니솔 로그인에 필요(최초 1회)
cp .env.example .env                          # AUTH_SECRET, DATABASE_URL, SUPER_ADMIN_OMNISOL_IDS 등
.venv/bin/alembic upgrade head                # 스키마 + 시드
.venv/bin/uvicorn app.main:app --port 8010    # startup 에서 seed 자동 실행
```

빠른 개발(마이그레이션 없이): `DEV_CREATE_ALL=1 .venv/bin/uvicorn app.main:app --port 8010`.
로컬 시스템 관리자: `admin` / `1111`(env `LOCAL_ADMIN_PASSWORD` 로 재정의, 프로덕션 필수).

### 3) 프론트엔드

```bash
pnpm install
pnpm dev -p 3101      # http://localhost:3101 (백엔드 CORS 기본 오리진)
pnpm build            # 프로덕션 빌드 검증
pnpm tsc              # 타입 체크
```

백엔드 주소는 `.env.local` 의 `NEXT_PUBLIC_API_BASE`(기본 `http://localhost:8010`).

## 주요 기능

| 화면 | 설명 |
|------|------|
| `/agents`, `/agents/[id]` | 에이전트 목록·상세 + **라이브 실행**(단계 타임라인·로그·개입 패널·라이브 브라우저 화면) |
| `/assistant` | LLM 대화형 어시스턴트(스트리밍, 레이트리밋) |
| `/organizations` | 조직구분 2뎁스(본부▸팀) 관리 + 비용구분(판관비/제조원가) + 에이전트 접근 제어 |
| `/members` | 멤버 관리 · 팀(조직구분) 배정 |
| `/manage/budget-units`, `/manage/projects` | 예산단위·프로젝트 관리(개인 즐겨찾기·기본지정·ERP 카탈로그 동기화) |
| `/account` | 내 정보·개인 코드 즐겨찾기 |
| `/audit`, `/logs` | 감사·실행 로그(페이지네이션) |
| `/analytics`, `/`, `/design-system` | 애널리틱스 · 홈 · 디자인 토큰 레퍼런스 |

### 대표 에이전트 — `card-collect`(결의서 입력 - 카드)

법인카드 승인내역을 조회해 건별 그리드로 예산단위·프로젝트·적요를 입력받고, **부가세구분에 따라 2패스**로 반영한 뒤 마지막에 한 번 저장(F7)한다.

```
login → user_type(회계) → menu_nav → set_gubun(카드) → add_row → open_evdn → select_evdn
→ select_all_cards → set_period → query → collect_rows(그리드 개입) → apply_doc(과세분 적용)
→ switch_evdn(불공 전환·F3) → apply_pass2(불공분 적용) → save_final(저장 F7)
```

- 승인취소(음수) 행은 원 승인과 **동일 계정** 필수 → 승인번호별로 묶어 같은 예산단위 부여.
- 소속 팀의 **비용구분** → 예산계정 `(판)`/`(제)` 접두사를 우선 선택.

## 프로젝트 구조

```
├── src/                         # Next.js 프론트엔드
│   ├── app/(app)/               # 대시보드 셸 + 앱 페이지(라우트별 _components)
│   ├── app/(auth)/              # 로그인
│   ├── components/{ui,shell,live}/   # 디자인 프리미티브 · 셸 · 라이브 실행 카드
│   └── lib/{api,live,data}/      # API 클라이언트 · 라이브 런 훅(SSE/HITL) · 타입·픽스처
├── backend/
│   ├── app/
│   │   ├── agents/              # LangGraph 워크플로우(card_collect, expense_card, common 노드)
│   │   ├── live/               # 세션·HITL·러너·워크플로우 레지스트리
│   │   ├── routers/            # auth·agents·runs·org_units·users·me_codes·assistant·logs
│   │   ├── models/·services/·llm/·erp/·core/
│   │   └── main.py             # 앱 조립 + startup 시드
│   ├── nbkit/omnisol/          # 옴니솔 특화 셀렉터·JS·플로우 단일 소스
│   └── alembic/versions/       # 마이그레이션
└── docs/                        # PERMISSIONS.md · REVIEW-langgraph-hitl.md
```

## 테스트

```bash
cd backend && .venv/bin/pytest -q    # 실브라우저/Postgres 불필요(SQLite + 인증 모킹)
pnpm tsc && pnpm build               # 프론트 타입·빌드 검증
```

## 문서

- [backend/README.md](backend/README.md) — 백엔드 설정·환경변수·마이그레이션
- [docs/PERMISSIONS.md](docs/PERMISSIONS.md) — RBAC 권한 모델
- [docs/REVIEW-langgraph-hitl.md](docs/REVIEW-langgraph-hitl.md) — LangGraph/HITL 설계 리뷰
- [backend/app/agents/card_collect/PROCESS.md](backend/app/agents/card_collect/PROCESS.md) — card-collect 실측 플로우
- [backend/e2e/README.md](backend/e2e/README.md) — E2E 스모크(에이전트 실행→저장 확인→ERP 삭제)
