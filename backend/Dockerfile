# syntax=docker/dockerfile:1
# 백엔드(FastAPI + Playwright 헤드리스 Chromium). 빌드는 CI에서 1회, 서버는 pull 만.
# 빌드 컨텍스트 = backend/  (CI: docker build -f backend/Dockerfile backend)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1) 파이썬 의존성 — requirements 먼저 복사해 레이어 캐시(코드만 바뀌면 재설치 스킵)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 2) ⚠ 이 백엔드는 더존 옴니솔을 헤드리스 Chromium(Playwright 1.49.1)으로 조작한다.
#    브라우저 바이너리 + OS 의존성 설치. /ms-playwright 에 두어 비루트 유저도 접근 가능.
RUN playwright install --with-deps chromium

# 3) 앱 소스
COPY . .
RUN chmod +x docker-entrypoint.sh \
    && useradd -m app && chown -R app:app /app /ms-playwright
USER app

EXPOSE 8010
# 마이그레이션(alembic) → uvicorn(단일 워커). 상세는 docker-entrypoint.sh 참고.
ENTRYPOINT ["./docker-entrypoint.sh"]
