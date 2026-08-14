"""학자금신청서(hakjagum-grant) — params(단건·금액 passthrough)·검증·그래프/등록·픽스처 lockstep.

detail ERP 스텝(피커·setValue·타이핑)은 국내출장 스텝을 재사용하므로 국내출장 테스트로 커버되고,
여기선 학자금 고유분(단건 스키마·공급가액=사용자 입력 그대로(50% 규칙 없음)·예산계정명
'복리후생비-기타'·회계일=증빙일·결의구분 라벨·State 계약·워크플로우 등록·픽스처 steps↔그래프
노드 순서 일치)만 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.hakjagum_grant.graph import (
    HAKJAGUM_GUBUN_LABEL,
    HakjagumGrantState,
    build_hakjagum_grant_graph,
)
from app.agents.hakjagum_grant.nodes import fill
from app.agents.hakjagum_grant.nodes.fill import make_fill_rows_node
from app.agents.hakjagum_grant.nodes.validate import make_validate_params_node
from app.agents.hakjagum_grant.params import parse_hakjagum_params
from app.agents.hakjagum_grant.steps import bgacct_name_for_cost_type
from tests.support.state_contract import assert_keys_declared


def _hj(**over) -> dict:
    return {
        "evidenceDate": "2026-07-15",
        "baseAmount": 200_000,
        "project": {"code": "800|800", "name": "판매관리비"},
        **over,
    }


# ── 금액 passthrough: 공급가액 = 사용자 입력 그대로(50% 규칙 없음 — 경조금과 차이) ──
def test_parse_amount_passthrough_at_half_boundary():
    # 경조금이면 under1Year=True 에서 100,001 → 50,001 로 반값이 되는 .5 경계값 — 학자금은
    # 반값/반올림 규칙 자체가 없어 입력 그대로 실린다(50% 규칙 회귀 감지).
    rows, _ = parse_hakjagum_params({"hakjagum": _hj(baseAmount=100_001)})
    assert rows[0]["amount"] == 100_001


def test_parse_amount_passthrough_odd_value():
    # 100,003 도 반올림·감액 없이 그대로(경조금 반값이면 50,002 가 됐을 값).
    rows, _ = parse_hakjagum_params({"hakjagum": _hj(baseAmount=100_003)})
    assert rows[0]["amount"] == 100_003


def test_parse_ignores_legacy_under1year_key():
    # 경조금 폼의 잔재 키(under1Year=True)가 섞여 와도 무시 — 50% 미적용, 정액 그대로.
    rows, _ = parse_hakjagum_params({"hakjagum": _hj(baseAmount=200_000, under1Year=True)})
    assert rows[0]["amount"] == 200_000


# ── parse_hakjagum_params: 단건 정규화·회계일=증빙일 ──────────────────────────
def test_parse_normalizes_single_row():
    rows, acct = parse_hakjagum_params({"hakjagum": _hj()})
    assert acct == "20260715"  # 회계일 = 증빙일(그대로).
    assert len(rows) == 1
    assert rows[0]["invoiceDate"] == "20260715"
    assert rows[0]["amount"] == 200_000
    assert rows[0]["project"] == {"code": "800|800", "name": "판매관리비"}


def test_parse_acct_equals_evidence_date():
    _, acct = parse_hakjagum_params({"hakjagum": _hj(evidenceDate="2026-05-01")})
    assert acct == "20260501"


def test_parse_preserves_project_extra():
    rows, _ = parse_hakjagum_params(
        {"hakjagum": _hj(project={"code": "800|800", "name": "P", "wbsNo": "800"})}
    )
    assert rows[0]["project"]["wbsNo"] == "800"


# ── parse_hakjagum_params: 검증 오류(한국어) ─────────────────────────────────
def test_parse_missing_hakjagum_raises():
    with pytest.raises(ValueError, match="학자금 입력"):
        parse_hakjagum_params({})


def test_parse_nonpositive_amount_raises():
    with pytest.raises(ValueError, match="정액"):
        parse_hakjagum_params({"hakjagum": _hj(baseAmount=0)})


def test_parse_missing_project_raises():
    with pytest.raises(ValueError, match="프로젝트"):
        parse_hakjagum_params({"hakjagum": _hj(project={"code": ""})})


def test_parse_missing_evidence_date_raises():
    hj = _hj()
    del hj["evidenceDate"]
    with pytest.raises(ValueError, match="증빙일"):
        parse_hakjagum_params({"hakjagum": hj})


# ── 예산계정명(D8): base "복리후생비-기타" ────────────────────────────────────
def test_bgacct_name_pankwan():
    assert bgacct_name_for_cost_type("판관비") == "(판)복리후생비-기타"


def test_bgacct_name_jejo():
    assert bgacct_name_for_cost_type("제조원가") == "(제)복리후생비-기타"


def test_bgacct_name_unknown_raises():
    with pytest.raises(ValueError, match="비용구분"):
        bgacct_name_for_cost_type("복리")


# ── validate_params 노드(코루틴 직접 호출) ────────────────────────────────────
@pytest.mark.asyncio
async def test_validate_node_success():
    node = make_validate_params_node()
    params = {"department": "회계팀", "cost_type": "판관비", "hakjagum": _hj()}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "error" not in out
    assert out["acct_date_compact"] == "20260715"
    assert out["department"] == "회계팀" and out["cost_type"] == "판관비"
    assert len(out["plan_rows"]) == 1
    # 노드 출력 키가 State 에 전부 선언됐는지(LangGraph silent drop 방지).
    assert_keys_declared(HakjagumGrantState, out)


@pytest.mark.asyncio
async def test_validate_node_missing_department_errors():
    node = make_validate_params_node()
    params = {"cost_type": "판관비", "hakjagum": _hj()}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "부서" in out["error"]
    assert "복리후생비-기타" in out["error"]  # 오류 문구가 학자금 예산단위를 가리킨다.


@pytest.mark.asyncio
async def test_validate_node_missing_cost_type_errors():
    node = make_validate_params_node()
    params = {"department": "회계팀", "hakjagum": _hj()}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "비용구분" in out["error"]


@pytest.mark.asyncio
async def test_validate_node_invalid_params_short_circuits():
    node = make_validate_params_node()
    params = {"department": "회계팀", "cost_type": "판관비", "hakjagum": _hj(baseAmount=0)}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "정액" in out["error"]


# ── 결의구분 라벨 + 그래프 + 등록 ─────────────────────────────────────────────
def test_gubun_label_is_hakjagum():
    assert HAKJAGUM_GUBUN_LABEL == "학자금신청서"


def test_graph_compiles():
    assert build_hakjagum_grant_graph() is not None


def test_registered_in_workflow_registry():
    import app.agents  # noqa: F401 — import 시 register_workflow 트리거

    from app.live.registry import get_spec

    spec = get_spec("hakjagum-grant")
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale == 0.4
    assert spec.site == "omnisol"


# ── 픽스처 steps ↔ 그래프 노드 순서 lockstep ─────────────────────────────────
def test_fixture_promoted_from_dummy():
    from app.services.agent_fixtures import AGENT_FIXTURES

    fx = next((f for f in AGENT_FIXTURES if f.get("workflow_id") == "hakjagum-grant"), None)
    assert fx is not None  # scholarship 더미에서 승격.
    assert fx["interaction"] == "autonomous"
    assert fx["group_id"] == "resolution"
    assert fx["hidden"] is False  # 라이브 스모크 10/10 통과 후 노출(경조금 관례, 2026-07-15).
    assert fx["flow_graph"] is not None
    assert fx.get("handoff_note")  # 상신 수동 안내.
    # steps 의 key 순서는 build_hakjagum_grant_graph 의 노드 등록 순서와 정확히 일치해야 한다.
    step_keys = [s["key"] for s in fx["steps"]]
    assert step_keys == [
        "validate_params",
        "login",
        "user_type",
        "menu_nav",
        "set_gubun",
        "add_row",
        "set_acct_date",
        "fill_rows",
        "save_doc",
    ]


# ── fill_rows 노드(스텝 monkeypatch — 브라우저 없이 계약·분기 검증) ────────────────
# detail ERP 스텝은 국내출장 재사용이라 trip 테스트가 커버하지만, 학자금 fill 노드 고유 조립
# (단건 채움 순서·거래처 본인검색 분기·적요 '학자금-{본인이름}'·실패 단락·State 계약)은 여기서 강제한다.
class _FakePage:
    """fill_rows 는 모든 detail 조작을 steps/doc_steps 로 위임(스텁)하므로 page.evaluate 는 직접
    호출하지 않는다. screenshot 미구현이라 emit_shot 은 우아하게 생략된다(캡처 실패 → None)."""

    async def evaluate(self, js_src, arg=None):
        return {"ok": True, "after": str(arg)}

    async def wait_for_timeout(self, ms):
        return None


def _patch_fill_all_ok(monkeypatch, calls: list, notes: list):
    """모든 detail 스텝을 ok 로 스텁 — 호출 순서를 calls 에, 적요 텍스트를 notes 에 기록.

    거래처 본인검색(fill_partner_by_search)은 로그인 계정과 **다른** 표시명('홍길동')을 돌려줘,
    적요가 userid 가 아니라 본인검색 결과 이름으로 조립되는지 구분 검증되게 한다.
    """

    def _rec(name, extra=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(extra or {})}

        return _f

    async def _rec_note(page, text):
        calls.append("set_row_note")
        notes.append(text)
        return {"ok": True}

    monkeypatch.setattr(fill.doc_steps, "open_evdn_editor", _rec("open_evdn", {"shown": {}}))
    monkeypatch.setattr(fill.doc_steps, "select_evdn_code", _rec("select_evdn", {"name": "규정에의한 비용정산", "code": "10"}))
    monkeypatch.setattr(fill.steps, "set_invoice_date", _rec("set_invoice_date"))
    monkeypatch.setattr(fill.steps, "fill_partner_by_search", _rec("fill_partner_by_search", {"name": "홍길동"}))
    monkeypatch.setattr(fill.steps, "fill_budget_fixed", _rec("fill_budget"))
    monkeypatch.setattr(fill.steps, "fill_project", _rec("fill_project"))
    monkeypatch.setattr(fill.steps, "type_amount", _rec("type_amount"))
    monkeypatch.setattr(fill.steps, "set_row_note", _rec_note)
    monkeypatch.setattr(fill.steps, "set_master_total", _rec("set_master_total"))


def _fill_state(**over) -> dict:
    state = {
        "events": asyncio.Queue(),
        "page": _FakePage(),
        "userid": "이트라이브2계정",  # 로그인 계정 id — 표시명(홍길동)과 다름.
        "department": "회계팀",
        "cost_type": "판관비",
        "plan_rows": [
            {
                "invoiceDate": "20260715",
                "amount": 200_000,  # 사용자 입력 금액 그대로(50% 규칙 없음).
                "project": {"code": "800|800", "name": "판매관리비"},
            }
        ],
    }
    state.update(over)
    return state


@pytest.mark.asyncio
async def test_fill_rows_single_row_success(monkeypatch):
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)
    node = make_fill_rows_node()
    out = await node(_fill_state())
    assert out["filled"] == 1 and out["fill_failures"] == []
    assert_keys_declared(HakjagumGrantState, out)
    # 단건 — 각 스텝 정확히 1회(다행 F3 루프 없음).
    assert calls.count("type_amount") == 1
    assert calls.count("set_invoice_date") == 1
    assert calls.count("set_master_total") == 1
    # 거래처 = 작성자 본인 검색(통행료 fill_partner 아님).
    assert "fill_partner_by_search" in calls
    # 적요 = '학자금-{본인이름}' — userid('이트라이브2계정') 가 아니라 본인검색 표시명('홍길동')으로 조립(D7).
    assert notes == ["학자금-홍길동"]
    # 상대계정거래처는 미사용(경조금 동형 가정, 검증:❓) — fill 에서 스텝 자체가 없다.
    assert "register_counter_partner" not in calls and "delete_blank_row" not in calls


@pytest.mark.asyncio
async def test_fill_rows_field_failure_reports_field_and_short_circuits(monkeypatch):
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)

    async def _fail_budget(*a, **k):
        return {"ok": False, "reason": "예산단위 조합 무매칭: 회계팀 · (판)복리후생비-기타"}

    monkeypatch.setattr(fill.steps, "fill_budget_fixed", _fail_budget)
    node = make_fill_rows_node()
    out = await node(_fill_state())
    assert "예산단위" in out["error"]
    assert out["fill_failures"] == [
        {"row": 1, "field": "예산단위", "reason": "예산단위 조합 무매칭: 회계팀 · (판)복리후생비-기타"}
    ]
    # 예산단위 실패 → 이후 스텝(프로젝트·금액·적요) 미호출(조기 반환).
    assert "fill_project" not in calls
    assert "type_amount" not in calls
    assert notes == []
    assert_keys_declared(HakjagumGrantState, out)


@pytest.mark.asyncio
async def test_fill_rows_requires_self_name(monkeypatch):
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)
    node = make_fill_rows_node()
    out = await node(_fill_state(userid=""))
    assert "본인 이름" in out["error"]
    assert calls == []  # 본인 이름 없으면 어떤 detail 스텝도 호출하지 않는다.


# ══════════════════════════════════════════════════════════════════════════════
# 확인(verify) 커널 계약 — "세팅했다"가 아니라 "반영됐다"를 근거로만 성공을 돌려준다.
#   실물 시맨틱: setValue 는 ERP 핸들러가 되돌리면 **호출은 성공(ok:true)인데 셀은 옛 값**이고,
#   코드피커 '적용'은 이름(BG_NM)만 비슷한 다른 행이 붙을 수 있다. 페이크는 이 두 가지를
#   그대로 재현한다(값을 안 붙이지만 setter 는 ok 를 돌려준다).
# ══════════════════════════════════════════════════════════════════════════════
import re  # noqa: E402 — 확인 커널 테스트 블록 전용(위 블록의 import 순서를 건드리지 않음).

from nbkit.omnisol import js_lib  # noqa: E402

from app.agents.hakjagum_grant import steps as hj_steps  # noqa: E402
from app.agents.hakjagum_grant.nodes.gubun import make_confirmed_set_gubun_node  # noqa: E402
from app.agents.trip_domestic import js as trip_js  # noqa: E402
from app.agents.trip_domestic import steps as trip_steps  # noqa: E402


class _GridPage:
    """detail RealGrid(index 1) 스텁 — setValue/셀 재독의 실물 시맨틱을 흉내낸다.

    frozen: 그 필드는 setValue 를 **삼킨다**(ERP 핸들러 되돌림 재현). 그래도 SET_DETAIL_CELL_JS 는
            ok:true 를 돌려준다 — 이게 국내출장 원본 스텝이 못 잡던 조용한 실패다.
    readable=False: 리더가 그리드를 못 잡는 상황(세션·버전차) — ok:false = **확인 불가**.
    """

    def __init__(self, cells: dict | None = None, *, frozen: tuple = (), readable: bool = True):
        self.cells: dict = dict(cells or {})
        self.frozen = frozen
        self.readable = readable

    async def evaluate(self, js_src, arg=None):
        if js_src is js_lib.GRID_CELL_VALUE_JS:
            if not self.readable:
                return {"ok": False, "reason": "detail 그리드 없음"}
            field = arg["field"]
            raw = str(self.cells.get(field, ""))
            return {
                "ok": True,
                "row": 0,
                "rows": 1,
                "raw": {field: raw},
                "compact": {field: re.sub(r"\D", "", raw)},
                "display": {field: raw},
            }
        if js_src is trip_js.SET_DETAIL_CELL_JS:
            field, value = arg["field"], arg["value"]
            if field not in self.frozen:
                self.cells[field] = value
            # ⚠ 되돌려진 경우에도 setter 는 성공을 돌려준다(after = 현재 셀 값).
            return {"ok": True, "row": 0, "after": str(self.cells.get(field, "")), "display": ""}
        if js_src is js_lib.PICKER_READ_MULTI_JS:
            return {
                "options": [
                    {
                        "i": 0,
                        "BG_CD": "2005",
                        "BG_NM": "회계팀",
                        "BIZPLAN_NM": "운영비",
                        "BGACCT_NM": "(판)복리후생비-기타",
                    }
                ]
            }
        return {"ok": True}

    async def wait_for_timeout(self, ms):
        return None


def _apply_writes(**cells):
    """피커 '적용'이 detail 셀에 쓰는 것을 흉내내는 _select_and_apply 스텁."""

    async def _f(page, row_index, label, verify_field, expect_value):
        page.cells.update(cells)
        return {"ok": True}

    return _f


def _patch_budget_picker(monkeypatch, apply_fn):
    """피커 열기/검색·선택은 국내출장 단일소스라 스텁 — 여기서 보는 건 **적용 후 확인**뿐이다."""

    async def _open_ok(*a, **k):
        return {"ok": True}

    async def _search_and_pick(page, keyword, fields, pick, **k):
        read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [fields, 0])
        return pick(read.get("options") or [])

    monkeypatch.setattr(trip_steps, "_open_detail_cell_picker", _open_ok)
    monkeypatch.setattr(trip_steps, "_search_and_pick", _search_and_pick)
    monkeypatch.setattr(trip_steps, "_select_and_apply", apply_fn)


# ── 적요(NOTE_DC): 세팅 + 셀 재독(확인은 국내출장 단일소스 스텝에 있다) ──────────
# 이 패키지는 그 스텝을 재수출만 하므로 여기서는 **재수출이 확인을 잃지 않았는지**를 계약으로 건다
# (적요는 단건 전표의 내용 그 자체라, 확인을 잃으면 빈 적요가 그대로 저장된다).
@pytest.mark.asyncio
async def test_set_row_note_ok_when_cell_reflects():
    page = _GridPage()
    r = await hj_steps.set_row_note(page, "학자금-홍길동")
    assert r["ok"] is True and "warn" not in r
    assert page.cells["NOTE_DC"] == "학자금-홍길동"


@pytest.mark.asyncio
async def test_set_row_note_hard_fails_when_cell_not_reflected():
    # ERP 핸들러가 적요를 되돌린 상황 — setter 는 ok 지만 셀은 빈 값이다.
    page = _GridPage(frozen=("NOTE_DC",))
    r = await hj_steps.set_row_note(page, "학자금-홍길동")
    assert r["ok"] is False
    assert "적요" in r["reason"]


@pytest.mark.asyncio
async def test_set_row_note_warns_when_cell_unreadable():
    # 리더가 그리드를 못 잡음 = 확인 불가 → 하드 실패가 아니라 warn 후 진행.
    page = _GridPage(readable=False)
    r = await hj_steps.set_row_note(page, "학자금-홍길동")
    assert r["ok"] is True
    assert "확인 불가" in r["warn"]


# ── 예산단위: 적용 후 BG_CD 완전일치 확인 ────────────────────────────────────
@pytest.mark.asyncio
async def test_fill_budget_ok_when_bg_cd_reflects(monkeypatch):
    page = _GridPage()
    _patch_budget_picker(monkeypatch, _apply_writes(BG_NM="회계팀", BG_CD="2005"))
    r = await hj_steps.fill_budget_fixed(page, "회계팀", "판관비")
    assert r["ok"] is True and r["code"] == "2005" and "warn" not in r


@pytest.mark.asyncio
async def test_fill_budget_hard_fails_when_other_budget_applied(monkeypatch):
    # 이름만 서로 포함되는 다른 예산단위(회계팀2/BG_CD 2099)가 붙은 상황 — BG_NM 상호포함
    # 판정은 통과시키지만 BG_CD 완전일치가 잡아낸다.
    page = _GridPage()
    _patch_budget_picker(monkeypatch, _apply_writes(BG_NM="회계팀2", BG_CD="2099"))
    r = await hj_steps.fill_budget_fixed(page, "회계팀", "판관비")
    assert r["ok"] is False
    assert "BG_CD" in r["reason"]


@pytest.mark.asyncio
async def test_fill_budget_warns_when_cell_unreadable(monkeypatch):
    page = _GridPage(readable=False)
    _patch_budget_picker(monkeypatch, _apply_writes(BG_NM="회계팀", BG_CD="2005"))
    r = await hj_steps.fill_budget_fixed(page, "회계팀", "판관비")
    assert r["ok"] is True and "확인 불가" in r["warn"]
    assert r["code"] == "2005"  # 확인 불가여도 선택 자체의 결과는 그대로 돌려준다.


# ── 결의구분: 세팅 후 선택 텍스트 재확인(문서 종류 = 대상 정의 → 하드) ────────────
class _GubunPage:
    """결의구분 native select 스텁 — revert 면 change 핸들러가 값을 되돌린다(실물 함정)."""

    def __init__(self, *, revert: bool = False, readable: bool = True):
        self.selected = "일반"
        self.revert = revert
        self.readable = readable

    async def evaluate(self, js_src, arg=None):
        if js_src is js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS:
            if not self.revert:  # 되돌림이면 세터는 ok 인데 선택값은 그대로다.
                self.selected = arg["text"]
            return {"ok": True}
        if js_src is js_lib.SELECTED_TEXT_JS:
            if not self.readable:
                return {"ok": False, "reason": "no-select"}
            return {"ok": True, "text": self.selected, "value": "56"}
        return True  # select 로드 폴링('(s) => !!document.querySelector(s)')

    async def wait_for_timeout(self, ms):
        return None


def _drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


@pytest.mark.asyncio
async def test_set_gubun_node_ok_when_selection_confirmed():
    events = asyncio.Queue()
    node = make_confirmed_set_gubun_node(HAKJAGUM_GUBUN_LABEL)
    out = await node({"events": events, "page": _GubunPage()})
    assert "error" not in out
    assert not [e for e in _drain(events) if e.get("level") == "warn"]


@pytest.mark.asyncio
async def test_set_gubun_node_hard_fails_when_reverted():
    events = asyncio.Queue()
    node = make_confirmed_set_gubun_node(HAKJAGUM_GUBUN_LABEL)
    out = await node({"events": events, "page": _GubunPage(revert=True)})
    assert "결의구분" in out["error"]
    assert [e for e in _drain(events) if e.get("status") == "failed"]


@pytest.mark.asyncio
async def test_set_gubun_node_warns_when_select_unreadable():
    events = asyncio.Queue()
    node = make_confirmed_set_gubun_node(HAKJAGUM_GUBUN_LABEL)
    out = await node({"events": events, "page": _GubunPage(readable=False)})
    assert "error" not in out  # 확인 불가는 플로우를 끊지 않는다.
    warns = [e for e in _drain(events) if e.get("level") == "warn"]
    assert warns and "결의구분" in warns[0]["log"]


# ── fill_rows: 확인 불가(warn)를 삼키지 않는다 ───────────────────────────────
@pytest.mark.asyncio
async def test_fill_rows_surfaces_unverified_fields(monkeypatch):
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)

    async def _note_unverified(page, text):
        calls.append("set_row_note")
        notes.append(text)
        return {"ok": True, "warn": "적요(NOTE_DC) 확인 불가(기대 '학자금-홍길동' / 실제 None…)"}

    monkeypatch.setattr(fill.steps, "set_row_note", _note_unverified)
    node = make_fill_rows_node()
    state = _fill_state()
    out = await node(state)
    assert out["filled"] == 1
    assert out["fill_warnings"] == ["적요"]
    assert_keys_declared(HakjagumGrantState, out)
    logs = [e for e in _drain(state["events"]) if "log" in e]
    # 미확인이 있으면 완료라고 단정하지 않는다 — 마무리 로그가 warn 이고 미확인 필드를 명시한다.
    final = logs[-1]
    assert final["level"] == "warn" and "미확인" in final["log"] and "완료" not in final["log"]


@pytest.mark.asyncio
async def test_fill_rows_surfaces_warns_from_evdn_partner_project(monkeypatch):
    # 회귀(2026-08-07 감사): note_warn 이 예산단위·적요에만 붙어 있어 증빙 열기(스테일 팝업)·
    # 증빙유형(팝업 미닫힘)·거래처·프로젝트({ok:True, warn})의 warn 이 조용히 버려졌다 —
    # '학자금 반영 완료'(ok) 로그와 fill_warnings 가 거짓이 되는 자체 불변식 위반(경조금 동형).
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)

    def _warned(name, extra=None, warn=""):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, "warn": warn, **(extra or {})}

        return _f

    monkeypatch.setattr(
        fill.doc_steps,
        "open_evdn_editor",
        _warned("open_evdn", {"shown": {}}, warn="증빙유형 팝업이 이미 열린 상태에서 시작 — 스테일 팝업 가능"),
    )
    monkeypatch.setattr(
        fill.doc_steps,
        "select_evdn_code",
        _warned("select_evdn", {"name": "규정에의한 비용정산", "code": "10"}, warn="증빙유형 팝업 닫힘 확인 불가"),
    )
    monkeypatch.setattr(
        fill.steps,
        "fill_partner_by_search",
        _warned("fill_partner_by_search", {"name": "홍길동"}, warn="거래처(PARTNER) 확인 불가"),
    )
    monkeypatch.setattr(
        fill.steps, "fill_project", _warned("fill_project", warn="프로젝트(PJT_NM) 확인 불가")
    )
    node = make_fill_rows_node()
    state = _fill_state()
    out = await node(state)
    assert out["filled"] == 1
    # 네 스텝의 warn 이 전부 fill_warnings 에 실린다(호출 순서 그대로).
    assert out["fill_warnings"] == ["증빙 열기", "증빙유형(10)", "거래처", "프로젝트"]
    assert_keys_declared(HakjagumGrantState, out)
    logs = [e for e in _drain(state["events"]) if "log" in e]
    final = logs[-1]
    assert final["level"] == "warn" and "미확인" in final["log"] and "완료" not in final["log"]
    # 각 warn 은 개별 warn 로그로도 방출된다.
    warn_logs = [e["log"] for e in logs if e.get("level") == "warn"]
    assert any("증빙 열기" in w for w in warn_logs)
    assert any("거래처" in w for w in warn_logs)
