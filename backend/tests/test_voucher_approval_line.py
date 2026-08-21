"""D5-1 결재라인 교차 지정 — 단위 테스트(페이지 fake 주입).

실측 근거(2026-08-21 approval_line_probe_4b): 전표 헤더 '결재' 라벨 → 모달 → 캔버스 체크 →
툴바 '결재' → 저장 → 전표 헤더에 대상 이름 리프 신규 등장. 여기서는 그 시퀀스를 fake child
Page 로 재현해 판정 로직(성공/검증 실패/스킵)을 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.voucher_receivable import steps
from nbkit.patterns import approval_line_flow as flow


def run(coro):
    return asyncio.run(coro)


class FakeChild:
    """evaluate 를 JS 상수별 응답 큐로 흉내낸다. mouse.click 은 좌표를 기록만 한다."""

    def __init__(
        self,
        leaf_seq: list[list[dict]],
        canvases: list[dict],
        canvas_seq: list[list[dict]] | None = None,
    ):
        # EAP_LEAF_DUMP_JS / EAP_CANVAS_RECTS_JS 호출마다 순서대로 반환(마지막 값은 반복).
        self._leaf_seq = list(leaf_seq)
        self._canvas_seq = list(canvas_seq) if canvas_seq is not None else [canvases]
        self.clicks: list[tuple[float, float]] = []
        self.mouse = self
        self.keyboard = self

    async def evaluate(self, script: str):
        if script == flow.EAP_LEAF_DUMP_JS:
            if len(self._leaf_seq) > 1:
                return self._leaf_seq.pop(0)
            return self._leaf_seq[0]
        if script == flow.EAP_CANVAS_RECTS_JS:
            if len(self._canvas_seq) > 1:
                return self._canvas_seq.pop(0)
            return self._canvas_seq[0]
        if script == flow.EAP_SMALL_DIALOG_JS:
            return []
        raise AssertionError(f"unexpected script: {script[:40]}")

    async def click(self, x, y):  # mouse.click
        self.clicks.append((x, y))

    async def press(self, key):  # keyboard.press
        pass


# 실측 좌표·크기를 본뜬 리프 셋 — 문서 헤더(모달 전), 모달 열림, 저장 후.
# '결재' 라벨은 세로 셀(w40×h110) — 형태(h≥60) 판별의 근거. 툴바 '결재'는 h24.
NAVBAR_ONLY_LEAVES = [
    {"text": "상신", "x": 922, "y": 30, "w": 60, "h": 26},  # 본문 렌더 전(배치 지연 재현)
]
DOC_LEAVES = [
    {"text": "상신", "x": 922, "y": 30, "w": 60, "h": 26},
    {"text": "결재", "x": 770, "y": 262, "w": 40, "h": 110},  # 전표 헤더 라벨(세로 셀)
    {"text": "이트라이브2", "x": 900, "y": 300, "w": 80, "h": 20},  # 기안자/결재란 본인
]
MODAL_LEAVES = DOC_LEAVES + [
    {"text": "결재라인 지정", "x": 71, "y": 65, "w": 120, "h": 24},
    {"text": "결재", "x": 772, "y": 117, "w": 40, "h": 24},  # 상단 툴바(y<150, h<60)
    {"text": "저장", "x": 491, "y": 706, "w": 60, "h": 30},
]
SAVED_LEAVES = [
    {"text": "상신", "x": 922, "y": 30, "w": 60, "h": 26},
    {"text": "결재", "x": 770, "y": 262, "w": 40, "h": 110},
    {"text": "이트라이브2", "x": 900, "y": 300, "w": 80, "h": 20},
    {"text": "이트라이브", "x": 960, "y": 300, "w": 80, "h": 20},  # 추가된 결재자(신규 리프)
]
# 모달 캔버스 2개(실측) — 인원표(상단)·결재선 그리드(하단). 선택 규칙 = 넓은 것 중 최상단.
CANVASES = [
    {"x": 344, "y": 150, "w": 617, "h": 230},  # 인원표
    {"x": 344, "y": 423, "w": 617, "h": 218},  # 결재선 그리드
]


def test_cross_map_is_symmetric_pair():
    assert steps.APPROVAL_LINE_CROSS == {"이트라이브": "이트라이브2", "이트라이브2": "이트라이브"}
    for target in steps.APPROVAL_LINE_CROSS.values():
        assert target in steps.APPROVAL_LINE_MEMBER_ROW


def test_ensure_skips_non_target_accounts():
    async def boom(*_a, **_k):  # 지정 로직이 호출되면 실패
        raise AssertionError("designate_approval_line must not be called")

    orig = flow.designate_approval_line
    flow.designate_approval_line = boom
    try:
        res = run(steps.ensure_cross_approval_line(object(), "admin"))
        assert res == {"ok": True, "skipped": True}
        res = run(steps.ensure_cross_approval_line(object(), None))
        assert res == {"ok": True, "skipped": True}
    finally:
        flow.designate_approval_line = orig


def test_designate_happy_path_adds_target_leaf():
    child = FakeChild(
        leaf_seq=[
            DOC_LEAVES,  # 모달 상태 확인 + 라벨 탐색(locator 없음 → 폴백)
            MODAL_LEAVES,  # 모달 오픈 폴링
            MODAL_LEAVES,  # count_before 기준선
            MODAL_LEAVES,  # 툴바 탐색
            MODAL_LEAVES,  # 저장 버튼 탐색
            SAVED_LEAVES,  # 다이얼로그 루프의 모달 닫힘 판정
            SAVED_LEAVES,  # 최종 검증 덤프
        ],
        canvases=CANVASES,
    )
    res = run(flow.designate_approval_line(child, "이트라이브", 3))
    assert res["ok"] is True
    assert res["count_before"] == 0 and res["count_after"] == 1
    # 클릭 순서: 라벨 → 캔버스 체크박스 → 툴바 결재 → 저장 (4회)
    assert len(child.clicks) == 4
    cb_x, cb_y = child.clicks[1]
    assert cb_x == CANVASES[0]["x"] + 10
    # 행 3 체크박스 y = y + 27.5 + 3*29.2 + 14.6
    assert abs(cb_y - (150 + 27.5 + 3 * 29.2 + 29.2 / 2)) < 0.01


def test_designate_fails_when_target_leaf_missing_after_save():
    # 저장 후에도 대상 리프가 안 생기면(오지정/행 밀림) ok=False — 상신 금지 근거.
    child = FakeChild(
        leaf_seq=[
            DOC_LEAVES,
            MODAL_LEAVES,
            MODAL_LEAVES,
            MODAL_LEAVES,
            MODAL_LEAVES,
            DOC_LEAVES,  # 모달은 닫혔지만
            DOC_LEAVES,  # '이트라이브' 리프 없음
        ],
        canvases=CANVASES,
    )
    res = run(flow.designate_approval_line(child, "이트라이브", 3))
    assert res["ok"] is False
    assert "상신 금지" in res["reason"]


def test_designate_fails_without_label(monkeypatch):
    monkeypatch.setattr(flow, "_LABEL_CAP_S", 0.6)  # 폴링 상한만 줄여 테스트 시간 절약
    child = FakeChild(leaf_seq=[NAVBAR_ONLY_LEAVES], canvases=CANVASES)
    res = run(flow.designate_approval_line(child, "이트라이브", 3))
    assert res["ok"] is False
    assert "'결재' 라벨" in res["reason"]


def test_designate_waits_for_slow_canvas_init():
    # 모달 제목이 떠도 RealGrid 캔버스 초기화가 늦는다(라이브 배치 실패 2026-08-21 재현) —
    # 캔버스 폴링으로 잡는지 검증.
    child = FakeChild(
        leaf_seq=[
            DOC_LEAVES,
            MODAL_LEAVES,
            MODAL_LEAVES,
            MODAL_LEAVES,
            MODAL_LEAVES,
            SAVED_LEAVES,
            SAVED_LEAVES,
        ],
        canvases=CANVASES,
        canvas_seq=[[], [], CANVASES],  # 두 번은 빈 목록 → 세 번째에 출현
    )
    res = run(flow.designate_approval_line(child, "이트라이브", 3))
    assert res["ok"] is True
    cb_x, cb_y = child.clicks[1]
    assert cb_x == CANVASES[0]["x"] + 10  # 최상단(인원표) 캔버스를 골랐는가


def test_designate_waits_for_slow_body_render():
    # 배치(다건) EAP 문서 — 네비바만 뜬 첫 덤프 후 본문이 늦게 렌더돼도 폴링으로 라벨을 잡는다
    # (라이브 45건 실패 2026-08-21 재현 → 수정 검증).
    child = FakeChild(
        leaf_seq=[
            NAVBAR_ONLY_LEAVES,  # 모달 상태 확인(본문 미렌더, locator 없음 → 폴백)
            NAVBAR_ONLY_LEAVES,  # 폴백 폴링 1회차 — 아직 미렌더
            DOC_LEAVES,  # 폴백 폴링 2회차 — 본문 렌더 완료, 라벨 발견
            MODAL_LEAVES,  # 모달 오픈 폴링
            MODAL_LEAVES,  # count_before 기준선
            MODAL_LEAVES,  # 툴바 탐색
            MODAL_LEAVES,  # 저장 버튼 탐색
            SAVED_LEAVES,  # 다이얼로그 루프의 모달 닫힘 판정
            SAVED_LEAVES,  # 최종 검증 덤프
        ],
        canvases=CANVASES,
    )
    res = run(flow.designate_approval_line(child, "이트라이브", 3))
    assert res["ok"] is True
    assert len(child.clicks) == 4


def test_exact_match_not_polluted_by_longer_name():
    # '이트라이브2' 리프만 늘어난 경우 '이트라이브' 검증이 통과하면 안 된다(부분일치 금지).
    leaves = DOC_LEAVES + [{"text": "이트라이브2", "x": 960, "y": 300}]
    assert flow._count_exact(leaves, "이트라이브") == 0
    assert flow._count_exact(leaves, "이트라이브2") == 2


@pytest.mark.parametrize("userid,target", [("이트라이브", "이트라이브2"), ("이트라이브2", "이트라이브")])
def test_ensure_delegates_with_cross_target(userid, target):
    seen: dict = {}

    async def fake(child, t, row, **_k):
        seen["target"], seen["row"] = t, row
        return {"ok": True, "target": t}

    orig = flow.designate_approval_line
    flow.designate_approval_line = fake
    try:
        res = run(steps.ensure_cross_approval_line(object(), userid))
    finally:
        flow.designate_approval_line = orig
    assert res["ok"] is True
    assert seen["target"] == target
    assert seen["row"] == steps.APPROVAL_LINE_MEMBER_ROW[target]
