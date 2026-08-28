"""app.erp.api_client 단위 테스트 — httpx.MockTransport 로 ERP 응답을 가짜로 주입.

실 ERP 없이 로그인·조회·매핑·페이징·에러(폴백 신호)를 검증한다. 엔드포인트/파라미터/헤더의
실측 근거는 backend/e2e/api_discovery_http_repro.py.
"""

from __future__ import annotations

import httpx
import pytest

from app.erp import api_client
from app.erp.api_client import ErpApiError

# 토큰은 서버가 발급하는 불투명 문자열로만 쓰인다(클라이언트가 payload 를 해석하지 않음).
_TOK = "opaque-access-token"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)


def _userinfo_response(dept_code: str = "2006") -> httpx.Response:
    return httpx.Response(
        200,
        json={"state": "success", "data": {"companies": [{"depts": [{"deptCode": dept_code, "deptName": "인사/기획팀"}]}]}},
    )


# ── 순수 매퍼 ────────────────────────────────────────────────────────────────
def test_budget_mapper_composes_code_and_dedupes():
    rows = api_client._budget_options_to_rows(
        [
            {"BG_CD": "B1", "BG_NM": "인사기획팀", "BIZPLAN_CD": "P1", "BIZPLAN_NM": "계획", "BGACCT_CD": "A1", "BGACCT_NM": "여비"},
            {"BG_CD": "B1", "BG_NM": "인사기획팀", "BIZPLAN_CD": "P1", "BGACCT_CD": "A1"},  # 중복 code → 무시
            {"BG_NM": "코드없음"},  # BG_CD 없음 → 무시
        ]
    )
    assert len(rows) == 1
    assert rows[0]["code"] == "B1|P1|A1"
    assert rows[0]["name"] == "인사기획팀"
    assert rows[0]["bgacctNm"] == "여비"


def test_project_mapper_uses_view_wbs_and_composite_code():
    rows = api_client._project_options_to_rows(
        [
            {"PJT_NO": "500", "PJT_NM": "프로젝트A", "WBS_NO": "10", "VIEW_WBS_NM": "표시명", "WBS_NM": "원명", "USE_YN": "Y"},
            {"PJT_NO": "500", "PJT_NM": "프로젝트A", "WBS_NO": "10"},  # 중복 → 무시
            {"WBS_NO": "99"},  # PJT_NO 없음 → 무시
        ]
    )
    assert len(rows) == 1
    assert rows[0]["code"] == "500|10"
    assert rows[0]["wbsNm"] == "표시명"  # VIEW_WBS_NM 우선


# ── login ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_login_success_returns_token():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/CM/AccountService/login"
        body = req.content.decode()
        assert "userid=svc" in body and "password=secret" in body and "type=main" in body
        return httpx.Response(200, json={"state": "success", "data": {"access_token": "TOK"}})

    async with _client(handler) as c:
        assert await api_client.login(c, "svc", "secret") == "TOK"


@pytest.mark.asyncio
async def test_login_rejected_raises():
    def handler(req):
        return httpx.Response(200, json={"state": "fail", "message": "비밀번호 오류"})

    async with _client(handler) as c:
        with pytest.raises(ErpApiError, match="비밀번호 오류"):
            await api_client.login(c, "svc", "bad")


@pytest.mark.asyncio
async def test_login_http_error_raises():
    def handler(req):
        return httpx.Response(500, text="oops")

    async with _client(handler) as c:
        with pytest.raises(ErpApiError, match="HTTP 500"):
            await api_client.login(c, "svc", "secret")


# ── fetchers ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_fetch_user_dept_code_reads_first_dept():
    async with _client(lambda req: _userinfo_response("2006")) as c:
        assert await api_client.fetch_user_dept_code(c, _TOK) == "2006"


@pytest.mark.asyncio
async def test_fetch_user_dept_code_missing_raises():
    def handler(req):
        return httpx.Response(200, json={"state": "success", "data": {"companies": []}})

    async with _client(handler) as c:
        with pytest.raises(ErpApiError, match="deptCode"):
            await api_client.fetch_user_dept_code(c, _TOK)


@pytest.mark.asyncio
async def test_fetch_budget_units_resolves_deptcode_and_maps():
    seen = {}

    def handler(req):
        if req.url.path.endswith("/UserInfoService/info"):
            return _userinfo_response("2006")
        seen["dept_cd"] = req.url.params.get("dept_cd")
        seen["abdocu"] = req.url.params.get("abdocu_fg_cd")
        seen["auth"] = req.headers.get("x-authenticate-token")
        return httpx.Response(200, json={"state": "success", "data": [
            {"BG_CD": "B1", "BG_NM": "팀", "BIZPLAN_CD": "P", "BGACCT_CD": "A"}]})

    async with _client(handler) as c:
        rows = await api_client.fetch_budget_units(c, _TOK)
    assert rows[0]["code"] == "B1|P|A"
    assert seen["dept_cd"] == "2006"  # UserInfoService 의 deptCode 가 dept_cd 로 실린다
    assert seen["abdocu"] == "52"  # 결의구분 '카드'
    assert seen["auth"] == _TOK


@pytest.mark.asyncio
async def test_fetch_budget_units_no_dept_raises():
    """dept_cd 를 못 구하면 조용한 0행 대신 ErpApiError(→브라우저 폴백)."""
    def handler(req):
        if req.url.path.endswith("/UserInfoService/info"):
            return httpx.Response(200, json={"state": "success", "data": {"companies": []}})
        raise AssertionError("dept_cd 없으면 예산 조회로 진행하면 안 됨")

    async with _client(handler) as c:
        with pytest.raises(ErpApiError):
            await api_client.fetch_budget_units(c, _TOK)


@pytest.mark.asyncio
async def test_fetch_projects_paginates(monkeypatch):
    monkeypatch.setattr(api_client, "_PAGE_SIZE", 2)  # 작은 페이지로 페이징 루프 강제
    pages = {
        0: [{"PJT_NO": "1", "PJT_NM": "a", "WBS_NO": "x"}, {"PJT_NO": "2", "PJT_NM": "b", "WBS_NO": "y"}],
        2: [{"PJT_NO": "3", "PJT_NM": "c", "WBS_NO": "z"}],  # 부분 페이지 → 종료
    }

    def handler(req):
        assert req.url.params.get("pjt_no") == ""  # 전량 수집 필수 조건
        start = int(req.url.params.get("pagingStart"))
        return httpx.Response(200, json={"state": "success", "total": "3", "data": pages.get(start, [])})

    async with _client(handler) as c:
        rows = await api_client.fetch_projects(c, _TOK)
    assert {r["code"] for r in rows} == {"1|x", "2|y", "3|z"}


@pytest.mark.asyncio
async def test_fetch_partners_maps_bizno():
    def handler(req):
        return httpx.Response(200, json={"state": "success", "total": "1", "data": [
            {"PARTNER_CD": "C1", "PARTNER_NM": "거래처", "BIZR_NO": "123-45-67890"}]})

    async with _client(handler) as c:
        rows = await api_client.fetch_partners(c, _TOK)
    assert rows == [{"code": "C1", "name": "거래처", "bizNo": "123-45-67890"}]


@pytest.mark.asyncio
async def test_get_list_non_success_raises():
    def handler(req):
        return httpx.Response(200, json={"state": "error", "message": "요청한 파일을 찾을 수 없습니다."})

    async with _client(handler) as c:
        with pytest.raises(ErpApiError, match="찾을 수 없습니다"):
            await api_client.fetch_partners(c, _TOK)


@pytest.mark.asyncio
async def test_fetch_catalog_rows_logs_in_then_fetches(monkeypatch):
    """login → fetcher 통합. new_async_client 를 MockTransport 로 갈아끼운다."""
    def handler(req):
        if req.url.path.endswith("/login"):
            return httpx.Response(200, json={"state": "success", "data": {"access_token": _TOK}})
        return httpx.Response(200, json={"state": "success", "total": "1", "data": [
            {"PARTNER_CD": "C1", "PARTNER_NM": "거래처", "BIZR_NO": "1"}]})

    monkeypatch.setattr(api_client, "new_async_client", lambda **kw: _client(handler))
    rows = await api_client.fetch_catalog_rows("partner", "svc", "secret")
    assert rows == [{"code": "C1", "name": "거래처", "bizNo": "1"}]


@pytest.mark.asyncio
async def test_fetch_catalog_rows_unknown_kind_raises():
    with pytest.raises(ErpApiError, match="미지원 kind"):
        await api_client.fetch_catalog_rows("org_unit", "svc", "secret")
