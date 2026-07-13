# 배포 (내부 3서버 + GitLab CI) — 초안

> 원칙: **CI에서 이미지 1회 빌드 → 레지스트리 push → 서버는 pull만.** 서버에서 빌드하지 않는다.
> AWS(`infra/aws/`)는 이번 범위 밖. 여기선 로컬 + 내부 3서버만 다룬다.

## 토폴로지
```
[GitLab CI 러너] ─build→ backend:SHA / frontend:SHA ─push→ [GitLab Container Registry]
                                                              │ pull
  api (172.20.50.50)          front (172.20.50.52)          db (172.20.50.51)
  FastAPI + Chromium          Caddy(프록시) + Next.js        Postgres(볼륨)
  :8010 (내부)               :80/:443 (유일한 public)        :5432 (내부)
  alembic 자동                /api → api50, / → next          앱배포와 분리
```
- 프론트는 `NEXT_PUBLIC_API_BASE=/api` 로 빌드 → Caddy가 `/api`를 api서버로, 나머지를 next로. **same-origin이라 쿠키/CORS 단순.**

## 파일 맵
| 파일 | 용도 |
|---|---|
| `Dockerfile` (루트) | 프론트(Next standalone) |
| `backend/Dockerfile` + `docker-entrypoint.sh` | 백엔드(FastAPI+Chromium), 시작 시 alembic→uvicorn(단일워커) |
| `deploy/db/docker-compose.yml` | Postgres |
| `deploy/api/docker-compose.yml` + `app.env.example` | 백엔드 실행(+런타임 시크릿) |
| `deploy/front/docker-compose.yml` + `Caddyfile` + `.env.example` | 프록시+프론트 |
| `.gitlab-ci.yml` | build→push→deploy |

## 1) 서버 1회 준비
**api(50)·front(52)**: Docker + compose 플러그인 설치.
```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # 재로그인
```
**db(51)**: Docker(위와 동일) — 또는 네이티브 `postgresql` 설치(그 경우 db compose 불필요).

디렉터리 + 시크릿 배치(⚠ 리포 커밋 금지):
```sh
# api(50)
sudo mkdir -p /opt/ninebell/api && cd /opt/ninebell/api
cp .../deploy/api/app.env.example app.env   # 편집: DATABASE_URL·AUTH_SECRET·LOCAL_ADMIN_PASSWORD…
# front(52)
sudo mkdir -p /opt/ninebell/front && cd /opt/ninebell/front
cp .../deploy/front/.env.example .env        # SITE_ADDRESS / API_UPSTREAM
# db(51)
sudo mkdir -p /opt/ninebell/db && cd /opt/ninebell/db
cp .../deploy/db/docker-compose.yml . && cp .../deploy/db/.env.example .env   # POSTGRES_PASSWORD
```
**배포키**: CI가 SSH할 배포 유저의 `~/.ssh/authorized_keys`에 CI 공개키 추가(세 서버 모두). 비번 로그인 말고 키.

**계정 모델**(서버 주인=나인벨, 관리자=외주):
- **`ninebell`** — 서비스/배포 계정. docker 그룹, `/opt/ninebell` 소유, SSH **배포키만**, **sudo 없음**. CI가 이 계정으로 붙는다.
- **`etribe`** — 사람(관리자) 계정. **비번 로그인 + sudo**. docker 그룹·배포키 없음(서버 셋업·점검용).

## 2) GitLab CI/CD 변수 (Settings → CI/CD → Variables)
| 변수 | 값 | 비고 |
|---|---|---|
| `DEPLOY_SSH_KEY` | 배포용 개인키 | masked·protected |
| `DEPLOY_USER` | **`ninebell`** (서비스 계정 — etribe 아님) | |
| `API_HOST`/`DB_HOST`/`FRONT_HOST` | 172.20.50.50/51/52 | |
| `REGISTRY_DEPLOY_USER`/`REGISTRY_DEPLOY_TOKEN` | Deploy Token(scope `read_registry`) | 서버 pull용 |
> `CI_REGISTRY*`(빌드 push용)는 GitLab 자동 제공. ⚠ **채팅에 붙였던 서버 비번은 쓰지 말 것** — SSH 키로.

## 3) 최초 배포 순서
1. **db(51)**: `cd /opt/ninebell/db && docker compose up -d` (한 번). `pg_isready` 확인.
2. **main 에 push** → CI가 이미지 build+push.
3. 파이프라인에서 **deploy:api 수동 실행** → api 서버가 pull + `alembic upgrade head`(entrypoint) + seed(startup) + up.
4. **deploy:frontend 수동 실행** → Caddy+next up. `http://172.20.50.52` 접속.
> 이후 배포는 main push → deploy 버튼만.

## 로컬 개발 (변경 없음)
- 백엔드: `cd backend && .venv/bin/uvicorn app.main:app --port 8010`
- 프론트: `.env.local` 에 `NEXT_PUBLIC_API_BASE=http://localhost:8010` → `npm run dev`
- 프록시/도커 불필요. same-origin이 아니라 백엔드 CORS(`CORS_ORIGINS`)에 `http://localhost:3101` 필요(기본값에 있음).

## 꼭 기억할 것
- **api는 단일 워커**(`--workers 1`) — 로그인 시도제한·HITL 큐가 인메모리. 멀티워커 금지.
- **Chromium**: 컨테이너에서 `CHROMIUM_ARGS=--disable-dev-shm-usage --no-sandbox`(compose에 설정됨) + `shm_size`.
- **HTTPS 켜면** `app.env`의 `COOKIE_SECURE=true`(Caddyfile HTTPS 옵션 참고). HTTP면 false.
- **시크릿은 서버의 `app.env`/`.env`에만.** 이미지·리포·CI 로그에 넣지 말 것(`NEXT_PUBLIC_*` 제외 — 그건 공개 값).
- **캐시 정리**: 빌드 캐시는 CI 몫. 서버는 배포 끝에 `docker image prune -f` 자동(파이프라인에 포함).
- **마이그레이션**: api 컨테이너 시작 시 자동. 다중 인스턴스로 늘리면 별도 잡으로 분리.
