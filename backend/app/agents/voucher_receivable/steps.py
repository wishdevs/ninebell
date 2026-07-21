"""전표조회승인(voucher-receivable) 스텝 프리미티브 — 브라우저 조작 단위(노드가 조립).

e2e/voucher_receivable_probe.py(3회 그린) 로직을 그대로 이식한다: 조회조건 8필드 세팅 →
조회(F2) → 행 checkRow → 결제(결재)창(별도 팝업 Page) 열기/렌더대기/닫기. 셀렉터/JS 는
app.agents.voucher_receivable.js + nbkit.omnisol.{js_lib,selectors} 단일소스에서 가져온다.

⚠ 절대 안전: 이 모듈에는 결제창의 **상신·보관 버튼을 클릭하는 함수가 없다**. open_approval 은
   자식 Page 핸들을 돌려줄 뿐이고, close_child 는 창을 닫기만 한다(비영속 확정 ✅). F7 저장·F6
   삭제·실제 상신 없음.
"""

from __future__ import annotations

import logging
from typing import Any

from nbkit.browser.actions import js_click, mouse_click
from nbkit.omnisol import js_lib, selectors
from nbkit.omnisol.modals import dismiss_notice_popup

from . import js

logger = logging.getLogger(__name__)

# ── 조회 조건 목표값(D2 실측 — 대부분 고정) ─────────────────────────────────────
DEPT_LABEL = "작성부서"  # 전체선택(checkAll)
GWAPRVLST_LABEL = "전자결재상태"
GWAPRVLST_TARGET = "저장"  # SYSDEF_NM='저장'(code=1)
DOCU_TYPE_LABEL = "전표유형"
# 전표유형(SYSDEF_NM) 대상 — 에이전트(=전표유형)별로만 다르고 나머지 플로우는 전부 공유한다.
DOCU_TYPES_RECEIVABLE = ("국내매출", "해외매출")  # 외상매출금(voucher-receivable)
# 외상매입금(voucher-payable) 전표유형 — 내수구매(SYSDEF_CD=31). 사용자 확정 2026-07-21
#   ("내구수매"는 오타였고 피커 실존값은 "내수구매"임을 프로브로 확인).
DOCU_TYPES_PAYABLE = ("내수구매",)
DOCU_TYPE_TARGETS = DOCU_TYPES_RECEIVABLE  # set_docu_types 기본값(하위호환)
DOCU_ST_SELECT = "#s_docu_st_cd"  # native kendo dropdownlist
DOCU_ST_TARGET = "미결"

# 결제창 렌더 완료 폴링 상한(SSO 리다이렉트+SPA 마운트 1~12s 편차 — 고정대기 금지, 조건폴링).
CHILD_READY_CAP_MS = 25_000
CHILD_READY_INTERVAL_MS = 1_000
# 결과 조회 rowcount 안정 폴링(그리드 로딩 대기).
QUERY_POLL_TRIES = 30
QUERY_POLL_INTERVAL_MS = 400


# ══════════════════════════════════════════════════════════════════════════════
# D2 — 조회 조건 8필드 세팅(회계단위·역분개여부는 기본값이라 스텝 없음)
# ══════════════════════════════════════════════════════════════════════════════
async def expand_condition_panel(page: Any) -> bool:
    """조회조건 패널 확장 토글(첫 매치) 클릭(전표유형이 optional-area 라 펼쳐야 보임). 없으면 no-op.

    ⚠ set_query 진입 시 1회 워밍용 — 토글이 여러 개면 이 함수가 잡는 건 그중 하나뿐이라
    전표유형이 보인다는 보장이 없다. 그 보장이 필요하면 ensure_field_visible 을 쓸 것.
    """
    rect = await page.evaluate(js.EXPAND_TOGGLE_RECT_JS)
    if not rect:
        return False
    await mouse_click(page, rect["x"], rect["y"])
    await page.wait_for_timeout(1_000)
    return True


async def ensure_field_visible(page: Any, label: str, *, max_toggles: int = 4) -> bool:
    """라벨이 화면에 보일 때까지(FIELD_LABEL_VISIBLE_JS) 확장 토글을 좌→우 순으로 하나씩
    **결과검증형**으로 눌러본다 — 실측(2026-07-21, 도메인전문가): 확장 토글이 여러 개일 수
    있고 어느 것이 목표 필드(전표유형)를 드러내는지 미리 알 수 없다. 이미 보이면 아무것도
    클릭하지 않는다(역방향 접힘 방지 — 이미 펼쳐진 토글을 다시 누르면 접힐 수 있다).

    다른 필드(작성부서·회계일·작성자·전표상태·전자결재상태) 조작 도중 패널이 재접히는
    레이스도 방어한다(호출자가 픽커를 열기 **직전**에 호출). 반환 = 최종 가시 여부.
    """
    if await page.evaluate(js.FIELD_LABEL_VISIBLE_JS, label):
        return True
    rects = await page.evaluate(js.EXPAND_TOGGLE_RECTS_JS) or []
    for rect in rects[:max_toggles]:
        await mouse_click(page, rect["x"], rect["y"])
        await page.wait_for_timeout(1_000)
        if await page.evaluate(js.FIELD_LABEL_VISIBLE_JS, label):
            return True
    return False


async def _open_picker(
    page: Any, label: str, *, ready_cap_ms: int = 12_000, ready_interval_ms: int = 300
) -> bool:
    """라벨의 돋보기(검색) 버튼을 실클릭해 MultiCodePicker 팝업을 연다.

    ⚠ 근본원인 확정(2026-07-21 voucher-payable 라이브 스모크 3회 재현): 클릭 후 고정 1200ms
    대기만으로 곧장 checkAll/checkRow 를 호출하면, 서버 응답이 느린 세션에서 팝업의 RealGrid
    가 아직 안 붙어 `Cannot read properties of undefined (reading '_grid')` 로 **그래프 전체가
    크래시**한다(우아한 실패가 아님 — set_query 가 error 로 단락하지 못하고 runner 의 최상위
    except 로 떨어짐). 고정 1200ms 대기 뒤, 그리드가 실제로 붙었는지(`POPUP_GRID_READY_JS`)
    조건 폴링한다(상한 내 미확인이어도 호출자는 계속 진행 — 호출부 JS 가 이제 grid-not-ready
    를 우아하게 반환하므로 최종 방어선이 있다).
    ⚠ 상한 12s(2026-07-21 실측 상향): 같은 세션에서 user_type 전환이 4~5.6s 로 관측될 만큼
    서버 응답이 느린 구간이 있었다 — 5s 상한으론 그 구간에 그리드 부착이 끝나지 못했다.
    `page.wait_for_timeout` 은 delay_scale 로 스케일되지만 `page.evaluate` 왕복(실 네트워크)은
    스케일되지 않으므로, 상한을 넉넉히 잡아도 그리드가 실제로 빨리 붙으면 즉시 break 한다.
    ⚠ just-in-time 공지 팝업 재확인(2026-07-21 실측): 로그인 시 1회 닫아도, 공지 팝업이
    **비동기 지연 로드**돼(localStorage `gerp:notice:loaded:time`) 그 시점 이후에 떠 화면을
    덮어 클릭을 가로채는 레이스가 있었다. 실제 클릭 **직전**(매 피커 호출마다) 공유
    ``dismiss_notice_popup`` 을 대기 없이(appear_cap_ms=0) 한 번 더 확인해 방어한다.
    """
    await dismiss_notice_popup(page, appear_cap_ms=0)
    rect = await page.evaluate(js.FIELD_SEARCH_BTN_RECT_JS, label)
    if not rect:
        return False
    await mouse_click(page, rect["x"], rect["y"])
    await page.wait_for_timeout(1_200)
    waited = 0
    while waited < ready_cap_ms:
        try:
            ready = await page.evaluate(js.POPUP_GRID_READY_JS)
        except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
            return True
        if ready:
            break
        await page.wait_for_timeout(ready_interval_ms)
        waited += ready_interval_ms
    return True


async def _apply_popup(page: Any) -> bool:
    """최상단 팝업의 '적용' 버튼을 실클릭(팝업은 적용 후 자동 닫힘)."""
    apply_rect = await page.evaluate(js.POPUP_APPLY_BTN_JS)
    if not apply_rect:
        return False
    await mouse_click(page, apply_rect["x"], apply_rect["y"])
    await page.wait_for_timeout(1_200)
    return True


async def set_dept_all(page: Any) -> dict:
    """작성부서 = 전체선택 — 돋보기 → 팝업 checkAll() → 적용. 반환 {ok, n?, display?}."""
    if not await _open_picker(page, DEPT_LABEL):
        return {"ok": False, "reason": "작성부서 돋보기 버튼을 찾지 못했습니다."}
    res = await page.evaluate(js.POPUP_CHECK_ALL_JS)
    if not (isinstance(res, dict) and res.get("ok")):
        return {"ok": False, "reason": "작성부서 팝업 전체선택(checkAll) 실패."}
    if not await _apply_popup(page):
        return {"ok": False, "reason": "작성부서 팝업 '적용' 버튼을 찾지 못했습니다."}
    display = await page.evaluate(js.FIELD_DISPLAY_JS, DEPT_LABEL)
    return {"ok": True, "n": res.get("n"), "display": display}


async def set_period_this_month(page: Any) -> dict:
    """회계일 = 당월(1일~말일) — dews periodpicker 앱 API setMonth(). ⚠ YYYYMMDD 타이핑 아님."""
    ok = await page.evaluate(js.SET_PERIOD_THIS_MONTH_JS)
    if not ok:
        return {"ok": False, "reason": "회계일 periodpicker setMonth() 호출 실패."}
    return {"ok": True}


async def clear_writer(page: Any) -> dict:
    """작성자 = 비움 — dews multicodepicker 앱 API clear()(기본선택 제거)."""
    ok = await page.evaluate(js.CLEAR_WRITER_JS)
    if not ok:
        return {"ok": False, "reason": "작성자 multicodepicker clear() 호출 실패."}
    return {"ok": True}


async def set_docu_status(page: Any, text: str = DOCU_ST_TARGET) -> dict:
    """전표상태 = 미결 — native kendo dropdownlist(KENDO_SET_DROPDOWN_BY_TEXT_JS 재사용)."""
    r = await page.evaluate(
        js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": DOCU_ST_SELECT, "text": text}
    )
    if not (isinstance(r, dict) and r.get("ok")):
        return {"ok": False, "reason": f"전표상태 '{text}' 설정 실패: {r}"}
    await page.wait_for_timeout(500)
    return {"ok": True}


async def set_gwaprvlst(page: Any, target: str = GWAPRVLST_TARGET) -> dict:
    """전자결재상태 = 저장 — MultiCodePicker 팝업 RealGrid checkRow(SYSDEF_NM==target) → 적용."""
    if not await _open_picker(page, GWAPRVLST_LABEL):
        return {"ok": False, "reason": "전자결재상태 돋보기 버튼을 찾지 못했습니다."}
    res = await page.evaluate(js.POPUP_CHECK_ROWS_JS, [[target], "SYSDEF_NM"])
    if not (isinstance(res, dict) and res.get("ok") and res.get("idxs")):
        return {"ok": False, "reason": f"전자결재상태 '{target}' 행을 팝업에서 찾지 못했습니다: {res}"}
    if not await _apply_popup(page):
        return {"ok": False, "reason": "전자결재상태 팝업 '적용' 버튼을 찾지 못했습니다."}
    return {"ok": True, "checked": res.get("idxs")}


async def set_docu_types(page: Any, targets: tuple[str, ...] = DOCU_TYPE_TARGETS) -> dict:
    """전표유형 = 국내매출+해외매출 — MultiCodePicker 팝업 다중 checkRow(SYSDEF_NM==target) → 적용.

    전표유형은 optional-area 라 열기 직전에 ensure_field_visible 로 가시성을 보장한다.
    ⚠ 실측(2026-07-21, 라이브 스모크 + 도메인전문가 확인): set_query 앞단의 1회
      expand_condition_panel 은 확장 토글이 **여러 개**라 전표유형을 드러내는 토글을 못 누를
      수 있고, 또 다른 4개 필드(작성부서·회계일·작성자·전표상태·전자결재상태) 조작 도중 패널이
      **재접힘**하는 레이스도 관찰됐다 — 접힌 상태의 돋보기 버튼은 rect 가 0×0 이라
      `_open_picker` 가 "찾음"으로 오판해 (0,0) 을 클릭하고 팝업이 안 뜬다(no-popup). 열기
      직전에 ensure_field_visible(결과검증형: 좌→우 토글을 하나씩 시도, 이미 보이면 미클릭)로
      가시성을 보장한다(고정 1회 expand 대신 조건 확인 — 타이밍 카테고리 수정).
    """
    if not await ensure_field_visible(page, DOCU_TYPE_LABEL):
        return {"ok": False, "reason": "전표유형 필드가 어떤 확장 토글로도 보이지 않았습니다."}
    if not await _open_picker(page, DOCU_TYPE_LABEL):
        return {"ok": False, "reason": "전표유형 돋보기 버튼을 찾지 못했습니다(패널 확장 확인)."}
    # ⚠ 실측(2026-07-21 읽기전용 진단, e2e/voucher_receivable_docu_type_diag.py): 이 팝업의
    # 실제 RealGrid 필드는 전자결재상태 팝업과 동일한 범용 코드테이블 스키마
    # SYSDEF_CD/SYSDEF_NM 이다 — 'DOCU_NM'/'DOCU_CD' 필드는 이 팝업엔 없다(2026-07-20 프로브
    # 기록이 실측과 어긋남 — 코드/명칭 레벨 불일치, PROCESS.md D2 정정 대상).
    res = await page.evaluate(js.POPUP_CHECK_ROWS_JS, [list(targets), "SYSDEF_NM"])
    checked = res.get("idxs") if isinstance(res, dict) else None
    if not (isinstance(res, dict) and res.get("ok") and checked and len(checked) == len(targets)):
        return {"ok": False, "reason": f"전표유형 {list(targets)} 전부를 팝업에서 찾지 못했습니다: {res}"}
    if not await _apply_popup(page):
        return {"ok": False, "reason": "전표유형 팝업 '적용' 버튼을 찾지 못했습니다."}
    return {"ok": True, "checked": checked}


# ══════════════════════════════════════════════════════════════════════════════
# D3 — 조회 실행 + 결과 그리드 읽기
# ══════════════════════════════════════════════════════════════════════════════
async def run_query(page: Any) -> dict:
    """조회(F2, BTN_LOOKUP) → 마스터 그리드(index 0) rowcount 안정 폴링. 반환 {ok, rowcount}.

    rowcount≥0 = 정상(0이면 처리 대상 없음). 못 읽으면(-1/비정수) ok=False(그리드 미로딩).
    """
    await js_click(page, selectors.BTN_LOOKUP)
    rc: Any = -1
    for _ in range(QUERY_POLL_TRIES):
        await page.wait_for_timeout(QUERY_POLL_INTERVAL_MS)
        rc = await page.evaluate(js_lib.ROWCOUNT_BY_INDEX_JS, 0)
        if isinstance(rc, int) and rc >= 0:
            return {"ok": True, "rowcount": rc}
    return {"ok": False, "reason": "조회 결과 그리드 rowcount 를 읽지 못했습니다.", "rowcount": -1}


async def read_master_rows(page: Any, limit: int = 5) -> dict:
    """마스터 그리드 컬럼+상위 N행 덤프(로깅/디버그용). 반환 {ok, n, cols, sample}."""
    return await page.evaluate(js.MASTER_DUMP_JS, limit)


async def read_row_key(page: Any, idx: int) -> str | None:
    """마스터 그리드 idx 행의 키(DOCU_NO). 못 읽으면 None."""
    return await page.evaluate(js.READ_ROW_KEY_JS, idx)


async def read_row_abdocu_no(page: Any, idx: int) -> str | None:
    """마스터 그리드 idx 행의 결의서번호(ABDOCU_NO). 못 읽거나 없으면 None.

    카드(voucher-card) on_popup 훅이 이 값으로 payment_map(ABDOCU_NO→GWDOCU_NO)을 조회한다 —
    매출/매입 백본(on_popup=None)은 호출하지 않으므로 무영향(신규 함수 추가일 뿐).
    """
    try:
        return await page.evaluate(js.READ_ROW_ABDOCU_NO_JS, idx)
    except Exception:  # noqa: BLE001 — 테스트 스텁/버전차 방어(best-effort).
        return None


async def uncheck_all_rows(page: Any) -> bool:
    """마스터 그리드 전체 체크 해제 — 배치 순회에서 직전 대상 행의 체크가 남지 않게 한다
    (결재가 여러 문서를 잡는 위험 차단; 대상 행 checkRow 직전에 호출)."""
    return bool(await page.evaluate(js.UNCHECK_ALL_JS))


async def check_row(page: Any, idx: int) -> bool:
    """마스터 그리드 idx 행 선택 — setCurrent + checkRow(결재 대상 인식 필수)."""
    return bool(await page.evaluate(js.CHECK_ROW_JS, idx))


async def checked_row_indexes(page: Any) -> dict:
    """D7(배치 순회 정합성) — 마스터 그리드에서 현재 체크된 행 인덱스(읽기전용).

    결제(결재)를 열기 **직전**에 호출해 "정확히 1행만 체크"인지 검증하는 용도. 페이지 스텁이
    RealGrid 를 흉내내지 못하거나(단위테스트) API 버전 차이로 평가가 실패해도 예외를 흡수해
    ``{"ok": False, ...}`` 로 돌려준다 — 이 진단은 **확인 실패(soft)** 와 **확인된 위반(hard)**
    을 구분해야 하므로, 실패를 조용히 삼키고 호출자가 ok 플래그로 판단하게 한다.
    """
    try:
        return await page.evaluate(js.CHECKED_ROW_INDEXES_JS)
    except Exception as exc:  # noqa: BLE001 — 테스트 스텁/버전차 방어(soft-fail).
        return {"ok": False, "reason": str(exc)[:140]}


# ══════════════════════════════════════════════════════════════════════════════
# D5/D6 — 결제(결재)창(별도 팝업 Page) 열기 / 렌더 대기 / 닫기
# ⚠ 상신·보관 클릭 금지 — 열기·읽기·닫기만.
# ══════════════════════════════════════════════════════════════════════════════
async def wait_loading_overlay_gone(
    page: Any, *, cap_ms: int = 8_000, interval_ms: int = 200
) -> bool:
    """알려진 dews/kendo 로딩 인디케이터(`LOADING_OVERLAY_VISIBLE_JS`)가 전부 사라질 때까지
    조건 폴링(고정 대기 금지) — D7 반복 견고화의 핵심 가드.

    ⚠ 근본원인 확정(도메인전문가 + 2026-07-21 읽기전용 진단 2건):
      1. `check_row`(setCurrent)가 디테일 그리드 재조회를 트리거해 `.dews-loading-bg` 가 잠깐
         뜨는데, 이때 결재 버튼을 클릭하면 **오버레이가 클릭을 가로챈다**(진단 실측:
         `elementFromPoint` 가 버튼 대신 이 DIV 를 반환 → `window.open` 미호출).
      2. **결제창을 닫으면**(`close_child`) 본창이 별도 후처리를 하며 `.dews-loading-container`
         스피너가 뜬다(진단 실측: close 직후 t≈0~0.6s visible). 도메인전문가 확정: "그 로딩이
         끝나기 전에 다음 행을 체크하고 결제를 다시 호출해서 안 되는 것"이 2건째 결제창 미출현의
         진짜 근본원인 — 이 대기는 `close_child` 직후(`settle_parent_after_child_close`)에도
         호출된다.
    반환: 사라짐 확인=True, 상한 내 미확인=False(그래도 호출자는 계속 진행 — 버튼 클릭 자체가
    최종 방어선인 `open_approval` 의 재시도 루프가 있다). 페이지 스텁이 이 평가/대기를
    지원하지 못해도(단위테스트 등) True 로 흡수한다 — 이 함수는 best-effort 다.
    """
    try:
        waited = 0
        while waited < cap_ms:
            visible = await page.evaluate(js.LOADING_OVERLAY_VISIBLE_JS)
            if not visible:
                return True
            await page.wait_for_timeout(interval_ms)
            waited += interval_ms
        return False
    except Exception:  # noqa: BLE001 — 테스트 스텁/버전차 방어(best-effort).
        return True


async def open_approval(page: Any, *, attempts: int = 2) -> Any | None:
    """결재 버튼(button.main-button.approval) 실클릭 → window.open 으로 뜨는 **별도 Page** 캡처.

    결재 클릭 **전에** context.expect_page() 로 새 Page 를 기다린다(cross-origin EAP, SSO 경유).
    새 Page 가 안 뜨면(모든 시도 소진 후) None(인페이지 모달 등 예외 상황) — 호출자가 error 로
    처리.

    ⚠ 반복 호출 견고화(2026-07-21 배치 라이브 실측 + 읽기전용 진단으로 근본원인 확정: 1건째
    결제창을 닫고 2건째를 열 때 `.dews-loading-bg` 오버레이가 클릭을 가로채 새 Page 가 아예
    안 뜨는 사례). 매 시도마다: (1) 오버레이가 사라질 때까지 조건 폴링(`wait_loading_overlay_gone`),
    (2) 버튼 rect 를 **새로** 읽는다(절대 캐시하지 않음). 실패해도 무한 재시도가 아니라
    `attempts`(기본 2) 로 상한을 둔 **결과검증형** 재시도: 실패 시 짧게 정착 대기 후 다시
    시도한다.
    """
    context = page.context  # _ScaledPage 는 .context 를 원본 page 로 위임한다.
    for attempt in range(attempts):
        await wait_loading_overlay_gone(page)
        rect = await page.evaluate(js.APPROVAL_BTN_RECT_JS)
        if not rect:
            if attempt + 1 < attempts:
                await page.wait_for_timeout(500)
                continue
            return None
        try:
            async with context.expect_page() as page_info:
                await mouse_click(page, rect["x"], rect["y"])
        except Exception:  # noqa: BLE001 — 새 Page 미출현(타임아웃 등) → 재시도 또는 포기.
            if attempt + 1 < attempts:
                await page.wait_for_timeout(500)
                continue
            return None
        # expect_page 가 새 Page 를 잡았다. value 확정을 try 밖에서 반환해, 팝업이 이미 열린
        # 경우 블랭킷 except 로 None 을 돌려주고 핸들을 잃어(팝업 유출) 버리는 일을 막는다 —
        # 캡처된 팝업은 반드시 호출자에게 넘겨 close_child 로 닫히게 한다.
        return await page_info.value
    return None


async def settle_parent_after_child_close(page: Any, child: Any) -> None:
    """자식창(결제창)을 닫은 뒤 다음 결재 오픈을 시도하기 전에 부모 페이지를 정착시킨다.

    ⚠ 근본원인 확정(도메인전문가, 2026-07-21 라이브 리포트 + 읽기전용 진단으로 재현·확정):
    "결제 팝업을 닫으면 본창(전표조회승인)에서 별도 처리가 진행되고 로딩이 걸린다. 그런데 그
    로딩이 끝나기 전에 다음 행을 체크하고 결제를 다시 호출해서 안 되는 것." — 진단 실측
    (e2e/voucher_receivable_parent_loading_diag.py)으로 `.dews-loading-container` 스피너가
    close 직후 뜨는 것을 확인했다. 순서(도메인전문가 지시대로):
      (1) `child.is_closed()` 될 때까지 조건 폴링(자식 **완전 종료** 확인).
      (2) **본창 로딩이 사라질 때까지** 조건 폴링(`wait_loading_overlay_gone` — 핵심 수정).
      (3) 부모를 포그라운드로 복귀(`bring_to_front` — cross-origin 자식 포커스 잔류 방어).
      (4) 결재 버튼이 다시 클릭 가능(rect 유효)해질 때까지 짧게 조건 폴링(최소 정착 방어선).
    전부 **고정 settle 이 아니라 조건 확인**이며, 페이지/자식 스텁이 이 메서드들을 갖추지
    못해도(단위테스트 등) 예외를 삼켜 조용히 반환한다 — 이 함수는 best-effort 이며,
    `open_approval` 자체의 재시도(+ 자체 로딩 대기)가 최종 방어선이다.
    """
    try:
        for _ in range(20):  # child.is_closed() 될 때까지(최대 ~2s, 100ms 폴링).
            if child.is_closed():
                break
            await page.wait_for_timeout(100)
    except Exception:  # noqa: BLE001
        return
    # 근본원인 수정 지점 — 팝업 닫힘 직후 본창 로딩이 끝날 때까지 대기(다음 반복 진입 전).
    await wait_loading_overlay_gone(page)
    try:
        await page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    try:
        for _ in range(15):  # 결재 버튼 rect 가 다시 유효해질 때까지(최대 ~3s, 200ms 폴링).
            rect = await page.evaluate(js.APPROVAL_BTN_RECT_JS)
            if rect:
                return
            await page.wait_for_timeout(200)
    except Exception:  # noqa: BLE001
        return


async def poll_child_ready(
    child: Any, *, cap_ms: int = CHILD_READY_CAP_MS, interval_ms: int = CHILD_READY_INTERVAL_MS
) -> list[dict]:
    """결제창 상단 버튼(미리보기/보관/상신) 텍스트가 뜰 때까지 조건 폴링 — 고정대기 금지.

    반환: 감지된 상단 버튼 목록(빈 리스트면 cap 내 렌더 미확인). 읽기 전용 — 클릭하지 않는다.
    """
    try:
        await child.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001 — child 아직 네비게이션 중일 수 있음(계속 폴링).
        pass
    top: list[dict] = []
    waited = 0
    # 첫 대기 전에 먼저 점검한다(이미 렌더됐으면 한 인터벌을 낭비하지 않는다).
    while True:
        try:
            top = await child.evaluate(js.CHILD_TOP_BUTTONS_JS)
        except Exception:  # noqa: BLE001 — child 네비게이션 중 evaluate 실패 → 재시도.
            top = []
        if top or waited >= cap_ms:
            break
        await child.wait_for_timeout(interval_ms)
        waited += interval_ms
    return top


async def read_child_docu_no(child: Any) -> list[str]:
    """D7(배치 순회 정합성) — 결제창(자식 Page)에 표시된 전표번호 후보를 읽는다(읽기전용).

    반환 리스트 길이: 0=못 찾음, 1=확정(대상 행 DOCU_NO 와 대조 가능), 2+=모호(다른 곳에도
    같은 패턴이 매치 — 하드 실패 근거로 쓰지 않는다). child 가 아직 네비게이션 중이면 빈 리스트.
    """
    try:
        return await child.evaluate(js.CHILD_DOCU_NO_JS) or []
    except Exception:  # noqa: BLE001 — child 네비게이션 중 evaluate 실패 → 모호 취급.
        return []


async def close_child(child: Any) -> None:
    """결제창을 닫는다(비영속 확정 ✅) — 상신/보관을 누르지 않았으므로 아무것도 저장되지 않는다.

    finally 경로에서 호출되므로 이미 닫힌/유실된 팝업이어도 예외를 삼켜(로그 후 무시) 런 전체가
    중단되지 않게 한다.
    """
    try:
        await child.close()
    except Exception:  # noqa: BLE001 — 이미 닫힘/유실된 팝업 teardown 은 무해.
        logger.debug("close_child: 결제창 닫기 실패(무시)", exc_info=True)
