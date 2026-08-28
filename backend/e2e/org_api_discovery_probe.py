"""조직도(org_unit) 순수 HTTP 소스 실측 캡처 — 읽기전용.

배경: 현행 org_sync.py 는 랜딩 우상단 '조직도' 클릭 → Kendo TreeView(#organizationTreeView)를
DOM 에서 전량 스크레이프한다(2026-07-09 프로브 관찰: "전체 트리가 DOM 에 이미 있음(XHR 아님)").
이 프로브는 그 관찰이 오늘도 유효한지 재확인하고, 혹시 있을 XHR/임베디드 JSON 소스를 찾는다.

절차: 로그인(goto 이전부터 request/response 훅) → 랜딩 정착 → 랜딩 HTML 스냅샷(서버렌더/임베디드
스크립트 확인용) → '조직도' 클릭(org_sync._open_org_chart 재사용) → 트리 렌더 후 재캡처 →
FULL_TREE_JS 로 DOM 트리 덤프(파리티 확인용, org_sync.py 재사용).

⚠ 읽기 전용 — 로그인·클릭·조회만. 저장/상신/보관 절대 금지.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/org_api_discovery_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Response, async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.org_sync import FULL_TREE_JS, _open_org_chart  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

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
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(exist_ok=True)
CAPTURE_PATH = OUT_DIR / "org_api_discovery_capture.json"

# api_discovery_probe.py 와 동일 관례 — document/xhr/fetch 만 캡처, 1MB 초과는 앞 200KB.
RESOURCE_TYPES = {"document", "xhr", "fetch"}
BODY_CAP_BYTES = 1_000_000
BODY_HEAD_BYTES = 200_000

# 조직/부서/트리 관련 후보 키워드 — 정적 리소스(script/img 등)라도 URL 에 이 단어가 있으면
# 캡처 대상에 포함시킨다(위 3종 리소스타입 필터를 우회해서라도 놓치지 않기 위함).
ORG_URL_KEYWORDS = ("org", "dept", "chart", "employee", "empl", "hr", "team", "sprite", "tree")


class Capture:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.phase = "init"
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


async def _on_response(resp: Response, cap: Capture) -> None:
    req = resp.request
    url_low = req.url.lower()
    is_target_type = req.resource_type in RESOURCE_TYPES
    is_org_keyword = any(k in url_low for k in ORG_URL_KEYWORDS)
    if not (is_target_type or is_org_keyword):
        return
    entry: dict[str, Any] = {
        "seq": cap.next_seq(),
        "phase": cap.phase,
        "ts": time.time(),
        "url": req.url,
        "method": req.method,
        "resourceType": req.resource_type,
        "status": resp.status,
    }
    try:
        entry["requestHeaders"] = await req.all_headers()
    except Exception as exc:  # noqa: BLE001
        entry["requestHeadersError"] = str(exc)
    try:
        entry["postData"] = req.post_data
    except Exception:  # noqa: BLE001
        entry["postData"] = None
    try:
        buf = await resp.body()
        raw_len = len(buf)
        entry["bodyLen"] = raw_len
        if raw_len > BODY_CAP_BYTES:
            entry["body"] = buf[:BODY_HEAD_BYTES].decode("utf-8", errors="replace")
            entry["bodyTruncated"] = True
        else:
            entry["body"] = buf.decode("utf-8", errors="replace")
            entry["bodyTruncated"] = False
    except Exception as exc:  # noqa: BLE001
        entry["bodyError"] = str(exc)
    cap.entries.append(entry)


LANDING_HTML_SCAN_JS = r"""() => {
  // 랜딩 DOM 안에 조직도 관련 임베디드 데이터가 있는지 — <script> 태그 전수 + 특정 마커.
  const scripts = [...document.querySelectorAll('script')].map(s => ({
    src: s.src || null,
    inlineLen: s.src ? 0 : (s.textContent || '').length,
    hasOrgHint: !s.src && /organizationTree|k-sprite|business["']?\s*:|dept["']?\s*:/.test(s.textContent || ''),
  })).filter(s => s.src || s.inlineLen > 0);
  const orgHint = scripts.filter(s => s.hasOrgHint);
  return {
    totalScripts: scripts.length,
    inlineScriptsWithHint: orgHint.length,
    hintSample: orgHint.slice(0, 3).map(s => s.inlineLen),
    hasOrgTreeInDOM: !!document.querySelector('#organizationTreeView'),
  };
}"""


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 를 .env 에 채우고 실행하세요.", file=sys.stderr)
        return 2

    base = get_settings().erp_base
    cap = Capture()
    result: dict[str, Any] = {"base": base, "userid": USERID}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await ctx.new_page()
        page.on("response", lambda r: asyncio.ensure_future(_on_response(r, cap)))

        try:
            cap.phase = "login"
            t0 = time.monotonic()
            await ensure_logged_in(page, USERID, PASSWORD, base)
            print(f"[login] {int((time.monotonic() - t0) * 1000)}ms", flush=True)
            await page.wait_for_timeout(1500)  # 랜딩 위젯 정착(기존 org_sync 관례와 동일).
            await page.screenshot(path=str(ARTIFACTS / "org_api_landing.png"))

            cap.phase = "landing_scan"
            result["landingScan"] = await page.evaluate(LANDING_HTML_SCAN_JS)
            print(f"[landing_scan] {result['landingScan']}", flush=True)

            cap.phase = "org_click"
            t1 = time.monotonic()
            await _open_org_chart(page)
            print(f"[org_click] 트리 오픈 {int((time.monotonic() - t1) * 1000)}ms", flush=True)
            await page.wait_for_timeout(1000)
            await page.screenshot(path=str(ARTIFACTS / "org_api_tree_opened.png"), full_page=True)

            cap.phase = "tree_dump"
            full = await page.evaluate(FULL_TREE_JS)
            result["treeDump"] = full
            if full:
                items = full.get("items") or []
                by_type: dict[str, int] = {}
                for it in items:
                    by_type[it.get("type") or ""] = by_type.get(it.get("type") or "", 0) + 1
                print(f"[tree_dump] 노드 {full.get('total')}개, 종류별={by_type}", flush=True)

            result["stepError"] = None
        except Exception as exc:  # noqa: BLE001 — 실패해도 지금까지의 캡처는 저장한다.
            result["stepError"] = f"{type(exc).__name__}: {exc}"
            print(f"프로브 중단: {result['stepError']}", file=sys.stderr)
            try:
                await page.screenshot(path=str(ARTIFACTS / "org_api_error.png"))
            except Exception:  # noqa: BLE001
                pass
        finally:
            await ctx.close()
            await browser.close()

    result["networkEntryCount"] = len(cap.entries)
    result["network"] = cap.entries

    # 조직/부서/트리 관련 후보만 별도로 요약 출력(전체는 파일에 남김).
    print("\n=== org 관련 후보 엔드포인트(URL 키워드 또는 body 히트) ===")
    for e in cap.entries:
        url_low = e["url"].lower()
        if any(k in url_low for k in ORG_URL_KEYWORDS):
            print(f"  [{e['phase']}] {e['method']} {e['status']} {e['url']} (bodyLen={e.get('bodyLen')})")

    CAPTURE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(f"\n캡처 저장: {CAPTURE_PATH} (entries={len(cap.entries)})")
    return 1 if result.get("stepError") else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
