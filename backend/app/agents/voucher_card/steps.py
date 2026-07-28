"""미지급금 법인카드(voucher-card) 고유 스텝 프리미티브 — 프로브 이식.

공유 백본(voucher_receivable.steps: set_query 8필드·run_query·read_row_key·checkRow·결제창
열기/렌더/닫기·D7)은 그대로 재사용하고, 여기에는 카드 고유 3대 확장의 브라우저 조작만 둔다:
  Phase B  결의서조회승인(GLDDOC00400) **다중 메뉴 탭** — 결의구분=카드 일괄 조회 →
           ABDOCU_NO→GWDOCU_NO 맵 수집 → 전표조회승인 탭 복귀.
  Phase C  결제창(EAP React) 안 **참조문서 선택** sub-flow(문서번호=GWDOCU_NO 검색→선택→아래버튼).

⚠ 절대 안전: 이 모듈에는 결제창 상신·참조문서 확인을 **무조건** 클릭하는 함수가 없다.
   click_refdoc_confirm 은 존재하되(미래용 프리미티브), 호출은 reference_doc 훅의
   allow_confirm 게이트(기본 False) 뒤에서만 일어난다. F7/F6 없음.
"""

from __future__ import annotations

import calendar
import logging
import re
from typing import Any

from nbkit.browser.actions import js_click, mouse_click
from nbkit.omnisol import js_lib, selectors, verify
from nbkit.omnisol.modals import dismiss_blocking_modals, dismiss_notice_popup

from app.agents.voucher_receivable import js as vr_js
from app.agents.voucher_receivable import steps as vr_steps

from . import js

logger = logging.getLogger(__name__)

# 전표유형(SYSDEF_NM) — 카드는 '일반'(SYSDEF_CD=11). 나머지 조회조건은 공유 set_query 와 동일.
DOCU_TYPES_CARD = ("일반",)

# 결의구분 native select(#ABDOCU_FG_CD) 대상 — '카드'(ABDOCU_FG_CD=52).
GUBUN_SELECT = "#ABDOCU_FG_CD"
GUBUN_CARD_TEXT = "카드"

COLLECT_DEPT_LABEL = "결의부서"
# 화면 도착 확인용 앵커 — 그 화면에만 있는 **눈에 보이는** 요소로 판정한다(다중 메뉴 탭에서는
# 다른 탭 DOM 이 그대로 남아 있어 '존재'만으론 어느 화면인지 알 수 없다).
# ⚠ 결의구분 select(#ABDOCU_FG_CD)를 앵커로 쓰면 안 된다(2026-07-27 라이브 실패): kendo
#   DropDownList 가 원본 select 를 display:none 으로 숨겨, 제대로 도착해도 '안 보임'이라
#   확인이 **항상 실패**한다(세팅은 jQuery 위젯 API 라 숨은 select 에서도 정상 동작).
#   전표조회승인에는 '작성부서', 결의서조회승인에는 '결의부서' 라벨이 있어 화면 식별이 된다.
COLLECT_SCREEN_LABEL = COLLECT_DEPT_LABEL
COLLECT_WRITER_LABEL = "결의자"
COLLECT_PERIOD_FIELD = "#PERIOD_DT_C"  # 결의서조회승인 회계일 periodpicker
# 결의부서 전체선택 반영 판정 — 다부서 선택 시 표시값이 "회계팀 외 45건" 형태가 된다.
_MULTI_DEPT_RE = re.compile(r"외\s*\d+\s*건")

# 참조문서 dialog 제목(도착 확인 앵커 — REFDOC_CLOSE_BTN_RECT_JS 가 쓰는 것과 동일 리프 텍스트).
REFDOC_DIALOG_TITLE = "참조문서"
# 참조문서 조회 결과 조건 폴링(대량 리스트 렌더 vs '없음' 메시지 편차 — 고정대기 금지).
REFDOC_POLL_TRIES = 8
# 캔버스 그리드 첫 데이터 행 클릭 오프셋(그리드 박스 기준) — 헤더 높이 + 행 높이 실측 근사.
_GRID_HEADER_H = 30
_GRID_ROW_H = 24
# 체크박스 컬럼 중심의 좌측 오프셋(실측) — 행 중앙을 누르면 선택되지 않는다.
_GRID_CHECKBOX_DX = 16
# 두 그리드 사이 이동 버튼 후보 수(왼→오). 어느 쪽이 '아래'인지 라벨이 없어 순서대로 시도한다.
_MOVE_BTN_CANDIDATES = 2
REFDOC_POLL_INTERVAL_MS = 500
# React controlled input 클리어 — Ctrl/Cmd+A 미수신 케이스가 있어 End 후 Backspace 다회.
REFDOC_CLEAR_BACKSPACES = 40


# ══════════════════════════════════════════════════════════════════════════════
# Phase B — 결의서조회승인(GLDDOC00400) 다중 메뉴 탭 + 결의구분=카드 조회 + 맵 수집
# ══════════════════════════════════════════════════════════════════════════════
async def open_collect_tab(page: Any) -> dict:
    """사이드바 결의서조회승인 링크를 실클릭해 **새 메뉴 탭**을 연다(페이지 캐시 — 전표조회승인
    탭 유지). ⚠ 공지 팝업(비동기 지연 로드)이 클릭을 가로채는 레이스가 있어 클릭 직전 공유
    dismiss 를 확인하고, 1차 실패 시 모달 재정리 후 1회 재시도(프로브 확정 패턴).

    ⚠ 도착 확인(2026-07-27): 종전에는 클릭 후 고정 2초 대기하고 **무조건 성공**을 돌려줬다 —
    탭이 안 열려도 전표조회승인 화면을 결의서조회승인으로 착각해 조작했다. 이제 이 화면에만
    있는 조회조건 라벨('결의부서')의 렌더 여부로 도착을 확인한다(화면 전환 = HEAVY 스케줄).
    반환 {ok, reason?}.
    """
    await dismiss_notice_popup(page, appear_cap_ms=0)
    await dismiss_blocking_modals(page, rounds=1)
    try:
        await page.click(js.NAV_LINK_SELECTOR, timeout=8_000)
    except Exception:  # noqa: BLE001 — 모달 레이스 진단 후 1회 재시도.
        await dismiss_notice_popup(page, appear_cap_ms=0)
        await dismiss_blocking_modals(page, rounds=1)
        await page.click(js.NAV_LINK_SELECTOR, timeout=8_000)
    chk = await verify.confirm_visible_label(page, COLLECT_SCREEN_LABEL)
    if not chk:
        return {"ok": False, "reason": f"결의서조회승인 탭 도착을 확인하지 못했습니다({chk.reason})."}
    return {"ok": True}


async def set_collect_dept_all(page: Any) -> bool:
    """결의부서 = 전체선택(돋보기 → 목록 로드 대기 → checkAll → 적용 → **표시값 확인**).

    ⚠⚠ 이 값은 '보조 조건'이 아니라 **수집 대상 집합을 정의**한다(2026-07-27 라이브 규명):
      실패하면 결의부서가 로그인 부서("회계팀")로 남아 그 부서 결의서만 수집되고, 전표조회승인
      대상 행들의 결의서번호와 **하나도 겹치지 않아**(실측: 맵 4건 / 커버 0건) 전 행이
      '맵에 없음'으로 건너뛰어진다 = 에이전트가 아무것도 처리하지 못한다.

    ⚠ 첫 시도만 실패하는 레이스가 실측됐다(같은 스텝을 곧바로 다시 부르면 open_picker·
      checkAll(n=46)·apply 가 전부 성공했다). 탭 진입 직후 피커/그리드 준비가 덜 된 상태로
      보인다 — 그래서 **결과검증형 재시도**로 감싼다: '전체선택된 표시값'이 될 때까지
      (실시간 점증 대기) 최대 3회 다시 시도한다.

    판정은 표시값이다 — 전체선택이 반영되면 "회계팀 외 45건"처럼 **'외 N건'** 형태가 된다
    (단일 부서 계정 대비: checkAll 이 1건만 체크한 경우도 성공으로 인정).
    """
    checked: dict = {"n": 0}

    async def attempt() -> None:
        if not await vr_steps._open_picker(page, COLLECT_DEPT_LABEL):
            return
        res: Any = None
        for _ in range(vr_steps._DEPT_LOAD_TRIES):
            res = await page.evaluate(vr_js.POPUP_CHECK_ALL_JS)
            if isinstance(res, dict) and res.get("ok") and (res.get("n") or 0) > 0:
                break
            await page.wait_for_timeout(vr_steps._DEPT_LOAD_INTERVAL_MS)
        if not (isinstance(res, dict) and res.get("ok") and (res.get("n") or 0) > 0):
            return
        checked["n"] = int(res.get("n") or 0)
        await page.wait_for_timeout(vr_steps._DEPT_APPLY_SETTLE_MS)
        await vr_steps._apply_popup(page)

    def reflected(v: Any) -> bool:
        text = " ".join(str(v or "").split())
        if not text:
            return False
        if _MULTI_DEPT_RE.search(text):
            return True  # '외 N건' = 다부서 선택 반영.
        return checked["n"] == 1  # 부서가 하나뿐인 계정.

    await attempt()
    chk = await verify.confirm(
        lambda: page.evaluate(js_lib.FIELD_DISPLAY_JS, COLLECT_DEPT_LABEL),
        reflected,
        timing=verify.ASYNC,
        what="결의부서 전체선택",
        expected="'외 N건' 표시",
        reapply=attempt,
    )
    return bool(chk)


async def clear_collect_writer(page: Any) -> bool:
    """결의자(#WRT_EMP_NO_C) 비움 — 로그인 계정 소속으로 결과가 좁혀지지 않게.

    clear() 호출 성공에 더해 **표시값이 실제로 비었는지** 확인한다(즉시 반영 계열). 라벨을
    못 읽으면 확인 불가로 보고 통과(best-effort — 호출부가 warn). 반환 bool.
    """
    ok = await page.evaluate(js.CLEAR_WRT_EMP_JS)
    if not ok:
        return False
    chk = await verify.confirm_display_empty(page, COLLECT_WRITER_LABEL, timing=verify.INSTANT)
    return bool(chk or chk.unknown)


async def set_collect_period(page: Any, accounting_ym: str | None = None) -> bool:
    """회계일 세팅 — accounting_ym(YYYYMM) override 시 그 월의 1일~말일로, None 이면 미조작
    (폼 기본값=당월, 프로브 확정 경로). best-effort(실패해도 폼 기본값으로 진행). 반환 bool.

    ⚠ 프로브 확정 조회는 이 필드를 건드리지 않았다(폼 기본 당월으로 카드 결과 정상 수집).
      override 경로(특정월)는 미검증이므로 실패해도 조용히 폼 기본값에 맡긴다.
    """
    if not accounting_ym:
        return True  # 폼 기본값(당월) 유지 — 프로브 확정 경로.
    y, m = int(accounting_ym[:4]), int(accounting_ym[4:6])
    last = calendar.monthrange(y, m)[1]
    start = f"{y:04d}{m:02d}01"
    end = f"{y:04d}{m:02d}{last:02d}"
    ok = await page.evaluate(js.SET_PERIOD_RANGE_JS, {"start": start, "end": end})
    if not ok:
        return False
    # 입력값의 연월이 목표월인지 확인(즉시 반영 계열 — input 직접 세팅). 위젯 구조를 못 읽으면
    # 확인 불가로 보고 통과(이 경로 자체가 미검증 override 라 하드 실패시키지 않는다).
    chk = await verify.confirm(
        lambda: page.evaluate(js_lib.PERIOD_VALUE_JS, COLLECT_PERIOD_FIELD),
        lambda v: isinstance(v, dict)
        and bool(v.get("found"))
        and bool(v.get("ym"))
        and all(y == accounting_ym for y in v["ym"]),
        timing=verify.INSTANT,
        what="결의서조회승인 회계일",
        expected=accounting_ym,
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("found")),
    )
    return bool(chk or chk.unknown)


async def set_collect_gubun_card(page: Any) -> bool:
    """결의구분 = 카드 — dropdownlist 세팅 후 **현재 선택 텍스트 재확인**(되돌림 대비 재세팅 재시도).

    ⚠ 여기가 틀리면 카드가 아닌 결의구분으로 결의서가 수집돼 payment_map 이 통째로 어긋나고,
      loop_approvals 가 모든 행을 '맵에 없음'으로 건너뛴다(2026-07-24 실측 증상). 호출부는 이
      반환값이 False 면 **조회로 진행하지 않는다**. 반환 bool.
    """
    payload = {"selector": GUBUN_SELECT, "text": GUBUN_CARD_TEXT}
    r = await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, payload)
    if not (isinstance(r, dict) and r.get("ok")):
        return False
    chk = await verify.confirm_select(
        page,
        GUBUN_SELECT,
        GUBUN_CARD_TEXT,
        reapply=lambda: page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, payload),
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("ok")),
    )
    return bool(chk or chk.unknown)


async def run_collect_query(page: Any) -> bool:
    """결의서조회승인 조회 실행 — **가시** 조회버튼(다중탭이라 여럿) 실클릭. 폴백=BTN_LOOKUP.

    ⚠ 스테일 결과 방지(2026-07-27): 종전에는 클릭 후 고정 2초만 기다리고 무조건 성공을 돌려줘,
      느린 세션에서 read_payment_map 이 **직전 결과 그리드**를 읽을 수 있었다. 이제 매 확인
      직전에 로딩 오버레이가 사라졌는지 정착(settle)시키고, 가시 마스터 그리드가 rowcount 를
      낼 수 있는 상태인지 확인한다(0건도 정상 — 확인 대상은 '응답 가능 상태'이지 '결과 존재'가
      아니다). 반환 bool(=확인된 조회 완료).
    """
    rect = await page.evaluate(js.VISIBLE_LOOKUP_BTN_RECT_JS)
    if rect:
        await mouse_click(page, rect["x"], rect["y"])
    else:
        await js_click(page, selectors.BTN_LOOKUP)
    chk = await verify.confirm(
        lambda: page.evaluate(js.VISIBLE_MASTER_ROWCOUNT_JS),
        lambda v: isinstance(v, int) and v >= 0,
        timing=verify.HEAVY,
        what="결의서조회승인 조회 결과",
        expected="rowcount>=0",
        settle=lambda: vr_steps.wait_loading_overlay_gone(page),
    )
    return bool(chk)


async def read_payment_map(page: Any, limit: int = 500) -> dict:
    """가시 마스터 그리드에서 ABDOCU_NO→GWDOCU_NO(결재번호) 맵을 만든다. 반환
    {ok, n, map:{ABDOCU_NO: GWDOCU_NO}}. ABDOCU_NO/GWDOCU_NO 둘 다 있는 행만 담는다."""
    dump = await page.evaluate(js.VISIBLE_MASTER_ROWS_JS, limit)
    if not (isinstance(dump, dict) and dump.get("ok")):
        return {"ok": False, "reason": (dump or {}).get("reason", "no-grid"), "map": {}}
    mapping: dict[str, str] = {}
    for row in dump.get("rows", []):
        ab = row.get("ABDOCU_NO")
        gw = row.get("GWDOCU_NO")
        # 공백 정규화 — loop_approvals 의 lookup(ab_key.strip())과 키를 맞춘다(그리드 표기값의
        # 앞뒤 공백으로 정확일치가 조용히 실패하는 것 방지).
        ab_key = str(ab).strip() if ab else ""
        gw_val = str(gw).strip() if gw else ""
        if ab_key and gw_val:
            mapping[ab_key] = gw_val
    return {"ok": True, "n": dump.get("n", 0), "map": mapping}


async def switch_back_to_voucher_tab(page: Any) -> bool:
    """캐시된 전표조회승인 탭으로 복귀(상태 유지) + **도착 확인**. 반환 bool.

    ⚠ 클릭 성공은 복귀가 아니다 — 결재 순회가 곧바로 쓸 **결재 버튼이 실제로 보이는지**를
    확인해야 엉뚱한 탭에서 결재를 누르는 사고를 막는다(화면 전환 = HEAVY 스케줄).
    """
    try:
        await page.click(js.TAB_BACK_VOUCHER_SELECTOR, timeout=5_000)
    except Exception:  # noqa: BLE001 — 탭 전환 실패는 호출자가 error 로 처리.
        return False
    chk = await verify.confirm(
        lambda: page.evaluate(vr_js.APPROVAL_BTN_RECT_JS),
        lambda v: bool(v),
        timing=verify.HEAVY,
        what="전표조회승인 탭 복귀(결재 버튼 가시)",
        expected="결재 버튼 표시",
    )
    return bool(chk)


# ══════════════════════════════════════════════════════════════════════════════
# Phase C — 결제창(EAP React) 안 참조문서 선택 sub-flow(child Page 대상)
# ⚠ '확인'/'상신' 무조건 클릭 없음 — click_refdoc_confirm 은 게이트 뒤에서만.
# ══════════════════════════════════════════════════════════════════════════════
async def open_refdoc_dialog(child: Any) -> bool:
    """결제창 하단 '참조문서 선택' 버튼(뷰포트 밖 가능) → scrollIntoView 후 좌표 재계산 클릭.
    반환 = dialog 오픈 시도 여부(버튼 못 찾으면 False)."""
    await child.evaluate(js.REFDOC_SELECT_BTN_SCROLL_JS)
    await child.wait_for_timeout(500)  # smooth-scroll 정착.
    rect = await child.evaluate(js.REFDOC_SELECT_BTN_RECT_JS)
    if not rect:
        return False
    await child.mouse.click(rect["x"], rect["y"])
    # dialog 가 실제로 떴는지 확인 — 제목 '참조문서'(리프 노드 정확일치)로 판정한다. 종전에는
    # 고정 1.5초 뒤 무조건 True 라, 안 뜬 dialog 에 문서번호를 입력·조회하고 있었다.
    # ('참조문서 선택' 버튼 텍스트는 DOM 상 '참 조 문 서'라 이 확인에 걸리지 않는다.)
    chk = await verify.confirm_visible_text(child, REFDOC_DIALOG_TITLE, timing=verify.ASYNC)
    if not chk:
        return False
    # dialog 를 뷰포트 안으로 정렬한다 — 결제창이 아래로 스크롤된 상태라 dialog 내용이 화면
    # 위(음수 y)에 놓이는 경우가 있고, 그러면 캔버스 행 클릭 같은 좌표 조작이 전부 허공을 친다.
    placed = await verify.confirm(
        lambda: child.evaluate(js.REFDOC_SCROLL_INTO_VIEW_JS),
        lambda v: isinstance(v, dict) and v.get("ok") and (v.get("box") or {}).get("y", -1) >= 0,
        timing=verify.ASYNC,
        what="참조문서 dialog 뷰포트 정렬",
        expected="box.y >= 0",
    )
    if not placed:
        logger.info("참조문서 dialog 를 뷰포트 안으로 정렬하지 못했습니다: %s", placed.reason)
    return True


async def expand_refdoc_filter(child: Any) -> bool:
    """참조문서 dialog 필터 패널을 펴서 **'조회' 버튼이 보이는 상태**로 만든다(결과검증형).

    ⚠ 근본원인 확정(2026-07-27 사용자 리포트 + DOM 프로브): 이 셀렉터는 **토글**이다. 종전에는
      상태를 보지 않고 무조건 한 번 클릭하고 성공을 반환했다 —
        · 접혀 있으면 → 펴진다(정상)
        · **이미 펴져 있으면 → 접힌다** → '조회' 버튼이 DOM 에서 사라진다
      그리고 `run_refdoc_search` 는 버튼을 못 찾으면 조용히 False 를 돌려주고 호출부가 그걸
      무시했기 때문에, **어떤 건 조회가 눌리고 어떤 건 안 눌리는** 산발적 증상이 됐다.
      (실측: dialog 오픈 직후 '조회' 버튼 후보 0개 → 패널 확장 후 1개.)

    그래서 이제 **목표 상태**로 판정한다: 이미 조회 버튼이 보이면 아무것도 누르지 않고,
    안 보이면 토글한 뒤 버튼이 보일 때까지 확인한다. 반환 = 최종 가시 여부.
    """

    async def search_btn_visible() -> Any:
        return await child.evaluate(js.REFDOC_SEARCH_BTN_RECT_JS)

    if await search_btn_visible():
        return True  # 이미 펴짐 — 다시 누르면 접힌다(역방향 토글 방지).
    try:
        await child.click(js.REFDOC_FILTER_EXPAND_SELECTOR, timeout=5_000)
    except Exception:  # noqa: BLE001 — 토글 자체를 못 찾으면 확인 단계에서 False 로 드러난다.
        logger.debug("참조문서 필터 토글 클릭 실패", exc_info=True)
    chk = await verify.confirm(
        search_btn_visible,
        lambda v: bool(v),
        timing=verify.ASYNC,
        what="참조문서 '조회' 버튼",
        expected="표시(필터 패널 확장)",
    )
    return bool(chk)


async def fill_refdoc_docno(child: Any, value: str) -> bool:
    """문서번호 입력 — **요소 클릭**으로 포커스를 잡고 키보드로 지우고 타이핑한다.

    ⚠ 좌표 클릭 폐기(2026-07-27 실측): 입력칸이 뷰포트 밖(y=-504)에 있는 경우가 있어 좌표를
      누르면 아무 데도 포커스가 가지 않고, 그런데도 '입력했다'로 진행돼 필터 없는 조회가 됐다.
      요소 클릭은 Playwright 가 스크롤·가시성을 보장한다.
    ⚠ React controlled input 이라 값 직접 대입(setValue) 금지 — End+Backspace 다회로 비우고
      키보드로 타이핑한 뒤 **readback 으로 확인**한다(불일치 시 1회 재시도).
    """
    for _attempt in range(2):
        marked = await child.evaluate(js.REFDOC_MARK_JS, {"kind": "docno"})
        if not (isinstance(marked, dict) and marked.get("ok")):
            logger.info("문서번호 입력칸을 찾지 못했습니다: %s", (marked or {}).get("reason"))
            return False
        try:
            await child.click(_MARKED.format("docno"), timeout=5_000)
        except Exception:  # noqa: BLE001 — 다음 시도에서 다시 잡는다.
            logger.debug("문서번호 입력칸 클릭 실패", exc_info=True)
            continue
        await child.keyboard.press("End")
        for _ in range(REFDOC_CLEAR_BACKSPACES):
            await child.keyboard.press("Backspace")
        if value:
            await child.keyboard.type(value)
        await child.wait_for_timeout(300)
        actual = await child.evaluate(js.REFDOC_DOCNO_VALUE_JS)
        if (actual or "") == value:
            return True
    return False


# 마커 속성으로 지정한 요소를 Playwright **요소 클릭**으로 누른다 — 좌표 클릭을 쓰지 않는다.
_MARKED = "[data-nb-refdoc='{}']"


async def _click_marked(child: Any, kind: str, *, index: int = 0) -> dict:
    """dialog 안에서 대상 요소를 찾아 마킹하고 **요소로** 클릭한다.

    ⚠ 왜 좌표가 아니라 요소 클릭인가(2026-07-27 실측): 참조문서 dialog 는 더존 캔버스가 아니라
      **일반 DOM(React/OBT)** 이다. 좌표 클릭은 (a) dialog 밖 동명 버튼을 잡거나 (b) 스크롤로
      화면 밖(y=-429)이 된 좌표를 눌러 **아무 일도 안 일어나는데 성공으로 보고**됐다.
      요소 클릭은 Playwright 가 자동으로 스크롤·가시성·안정성을 확인하고 누른다.
      (캔버스 그리드의 행 선택만은 좌표가 불가피하다 — select_refdoc_first_row 참조.)
    """
    marked = await child.evaluate(js.REFDOC_MARK_JS, {"kind": kind, "index": index})
    if not (isinstance(marked, dict) and marked.get("ok")):
        return {"ok": False, "reason": (marked or {}).get("reason", "mark-failed")}
    try:
        await child.click(_MARKED.format(kind), timeout=5_000)
    except Exception as exc:  # noqa: BLE001 — 클릭 실패는 호출부가 판정한다.
        return {"ok": False, "reason": f"click-failed: {str(exc)[:80]}"}
    return {"ok": True, **{k: v for k, v in marked.items() if k in ("count", "index")}}


async def read_refdoc_state(child: Any) -> dict:
    """참조문서 dialog 상태(조회 건수·없음 문구·선택목록 비어있음·그리드 박스) 읽기 전용."""
    return await child.evaluate(js.REFDOC_STATE_JS)


async def run_refdoc_search(child: Any) -> bool:
    """dialog 안 '조회' 버튼을 **요소로** 클릭한다. 반환 = 실제로 눌렀는지.

    ⚠ False 는 "결과 0건"이 아니라 **조회를 누르지도 못했다**는 뜻이다 — 호출부는 이 둘을 반드시
      구분해 로그해야 한다.
    ⚠ 1회 재시도(2026-07-27 사용자 리포트: 4건 중 1건은 조회조차 하지 않고 종료): 실패 원인이
      대개 dialog 가 뷰포트 밖으로 밀린 상태라, 재정렬 후 다시 시도한다.
    """
    res = await _click_marked(child, "search")
    if res.get("ok"):
        return True
    logger.info("참조문서 조회 버튼 클릭 실패(재정렬 후 재시도): %s", res.get("reason"))
    try:
        await child.evaluate(js.REFDOC_SCROLL_INTO_VIEW_JS)
    except Exception:  # noqa: BLE001 — 재정렬 실패해도 아래 재시도는 해본다.
        logger.debug("dialog 재정렬 실패", exc_info=True)
    retry = await _click_marked(child, "search")
    if not retry.get("ok"):
        logger.info("참조문서 조회 버튼 클릭 재시도 실패: %s", retry.get("reason"))
        return False
    return True


async def poll_refdoc_result(child: Any, prev_total: int | None = None) -> dict:
    """조회 결과가 화면에 **갱신될 때까지** 기다린다(캔버스 그리드라 DOM 행 스캔 불가).

    :param prev_total: **조회 버튼을 누르기 전에** 읽어둔 총 건수. 갱신 판정의 기준선이다.

    ⚠ 근본원인(2026-07-27 사용자 리포트 "조회만 하고 종료"): 종전 구현은 (a) 기준선을 조회
      **클릭 이후**에 읽고 (b) '총계가 존재하면 완료'로 판정했다. 그래서 필터 반영 전의
      **직전 총계(예: 2714)** 를 곧바로 완료로 읽었고, 호출부의 `total > 1` 게이트가
      "대상을 특정할 수 없다"며 선택·이동 없이 끝냈다 — 4건 중 3건이 조회만 하고 종료한 증상.

    판정 앵커는 dialog 텍스트다: '조회된 데이터가 없습니다.'(0건) 또는 **바뀐** '총 N개'.
    """

    def settled(v: Any) -> bool:
        if not (isinstance(v, dict) and v.get("ok")):
            return False
        if v.get("noData"):
            return True
        total = v.get("total")
        if total is None:
            return False
        # 기준선을 모르면 '건수를 읽었다'로 만족(첫 조회), 알면 **바뀌어야** 반영으로 본다.
        return prev_total is None or total != prev_total

    chk = await verify.confirm(
        lambda: read_refdoc_state(child),
        settled,
        timing=verify.HEAVY,
        what="참조문서 조회 결과",
        expected=f"'조회된 데이터가 없습니다' 또는 총 건수 변경(직전 {prev_total})",
    )
    state = chk.actual if isinstance(chk.actual, dict) else {}
    return {**state, "settled": bool(chk), "prev_total": prev_total}


async def select_refdoc_first_row(child: Any) -> bool:
    """참조문서 목록(**RealGrid 캔버스**) 첫 행의 **체크박스**를 클릭해 선택한다.

    ⚠ 여기만 좌표 클릭이 불가피하다 — 캔버스라 행/체크박스가 DOM 요소가 아니다(옴니솔 그리드와
      동일). 화면 실측(2026-07-27): 그리드 첫 컬럼이 체크박스이고, 그 중심은 그리드 박스
      좌측 +16px · 헤더(30px) 아래 첫 행 중앙(+12px)이다.
    ⚠ 행 **중앙**(제목 셀)을 눌러서는 안 된다 — 실측에서 단일/더블 클릭 모두 선택으로 이어지지
      않았고(이동 버튼을 눌러도 반영 없음), 체크박스 열을 눌렀을 때만 이동이 성립했다.
    ⚠ 선행 조건: dialog 가 뷰포트 안에 있어야 한다(open_refdoc_dialog 가 정렬한다) — 화면 밖
      좌표(음수 y)를 누르면 아무 일도 일어나지 않는다.
    """
    state = await read_refdoc_state(child)
    box = state.get("topGrid") if isinstance(state, dict) else None
    if not box:
        return False
    if box.get("y", -1) < 0:
        logger.info("참조문서 목록이 뷰포트 밖입니다(y=%s) — 선택을 시도하지 않습니다.", box.get("y"))
        return False
    await child.mouse.click(box["x"] + _GRID_CHECKBOX_DX, box["y"] + _GRID_HEADER_H + _GRID_ROW_H // 2)
    await child.wait_for_timeout(300)
    return True


async def read_refdoc_grids(child: Any) -> dict:
    """참조문서 dialog 두 그리드의 **행 수·문서번호**를 gridView API 로 읽는다(읽기 전용).

    반환 {ok, top:{count, docNos}, selected:{count, docNos}} | {ok:False, reason}.
    ⚠ 캔버스라 DOM 으로는 못 읽지만 컨테이너 **부모**(id=grid_<uuid>)의 `gridView` 로 읽힌다
      (2026-07-27 사용자 지적으로 발견) — 간접 신호('선택된 목록이 없습니다.')를 대체한다.
    """
    return await child.evaluate(js.REFDOC_GRID_ROWS_JS)


async def selected_list_count(child: Any) -> int | None:
    """'선택된 문서 목록'의 **행 수**. None = 판독 불가(그리드 미준비 등)."""
    g = await read_refdoc_grids(child)
    if not (isinstance(g, dict) and g.get("ok")):
        return None
    return (g.get("selected") or {}).get("count")


async def selected_list_has_doc(child: Any, docu_no: str) -> bool | None:
    """'선택된 문서 목록'에 **그 문서번호**가 있는지. None = 판독 불가."""
    g = await read_refdoc_grids(child)
    if not (isinstance(g, dict) and g.get("ok")):
        return None
    want = " ".join(str(docu_no or "").split())
    return any(" ".join(str(d).split()) == want for d in (g.get("selected") or {}).get("docNos") or [])


async def move_refdoc_down(child: Any, docu_no: str | None = None) -> dict:
    """선택한 행을 '선택된 문서 목록'으로 옮기고 **첨부 결과를 실제로 확인**한다.

    성공 조건(사용자 확정 2026-07-27): 첨부 후 **참조문서 1건 이상**. docu_no 를 주면
    그 문서번호가 목록에 실제로 있는지까지 대조한다(gridView 로 행 데이터를 읽는다).
    반환 {ok, verified, count?, doc_matched?, button_index?, pre_count?, reason?}.

    ⚠ 종전 실패 원인(2026-07-27 실측): 이동 버튼은 두 그리드 **사이**의 라벨 없는 27×27 아이콘
      버튼 2개인데, 기존 리더는 class/aria 에 down|아래|arrow-down 이 있는 요소를 찾아 **어느
      것도 해당되지 않았고** 폴백 좌표(477,412 — 페이지네이션 위 빈 공간)를 눌렀다. 그 구간에는
      **페이지네이션**도 있어 후보를 좁히지 않으면 페이지만 넘어간다.
    두 버튼 중 어느 쪽이 '아래(추가)'인지 DOM 으로 알 수 없어(둘 다 라벨 없음) **결과검증형**으로
    왼쪽부터 눌러보고 목록이 실제로 늘어나면 확정한다.
    """
    pre_count = await selected_list_count(child)
    if pre_count is None:
        return {"ok": False, "verified": False, "reason": "참조문서 목록을 읽지 못했습니다(그리드 미준비)."}

    def grew(v: Any) -> bool:
        # 1건 이상 + (가능하면) 대상 문서번호 포함 + 이동 전보다 증가.
        if not (isinstance(v, dict) and v.get("ok")):
            return False
        sel = v.get("selected") or {}
        count = sel.get("count") or 0
        if count < 1 or count <= pre_count:
            return False
        if not docu_no:
            return True
        want = " ".join(str(docu_no).split())
        return any(" ".join(str(d).split()) == want for d in sel.get("docNos") or [])

    tried: list[dict] = []
    for index in range(_MOVE_BTN_CANDIDATES):
        res = await _click_marked(child, "move", index=index)
        tried.append({"index": index, **res})
        if not res.get("ok"):
            continue
        chk = await verify.confirm(
            lambda: read_refdoc_grids(child),
            grew,
            timing=verify.ASYNC,
            what=f"참조문서 첨부(이동 버튼 {index + 1})",
            expected=f"선택 목록 {pre_count}건 → 1건 이상 증가"
            + (f" 및 {docu_no} 포함" if docu_no else ""),
            unknown_when=lambda v: not (isinstance(v, dict) and v.get("ok")),
        )
        if chk:
            sel = (chk.actual or {}).get("selected") or {}
            return {
                "ok": True,
                "verified": True,
                "count": sel.get("count"),
                "doc_matched": bool(docu_no),
                "button_index": index,
                "pre_count": pre_count,
                "tried": tried,
            }
        if (res.get("count") or 1) <= index + 1:
            break
    after = await selected_list_count(child)
    return {
        "ok": False,
        "verified": False,
        "count": after,
        "pre_count": pre_count,
        "tried": tried,
        "reason": f"이동 후에도 참조문서가 첨부되지 않았습니다(선택 목록 {pre_count}건 → {after}건).",
    }


async def click_refdoc_confirm(child: Any) -> bool:
    """⚠ 게이트 전용 — 참조문서 '확인'(파란 OBTButton) 클릭. reference_doc 훅의 allow_confirm
    (기본 False) 뒤에서만 호출된다. 기본 실행 경로에서는 절대 도달하지 않는다(절대 안전)."""
    rect = await child.evaluate(js.REFDOC_CONFIRM_BTN_RECT_JS)
    if not rect:
        return False
    await child.mouse.click(rect["x"], rect["y"])
    await child.wait_for_timeout(500)
    return True


async def close_refdoc_dialog(child: Any) -> bool:
    """참조문서 dialog 닫기(X) — 확인/선택 미클릭 상태로 취소(비영속 유지). best-effort."""
    rect = await child.evaluate(js.REFDOC_CLOSE_BTN_RECT_JS)
    if not rect:
        return False
    await child.mouse.click(rect["x"], rect["y"])
    await child.wait_for_timeout(500)
    return True
