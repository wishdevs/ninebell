"""더존 기본정보(이름·부서) best-effort 추출 (ninebell-bak 이식).

★ 셀렉터는 더존 UI 변경 시 깨질 수 있다. 추출 실패해도 예외를 던지지 않고 빈 값으로 반환한다
  — 로그인/계정 생성은 userid(권위)로 가능해야 하기 때문. email 은 옴니솔 프로필에서
  안정적으로 얻기 어려워 현재 항상 None(향후 셀렉터 확보 시 채움).

부서(department)는 로그인 직후 화면엔 없다. **우상단 아바타를 눌러야 뜨는 사용자 패널**에
회계/인사 사용자유형 select 가 있고, **그 바로 아래에 부서**가 표시된다. 따라서
(1) 아바타를 실제 마우스 클릭으로 눌러 패널을 연 뒤(부서 노출), (2) 사용자유형 정보 근처
(패널)에서 부서 토큰을 읽는다. JS `.click()` 은 Kendo 열기 핸들러를 못 깨워 패널이 안 열리는
경우가 있어(= 부서 빈값의 원인), ninebell-bak `erp/graph.py:_open_user_panel` 의 검증된
'실제 클릭 우선 + JS 폴백' 패턴을 그대로 쓴다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app.erp.profile")

# 우상단 아바타 클릭(JS 폴백) — 실제 page.click 이 실패할 때만 사용.
_AVATAR_CLICK_JS = (
    "() => { const a = document.querySelector('img[src*=profile_circle]') "
    "|| [...document.querySelectorAll('header img, img[alt]')].pop(); if (a) a.click(); }"
)

# 부서는 사용자 패널의 전용 엘리먼트 `.dept-name`(예 "인사/기획팀") 에 들어있다(실측 확인).
# 이를 1순위로 읽는다. 못 찾으면 사용자유형(회계/인사) select 근처(패널)에서 정규식으로 잡고,
# 그래도 없으면 본문 전체 첫 매치로 폴백. 정규식 문자셋에 '/'를 포함해 "인사/기획팀" 이
# "기획팀" 으로 잘리지 않게 한다(과거 버그: '/' 미포함으로 접두부 유실). 이름은 기존 셀렉터 유지.
_PROFILE_JS = r"""() => {
  const out = { display_name: "", department: "" };
  const clean = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  // '/' 포함 전체 부서명 포착(예 '인사/기획팀'). '/'가 빠지면 접두부가 잘린다.
  const deptRe = /([가-힣A-Za-z0-9][가-힣A-Za-z0-9/]*(?:팀|부서|부|실|본부|센터|그룹|사업부|TF))/;

  // 1) 전용 엘리먼트(.dept-name) — 가장 정확(슬래시 포함 전체 부서명).
  const deptEl = document.querySelector('.user-info .dept-name, .dept-name');
  if (deptEl) out.department = clean(deptEl.innerText || deptEl.textContent).slice(0, 60);

  // 2) 폴백: 사용자유형 select(옵션에 '사용자' 포함) 근처 패널에서 부서 토큰 탐색.
  if (!out.department) {
    const utSel = [...document.querySelectorAll('select')]
      .find(s => [...s.options].some(o => /사용자/.test(o.text || '')));
    if (utSel) {
      let node = utSel.closest('.user-info, .user-info-change, .k-window, [role=dialog]')
        || utSel.parentElement;
      for (let i = 0; i < 5 && node; i++) {
        const m = clean(node.innerText).match(deptRe);
        if (m) { out.department = m[1]; break; }
        node = node.parentElement;
      }
    }
  }
  // 3) 최종 폴백: 본문 전체 첫 매치(정확도 낮음 — 위 두 경로 실패 시에만).
  if (!out.department) {
    const body = document.body ? clean(document.body.innerText) : '';
    const m = body.match(deptRe);
    if (m) out.department = m[1];
  }

  const nameEl = document.querySelector(
    '[class*="user"] [class*="name"], .user-name, .username, header [class*="name"]'
  );
  if (nameEl) out.display_name = ((nameEl.innerText || nameEl.textContent) || '').trim().slice(0, 40);
  return out;
}"""


async def _open_user_panel(page) -> None:
    """우상단 아바타를 실제 클릭해 사용자 패널(회계/인사 사용자유형 + 부서)을 연다.

    이식 출처: ninebell-bak `erp/graph.py:_open_user_panel`. JS click 은 Kendo 열기
    핸들러를 못 깨워 패널이 안 열리는 경우가 있어 실제 page.click 을 먼저 시도하고,
    실패하면 JS 로 폴백한다. 셀렉터 변경 대비로 전부 예외 가드(못 열어도 계속).
    """
    try:
        await page.click("img[src*=profile_circle]", timeout=4_000)
    except Exception:  # noqa: BLE001 — 실제 클릭 실패 시 JS 폴백
        try:
            await page.evaluate(_AVATAR_CLICK_JS)
        except Exception:  # noqa: BLE001 — 패널 못 열어도 읽기는 시도
            pass
    await page.wait_for_timeout(1_500)


async def read_profile(page) -> dict:
    """로그인된 page 에서 더존 기본정보 추출. 항상 ``{display_name, department, email}`` 반환."""
    try:
        await _open_user_panel(page)
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
