"""옴니솔(더존 OmniEsol) **취약 셀렉터 단일 소스**.

★ 이 파일이 존재하는 이유: 옴니솔은 상용 RealGrid + Kendo + 더존 dews 래퍼로,
  화면 리스킨/버전업 시 클래스·id 가 바뀔 수 있다. 그때 **여기 한 곳만** 고치면 되도록
  모든 CSS 셀렉터를 상수로 모은다. in-page JS 문자열은 :mod:`nbkit.omnisol.js_lib` 에 있다.

⚠ 저장/확정 관련 셀렉터(BTN_SAVE)는 **실전표 생성**을 유발한다 — 자동화는 절대 클릭 금지.
"""

from __future__ import annotations

# 뷰포트 — 픽셀 좌표(캔버스 돋보기 등)는 이 크기 기준으로 검증됨. 바꾸면 좌표 재검증 필요.
VIEWPORT = {"width": 1600, "height": 1000}

# ── 로그인 폼 ────────────────────────────────────────────────────────────────
LOGIN_USERID = "#userid"
LOGIN_PASSWORD = "#password"
LOGIN_SUBMIT = "button[type=submit]"

# ── 사용자 패널 / 아바타 ───────────────────────────────────────────────────────
AVATAR = "img[src*=profile_circle]"

# ── 그리드(더존 dews 래퍼; 내부는 RealGrid 캔버스) ─────────────────────────────
GRID = ".dews-ui-grid"  # 순서: [0]=마스터, [1]=디테일, [2]=항목, 팝업 내부 그리드는 별도.

# ── 본문 툴바 버튼(메인 헤더) ─────────────────────────────────────────────────
BTN_LOOKUP = "button.main-button.lookup"  # 조회(F2)
BTN_ADD = "button.main-button.add"  # 추가(F3)
BTN_DELETE = "button.main-button.delete"  # 삭제
BTN_SAVE = "button.main-button.save"  # ⚠ 저장(F7) — 실전표 생성. 자동화 금지.

# ── 결의서입력(FI/GLDDOC00300) ───────────────────────────────────────────────
GUBUN_SELECT = "#s_abdocu_fg_cd"  # 결의구분 native select(name 없음 — id 로 잡을 것)

# ── 팝업/모달 ────────────────────────────────────────────────────────────────
DIALOG = ".k-window.dialog"  # 증빙유형 등 확정 모달
KWINDOW = ".k-window"  # 일반 Kendo 윈도우(프로젝트 코드피커 팝업 등)
KENDO_DROPDOWN = ".k-dropdown"  # 사용자유형 등 Kendo 드롭다운

# ── 코드피커(돋보기) / 검색 ────────────────────────────────────────────────────
CODEPICKER_BTN = "button.dews-codepicker-button"
SEARCH_KEY = "#s_search_key"  # 팝업 내부 검색어 입력(프로젝트 등)

# ── 딥링크 접두 ──────────────────────────────────────────────────────────────
# 메뉴 진입은 base + deeplink 로. 예: {base}/IM/IMIIRM00700_X20616, {base}/FI/GLDDOC00300.
MODULE_IM = "/IM"  # 재고관리(인사사용자 컨텍스트)
MODULE_FI = "/FI"  # 재무회계(회계사용자 컨텍스트)
