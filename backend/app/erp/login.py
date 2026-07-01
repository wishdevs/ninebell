"""더존 옴니솔 헤드리스 로그인 (ninebell-bak `erp/client.py:browser_login` 이식).

★ 원칙: 모든 더존 상호작용은 헤드리스 브라우저(Playwright)로만. 자격증명 비저장.
성공 판정: 로그인 폼(#userid) 소멸. 성공 시 프로필 dict 반환, 실패 시 ErpAuthError.
"""

from __future__ import annotations

import logging

from app.erp.profile import read_profile

logger = logging.getLogger("app.erp.login")

_LOGIN_TIMEOUT_MS = 25_000


class ErpAuthError(Exception):
    """로그인 실패(자격증명 불일치 등)."""


async def authenticate(browser, userid: str, password: str, base: str) -> dict:
    """헤드리스 로그인 검증 + 더존 기본정보 best-effort 추출.

    성공 시 프로필 dict ``{display_name, department, email|None}`` 반환,
    실패 시 :class:`ErpAuthError`. 매 호출마다 새 컨텍스트를 만들고 즉시 폐기한다
    (자격증명 비저장 + 컨텍스트 격리). 호출자는 동시 로그인 세마포어로 보호한다.

    이식 출처: ninebell-bak browser_login —
    page.goto(base) → #userid/#password fill → button[type=submit] click →
    networkidle 대기 → 로그인폼(#userid) 소멸로 성공 판정.
    """
    if not (userid and password):
        raise ErpAuthError("자격증명이 비어 있습니다.")

    ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
    try:
        page = await ctx.new_page()
        await page.goto(
            f"{base.rstrip('/')}/",
            wait_until="networkidle",
            timeout=_LOGIN_TIMEOUT_MS,
        )
        await page.fill("#userid", userid)
        await page.fill("#password", password)
        await page.click("button[type=submit]")
        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:  # noqa: BLE001 — networkidle 못 잡아도 계속 진행
            pass
        await page.wait_for_timeout(1_500)
        form_gone = await page.evaluate("() => !document.querySelector('#userid')")
        if not form_gone:
            raise ErpAuthError("아이디 또는 비밀번호가 올바르지 않습니다.")
        profile = await read_profile(page)
        logger.info("ERP 인증 성공: userid=%s dept=%s", userid, profile.get("department"))
        return profile
    finally:
        await ctx.close()
