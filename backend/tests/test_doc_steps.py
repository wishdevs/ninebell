"""결의서입력 공용 스텝(app.agents.common.doc_steps) 확인 계약 — 브라우저 없이.

고정하는 계약(§10 "값 선택은 선택 → 확인 → 다음"):
  1. 회계일(ACTG_DT) — 세터가 돌려준 표시값만 믿지 않고 **셀을 다시 읽어** 확인한다.
     반영 성공 → ok / 되돌려짐(값 다름) → 하드 실패 / 그리드를 못 읽음 → warn 후 진행.
  2. 증빙유형 '적용' 후 **팝업이 닫혔는지** 확인한다 — 닫히지 않았으면 다음 행이 그 스테일
     팝업을 잡아 엉뚱한 행에 쓰는 사고로 이어지므로, 성공을 단정하지 않고 warn 을 얹는다.
  3. 증빙 팝업이 **이미 열린 상태**에서 시작하면 '새로 열림'을 확인할 수 없으므로 warn.

페이지 페이크는 실물 시맨틱을 지킨다 — 에디터를 띄워야 돋보기 rect 가 나오고, 돋보기를
클릭해야 팝업이 열리며, 팝업이 열려 있어야 코드 선택이 되고, '적용'을 눌러야 셀이 반영되고
팝업이 닫힌다. (임의로 통과시키는 스텁이면 이 확인들이 무의미해진다.)
"""

from __future__ import annotations

import pytest

from app.agents.common import doc_steps
from nbkit.omnisol import js_lib

pytestmark = pytest.mark.asyncio

MAGNIFIER = {"x": 700, "y": 320}
APPLY_BOX = {"x": 900, "y": 640}


# ══════════════════════════════════════════════════════════════════════════════
# 회계일(ACTG_DT) — 세터 스냅샷 + 독립 readback
# ══════════════════════════════════════════════════════════════════════════════
class _AcctDatePage:
    """마스터 그리드 0행 회계일 셀 모사.

    set: SET_ACCT_DATE_JS 가 setValue 와 **같은 콜 안에서** 표시값을 돌려준다(실물과 동일 —
    그래서 나중에 되돌아가는 값을 이 반환만으론 잡지 못한다).
    readback: GRID_CELL_VALUE_JS 는 ``committed`` 를 읽는다. ``committed`` 를 세팅값과 다르게
    두면 "그리드 커밋 검증이 값을 되돌린" 조용한 실패를 그대로 재현한다.
    날짜 셀 getValue 는 Date 라 raw 는 'Tue Jul 07 2026 …' 이고 compact 만 'YYYYMMDD' 다.
    """

    def __init__(self, *, committed: str | None = "20260707", readable: bool = True) -> None:
        self.committed = committed
        self.readable = readable
        self.display = ""

    async def evaluate(self, js_src, arg=None):
        if js_src is js_lib.SET_ACCT_DATE_JS:
            self.display = f"{arg[0:4]}-{arg[4:6]}-{arg[6:8]}"
            return {"ok": True, "display": self.display}
        if js_src is js_lib.GRID_CELL_VALUE_JS:
            if not self.readable:
                return {"ok": False, "reason": "Cannot read properties of undefined"}
            c = self.committed or ""
            return {
                "ok": True,
                "row": 0,
                "rows": 1,
                "raw": {"ACTG_DT": "Tue Jul 07 2026 00:00:00 GMT+0900"},
                "compact": {"ACTG_DT": c},
                "display": {"ACTG_DT": f"{c[0:4]}-{c[4:6]}-{c[6:8]}" if c else ""},
            }
        raise AssertionError(f"예상치 못한 evaluate: {str(js_src)[:60]}")

    async def wait_for_timeout(self, ms):
        return None


async def test_acct_date_ok_when_cell_readback_matches():
    page = _AcctDatePage(committed="20260707")
    r = await doc_steps.set_acct_date(page, "20260707", "2026-07-07")
    assert r["ok"] is True and r["verified"] is True
    assert r["display"] == "2026-07-07"
    assert "warn" not in r


async def test_acct_date_hard_fails_when_cell_reverted_after_set():
    """세터는 성공(표시값도 일치)했지만 그리드가 값을 되돌린 경우 — 저장될 데이터라 하드 실패."""
    page = _AcctDatePage(committed="20260731")  # 마감월 규칙 등으로 되돌아간 값.
    r = await doc_steps.set_acct_date(page, "20260707", "2026-07-07")
    assert r["ok"] is False
    assert "회계일" in r["reason"] and "20260731" in r["reason"]


async def test_acct_date_warns_when_cell_unreadable():
    """리더가 그리드를 못 읽으면 '값이 다름'이 아니라 확인 불가 — 플로우는 warn 후 진행."""
    page = _AcctDatePage(readable=False)
    r = await doc_steps.set_acct_date(page, "20260707", "2026-07-07")
    assert r["ok"] is True and r["verified"] is False
    assert "확인 불가" in r["warn"]


async def test_acct_date_setter_failure_still_short_circuits():
    """세터 자체가 실패하면 readback 까지 가지 않는다(기존 계약 보존)."""

    class _Broken(_AcctDatePage):
        async def evaluate(self, js_src, arg=None):
            if js_src is js_lib.SET_ACCT_DATE_JS:
                return {"ok": False, "reason": "결의서(마스터) 행 없음"}
            raise AssertionError("세터 실패 후에는 readback 을 하지 않아야 한다")

    r = await doc_steps.set_acct_date(_Broken(), "20260707", "2026-07-07")
    assert r["ok"] is False and "행 없음" in r["reason"]


# ══════════════════════════════════════════════════════════════════════════════
# 증빙유형 팝업 — 열기(스테일 감지) / 적용 후 닫힘 확인
# ══════════════════════════════════════════════════════════════════════════════
class _EvdnPage:
    """증빙유형 팝업 실물 시맨틱: 에디터 → 돋보기 rect → 클릭으로 열림 → 선택 → 적용.

    sticky_popup=True 는 '적용'을 눌러 셀은 반영됐는데 **팝업이 안 닫히는** 실패를 재현한다
    (다음 행이 이 잔여 팝업을 새 팝업으로 오독하는 사고의 원인 상태).
    """

    def __init__(self, *, popup_open: bool = False, sticky_popup: bool = False) -> None:
        self.popup_open = popup_open
        self.sticky_popup = sticky_popup
        self.editor_shown = False
        self.cell = ""
        self.selected = ""
        self.clicks: list[tuple[int, int]] = []
        self.rows = 1

    async def evaluate(self, js_src, arg=None):
        if js_src is js_lib.EVDN_POPUP_OPEN_JS:
            return self.popup_open
        if js_src is js_lib.OPEN_EVDN_EDITOR_JS:
            self.editor_shown = True
            return {"ok": True, "idx": self.rows - 1, "rows": self.rows}
        if js_src is js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS:
            return dict(MAGNIFIER) if self.editor_shown else None
        if js_src is js_lib.EVDN_SELECT_BY_CODE_JS:
            if not self.popup_open:
                return {"ok": False, "reason": "no-dialog"}
            self.selected = {"01": "법인카드", "10": "규정에의한 비용정산"}[arg]
            return {"ok": True, "code": arg, "name": self.selected}
        if js_src is js_lib.EVDN_APPLY_BOX_JS:
            return dict(APPLY_BOX) if self.popup_open else None
        if js_src is js_lib.DETAIL_EVDN_CELL_JS:
            return self.cell
        if js_src is js_lib.PICKER_CLOSE_JS:
            # 실패 정리(_fail_close) 닫기 — sticky_popup 은 닫기도 안 듣는 팝업(정리 실패 재현).
            if self.popup_open and not self.sticky_popup:
                self.popup_open = False
                return True
            return False
        raise AssertionError(f"예상치 못한 evaluate: {str(js_src)[:60]}")

    async def wait_for_timeout(self, ms):
        return None

    # 좌표 클릭(실물 mouse_click 대체) — 돋보기는 팝업을 열고, '적용'은 셀에 반영·팝업 닫기.
    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))
        if (x, y) == (MAGNIFIER["x"], MAGNIFIER["y"]):
            self.popup_open = True
        elif (x, y) == (APPLY_BOX["x"], APPLY_BOX["y"]):
            self.cell = self.selected
            if not self.sticky_popup:
                self.popup_open = False


@pytest.fixture(autouse=True)
def _wire_page_interactions(monkeypatch):
    """mouse_click → 페이지 페이크의 click, 공지 팝업 정리는 no-op(이 테스트의 관심사 아님)."""

    async def _mouse_click(page, x, y, **kw):
        await page.click(x, y)

    async def _dismiss(page, **kw):
        return None

    monkeypatch.setattr(doc_steps, "mouse_click", _mouse_click)
    monkeypatch.setattr(doc_steps, "dismiss_notice_popup", _dismiss)


async def test_open_evdn_editor_ok_without_warn_when_no_stale_popup():
    page = _EvdnPage()
    r = await doc_steps.open_evdn_editor(page)
    assert r["ok"] is True and "warn" not in r
    assert r["shown"] == {"ok": True, "idx": 0, "rows": 1}
    assert page.clicks == [(MAGNIFIER["x"], MAGNIFIER["y"])]  # 돋보기 실클릭 1회.


async def test_open_evdn_editor_warns_when_popup_already_open():
    """이전 행의 잔여 팝업이 떠 있으면 '새로 열림'을 확인할 수 없다 — 하드 실패 대신 warn."""
    page = _EvdnPage(popup_open=True)
    r = await doc_steps.open_evdn_editor(page)
    assert r["ok"] is True
    assert "스테일" in r["warn"]


async def test_select_evdn_ok_and_popup_closed():
    page = _EvdnPage(popup_open=True)
    r = await doc_steps.select_evdn_code(page, "01")
    assert r["ok"] is True and r["name"] == "법인카드" and r["code"] == "01"
    assert "warn" not in r
    assert page.popup_open is False and page.cell == "법인카드"


async def test_select_evdn_warns_when_popup_stays_open_after_apply():
    """셀 반영은 확인됐으니 이 문서 데이터는 맞다 → 하드 실패가 아니라 warn 후 진행."""
    page = _EvdnPage(popup_open=True, sticky_popup=True)
    r = await doc_steps.select_evdn_code(page, "01")
    assert r["ok"] is True and r["name"] == "법인카드"
    assert "증빙유형 팝업 닫힘" in r["warn"]
    assert page.cell == "법인카드"  # 반영 자체는 성공.


async def test_open_evdn_editor_rect_wait_is_realtime_not_nominal():
    """돋보기 rect 관찰 상한은 **실시간**이다 — wait_for_timeout 이 delay_scale 로 축소돼도
    (페이크는 극단인 no-op) 관찰창이 명목 카운터(회당 100ms 가정, 시도당 10폴)로 붕괴하지
    않는다. 종전 'waited += 100' 카운터는 3회 시도 합계 30폴에서 소진돼 그보다 늦게 준비되는
    rect 를 영영 못 봤다(2026-08-07 시간축 규율 교정 회귀)."""

    class _SlowRect(_EvdnPage):
        def __init__(self) -> None:
            super().__init__()
            self.rect_polls = 0

        async def evaluate(self, js_src, arg=None):
            if js_src is js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS:
                self.rect_polls += 1
                if self.rect_polls < 40:  # 종전 명목 상한(3시도 × 10폴 = 30)보다 늦은 준비.
                    return None
            return await super().evaluate(js_src, arg)

    page = _SlowRect()
    r = await doc_steps.open_evdn_editor(page)
    assert r["ok"] is True, f"실시간 상한이면 40번째 폴에서 rect 를 잡아야 한다: {r}"
    assert page.rect_polls >= 40


async def test_open_evdn_editor_popup_open_poll_is_realtime():
    """⚠ 핀(2026-08-07 리뷰): 돋보기 클릭 후 '팝업 열림' 관찰도 실시간이다 — wait_for_timeout
    명목 폴로 되돌리면 대기가 기록돼 이 단언이 잡는다(delay_scale 0.15 에서 6s→0.9s 붕괴 회귀)."""

    class _LateOpen(_EvdnPage):
        def __init__(self) -> None:
            super().__init__()
            self.open_polls = 0
            self.waits: list[int] = []

        async def click(self, x, y):
            self.clicks.append((x, y))  # 돋보기를 눌러도 즉시 열리지 않는다(늦은 렌더).

        async def evaluate(self, js_src, arg=None):
            if js_src is js_lib.EVDN_POPUP_OPEN_JS:
                self.open_polls += 1
                clicked = (MAGNIFIER["x"], MAGNIFIER["y"]) in self.clicks
                if clicked and self.open_polls >= 5:
                    self.popup_open = True
                return self.popup_open
            return await super().evaluate(js_src, arg)

        async def wait_for_timeout(self, ms):
            self.waits.append(ms)

    page = _LateOpen()
    r = await doc_steps.open_evdn_editor(page)
    assert r["ok"] is True and "warn" not in r
    assert page.open_polls >= 5  # 소진 전 폴링 유지(늦은 열림을 미열림으로 오판하지 않음).
    # 열림 관찰 루프는 실시간 누산(DEFAULT_SLEEP)이라 page 대기를 남기지 않는다 — 허용되는
    # page 대기는 rect 준비 루프의 폴 간격 100ms 뿐(상한은 monotonic 실시간 — 별도 테스트가 핀).
    # 명목 폴(예: 300ms wait_for_timeout 누산)로 되돌리면 이 단언이 잡는다.
    assert all(w == 100 for w in page.waits), page.waits


async def test_select_evdn_cell_reflect_poll_is_realtime():
    """⚠ 핀(2026-08-07 리뷰): '적용' 후 셀 반영 관찰도 실시간이다 — 명목 폴 회귀 시 대기가
    기록돼 잡힌다(반영이 늦는 세션을 '적용 실패' 하드 실패로 오판하던 창 붕괴 방지)."""

    class _LateReflect(_EvdnPage):
        def __init__(self) -> None:
            super().__init__(popup_open=True)
            self.cell_polls = 0
            self.waits: list[int] = []
            self._applied = False

        async def click(self, x, y):
            self.clicks.append((x, y))
            if (x, y) == (APPLY_BOX["x"], APPLY_BOX["y"]):
                self._applied = True
                self.popup_open = False  # 팝업은 닫혔는데 셀 반영이 늦는 세션.

        async def evaluate(self, js_src, arg=None):
            if js_src is js_lib.DETAIL_EVDN_CELL_JS:
                self.cell_polls += 1
                if self._applied and self.cell_polls >= 5:
                    self.cell = self.selected
                return self.cell
            return await super().evaluate(js_src, arg)

        async def wait_for_timeout(self, ms):
            self.waits.append(ms)

    page = _LateReflect()
    r = await doc_steps.select_evdn_code(page, "01")
    assert r["ok"] is True and r["name"] == "법인카드"
    assert page.cell_polls >= 5
    # 행 자동선택·셀 반영 관찰 루프는 실시간 누산(DEFAULT_SLEEP)이라 page 대기를 남기지 않는다 —
    # 허용되는 page 대기는 선택→적용 사이 의도적 정착 500ms 단발뿐(정상경로, 스케일 대상).
    # 관찰 루프를 명목 폴(wait_for_timeout 누산)로 되돌리면 대기가 늘어 이 단언이 잡는다.
    assert page.waits == [500], page.waits


class _NoReflect(_EvdnPage):
    """'적용'을 눌러도 셀이 반영되지 않는 페이지 — 적용 실패 경로 재현."""

    async def click(self, x, y):
        self.clicks.append((x, y))  # 적용을 눌러도 셀이 그대로.


async def test_select_evdn_hard_fails_when_cell_never_reflects():
    """'적용'이 셀에 안 붙으면 증빙유형이 미정인 채 진행되므로 하드 실패(기존 계약 보존).

    2026-08-07 감사: 실패 반환 직전 열린 증빙 팝업을 닫는다(_fail_close) — 안 닫으면 다음 행의
    open_evdn_editor 가 스테일 팝업을 잡아 그 '적용'이 엉뚱한 행 셀에 쓰인다(2026-07-02 동형).
    """
    page = _NoReflect(popup_open=True)
    r = await doc_steps.select_evdn_code(page, "01")
    assert r["ok"] is False and "적용" in r["reason"]
    assert page.popup_open is False  # 실패 정리로 팝업이 닫혔다.
    assert "미닫힘" not in r["reason"]


async def test_select_evdn_fail_appends_warning_when_popup_wont_close():
    """실패 정리 닫기가 안 듣는 팝업 — 원래 실패 사유를 덮지 않고 미닫힘을 병기한다."""
    page = _NoReflect(popup_open=True, sticky_popup=True)
    r = await doc_steps.select_evdn_code(page, "01")
    assert r["ok"] is False
    assert "적용" in r["reason"] and "미닫힘" in r["reason"]
    assert page.popup_open is True  # 실제로 안 닫혔음을 사실대로 반영.


# ══════════════════════════════════════════════════════════════════════════════
# add_next_row — 행수 관찰은 실시간(delay_scale 축소 비대상)
# ══════════════════════════════════════════════════════════════════════════════
class _AddRowPage:
    """추가(F3) 후 디테일 rowCount 폴링 페이크 — js_click(문자열 JS) + rowcount 시퀀스."""

    def __init__(self, rowcounts: list[int]) -> None:
        self._seq = list(rowcounts)
        self.waits: list[int] = []

    async def evaluate(self, js_src, arg=None):
        if isinstance(js_src, str) and js_src.startswith("(sel) =>"):
            return True  # BTN_ADD js_click.
        if js_src is js_lib.DETAIL_ROWCOUNT_JS:
            return self._seq.pop(0) if len(self._seq) > 1 else self._seq[0]
        raise AssertionError(f"예상치 못한 evaluate: {str(js_src)[:60]}")

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


async def test_add_next_row_observation_avoids_scaled_waits():
    """행수 관찰 대기는 실시간 sleep 이다 — wait_for_timeout(delay_scale 축소 대상)을 쓰면
    card 0.15 배율에서 상한 ~10s 가 실 1.5s 로 붕괴한다(2026-08-07 시간축 규율 회귀)."""
    page = _AddRowPage([1, 1, 2])
    r = await doc_steps.add_next_row(page, 2)
    assert r == {"ok": True, "rows": 2}
    assert page.waits == []  # 관찰 루프가 wait_for_timeout 을 쓰지 않는다.


async def test_add_next_row_fails_with_last_rowcount_after_cap():
    """미생성 = 상한 소진 후 구조화 실패(마지막 행수 동봉) — 기존 실패 계약 보존."""
    page = _AddRowPage([1])
    r = await doc_steps.add_next_row(page, 2)
    assert r["ok"] is False and r["rows"] == 1 and "행수 미달" in r["reason"]


# ── 회계일 warn 의 **호출부 노출**(영역 경계 항목, 2026-07-27 확산 후 마감) ────────
# doc_steps.set_acct_date 는 확인 불가 시 {"ok": True, "warn": ..., "verified": False} 를
# 돌려주는데, 그걸 로그로 올리는 책임은 각 에이전트의 fill 노드에 있다. 네 에이전트가 같은
# 구조를 복제해 쓰므로 여기서 한 번에 계약을 고정한다(한 곳만 고쳐지고 나머지가 새는 것 방지).
import asyncio  # noqa: E402

import pytest  # noqa: E402

_FILL_NODES = [
    ("trip_domestic", "app.agents.trip_domestic.nodes.fill"),
    ("trip_overseas", "app.agents.trip_overseas.nodes.fill"),
    ("gyeongjo_grant", "app.agents.gyeongjo_grant.nodes.fill"),
    ("hakjagum_grant", "app.agents.hakjagum_grant.nodes.fill"),
]


def _drain_logs(q: asyncio.Queue) -> list[str]:
    out = []
    while not q.empty():
        f = q.get_nowait()
        if "log" in f:
            out.append((f.get("level"), f["log"]))
    return out


@pytest.mark.parametrize("pkg,mod_path", _FILL_NODES)
async def test_acct_date_node_surfaces_unverified_warn(pkg, mod_path, monkeypatch):
    import importlib

    mod = importlib.import_module(mod_path)

    async def _unverified(page, compact, dashed):
        return {"ok": True, "warn": "확인 불가(그리드 미접근)", "verified": False}

    monkeypatch.setattr(mod.doc_steps, "set_acct_date", _unverified)
    q: asyncio.Queue = asyncio.Queue()
    node = mod.make_set_acct_date_node()
    out = await node({"events": q, "page": object(), "acct_date_compact": "20260727"})
    assert "error" not in out
    logs = _drain_logs(q)
    assert any(lvl == "warn" and "회계일" in msg for lvl, msg in logs), f"{pkg}: warn 미노출"
    assert any("반영 미확인" in msg for _lvl, msg in logs), f"{pkg}: 미확인 표기 없음"


@pytest.mark.parametrize("pkg,mod_path", _FILL_NODES)
async def test_acct_date_node_stays_quiet_when_verified(pkg, mod_path, monkeypatch):
    import importlib

    mod = importlib.import_module(mod_path)

    async def _verified(page, compact, dashed):
        return {"ok": True, "verified": True}

    monkeypatch.setattr(mod.doc_steps, "set_acct_date", _verified)
    q: asyncio.Queue = asyncio.Queue()
    out = await mod.make_set_acct_date_node()({"events": q, "page": object(), "acct_date_compact": "20260727"})
    assert "error" not in out
    logs = _drain_logs(q)
    assert not any(lvl == "warn" for lvl, _msg in logs), f"{pkg}: 정상 경로에 warn 인플레"
    assert not any("반영 미확인" in msg for _lvl, msg in logs)
