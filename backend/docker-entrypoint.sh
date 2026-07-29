#!/bin/sh
set -e

# 1) 스키마 마이그레이션 — 앱 시작 전 1회. 실패하면 set -e 로 여기서 멈춘다.
#    ⚠ 단일 인스턴스 전제. api 를 다중 레플리카로 늘리면 이 스텝을 배포 파이프라인의
#    별도 잡(docker compose run --rm api alembic upgrade head)으로 빼서 경합을 막을 것.
alembic upgrade head

# 2) 앱 시작 — 실행 명령은 **CMD/런타임 인자**에서 받는다(하드코딩하지 않는다).
#    ⚠ 2026-07-29 장애: AWS 이미지(infra/aws/docker/api.Dockerfile)는 이 스크립트를 안 쓰고
#      CMD 로 uvicorn 을 직접 띄워 **마이그레이션이 통째로 빠져 있었다**. changelog_entries
#      미생성 상태로 부팅 → 'relation does not exist' 로 startup 실패 → ECS 재시작 루프.
#      온프렘만 자동이고 AWS 만 수동인 비대칭이 원인이라, 양쪽이 이 스크립트를 공유하게 바꿨다.
#      포트가 서로 달라(온프렘 8010 / AWS 8000) 실행 명령은 각 Dockerfile 의 CMD 가 정한다.
#      ECS 태스크 정의의 command 오버라이드도 그대로 "$@" 로 들어와 마이그레이션 뒤에 실행된다.
#    ⚠ --workers 1 필수: 로그인 시도제한·HITL 큐가 인메모리(단일 워커 전제)라 멀티워커면 상태가 갈라진다.
exec "$@"
