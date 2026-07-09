"""trip-domestic 노드 순수 로직 테스트 — 브라우저 없이(스텝 monkeypatch) 계약·분기 검증.

- state-contract: 각 노드 출력 키가 TripDomesticState 에 선언됐는지(LangGraph silent drop 방지).
- validate_params: 정규화 성공 / 부서·비용구분 누락 / 잘못된 params 오류 경로.
- fill_rows: 행별 스텝 호출 순서·통행료/유류비 거래처 분기·실패 시 행·필드 명시 error.
- save_doc: 반영 0건 스킵 / 저장 거부 재시도 신호 / 상한 초과 실패 / 성공.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.trip_domestic.graph import TripDomesticState
from app.agents.trip_domestic.nodes import fill, save
from app.agents.trip_domestic.nodes.fill import make_fill_rows_node, make_set_acct_date_node
from app.agents.trip_domestic.nodes.save import make_save_doc_node
from app.agents.trip_domestic.nodes.validate import make_validate_params_node
from tests.support.state_contract import assert_keys_declared

pytestmark = pytest.mark.asyncio

# 차량종류는 동적 목록(fuel_classes) — 실효 설정 형태와 일치시킨다.
DEFAULT_SETTINGS = {
    "fuel_unit_price": 2000,
    "fuel_classes": [
        {"id": "under1000", "label": "1,000cc 미만", "kmPerL": 14},
        {"id": "under1600", "label": "1,600cc 미만", "kmPerL": 9},
        {"id": "under2000", "label": "2,000cc 미만", "kmPerL": 7},
        {"id": "over2000", "label": "2,000cc 이상", "kmPerL": 6},
    ],
}


def _q() -> asyncio.Queue:
    return asyncio.Queue()


def _toll(**over) -> dict:
    return {
        "type": "toll",
        "invoiceDate": "2026-07-03",
        "partnerCode": "P001",
        "partnerName": "한국도로공사",
        "amount": 15400,
        "project": {"code": "PJT|WBS", "name": "출장 프로젝트"},
        **over,
    }


def _fuel(**over) -> dict:
    return {
        "type": "fuel",
        "invoiceDate": "2026-07-03",
        "km": 320,
        "carClass": "under1600",
        "project": {"code": "PJT|WBS", "name": "출장 프로젝트"},
        **over,
    }


def _trip_params(rows, **over) -> dict:
    return {
        **DEFAULT_SETTINGS,
        "department": "회계팀",
        "cost_type": "판관비",
        "trip": {"rows": rows},
        **over,
    }


# ── validate_params ───────────────────────────────────────────────────────────
async def test_validate_success_declares_all_keys():
    node = make_validate_params_node()
    out = await node({"events": _q(), "params": _trip_params([_toll(), _fuel()])})
    assert "error" not in out
    assert out["acct_date_compact"] == "20260703"
    assert out["department"] == "회계팀" and out["cost_type"] == "판관비"
    assert [r["type"] for r in out["plan_rows"]] == ["toll", "fuel"]
    assert out["plan_rows"][1]["amount"] == round(320 / 9 * 2000)  # 유류비 백엔드 계산
    assert_keys_declared(TripDomesticState, out)


async def test_validate_missing_department_errors():
    node = make_validate_params_node()
    params = _trip_params([_toll()])
    del params["department"]
    out = await node({"events": _q(), "params": params})
    assert "부서" in out["error"]
    assert_keys_declared(TripDomesticState, out)


async def test_validate_missing_cost_type_errors():
    node = make_validate_params_node()
    params = _trip_params([_toll()])
    del params["cost_type"]
    out = await node({"events": _q(), "params": params})
    assert "비용구분" in out["error"]


async def test_validate_bad_params_errors_in_korean():
    node = make_validate_params_node()
    params = _trip_params([_toll(partnerCode="", partnerName="")])
    out = await node({"events": _q(), "params": params})
    assert "거래처가 없습니다" in out["error"]


async def test_validate_short_circuits_on_prior_error():
    node = make_validate_params_node()
    out = await node({"events": _q(), "error": "이전 실패", "params": _trip_params([_toll()])})
    assert out == {}


# ── set_acct_date ─────────────────────────────────────────────────────────────
async def test_set_acct_date_bad_format_errors():
    node = make_set_acct_date_node()
    out = await node({"events": _q(), "page": object(), "acct_date_compact": "2026-07-03"})
    assert "형식 오류" in out["error"]
    assert_keys_declared(TripDomesticState, out)


async def test_set_acct_date_success(monkeypatch):
    async def _ok(page, compact, dashed):
        return {"ok": True, "display": dashed}

    monkeypatch.setattr(fill.doc_steps, "set_acct_date", _ok)
    node = make_set_acct_date_node()
    out = await node({"events": _q(), "page": object(), "acct_date_compact": "20260703"})
    assert out == {}


# ── fill_rows(스텝 monkeypatch) ───────────────────────────────────────────────
class _FakePage:
    """fill_rows 는 모든 detail 조작을 steps/doc_steps 로 위임(스텁)하므로 page.evaluate 는
    직접 호출하지 않는다 — 금액도 steps.set_transaction_amount 안에서 세팅된다."""

    async def evaluate(self, js_src, arg=None):
        return {"ok": True, "after": str(arg)}

    async def wait_for_timeout(self, ms):
        return None


def _patch_all_ok(monkeypatch, calls: list):
    """모든 detail 스텝을 ok 로 스텁하고 호출 순서를 calls 에 기록."""

    def _rec(name, extra=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(extra or {})}

        return _f

    monkeypatch.setattr(fill.doc_steps, "add_next_row", _rec("add_next_row", {"rows": 2}))
    monkeypatch.setattr(fill.doc_steps, "open_evdn_editor", _rec("open_evdn", {"shown": {}}))
    monkeypatch.setattr(fill.doc_steps, "select_evdn_code", _rec("select_evdn", {"name": "규정에의한 비용정산", "code": "10"}))
    monkeypatch.setattr(fill.steps, "fill_partner", _rec("fill_partner", {"name": "한국도로공사"}))
    monkeypatch.setattr(fill.steps, "fill_partner_by_search", _rec("fill_partner_by_search", {"name": "이트라이브2"}))
    monkeypatch.setattr(fill.steps, "fill_budget_fixed", _rec("fill_budget"))
    monkeypatch.setattr(fill.steps, "fill_project", _rec("fill_project"))
    monkeypatch.setattr(fill.steps, "set_invoice_date", _rec("set_invoice_date"))
    monkeypatch.setattr(fill.steps, "type_amount", _rec("type_amount"))
    monkeypatch.setattr(fill.steps, "set_row_note", _rec("set_row_note"))
    monkeypatch.setattr(fill.steps, "register_counter_partner", _rec("register_counter_partner"))
    monkeypatch.setattr(fill.steps, "delete_blank_row", _rec("delete_blank_row"))


async def test_fill_rows_two_rows_success(monkeypatch):
    calls: list = []
    _patch_all_ok(monkeypatch, calls)
    page = _FakePage()
    node = make_fill_rows_node()
    state = {
        "events": _q(),
        "page": page,
        "userid": "이트라이브2",
        "department": "회계팀",
        "cost_type": "판관비",
        "plan_rows": [
            {"type": "toll", "partnerCode": "P001", "partnerName": "한국도로공사", "amount": 15400, "project": {"code": "A|B", "name": "P"}, "note": "통행료(현금)", "km": None, "carClass": None},
            {"type": "fuel", "partnerCode": "", "partnerName": "", "amount": 71111, "project": {"code": "A|B", "name": "P"}, "note": "유류비", "km": 320, "carClass": "under1600"},
        ],
    }
    out = await node(state)
    assert out["filled"] == 2 and out["fill_failures"] == []
    assert_keys_declared(TripDomesticState, out)
    # 2행째만 add_next_row(1행은 앞단 add_row 노드가 생성).
    assert calls.count("add_next_row") == 1
    # 통행료는 fill_partner, 유류비는 fill_partner_by_search(본인).
    assert "fill_partner" in calls and "fill_partner_by_search" in calls
    # 상대계정거래처 = 행별 register_counter_partner(부가선택 위젯) + 딸려온 빈 행 delete_blank_row.
    assert calls.count("register_counter_partner") == 2
    assert calls.count("delete_blank_row") == 2
    # 금액은 type_amount(셀 에디터 타이핑 + 예산현황 확인) 로 행별 세팅.
    assert calls.count("type_amount") == 2
    # (세금)계산서일(START_DT)도 행별 세팅.
    assert calls.count("set_invoice_date") == 2


async def test_fill_rows_partner_failure_reports_row_and_field(monkeypatch):
    calls: list = []
    _patch_all_ok(monkeypatch, calls)

    async def _fail_partner(*a, **k):
        return {"ok": False, "reason": "거래처 '한국도로공사' 일치 없음"}

    monkeypatch.setattr(fill.steps, "fill_partner", _fail_partner)
    node = make_fill_rows_node()
    state = {
        "events": _q(),
        "page": _FakePage(),
        "userid": "이트라이브2",
        "department": "회계팀",
        "cost_type": "판관비",
        "plan_rows": [
            {"type": "toll", "partnerCode": "P", "partnerName": "한국도로공사", "amount": 15400, "project": {"code": "A|B", "name": "P"}, "note": "통행료(현금)", "km": None, "carClass": None},
        ],
    }
    out = await node(state)
    assert "1행" in out["error"] and "거래처" in out["error"]
    assert out["fill_failures"] == [{"row": 1, "field": "거래처", "reason": "거래처 '한국도로공사' 일치 없음"}]
    assert_keys_declared(TripDomesticState, out)


async def test_fill_rows_amount_failure_fails_fast(monkeypatch):
    # 거래금액 세팅 실패(type_amount)는 fail-fast 여야 한다(반쪽 결의서 저장 방지).
    calls: list = []
    _patch_all_ok(monkeypatch, calls)

    async def _fail_amount(*a, **k):
        return {"ok": False, "reason": "합계금액 반영 불일치(기대 15,400·실제 0)"}

    monkeypatch.setattr(fill.steps, "type_amount", _fail_amount)
    node = make_fill_rows_node()
    out = await node({
        "events": _q(),
        "page": _FakePage(),
        "userid": "이트라이브2",
        "department": "회계팀",
        "cost_type": "판관비",
        "plan_rows": [_toll(km=None, carClass=None, note="통행료(현금)")],
    })
    assert "1행" in out["error"] and "거래금액" in out["error"]
    assert out["fill_failures"] == [{"row": 1, "field": "거래금액", "reason": "합계금액 반영 불일치(기대 15,400·실제 0)"}]
    assert_keys_declared(TripDomesticState, out)


async def test_fill_rows_requires_self_name(monkeypatch):
    calls: list = []
    _patch_all_ok(monkeypatch, calls)
    node = make_fill_rows_node()
    out = await node({
        "events": _q(),
        "page": _FakePage(),
        "userid": "",
        "department": "회계팀",
        "cost_type": "판관비",
        "plan_rows": [_toll()],
    })
    assert "본인 이름" in out["error"]


# ── save_doc ──────────────────────────────────────────────────────────────────
class _SavePage:
    """save_doc 는 F7 전 blur JS 를 page.evaluate 로 실행한다 — 최소 스텁."""

    async def evaluate(self, js_src, arg=None):
        return True

    async def wait_for_timeout(self, ms):
        return None


async def test_save_doc_skips_when_nothing_filled():
    node = make_save_doc_node()
    out = await node({"events": _q(), "page": object(), "filled": 0})
    assert "저장하지 않았습니다" in out["result"] and out["retry_save"] is False
    assert_keys_declared(TripDomesticState, out)


async def test_save_doc_success(monkeypatch):
    async def _ok(page, confirm):
        return {"ok": True, "modals_seen": []}

    monkeypatch.setattr(save.card_steps, "save_document", _ok)
    node = make_save_doc_node()
    out = await node({"events": _q(), "page": _SavePage(), "filled": 2})
    assert "입력·저장" in out["result"] and out["retry_save"] is False
    assert_keys_declared(TripDomesticState, out)


async def test_save_doc_transient_rejection_signals_retry(monkeypatch):
    # 비결정적(일시적) 실패로 분류되는 사유 → 재시도 신호(검증/ERP/필수 마커·토스트 없음).
    async def _reject(page, confirm):
        return {"ok": False, "reason": "카드팝업이 열려 있어 저장 불가"}

    monkeypatch.setattr(save.card_steps, "save_document", _reject)
    node = make_save_doc_node()
    out = await node({"events": _q(), "page": _SavePage(), "filled": 1, "save_retries": 0})
    assert out["retry_save"] is True and out["save_retries"] == 1
    assert out["save_error_msg"] == "카드팝업이 열려 있어 저장 불가"
    assert_keys_declared(TripDomesticState, out)


async def test_save_doc_validation_rejection_no_retry(monkeypatch):
    # 검증성(결정적) 거부 = 동일 입력 재작성 무의미 → 재시도 없이 즉시 실패(리뷰 반영).
    async def _reject(page, confirm):
        return {
            "ok": False,
            "reason": "저장(F7)이 검증 실패로 거부됨: 상세그리드에 필수 값이 입력되지 않은 항목이 있습니다",
            "toasts_seen": ["필수 값이 입력되지 않은 항목이 있습니다"],
        }

    monkeypatch.setattr(save.card_steps, "save_document", _reject)
    node = make_save_doc_node()
    out = await node({"events": _q(), "page": _SavePage(), "filled": 1, "save_retries": 0})
    assert out["retry_save"] is False
    assert "거부" in out["error"] and "재시도" not in out["error"]
    assert_keys_declared(TripDomesticState, out)


async def test_save_doc_gives_up_after_max_retries(monkeypatch):
    async def _reject(page, confirm):
        return {"ok": False, "reason": "일시적 팝업 잔존"}

    monkeypatch.setattr(save.card_steps, "save_document", _reject)
    node = make_save_doc_node()
    out = await node({"events": _q(), "page": _SavePage(), "filled": 1, "save_retries": save.MAX_SAVE_RETRIES})
    assert "포기" in out["error"] and out["retry_save"] is False


async def test_save_doc_short_circuits_on_prior_error():
    node = make_save_doc_node()
    out = await node({"events": _q(), "page": object(), "error": "채움 실패"})
    assert "저장하지 않음" in out["result"] and out["retry_save"] is False
