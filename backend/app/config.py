"""애플리케이션 설정 — 환경변수 기반(pydantic-settings).

ninebell-bak `config.py` 구조를 단일 테넌트 대시보드용으로 적응.
리스트형 값(CORS, super-admin ids)은 pydantic 의 JSON 파싱 함정을 피하려고
쉼표 구분 문자열로 받고 헬퍼로 파싱한다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- DB ---
    database_url: str = "postgresql+asyncpg://dashboard:dashboard@localhost:5432/dashboard"

    # --- 세션/JWT ---
    auth_secret: str = "dev-insecure-change-me-please"
    jwt_algorithm: str = "HS256"
    session_ttl_hours: int = 12
    cookie_secure: bool = False

    # --- 더존 옴니솔 ERP ---
    erp_base: str = "https://erp.ninebell.co.kr"
    max_concurrent_erp_logins: int = 3

    # --- Gemini(대화형 법인카드 에이전트 P3) ---
    gemini_api_key: str = ""  # env GEMINI_API_KEY(backend/.env). 없으면 chat_form 이 명확 실패.
    gemini_model: str = "gemini-2.0-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # --- 라이브 세션(run) / 스크린캐스트 ---
    # 구독자가 모두 끊긴 미완료 흐름을 유지하는 시간(재연결 가능 창).
    session_detach_grace_s: float = 120.0
    # 종료된 흐름을 재연결용 버퍼로 유지하는 시간(브라우저는 이미 닫힘).
    session_terminal_grace_s: float = 120.0
    session_reaper_interval_s: float = 15.0
    # CDP Page.startScreencast 파라미터(라이브 뷰). q50·everyNthFrame=2 → ~16fps.
    screencast_quality: int = 50
    screencast_max_width: int = 1280
    screencast_max_height: int = 800
    screencast_every_nth_frame: int = 2
    # HITL(사용자 개입) 대기 상한(초).
    hitl_timeout_s: int = 300

    # 쉼표 구분 문자열(헬퍼로 파싱) — pydantic 의 list 자동 JSON 파싱 회피.
    super_admin_omnisol_ids: str = ""
    cors_origins: str = "http://localhost:3101"

    # 개발용: startup 에서 Base.metadata.create_all 실행 여부.
    dev_create_all: bool = False

    def super_admin_id_set(self) -> set[str]:
        return {x.strip() for x in self.super_admin_omnisol_ids.split(",") if x.strip()}

    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def session_ttl_seconds(self) -> int:
        return self.session_ttl_hours * 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
