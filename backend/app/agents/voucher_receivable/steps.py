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
import time
from typing import Any

from nbkit.browser.actions import js_click, mouse_click
from nbkit.omnisol import js_lib, latency, selectors, verify
from nbkit.omnisol.modals import dismiss_notice_popup

from app.agents.common import ERR_REASON_MAX

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
WRITER_LABEL = "작성자"
PERIOD_FIELD = "#s_period"  # 회계일 periodpicker 컨테이너(반영 확인 리더용)

# 작성부서 팝업 그리드 데이터(부서 목록) 로드 폴링 — 그리드 컨트롤 부착(_grid) 후에도 46건
# 데이터 fetch 가 늦으면 checkAll 이 0건을 체크한다(2026-07-24 '전체선택 안 됨' 실측).
_DEPT_APPLY_SETTLE_MS = 300  # checkAll 체크 반영 대기(적용 전).
_PICKER_ROWS_CAP_MS = 6_000  # 팝업 행 도착 관찰 상한(실시간) — ERP 지연 시 latency 배율(≤×4)로 확대.
_PICKER_ROWS_INTERVAL_S = 0.25
_PICKER_ROWS_MAX_POLLS = 40  # 테스트의 no-op sleep 에서도 유한 종료를 보장하는 안전판.

# 결제창 렌더 완료 폴링 상한(SSO 리다이렉트+SPA 마운트 1~12s 편차 — 고정대기 금지, 조건폴링).
CHILD_READY_CAP_MS = 25_000
CHILD_READY_INTERVAL_MS = 1_000
# 결과 조회 rowcount 안정 폴링(그리드 로딩 대기).
QUERY_POLL_TRIES = 30
QUERY_POLL_INTERVAL_MS = 400


# ══════════════════════════════════════════════════════════════════════════════
# 확인(verify) 규율 — 값을 세팅한 스텝은 **반영을 확인**하고서야 ok 를 돌려준다.
#   불일치(확인은 됐는데 값이 다름) = 하드 실패(잘못된 조건으로 결재 대상 오인 차단).
#   확인 불가(필드/위젯을 못 읽음) = 경고 후 진행(리더 오탐이 플로우를 끊지 않게 — D7 규율과 동일).
# 재시도는 nbkit.omnisol.verify 커널이 담당(즉시 1회 + 점증 대기 3회, 실시간 대기).
# ══════════════════════════════════════════════════════════════════════════════
def _verdict(res: verify.Confirmed, **ok_extra: Any) -> dict:
    """확인 결과를 스텝 반환 dict 로 — 불일치는 실패, 확인 불가는 warn 을 얹은 성공."""
    if res:
        return {"ok": True, **ok_extra}
    if res.unknown:
        return {"ok": True, "warn": res.reason, **ok_extra}
    return {"ok": False, "reason": res.reason}


def _unreadable_display(v: Any) -> bool:
    """FIELD_DISPLAY_JS 가 null = 라벨/피커를 못 찾음(값이 틀린 게 아니라 확인 불가)."""
    return v is None


def _period_is_current_month(v: Any) -> bool:
    """PERIOD_VALUE_JS 결과가 **브라우저 기준 당월** 범위인지(시작·종료 모두)."""
    if not (isinstance(v, dict) and v.get("found")):
        return False
    yms = v.get("ym") or []
    return bool(yms) and all(y == v.get("now") for y in yms)


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
        # 무엇을 기다리나: 이 토글의 확장 애니메이션 뒤 **목표 라벨 가시화**(종전 고정 1s 후
        # 1회 확인). 보이는 즉시 진행하고, 이 토글이 목표 필드를 안 드러내면 상한(1s ×
        # latency 배율, 실시간 monotonic — delay_scale 무관) 소진 후 다음 토글(기존 수순 동일).
        t0 = time.monotonic()
        cap_ms = latency.budget_ms(1_000)
        while True:
            if await page.evaluate(js.FIELD_LABEL_VISIBLE_JS, label):
                return True
            if (time.monotonic() - t0) * 1_000 >= cap_ms:
                break
            await page.wait_for_timeout(200)
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
    # ⚠ 스테일 팝업 오독 방지(2026-07-24 실측): 앞 피커 팝업이 안 닫힌 채면 돋보기 클릭이 그
    #   팝업 뒤라 먹혀 새 팝업이 안 뜨는데도, 최상단(=잔여 팝업) 그리드가 ready 라 "열림"으로
    #   오판했다. 클릭 전 개수를 기록하고, 개수가 실제로 늘고(=새 팝업) 그 그리드가 붙어야만
    #   성공으로 본다. 상한 내 미충족이면 False(호출부가 명확 실패 처리 → 잘못된 팝업 조작 차단).
    try:
        before = await page.evaluate(js.POPUP_COUNT_JS)
    except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
        before = 0
    rect = await page.evaluate(js.FIELD_SEARCH_BTN_RECT_JS, label)
    if not rect:
        return False
    await mouse_click(page, rect["x"], rect["y"])
    # 무엇을 기다리나: **새 팝업 출현(개수 증가) + 그리드 부착(POPUP_GRID_READY_JS)** — 종전
    # '고정 1200ms 선대기 후 폴링'에서 고정 선대기를 제거하고 즉시 같은 조건을 폴링한다
    # (조건이 곧 아래 성공 판정이라 조기 진행 위험 없음). 느린 세션 실측 근거(12s 상한,
    # 2026-07-21)는 유지하되 ERP 지연 시 latency 배율(≤×4)로만 확대.
    waited = 0
    cap_ms = latency.budget_ms(ready_cap_ms)
    while True:
        try:
            opened = await page.evaluate(js.POPUP_COUNT_JS) > before
            ready = await page.evaluate(js.POPUP_GRID_READY_JS)
        except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
            return True
        if opened and ready:
            return True
        if waited >= cap_ms:
            break
        await page.wait_for_timeout(ready_interval_ms)
        waited += ready_interval_ms
    # 타임아웃: 새 팝업이 떴으면(개수 증가) 그리드 부착만 느린 것 — 기존 하드닝(2026-07-21)대로
    # 진행을 허용한다(호출부 JS 가 grid-not-ready 를 우아하게 반환하는 최종 방어선이 있다).
    # 새 팝업이 안 떴으면(스테일 잔여 팝업/열기 실패) False 로 명확히 실패시킨다.
    try:
        return await page.evaluate(js.POPUP_COUNT_JS) > before
    except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
        return True


async def _eval_rows_when_loaded(page: Any, script: str, arg: Any = None) -> Any:
    """팝업 행 검색/전체선택 JS 를 **행 도착까지** 실시간 폴링한 뒤 마지막 결과를 반환한다.

    ⚠ 근본원인(2026-08-01 전자결재상태 라이브 실증): `_open_picker` 는 '팝업 출현 + 그리드
    부착'까지만 보장하고 **데이터 행 도착은 별개의 비동기 로드**다. 종전에는 열기 경로의
    고정 1200ms 선대기가 이 틈을 우연히 가렸으나, 조건 폴링 전환(bcf6106)으로 선대기가
    사라지자 '그리드는 붙었는데 행은 0개'인 순간의 단발 checkRow 가 {ok:True, n:0} 으로
    실패 오판됐다. 부서(checkAll)만 자체 로드 폴링이 있었고 전자결재상태·전표유형은 단발이라
    이 공용 헬퍼로 통일한다.
    - 무엇을 기다리나: 행 도착(n>0 또는 idxs 비어있지 않음). 그 동안의 {ok:False}(grid-not-ready
      우아 반환 포함)·n==0 은 '아직'으로 보고 재시도한다.
    - n>0 인데 대상 미매칭이면 즉시 반환 — 대상 부재는 기다려도 생기지 않으므로 빠른 실패가 옳다.
    - 대기는 확인 커널과 같은 실시간 sleep(verify.DEFAULT_SLEEP — delay_scale 무관, 테스트는
      conftest 가 no-op 대체)이며 상한은 latency 배율로만 확대된다.
    """
    deadline = time.monotonic() + latency.budget_ms(_PICKER_ROWS_CAP_MS) / 1000.0
    res: Any = None
    for _ in range(_PICKER_ROWS_MAX_POLLS):
        res = await (page.evaluate(script, arg) if arg is not None else page.evaluate(script))
        if isinstance(res, dict) and res.get("ok") and ((res.get("n") or 0) > 0 or res.get("idxs")):
            return res
        if time.monotonic() >= deadline:
            break
        await verify.DEFAULT_SLEEP(_PICKER_ROWS_INTERVAL_S)
    return res


def _rows_never_loaded(res: Any) -> bool:
    """행 도착 대기가 끝내 실패했는지(대상 부재와 구분) — ok 인데 n==0(빈 그리드)이면 참."""
    return isinstance(res, dict) and bool(res.get("ok")) and not res.get("idxs") and (res.get("n") or 0) == 0


async def _apply_popup(
    page: Any, *, close_cap_ms: int = 8_000, interval_ms: int = 300, reclick_after_ms: int = 1_500
) -> bool:
    """최상단 팝업의 '적용' 버튼을 실클릭하고 **팝업이 실제로 닫힐 때까지 검증**한다.

    ⚠ 근본원인(2026-07-24 실측, 외상매출금 라이브): 고정 1200ms 대기만 하고 닫힘을 검증하지
      않으면, 느린 세션에서 부서 팝업(46개 checkAll)이 남은 채 다음 스텝(회계일·작성자·전표상태
      = 앱 API 직접 호출이라 팝업 무관)을 통과하고, 전자결재상태 피커가 그 잔여 부서 팝업을 읽어
      '저장'을 못 찾는다({ok:True, idxs:[], n:46}). 열려있던 팝업 개수가 줄어드는지 폴링해
      닫힘을 확정한다. checkAll 로 레이아웃이 밀려 첫 클릭이 빗나갔을 수 있어, 절반쯤 지나도 안
      닫혔으면 '적용'을 **팝업이 아직 열려있을 때만** 한 번 더(좌표 재취득) 클릭한다.
    """
    try:
        before = await page.evaluate(js.POPUP_COUNT_JS)
    except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
        before = None
    apply_rect = await page.evaluate(js.POPUP_APPLY_BTN_JS)
    if not apply_rect:
        return False
    await mouse_click(page, apply_rect["x"], apply_rect["y"])
    if before is None:  # 개수 조회 불가(스텁) — 기존 고정대기 동작 유지(best-effort).
        await page.wait_for_timeout(1_200)
        return True
    reclicked = False
    waited = 0
    while waited < close_cap_ms:
        await page.wait_for_timeout(interval_ms)
        waited += interval_ms
        if await page.evaluate(js.POPUP_COUNT_JS) < before:
            return True  # 팝업 개수 감소 = 실제 닫힘 확정.
        # 안 닫혔으면 첫 클릭이 빗나간 것일 수 있다(checkAll 로 레이아웃 이동). 팝업이 아직
        # 열린 지금 '적용' 좌표를 새로 읽어(최신 위치) 한 번 더 클릭한다(닫힌 뒤 오클릭 방지 1회만).
        # 재시도는 그리드가 재로딩돼 체크가 지워지기 전에 빠르게 — reclick_after_ms(기본 1.5s).
        if not reclicked and waited >= reclick_after_ms:
            reclicked = True
            r = await page.evaluate(js.POPUP_APPLY_BTN_JS)
            if r:
                await mouse_click(page, r["x"], r["y"])
    return False


async def set_dept_all(page: Any) -> dict:
    """작성부서 = 전체선택 — 돋보기 → 목록 로드 대기 → checkAll → 적용 → 표시값 검증.

    ⚠ '전체선택 안 됨' 방지(2026-07-24 실측):
      (1) 팝업 그리드 컨트롤이 붙어도(_grid) 부서 목록(46건) fetch 가 늦으면 checkAll 이 0건을
          체크한다 → checkAll 이 n>0 을 낼 때까지 폴링(빈 그리드 커밋 방지).
      (2) checkAll 직후 곧장 적용하면 체크 반영 전 커밋될 수 있어 짧게 settle 후 적용.
      (3) 적용 후 표시값이 비면 전체선택 미반영 — 잘못된 부서 필터로 조회하면 결재 대상이
          어긋나므로 **명확히 실패**시킨다(조용히 잘못된 조회로 진행하지 않는다).
    반환 {ok, n?, display?}.
    """
    if not await _open_picker(page, DEPT_LABEL):
        return {"ok": False, "reason": "작성부서 팝업을 열지 못했습니다(돋보기 미발견 또는 팝업 미표시)."}
    # (1) 부서 목록 로드 대기 — checkAll 이 실제로 행을 체크(n>0)할 때까지 공용 헬퍼로 폴링
    #     (종전 자체 루프는 wait_for_timeout 이 delay_scale 로 축소돼 관찰창이 줄던 명목 카운터
    #     함정이 있었다 — 실시간 monotonic + latency 배율로 통일).
    res = await _eval_rows_when_loaded(page, js.POPUP_CHECK_ALL_JS)
    if not (isinstance(res, dict) and res.get("ok")):
        return {"ok": False, "reason": f"작성부서 팝업 전체선택(checkAll) 실패: {res}"}
    if (res.get("n") or 0) <= 0:
        return {"ok": False, "reason": "작성부서 목록이 로드되지 않아 전체선택이 0건입니다(그리드 데이터 대기 실패)."}
    # (2) checkAll 반영 settle 후 적용.
    await page.wait_for_timeout(_DEPT_APPLY_SETTLE_MS)
    if not await _apply_popup(page):
        return {"ok": False, "reason": "작성부서 팝업 적용/닫힘 실패(적용 버튼 미발견 또는 팝업이 닫히지 않음)."}
    # (3) 전체선택 반영 검증 — 표시값이 비면 실패(잘못된 부서 필터 조회 차단).
    #     확인 커널로 위임: 적용 직후 즉시 1회 확인하고, 반영이 늦으면 점증 대기로 3회 재확인한다.
    chk = await verify.confirm_display(page, DEPT_LABEL, unknown_when=_unreadable_display)
    return _verdict(chk, n=res.get("n"), display=chk.actual)


async def set_period_this_month(page: Any) -> dict:
    """회계일 = 당월(1일~말일) — dews periodpicker 앱 API setMonth() 후 **반영 확인**.

    ⚠ YYYYMMDD 타이핑 아님. setMonth() 는 예외 없이 반환해도 위젯이 값을 안 붙이는 경우가
    있어(폼 리로드 레이스), 시작·종료 입력값의 연월이 **브라우저 기준 당월**인지 재확인한다.
    """
    ok = await page.evaluate(js.SET_PERIOD_THIS_MONTH_JS)
    if not ok:
        return {"ok": False, "reason": "회계일 periodpicker setMonth() 호출 실패."}
    chk = await verify.confirm(
        lambda: page.evaluate(js_lib.PERIOD_VALUE_JS, PERIOD_FIELD),
        _period_is_current_month,
        timing=verify.INSTANT,
        what="회계일(당월)",
        expected="당월 1일~말일",
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("found")),
    )
    values = chk.actual.get("values") if isinstance(chk.actual, dict) else None
    return _verdict(chk, display=values)


async def set_period(page: Any, start: str | None = None, end: str | None = None) -> dict:
    """회계일 = 지정 기간(YYYYMMDD) — 실행 전 폼이 고른 조회기간을 반영한다.

    기간이 주어지면 **당월이든 아니든 항상 그 기간을 세팅**한다. 미지정일 때만 setMonth()
    (폼 없이 실행하던 구 경로). 회계일이 틀리면 결재 대상 자체가 어긋나므로 세팅 후 readback
    으로 반영을 확인한다 — 불일치는 하드 실패, 위젯 구조를 못 읽는 경우만 warn 으로 통과.

    ⚠ 종전에는 '당월 1일~말일이면 setMonth() 로 단락'했는데 그게 결함이었다(2026-07-28 실측):
      화면 기본값은 **1일~오늘**이지 1일~말일이 아니고, 결의서조회승인 쪽은 단락 시 아예
      건드리지 않아 두 화면이 서로 다른 기간으로 조회됐다. 임의 기간 세팅이 두 화면 모두
      확실히 반영됨을 프로브로 확인했으므로(e2e/voucher_period_probe.py) 단락을 제거한다.
    """
    if not start or not end:
        return await set_period_this_month(page)

    ok = await page.evaluate(js.SET_PERIOD_RANGE_JS, {"start": start, "end": end})
    if not ok:
        return {"ok": False, "reason": "회계일 기간 입력 실패(시작/종료 input 미발견)."}
    values = await page.evaluate(js.PERIOD_VALUE_JS)
    if not isinstance(values, dict):
        return {"ok": True, "warn": "반영 확인 불가(회계일 입력 구조를 읽지 못함).", "display": None}
    if values.get("start") != start or values.get("end") != end:
        return {
            "ok": False,
            "reason": f"회계일 기간 반영 불일치 — 기대 {start}~{end}, 실제 {values}.",
        }
    return {"ok": True, "display": f"{start}~{end}"}


async def clear_writer(page: Any) -> dict:
    """작성자 = 비움 — dews multicodepicker clear() 후 **표시값이 실제로 비었는지 확인**."""
    ok = await page.evaluate(js.CLEAR_WRITER_JS)
    if not ok:
        return {"ok": False, "reason": "작성자 multicodepicker clear() 호출 실패."}
    chk = await verify.confirm_display_empty(page, WRITER_LABEL, timing=verify.INSTANT)
    return _verdict(chk)


async def set_docu_status(page: Any, text: str = DOCU_ST_TARGET) -> dict:
    """전표상태 = 미결 — kendo dropdownlist 세팅 후 **현재 선택 텍스트 재확인**.

    ⚠ 세팅 JS 의 {ok:true} 는 "옵션을 찾아 값을 넣었다"까지다 — change 핸들러/폼 리로드가 값을
    되돌리는 경우가 있어 실제 선택값을 확인한다. 되돌려지는 성격이라 재시도 때 **재세팅**한다.
    """
    payload = {"selector": DOCU_ST_SELECT, "text": text}
    r = await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, payload)
    if not (isinstance(r, dict) and r.get("ok")):
        return {"ok": False, "reason": f"전표상태 '{text}' 설정 실패: {r}"}
    chk = await verify.confirm_select(
        page,
        DOCU_ST_SELECT,
        text,
        reapply=lambda: page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, payload),
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("ok")),
    )
    return _verdict(chk)


async def set_gwaprvlst(page: Any, target: str = GWAPRVLST_TARGET) -> dict:
    """전자결재상태 = 저장 — MultiCodePicker 팝업 RealGrid checkRow(SYSDEF_NM==target) → 적용."""
    if not await _open_picker(page, GWAPRVLST_LABEL):
        return {"ok": False, "reason": "전자결재상태 팝업을 열지 못했습니다(돋보기 미발견 또는 팝업 미표시)."}
    res = await _eval_rows_when_loaded(page, js.POPUP_CHECK_ROWS_JS, [[target], "SYSDEF_NM"])
    if not (isinstance(res, dict) and res.get("ok") and res.get("idxs")):
        if _rows_never_loaded(res):
            return {"ok": False, "reason": f"전자결재상태 팝업 행이 로드되지 않았습니다(행 도착 대기 실패): {res}"}
        return {"ok": False, "reason": f"전자결재상태 '{target}' 행을 팝업에서 찾지 못했습니다: {res}"}
    if not await _apply_popup(page):
        return {"ok": False, "reason": "전자결재상태 팝업 적용/닫힘 실패(적용 버튼 미발견 또는 팝업이 닫히지 않음)."}
    # 팝업 안 checkRow 성공은 '팝업 내부 상태'일 뿐 — 적용이 **폼에 붙었는지**까지 확인한다.
    chk = await verify.confirm_display(page, GWAPRVLST_LABEL, unknown_when=_unreadable_display)
    return _verdict(chk, checked=res.get("idxs"), display=chk.actual)


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
        return {"ok": False, "reason": "전표유형 팝업을 열지 못했습니다(돋보기 미발견/팝업 미표시 — 패널 확장 확인)."}
    # ⚠ 실측(2026-07-21 읽기전용 진단, e2e/voucher_receivable_docu_type_diag.py): 이 팝업의
    # 실제 RealGrid 필드는 전자결재상태 팝업과 동일한 범용 코드테이블 스키마
    # SYSDEF_CD/SYSDEF_NM 이다 — 'DOCU_NM'/'DOCU_CD' 필드는 이 팝업엔 없다(2026-07-20 프로브
    # 기록이 실측과 어긋남 — 코드/명칭 레벨 불일치, PROCESS.md D2 정정 대상).
    res = await _eval_rows_when_loaded(page, js.POPUP_CHECK_ROWS_JS, [list(targets), "SYSDEF_NM"])
    checked = res.get("idxs") if isinstance(res, dict) else None
    if not (isinstance(res, dict) and res.get("ok") and checked and len(checked) == len(targets)):
        if _rows_never_loaded(res):
            return {"ok": False, "reason": f"전표유형 팝업 행이 로드되지 않았습니다(행 도착 대기 실패): {res}"}
        return {"ok": False, "reason": f"전표유형 {list(targets)} 전부를 팝업에서 찾지 못했습니다: {res}"}
    if not await _apply_popup(page):
        return {"ok": False, "reason": "전표유형 팝업 적용/닫힘 실패(적용 버튼 미발견 또는 팝업이 닫히지 않음)."}
    # 폼 반영 확인 — 표시 형식(이름/코드/건수)이 세션마다 달라 정확일치는 요구하지 않고
    # '비어있지 않음'을 근거로 삼는다(어느 대상을 체크했는지는 위 checkRow 가 이미 확정).
    chk = await verify.confirm_display(page, DOCU_TYPE_LABEL, unknown_when=_unreadable_display)
    return _verdict(chk, checked=checked, display=chk.actual)


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


async def count_rows_with_abdocu(page: Any) -> dict:
    """마스터 그리드에서 결의서번호(ABDOCU_NO) 보유 행 수 — {ok, n, withAb} | {ok:False}.

    카드(voucher-card)가 결의서조회승인 수집 **전에** 호출해, 보유 0건이면 다중탭 수집을
    생략하고 즉시 종료한다(사용자 확정 2026-07-30). 읽기 실패는 ok:False 로 돌려 호출자가
    기존 경로(수집 진행)로 폴백하게 한다.
    """
    try:
        res = await page.evaluate(js.COUNT_ROWS_WITH_ABDOCU_JS)
        return res if isinstance(res, dict) else {"ok": False, "reason": f"비정상 반환: {res!r}"}
    except Exception as exc:  # noqa: BLE001 — 테스트 스텁/버전차 방어(soft-fail).
        return {"ok": False, "reason": str(exc)[:ERR_REASON_MAX]}


async def read_detail_count(page: Any, idx: int, docu_no: str | None = None) -> dict:
    """마스터 idx 행의 **하위(계정정보) 그리드 건수**를 읽는다. 반환 {ok, count, verified, reason?}.

    행을 setCurrent 하면 디테일이 서버에서 재조회된다(실측 2026-07-27, 138행 전수 프로브:
    행별 갱신 확인 · 평균 372ms/행 · 전수 52초). 읽기 전용이며 체크 상태를 건드리지 않는다
    (결재 대상 선택은 배치 실행 단계에서 따로 한다).

    ⚠ 스테일 판정(핵심): 디테일이 아직 **이전 행의 것**이어도 건수만 보면 구분되지 않는다
      (실측 분포상 대부분 전표가 3라인). 디테일 행이 자신의 ``DOCU_NO`` 를 갖고 있으므로,
      그 값이 대상 전표번호와 같아질 때까지 확인하고서야 건수를 채택한다(확인 커널, ASYNC).
      대상 전표번호를 모르면(docu_no=None) 소유 확인을 못 하므로 ``verified=False`` 로 돌려
      호출부가 그 행을 **단독 그룹**으로 빼게 한다(모르면 안전한 쪽).
    """
    await page.evaluate(js_lib.SET_CURRENT_BY_INDEX_JS, {"index": 0, "itemIndex": idx})

    async def read() -> Any:
        return await page.evaluate(js.DETAIL_COUNT_JS)

    def owned(v: Any) -> bool:
        if not (isinstance(v, dict) and v.get("ok")):
            return False
        return bool(docu_no) and str(v.get("docu_no") or "").strip() == str(docu_no).strip()

    chk = await verify.confirm(
        read,
        owned,
        timing=verify.ASYNC,
        what=f"{idx + 1}행 하위 건수(전표 {docu_no})",
        expected=docu_no,
        settle=lambda: wait_loading_overlay_gone(page),
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("ok")) or not docu_no,
    )
    n = chk.actual.get("n") if isinstance(chk.actual, dict) else None
    if chk:
        return {"ok": True, "count": int(n or 0), "verified": True}
    # 소유 확인 실패 — 건수를 그 행의 것으로 단정하지 않는다(-1 = 미상 → 단독 처리).
    return {"ok": True, "count": -1, "verified": False, "reason": chk.reason}


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
        return {"ok": False, "reason": str(exc)[:ERR_REASON_MAX]}


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
