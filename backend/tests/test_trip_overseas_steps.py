"""출장(해외/정산서) steps/노드 — **확인 커널 계약** 테스트(브라우저 없음).

여기서 검증하는 것은 "세팅 호출이 성공했다"가 아니라 **"값이 실제로 반영됐는지 확인한다"** 는
규율이다. 각 지점마다 세 갈래를 고정한다:
  1) 반영 성공        → ok
  2) 반영 실패(값 다름) → 하드 실패(reason)
  3) 리더가 못 읽음    → 확인 불가 = 통과 + warn(플로우를 끊지 않되 '완료'라고 단정하지 않음)

가짜 page 는 **실물 시맨틱**을 지킨다:
  * 셀 값은 그리드 상태(dict)에 보관하고, 세팅 JS 와 **독립된** 리더(GRID_CELL_VALUE_JS)가 그
    상태를 읽는다 — 실제 조용한 실패(세팅 JS 는 ok 인데 값이 안 붙음)를 재현할 수 있어야 한다.
  * 팝업은 개수로 모델링하고 PICKER_ROWCOUNT_JS 는 '최상단 팝업'을 흉내낸다(잔존 팝업이 있으면
    새 팝업이 안 떠도 행수를 돌려준다 — 열림 오판 사고의 원인 구조).
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.trip_overseas import js, steps
from nbkit.omnisol import js_lib

MAGNIFIER = {"x": 10, "y": 10}
APPLY_BTN = {"x": 20, "y": 20}


class _FakeKeyboard:
    async def press(self, key, delay=None):  # noqa: ANN001
        return None


class _FakeMouse:
    def __init__(self, page: "_FakeDetailPage") -> None:
        self._page = page

    async def click(self, x, y):  # noqa: ANN001
        await self._page.on_click(x, y)


class _FakeDetailPage:
    """detail 그리드 + 코드피커 팝업의 최소 가짜 page.

    옵션 플래그로 조용한 실패를 재현한다:
      set_writes    — SET_DETAIL_CELL_JS 가 실제로 셀에 값을 쓰는가(False = 세팅이 튕김)
      cell_readable — GRID_CELL_VALUE_JS 가 읽히는가(False = 확인 불가)
      mag_opens     — 돋보기 클릭이 새 팝업을 여는가(False = 클릭 빗나감)
      apply_writes  — '적용' 클릭이 대상 셀에 값을 반영하는가
      apply_closes  — '적용' 클릭이 팝업을 닫는가(False = 잔존 팝업)
      apply_effective_at — 몇 번째 '적용' 클릭부터 먹는가(2 = 첫 클릭 튕김 → reapply 검증)
      close_works   — PICKER_CLOSE_JS 가 실제로 팝업을 닫는가(False = 닫기 무효)
    """

    def __init__(
        self,
        *,
        cells: dict | None = None,
        popups: int = 0,
        picker_rows: int = 3,
        options: list[dict] | None = None,
        set_writes: bool = True,
        cell_readable: bool = True,
        mag_opens: bool = True,
        apply_writes: tuple[str, str] | None = None,
        apply_closes: bool = True,
        apply_effective_at: int = 1,
        close_works: bool = True,
    ) -> None:
        self.cells = dict(cells or {})
        self.popups = popups
        self.picker_rows = picker_rows
        self.options = options if options is not None else []
        self.set_writes = set_writes
        self.cell_readable = cell_readable
        self.mag_opens = mag_opens
        self.apply_writes = apply_writes
        self.apply_closes = apply_closes
        self.apply_effective_at = apply_effective_at
        self.close_works = close_works
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse(self)
        self.searches: list[str] = []
        self.read_calls = 0
        self.set_calls = 0
        self.apply_clicks = 0
        self.closed = 0

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def on_click(self, x, y):  # noqa: ANN001
        if (x, y) == (MAGNIFIER["x"], MAGNIFIER["y"]) and self.mag_opens:
            self.popups += 1
        if (x, y) == (APPLY_BTN["x"], APPLY_BTN["y"]):
            self.apply_clicks += 1
            if self.apply_clicks < self.apply_effective_at:
                return  # 튕겨나간 '적용' — 셀도 팝업도 그대로.
            if self.apply_writes:
                field, value = self.apply_writes
                self.cells[field] = value
            if self.apply_closes:
                self.popups = max(0, self.popups - 1)

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001, C901
        if jsstr is js.SET_DETAIL_CELL_JS:
            self.set_calls += 1
            if self.set_writes:
                self.cells[arg["field"]] = str(arg["value"])
            # ⚠ 실물과 동일하게 self-readback 은 **세팅 JS 자기 반환값**이라 튕김을 못 잡는다.
            return {"ok": True, "row": 0, "after": str(arg["value"]), "display": str(arg["value"])}
        if jsstr is js_lib.GRID_CELL_VALUE_JS:
            self.read_calls += 1
            if not self.cell_readable:
                return {"ok": False, "reason": "행 없음", "rows": 0}
            field = arg.get("field")
            raw = str(self.cells.get(field, ""))
            return {
                "ok": True,
                "row": 0,
                "rows": 1,
                "raw": {field: raw},
                "compact": {field: "".join(c for c in raw if c.isdigit())},
                "display": {field: raw},
            }
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.popups
        if jsstr is js_lib.OPEN_DETAIL_CELL_EDITOR_JS:
            return {"ok": True, "field": arg}
        if jsstr is js_lib.DETAIL_EDITOR_MAGNIFIER_JS:
            return dict(MAGNIFIER)
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            # 최상단 팝업 기준 — 팝업이 하나라도 떠 있으면 행수를 돌려준다(잔존 팝업 오판 재현).
            return self.picker_rows if self.popups > 0 else -1
        if jsstr is js_lib.PICKER_SEARCH_JS:
            self.searches.append(arg)
            return {"ok": True, "field": "customTextBox"}
        if jsstr is js_lib.PICKER_READ_MULTI_JS:
            opts = self.options.pop(0) if self.options and isinstance(self.options[0], list) else []
            return {"rows": len(opts), "options": opts}
        if jsstr is js_lib.PICKER_SELECT_JS:
            return {"ok": True, "row": arg}
        if jsstr is js_lib.PICKER_APPLY_BTN_JS:
            return dict(APPLY_BTN)
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closed += 1
            if self.close_works:
                self.popups = max(0, self.popups - 1)
            return True
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 적요(NOTE_DC) — 담당 경로에서 유일하게 readback 이 빠져 있던 값 세팅 지점
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_set_row_note_confirms_cell_value():
    page = _FakeDetailPage()
    r = await steps.set_row_note(page, "해외출장 일비")
    assert r["ok"] is True and "warn" not in r
    assert page.cells["NOTE_DC"] == "해외출장 일비"
    assert page.read_calls >= 1  # 세팅 self-readback 이 아니라 **독립 리더**로 확인했다.


@pytest.mark.asyncio
async def test_set_row_note_bounced_value_is_hard_failure():
    """세팅 JS 는 ok 인데 셀에 값이 안 붙는 조용한 실패 → 하드 실패(적요 없는 결의서 저장 차단)."""
    page = _FakeDetailPage(set_writes=False)
    r = await steps.set_row_note(page, "해외출장 일비")
    assert r["ok"] is False
    assert "적요" in r["reason"]
    assert page.set_calls > 1  # 튕긴 값이라 재시도 때 재세팅(reapply)까지 시도했다.


@pytest.mark.asyncio
async def test_set_row_note_unreadable_grid_warns_and_passes():
    """리더가 그리드를 못 읽음 = 확인 불가 → 하드 실패 금지, warn 후 진행."""
    page = _FakeDetailPage(cell_readable=False)
    r = await steps.set_row_note(page, "해외출장 일비")
    assert r["ok"] is True
    assert "확인 불가" in r["warn"]


# ══════════════════════════════════════════════════════════════════════════════
# 피커 팝업 개폐 — 개수로 판정(스테일 팝업 오독 차단)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_open_detail_cell_picker_confirms_new_popup():
    page = _FakeDetailPage(popups=0)
    r = await steps._open_detail_cell_picker(page, steps.PARTNER_CELL, "거래처")
    assert r["ok"] is True and page.popups == 1


@pytest.mark.asyncio
async def test_open_detail_cell_picker_rejects_stale_popup():
    """잔존 팝업이 있고 돋보기 클릭이 빗나간 상황 — rowcount 는 읽히지만 **새 팝업이 아니다**.

    개수 증가를 확인하지 않으면 이 상태가 '열림'으로 통과해 앞 단계 팝업을 조작하게 된다.
    """
    page = _FakeDetailPage(popups=1, mag_opens=False)
    r = await steps._open_detail_cell_picker(page, steps.PARTNER_CELL, "거래처")
    assert r["ok"] is False
    assert "열리지 않았습니다" in r["reason"]


@pytest.mark.asyncio
async def test_select_and_apply_confirms_cell_and_close():
    page = _FakeDetailPage(popups=1, apply_writes=("BG_NM", "회계팀"))
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "회계팀")
    assert r["ok"] is True and "warn" not in r
    assert page.popups == 0


@pytest.mark.asyncio
async def test_select_and_apply_fails_when_popup_stays_open():
    """셀은 반영됐지만 팝업이 안 닫힘 — 잔존 팝업은 F7 을 삼켜 팬텀 저장을 유발하므로 실패."""
    page = _FakeDetailPage(popups=1, apply_writes=("BG_NM", "회계팀"), apply_closes=False)
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "회계팀")
    assert r["ok"] is False
    assert "닫히지 않았습니다" in r["reason"]


@pytest.mark.asyncio
async def test_select_and_apply_fails_when_cell_not_reflected():
    page = _FakeDetailPage(popups=1, apply_writes=None)
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "회계팀")
    assert r["ok"] is False
    assert "미반영" in r["reason"]
    assert page.closed == 1  # 실패 경로는 팝업을 닫고 나간다(다음 피커 오독 방지).


@pytest.mark.asyncio
async def test_select_and_apply_unreadable_cell_warns():
    page = _FakeDetailPage(popups=1, cell_readable=False, apply_writes=("BG_NM", "회계팀"))
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "회계팀")
    assert r["ok"] is True
    assert "확인 불가" in r["warn"]


@pytest.mark.asyncio
async def test_select_and_apply_reclicks_apply_when_first_click_bounces():
    """첫 '적용'이 튕긴 세션 — 대기·재확인만으로는 영영 안 붙는다(국내 하드닝판 reapply 공유로 살린다)."""
    page = _FakeDetailPage(popups=1, apply_writes=("BG_NM", "회계팀"), apply_effective_at=2)
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "회계팀")
    assert r["ok"] is True and page.apply_clicks >= 2


@pytest.mark.asyncio
async def test_fail_close_appends_unclosed_popup_warning():
    """실패 정리의 닫기가 안 먹는 세션 — '닫았다'를 단정하지 않고 원래 사유에 미닫힘 경고를 덧붙인다."""
    page = _FakeDetailPage(popups=1, apply_writes=None, apply_closes=False, close_works=False)
    r = await steps._select_and_apply(page, 0, "예산단위", "BG_NM", "회계팀")
    assert r["ok"] is False and "미반영" in r["reason"] and "미닫힘" in r["reason"]
    assert page.closed >= 2  # 재닫기(reapply)까지 시도했다.


@pytest.mark.asyncio
async def test_open_detail_cell_picker_closes_stale_popup_before_retry():
    """재시도 진입 시 직전 시도가 남긴 팝업을 닫는다 — 기준선(before) 오염으로 '개수 증가' 확인이
    스테일 팝업으로 충족되는 것을 막는 국내 하드닝판의 정리 경로."""
    page = _FakeDetailPage(popups=1, mag_opens=False)
    r = await steps._open_detail_cell_picker(page, steps.PARTNER_CELL, "거래처")
    assert r["ok"] is False and page.closed >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 예산단위 — 클라이언트 필터 정착 레이스(무매칭이면 재검색)
# ══════════════════════════════════════════════════════════════════════════════
_BG_MATCH = [
    {
        "i": 0,
        "BG_CD": "2005",
        "BG_NM": "회계팀",
        "BIZPLAN_NM": "운영비",
        "BGACCT_NM": "(판)여비교통비-해외출장",
    }
]
_BG_UNFILTERED = [
    {
        "i": 0,
        "BG_CD": "9999",
        "BG_NM": "구매팀",
        "BIZPLAN_NM": "운영비",
        "BGACCT_NM": "(판)여비교통비-국내출장",
    }
]


@pytest.mark.asyncio
async def test_fill_budget_retries_search_until_filter_settles():
    """Enter 직후 첫 재독이 **필터 전 상단행**이면 재검색으로 정착을 기다린다(무매칭 즉시 실패 금지)."""
    page = _FakeDetailPage(
        popups=0, options=[_BG_UNFILTERED, _BG_MATCH], apply_writes=("BG_NM", "회계팀")
    )
    r = await steps.fill_budget_fixed(page, "회계팀", "판관비")
    assert r["ok"] is True and r["code"] == "2005"
    assert len(page.searches) >= 2  # 재검색(reapply)이 실제로 일어났다.


@pytest.mark.asyncio
async def test_fill_budget_no_match_reports_candidates():
    page = _FakeDetailPage(popups=0, options=[_BG_UNFILTERED, _BG_UNFILTERED, _BG_UNFILTERED, _BG_UNFILTERED])
    r = await steps.fill_budget_fixed(page, "회계팀", "판관비")
    assert r["ok"] is False
    assert "무매칭" in r["reason"]
    assert page.closed == 1  # 실패해도 팝업은 닫고 나간다.


# ══════════════════════════════════════════════════════════════════════════════
# 프로젝트 — 필터 정착 전 읽기(필터 전 행 인덱스 선택)를 재검색으로 살린다(국내 역이식)
# ══════════════════════════════════════════════════════════════════════════════
_PJT_MATCH = [{"i": 0, "PJT_NO": "PJ1", "PJT_NM": "알파", "WBS_NO": "W2"}]
_PJT_UNFILTERED = [{"i": 0, "PJT_NO": "PJ9", "PJT_NM": "베타", "WBS_NO": "W9"}]


@pytest.mark.asyncio
async def test_fill_project_retries_search_until_filter_settles():
    """정착 전 첫 읽기가 필터 전 행 목록이면 재검색으로 정착을 기다린다 — 같은 PJT_NM 의 다른
    WBS 인덱스를 뽑아도 셀 검증(PJT_NM)이 못 잡는 자리라 읽기 자체를 정착 후로 확정해야 한다."""
    page = _FakeDetailPage(
        popups=0, options=[_PJT_UNFILTERED, _PJT_MATCH], apply_writes=("PJT_NM", "알파")
    )
    r = await steps.fill_project(page, {"name": "알파", "wbsNo": "W2"})
    assert r["ok"] is True and r["code"] == "PJ1"
    assert len(page.searches) >= 2  # 재검색(정착 대기)이 실제로 일어났다.


@pytest.mark.asyncio
async def test_fill_project_no_match_closes_and_fails():
    page = _FakeDetailPage(popups=0, options=[_PJT_UNFILTERED] * 4)
    r = await steps.fill_project(page, {"name": "알파", "wbsNo": "W2"})
    assert r["ok"] is False and "무매칭" in r["reason"]
    assert page.closed >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 조회 전용 경로 — 잔존 팝업(유일한 부작용 위험)을 닫힘까지 확인하고 나간다
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_lookup_partner_code_closes_popup_verified():
    opts = [[{"i": 0, "PARTNER_CD": "00037", "PARTNER_NM": "이트라이브2"}]]
    page = _FakeDetailPage(popups=0, options=opts)
    code = await steps.lookup_partner_code(page, "이트라이브2")
    assert code == "00037"
    assert page.popups == 0 and page.closed >= 1  # 고정 대기가 아니라 닫힘 확인으로 정리했다.


@pytest.mark.asyncio
async def test_lookup_partner_code_warns_when_popup_not_closed(caplog):
    """⚠ 핀(2026-08-07 리뷰): 닫기가 무효한 세션 — **검증된 닫기**가 미닫힘을 감지해 경고를
    남긴다(종전 무검증 닫기+고정 대기로 되돌리면 경고가 사라져 이 단언이 잡는다). 조회 전용이라
    반환 계약(code|None)은 유지."""
    import logging

    opts = [[{"i": 0, "PARTNER_CD": "00037", "PARTNER_NM": "이트라이브2"}]]
    page = _FakeDetailPage(popups=0, options=opts, close_works=False)
    with caplog.at_level(logging.WARNING, logger="app.agents.trip_overseas.steps"):
        code = await steps.lookup_partner_code(page, "이트라이브2")
    assert code == "00037"
    assert any("상대계정 코드조회 팝업 미닫힘" in r.message for r in caplog.records)


class _DumpMouse:
    """코드피커 버튼 클릭 → 팝업이 실제로 열린다(개수 0→1)."""

    def __init__(self, page) -> None:  # noqa: ANN001
        self._p = page

    async def click(self, x, y):  # noqa: ANN001
        self._p.popups = 1


class _DumpPage:
    """dump_partners 용 가짜 page — 팝업 개수를 실제 상태로 들고 있어 오픈(0→1) 확인과
    검증된 닫기(1→0)가 가짜 통과가 되지 않게 한다(국내 _FakePartnerPage 미러)."""

    def __init__(self, rowcount: int, options: list[dict]) -> None:
        self._rowcount = rowcount
        self._options = options
        self.keyboard = _FakeKeyboard()
        self.mouse = _DumpMouse(self)
        self.popups = 0
        self.closed = 0
        self.clock_ms = 0.0

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        self.clock_ms += ms  # _poll_rowcount_over 실시간 상한용 가짜 시계 전진.

    def install_clock(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.agents.trip_domestic.steps.time.monotonic", lambda: self.clock_ms / 1_000
        )

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.PICKER_ROWCOUNT_JS:
            return self._rowcount if self.popups else -1
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self.popups
        if jsstr is js_lib.PICKER_SEARCH_JS:
            return {"ok": True, "field": "customTextBox"}
        if jsstr is js_lib.PICKER_FOCUS_LAST_JS:
            return {"ok": True, "row": self._rowcount - 1}
        if jsstr is js_lib.PICKER_READ_MULTI_JS:
            return {"rows": self._rowcount, "options": self._options}
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closed += 1
            self.popups = 0
            return True
        if "dews-codepicker-button" in jsstr:  # picker_btn_js(동적 f-string)
            return {"x": 10, "y": 10}
        return None


class _NoopDumpMouse:
    """클릭이 먹지 않는 마우스 — 코드피커 버튼을 눌러도 팝업이 열리지 않는 세션 재현."""

    async def click(self, x, y):  # noqa: ANN001
        return None


class _StickyDumpPage(_DumpPage):
    """닫기 JS 가 듣지 않는 팝업 — 검증된 닫기가 미닫힘을 감지해야 하는 세션 재현."""

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.PICKER_CLOSE_JS:
            self.closed += 1
            return True  # 닫기 호출은 성공 반환하지만 popups 는 유지(닫힘 무효).
        return await super().evaluate(jsstr, arg)


@pytest.mark.asyncio
async def test_dump_partners_warns_when_popup_never_opens(monkeypatch, caplog):
    """⚠ 핀(2026-08-07 리뷰): 클릭이 팝업을 못 열면 '개수 증가 미확인' 경고 — 오픈 확인을
    되돌리면(무검증 클릭) 경고가 사라져 이 단언이 잡는다(스테일 팝업 오독 전조 표면화)."""
    import logging

    page = _DumpPage(rowcount=0, options=[])
    page.mouse = _NoopDumpMouse()
    page.install_clock(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app.agents.trip_overseas.steps"):
        await steps.dump_partners(page, max_rounds=2)
    assert any("거래처 팝업 개수 증가 미확인" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_dump_partners_warns_when_close_fails(monkeypatch, caplog):
    """⚠ 핀(2026-08-07 리뷰): 닫기가 무효하면 '덤프 팝업 미닫힘' 경고 — 검증된 닫기를 되돌리면
    경고가 사라져 이 단언이 잡는다(잔존 팝업이 다음 코드피커를 오염시키는 전조)."""
    import logging

    opts = [{"PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"}]
    page = _StickyDumpPage(rowcount=1, options=opts)
    page.install_clock(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app.agents.trip_overseas.steps"):
        rows = await steps.dump_partners(page, max_rounds=2)
    assert [r["code"] for r in rows] == ["10512"]  # 덤프 자체는 성공(경고 병기).
    assert any("거래처 덤프 팝업 미닫힘" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_dump_partners_confirms_open_and_verified_close(monkeypatch):
    """오픈은 개수 증가로 확인하고, 닫기는 닫힘까지 확인한다(스테일 팝업 잔존 차단 — 국내 미러)."""
    opts = [
        {"PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"},
        {"PARTNER_CD": "10512", "PARTNER_NM": "한국도로공사", "BIZR_NO": "1298200103"},  # 중복
        {"PARTNER_CD": "00037", "PARTNER_NM": "전준현", "BIZR_NO": None},
    ]
    page = _DumpPage(rowcount=3, options=opts)
    page.install_clock(monkeypatch)
    rows = await steps.dump_partners(page, max_rounds=5)
    assert page.popups == 0 and page.closed >= 1  # 종료 시 닫힘이 확인됐다.
    assert [r["code"] for r in rows] == ["10512", "00037"]


# ══════════════════════════════════════════════════════════════════════════════
# fill_rows 노드 — 스텝의 warn(확인 불가)을 로그로 노출하고 '완료'라고 쓰지 않는다
# ══════════════════════════════════════════════════════════════════════════════
async def _run_fill_rows(monkeypatch, *, note_result: dict) -> dict:
    """행 채움 스텝을 전부 성공으로 스텁하고 적요만 주어진 결과로 바꿔 노드 계약을 본다."""
    from app.agents.common import doc_steps
    from app.agents.trip_overseas import steps as ov_steps
    from app.agents.trip_overseas.nodes import fill as fill_mod

    async def _ok(*a, **kw):  # noqa: ANN001
        return {"ok": True}

    for mod, name in [
        (doc_steps, "add_next_row"),
        (doc_steps, "open_evdn_editor"),
        (doc_steps, "select_evdn_code"),
        (ov_steps, "set_invoice_date"),
        (ov_steps, "fill_partner_by_search"),
        (ov_steps, "fill_budget_fixed"),
        (ov_steps, "fill_project"),
        (ov_steps, "type_amount"),
        (ov_steps, "register_counter_partner"),
        (ov_steps, "delete_blank_row"),
        (ov_steps, "set_master_total"),
    ]:
        monkeypatch.setattr(mod, name, _ok)

    async def _note(page, text):  # noqa: ANN001
        return dict(note_result)

    monkeypatch.setattr(ov_steps, "set_row_note", _note)

    async def _no_shot(emit, page, window="parent"):  # noqa: ANN001
        return None

    monkeypatch.setattr(fill_mod, "emit_shot", _no_shot)

    events: asyncio.Queue = asyncio.Queue()
    node = fill_mod.make_fill_rows_node()
    out = await node(
        {
            "events": events,
            "page": _FakeDetailPage(),
            "userid": "이트라이브2",
            "department": "회계팀",
            "cost_type": "판관비",
            "plan_rows": [{"invoiceDate": "20260401", "amount": 1000, "project": {}, "note": "일비"}],
        }
    )
    logs = []
    while not events.empty():
        ev = events.get_nowait()
        if "log" in ev:
            logs.append(ev)
    return {"out": out, "logs": logs}


@pytest.mark.asyncio
async def test_fill_rows_surfaces_unverified_warn(monkeypatch):
    res = await _run_fill_rows(
        monkeypatch, note_result={"ok": True, "warn": "적요(NOTE_DC) 확인 불가(기대 '일비' / 실제 None)"}
    )
    assert res["out"]["unverified"] == ["1행 적요"]
    warn_logs = [log["log"] for log in res["logs"] if log["level"] == "warn"]
    assert any("확인 불가" in m for m in warn_logs)
    # 미확인이 있으면 행 로그를 '반영 완료'로 쓰지 않는다.
    assert not any("반영 완료" in log["log"] for log in res["logs"])


@pytest.mark.asyncio
async def test_fill_rows_clean_run_has_no_warn(monkeypatch):
    res = await _run_fill_rows(monkeypatch, note_result={"ok": True, "after": "일비"})
    assert res["out"]["unverified"] == []
    assert any("반영 완료" in log["log"] for log in res["logs"])
    assert not any(log["level"] == "warn" for log in res["logs"])


# ══════════════════════════════════════════════════════════════════════════════
# 저장 후 재조회 persist 확인 — 팬텀 저장 검출 vs 확인 불가 보류
# ══════════════════════════════════════════════════════════════════════════════
class _FakeSavePage:
    """save_doc 재조회 검증용 — 마스터 rowcount + F7 직전 팝업 수를 흉내낸다(그 외 무해 반환).

    `POPUP_COUNT_JS` = F7 직전 열린 k-window 수(잔존 팝업은 F7 을 삼켜 팬텀 저장을 만든다) —
    국내 save 게이트 역이식(2026-08-07)에 맞춰 실물 시맨틱을 들고 있다.
    """

    def __init__(self, rowcount: int, *, popups: int = 0) -> None:
        self._rowcount = rowcount
        self._popups = popups
        self.lookup_clicks = 0

    async def wait_for_timeout(self, ms):  # noqa: ANN001
        return None

    async def screenshot(self, **kw):  # noqa: ANN001
        raise RuntimeError("no browser")  # emit_shot 은 실패를 삼킨다(프레임 생략).

    async def evaluate(self, jsstr, arg=None):  # noqa: ANN001
        if jsstr is js_lib.ROWCOUNT_BY_INDEX_JS:
            return self._rowcount
        if jsstr is js_lib.POPUP_COUNT_JS:
            return self._popups
        if "el.click()" in str(jsstr):  # js_click(조회 F2)
            self.lookup_clicks += 1
            return True
        return True


async def _run_save(
    monkeypatch, rowcount: int, *, popups: int = 0, state_extra: dict | None = None,
    save_calls: list | None = None,
) -> dict:
    from app.agents.card_collect import steps as card_steps
    from app.agents.trip_overseas.nodes.save import make_save_doc_node

    async def _fake_save(page, confirm=True):  # noqa: ANN001
        if save_calls is not None:
            save_calls.append(True)
        return {"ok": True, "modals_seen": []}

    monkeypatch.setattr(card_steps, "save_document", _fake_save)
    node = make_save_doc_node()
    events: asyncio.Queue = asyncio.Queue()
    state = {
        "events": events,
        "page": _FakeSavePage(rowcount, popups=popups),
        "filled": 2,
        **(state_extra or {}),
    }
    out = await node(state)
    logs = []
    while not events.empty():
        ev = events.get_nowait()
        if "log" in ev:
            logs.append(ev)
    return {"out": out, "logs": logs}


@pytest.mark.asyncio
async def test_save_confirms_document_persisted(monkeypatch):
    res = await _run_save(monkeypatch, rowcount=1)
    assert "error" not in res["out"]
    assert any("문서 지속" in log["log"] for log in res["logs"])


@pytest.mark.asyncio
async def test_save_aborts_when_popup_left_open(monkeypatch):
    """F7 직전에 팝업이 남아 있으면 저장을 **시도조차 하지 않는다**(국내 게이트 역이식, 팬텀 저장 차단)."""
    called: list = []
    res = await _run_save(monkeypatch, rowcount=1, popups=1, save_calls=called)
    assert called == []  # 저장 게이트를 건드리지 않았다.
    assert "열린 팝업" in res["out"]["error"] and res["out"]["retry_save"] is False


@pytest.mark.asyncio
async def test_save_detects_phantom_save(monkeypatch):
    """재조회 확정 0건 = 서버에 문서가 없음 → 팬텀 저장으로 하드 실패."""
    res = await _run_save(monkeypatch, rowcount=0)
    assert "팬텀 저장" in res["out"]["error"]


@pytest.mark.asyncio
async def test_save_holds_verdict_when_rowcount_unreadable(monkeypatch):
    """rowcount 를 못 읽음(-1) = 확인 불가 → 정상 저장을 뒤집지 않고 warn 으로만 남긴다."""
    res = await _run_save(monkeypatch, rowcount=-1)
    assert "error" not in res["out"]
    assert any(log["level"] == "warn" and "보류" in log["log"] for log in res["logs"])


@pytest.mark.asyncio
async def test_save_result_flags_unverified_values(monkeypatch):
    """채움 단계에서 확인 불가가 남았으면 결과 문구를 '완료'로 단정하지 않는다."""
    res = await _run_save(monkeypatch, rowcount=1, state_extra={"unverified": ["1행 적요"]})
    assert "확인하지 못했습니다" in res["out"]["result"]
