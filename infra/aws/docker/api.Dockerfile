# 빌드 컨텍스트 = 리포 루트.  docker build -f infra/aws/docker/api.Dockerfile .
# Playwright 공식 파이썬 베이스(브라우저·시스템 의존성 포함). 태그 = requirements 의 playwright 버전과 일치.
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

# 한글 폰트(옴니솔 화면 렌더/스크린샷/Gemini 비전) + tini(좀비 회수 보조; ECS init 도 켜둠).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 베이스 이미지에 이미 브라우저 포함. requirements 버전이 베이스와 다르면 아래 주석 해제.
# RUN playwright install chromium

COPY backend/ .

EXPOSE 8000

# ⚠ uvicorn 1 프로세스(멀티 워커 금지 — 인메모리 SSE/세마포어 상태). 태스크 정의에서 command 로도 지정.
# ⚠ 마이그레이션은 배포 시 1회 실행: alembic upgrade head (README 참조).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
