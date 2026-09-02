"""FastAPI 앱 + lifespan.

lifespan: async 엔진 초기화 → (DEV_CREATE_ALL 이면) Base.metadata.create_all →
멱등 seed 실행 → Playwright 브라우저 기동 + 동시 로그인 세마포어 → CredCache + reaper.
CORS 는 프론트 dev(http://localhost:3101) 허용 + credentials(쿠키) 허용.

`import app.main` 은 lifespan 을 실행하지 않으므로 DB/브라우저 없이도 임포트가 성공한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.agents  # noqa: F401 — import 시 실 워크플로우(expense-card-chat)를 registry 에 등록
from app.config import get_settings
from app.core.assistant_ratelimit import AssistantRateLimiter
from app.core.http_client import new_async_client
from app.core.logging_setup import configure_logging
from app.core.ratelimit import LoginRateLimiter
from app.core.request_log import HttpRequestLogMiddleware
from app.db import dispose_engine, get_engine, get_sessionmaker, init_engine
from app.erp.credcache import CredCache
from app.live.session import close_all_sessions, reap_sessions
from app.models import Base
from app.routers import (
    agents,
    assistant,
    auth,
    changelog,
    dev_llm,
    erp_sync,
    logs,
    me_codes,
    org_units,
    purchase_order_plans,
    runs,
    skills,
    users,
)
from app.services.catalog_sync_scheduler import run_daily_catalog_sync
from app.services.erp_sync import reconcile_stale_runs
from app.services.seed import seed_all
from app.services.signup_cache import SignupCache

logger = logging.getLogger("app.main")


def _detect_worker_count(argv: list[str] | None = None, env: dict | None = None) -> int | None:
    """uvicorn 워커 수 탐지 — --workers/-w CLI 인자와 WEB_CONCURRENCY env. 미지정이면 None."""
    args = sys.argv if argv is None else argv
    environ = os.environ if env is None else env
    for i, a in enumerate(args):
        if a in ("--workers", "-w") and i + 1 < len(args):
            candidate = args[i + 1]
        elif a.startswith("--workers="):
            candidate = a.split("=", 1)[1]
        else:
            continue
        try:
            return int(candidate)
        except ValueError:
            continue
    raw = environ.get("WEB_CONCURRENCY", "")
    if raw.strip():
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _ensure_single_worker() -> None:
    """다중 워커 기동 거부 — 인메모리 상태(CredCache·HITL 큐·세션 레지스트리·시도제한 등)가
    단일 워커 전제라, 워커가 갈라지면 로그인 세션·SSE 재연결·세마포어가 워커별로 찢어져
    조용히 오동작한다. docker-entrypoint.sh 주석만으로는 강제되지 않아 부팅 시점에 막는다."""
    n = _detect_worker_count()
    if n is not None and n > 1:
        raise RuntimeError(
            f"workers={n} 로 기동할 수 없습니다 — 이 앱은 인메모리 상태(CredCache/HITL/"
            "라이브 세션/로그인 시도제한) 때문에 단일 워커 전용입니다. --workers 1 로 "
            "실행하거나 WEB_CONCURRENCY 를 제거하세요."
        )


def create_app() -> FastAPI:
    settings = get_settings()
    # ⚠ 앱 로거 부트스트랩 — uvicorn 은 root 에 핸들러를 달지 않아 이걸 빼면 app.* 의 INFO 가
    #   전부 유실된다(HTTP 요청 로그 포함). 라우터 등록보다 먼저 세운다.
    configure_logging(settings.log_level, settings.log_file)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- 다중 워커 기동 가드(인메모리 상태 단일 워커 전제) ---
        _ensure_single_worker()

        # --- DB ---
        init_engine(settings.database_url)
        if settings.dev_create_all:
            async with get_engine().begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.warning("DEV_CREATE_ALL=1 — Base.metadata.create_all 로 테이블 생성(개발용).")

        async with get_sessionmaker()() as session:
            await seed_all(session)
            await session.commit()
        # 재기동으로 태스크가 사라진 ERP 동기화 이력(running)을 failed 로 닫는다.
        await reconcile_stale_runs(get_sessionmaker())

        # --- 공용 httpx 클라이언트(AI 어시스턴트 Gemini 스트리밍) ---
        # read=None: SSE 스트림이 장시간 idle 이어도 읽기 타임아웃으로 끊기지 않게 한다.
        app.state.http = new_async_client(timeout=httpx.Timeout(30.0, read=None))

        # --- 더존 헤드리스 브라우저 + 동시 로그인 상한 ---
        # 컨테이너/Fargate 는 CHROMIUM_ARGS="--disable-dev-shm-usage --no-sandbox" 로 크래시 방지(env).
        _chromium_args = [a for a in settings.chromium_args.split() if a]
        pw = await async_playwright().start()
        app.state.playwright = pw
        app.state.erp_browser = await pw.chromium.launch(
            headless=settings.erp_headless, args=_chromium_args
        )
        # 로그인/실행 세마포어 분리 — 장기 실행이 짧은 로그인을 막지 않도록 격리(P3-5).
        app.state.login_semaphore = asyncio.Semaphore(settings.max_concurrent_erp_logins)
        app.state.run_semaphore = asyncio.Semaphore(settings.max_concurrent_erp_runs)

        # --- 라이브 실행(run): run 당 fresh 헤드리스 브라우저 팩토리 + 세션 리퍼 ---
        # 라우터(runs.py)가 이 팩토리로 run 당 새 브라우저를 열고 finally 에서 닫는다.
        async def _launch_browser():
            return await pw.chromium.launch(headless=settings.erp_headless, args=_chromium_args)

        app.state.browser_factory = _launch_browser
        session_reaper = asyncio.create_task(reap_sessions())
        # --- 일일 무인 코드 카탈로그 동기화(설정 시에만 실제 루프가 돈다) ---
        catalog_scheduler = asyncio.create_task(run_daily_catalog_sync(app))

        # --- 로그인 시도 제한(인메모리) ---
        app.state.login_limiter = LoginRateLimiter(
            max_attempts=settings.login_max_attempts,
            window_s=settings.login_window_s,
            ip_max_attempts=settings.login_ip_max_attempts,
            lockout_base_s=settings.login_lockout_base_s,
            lockout_max_s=settings.login_lockout_max_s,
        )

        # --- 자격증명 캐시 + 회원가입 대기 캐시 + 주기 reaper ---
        app.state.cred_cache = CredCache()
        app.state.signup_cache = SignupCache()
        cred_reaper = asyncio.create_task(app.state.cred_cache.reaper())
        signup_reaper = asyncio.create_task(app.state.signup_cache.reaper())

        if not settings.cookie_secure:
            logger.warning(
                "COOKIE_SECURE=false — 세션 쿠키가 평문 HTTP 로 전송됩니다. "
                "프로덕션(HTTPS)에서는 COOKIE_SECURE=true 로 설정하세요."
            )

        try:
            yield
        finally:
            session_reaper.cancel()
            catalog_scheduler.cancel()
            cred_reaper.cancel()
            signup_reaper.cancel()
            await close_all_sessions()  # 살아있는 라이브 세션의 브라우저까지 정리
            await app.state.http.aclose()
            try:
                await app.state.erp_browser.close()
            finally:
                await pw.stop()
                await dispose_engine()

    app = FastAPI(title="더존 옴니솔 대시보드 API", lifespan=lifespan)
    # 동기·순수 인메모리라 lifespan 을 타지 않는 컨텍스트(테스트 등)에서도 필요 — 즉시 생성.
    app.state.assistant_limiter = AssistantRateLimiter()
    # 코드 카탈로그 동기화: 1슬롯 세마포어(동시 1건) + kind 별 진행/결과 상태.
    app.state.catalog_sync_semaphore = asyncio.Semaphore(1)
    app.state.catalog_sync_state = {}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # CORS **뒤에** 등록해 가장 바깥에 놓는다(Starlette 은 나중에 등록한 것이 바깥) — CORS 가
    # 선처리하는 preflight(OPTIONS)와 CORS 단계의 예외까지 빠짐없이 남기기 위함이다.
    app.add_middleware(HttpRequestLogMiddleware)

    # 에러 응답 dual-key: HTTPException(detail) 47곳 vs JSONResponse(error) 16곳 혼재를
    # 라우터 무수정으로 통일한다 — 핸들러가 detail·error 를 병기(리스트 dual-key 이행 선례와
    # 동일 방식). FE 전환 완료 후 별도 커밋에서 한 키로 수렴 예정. headers(Retry-After 등) 보존.
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_dual_key(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            {"detail": exc.detail, "error": exc.detail},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    # 422(경계 검증 실패) 표면화 — 사유를 서버 로그에 남기고(요청 로그는 body 를 자르므로 어느
    # 필드가 왜 튕겼는지 안 보인다: 2026-08-28 계획서 제출 422 사고), 응답에도 읽을 수 있는
    # error 요약을 병기한다(detail 은 FastAPI 기본 [{loc,msg,input}] 그대로).
    @app.exception_handler(RequestValidationError)
    async def _validation_error_surface(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        lines = [
            f"{'.'.join(str(x) for x in e.get('loc', ()) if x != 'body')}: {e.get('msg', '')}"
            for e in errors[:5]
        ]
        summary = "요청 형식 오류 — " + " / ".join(lines) if lines else "요청 형식 오류"
        logger.warning(
            "422 %s %s — %s%s",
            request.method,
            request.url.path,
            "; ".join(lines),
            f" (input={str(errors[0].get('input'))[:200]!r})" if errors else "",
        )
        # ⚠ pydantic v2 의 errors[].ctx 에는 ValueError 객체가 들어올 수 있다(EmailStr 등) —
        #   그대로 직렬화하면 422 응답 자체가 TypeError 로 터진다(2026-08-31 pytest 실측 2건).
        safe_errors = jsonable_encoder(errors, custom_encoder={Exception: str})
        return JSONResponse({"detail": safe_errors, "error": summary}, status_code=422)

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(agents.router)
    app.include_router(org_units.router)
    app.include_router(logs.router)
    app.include_router(runs.router)
    app.include_router(assistant.router)
    app.include_router(me_codes.router)
    app.include_router(erp_sync.router)
    app.include_router(skills.router)
    app.include_router(changelog.router)
    app.include_router(purchase_order_plans.router)
    app.include_router(purchase_order_plans.resume_router)
    # 로컬 dev 전용 게이트 라우터 — LLM_PROVIDER_TOGGLE off(기본)면 전 엔드포인트 404.
    app.include_router(dev_llm.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
