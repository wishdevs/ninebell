#!/bin/sh
set -e

# 1) 스키마 마이그레이션 — 앱 시작 전 1회.
#    ⚠ 단일 인스턴스 전제. api 를 다중 레플리카로 늘리면 이 스텝을 배포 파이프라인의
#    별도 잡(docker compose run --rm api alembic upgrade head)으로 빼서 경합을 막을 것.
alembic upgrade head

# 2) 앱 시작. lifespan 에서 seed(권한·롤·admin·카드 시드)가 멱등 실행된다.
#    ⚠ --workers 1 필수: 로그인 시도제한·HITL 큐가 인메모리(단일 워커 전제)라 멀티워커면 상태가 갈라진다.
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 --workers 1
