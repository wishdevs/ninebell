"""애플리케이션 설정 — 환경변수 기반(pydantic-settings).

ninebell-bak `config.py` 구조를 단일 테넌트 대시보드용으로 적응.
리스트형 값(CORS, super-admin ids)은 pydantic 의 JSON 파싱 함정을 피하려고
쉼표 구분 문자열로 받고 헬퍼로 파싱한다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 개발 기본 시크릿 — 운영 휴리스틱(cookie_secure=true)에서는 이 값으로 부팅을 차단한다.
_DEV_AUTH_SECRET = "dev-insecure-change-me-please"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- DB ---
    database_url: str = "postgresql+asyncpg://dashboard:dashboard@localhost:5432/dashboard"
    # PG 커넥션 풀 노브(create_async_engine). SQLite(aiosqlite) 경로에는 적용하지 않는다.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_pre_ping: bool = True

    # --- 세션/JWT ---
    auth_secret: str = _DEV_AUTH_SECRET
    jwt_algorithm: str = "HS256"
    session_ttl_hours: int = 12
    # '로그인 상태 유지' 체크 시의 연장 세션 수명(기본 30일). 미체크는 session_ttl_hours.
    remember_ttl_hours: int = 24 * 30
    cookie_secure: bool = False
    # 세션 쿠키 SameSite. 로컬(동일 출처 http)=lax. 운영에서 front·api 가 다른 도메인이면
    # cross-origin 이라 "none"(+cookie_secure=true) 필요. env COOKIE_SAMESITE.
    cookie_samesite: str = "lax"
    # 세션 쿠키 Domain. 비우면 host-only(로컬: front·api 가 같은 localhost 라 공유됨).
    # 운영에서 front(ninebell.hynro.com)·api(ninebell-api.hynro.com) 가 서로 다른 서브도메인이면
    # ".hynro.com" 처럼 부모 도메인으로 발급해야 front 프록시(구 middleware)가 쿠키를 본다. env COOKIE_DOMAIN.
    cookie_domain: str = ""

    # --- 더존 옴니솔 ERP ---
    erp_base: str = "https://erp.ninebell.co.kr"
    # 로그인 검증(단발·짧음)과 워크플로우 실행(브라우저 전 구간·HITL 대기로 길다)의 동시성을
    # 분리한다. 단일 세마포어 공유 시 장기 실행이 세마포어를 점유해 짧은 로그인이 최대 hitl_timeout
    # 만큼 블로킹됐다(역커플링).
    # 2026-08-26 실행 상한 2→30(사용자 지시 — 다계정 동시 사용 대비). ⚠ 브라우저 1개 ≈
    # 0.6~1.0GB(infra/aws/variables.tf 실측 주석)라 30이 실제로 차면 18~30GB — 현 Fargate
    # 태스크(4vCPU/16GB)에서는 OOM→재시작 루프 위험. 동접이 실제로 늘면 태스크 사양 상향이
    # 선행돼야 한다. 로그인 세마포어(3)는 유지 — 동시 기동 시 로그인 구간의 CPU 스파이크를
    # 자연 스로틀하는 역할이라 함께 올리지 않는다(대기일 뿐 실패 아님).
    max_concurrent_erp_logins: int = 3
    max_concurrent_erp_runs: int = 30

    # 헤드리스 Chromium 실행 인자(공백 구분). env CHROMIUM_ARGS. 로컬 dev 는 빈값(기본 동작).
    # ⚠ 컨테이너/Fargate 는 /dev/shm 조절 불가 → "--disable-dev-shm-usage --no-sandbox" 필수.
    chromium_args: str = ""
    # ERP 브라우저 헤디드 전환(로컬 관찰용). env ERP_HEADLESS=0 이면 창을 띄운다 — 사용자가 실행을
    # 지켜보며 개입하는 용도(2026-08-28 구매발주 쓰기 개방). 배포(컨테이너)는 항상 기본 True.
    erp_headless: bool = True

    # --- Gemini(대화형 법인카드 에이전트 P3) ---
    gemini_api_key: str = ""  # env GEMINI_API_KEY(backend/.env). 없으면 chat_form 이 명확 실패.
    # gemini-2.0-flash retired(404) → 2.5 → 3.5 → 3.6 → 3.7-flash 상향(2026-08-14 사용자 지시).
    # 상향 전 models API 로 실재 확인(폐기 모델 지정 = 런타임 404). env GEMINI_MODEL 오버라이드.
    gemini_model: str = "gemini-3.7-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # LLM 프로바이더 선택 — 'gemini'(기본: GitHub/AWS 배포) | 'etribe'(온프렘 GitLab 배포, 사내
    # Etribe-LLM OpenAI 호환 서버 — 회계 데이터·ERP 스크린샷이 사외로 나가지 않는다). env LLM_PROVIDER.
    llm_provider: str = "gemini"
    # ETRIBE-LLM API(2026-08 개발자 참조) 기준: 서버 :30001, 모델 id "ETRIBE-LLM"(대문자),
    # 컨텍스트 256K(입력+출력 합·신뢰 검색 구간 ≤~120K), max_tokens 생략 시 8192·상한
    # 16384(초과는 서버가 클램프), 샘플링 권장 temperature=1.0·top_p=1.0(프록시 미주입),
    # reasoning_effort 는 **생략=자동**(실작업은 서버가 high 처리 — 일괄 고정 비권장).
    # base 에 /v1 을 붙이지 않는다(클라이언트가 /v1/chat/completions 를 붙임).
    # 실측: 채팅·네이티브 툴콜·thinking 기본 ON(reasoning 채널) OK. **텍스트 전용**("not a
    # multimodal model" 400) → etribe_multimodal=False 로 디스패처가 스크린샷 첨부를 차단한다.
    # 대안 서버: 192.168.50.2:8030 ETRIBE-VLM(멀티모달 OK·네이티브 툴콜 불가 — JSON 폴백
    # 필요, 컨텍스트 32K) — 전환 시 ETRIBE_BASE_URL/MODEL/MULTIMODAL=true 만 바꾸면 된다.
    etribe_base_url: str = "http://172.20.50.2:30001"  # env ETRIBE_BASE_URL(온프렘 사내망)
    etribe_model: str = "ETRIBE-LLM"  # env ETRIBE_MODEL
    etribe_multimodal: bool = False  # env ETRIBE_MULTIMODAL — GLM-5.2 텍스트 전용(이미지 400)
    # Bearer 토큰 — API 문서상 임의 문자열이되 **사용자 식별자 = QoS 단위**다(토큰당 동시
    # 4 요청, 초과 시 429 concurrency_limit·Retry-After 5). 서비스 식별 토큰 하나로 통일해
    # 대시보드 트래픽이 한 버킷으로 계량되게 한다. env ETRIBE_TOKEN.
    etribe_token: str = "ninebell-dashboard"
    # 로컬 전용 LLM 프로바이더 런타임 전환 게이트(/dev/llm-provider 활성 여부). 서버 배포에선
    # 미설정=off → 라우터가 404 를 반환해 기능 자체가 없는 것처럼 동작한다. env LLM_PROVIDER_TOGGLE.
    llm_provider_toggle: bool = False
    # LLM 전체 프롬프트 캡처(디버깅 전용, 기본 OFF). 켜면 프로바이더가 실제 전송하는 와이어
    # 요청 바디 전체(system·user·context·tools)를 JSONL 로 append 한다 — 민감정보 포함이라
    # 수집 후 파일을 정리하고 커밋하지 않는다. env LLM_PROMPT_CAPTURE / LLM_PROMPT_CAPTURE_PATH.
    llm_prompt_capture: bool = False
    llm_prompt_capture_path: str = "prompt-capture.jsonl"

    # --- 로깅 ---
    # root 로거 레벨. uvicorn 은 root 에 핸들러를 달지 않아 그대로 두면 app.* 의 INFO 가 전부
    # 유실된다(core/logging_setup 참고). env LOG_LEVEL 로 운영에서 WARNING 등으로 조절한다.
    log_level: str = "INFO"
    # 로그 파일 경로(회전 50MB×5). 비우면 stdout 만 — **배포 기본값**이다(ECS 는 CloudWatch,
    # 온프렘은 Docker json-file 로 stdout 을 수집하므로 컨테이너 안 파일은 무의미).
    # 로컬 개발에서 터미널을 닫아도 로그를 남기려면 backend/.env 에 LOG_FILE=logs/app.log.
    log_file: str = ""
    # LLM 호출별 파일 로그 디렉터리(호출 1건 = 파일 1개, 요청·응답 전문). 비우면 끔 —
    # **배포 기본값**. 한 줄 로그(app.llm.wire)는 프롬프트가 수천 자라 눈으로 못 읽어서,
    # 사람이 읽을 용도로 따로 남긴다. 로컬은 LLM_LOG_DIR=logs/llm.
    llm_log_dir: str = ""

    @field_validator("llm_provider")
    @classmethod
    def _normalize_llm_provider(cls, v: str) -> str:
        """공백·대소문자 정규화 + 미지 값 즉시 실패(부팅 차단).

        오타(LLM_PROVIDER=Etribe / 'etribe ' 등)가 조용히 gemini 폴백되면 온프렘의 회계
        데이터·ERP 스크린샷이 무음으로 사외(구글)에 나간다 — 이 기능의 존재 이유가 무너지는
        사고라 런타임 폴백 대신 부팅 시점에 명확히 실패시킨다.
        """
        norm = (v or "").strip().lower()
        if norm not in {"gemini", "etribe"}:
            raise ValueError(f"LLM_PROVIDER 는 'gemini'|'etribe' 만 허용합니다(입력: {v!r})")
        return norm

    @model_validator(mode="after")
    def _reject_dev_secret_in_prod(self) -> Settings:
        """운영 휴리스틱(cookie_secure=true)에서 기본 auth_secret 부팅 차단.

        기본 시크릿으로 운영에 뜨면 세션 JWT 를 누구나 위조할 수 있다 — 조용한 폴백 대신
        부팅 시점에 명확히 실패시킨다(_normalize_llm_provider 와 동일 철학). 로컬/테스트
        (cookie_secure=false)는 기본값 부팅을 그대로 허용한다.
        """
        if self.cookie_secure and self.auth_secret == _DEV_AUTH_SECRET:
            raise ValueError(
                "COOKIE_SECURE=true(운영)인데 AUTH_SECRET 이 개발 기본값입니다 — "
                "세션 토큰 위조가 가능하므로 부팅을 중단합니다. AUTH_SECRET 을 설정하세요."
            )
        return self

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
    # HITL(사용자 개입) 대기 상한(초). collect_rows/chat_form 대화 한 턴·저장 확인 공통 소스.
    # 600 → 1800 (사용자 요청 2026-08-14): 구매발주 계획서처럼 발주단위·거래처·납기를 여러 건
    # 채우는 개입은 10분 안에 못 끝낸다. 대기 시간은 런 활동 예산에서 제외되므로(아래
    # run_active_budget_s) 상한을 늘려도 자동화 구간 무한 루프 보호는 그대로다.
    hitl_timeout_s: int = 1800
    # 런 전역 활동 시간 예산(초) — **HITL 대기 시간을 제외한 활동 시간** 기준. 사용자가
    # 그리드/채팅 응답을 오래 고민하는 것은 정당(턴당 hitl_timeout_s 상한이 별도)하므로 세지
    # 않고, 자동화 구간이 무한히 도는 것만 제한한다(세마포어 슬롯·Chromium 메모리 무기한
    # 점유 방지). 초과 시 러너 워치독이 그래프를 취소하고 런을 failed 로 확정한다. 0=비활성.
    run_active_budget_s: int = 1200

    # --- 로컬 시스템 관리자(admin) ---
    # 비우면 seed 가 폴백 '1111'을 쓰되 critical 경고. 프로덕션은 반드시 env 로 지정.
    local_admin_password: str = ""

    # --- 로그인 시도 제한(인메모리, 단일 워커 전제) ---
    login_max_attempts: int = 5
    login_window_s: float = 900.0
    login_ip_max_attempts: int = 20
    login_lockout_base_s: float = 30.0
    login_lockout_max_s: float = 900.0

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

    @property
    def remember_ttl_seconds(self) -> int:
        return self.remember_ttl_hours * 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
