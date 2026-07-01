"""grid/strategies — CollectionStrategy enum + GridExtractor 구성(라이브 없이)."""

from __future__ import annotations

from nbkit.grid.strategies import CollectionStrategy, GridExtractor


def test_collection_strategy_values():
    assert CollectionStrategy.PARALLEL_AJAX.value == "parallel_ajax"
    assert CollectionStrategy.KEYBOARD_FALLBACK.value == "keyboard_fallback"
    assert CollectionStrategy.AUTO.value == "auto"
    assert {s.value for s in CollectionStrategy} == {
        "parallel_ajax",
        "keyboard_fallback",
        "auto",
    }


def test_collection_strategy_is_str_enum():
    # str 혼합 enum → JSON/이벤트 직렬화가 문자열로 자연스럽게.
    assert CollectionStrategy.AUTO == "auto"


def test_extractor_constructs_without_live_page():
    ex = GridExtractor(page=None, master_index=0, detail_index=1)
    assert ex._master_index == 0
    assert ex._detail_index == 1
