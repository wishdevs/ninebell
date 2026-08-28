"""옴니솔 ERP HTTP API 클라이언트 — 코드 카탈로그(예산단위·프로젝트·거래처) 순수 HTTP 수집.

브라우저 없이 로그인(``POST /api/CM/AccountService/login``)으로 ``access_token``(HS256 JWT)을 받고,
``x-authenticate-token`` 헤더로 코드도움 서비스(H_*_list) XHR 을 직접 호출한다. 반환 행은
``card_collect``/``trip_domestic`` 의 ``dump_*`` 와 **동일한 형태**라 ``code_sync`` 의 upsert 를
그대로 재사용한다(예산단위·프로젝트 매퍼는 여기 로컬 재구현, 거래처는 trip_domestic 의
``partner_options_to_rows`` 를 지연 import — 순환 import 회피).

⚠ **읽기 전용** — 로그인 + GET 조회만 수행한다. 저장/상신/쓰기는 이 경로에 없다. 실측 근거는
``backend/e2e/api_discovery_http_repro.py`` 프로브(2026-08-28). 자동화·쓰기 흐름은 여전히
브라우저(Playwright) 전용이며, 이 HTTP 경로는 사용자 승인(2026-08-28) 아래 **읽기전용 마스터
수집**에 한정한다(nbkit/OMNISOL_NOTES.md 원칙 예외).
"""

from __future__ import annotations

import datetime as _dt
import logging

import httpx

from app.config import get_settings
from app.core.http_client import new_async_client

logger = logging.getLogger(__name__)

# 코드도움 서비스 경로(프로브 실측). 앞의 base(erp_base)는 호출 시 붙인다.
_LOGIN_PATH = "/api/CM/AccountService/login"
_USERINFO_PATH = "/api/CM/UserInfoService/info"  # 로그인 사용자 부서코드(dept_cd) 원천.
_BUDGET_PATH = "/api/FI/FICustomCodeHelpService/H_FI_BG_BP_BA_C_list"
_PROJECT_PATH = "/api/PS/PSCustomCodeHelpService/H_PS_WBS_MST_C_search_list"
_PARTNER_PATH = "/api/MA/MACustomCodeHelpService/MA_PARTNERE_MST_C_list"

# 결의구분 '카드' 코드(app/agents/voucher_card/steps.py 주석과 일치). 예산단위 목록의 문맥 값.
_ABDOCU_FG_CARD = "52"
# 페이징 1회 요청 크기. 서버는 pagingCount 를 강제 상한 없이 그대로 처리한다(500 캡은 UI 값일
# 뿐, 프로브 F). 넉넉히 잡아 대부분 1회에 끝내되, total 미달이면 pagingStart 로 이어 받는다.
_PAGE_SIZE = 5000
# 페이징 안전 상한(무한 루프 방지) — 5000×40 = 20만 행까지.
_MAX_PAGES = 40

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class ErpApiError(RuntimeError):
    """ERP HTTP API 호출 실패 — 이 예외를 폴백(브라우저 경로) 신호로 쓴다."""


def _base() -> str:
    return get_settings().erp_base.rstrip("/")


def _login_headers(base: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "user-agent": _UA,
        "x-requested-with": "XMLHttpRequest",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": base,
        "referer": f"{base}/",
    }


def _data_headers(base: str, token: str) -> dict[str, str]:
    """코드도움 XHR 인증 헤더. 실인증은 x-authenticate-token(access_token) 하나면 되고(프로브 E:
    토큰만 빼면 401), x-grant-*/x-requested-pageid 는 브라우저와 동일하게 실어 무해하게 둔다."""
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "user-agent": _UA,
        "x-requested-with": "XMLHttpRequest",
        "referer": f"{base}/FI/GLDDOC00300",
        "x-authenticate-token": token,
        "x-grant-authority": "C",
        "x-grant-date": "null",
        "x-grant-signature": "null",
        "x-requested-pageid": "GLDDOC00300",
    }


async def login(client: httpx.AsyncClient, userid: str, password: str) -> str:
    """로그인 POST → access_token(JWT) 반환. 실패 시 ErpApiError.

    콜드 클라이언트로 바로 호출 가능(사전 GET/쿠키 워밍 불필요, 프로브 A). 비밀번호는 평문
    form-urlencoded 로 전송된다(클라이언트 암호화 없음 — 프로브 확인). TLS(https)로 보호된다.
    """
    base = _base()
    try:
        r = await client.post(
            f"{base}{_LOGIN_PATH}",
            data={"userid": userid, "password": password, "type": "main"},
            headers=_login_headers(base),
        )
    except httpx.HTTPError as exc:
        raise ErpApiError(f"ERP 로그인 요청 실패: {exc}") from exc
    if r.status_code != 200:
        raise ErpApiError(f"ERP 로그인 HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError as exc:
        raise ErpApiError("ERP 로그인 응답이 JSON 이 아닙니다") from exc
    if not (isinstance(body, dict) and body.get("state") == "success"):
        # 자격증명 오류 등 — state/message 를 그대로 노출(비밀번호는 포함 안 됨).
        raise ErpApiError(f"ERP 로그인 거부: {body.get('message') or body.get('state')}")
    token = ((body.get("data") or {}) if isinstance(body.get("data"), dict) else {}).get("access_token")
    if not token:
        raise ErpApiError("ERP 로그인 응답에 access_token 이 없습니다")
    return token


async def _get_list(client: httpx.AsyncClient, base: str, token: str, path: str, params: dict) -> dict:
    """코드도움 GET → JSON. state!=success 또는 비-JSON 이면 ErpApiError(폴백 신호)."""
    try:
        r = await client.get(f"{base}{path}", params=params, headers=_data_headers(base, token))
    except httpx.HTTPError as exc:
        raise ErpApiError(f"ERP 조회 요청 실패({path}): {exc}") from exc
    if r.status_code != 200:
        raise ErpApiError(f"ERP 조회 HTTP {r.status_code}({path})")
    try:
        body = r.json()
    except ValueError as exc:
        raise ErpApiError(f"ERP 조회 응답이 JSON 이 아닙니다({path})") from exc
    if not (isinstance(body, dict) and body.get("state") == "success"):
        raise ErpApiError(f"ERP 조회 실패({path}): {body.get('message') or body.get('state')}")
    return body


def _budget_options_to_rows(options: list[dict]) -> list[dict]:
    """예산단위 API 행(BG_*/BIZPLAN_*/BGACCT_*) → 카탈로그 행. dump_budget_units 와 동일 shape.

    선택 단위는 (BG × 사업계획 × 예산계정) 조합 행이라 code=BG_CD|BIZPLAN_CD|BGACCT_CD 복합.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for o in options:
        bg = o.get("BG_CD")
        if not bg:
            continue
        code = f"{bg}|{o.get('BIZPLAN_CD') or ''}|{o.get('BGACCT_CD') or ''}"
        if code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "code": code,
                "name": o.get("BG_NM") or "",
                "bizplanCd": o.get("BIZPLAN_CD") or "",
                "bizplanNm": o.get("BIZPLAN_NM") or "",
                "bgacctCd": o.get("BGACCT_CD") or "",
                "bgacctNm": o.get("BGACCT_NM") or "",
            }
        )
    return out


def _project_options_to_rows(options: list[dict]) -> list[dict]:
    """프로젝트 API 행(PJT_*/WBS_*) → 카탈로그 행. dump_projects 의 _dedupe_projects 와 동일 규칙."""
    seen: set[str] = set()
    out: list[dict] = []
    for o in options:
        pjt = o.get("PJT_NO")
        if not pjt:
            continue
        wbs = o.get("WBS_NO") or ""
        code = f"{pjt}|{wbs}"
        if code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "code": code,
                "name": o.get("PJT_NM") or "",
                "pjtNo": pjt,
                "wbsNo": wbs,
                "wbsNm": o.get("VIEW_WBS_NM") or o.get("WBS_NM") or "",
                "loc": o.get("WBS_LOC") or "",
                "useYn": o.get("USE_YN") or "",
                "partnerNm": o.get("PARTNER_NM") or "",
            }
        )
    return out


async def fetch_user_dept_code(client: httpx.AsyncClient, token: str) -> str:
    """로그인 사용자의 부서코드(dept_cd) — UserInfoService/info 의 첫 회사·첫 부서 deptCode.

    예산단위 조회는 dept_cd 가 **필수**다(빈값=0행, 실측). access_token(JWT)에는 deptCode 가
    없어(claim: companyCode/userid/authToken…) 이 엔드포인트로 따로 받는다. 못 구하면
    ErpApiError 를 올려 호출부가 브라우저 폴백을 태우게 한다(조용한 0행 방지)."""
    base = _base()
    try:
        r = await client.get(f"{base}{_USERINFO_PATH}", headers=_data_headers(base, token))
    except httpx.HTTPError as exc:
        raise ErpApiError(f"사용자 정보 조회 실패: {exc}") from exc
    if r.status_code != 200:
        raise ErpApiError(f"사용자 정보 HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError as exc:
        raise ErpApiError("사용자 정보 응답이 JSON 이 아닙니다") from exc
    data = body.get("data") if isinstance(body, dict) else None
    companies = (data or {}).get("companies") if isinstance(data, dict) else None
    if isinstance(companies, list) and companies and isinstance(companies[0], dict):
        depts = companies[0].get("depts")
        if isinstance(depts, list) and depts and isinstance(depts[0], dict):
            code = str(depts[0].get("deptCode") or "")
            if code:
                return code
    raise ErpApiError("사용자 정보에서 deptCode 를 찾지 못했습니다")


async def fetch_budget_units(client: httpx.AsyncClient, token: str) -> list[dict]:
    """예산단위(bg_cd) 전량. dept_cd 는 로그인 사용자 부서코드(UserInfoService)로 채운다.

    ERP 예산단위 코드도움은 전사 목록을 반환하지만 dept_cd 는 필수 파라미터라(빈값=0행, 실측),
    로그인 사용자의 실 부서코드를 넣어 브라우저 경로와 동일 결과(전사 2,282건)를 얻는다.
    페이징 없음(항상 전량).
    """
    base = _base()
    dept_cd = await fetch_user_dept_code(client, token)
    today = _dt.date.today().strftime("%Y%m%d")
    body = await _get_list(
        client,
        base,
        token,
        _BUDGET_PATH,
        {"abdocu_fg_cd": _ABDOCU_FG_CARD, "dept_cd": dept_cd, "keyword": "", "end_dt": today},
    )
    data = body.get("data")
    return _budget_options_to_rows(data if isinstance(data, list) else [])


async def _fetch_paged(
    client: httpx.AsyncClient, base: str, token: str, path: str, base_params: dict, label: str
) -> list[dict]:
    """paging=true 계열 전량 수집 — pagingStart 를 밀며 total 도달/부분 페이지까지 누적."""
    options: list[dict] = []
    total: int | None = None
    for page in range(_MAX_PAGES):
        params = {**base_params, "paging": "true", "pagingStart": page * _PAGE_SIZE, "pagingCount": _PAGE_SIZE}
        body = await _get_list(client, base, token, path, params)
        if total is None:
            try:
                total = int(body.get("total") or 0)
            except (TypeError, ValueError):
                total = None
        data = body.get("data")
        chunk = data if isinstance(data, list) else []
        options.extend(chunk)
        # 마지막 페이지 판정 — 부분 페이지거나(=더 없음) total 도달.
        if len(chunk) < _PAGE_SIZE or (total is not None and len(options) >= total):
            break
    else:
        logger.warning("%s 페이징 안전상한(%d페이지) 도달 — 일부 누락 가능", label, _MAX_PAGES)
    if total is not None and len(options) < total:
        logger.warning("%s 수집 %d행 < 응답 total %d — 미완결 가능", label, len(options), total)
    return options


async def fetch_projects(client: httpx.AsyncClient, token: str) -> list[dict]:
    """프로젝트/WBS(pjt_cd) 전량. pjt_no 는 빈 문자열 필수(존재하지 않는 값=서버 에러, 프로브 H)."""
    base = _base()
    params = {
        "pjt_no": "", "pc_cd": "", "plan_element_yn": "", "acct_altm_element_yn": "",
        "bill_element_yn": "", "pjt_auth_yn": "", "pjt_type_cd": "", "keyword": "",
        "use_yn": "Y", "lv_sq": "", "tlnd_yn": "N", "wbs_st": "", "stl_object_fg": "",
        "partner_cd": "", "start_dt": "", "end_dt": "",
    }
    options = await _fetch_paged(client, base, token, _PROJECT_PATH, params, "프로젝트")
    return _project_options_to_rows(options)


async def fetch_partners(client: httpx.AsyncClient, token: str) -> list[dict]:
    """거래처(partner_cd) 전량. 반환 [{code, name, bizNo}](trip_domestic.partner_options_to_rows).

    partner_options_to_rows 는 함수 안에서 지연 import 한다 — 모듈 top 에서 app.agents 를 끌면
    code_sync↔api_client↔agents 순환 import 가 생긴다(card_collect.nodes.collect 가 code_sync 를
    다시 참조). code_sync 가 이미 dump_partners 를 같은 이유로 지연 import 한다.
    """
    from app.agents.trip_domestic.steps import partner_options_to_rows

    base = _base()
    params = {
        "company_cd": "", "partner_fg_cd": "", "partner_csf_cd": "", "keyword": "",
        "use_yn": "", "bizr_no_required": "", "search_fg": "", "biz_cond_fg": "",
        "pc_cd": "", "reqn_yn": "", "partner_grp_cd": "", "partner_grp2_cd": "",
        "selected_partner": "",
    }
    options = await _fetch_paged(client, base, token, _PARTNER_PATH, params, "거래처")
    return partner_options_to_rows(options)


_FETCHERS = {
    "budget_unit": fetch_budget_units,
    "project": fetch_projects,
    "partner": fetch_partners,
}

# 이 클라이언트가 HTTP 로 커버하는 kind — org_unit 은 제외(브라우저 스크레이프 전용).
API_KINDS = frozenset(_FETCHERS)


async def fetch_catalog_rows(kind: str, userid: str, password: str) -> list[dict]:
    """kind('budget_unit'|'project'|'partner') 카탈로그 행을 순수 HTTP 로 수집.

    로그인(1회) → 해당 fetcher 1회 호출. 반환 행은 dump_* 와 동일 shape 라 code_sync upsert 가
    그대로 소비한다. 실패는 ErpApiError 로 올려 호출부가 브라우저 폴백을 태우게 한다.
    """
    fetcher = _FETCHERS.get(kind)
    if fetcher is None:
        raise ErpApiError(f"API 미지원 kind: {kind}")
    async with new_async_client(timeout=httpx.Timeout(30.0)) as client:
        token = await login(client, userid, password)
        rows = await fetcher(client, token)
    logger.info("ERP API 수집 kind=%s → %d행", kind, len(rows))
    return rows
