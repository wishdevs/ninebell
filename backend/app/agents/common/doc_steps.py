"""결의서입력 문서 공용 스텝 — 마스터 회계일 세팅 + 상세행 추가(F3).

card_collect 에서 승격(2026-07-06) — 결의서입력(GLDDOC00300) 문서 종류 공용(card·출장 등).
in-page JS 는 :mod:`nbkit.omnisol.js_lib` 단일 소스를 쓴다. 하위호환: card_collect 는
`set_acct_date`/`SET_ACCT_DATE_JS` 를 기존 위치에서 재수출(shim)해 기존 테스트를 보존한다.

⚠ 저장(F7)은 여기서 하지 않는다 — 각 에이전트 steps 의 저장 게이트에서만 실행한다.
"""

from __future__ import annotations

from typing import Any

from nbkit.browser.actions import js_click, mouse_click
from nbkit.omnisol import js_lib, selectors

# 재수출(하위호환·가독성) — card js.SET_ACCT_DATE_JS 도 js_lib 단일소스를 재수출한다.
SET_ACCT_DATE_JS = js_lib.SET_ACCT_DATE_JS


async def set_acct_date(page: Any, ymd_compact: str, expect_display: str) -> dict:
    """마스터(결의서) 0행 회계일(ACTG_DT) 설정 + 표시값 검증. 반환 {ok, display}|{ok:False, reason}.

    프로브 실측: ds.setValue(0,'ACTG_DT','YYYYMMDD') 로 설정되고 표시값이 dashed 로 확인된다.
    compact('YYYYMMDD') 만 사용한다 — 대시 형식은 오류 없이 셀을 비운다(함정).
    """
    r = await page.evaluate(js_lib.SET_ACCT_DATE_JS, ymd_compact)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "회계일 설정 실패"}
    if (r.get("display") or "") != expect_display:
        return {
            "ok": False,
            "reason": f"회계일 표시값 불일치(기대 {expect_display}·실제 {r.get('display')!r})",
        }
    return {"ok": True, "display": r.get("display")}


async def add_next_row(page: Any, expected_count: int, *, timeout_polls: int = 33) -> dict:
    """추가(F3)로 상세행 1개 생성 — 디테일 그리드 rowCount 가 expected_count 로 늘 때까지 폴링.

    2행째 이후 반복 채움에서 쓴다(첫 행은 공유 앞단 add_row 노드가 만든다). expected_count 는
    추가 **후** 기대 행수(현재 n 이면 n+1). 반환 {ok, rows}|{ok:False, reason, rows}.
    """
    await js_click(page, selectors.BTN_ADD)
    rows: Any = -1
    for _ in range(timeout_polls):  # 300ms 간격(상한 ~10s) — add_row 노드와 동일 폴링.
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
    반환 {ok:True, shown} | {ok:False, reason}. shown 은 대상 행 로깅용 {ok, idx, rows}.
    """
    for _attempt in range(1, 4):
        shown = await page.evaluate(js_lib.OPEN_EVDN_EDITOR_JS)
        if not shown:
            continue
        rect = None
        waited = 0
        while waited < 1_000:  # 돋보기 rect 준비 폴링(상한 1s)
            await page.wait_for_timeout(100)
            waited += 100
            rect = await page.evaluate(js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS)
            if rect:
                break
        if not rect:
            continue
        await mouse_click(page, rect["x"], rect["y"])  # 돋보기(캔버스) 클릭
        opened = False
        for _ in range(20):  # 300ms 간격(상한 6s)
            await page.wait_for_timeout(300)
            opened = await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS)
            if opened:
                break
        if opened:
            return {"ok": True, "shown": shown}
    return {
        "ok": False,
        "reason": "증빙유형 팝업이 열리지 않았습니다(돋보기 클릭 3회 실패). 잠시 후 다시 실행해 주세요.",
    }


async def select_evdn_code(page: Any, code: str) -> dict:
    """증빙유형을 code 로 자동선택 → '적용' 실클릭 → 디테일 증빙 셀 반영 판정(HITL 없음).

    **순수 스텝**(emit 없음). 반환 {ok:True, name, code} | {ok:False, reason}. 저장(F7) 안 함.
    팝업 '창'은 떠도 내부 그리드 행이 늦게 로드되는 레이스가 있어 선택 자체를 폴링한다.
    """
    r: dict = {}
    for _ in range(20):  # 행 로드 폴링(상한 ~6s)
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
    for _ in range(27):  # 셀 반영 폴링(상한 ~8s)
        await page.wait_for_timeout(300)
        cell = await page.evaluate(js_lib.DETAIL_EVDN_CELL_JS)
        if sel_name and sel_name in cell:
            return {"ok": True, "name": sel_name, "code": r.get("code")}
    return {"ok": False, "reason": "증빙유형 자동 적용(적용 버튼)에 실패했습니다."}
