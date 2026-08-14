"""옴니솔(더존 OmniEsol) **취약 셀렉터 단일 소스**.

★ 이 파일이 존재하는 이유: 옴니솔은 상용 RealGrid + Kendo + 더존 dews 래퍼로,
  화면 리스킨/버전업 시 클래스·id 가 바뀔 수 있다. 그때 **여기 한 곳만** 고치면 되도록
  모든 CSS 셀렉터를 상수로 모은다. in-page JS 문자열은 :mod:`nbkit.omnisol.js_lib` 에 있다.

⚠ 저장/확정 관련 셀렉터(BTN_SAVE)는 **실전표 생성**을 유발한다 — 자동화는 절대 클릭 금지.
"""

from __future__ import annotations

# 뷰포트 — nbkit 이 컨텍스트를 직접 만들 때(예: 자격증명 검증)의 기본 크기.
# ⚠ 모든 실행이 이 크기인 것은 아니다: **라이브 실행은 runner 소유 1920×1200**
#   (app/live/runner.py LIVE_VIEWPORT — 탐색 단계에서 검증된 크기)로 돈다. 따라서 고정
#   픽셀 좌표는 이 값 기준을 전제하지 말고, 가능하면 요소 bbox 를 읽어 동적 계산할 것
#   (grid/strategies 첫 행 클릭이 그 방식). 이 값 기준으로 검증된 좌표를 쓰는 코드는
#   뷰포트가 다르면 좌표 재검증이 필요하다.
VIEWPORT = {"width": 1600, "height": 1000}

# ── 로그인 폼 ────────────────────────────────────────────────────────────────
LOGIN_USERID = "#userid"
LOGIN_PASSWORD = "#password"
LOGIN_SUBMIT = "button[type=submit]"

# ── 사용자 패널 / 아바타 ───────────────────────────────────────────────────────
# 헤더 우상단 아바타 = `<a class="user-pic"><img …></a>`.
# ⚠ 이미지 src 로 잡지 말 것(2026-07-27 라이브 장애): 기본 아바타 계정은
#   `/images/profile_circle.png` 지만 **프로필 사진을 올린 계정은 `/download/image/<uuid>`** 라
#   `img[src*=profile_circle]` 가 아예 매칭되지 않는다 → 아바타 클릭 4s 타임아웃 → 패널 미개방
#   → "사용자 유형 선택기를 찾을 수 없습니다"로 사용자유형 전환이 실패했다(계정 '석대현').
#   앵커 클래스는 두 계정 모두 동일해 사진 유무와 무관하다.
# ⚠ `a.user-pic` 로 태그를 고정하는 이유: 열린 패널 안에도 `div.user-pic`(48×48 프로필 사진)이
#   있어 태그를 안 박으면 패널 내부 요소를 클릭해 패널이 토글로 닫힐 수 있다.
AVATAR = "a.user-pic"

# 로그인 직후 공지 레이어 팝업(전 화면 차단) — 고유 앵커. dismiss_notice_popup 참조.
NOTICE_CHECKBOX_TODAY = "#close-today-chk"  # '하루동안 보지 않기'
NOTICE_CLOSE_BTN = "#notice-dialog-close"  # '닫기'

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
