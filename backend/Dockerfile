# syntax=docker/dockerfile:1
# 백엔드(FastAPI + Playwright 헤드리스 Chromium). 빌드는 CI에서 1회, 서버는 pull 만.
# 빌드 컨텍스트 = backend/  (CI: docker build -f backend/Dockerfile backend)
# ⚠ bookworm(Debian 12) 고정 — python:3.13-slim 의 기본이 trixie(Debian 13)로 올라갔는데
#    playwright 1.49 는 trixie 를 모른다 → 'ubuntu20.04 fallback' 으로 우분투 전용 폰트 패키지
#    (ttf-ubuntu-font-family·ttf-unifont)를 apt 설치하려다 실패한다. bookworm 은 playwright 가
#    인식해 올바른 Debian 의존성을 깐다. (playwright 업그레이드로 trixie 지원되면 재검토.)
FROM python:3.13-slim-bookworm

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
# 마이그레이션(alembic) → CMD 실행. 상세는 docker-entrypoint.sh 참고.
# 실행 명령을 CMD 로 분리한 이유: AWS 이미지와 스크립트를 공유하되 포트만 각자 정하기 위함
# (온프렘 8010 / AWS 8000). 엔트리포인트가 마이그레이션 후 이 CMD 를 exec 한다.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
