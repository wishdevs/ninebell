"""조직도 인브라우저 API 호출 실증 — 브라우저로 조직도 열어 gw102A01 헤더 캡처 → isTreeAllOpen:true
재요청으로 전량 트리 획득이 되는지 라이브 검증. DOM 스크레이프와 노드 수 대조(완전성 버그 확인).

⚠ 읽기 전용 — 로그인·클릭·조회(POST 는 조직도 조회 API 뿐, 저장/상신 없음).

Usage: cd backend && .venv/bin/python e2e/org_api_inbrowser_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.org_sync import (  # noqa: E402
    FULL_TREE_JS,
    _ORG_API_MARKER,
    _open_org_chart,
    api_tree_to_items,
    build_full_tree,
    flatten_to_hq_team,
)
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

for _l in (Path(__file__).resolve().parents[1] / ".env").read_text(errors="ignore").splitlines():
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _v = _l.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

USERID = os.environ.get("E2E_USERID") or ""
PASSWORD = os.environ.get("E2E_PASSWORD") or ""
_DROP_HEADERS = {"content-length", "host", "accept-encoding", "connection"}


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID/PASSWORD 필요", file=sys.stderr)
        return 2
    base = get_settings().erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1600, "height": 1000})
            captured = {"req": None}

            def _on_req(req):
                if captured["req"] is None and _ORG_API_MARKER in req.url and req.method == "POST":
                    captured["req"] = req

            page.on("request", _on_req)
            await ensure_logged_in(page, USERID, PASSWORD, base)
            await page.wait_for_timeout(1200)
            await _open_org_chart(page)
            await page.wait_for_timeout(500)

            # DOM 스크레이프(현행 경로) — 완전성 비교 기준.
            dom = await page.evaluate(FULL_TREE_JS)
            dom_items = (dom or {}).get("items") or []
            dom_labeled = [n for n in dom_items if n.get("type") == "dept" and n.get("label")]
            print(f"[DOM] 노드 {len(dom_items)}개(dept 라벨있음 {len(dom_labeled)}) → 본부팀 {len(flatten_to_hq_team(dom_items))}행")

            req = captured["req"]
            if req is None:
                print("gw102A01 요청을 캡처하지 못함 — 위젯이 안 쐈거나 마커 불일치", file=sys.stderr)
                return 1
            headers = await req.all_headers()
            send = {k: v for k, v in headers.items() if k.lower() not in _DROP_HEADERS}
            body = json.loads(req.post_data or "{}")
            body["isTreeAllOpen"] = True
            resp = await page.request.post(req.url, headers=send, data=json.dumps(body))
            print(f"[API] page.request.post → {resp.status} (isTreeAllOpen:true)")
            j = await resp.json()
            tl = (j.get("resultData") or {}).get("treeList") or []
            print(f"[API] resultCode={j.get('resultCode')} treeList={len(tl)}개")
            items = api_tree_to_items(tl)
            flat = flatten_to_hq_team(items)
            nodes = build_full_tree(items)
            print(f"[API] preorder items {len(items)} → 본부팀 {len(flat)}행, full-tree {len(nodes)}(leaf {sum(1 for n in nodes if n['is_leaf'])})")

            api_teams = {(r["hq"], r["team"]) for r in flat}
            dom_teams = {(r["hq"], r["team"]) for r in flatten_to_hq_team(dom_items)}
            only_api = api_teams - dom_teams
            print(f"[대조] API 전용(=DOM 누락) 팀 {len(only_api)}개: {sorted(only_api)}")
            print(f"[대조] DOM 전용 팀 {len(dom_teams - api_teams)}개: {sorted(dom_teams - api_teams)}")
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
