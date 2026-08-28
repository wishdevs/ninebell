"""ERP 순수 HTTP 재현 프로브 — api_discovery_probe.py 캡처로 확정한 로그인/피커 엔드포인트를
httpx 로 재현해 "브라우저 없이 HTTP 만으로" 다룰 수 있는지 판정한다.

실험 목록:
  A. 콜드 로그인(사전 GET 없이 바로 로그인 POST)
  B. 웜 로그인(먼저 '/' GET → 로그인 POST) — 기준선
  C. B 의 쿠키+토큰으로 3종 피커 XHR 직접 호출(로그인 직후, user_type/menu_nav 없음)
  D. **쿠키 없이** 토큰 헤더만으로 3종 피커 XHR 호출 — 쿠키 필요 여부 판정
  E. **토큰 헤더 없이** 쿠키만으로 3종 피커 XHR 호출 — 쿠키가 곧 인증인지 판정
  F. 프로젝트 피커 pagingCount 확대(5000) — 500행 캡을 서버 쿼리로 돌파 가능한지
  G. 프로젝트/거래처 전 페이지 순회 합계 vs 응답 total 필드 일치 확인
  H. pjt_no 파라미터를 빈 값/임의 UUID 로 바꿔도 결과가 같은지(필터가 아니라 논스인지)

⚠ 읽기 전용 — 로그인(POST)과 조회(GET)만 수행. 저장/상신/보관 절대 금지.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/api_discovery_http_repro.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

import httpx  # noqa: E402
import json  # noqa: E402

from app.config import get_settings  # noqa: E402

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(errors="ignore").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

USERID = os.environ.get("E2E_USERID") or ""
PASSWORD = os.environ.get("E2E_PASSWORD") or ""

OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(exist_ok=True)
OUT_PATH = OUT_DIR / "api_discovery_http_repro.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "user-agent": UA,
    "x-requested-with": "XMLHttpRequest",
}


def login(client: httpx.Client, base: str, *, warm: bool) -> dict:
    """로그인 POST 재현. warm=True 면 먼저 '/' 를 GET 해 세션 쿠키를 확보한다."""
    result: dict[str, Any] = {"warm": warm}
    if warm:
        r0 = client.get(f"{base}/", headers={"user-agent": UA})
        result["warmStatus"] = r0.status_code
        result["cookiesAfterWarm"] = dict(client.cookies)
    r = client.post(
        f"{base}/api/CM/AccountService/login",
        data={"userid": USERID, "password": PASSWORD, "type": "main"},
        headers={
            **BASE_HEADERS,
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "origin": base,
            "referer": f"{base}/",
        },
    )
    result["status"] = r.status_code
    result["cookiesAfterLogin"] = dict(client.cookies)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {"_raw": r.text[:500]}
    result["body"] = body
    token = None
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        token = body["data"].get("access_token")
    result["token"] = token
    return result


def call_api(
    client: httpx.Client,
    base: str,
    path_and_query: str,
    *,
    token: str | None,
    use_token: bool,
) -> dict:
    headers = dict(BASE_HEADERS)
    headers["referer"] = f"{base}/FI/GLDDOC00300"
    if use_token and token:
        headers["x-authenticate-token"] = token
        headers["x-grant-authority"] = "C"
        headers["x-grant-date"] = "null"
        headers["x-grant-signature"] = "null"
        headers["x-requested-pageid"] = "GLDDOC00300"
    r = client.get(f"{base}{path_and_query}", headers=headers)
    out: dict[str, Any] = {"url": path_and_query, "status": r.status_code, "useToken": use_token}
    try:
        body = r.json()
    except Exception as exc:  # noqa: BLE001
        out["parseError"] = str(exc)
        out["bodyHead"] = r.text[:300]
        return out
    if isinstance(body, dict):
        out["state"] = body.get("state")
        out["total"] = body.get("total")
        out["current"] = body.get("current")
        data = body.get("data")
        if isinstance(data, list):
            out["dataLen"] = len(data)
            out["sample"] = data[0] if data else None
        elif isinstance(data, dict):
            out["dataKeys"] = list(data.keys())
        else:
            out["dataRepr"] = str(data)[:200]
    return out


def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 를 .env 에 채우고 실행하세요.", file=sys.stderr)
        return 2
    base = get_settings().erp_base
    today = __import__("datetime").date.today().strftime("%Y%m%d")
    dept_cd = "2006"  # 실측 캡처의 로그인 계정(이트라이브2) 소속 부서코드 — JWT deptCode 클레임과 일치.

    results: dict[str, Any] = {"base": base, "userid": USERID}

    # ── A. 콜드 로그인(사전 GET 없이) ────────────────────────────────────────────
    with httpx.Client(timeout=20) as c_cold:
        results["A_cold_login"] = login(c_cold, base, warm=False)
    print(f"[A] 콜드 로그인 status={results['A_cold_login']['status']} "
          f"token={'있음' if results['A_cold_login']['token'] else '없음'}")

    # ── B. 웜 로그인(기준선) ────────────────────────────────────────────────────
    client = httpx.Client(timeout=20)
    results["B_warm_login"] = login(client, base, warm=True)
    token = results["B_warm_login"]["token"]
    print(f"[B] 웜 로그인 status={results['B_warm_login']['status']} "
          f"token={'있음' if token else '없음'}")
    if not token:
        print("로그인 토큰을 얻지 못해 이후 실험을 중단합니다.", file=sys.stderr)
        OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return 1

    endpoints = {
        "budget": f"/api/FI/FICustomCodeHelpService/H_FI_BG_BP_BA_C_list"
        f"?abdocu_fg_cd=52&dept_cd={dept_cd}&keyword=&end_dt={today}",
        "project": "/api/PS/PSCustomCodeHelpService/H_PS_WBS_MST_C_search_list"
        "?pjt_no=&pc_cd=&plan_element_yn=&acct_altm_element_yn=&bill_element_yn="
        "&pjt_auth_yn=&pjt_type_cd=&keyword=&use_yn=Y&lv_sq=&tlnd_yn=N&wbs_st="
        "&stl_object_fg=&partner_cd=&start_dt=&end_dt=&paging=true&pagingStart=0&pagingCount=500",
        "partner": "/api/MA/MACustomCodeHelpService/MA_PARTNERE_MST_C_list"
        "?company_cd=&partner_fg_cd=&partner_csf_cd=&keyword=&use_yn=&bizr_no_required="
        "&search_fg=&biz_cond_fg=&pc_cd=&reqn_yn=&partner_grp_cd=&partner_grp2_cd="
        "&selected_partner=&paging=true&pagingStart=0&pagingCount=500",
    }

    # ── C. 로그인 직후(user_type/menu_nav 없음) 쿠키+토큰으로 3종 호출 ─────────────
    results["C_direct_after_login"] = {
        name: call_api(client, base, url, token=token, use_token=True) for name, url in endpoints.items()
    }
    for name, r in results["C_direct_after_login"].items():
        print(f"[C] {name}: status={r['status']} dataLen={r.get('dataLen')} total={r.get('total')}")

    # ── D. 쿠키 없이 토큰 헤더만 ─────────────────────────────────────────────────
    with httpx.Client(timeout=20) as c_no_cookie:
        results["D_token_only_no_cookies"] = {
            name: call_api(c_no_cookie, base, url, token=token, use_token=True)
            for name, url in endpoints.items()
        }
    for name, r in results["D_token_only_no_cookies"].items():
        print(f"[D] {name}(쿠키 없음): status={r['status']} dataLen={r.get('dataLen')}")

    # ── E. 토큰 헤더 없이 쿠키만 ─────────────────────────────────────────────────
    results["E_cookies_only_no_token"] = {
        name: call_api(client, base, url, token=token, use_token=False) for name, url in endpoints.items()
    }
    for name, r in results["E_cookies_only_no_token"].items():
        print(f"[E] {name}(토큰 없음): status={r['status']} dataLen={r.get('dataLen')}")

    # ── F. 프로젝트 피커 pagingCount 확대(5000) — 500행 캡 서버 쿼리 돌파 ──────────
    big_url = endpoints["project"].replace("pagingCount=500", "pagingCount=5000")
    results["F_paging_bypass_pagingCount"] = call_api(client, base, big_url, token=token, use_token=True)
    r = results["F_paging_bypass_pagingCount"]
    print(f"[F] pagingCount=5000 → dataLen={r.get('dataLen')} total={r.get('total')}")

    # ── G. 전 페이지 순회 합계 vs total 필드 ─────────────────────────────────────
    def paginate_all(url_tmpl: str, total_hint: int) -> int:
        seen = 0
        start = 0
        page_size = 500
        while True:
            u = url_tmpl.replace("pagingStart=0", f"pagingStart={start}").replace(
                "pagingCount=500", f"pagingCount={page_size}"
            )
            r = call_api(client, base, u, token=token, use_token=True)
            n = r.get("dataLen") or 0
            seen += n
            if n < page_size or seen >= total_hint or n == 0:
                break
            start += page_size
        return seen

    proj_total = int(results["C_direct_after_login"]["project"].get("total") or 0)
    partner_total = int(results["C_direct_after_login"]["partner"].get("total") or 0)
    results["G_paginate_all"] = {
        "project": {"totalField": proj_total, "summed": paginate_all(endpoints["project"], proj_total)},
        "partner": {"totalField": partner_total, "summed": paginate_all(endpoints["partner"], partner_total)},
    }
    print(f"[G] project total={proj_total} summed={results['G_paginate_all']['project']['summed']}")
    print(f"[G] partner total={partner_total} summed={results['G_paginate_all']['partner']['summed']}")

    # ── H. pjt_no 를 빈 값/임의 UUID 로 바꿔도 결과가 같은가(필터 아닌 논스 가설) ──
    empty_pjt = call_api(client, base, endpoints["project"], token=token, use_token=True)
    random_pjt_url = endpoints["project"].replace("pjt_no=", f"pjt_no={uuid.uuid4().hex}")
    random_pjt = call_api(client, base, random_pjt_url, token=token, use_token=True)
    results["H_pjt_no_nonce_check"] = {"empty": empty_pjt, "random_uuid": random_pjt}
    print(
        f"[H] pjt_no 빈값 dataLen={empty_pjt.get('dataLen')} total={empty_pjt.get('total')} vs "
        f"임의UUID dataLen={random_pjt.get('dataLen')} total={random_pjt.get('total')}"
    )

    client.close()
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\n저장: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
