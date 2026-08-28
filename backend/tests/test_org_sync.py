"""org_sync.api_tree_to_items 단위 테스트 — 조직도 API treeList → preorder items 변환."""

from __future__ import annotations

from app.services.org_sync import api_tree_to_items, build_full_tree, flatten_to_hq_team


def _tl():
    # 배열은 레벨-그룹(비-preorder) + id 충돌(회사·사업장 둘 다 '1000') + 형제 orderNum 뒤섞임.
    return [
        {"path": "1000|", "text": "회사", "orgLevel": 0, "orgGubun": "c", "childUserCnt": 100, "orderNum": 1},
        {"path": "1000|1000|", "text": "사업장", "orgLevel": 1, "orgGubun": "b", "childUserCnt": 100, "orderNum": 1},
        {"path": "1000|1000|20|", "text": "본부B", "orgLevel": 2, "orgGubun": "d", "childUserCnt": 5, "orderNum": 20},
        {"path": "1000|1000|10|", "text": "본부A", "orgLevel": 2, "orgGubun": "d", "childUserCnt": 8, "orderNum": 10},
        {"path": "1000|1000|10|11|", "text": "A팀", "orgLevel": 3, "orgGubun": "d", "childUserCnt": 3, "orderNum": 11},
    ]


def test_api_tree_to_items_preorder_and_mapping():
    items = api_tree_to_items(_tl())
    # path 기반 재정렬 → 전위순회. 본부A(orderNum10) 가 본부B(20) 보다 먼저, A팀은 본부A 직후.
    assert [i["label"] for i in items] == ["회사", "사업장", "본부A", "A팀", "본부B"]
    assert [i["depth"] for i in items] == [0, 1, 2, 3, 2]
    assert [i["type"] for i in items] == ["company", "business", "dept", "dept", "dept"]
    assert items[3] == {"depth": 3, "label": "A팀", "count": 3, "type": "dept"}


def test_api_tree_to_items_feeds_flatten_and_build():
    items = api_tree_to_items(_tl())
    flat = flatten_to_hq_team(items)
    # 본부A 는 자식(A팀) 보유 → (본부A, A팀). 본부B 는 leaf → 동명 팀.
    assert {(r["hq"], r["team"]) for r in flat} == {("본부A", "A팀"), ("본부B", "본부B")}
    nodes = build_full_tree(items)
    assert {n["label"] for n in nodes} == {"본부A", "A팀", "본부B"}  # 회사/사업장 제외, 본부 이하


def test_api_tree_to_items_skips_pathless_rows():
    items = api_tree_to_items([{"text": "노패스", "orgLevel": 2, "orgGubun": "d"}])
    assert items == []
