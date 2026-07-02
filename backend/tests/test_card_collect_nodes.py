"""P3-4 card_collect 노드/스텝 순수 로직 테스트(브라우저 불필요).

- steps.compute_period: 승인일 기간 D2 10일 규칙(10일 이전=전월 전체, 이후=당월 1일~오늘).
- nodes.recommend_note / _fmt_won: 적요 추천·금액 포맷 휴리스틱.
- collect_rows 빈 리스트 경로: 0건이면 안내 채팅 + filled=0(조용히 종료 안 함).
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.agents.card_collect import steps
from app.agents.card_collect.nodes import _fmt_won, make_collect_rows_node, recommend_note


# ── compute_period(D2 10일 규칙) ──────────────────────────────────────────────
def test_compute_period_before_cutoff_is_previous_month():
    # 7월 3일(10일 이전) → 전월(6월) 전체.
    assert steps.compute_period(date(2026, 7, 3)) == ("2026-06-01", "2026-06-30")


def test_compute_period_on_or_after_cutoff_is_current_month_to_today():
    # 7월 15일(10일 이후) → 당월 1일~오늘.
    assert steps.compute_period(date(2026, 7, 15)) == ("2026-07-01", "2026-07-15")


def test_compute_period_january_rolls_to_previous_year():
    # 1월 5일 → 전년 12월 전체(연도 롤백).
    assert steps.compute_period(date(2026, 1, 5)) == ("2025-12-01", "2025-12-31")


# ── 휴리스틱 ──────────────────────────────────────────────────────────────────
def test_recommend_note_matches_keyword():
    assert recommend_note("행복푸드", "10000") == "식대(법인카드)"
    assert recommend_note("공영주차장", "3000") == "주차료(법인카드)"


def test_recommend_note_fallback_uses_merchant():
    assert recommend_note("무명상점", "1000") == "무명상점 사용"
    assert recommend_note("", "1000") == "법인카드 사용"


def test_fmt_won_formats_thousands():
    assert _fmt_won("12000") == "12,000원"
    assert _fmt_won(3500) == "3,500원"
    assert _fmt_won("N/A") == "N/A원"  # 숫자 아님 → 원문 유지


# ── collect_rows 빈 리스트 경로 ────────────────────────────────────────────────
async def test_collect_rows_empty_list_announces_and_returns_zero():
    events: asyncio.Queue = asyncio.Queue()
    node = make_collect_rows_node()
    # rows_list 없음 → gemini/page 미사용 조기 종료.
    out = await node({"events": events, "page": None, "rows_list": []})
    assert out == {"filled": 0}
    # 안내 채팅(cc-empty)이 방출됐는지 — 조용히 끝나지 않는다.
    frames = []
    while not events.empty():
        frames.append(await events.get())
    chat = [f for f in frames if isinstance(f.get("chat"), dict)]
    assert any("0건" in (c["chat"].get("content") or "") for c in chat)
