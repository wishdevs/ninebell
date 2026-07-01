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
