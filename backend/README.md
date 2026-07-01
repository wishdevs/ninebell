# 더존 옴니솔 대시보드 — 백엔드 (FastAPI)

Python 3.13 · FastAPI · SQLAlchemy 2.0 async + asyncpg · Alembic · Playwright · PyJWT.

로그인 = 더존 옴니솔(`erp.ninebell.co.kr`) 헤드리스 검증. 로컬 비밀번호 저장 없음.
세션은 httpOnly 쿠키(`session`, JWT HS256). RBAC: super_admin / admin / user.

## 설정

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium   # 실제 더존 로그인에 필요(최초 1회)
cp .env.example .env                     # 값 채우기 (AUTH_SECRET, DATABASE_URL, SUPER_ADMIN_OMNISOL_IDS 등)
```

## DB 마이그레이션 + 기동

```bash
# PostgreSQL 준비 후:
.venv/bin/alembic upgrade head           # 스키마 생성
.venv/bin/uvicorn app.main:app --port 8000   # startup 에서 seed 자동 실행

# DB/Alembic 없이 빠른 개발:
DEV_CREATE_ALL=1 .venv/bin/uvicorn app.main:app --port 8000
```

## 테스트

```bash
.venv/bin/pytest -q   # 실제 브라우저/Postgres 불필요 (SQLite + authenticate 모킹)
```

## 환경변수

`.env.example` 참조. 핵심:
`DATABASE_URL`(postgresql+asyncpg://...), `AUTH_SECRET`, `SESSION_TTL_HOURS`,
`ERP_BASE`, `MAX_CONCURRENT_ERP_LOGINS`, `SUPER_ADMIN_OMNISOL_IDS`(쉼표 구분),
`COOKIE_SECURE`(프로덕션 true), `CORS_ORIGINS`(기본 http://localhost:3101), `DEV_CREATE_ALL`.

## API

`POST /auth/login` · `POST /auth/logout` · `GET /auth/me`
`GET /users` · `PATCH /users/{id}/role` · `PATCH /users/{id}` · `DELETE /users/{id}`
`GET /agents` · `GET /agents/{id}` · `GET /logs` · `GET /health`

권한 모델 상세는 `docs/PERMISSIONS.md`(permission-doc 팀 산출물) 참조.
