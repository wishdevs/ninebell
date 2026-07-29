# 빌드 컨텍스트 = 리포 루트.  docker build -f infra/aws/docker/api.Dockerfile .
# Playwright 공식 파이썬 베이스(브라우저·시스템 의존성 포함). 태그 = requirements 의 playwright 버전과 일치.
# ⚠ noble(Ubuntu 24.04) = Python 3.12 — 앱이 datetime.UTC(3.11+) 등 3.11+ 기능을 씀(jammy 3.10 은 크래시).
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

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
# git 상의 모드가 644 라 컨테이너에서 직접 실행하려면 실행권한을 준다(온프렘 Dockerfile 과 동일).
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# ⚠ 2026-07-29 장애 대응: 종전에는 CMD 로 uvicorn 을 직접 띄워 **마이그레이션이 빠져 있었다**.
#   changelog_entries 미생성 상태로 부팅해 'relation does not exist' → startup 실패 → ECS
#   재시작 루프 → services-stable 타임아웃. 온프렘은 엔트리포인트가 alembic 을 돌리는데 AWS 만
#   수동이던 비대칭이 원인이라, 같은 스크립트를 공유해 **항상 자동 실행**되게 한다.
#   ECS 태스크 정의(ecs.tf)의 command 오버라이드는 "$@" 로 전달돼 마이그레이션 뒤에 실행된다.
# ⚠ uvicorn 1 프로세스(멀티 워커 금지 — 인메모리 SSE/세마포어 상태).
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
