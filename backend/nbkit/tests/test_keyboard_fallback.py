"""방법 B(키보드 폴백) 정합 검증 — FakePage 로 라이브 브라우저 없이.

고정 dwell(1.5s) 시절의 결함: 디테일 로드가 dwell 을 넘으면 **직전 행 디테일이 현재 행에
붙는 무증상 오염**이 났다. 조건 폴링(식별 필드 조인 / rowcount 변화+안정) + jiggle 재앵커링
+ 최종 unverified 마킹이 그 오염을 막는지 검증한다(test_provider_offbyone.py 스타일).
"""

from __future__ import annotations

from nbkit.grid.strategies import CollectionStrategy, GridExtractor
from nbkit.omnisol import js_lib


def _masters(n: int) -> list[dict]:
    return [{"INVTRX_RSV_NO": f"A{i}"} for i in range(n)]


def _details(n: int) -> dict[int, list[dict]]:
    # 행 i 의 디테일 = i+1 개(행별 rowcount 가 달라 안정 판정 경로도 관측 가능).
    return {
        i: [{"INVTRX_RSV_NO": f"A{i}", "seq": j} for j in range(i + 1)] for i in range(n)
    }


class FakeMasterDetailPage:
    """마스터-디테일 그리드 + trusted 키보드 로드 시맨틱을 흉내내는 최소 Page 스텁.

    - 디테일 로드는 실클릭/ArrowDown 트리거 후 **rowcount 폴 ``detail_lag_polls`` 회** 뒤에
      반영된다(그 전까지는 직전 행 디테일이 그대로 남는 스테일 상태 — 실기기 동일).
    - ``stuck_rows`` 행은 로드 이벤트 자체가 유실된다(스테일 유지). jiggle(ArrowUp→ArrowDown)
      로 풀린다. ``unstickable=True`` 면 jiggle 로도 안 풀린다(최종 unverified 경로 검증용).
    """

    def __init__(
        self,
        masters: list[dict],
        details: dict[int, list[dict]],
        *,
        detail_lag_polls: int = 1,
        stuck_rows: set[int] | None = None,
        unstickable: bool = False,
        grid_rect: dict | None = None,
    ) -> None:
        self._masters = masters
        self._details = details
        self._lag = detail_lag_polls
        self._stuck = set(stuck_rows or ())
        self._unstickable = unstickable
        self._grid_rect = grid_rect
        self.current = 0  # 현재 마스터 행
        self.loaded_for: int | None = None  # 디테일이 현재 표시 중인 마스터 행(None=미로드)
        self._pending: tuple[int, int] | None = None  # (row, 남은 폴 수)
        self.clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.mouse = _Mouse(self)
        self.keyboard = _Keyboard(self)

    # ── 로드 시뮬레이션 ────────────────────────────────────────────────────────
    def _begin_load(self, row: int) -> None:
        if row in self._stuck:
            self._pending = None  # 로드 이벤트 유실 — 스테일 디테일 유지
            return
        self._pending = (row, self._lag)

    def _step(self) -> None:
        if self._pending is None:
            return
        row, remaining = self._pending
        if remaining <= 0:
            self.loaded_for = row
            self._pending = None
        else:
            self._pending = (row, remaining - 1)

    def _detail_rows(self) -> list[dict] | None:
        if self.loaded_for is None:
            return None
        return self._details[self.loaded_for]

    # ── Page 표면 ─────────────────────────────────────────────────────────────
    async def evaluate(self, script, arg=None):
        if script == js_lib.ROWCOUNT_BY_INDEX_JS:
            if arg == 0:
                return len(self._masters)
            self._step()  # 디테일 rowcount 폴 = 시간 경과
            rows = self._detail_rows()
            return -1 if rows is None else len(rows)
        if script == js_lib.GET_JSON_ROWS_JS:
            data = self._masters if arg["index"] == 0 else (self._detail_rows() or [])
            start, end = arg["start"], arg["end"]  # end 는 INCLUSIVE
            if end < start:
                return []
            return [dict(r) for r in data[start : end + 1]]
        if script == js_lib.SET_CURRENT_BY_INDEX_JS:
            self.current = arg["itemIndex"]  # ⚠ setCurrent 는 디테일 로드를 트리거하지 않는다
            return True
        if script == js_lib.GRID_RECT_BY_INDEX_JS:
            return self._grid_rect
        raise AssertionError(f"예상치 못한 스크립트 호출: {script[:40]}")

    async def wait_for_timeout(self, ms):
        return None


class _Mouse:
    def __init__(self, page: FakeMasterDetailPage) -> None:
        self._page = page

    async def click(self, x, y):
        self._page.clicks.append((x, y))
        self._page._begin_load(self._page.current)  # 첫 행 실클릭 → 행0 디테일 로드


class _Keyboard:
    def __init__(self, page: FakeMasterDetailPage) -> None:
        self._page = page

    async def press(self, key: str):
        p = self._page
        p.keys.append(key)
        if key == "ArrowUp":
            p.current = max(0, p.current - 1)
            p._begin_load(p.current)
        elif key == "ArrowDown":
            was_jiggle = len(p.keys) >= 2 and p.keys[-2] == "ArrowUp"
            p.current = min(len(p._masters) - 1, p.current + 1)
            if was_jiggle and not p._unstickable:
                p._stuck.discard(p.current)  # jiggle 재앵커링이 유실 로드를 되살린다
            p._begin_load(p.current)


async def _extract(page, **kw):
    ex = GridExtractor(page, master_index=0, detail_index=1)
    defaults = dict(
        master_count=3,
        detail_service_url=None,
        strategy=CollectionStrategy.KEYBOARD_FALLBACK,
        dwell_ms=200,
    )
    defaults.update(kw)
    return await ex.extract(**defaults)


# ── 조인 검증(식별 필드) ─────────────────────────────────────────────────────────


async def test_details_join_master_id_no_poisoning():
    page = FakeMasterDetailPage(_masters(3), _details(3), detail_lag_polls=2)
    out = await _extract(page)
    assert out["strategy"] == "keyboard_fallback"
    assert [d["no"] for d in out["details"]] == ["A0", "A1", "A2"]
    for i, d in enumerate(out["details"]):
        assert "unverified" not in d
        assert len(d["rows"]) == i + 1
        assert all(r["INVTRX_RSV_NO"] == f"A{i}" for r in d["rows"])  # 오염 없음


async def test_slow_detail_load_does_not_attach_previous_rows():
    # 로드 지연이 커도(폴 5회) 조인 확인 전에는 읽지 않는다 — 고정 dwell 오염의 회귀 방지.
    page = FakeMasterDetailPage(_masters(3), _details(3), detail_lag_polls=5)
    out = await _extract(page)
    for i, d in enumerate(out["details"]):
        assert "unverified" not in d
        assert all(r["INVTRX_RSV_NO"] == f"A{i}" for r in d["rows"])


# ── jiggle 재앵커링 ─────────────────────────────────────────────────────────────


async def test_jiggle_recovers_lost_detail_load():
    page = FakeMasterDetailPage(_masters(3), _details(3), detail_lag_polls=1, stuck_rows={1})
    out = await _extract(page, dwell_ms=40)  # 짧은 상한 → 1차 폴링 실패 후 jiggle 경로
    assert "ArrowUp" in page.keys  # jiggle(ArrowUp→ArrowDown) 이 실제로 실행됐다
    d1 = out["details"][1]
    assert "unverified" not in d1
    assert all(r["INVTRX_RSV_NO"] == "A1" for r in d1["rows"])
    # jiggle 이후 다음 행도 정상 진행.
    d2 = out["details"][2]
    assert "unverified" not in d2
    assert all(r["INVTRX_RSV_NO"] == "A2" for r in d2["rows"])


async def test_row0_stuck_jiggle_reanchor_keeps_alignment():
    # 최상단(행0) 미정착 케이스: jiggle 의 ArrowUp 은 행0 에서 무효(행 유지)이고 ArrowDown 만
    # 실동작해 커서가 행1 로 이탈한다. setCurrent 명시 재앵커가 없으면 이후 전 행 수집이
    # 한 행씩 밀린다(조인 가능 그리드는 전면 unverified, 조인 불가면 무증상 오염).
    # 그리드 행수(4) > master_count(3) 로 두어 끝행 클램프가 밀림을 가리지 못하게 한다.
    page = FakeMasterDetailPage(
        _masters(4), _details(4), detail_lag_polls=1, stuck_rows={0}
    )
    out = await _extract(page, dwell_ms=40)
    assert "ArrowUp" in page.keys  # jiggle 경로가 실제로 실행됐다
    d0 = out["details"][0]
    assert d0["unverified"] is True  # 행0 자체는 최상단이라 jiggle 로 복구 불가 — 명시 마킹
    assert d0["rows"] == []  # 다른 행(오염) 디테일은 절대 전달하지 않는다
    # 재앵커 덕에 이후 행들은 밀림 없이 정상 확정된다.
    for i in (1, 2):
        d = out["details"][i]
        assert "unverified" not in d
        assert len(d["rows"]) == i + 1
        assert all(r["INVTRX_RSV_NO"] == f"A{i}" for r in d["rows"])
    assert page.current == 2  # 커서가 마지막 수집 행(2)에 정렬 — 행3 으로 이탈하지 않았다


async def test_unrecoverable_row_marked_unverified_not_silent_empty():
    page = FakeMasterDetailPage(
        _masters(3), _details(3), detail_lag_polls=1, stuck_rows={1}, unstickable=True
    )
    out = await _extract(page, dwell_ms=40)
    d1 = out["details"][1]
    assert d1["unverified"] is True  # 명시 마킹 — 상위가 재시도/보정하도록
    assert d1["rows"] == []  # 직전 행(오염) 디테일은 절대 전달하지 않는다
    # 다른 행들은 정상 확정.
    assert "unverified" not in out["details"][0]
    assert "unverified" not in out["details"][2]


# ── 조인 불가 시 rowcount 변화+안정 폴백 ────────────────────────────────────────


async def test_rowcount_change_and_stability_when_no_id_field():
    masters = [{"c": i} for i in range(3)]
    details = {i: [{"v": j} for j in range(i + 1)] for i in range(3)}  # 행별 rowcount 상이
    page = FakeMasterDetailPage(masters, details, detail_lag_polls=1)
    out = await _extract(page, master_id_field=None)
    assert [d["no"] for d in out["details"]] == [0, 1, 2]
    assert [len(d["rows"]) for d in out["details"]] == [1, 2, 3]
    assert all("unverified" not in d for d in out["details"])


# ── 첫 행 실클릭 좌표 ──────────────────────────────────────────────────────────


async def test_first_row_xy_computed_from_master_grid_bbox():
    rect = {"x": 8, "y": 180, "width": 1200, "height": 400}
    page = FakeMasterDetailPage(_masters(2), _details(2), grid_rect=rect)
    await _extract(page, master_count=2)
    # x = left + min(width/2, 200) = 208, y = top + 헤더 34 + 행높이/2 16 = 230.
    assert page.clicks[0] == (208, 230)


async def test_first_row_xy_explicit_argument_respected():
    rect = {"x": 8, "y": 180, "width": 1200, "height": 400}
    page = FakeMasterDetailPage(_masters(2), _details(2), grid_rect=rect)
    await _extract(page, master_count=2, first_row_xy=(123, 222))
    assert page.clicks[0] == (123, 222)  # bbox 계산을 타지 않는다


async def test_first_row_xy_falls_back_to_legacy_without_bbox():
    page = FakeMasterDetailPage(_masters(2), _details(2), grid_rect=None)
    await _extract(page, master_count=2)
    assert page.clicks[0] == (400, 330)  # 1600×1000 시절 검증 좌표(최후 폴백)
