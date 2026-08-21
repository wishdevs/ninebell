"""전표조회승인(voucher-by-type) 스텝 프리미티브 — 브라우저 조작 단위(노드가 조립).

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
from nbkit.patterns import approval_line_flow

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
# 유형별 전표조회 승인(voucher-by-type) — 실행 전 폼이 **전체 62종에서** 다중 선택한다
# (사용자 지시 2026-08-20 "리스트에 있는 유형 다 보여주고 선택하게").
# 전량 실측 = e2e/artifacts/voucher_receivable_docu_type_diag.json (SYSDEF_CD/SYSDEF_NM 62행).
# ERP 피커는 SYSDEF_NM 한글 라벨로 매칭하므로 **라벨이 곧 계약값**이다(set_docu_types 참조).
# 코드(SYSDEF_CD)는 화면 표기·프론트 대조용이며 자동화 경로에서는 쓰지 않는다.
DOCU_TYPE_CATALOG: tuple[tuple[str, str], ...] = (
    ("11", "일반"),
    ("12", "결산대체"),
    ("13", "결산역분개"),
    ("21", "국내매출"),
    ("22", "국내수금"),
    ("23", "해외매출"),
    ("24", "해외수금"),
    ("25", "선수금"),
    ("26", "선수금 반제"),
    ("27", "해외선수금"),
    ("28", "해외선수금 반제"),
    ("31", "내수구매"),
    ("32", "외자구매"),
    ("14A", "결산손익역분개"),
    ("33", "선급금"),
    ("15A", "결산원가역분개"),
    ("34", "선급금반제"),
    ("41", "입고전기"),
    ("42", "출고전기"),
    ("43", "이동전기"),
    ("19", "일반전표역분개"),
    ("44", "이전전기"),
    ("51", "생산출고"),
    ("52", "생산입고"),
    ("53", "연산품입고"),
    ("54", "부산물입고"),
    ("55", "연산품출고(취소)"),
    ("56", "부산물출고(취소)"),
    ("61", "수출제비용"),
    ("62", "수입부대비용"),
    ("63", "미착정산"),
    ("29", "결산대체(자산)"),
    ("71", "급여"),
    ("72", "퇴직금"),
    ("73", "사업/기타소득"),
    ("74", "복리후생"),
    ("75", "교육"),
    ("14", "결산손익대체"),
    ("15", "결산원가대체"),
    ("35", "내수구매비용"),
    ("81", "PS정산"),
    ("82", "PM정산"),
    ("91", "리스임차"),
    ("16", "결산외화평가"),
    ("17", "결산역분개외화평가"),
    ("18", "건설중인자산대체"),
    ("76", "출장"),
    ("77", "퇴직금추계액"),
    ("94", "진행매출"),
    ("94A", "진행매출역분개"),
    ("95", "결산원가"),
    ("96", "급여안분"),
    ("97", "자산이동"),
    ("98", "리스임대"),
    ("99", "리스임대수납"),
    ("100", "자산처분"),
    ("101", "충당금결산"),
    ("102", "재고평가"),
    ("103", "원가정산"),
    ("104", "전자상거래 국내매출"),
    ("105", "전자상거래 해외매출"),
    ("106", "IU(MIG)"),
)
DOCU_TYPE_CHOICES = tuple(label for _code, label in DOCU_TYPE_CATALOG)  # 허용 라벨(62종)
# 폼 미지정 시 빌드 기본값 — 병합 전 동작(외상매출금 2종 + 외상매입금 1종)을 보존한다.
DOCU_TYPE_DEFAULTS = ("국내매출", "해외매출", "내수구매")
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
_BTN_RECT_TRIES = 4  # 돋보기 rect null(재접힘 직후) 짧은 재관찰 횟수.
_BTN_RECT_INTERVAL_S = 0.15
_BTN_STABLE_GAP_S = 0.12  # 좌표 2회 연속 동일 판정 간격(패널 확장 애니메이션 정착).
_OPEN_CLICK_MAX = 3  # 팝업 미출현 시 돋보기 재클릭 상한.
_OPEN_WINDOW_MS = 2_500  # 클릭당 팝업 출현 관찰창(실시간, latency 배율 적용).


async def _search_btn_rect_stable(page: Any, label: str) -> Any:
    """돋보기 버튼 rect 를 **정착 좌표**로 얻는다 — null 이면 짧게 재관찰(재접힘 직후 재출현),
    얻으면 같은 좌표가 2회 연속 읽힐 때까지 확인해 확장 애니메이션 중의 이동 좌표 클릭을 막는다.
    계속 null 이면 None(패널 접힘 — 가시성 재확보는 호출부 몫)."""
    rect = None
    for _ in range(_BTN_RECT_TRIES):
        rect = await page.evaluate(js.FIELD_SEARCH_BTN_RECT_JS, label)
        if rect:
            break
        await verify.DEFAULT_SLEEP(_BTN_RECT_INTERVAL_S)
    if not rect:
        return None
    for _ in range(_BTN_RECT_TRIES):
        await verify.DEFAULT_SLEEP(_BTN_STABLE_GAP_S)
        again = await page.evaluate(js.FIELD_SEARCH_BTN_RECT_JS, label)
        if again == rect:
            return rect
        if not again:
            return None
        rect = again
    return rect  # 계속 흔들리면 마지막 좌표로 진행 — 클릭 실패는 상위 재클릭이 흡수.

# 결제창 렌더 완료 폴링 상한(SSO 리다이렉트+SPA 마운트 1~12s 편차 — 고정대기 금지, 조건폴링).
CHILD_READY_CAP_MS = 25_000
CHILD_READY_INTERVAL_MS = 1_000


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
    # ⚠ 결과검증형 클릭 재시도(2026-08-01 전표유형 라이브 실증): 가시성 확인(ensure_field_visible)
    #   통과 직후에도 ① rect 읽는 순간 패널이 재접혀 null 이거나 ② 확장 애니메이션 중의 좌표를
    #   읽어 클릭이 빗나가 팝업이 안 뜨는 레이스가 있다(종전엔 고정 선대기가 우연히 가림).
    #   좌표는 2회 연속 동일(애니메이션 정착 — 사용자유형 드롭다운과 동일 패턴)일 때만 클릭하고,
    #   클릭당 출현 관찰창 안에 팝업이 안 뜨면 fresh 좌표로 재클릭한다(최대 3회 — 이미 첫
    #   클릭이 먹은 경우의 중복 오픈을 피하기 위해 관찰창을 충분히 두고 상한을 낮게 유지).
    deadline = time.monotonic() + latency.budget_ms(ready_cap_ms) / 1000.0
    opened = False
    for _ in range(_OPEN_CLICK_MAX):
        rect = await _search_btn_rect_stable(page, label)
        if not rect:
            return False  # 접힘/미발견 — 호출부가 가시성 재확보 후 재시도할 몫.
        await mouse_click(page, rect["x"], rect["y"])
        window_end = min(deadline, time.monotonic() + latency.budget_ms(_OPEN_WINDOW_MS) / 1000.0)
        polls = 0
        while polls < _PICKER_ROWS_MAX_POLLS:
            try:
                if await page.evaluate(js.POPUP_COUNT_JS) > before:
                    opened = True
                    break
            except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
                return True
            if time.monotonic() >= window_end:
                break
            polls += 1
            await verify.DEFAULT_SLEEP(ready_interval_ms / 1000.0)
        if opened or time.monotonic() >= deadline:
            break
    if not opened:
        # 새 팝업이 안 떴으면(스테일 잔여 팝업/열기 실패) False 로 명확히 실패시킨다.
        try:
            return await page.evaluate(js.POPUP_COUNT_JS) > before
        except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
            return True
    # ⚠ 이중 오픈 정규화(2026-08-07 무결성 감사): 첫 클릭이 실제로 먹었는데 렌더가 출현 관찰창
    #   (_OPEN_WINDOW_MS)을 넘겨 재클릭이 나가면 팝업이 **2개** 뜬다 — _apply_popup 은 '개수
    #   감소'만 확인하므로 잔여 1개가 남아 다음 피커가 스테일 팝업을 읽는 오염 경로가 된다
    #   (2026-07-24 사고의 재유입 뒷문). 초과분을 즉시 닫아 '새 팝업 1개' 불변식을 복원한다.
    if isinstance(before, int):
        try:
            n_now = await page.evaluate(js.POPUP_COUNT_JS)
        except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
            n_now = None
        if isinstance(n_now, int) and n_now > before + 1:
            logger.warning("피커 '%s' 이중 오픈 감지(%d→%d) — 초과분 닫기 정규화", label, before, n_now)
            await _close_top_popup(page, count=n_now - (before + 1))
    # 그리드 부착 폴링(기존 하드닝 유지) — 상한 내 미부착이어도 팝업이 떴으면 진행을 허용한다
    # (호출부 JS 가 grid-not-ready 를 우아하게 반환하는 최종 방어선이 있다). 실시간 상한과
    # 명목 횟수 상한을 병행한다(no-op sleep 테스트에서의 폴 폭증 방지).
    ready_polls_cap = max(1, latency.budget_ms(ready_cap_ms) // max(1, ready_interval_ms))
    for _ in range(ready_polls_cap):
        try:
            if await page.evaluate(js.POPUP_GRID_READY_JS):
                return True
        except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
            return True
        if time.monotonic() >= deadline:
            return True
        await verify.DEFAULT_SLEEP(ready_interval_ms / 1000.0)
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
    # ⚠ 시간축 규율(2026-08-07): 닫힘 관찰은 **실패-경로 대기**다 — 종전 page.wait_for_timeout
    #   은 delay_scale(0.4)로 줄어 관찰창이 실효 3.2s·재클릭 0.6s 로 붕괴했다(명목 카운터 함정,
    #   card_collect/trip_domestic 과 동일 규율로 정리). 실시간 sleep(verify.DEFAULT_SLEEP)으로
    #   세고(명목 누산 == 실경과), 상한만 latency 배율(≤×4)로 확대한다.
    cap_ms = latency.budget_ms(close_cap_ms)
    while waited < cap_ms:
        await verify.DEFAULT_SLEEP(interval_ms / 1000)
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


async def _close_top_popup(page: Any, *, count: int = 1) -> bool:
    """최상단 업무 팝업을 닫고 **개수 감소를 확인**한다(count 개까지). 전부 닫히면 True.

    이중 오픈 정규화·실패 경로 정리(_fail_close) 공용. 닫기 JS 는 검증된 공유 프리미티브
    js_lib.PICKER_CLOSE_JS(최상단 보이는 k-window 의 닫기/취소 클릭)를 재사용하고, 감소 확인은
    업무 팝업 기준(POPUP_COUNT_JS — 공지 제외)으로 한다. 닫기가 공지창에 먹은 회차는 업무
    개수가 안 줄어 reapply 재클릭으로 수렴한다.
    """
    for _ in range(max(1, count)):
        try:
            before = await page.evaluate(js.POPUP_COUNT_JS)
        except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
            return False
        if not isinstance(before, int) or before <= 0:
            return True  # 닫을 팝업이 없다.
        try:
            await page.evaluate(js_lib.PICKER_CLOSE_JS)
        except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
            return False
        chk = await verify.confirm_popup_count(
            page, less_than=before, reapply=lambda: page.evaluate(js_lib.PICKER_CLOSE_JS)
        )
        if not chk:
            return False
    return True


async def _reset_popups(page: Any) -> None:
    """attempt 재진입 위생 — 직전 시도가 남긴 업무 팝업을 전부 닫아 기준선(0)을 복원한다.

    결과검증형 재시도(attempt-as-reapply)에서 잔존 팝업을 안 닫으면 `_open_picker` 의
    '개수 증가' 판정이 영원히 실패한다(돋보기 클릭이 잔존 팝업 뒤로 먹힘).
    """
    try:
        n = await page.evaluate(js.POPUP_COUNT_JS)
    except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
        return
    if isinstance(n, int) and n > 0:
        await _close_top_popup(page, count=n)


async def _fail_close(page: Any, reason: str, **extra: Any) -> dict:
    """실패 경로 — 열린 피커 팝업을 정리하고 실패 dict 를 돌려준다(trip_domestic 규율 이식).

    팝업 스텝이 팝업을 연 뒤 실패하면서 열린 채 반환하면, 다음 피커가 그 잔존 팝업을 읽는
    오염(최상단 규칙)이 생긴다 — 이 화면(set_query)의 기준선은 '업무 팝업 0개'이므로 전부
    닫는다. 닫힘 실패는 **원래 실패 사유를 덮지 않고** 경고만 덧붙인다.
    """
    try:
        n = await page.evaluate(js.POPUP_COUNT_JS)
    except Exception:  # noqa: BLE001 — 테스트 스텁 등 방어(best-effort).
        n = None
    if isinstance(n, int) and n > 0:
        if not await _close_top_popup(page, count=n):
            reason = f"{reason} / ⚠ 실패 정리 중 팝업 미닫힘(다음 스텝 오염 주의)"
    return {"ok": False, "reason": reason, **extra}


async def set_dept_all(page: Any) -> dict:
    """작성부서 = 전체선택 — 돋보기 → 목록 로드 대기 → checkAll → 적용 → 표시값 검증.

    ⚠ '전체선택 안 됨' 방지(2026-07-24 실측):
      (1) 팝업 그리드 컨트롤이 붙어도(_grid) 부서 목록(46건) fetch 가 늦으면 checkAll 이 0건을
          체크한다 → checkAll 이 n>0 을 낼 때까지 폴링(빈 그리드 커밋 방지).
      (2) checkAll 직후 곧장 적용하면 체크 반영 전 커밋될 수 있어 짧게 settle 후 적용.
      (3) 적용 후 표시값이 비면 전체선택 미반영 — 잘못된 부서 필터로 조회하면 결재 대상이
          어긋나므로 **명확히 실패**시킨다(조용히 잘못된 조회로 진행하지 않는다).
    ⚠ 결과검증형 재시도(2026-08-07): 열기→행대기→checkAll→적용 전체를 attempt 로 묶어 표시값이
      붙을 때까지 재실행한다(voucher_card set_collect_dept_all 실증 패턴 — "첫 시도만 실패하고
      즉시 재시도는 전부 성공"하는 준비-덜-됨 레이스를 구조적으로 흡수). 재진입 시 잔존 팝업은
      _reset_popups 로 정리해 개수 기준선을 복원한다.
    반환 {ok, n?, display?}.
    """
    last: dict = {"n": None, "why": None, "done": False}

    async def attempt() -> None:
        await _reset_popups(page)
        if not await _open_picker(page, DEPT_LABEL):
            last["why"] = "작성부서 팝업을 열지 못했습니다(돋보기 미발견 또는 팝업 미표시)."
            return
        # (1) 부서 목록 로드 대기 — checkAll 이 실제로 행을 체크(n>0)할 때까지 공용 헬퍼로 폴링
        #     (종전 자체 루프는 wait_for_timeout 이 delay_scale 로 축소돼 관찰창이 줄던 명목
        #     카운터 함정이 있었다 — 실시간 monotonic + latency 배율로 통일).
        res = await _eval_rows_when_loaded(page, js.POPUP_CHECK_ALL_JS)
        if not (isinstance(res, dict) and res.get("ok")):
            last["why"] = f"작성부서 팝업 전체선택(checkAll) 실패: {res}"
            return
        if (res.get("n") or 0) <= 0:
            last["why"] = "작성부서 목록이 로드되지 않아 전체선택이 0건입니다(그리드 데이터 대기 실패)."
            return
        last["n"] = res.get("n")
        last["why"] = None
        # (2) checkAll 반영 settle 후 적용.
        await page.wait_for_timeout(_DEPT_APPLY_SETTLE_MS)
        if not await _apply_popup(page):
            last["why"] = "작성부서 팝업 적용/닫힘 실패(적용 버튼 미발견 또는 팝업이 닫히지 않음)."
            return
        last["done"] = True  # 적용·닫힘까지 완주한 시도가 있다 — 표시값 판정의 전제.

    await attempt()
    # (3) 전체선택 반영 검증 — 표시값이 비면 attempt 전체를 재실행(최대 3회, 실시간 점증 대기).
    chk = await verify.confirm_display(
        page, DEPT_LABEL, unknown_when=_unreadable_display, reapply=attempt
    )
    if last["done"] and (chk or chk.unknown):
        return _verdict(chk, n=last["n"], display=chk.actual)
    # 완주(적용까지) 없이 그럴듯한 표시값만으로 성공 처리하지 않는다 — 완주했으면 표시값
    # 불일치(확인 실패)가, 미완주면 마지막 시도의 실패 지점이 실패 근거다.
    return await _fail_close(page, chk.reason if last["done"] else (last["why"] or chk.reason))


async def set_period_this_month(page: Any) -> dict:
    """회계일 = 당월(1일~말일) — dews periodpicker 앱 API setMonth() 후 **반영 확인**.

    ⚠ YYYYMMDD 타이핑 아님. setMonth() 는 예외 없이 반환해도 위젯이 값을 안 붙이는 경우가
    있어(폼 리로드 레이스), 시작·종료 입력값의 연월이 **브라우저 기준 당월**인지 재확인한다.
    되돌려지는 성격의 값이라(range 분기와 동일) 재시도 때는 setMonth() 를 재실행한다.
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
        reapply=lambda: page.evaluate(js.SET_PERIOD_THIS_MONTH_JS),
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

    payload = {"start": start, "end": end}
    ok = await page.evaluate(js.SET_PERIOD_RANGE_JS, payload)
    if not ok:
        return {"ok": False, "reason": "회계일 기간 입력 실패(시작/종료 input 미발견)."}
    # ⚠ 되돌림 레이스(2026-08-03·08-06 라이브 실패 실측): dews periodpicker 의 change 핸들러가
    #   값을 비동기로 되돌려 **end 만 붙고 start 는 위젯 기본값**으로 돌아간 부분 반영이 관측됐다.
    #   단발 readback 은 그 과도상태를 하드 실패로 오판한다 — card_collect set_period 와 같은
    #   규율로 확인 커널 재확인 + 되돌려지는 성격의 값이라 재시도 때 **재세팅**(reapply)한다.
    chk = await verify.confirm(
        lambda: page.evaluate(js.PERIOD_VALUE_JS),
        lambda v: isinstance(v, dict) and v.get("start") == start and v.get("end") == end,
        timing=verify.INSTANT,
        what="회계일 기간",
        expected=f"{start}~{end}",
        reapply=lambda: page.evaluate(js.SET_PERIOD_RANGE_JS, payload),
        unknown_when=lambda v: not isinstance(v, dict),
    )
    return _verdict(chk, display=f"{start}~{end}" if chk else None)


async def clear_writer(page: Any) -> dict:
    """작성자 = 비움 — dews multicodepicker clear() 후 **표시값이 실제로 비었는지 확인**.

    ⚠ 되돌림 대비(2026-08-07): 작성자는 폼 리로드/change 캐스케이드가 로그인 사용자 기본값을
    **비동기로 재주입**하는 성격의 필드다 — 재확인에서 비어있지 않으면 재클리어(reapply)한다.
    (t=0 재확인 통과 후 늦게 재주입되는 창은 조회 직전 재확정 게이트(nodes/query.py)가 봉합.)
    """
    ok = await page.evaluate(js.CLEAR_WRITER_JS)
    if not ok:
        return {"ok": False, "reason": "작성자 multicodepicker clear() 호출 실패."}
    chk = await verify.confirm_display_empty(
        page,
        WRITER_LABEL,
        timing=verify.INSTANT,
        reapply=lambda: page.evaluate(js.CLEAR_WRITER_JS),
    )
    return _verdict(chk)


async def set_docu_status(page: Any, text: str = DOCU_ST_TARGET) -> dict:
    """전표상태 = 미결 — kendo dropdownlist 세팅 후 **현재 선택 텍스트 재확인**.

    ⚠ 세팅 JS 의 {ok:true} 는 "옵션을 찾아 값을 넣었다"까지다 — change 핸들러/폼 리로드가 값을
    되돌리는 경우가 있어 실제 선택값을 확인한다. 되돌려지는 성격이라 재시도 때 **재세팅**한다.
    ⚠ 준비 게이트(2026-08-07): 직전 스텝(팝업 적용·기간 세팅)이 폼 리로드를 유발하는 구간이라
    select 부재/위젯 재바인딩 순간에 단발 세팅이 실패할 수 있다 — 세팅 전에 준비를 폴링하고
    (형제 구현 common/nodes.set_gubun 의 존재 폴링을 확인 커널로 승격), 1차 세팅 실패도 즉시
    하드 실패하지 않는다(confirm_select 의 reapply 재세팅이 소진된 뒤에만 실패 확정 — 종전엔
    1차 실패가 reapply 에 도달조차 못 하는 구조였다).
    """
    payload = {"selector": DOCU_ST_SELECT, "text": text}
    ready = await verify.confirm(
        lambda: page.evaluate(js.DOCU_ST_READY_JS, DOCU_ST_SELECT),
        lambda v: isinstance(v, dict) and bool(v.get("widget")),
        timing=verify.ASYNC,
        what="전표상태 위젯 준비",
        expected="select+kendo 부착",
    )
    if not ready:
        if not (isinstance(ready.actual, dict) and ready.actual.get("sel")):
            return {"ok": False, "reason": f"전표상태 select 미출현: {ready.reason}"}
        # 위젯만 미부착(native select 존재) — 세팅 JS 의 native 폴백으로 진행(하드 리그레션 방지).
        logger.warning("전표상태 kendo 위젯 미부착 — native select 폴백으로 진행: %s", ready.reason)
    r = await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, payload)
    if not (isinstance(r, dict) and r.get("ok")):
        logger.warning("전표상태 '%s' 1차 세팅 실패(%s) — 확인 커널 재세팅으로 재시도", text, r)
    chk = await verify.confirm_select(
        page,
        DOCU_ST_SELECT,
        text,
        reapply=lambda: page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, payload),
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("ok")),
    )
    return _verdict(chk)


async def set_gwaprvlst(page: Any, target: str = GWAPRVLST_TARGET) -> dict:
    """전자결재상태 = 저장 — MultiCodePicker 팝업 RealGrid checkRow(SYSDEF_NM==target) → 적용.

    ⚠ 결과검증형 재시도(2026-08-07): 열기→행대기→checkRow→적용 전체를 attempt 로 묶어 폼
      표시값이 붙을 때까지 재실행한다(set_dept_all 과 동일 규율). 단 **대상 부재**(행은 로드
      됐는데 target 미매칭)는 기다리거나 다시 열어도 생기지 않으므로 즉시 실패한다(재시도는
      타이밍 실패에만 — 오탐 재시도로 런타임을 낭비하지 않는다).
    """
    last: dict = {"idxs": None, "why": None, "absent": False, "done": False}

    async def attempt() -> None:
        if last["absent"]:
            return  # 대상 부재 확정 — 재실행 무의미.
        await _reset_popups(page)
        if not await _open_picker(page, GWAPRVLST_LABEL):
            last["why"] = "전자결재상태 팝업을 열지 못했습니다(돋보기 미발견 또는 팝업 미표시)."
            return
        res = await _eval_rows_when_loaded(page, js.POPUP_CHECK_ROWS_JS, [[target], "SYSDEF_NM"])
        if not (isinstance(res, dict) and res.get("ok") and res.get("idxs")):
            if _rows_never_loaded(res):
                last["why"] = f"전자결재상태 팝업 행이 로드되지 않았습니다(행 도착 대기 실패): {res}"
            else:
                last["why"] = f"전자결재상태 '{target}' 행을 팝업에서 찾지 못했습니다: {res}"
                last["absent"] = True
            return
        last["idxs"] = res.get("idxs")
        last["why"] = None
        if not await _apply_popup(page):
            last["why"] = "전자결재상태 팝업 적용/닫힘 실패(적용 버튼 미발견 또는 팝업이 닫히지 않음)."
            return
        last["done"] = True

    await attempt()
    if last["absent"]:
        return await _fail_close(page, last["why"])
    # 팝업 안 checkRow 성공은 '팝업 내부 상태'일 뿐 — 적용이 **폼에 붙었는지**까지 확인하고,
    # 안 붙었으면 attempt 전체를 재실행한다(최대 3회, 실시간 점증 대기).
    chk = await verify.confirm_display(
        page, GWAPRVLST_LABEL, unknown_when=_unreadable_display, reapply=attempt
    )
    if last["done"] and (chk or chk.unknown):
        return _verdict(chk, checked=last["idxs"], display=chk.actual)
    # 완주(적용까지) 없는 그럴듯한 표시값은 성공 근거가 아니다(스테일 표시 차단).
    return await _fail_close(page, chk.reason if last["done"] else (last["why"] or chk.reason))


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
    last: dict = {"checked": None, "why": None, "absent": False, "done": False}

    async def attempt() -> None:
        if last["absent"]:
            return  # 대상 부재 확정 — 재실행 무의미.
        await _reset_popups(page)
        if not await ensure_field_visible(page, DOCU_TYPE_LABEL):
            last["why"] = "전표유형 필드가 어떤 확장 토글로도 보이지 않았습니다."
            return
        if not await _open_picker(page, DOCU_TYPE_LABEL):
            # ⚠ 재접힘 레이스(2026-08-01 라이브 실증): 가시성 확인~돋보기 클릭 사이에 패널이 다시
            #   접히면 rect 가 null 로 남아 열기가 실패한다 — 가시성을 재확보하고 1회만 재시도.
            logger.warning("전표유형 팝업 열기 실패 — 패널 재접힘 의심, 가시성 재확보 후 재시도")
            reopened = (
                await ensure_field_visible(page, DOCU_TYPE_LABEL)
                and await _open_picker(page, DOCU_TYPE_LABEL)
            )
            if not reopened:
                last["why"] = "전표유형 팝업을 열지 못했습니다(돋보기 미발견/팝업 미표시 — 패널 확장 확인)."
                return
        # ⚠ 실측(2026-07-21 읽기전용 진단, e2e/voucher_receivable_docu_type_diag.py): 이 팝업의
        # 실제 RealGrid 필드는 전자결재상태 팝업과 동일한 범용 코드테이블 스키마
        # SYSDEF_CD/SYSDEF_NM 이다 — 'DOCU_NM'/'DOCU_CD' 필드는 이 팝업엔 없다(2026-07-20 프로브
        # 기록이 실측과 어긋남 — 코드/명칭 레벨 불일치, PROCESS.md D2 정정 대상).
        res = await _eval_rows_when_loaded(page, js.POPUP_CHECK_ROWS_JS, [list(targets), "SYSDEF_NM"])
        checked = res.get("idxs") if isinstance(res, dict) else None
        if not (isinstance(res, dict) and res.get("ok") and checked and len(checked) == len(targets)):
            if _rows_never_loaded(res):
                last["why"] = f"전표유형 팝업 행이 로드되지 않았습니다(행 도착 대기 실패): {res}"
            else:
                last["why"] = f"전표유형 {list(targets)} 전부를 팝업에서 찾지 못했습니다: {res}"
                last["absent"] = True
            return
        last["checked"] = checked
        last["why"] = None
        if not await _apply_popup(page):
            last["why"] = "전표유형 팝업 적용/닫힘 실패(적용 버튼 미발견 또는 팝업이 닫히지 않음)."
            return
        last["done"] = True

    await attempt()
    if last["absent"]:
        return await _fail_close(page, last["why"])
    # 폼 반영 확인 — 표시 형식(이름/코드/건수)이 세션마다 달라 정확일치는 요구하지 않고
    # '비어있지 않음'을 근거로 삼는다(어느 대상을 체크했는지는 위 checkRow 가 이미 확정).
    # 미반영이면 attempt 전체(가시성 재확보 포함)를 재실행한다(2026-08-07 결과검증형 재시도).
    chk = await verify.confirm_display(
        page, DOCU_TYPE_LABEL, unknown_when=_unreadable_display, reapply=attempt
    )
    if last["done"] and (chk or chk.unknown):
        return _verdict(chk, checked=last["checked"], display=chk.actual)
    # 완주(적용까지) 없는 그럴듯한 표시값은 성공 근거가 아니다(스테일 표시 차단).
    return await _fail_close(page, chk.reason if last["done"] else (last["why"] or chk.reason))


# ══════════════════════════════════════════════════════════════════════════════
# D3 — 조회 실행 + 결과 그리드 읽기
# ══════════════════════════════════════════════════════════════════════════════
async def run_query(page: Any, *, expected: int | None = None) -> dict:
    """조회(F2, BTN_LOOKUP) → 마스터 그리드(index 0) rowcount 확정. 반환 {ok, rowcount, basis}.

    card_collect 조회 스텝 이식(2026-08-06 — 간헐 '거짓 0건' 포렌식 수정). 예전 구현은 클릭
    뒤 첫 폴(실질 ≈160ms — page.wait_for_timeout 이 delay_scale 0.4 로 축소)의 rowcount≥0 을
    그대로 믿어, ERP 응답이 늦으면 0건/부분 건수를 성공으로 확정했다(→ 조용한 '대상 없음'
    종료, 부분 계획으로 인한 '계획 밖 전표 혼입' 하드 실패). 규율을 바꾼다:
      * 클릭 **전** rowcount 를 기준값(base)으로 스냅샷 — 값이 base 와 **달라지면** 즉시 확정.
      * 무변화(특히 0건)는 verify.HEAVY 스케줄(실시간 대기 — delay_scale 무관)을 전부 소진한
        뒤에만 인정하고 basis='exhausted' 로 근거를 남긴다(진짜 0건 ↔ 조회 실패 구분).
      * 그래도 못 읽으면(-1/비정수) 재조회 1회 후 실패(grid_read_flow 의 재조회 관례).
      * expected(선택, 2026-08-07 상신 반영 재조회): 호출자가 아는 **기대 건수** — 값이 기대와
        일치하면 base 와 같아도 **즉시 확정**한다(basis='expected'). 상신 후 재조회는 결제창을
        닫는 순간 본창이 자동 갱신돼 클릭 전 값이 이미 기대값과 같으므로, 무변화 규율대로면
        매 건 HEAVY 전체(6.9s+)를 문다(사용자 리포트: 결제 후 ~10s 딜레이). 기대 불일치는
        기존 규율(변화 즉시 / 무변화 소진) 그대로 폴백한다.
    """
    before = await page.evaluate(js_lib.ROWCOUNT_BY_INDEX_JS, 0)
    # 그리드 미부착(-1)은 0 으로 본다 — 클릭 후의 0 을 '변화'로 오인하지 않기 위함(card_collect 동일).
    base = before if isinstance(before, int) and before >= 0 else 0
    _F2_OVERLAY_APPEAR_CAP_MS = 2_500  # F2 후 로딩 오버레이 출현 관찰 상한(실시간).
    clicked = {"ok": True}

    async def _click_lookup() -> bool:
        # ⚠ fire-and-forget 봉합(2026-08-07): js_click 반환(False=버튼 미발견)을 무시하면 base
        #   무변화 → basis='exhausted' 로 **조회 미실행이 '0건 정상완료'로 위장**된다. 미발견이면
        #   오버레이 소거를 기다렸다 1회 재시도하고, 그래도 없으면 명시적으로 실패시킨다.
        if await js_click(page, selectors.BTN_LOOKUP):
            return True
        await wait_loading_overlay_gone(page)
        return bool(await js_click(page, selectors.BTN_LOOKUP))

    async def _query_once() -> Any:
        clicked["ok"] = await _click_lookup()
        if not clicked["ok"]:
            return None  # 버튼을 못 눌렀다 — rowcount 폴링은 무의미.
        # F2 **리로드 수명주기** 대기(라이브 회귀 2026-08-07: expected 즉시확정이 리로드 완료
        # **전에** 반환 → 다음 묶음의 checkRow 가 뒤늦은 리로드에 씻겨나가 '행 미선택' 결재
        # 시도. 종전 무변화 HEAVY 소진이 우연히 이 리로드를 덮고 있었다). 클릭 직후 로딩
        # 오버레이 출현을 짧게 관찰하고, 떴으면 소멸까지 기다린 뒤에야 rowcount 를 확정한다.
        appeared = False
        t0 = time.monotonic()
        while (time.monotonic() - t0) * 1_000 < _F2_OVERLAY_APPEAR_CAP_MS:
            try:
                if await page.evaluate(js.LOADING_OVERLAY_VISIBLE_JS):
                    appeared = True
                    break
            except Exception:  # noqa: BLE001 — 스텁/버전차 방어(best-effort).
                break
            await verify.DEFAULT_SLEEP(0.1)
        if appeared:
            await wait_loading_overlay_gone(page)
        reads = {"n": 0, "hit": 0}

        def settled(v: Any) -> bool:
            if not isinstance(v, int) or v < 0:
                return False
            reads["n"] += 1
            if expected is not None and v == expected:
                reads["hit"] += 1
                # 기대 건수 일치 — base 와 같아도 확정(상신 반영 재조회). 단 오버레이를 관찰하지
                # 못했다면(리로드가 아직 시작 전일 수 있음) **연속 2회 일치**를 요구해 레이스를 막는다.
                return appeared or reads["hit"] >= 2
            if v != base:
                return True  # 새 결과 도착 — 즉시 확정.
            return reads["n"] >= len(verify.HEAVY)  # 무변화는 전체 대기를 소진한 뒤에만 인정.

        chk = await verify.confirm(
            lambda: page.evaluate(js_lib.ROWCOUNT_BY_INDEX_JS, 0),
            settled,
            timing=verify.HEAVY,
            what="조회 결과 rowcount",
            expected=f"기준({base}건)과 구분되는 확정값",
        )
        return chk.actual

    rc = await _query_once()
    if not clicked["ok"]:
        return {"ok": False, "reason": "조회(F2) 버튼을 찾지 못했습니다(재시도 포함) — 조회 미실행.", "rowcount": -1}
    if not (isinstance(rc, int) and rc >= 0):
        rc = await _query_once()  # 그리드 미부착/읽기 실패 — 재조회 1회.
        if not clicked["ok"]:
            return {"ok": False, "reason": "조회(F2) 버튼을 찾지 못했습니다(재시도 포함) — 조회 미실행.", "rowcount": -1}
    if isinstance(rc, int) and rc >= 0:
        if expected is not None and rc == expected:
            basis = "expected"
        else:
            basis = "changed" if rc != base else "exhausted"
        return {"ok": True, "rowcount": rc, "basis": basis}
    return {
        "ok": False,
        "reason": "조회 결과 그리드 rowcount 를 읽지 못했습니다(재조회 포함).",
        "rowcount": -1,
    }


async def read_master_rows(page: Any, limit: int = 5) -> dict:
    """마스터 그리드 컬럼+상위 N행 덤프(로깅/디버그용). 반환 {ok, n, cols, sample}."""
    return await page.evaluate(js.MASTER_DUMP_JS, limit)


async def read_row_key(page: Any, idx: int) -> str | None:
    """마스터 그리드 idx 행의 키(DOCU_NO). 못 읽으면 None."""
    return await page.evaluate(js.READ_ROW_KEY_JS, idx)


async def read_master_menus(page: Any, n: int) -> dict:
    """마스터 그리드 상위 n행의 메뉴(MENU_NM)+전표번호(DOCU_NO)를 한 번에 읽는다(왕복 1회).

    메뉴 필터(count_details, 2026-08-20 유형별 병합)가 행별 순회(372ms/행) **전에** 제외 대상을
    확정하는 용도. 반환 {ok, rows:[{idx, menu, docu_no}]} | {ok:False, reason}.
    """
    try:
        res = await page.evaluate(js.READ_MASTER_MENUS_JS, n)
        return res if isinstance(res, dict) else {"ok": False, "reason": f"비정상 반환: {res!r}"}
    except Exception as exc:  # noqa: BLE001 — 크래시 대신 실패 반환(호출부가 하드 중단 판단).
        return {"ok": False, "reason": str(exc)[:ERR_REASON_MAX]}


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
        # 시간축 규율(2026-08-07): 실패-경로 관찰창 — 실시간 sleep + latency 상한(종전
        # page.wait_for_timeout 은 delay_scale 0.4 로 상한이 3.2s 로 붕괴하던 명목 카운터).
        cap = latency.budget_ms(cap_ms)
        while waited < cap:
            visible = await page.evaluate(js.LOADING_OVERLAY_VISIBLE_JS)
            if not visible:
                return True
            await verify.DEFAULT_SLEEP(interval_ms / 1000)
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
        for _ in range(20):  # child.is_closed() 될 때까지(최대 ~2s 실시간, 100ms 폴링).
            if child.is_closed():
                break
            await verify.DEFAULT_SLEEP(0.1)  # 시간축 규율 — delay_scale 로 관찰창이 줄지 않게.
    except Exception:  # noqa: BLE001
        return
    # 근본원인 수정 지점 — 팝업 닫힘 직후 본창 로딩이 끝날 때까지 대기(다음 반복 진입 전).
    await wait_loading_overlay_gone(page)
    try:
        await page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    try:
        for _ in range(15):  # 결재 버튼 rect 가 다시 유효해질 때까지(최대 ~3s 실시간, 200ms 폴링).
            rect = await page.evaluate(js.APPROVAL_BTN_RECT_JS)
            if rect:
                return
            await verify.DEFAULT_SLEEP(0.2)  # 시간축 규율 — delay_scale 로 관찰창이 줄지 않게.
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
        # 자식 Page 는 _ScaledPage 미적용이라 종전에도 실시간이었다 — 시간축 단일화(관찰 대기는
        # 항상 실시간 sleep) 규율에 맞춰 통일한다(동작 불변).
        await verify.DEFAULT_SLEEP(interval_ms / 1000)
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
    """결제창을 닫는다 — 상신을 누르지 않았다면 아무것도 저장되지 않는다(비영속 확정 ✅).

    finally 경로에서 호출되므로 이미 닫힌/유실된 팝업이어도 예외를 삼켜(로그 후 무시) 런 전체가
    중단되지 않게 한다. 상신 성공 후에는 자식창이 이미 닫혀 있어 no-op 이다.
    """
    try:
        await child.close()
    except Exception:  # noqa: BLE001 — 이미 닫힘/유실된 팝업 teardown 은 무해.
        logger.debug("close_child: 결제창 닫기 실패(무시)", exc_info=True)


async def click_child_submit(
    child: Any, *, cap_ms: int = 25_000, interval_ms: int = 500
) -> dict:
    """⚠ 게이트 전용 — 결제창(EAP) '상신' 버튼 실클릭. loop_approvals 의 allow_submit
    (기본 False) 뒤에서만 호출된다. 게이트가 닫힌 기본 경로에서는 절대 도달하지 않는다.

    정책 전환(사용자 확정 2026-08-07): 상신은 이제 **가역** — 상신된 문서는
    `e2e/eap_approval_cancel_probe.py`(결재취소→상신취소→삭제, 실검증 2회 PASS)로 회수할 수
    있어 voucher 3종에 한해 실제 상신을 실행한다. '보관'은 여전히 절대 클릭하지 않는다.

    시퀀스(click_refdoc_confirm 과 동일 규율 — 세팅→독립확인):
      1. 상단 버튼 좌표를 **fresh** 로 읽어(CHILD_TOP_BUTTONS_JS) '상신'을 클릭한다(캐시 금지).
      2. 확인 다이얼로그가 뜨면 '확인'을 클릭한다(EAP React — 취소 프로브와 동일 버튼 패턴).
         ⚠ 상신 후속 다이얼로그·성공 신호는 미실측(리포 최초 실행 경로)이라 best-effort 다.
      3. 성공 판정 = **자식창 닫힘**. 상한 내 안 닫히면 {ok:False} — 호출자는 하드 실패로
         런을 중단한다(미상신이 성공으로 둔갑하는 조용한 실패 금지).
    반환 {ok, reason?}.
    """
    top: list[dict] = []
    try:
        top = await child.evaluate(js.CHILD_TOP_BUTTONS_JS) or []
    except Exception:  # noqa: BLE001 — 네비게이션 중 evaluate 실패 → 아래 미발견 처리.
        top = []
    btn = next((b for b in top if b.get("text") == "상신" and b.get("visible")), None)
    if not btn:
        return {"ok": False, "reason": "결제창에서 '상신' 버튼을 찾지 못했습니다."}
    try:
        await child.mouse.click(btn["x"], btn["y"])
    except Exception as exc:  # noqa: BLE001 — 클릭 실패는 하드 실패 사유로 반환.
        return {"ok": False, "reason": f"'상신' 클릭 실패: {str(exc)[:ERR_REASON_MAX]}"}

    t0 = time.monotonic()
    cap = latency.budget_ms(cap_ms)
    while (time.monotonic() - t0) * 1_000 < cap:
        try:
            if child.is_closed():
                return {"ok": True}
        except Exception:  # noqa: BLE001 — is_closed 미지원(스텁 등)은 닫힘으로 간주.
            return {"ok": True}
        # 확인 다이얼로그(있을 때만) 처리 — 없으면 짧은 timeout 으로 조용히 넘어간다.
        try:
            await child.get_by_role("button", name="확인").first.click(timeout=1_000)
        except Exception:  # noqa: BLE001 — 다이얼로그 없음/이미 닫힘.
            pass
        await verify.DEFAULT_SLEEP(interval_ms / 1000)  # 시간축 규율 — 관찰 대기는 실시간.
    return {"ok": False, "reason": "상신 클릭 후 결제창이 닫히지 않았습니다(적용 미확인)."}


# ── D5-1 결재라인 교차 지정(사용자 지시 2026-08-21) ─────────────────────────────
# 이트라이브/이트라이브2 계정은 상신 전에 상대 계정을 결재라인에 추가해야 한다(운영 규칙).
# 지정은 **비영속**(상신 없이 닫으면 소멸 — 실측 approval_line_probe_4b + cleanup)이라
# 결제창을 열 때마다, 상신 직전에 매번 수행한다. 그 외 계정은 no-op.
APPROVAL_LINE_CROSS = {"이트라이브": "이트라이브2", "이트라이브2": "이트라이브"}
# 결재라인 지정 모달 인원표(캔버스 RealGrid) 0-based 행 인덱스 — 인사/기획팀 5행 실측 순서
# (빈행/남희곤/황정하/이트라이브/이트라이브2, 2026-08-21). ⚠ 인원 변동 시 밀릴 수 있으나
# designate_approval_line 의 검증 게이트(전표 헤더 이름 리프 증가)가 오지정을 상신 전에 잡는다.
APPROVAL_LINE_MEMBER_ROW = {"이트라이브": 3, "이트라이브2": 4}


async def ensure_cross_approval_line(child: Any, userid: str | None) -> dict:
    """로그인 계정이 이트라이브/이트라이브2면 상대 계정을 결재라인에 추가(상신 직전 전용).

    반환 {ok, skipped?, target?, reason?} — skipped=True 는 대상 계정이 아니라 지정 자체를
    하지 않은 경우(기존 흐름 그대로). ok=False 면 호출자는 상신하지 말고 런을 중단한다
    (오지정 상태로 상신되는 조용한 실패 금지).
    """
    target = APPROVAL_LINE_CROSS.get(str(userid or "").strip())
    if target is None:
        return {"ok": True, "skipped": True}
    row = APPROVAL_LINE_MEMBER_ROW[target]
    return await approval_line_flow.designate_approval_line(child, target, row)
