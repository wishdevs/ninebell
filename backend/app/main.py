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

from app.config import get_settings
from app.db import dispose_engine, get_engine, get_sessionmaker, init_engine
from app.erp.credcache import CredCache
from app.models import Base
from app.routers import agents, auth, logs, users
from app.services.seed import seed_all

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
        app.state.erp_semaphore = asyncio.Semaphore(settings.max_concurrent_erp_logins)

        # --- 자격증명 캐시 + 주기 reaper ---
        app.state.cred_cache = CredCache()
        reaper = asyncio.create_task(app.state.cred_cache.reaper())

        if not settings.cookie_secure:
            logger.warning(
                "COOKIE_SECURE=false — 세션 쿠키가 평문 HTTP 로 전송됩니다. "
                "프로덕션(HTTPS)에서는 COOKIE_SECURE=true 로 설정하세요."
            )

        try:
            yield
        finally:
            reaper.cancel()
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
    app.include_router(logs.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
