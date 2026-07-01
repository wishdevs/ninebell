"""더존 기본정보(이름·부서) best-effort 추출 (ninebell-bak `auth/profile.py` 이식).

★ 셀렉터는 더존 UI 변경 시 깨질 수 있다. 추출 실패해도 예외를 던지지 않고 빈 값으로 반환한다
  — 로그인/계정 생성은 userid(권위)로 가능해야 하기 때문. email 은 옴니솔 프로필에서
  안정적으로 얻기 어려워 현재 항상 None(향후 셀렉터 확보 시 채움).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app.erp.profile")

# 우상단 아바타 클릭 → 사용자 패널 열기(부서 노출).
_AVATAR_CLICK_JS = (
    "() => { const a = document.querySelector('img[src*=profile_circle]') "
    "|| [...document.querySelectorAll('header img, img[alt]')].pop(); if (a) a.click(); }"
)

_PROFILE_JS = r"""() => {
  const out = { display_name: "", department: "" };
  const body = document.body ? (document.body.innerText || '') : '';
  const dept = body.match(/([가-힣A-Za-z0-9]+(?:팀|부서|부|실|본부|센터|그룹|TF))/);
  if (dept) out.department = dept[1];
  const nameEl = document.querySelector(
    '[class*="user"] [class*="name"], .user-name, .username, header [class*="name"]'
  );
  if (nameEl) out.display_name = ((nameEl.innerText || nameEl.textContent) || '').trim().slice(0, 40);
  return out;
}"""


async def read_profile(page) -> dict:
    """로그인된 page 에서 더존 기본정보 추출. 항상 ``{display_name, department, email}`` 반환."""
    try:
        await page.evaluate(_AVATAR_CLICK_JS)
        await page.wait_for_timeout(1_200)
    except Exception:  # noqa: BLE001 — 패널 못 열어도 읽기는 시도
        pass
    try:
        raw = await page.evaluate(_PROFILE_JS)
    except Exception:  # noqa: BLE001
        logger.warning("프로필 추출 실패 — 빈 값으로 진행(셀렉터 변경 가능성)")
        raw = {}
    return {
        "display_name": (raw.get("display_name") or "").strip(),
        "department": (raw.get("department") or "").strip(),
        "email": None,
    }
