"""더존 옴니솔 헤드리스 로그인 — nbkit 로그인 플로우의 얇은 래퍼.

★ 원칙: 모든 더존 상호작용은 헤드리스 브라우저(Playwright)로만. 자격증명 비저장.
성공 판정·팝업 방어는 nbkit 단일 소스를 쓴다: ninebell-bak 이식 초기본의
networkidle 고정 대기(최대 20s)·고정 sleep 은 nbkit 이 실측으로 폐기한 패턴이고
(아바타 출현 양성 폴링으로 대체), 공지 레이어·외부 창(회사 홈페이지 팝업) 방어는
:func:`nbkit.patterns.login_flow.ensure_logged_in` 에만 있다.

공개 계약(호출부 routers/auth.py 불변):
- ``authenticate(browser, userid, password, base) -> dict`` — 성공 시
  ``{display_name, job_title, department, email|None}``.
- 실패 시 :class:`ErpAuthError` — nbkit :class:`~nbkit.omnisol.errors.AuthError` 의
  별칭(동일 클래스)이라 nbkit 로그인 실패가 그대로 이 계약으로 잡힌다.
- 예외: :class:`~nbkit.omnisol.errors.LoginPageError`(페이지 미로드 = 옴니솔 점검·
  SPA 지연)는 자격증명 실패가 아니므로 RuntimeError 로 승격 — 라우터의 502 경로
  (except Exception)로 흘려 시도제한 카운트를 타지 않게 한다.
"""

from __future__ import annotations

import logging

from nbkit.omnisol import selectors
from nbkit.omnisol.errors import ErpAuthError  # noqa: F401 — 공개 계약(라우터가 임포트)
from nbkit.omnisol.errors import LoginPageError
from nbkit.patterns.login_flow import ensure_logged_in

from app.erp.profile import split_job_title

logger = logging.getLogger("app.erp.login")


async def authenticate(browser, userid: str, password: str, base: str) -> dict:
    """헤드리스 로그인 검증 + 더존 기본정보 best-effort 추출.

    성공 시 프로필 dict ``{display_name, job_title, department, email|None}`` 반환,
    실패 시 :class:`ErpAuthError`. 매 호출마다 새 컨텍스트를 만들고 즉시 폐기한다
    (자격증명 비저장 + 컨텍스트 격리). 호출자는 동시 로그인 세마포어로 보호한다.
    display_name 은 직책을 뗀 순수 이름(카드 소유자 매칭용), job_title 은 분리된 직책.
    email 은 옴니솔 프로필에서 안정적으로 얻기 어려워 항상 None(기존 계약 유지).
    """
    if not (userid and password):
        raise ErpAuthError("자격증명이 비어 있습니다.")

    ctx = await browser.new_context(viewport=selectors.VIEWPORT)
    try:
        page = await ctx.new_page()
        try:
            result = await ensure_logged_in(page, userid, password, base)
        except LoginPageError as exc:
            # 로그인 폼/아바타 미출현 = 옴니솔 점검·SPA 지연(인프라 장애). 자격증명 실패
            # (ErpAuthError → 401 + 시도제한 카운트)가 아니라 라우터의 일반 예외 경로
            # (except Exception → 502 + 미카운트)로 승격 — 점검 중 재시도하는 정상
            # 사용자가 429 로 잠기지 않게 한다. LoginPageError 는 AuthError 서브클래스라
            # 여기서 잡지 않으면 ErpAuthError 로 흘러간다.
            raise RuntimeError(f"ERP 접속 지연/점검 — {exc}") from exc
        raw = result.get("profile") or {}
        display_name, job_title = split_job_title((raw.get("display_name") or "").strip())
        profile = {
            "display_name": display_name,
            "job_title": job_title,
            "department": (raw.get("department") or "").strip(),
            "email": None,
        }
        logger.info("ERP 인증 성공: userid=%s dept=%s", userid, profile.get("department"))
        return profile
    finally:
        await ctx.close()
