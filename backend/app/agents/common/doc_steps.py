"""결의서입력 문서 공용 스텝 — 마스터 회계일 세팅 + 상세행 추가(F3).

card_collect 에서 승격(2026-07-06) — 결의서입력(GLDDOC00300) 문서 종류 공용(card·출장 등).
in-page JS 는 :mod:`nbkit.omnisol.js_lib` 단일 소스를 쓴다. 하위호환: card_collect 는
`set_acct_date`/`SET_ACCT_DATE_JS` 를 기존 위치에서 재수출(shim)해 기존 테스트를 보존한다.

⚠ 저장(F7)은 여기서 하지 않는다 — 각 에이전트 steps 의 저장 게이트에서만 실행한다.
"""

from __future__ import annotations

from typing import Any

from nbkit.browser.actions import js_click, mouse_click
from nbkit.omnisol import js_lib, latency, selectors, verify
from nbkit.omnisol.modals import dismiss_notice_popup

# 재수출(하위호환·가독성) — card js.SET_ACCT_DATE_JS 도 js_lib 단일소스를 재수출한다.
SET_ACCT_DATE_JS = js_lib.SET_ACCT_DATE_JS

# 마스터(결의서) 그리드 인덱스 — 회계일 readback 대상(디테일은 인덱스 1).
_MASTER_GRID_INDEX = 0


def _verdict(res: verify.Confirmed, **ok_extra: Any) -> dict:
    """확인 결과를 스텝 반환 dict 로 — 불일치는 하드 실패, 확인 불가는 warn 을 얹은 성공.

    voucher_receivable/steps.py 와 동일한 규율(§10): 리더로 읽었는데 값이 다르면 중단,
    리더가 필드/그리드를 못 읽으면(오탐 가능) 경고만 남기고 진행한다.
    """
    if res:
        return {"ok": True, **ok_extra}
    if res.unknown:
        return {"ok": True, "warn": res.reason, **ok_extra}
    return {"ok": False, "reason": res.reason}


def _grid_unreadable(v: Any) -> bool:
    """GRID_CELL_VALUE_JS 가 ok:false = 그리드/행을 못 읽음(값이 틀린 게 아니라 확인 불가)."""
    return not (isinstance(v, dict) and v.get("ok"))


async def set_acct_date(page: Any, ymd_compact: str, expect_display: str) -> dict:
    """마스터(결의서) 0행 회계일(ACTG_DT) 설정 + 표시값 검증 + **독립 readback**.

    반환 {ok, display, verified}|{ok:True, …, warn}|{ok:False, reason}.

    프로브 실측: ds.setValue(0,'ACTG_DT','YYYYMMDD') 로 설정되고 표시값이 dashed 로 확인된다.
    compact('YYYYMMDD') 만 사용한다 — 대시 형식은 오류 없이 셀을 비운다(함정).

    ⚠ 세터가 돌려주는 display 는 **setValue 와 같은 JS 콜 안에서 즉시** 읽은 스냅샷이다 —
    그리드 커밋 검증(마감월·전표일자 규칙)이 값을 **나중에 되돌리는** 조용한 실패는 그 값으로
    잡히지 않는다. 회계일은 저장될 데이터 자체(대상 정의)이므로, 별도 리더로 셀을 다시 읽어
    확인하고 불일치는 하드 실패로 끊는다(§10 실패 정책).
    ⚠ 날짜 셀 getValue 는 Date 객체라 String() 하면 'Tue Jul 07 2026 …' 이 된다 —
    GRID_CELL_VALUE_JS 의 compact(브라우저 로컬 Y/M/D → 'YYYYMMDD')로 비교해야 오판이 없다.
    """
    r = await page.evaluate(js_lib.SET_ACCT_DATE_JS, ymd_compact)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "회계일 설정 실패"}
    if (r.get("display") or "") != expect_display:
        return {
            "ok": False,
            "reason": f"회계일 표시값 불일치(기대 {expect_display}·실제 {r.get('display')!r})",
        }
    res = await verify.confirm(
        read=lambda: page.evaluate(
            js_lib.GRID_CELL_VALUE_JS,
            {"index": _MASTER_GRID_INDEX, "field": "ACTG_DT", "row": 0},
        ),
        ok=lambda v: isinstance(v, dict)
        and bool(v.get("ok"))
        and (v.get("compact") or {}).get("ACTG_DT") == ymd_compact,
        timing=verify.INSTANT,  # 그리드 셀 readback = DOM/데이터셋 즉시 반영 계열.
        what="회계일(ACTG_DT) 셀",
        expected=ymd_compact,
        unknown_when=_grid_unreadable,
    )
    return _verdict(res, display=r.get("display"), verified=bool(res))


async def add_next_row(page: Any, expected_count: int, *, timeout_polls: int = 33) -> dict:
    """추가(F3)로 상세행 1개 생성 — 디테일 그리드 rowCount 가 expected_count 로 늘 때까지 폴링.

    2행째 이후 반복 채움에서 쓴다(첫 행은 공유 앞단 add_row 노드가 만든다). expected_count 는
    추가 **후** 기대 행수(현재 n 이면 n+1). 반환 {ok, rows}|{ok:False, reason, rows}.
    """
    await js_click(page, selectors.BTN_ADD)
    rows: Any = -1
    # 300ms 간격(상한 ~10s) — add_row 노드와 동일 폴링. 회수 상한만 지연 배율(≤×4) 확대.
    for _ in range(latency.budget_polls(timeout_polls)):
        await page.wait_for_timeout(300)
        rows = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
        if isinstance(rows, int) and rows >= expected_count:
            return {"ok": True, "rows": rows}
    return {
        "ok": False,
        "reason": f"추가(F3) 후 행수 미달(기대 {expected_count}·실제 {rows})",
        "rows": rows if isinstance(rows, int) else -1,
    }


async def open_evdn_editor(page: Any) -> dict:
    """디테일 그리드 증빙 셀 → showEditor → 돋보기 실클릭 → 증빙유형 팝업 오픈(3회 재시도).

    RealGrid(캔버스) 셀이라 돋보기 좌표 픽셀 클릭이 빗나갈 수 있어 재시도한다. **순수 스텝**
    (emit 없음) — 호출부(공유 노드 make_open_evdn_node·출장 fill_rows)가 진행 이벤트를 방출한다.
    반환 {ok:True, shown, warn?} | {ok:False, reason}. shown 은 대상 행 로깅용 {ok, idx, rows}.
    """
    stale_warn: str | None = None
    for _attempt in range(1, 4):
        # 늦게 뜬 공지 팝업 방어(just-in-time) — 로그인 시점 닫기(2s 관찰창)를 넘겨 비동기
        # 렌더된 공지가 돋보기 클릭을 삼킨 실전 장애(2026-07-22 card-chat). voucher
        # _open_picker 와 동일한 검증 패턴(appear_cap_ms=0: 대기 없이 1회 확인).
        await dismiss_notice_popup(page, appear_cap_ms=0)
        if _attempt == 1:
            # 스테일 팝업 사전 감지 — 아래 '열림' 판정(EVDN_POPUP_OPEN_JS 폴링)은 "팝업이 떠
            # 있다"만 본다. 이전 행의 증빙 팝업이 '적용' 후에도 안 닫혔다면 돋보기 클릭이
            # 그 팝업에 먹혀도 즉시 '열림'으로 통과하고, 이어지는 select_evdn_code 의 '적용'이
            # **이전 행**의 셀에 쓰인다(2026-07-02 2패스 불공 덮어쓰기와 동형). 우리가 여는
            # 팝업인지 구분할 리더가 없어 하드 실패로 끊지 않고(오탐 시 정상 플로우 차단),
            # 확신할 수 없음을 warn 으로 올려 호출부 로그에 남긴다.
            if await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS):
                stale_warn = (
                    "증빙유형 팝업이 이미 열린 상태에서 시작 — 이전 행의 잔여(스테일) 팝업일 수 "
                    "있어 '새로 열림'을 확인하지 못했습니다."
                )
        shown = await page.evaluate(js_lib.OPEN_EVDN_EDITOR_JS)
        if not shown:
            continue
        rect = None
        waited = 0
        rect_cap_ms = latency.budget_ms(1_000)  # 돋보기 rect 준비 폴링(상한 1s × 지연 배율).
        while waited < rect_cap_ms:
            await page.wait_for_timeout(100)
            waited += 100
            rect = await page.evaluate(js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS)
            if rect:
                break
        if not rect:
            continue
        await mouse_click(page, rect["x"], rect["y"])  # 돋보기(캔버스) 클릭
        opened = False
        for _ in range(latency.budget_polls(20)):  # 300ms 간격(상한 6s, 회수만 배율 확대)
            await page.wait_for_timeout(300)
            opened = await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS)
            if opened:
                break
        if opened:
            out = {"ok": True, "shown": shown}
            if stale_warn:
                out["warn"] = stale_warn
            return out
    return {
        "ok": False,
        "reason": "증빙유형 팝업이 열리지 않았습니다(돋보기 클릭 3회 실패). 잠시 후 다시 실행해 주세요.",
    }


async def select_evdn_code(page: Any, code: str) -> dict:
    """증빙유형을 code 로 자동선택 → '적용' 실클릭 → 디테일 증빙 셀 반영 판정(HITL 없음).

    **순수 스텝**(emit 없음). 반환 {ok:True, name, code} | {ok:False, reason}. 저장(F7) 안 함.
    팝업 '창'은 떠도 내부 그리드 행이 늦게 로드되는 레이스가 있어 선택 자체를 폴링한다.
    """
    # 증빙 팝업이 뜬 뒤 공지가 늦게 화면을 덮으면 아래 '적용' 실클릭이 공지에 먹힌다 — 선택
    # 전 1회 재확인(EVDN_* JS 는 그리드 보유 다이얼로그만 잡아 오인은 없지만 클릭은 좌표라 방어).
    await dismiss_notice_popup(page, appear_cap_ms=0)
    r: dict = {}
    for _ in range(latency.budget_polls(20)):  # 행 로드 폴링(상한 ~6s, 회수만 배율 확대)
        r = await page.evaluate(js_lib.EVDN_SELECT_BY_CODE_JS, code)
        if r.get("ok"):
            break
        await page.wait_for_timeout(300)
    if not r.get("ok"):
        return {"ok": False, "reason": f"증빙유형 코드 {code} 자동선택 실패: {r.get('reason')}"}
    await page.wait_for_timeout(500)
    sel_name = r.get("name") or ""
    box = await page.evaluate(js_lib.EVDN_APPLY_BOX_JS)
    if box:
        await mouse_click(page, box["x"], box["y"])
    for _ in range(latency.budget_polls(27)):  # 셀 반영 폴링(상한 ~8s, 회수만 배율 확대)
        await page.wait_for_timeout(300)
        cell = await page.evaluate(js_lib.DETAIL_EVDN_CELL_JS)
        if sel_name and sel_name in cell:
            out = {"ok": True, "name": sel_name, "code": r.get("code")}
            closed = await _confirm_evdn_popup_closed(page)
            if not closed:
                out["warn"] = closed.reason
            return out
    return {"ok": False, "reason": "증빙유형 자동 적용(적용 버튼)에 실패했습니다."}


async def _confirm_evdn_popup_closed(page: Any) -> verify.Confirmed:
    """'적용' 후 증빙유형 팝업이 실제로 닫혔는지 확인 — **다음 행**의 조용한 실패를 막는 근거.

    셀 반영이 확인된 이상 이 문서의 데이터는 맞으므로 하드 실패로 끊지 않는다(보조 조건 →
    warn 후 진행). 다만 팝업이 남으면 다음 행의 open_evdn_editor 가 그 스테일 팝업을 '열렸다'로
    오판하고, 그 팝업의 '적용'이 **이 행**의 셀에 다시 쓰인다 — 조회조건 피커에서 같은 유형의
    잔여 팝업이 46행 부서 목록을 오독하게 했던 2026-07-24 사례와 동형이다. 원인 지점에서
    경고를 남겨야 결과(엉뚱한 행 증빙)만 보고 원인을 되짚는 일이 없다.

    EVDN_POPUP_OPEN_JS 는 '그리드를 가진 보이는 dialog' 를 요구하므로 공지 팝업을 증빙 팝업으로
    오탐하지 않는다(k-window 총개수보다 정밀 — 배경의 카드 팝업 등에 흔들리지 않는다).
    """
    return await verify.confirm(
        read=lambda: page.evaluate(js_lib.EVDN_POPUP_OPEN_JS),
        ok=lambda v: not v,  # falsy = 보이는 증빙 dialog 없음(= 닫힘).
        timing=verify.ASYNC,  # 팝업 개폐 = 위젯 왕복 계열.
        what="증빙유형 팝업 닫힘",
        expected="닫힘",
    )
