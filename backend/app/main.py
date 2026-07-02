"""FastAPI 앱 + lifespan.

lifespan: async 엔진 초기화 → (DEV_CREATE_ALL 이면) Base.metadata.create_all →
멱등 seed 실행 → Playwright 브라우저 기동 + 동시 로그인 세마포어 → CredCache + reaper.
CORS 는 프론트 dev(http://localhost:3101) 허용 + credentials(쿠키) 허용.

`import app.main` 은 lifespan 을 실행하지 않으므로 DB/브라우저 없이도 임포트가 성공한다.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

import app.agents  # noqa: F401 — import 시 실 워크플로우(expense-card-chat)를 registry 에 등록
from app.config import get_settings
from app.core.ratelimit import LoginRateLimiter
from app.db import dispose_engine, get_engine, get_sessionmaker, init_engine
from app.erp.credcache import CredCache
from app.live.session import close_all_sessions, reap_sessions
from app.models import Base
from app.routers import agents, auth, logs, org_units, runs, users
from app.services.seed import seed_all
from app.services.signup_cache import SignupCache

logger = logging.getLogger("app.main")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- DB ---
        init_engine(settings.database_url)
        if settings.dev_create_all:
            async with get_engine().begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.warning("DEV_CREATE_ALL=1 — Base.metadata.create_all 로 테이블 생성(개발용).")

        async with get_sessionmaker()() as session:
            await seed_all(session)
            await session.commit()

        # --- 더존 헤드리스 브라우저 + 동시 로그인 상한 ---
        pw = await async_playwright().start()
        app.state.playwright = pw
        app.state.erp_browser = await pw.chromium.launch(headless=True)
        # 로그인/실행 세마포어 분리 — 장기 실행이 짧은 로그인을 막지 않도록 격리(P3-5).
        app.state.login_semaphore = asyncio.Semaphore(settings.max_concurrent_erp_logins)
        app.state.run_semaphore = asyncio.Semaphore(settings.max_concurrent_erp_runs)

        # --- 라이브 실행(run): run 당 fresh 헤드리스 브라우저 팩토리 + 세션 리퍼 ---
        # 라우터(runs.py)가 이 팩토리로 run 당 새 브라우저를 열고 finally 에서 닫는다.
        async def _launch_browser():
            return await pw.chromium.launch(headless=True)

        app.state.browser_factory = _launch_browser
        session_reaper = asyncio.create_task(reap_sessions())

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
            cred_reaper.cancel()
            signup_reaper.cancel()
            await close_all_sessions()  # 살아있는 라이브 세션의 브라우저까지 정리
            try:
                await app.state.erp_browser.close()
            finally:
                await pw.stop()
                await dispose_engine()

    app = FastAPI(title="더존 옴니솔 대시보드 API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(agents.router)
    app.include_router(org_units.router)
    app.include_router(logs.router)
    app.include_router(runs.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
