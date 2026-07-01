"""nbkit — 더존 옴니솔 브라우저 자동화 라이브러리(ninebell-bak 노하우 추출·정제).

계층:
- ``browser/``  앱-불문 프리미티브(재시도 click/fill/evaluate·trusted 키보드·감지·스냅샷).
- ``grid/``     dews/RealGrid 읽기(GridProvider·GridExtractor·off-by-one 정규화).
- ``omnisol/``  더존 특화(로그인·사용자유형 실클릭·메뉴진입·취약 셀렉터/JS 단일소스·메뉴스키마).
- ``patterns/`` 조합 플로우 템플릿(login/user_type/menu/grid_read) — 엔진/에이전트가 사용.

모든 함수는 Playwright ``Page`` 를 느슨하게(``Any``) 받아 **라이브 브라우저 없이 import** 된다.
자세한 옴니솔 노하우는 ``OMNISOL_NOTES.md`` 참고.
"""

from __future__ import annotations

__version__ = "0.1.0"

# ── 공개 API(P3/엔진이 주로 쓰는 표면) ────────────────────────────────────────
from nbkit.browser.actions import (
    js_click,
    mouse_click,
    safe_click,
    safe_evaluate,
    safe_fill,
)
from nbkit.grid.provider import GridProvider
from nbkit.grid.strategies import CollectionStrategy, GridExtractor
from nbkit.omnisol.auth import omnisol_login, switch_user_type
from nbkit.omnisol.errors import (
    AuthError,
    GridError,
    MenuError,
    OmnisolError,
    PopupError,
    UserTypeError,
)
from nbkit.omnisol.menu_schemas import MENU_MAP, MenuSchema, get_menu
from nbkit.omnisol.navigator import navigate_menu, verify_plant
from nbkit.omnisol.profile import read_profile
from nbkit.patterns.grid_read_flow import read_grid_with_fallback, run_query
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.user_type_flow import ensure_user_type

__all__ = [
    "__version__",
    # browser primitives
    "safe_click",
    "safe_fill",
    "safe_evaluate",
    "js_click",
    "mouse_click",
    # grid
    "GridProvider",
    "GridExtractor",
    "CollectionStrategy",
    # omnisol
    "omnisol_login",
    "switch_user_type",
    "navigate_menu",
    "verify_plant",
    "read_profile",
    "MENU_MAP",
    "MenuSchema",
    "get_menu",
    # patterns
    "ensure_logged_in",
    "ensure_user_type",
    "read_grid_with_fallback",
    "run_query",
    # errors
    "OmnisolError",
    "AuthError",
    "UserTypeError",
    "MenuError",
    "GridError",
    "PopupError",
]
