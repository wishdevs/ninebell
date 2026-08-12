"""전자결재(EAP) 상신 취소 — 순수 브라우저 스텝(이벤트 방출 없음).

`e2e/eap_approval_cancel_probe.py`(2026-08-07 Playwright codegen 실측 + 실검증 PASS)의
브라우저 조작부를 그대로 이식했다. 프로브가 확정한 사실만 여기 남기고, 진행 이벤트·HITL·
실패 문구는 nodes.py 가 담당한다(스텝은 {"ok": bool, "reason"?: str} 만 돌려준다).

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 이 모듈이 누르는 버튼은 `ALLOWED_BUTTONS` 4개(결재취소·상신취소·삭제·확인)뿐이다.
    상신·저장(F7)·보관은 어떤 경로로도 클릭하지 않는다.
  - 세 단계는 전부 **비가역**이다. 호출부(nodes.py)가 사용자가 체크한 문서에만 부른다.

⏱ 시간축 규율: 관찰 폴 대기는 항상 실시간(`verify.DEFAULT_SLEEP`)이고, 상한만
   `latency.budget_ms` 로 확대한다 — 명목 카운터(page.wait_for_timeout 누산)는 delay_scale 로
   관찰창이 붕괴한다(2026-08-07 규율).
"""

from __future__ import annotations

import logging
from typing import Any

from nbkit.omnisol import latency, verify

from . import js

logger = logging.getLogger(__name__)

IFRAME = "#content_UB"  # EAP React 앱 iframe(dews 그리드 아님)
MENU_SUBMIT_GROUP = "#UBA_UBA1000"  # 상신/보관함(그룹)
MENU_SUBMITTED = "#UBA1010_UBA"  # 상신문서
MENU_PENDING = "#UBA2020_UBA"  # 결재수신함 > 미결문서(그룹 펼침 없이 직접 클릭됨)
MENU_DRAFTBOX = "#UBA1020_UBA"  # 임시보관문서

# 취소 3단계 — (메뉴 라벨, 리프 셀렉터, 그룹 셀렉터, 문서창에서 누를 버튼).
# 상신문서에서 결재를 취소하면 미결문서로, 거기서 상신을 취소하면 임시보관문서로 내려온다.
PHASES: tuple[tuple[str, str, str | None, str], ...] = (
    ("상신문서", MENU_SUBMITTED, MENU_SUBMIT_GROUP, "결재취소"),
    ("미결문서", MENU_PENDING, None, "상신취소"),
    ("임시보관문서", MENU_DRAFTBOX, MENU_SUBMIT_GROUP, "삭제"),
)

# 문서 창에서 누르는 취소 동사 3개 + 뒤따르는 확인 = 이 워크플로우가 누르는 버튼의 전량.
# `click_doc_button` 이 CANCEL_BUTTONS 밖 라벨을 거부한다 — 상신·보관 오클릭 마지막 방어선.
CANCEL_BUTTONS = frozenset({"결재취소", "상신취소", "삭제"})
CONFIRM_BUTTON = "확인"
ALLOWED_BUTTONS = CANCEL_BUTTONS | {CONFIRM_BUTTON}

POLL_MS = 500  # 리스트 관찰 폴 간격(실시간)
LIST_CAP_MS = 25_000  # 리스트에 문서가 나타날 때까지의 상한(결재취소 직후 도착 지연 실측 대비)
ROWS_CAP_MS = 20_000  # 리스트 행 렌더 상한
GONE_CAP_MS = 15_000  # 삭제 후 사라짐 확인 상한
POPUP_CLOSE_CAP_MS = 3_000  # '확인' 후 문서창이 스스로 닫히길 기다리는 상한


async def _frame(page: Any) -> Any:
    """EAP iframe 의 Frame 객체 — evaluate 용. 스테일 방지를 위해 매번 재획득한다."""
    handle = await page.wait_for_selector(IFRAME, timeout=30_000)
    fr = await handle.content_frame()
    if fr is None:
        raise RuntimeError("EAP iframe(#content_UB) 콘텐츠 프레임을 얻지 못했습니다.")
    return fr


async def enter_eap(page: Any, *, cap_ms: int = 30_000) -> dict:
    """GNB '전자결재' 진입 — 같은 탭에서 iframe(#content_UB)이 뜰 때까지 대기."""
    try:
        # 로그인 직후 배너(codegen 실측 — aria-label=Close). 없으면 no-op.
        await page.get_by_label("Close").click(timeout=3_000)
    except Exception:  # noqa: BLE001 — 배너는 없을 수 있다(정상 경로).
        logger.debug("enter_eap: 로그인 배너 없음(무시)", exc_info=True)
    try:
        await page.get_by_role("listitem", name="전자결재").locator("div").click()
    except Exception as exc:  # noqa: BLE001 — 진입 실패는 사유와 함께 반환.
        return {"ok": False, "reason": f"GNB '전자결재' 클릭 실패: {exc}"}
    try:
        await page.wait_for_selector(IFRAME, timeout=latency.budget_ms(cap_ms))
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "전자결재 화면(iframe #content_UB)이 뜨지 않았습니다."}
    return {"ok": True}


async def click_menu(page: Any, leaf: str, group: str | None) -> bool:
    """사이드바 리프 메뉴 클릭 — 안 보이면 그룹을 먼저 펼치고 재시도."""
    fl = page.locator(IFRAME).content_frame
    try:
        await fl.locator(leaf).click(timeout=5_000)
        return True
    except Exception:  # noqa: BLE001 — 접힌 그룹이면 아래에서 펼치고 재시도.
        if group is None:
            logger.debug("click_menu: 리프 %s 클릭 실패(그룹 없음)", leaf, exc_info=True)
            return False
    try:
        await fl.locator(group).click(timeout=10_000)
        await fl.locator(leaf).click(timeout=10_000)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("click_menu: 그룹 %s 펼침 후에도 리프 %s 실패", group, leaf, exc_info=True)
        return False


async def wait_rows(page: Any, *, cap_ms: int = ROWS_CAP_MS) -> list[dict]:
    """리스트 행(li.listChk)이 렌더될 때까지 폴링 후 전량 덤프(읽기 전용)."""
    waited = 0
    cap = latency.budget_ms(cap_ms)
    rows: list[dict] = []
    while True:
        try:
            fr = await _frame(page)
            rows = await fr.evaluate(js.ROWS_DUMP_JS)
        except Exception:  # noqa: BLE001 — iframe 재로딩 중이면 다음 폴에서 다시 읽는다.
            rows = []
        if rows or waited >= cap:
            return rows or []
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS


async def count_title(page: Any, title: str) -> int:
    """리스트에서 제목을 포함하는 span 수(읽기 전용). 읽지 못하면 -1."""
    try:
        fr = await _frame(page)
        return int(await fr.evaluate(js.TITLE_COUNT_JS, title))
    except Exception:  # noqa: BLE001 — 재로딩 중 evaluate 실패는 '미상'.
        return -1


async def wait_title(page: Any, title: str, *, present: bool, cap_ms: int = LIST_CAP_MS) -> bool:
    """리스트에 제목이 (나타날/사라질) 때까지 실시간 폴링. 상한 내 미확인이면 False."""
    waited = 0
    cap = latency.budget_ms(cap_ms)
    while True:
        n = await count_title(page, title)
        if n >= 0 and (n > 0) == present:
            return True
        if waited >= cap:
            return False
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS


async def open_doc(page: Any, title: str) -> Any | None:
    """리스트에서 제목을 클릭해 문서 창(별도 Page)을 연다. 안 뜨면 None.

    ⚠ 동명 문서가 있으면 어느 쪽이 열릴지 확정할 수 없다 — 호출부가 **사전 가드**로
    (후보 목록의 제목 중복 검사) 이 함수에 도달하지 못하게 막는다.
    """
    fl = page.locator(IFRAME).content_frame
    try:
        async with page.expect_popup() as pinfo:
            await fl.locator("span").filter(has_text=title).first.click()
    except Exception:  # noqa: BLE001 — 문서창 미출현(타임아웃 등).
        logger.debug("open_doc: 문서창이 뜨지 않음(title=%s)", title, exc_info=True)
        return None
    popup = await pinfo.value
    try:
        await popup.wait_for_load_state("domcontentloaded")
    except Exception:  # noqa: BLE001 — 로드 상태 대기 실패는 아래 버튼 대기가 흡수한다.
        logger.debug("open_doc: domcontentloaded 대기 실패(계속 진행)", exc_info=True)
    return popup


async def click_doc_button(popup: Any, button: str) -> dict:
    """문서 창에서 취소 버튼 + '확인'을 누른다. 허용 목록 밖 버튼은 거부한다.

    ⚠ 마지막 방어선: `CANCEL_BUTTONS` 에 없는 라벨은 클릭하지 않고 실패로 돌려준다.
    (상신·보관이 실수로 호출부에 들어와도 브라우저에 닿지 않는다.)
    """
    if button not in CANCEL_BUTTONS:
        return {"ok": False, "reason": f"허용되지 않은 버튼 '{button}' — 클릭하지 않았습니다."}
    try:
        await popup.get_by_text(button, exact=True).first.click(timeout=20_000)
    except Exception as exc:  # noqa: BLE001 — 버튼 미발견/비활성.
        return {"ok": False, "reason": f"문서 창에서 '{button}' 버튼을 누르지 못했습니다: {exc}"}
    try:
        await popup.get_by_role("button", name=CONFIRM_BUTTON).click(timeout=10_000)
    except Exception as exc:  # noqa: BLE001 — 확인 미클릭이면 취소가 적용되지 않았을 수 있다.
        return {"ok": False, "reason": f"'{button}' 확인 대화상자를 처리하지 못했습니다: {exc}"}
    return {"ok": True}


async def close_doc(popup: Any, *, cap_ms: int = POPUP_CLOSE_CAP_MS) -> None:
    """'확인' 후 문서 창이 스스로 닫히길 기다리고, 안 닫혔으면 직접 닫는다(best-effort)."""
    waited = 0
    while waited < cap_ms:
        try:
            if popup.is_closed():
                return
        except Exception:  # noqa: BLE001 — 이미 유실된 핸들은 닫힌 것으로 본다.
            return
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS
    try:
        await popup.close()
    except Exception:  # noqa: BLE001 — teardown 실패는 무해.
        logger.debug("close_doc: 문서 창 닫기 실패(무시)", exc_info=True)


async def cancel_phase(page: Any, title: str, leaf: str, group: str | None, button: str) -> dict:
    """한 단계 실행 — 메뉴 이동 → 문서 대기 → 문서 창 열기 → 버튼+확인 → 창 닫기.

    문서가 상한 내 리스트에 안 보이면 **다른 메뉴로 갔다가 재진입**해 리스트를 강제 갱신하고
    한 번 더 관찰한다(실측 2026-08-07: 결재취소 직후 미결문서 도착이 20s 를 넘긴 사례).
    """
    if not await click_menu(page, leaf, group):
        return {"ok": False, "reason": f"'{leaf}' 메뉴로 이동하지 못했습니다."}
    found = await wait_title(page, title, present=True)
    if not found:
        alt = MENU_PENDING if leaf != MENU_PENDING else MENU_SUBMITTED
        await click_menu(page, alt, None if alt == MENU_PENDING else MENU_SUBMIT_GROUP)
        await click_menu(page, leaf, group)
        found = await wait_title(page, title, present=True)
    if not found:
        return {"ok": False, "reason": f"리스트에서 '{title}' 문서를 찾지 못했습니다."}

    popup = await open_doc(page, title)
    if popup is None:
        return {"ok": False, "reason": f"'{title}' 문서 창이 열리지 않았습니다."}
    try:
        r = await click_doc_button(popup, button)
    finally:
        await close_doc(popup)
    return r
