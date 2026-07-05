"""법인카드 승인내역 정리(card-collect) — 카드팝업 이후 노드(진입 앞단은 expense_card 재사용).

체인: (login→user_type→menu_nav→set_gubun→add_row→open_evdn→select_evdn = expense_card 재사용)
→ select_all_cards → set_period(D2) → query(리스트 조회·표 보고) → collect_rows(그리드 HITL 로
행별 예산단위·프로젝트·적요 일괄 입력) → save(최종 HITL 확인 후에만 F7).

state 계약: page/browser/events/userid/password/params(러너 주입). 실패는 {"error"} 로 남긴다.
⚠ 저장(F7)은 collect 완료 후 사용자가 HITL 로 '저장'을 택했을 때만. 그 외 저장 절대 금지.

collect_rows 는 kind="grid" HITL 프레임을 방출한다 — 프론트가 행 그리드 + 예산단위/프로젝트
피커 UI 를 그리고, 사용자가 값을 채워 한 번에 제출(`rows`)하거나 프로젝트 검색(`query`)을 보낸다.
Gemini 대화 루프는 제거됐다(그리드 채널로 대체).

2026-07-05: 단일 nodes.py(1520줄)를 nodes/ 패키지(_shared·query·catalog·prefill·
collect·batch·pass2·save)로 분할 — 공개 심볼은 여기서 전부 재수출한다.
"""

from __future__ import annotations

from . import _shared, batch, catalog, collect, pass2, prefill, query, save
from ._shared import (
    FIELD_SPEC,
    _MAX_BUDGET_UNITS,
    _MAX_FAVORITES,
    _MAX_PROJECT_RESULTS,
    _STATUS_MARK,
    _fmt_won,
    _md_cell,
    _ms,
    _params_today,
    _row_key,
    _status_table,
    recommend_note,
)
from .batch import _apply_batch, _apply_group_fields, _batch_key
from .catalog import (
    _COST_PREFIX,
    _COST_PROJECT_NO,
    _acct_norm,
    _load_budget_catalog,
    _load_cost_project,
    _load_user_favorites,
    _pick_budget,
    _pick_project,
    _resolve_seed_budget,
)
from .collect import _validate_grid_submit, make_collect_rows_node
from .pass2 import (
    _apply_doc,
    make_apply_doc_node,
    make_apply_pass2_node,
    make_switch_evdn_node,
)
from .prefill import _prefill_selections
from .query import (
    make_query_node,
    make_select_all_cards_node,
    make_set_acct_date_node,
    make_set_period_node,
)
from .save import (
    MAX_SAVE_RETRIES,
    _SAVE_APRVL_RE,
    _SAVE_REQ_ACCT_RE,
    _parse_save_rejections,
    _save_guidance,
    make_save_final_node,
)

__all__ = [
    # 서브모듈(테스트가 monkeypatch 대상으로 직접 import)
    "_shared", "batch", "catalog", "collect", "pass2", "prefill", "query", "save",
    # _shared
    "FIELD_SPEC", "_MAX_BUDGET_UNITS", "_MAX_FAVORITES", "_MAX_PROJECT_RESULTS",
    "_STATUS_MARK", "_fmt_won", "_md_cell", "_ms", "_params_today", "_row_key",
    "_status_table", "recommend_note",
    # batch
    "_apply_batch", "_apply_group_fields", "_batch_key",
    # catalog
    "_COST_PREFIX", "_COST_PROJECT_NO", "_acct_norm", "_load_budget_catalog",
    "_load_cost_project", "_load_user_favorites", "_pick_budget", "_pick_project",
    "_resolve_seed_budget",
    # collect
    "_validate_grid_submit", "make_collect_rows_node",
    # pass2
    "_apply_doc", "make_apply_doc_node", "make_apply_pass2_node", "make_switch_evdn_node",
    # prefill
    "_prefill_selections",
    # query
    "make_query_node", "make_select_all_cards_node", "make_set_acct_date_node",
    "make_set_period_node",
    # save
    "MAX_SAVE_RETRIES", "_SAVE_APRVL_RE", "_SAVE_REQ_ACCT_RE",
    "_parse_save_rejections", "_save_guidance", "make_save_final_node",
]
