"""옴니솔 조직도(우상단 Kendo TreeView) 헤드리스 스크레이프 + 본부▸팀 평탄화.

프로브(e2e/org_probe.py, 2026-07-09) 실측: 조직도는 랜딩 우상단 '조직도' 클릭 → 모달의
`#organizationTreeView`(Kendo TreeView). **전체 트리가 DOM 에 이미 있음**(접힘=display:none,
지연로드/XHR 아님) → 한 번에 전량 스크레이프. 노드 = 이름 + 인원수 + 종류(company/business/dept).
안정 ERP 코드 없음(Kendo GUID 뿐) → 이름으로 정합. cost_type 은 ERP 에 없음(우리 시스템 유지).

실제 깊이는 최대 5단계(회사>사업장>본부>그룹>팀)라 우리 OrgUnit(2단계)로 **평탄화**한다:
  - 본부 = 사업장 직속(depth = business+1) dept 노드.
  - 팀   = 각 본부의 **leaf** 자손(그룹 중간 단계는 버리고 말단만 팀으로 승격).
  - leaf 본부(중국법인 등, 하위 없음) = 본부 + 동명 팀 1개.
"""

from __future__ import annotations

import json
import logging

from app.config import get_settings
from nbkit.browser.actions import mouse_click
from nbkit.patterns.login_flow import ensure_logged_in

logger = logging.getLogger(__name__)

# 조직도 트리 API(Wehago 포탈) — 랜딩 '조직도' 클릭 시 위젯이 이 엔드포인트로 트리를 받는다.
# erp.ninebell.co.kr 이 아니라 uc.ninebell.co.kr(그룹웨어 백엔드)이고, 인증은 ERP 의
# x-authenticate-token 이 아니라 Authorization: Bearer <authToken> + session-id + wehago-sign
# 헤더다(브라우저 위젯이 계산). 그 서명을 브라우저 없이 만들 수 없어, **브라우저로 조직도를
# 한 번 열어 위젯이 쏜 이 요청의 헤더를 캡처한 뒤 isTreeAllOpen:true 로 재요청**해 전량 트리를
# 얻는다(하이브리드). 순수 DOM 스크레이프의 lazy-load 누락(미펼친 팀)을 함께 해소한다(실측).
_ORG_API_MARKER = "gw102A01"
# orgGubun(회사/사업장/부서) → DOM k-sprite type 과 동일 어휘로 정규화.
_ORG_GUBUN_TYPE = {"c": "company", "b": "business", "d": "dept"}
# 재요청 시 캡처 헤더에서 뺄 것(길이·호스트·인코딩·연결은 page.request 가 다시 채운다).
_ORG_API_DROP_HEADERS = {"content-length", "host", "accept-encoding", "connection"}


def api_tree_to_items(tree_list: list[dict]) -> list[dict]:
    """조직도 API 응답(resultData.treeList) → org_sync 공용 items 형태로 변환.

    반환 [{depth, label, count, type}] 를 **전위순회(preorder)** 로 — flatten_to_hq_team/
    build_full_tree 가 순서 의존(다음 항목 depth 비교로 leaf 판정)이라, API 의 레벨-그룹 배열을
    path 기반으로 재정렬한다. id/parentSeq 는 회사·사업장이 같은 코드(1000)를 공유해 모호하므로
    **path**(예: '1000|1000|1205|') 를 유일 키로 쓰고, 형제는 orderNum 으로 정렬한다.
    depth=orgLevel(서버 계산), type=orgGubun(c/b/d), count=childUserCnt, label=text.
    """
    def _parent_path(path: str) -> str:
        segs = [s for s in path.split("|") if s]
        return ("|".join(segs[:-1]) + "|") if len(segs) > 1 else ""

    children: dict[str, list[dict]] = {}
    for n in tree_list:
        path = n.get("path") or ""
        if not path:
            continue
        children.setdefault(_parent_path(path), []).append(n)
    for sibs in children.values():
        sibs.sort(key=lambda x: (x.get("orderNum") or 0, x.get("path") or ""))

    items: list[dict] = []

    def _dfs(parent_path: str) -> None:
        for n in children.get(parent_path, []):
            items.append(
                {
                    "depth": int(n.get("orgLevel") or 0),
                    "label": (n.get("text") or "").strip(),
                    "count": n.get("childUserCnt"),
                    "type": _ORG_GUBUN_TYPE.get(n.get("orgGubun"), n.get("orgGubun") or ""),
                }
            )
            _dfs(n.get("path") or "")

    _dfs("")  # 루트(회사) = 부모 경로 ''
    return items

# 우상단 '조직도' 트리거 후보(정확 텍스트) 좌표 조회 — 화면 안·클릭 가능한 것만.
FIND_ORG_TRIGGER_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const els = [...document.querySelectorAll('a,button,li,span,div')].filter(e =>
    e.offsetParent !== null && c(e.innerText || e.textContent || '') === '조직도');
  const out = [];
  for (const e of els) {
    const r = e.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.x >= 0)
      out.push({ x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), w: Math.round(r.width) });
  }
  // 위(y 작고)·오른쪽(x 큰) 우선.
  out.sort((a, b) => a.y - b.y || b.x - a.x);
  return out;
}"""

# 전체 조직 트리 덤프 — Kendo TreeView. depth=ul.k-group 조상 수, type=k-sprite 종류, count=(N)인원.
FULL_TREE_JS = r"""() => {
  const root = document.querySelector('#organizationTreeView') || document.querySelector('.dews-ui-treeview');
  if (!root) return null;
  const items = [...root.querySelectorAll('li[role=treeitem]')].map(li => {
    let d = 0, p = li.parentElement;
    while (p && p !== root) { if (p.matches('ul.k-group')) d++; p = p.parentElement; }
    const inEl = li.querySelector(':scope > div > .k-in');
    let raw = '';
    if (inEl) raw = ([...inEl.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()) || inEl.innerText.trim();
    const sprite = li.querySelector(':scope > div .k-sprite');
    const type = sprite ? ([...sprite.classList].find(c => c !== 'k-sprite') || '') : '';
    const m = raw.match(/\((\d+)\)\s*$/);
    return { depth: d, label: raw.replace(/\s*\(\d+\)\s*$/, ''), count: m ? +m[1] : null, type };
  });
  return { total: items.length, items };
}"""


async def _open_org_chart(page) -> None:
    """랜딩 우상단 '조직도' 클릭 → 트리 렌더까지 대기. 실패 시 RuntimeError."""
    cands = await page.evaluate(FIND_ORG_TRIGGER_JS)
    if not cands:
        raise RuntimeError("조직도 버튼을 찾지 못했습니다(랜딩 화면 확인 필요).")
    await mouse_click(page, cands[0]["x"], cands[0]["y"])
    for _ in range(20):  # 트리 렌더 폴링(상한 ~10s)
        await page.wait_for_timeout(500)
        full = await page.evaluate(FULL_TREE_JS)
        if full and full.get("total", 0) >= 2:
            return
    raise RuntimeError("조직도 트리가 열리지 않았습니다.")


def flatten_to_hq_team(items: list[dict]) -> list[dict]:
    """평탄한 노드 목록(전위순회) → 본부▸팀. 반환 [{hq, hqCount, team, teamCount}] (팀 단위 행).

    본부 = 사업장 직속(depth business+1) dept, 팀 = 그 본부의 leaf 자손. leaf 본부는 동명 팀.
    """
    biz_depth = next((n["depth"] for n in items if n["type"] == "business"), 2)
    hq_depth = biz_depth + 1

    # dept 노드만(빈 라벨·비-dept 노드 제거) 순서 유지 — 빈 자식 때문에 팀이 leaf 판정에서
    # 누락되던 문제 방지(제조1/2팀 아래 빈 노드 실측). has_child 는 이 정제 목록 기준.
    depts = [n for n in items if n["type"] == "dept" and n["label"]]

    rows: list[dict] = []
    cur_hq: str | None = None
    cur_hq_count: int | None = None
    for i, n in enumerate(depts):
        has_child = i + 1 < len(depts) and depts[i + 1]["depth"] > n["depth"]
        if n["depth"] == hq_depth:
            cur_hq, cur_hq_count = n["label"], n["count"]
            if not has_child:  # leaf 본부 → 동명 팀.
                rows.append({"hq": cur_hq, "hqCount": cur_hq_count, "team": cur_hq, "teamCount": n["count"]})
        elif n["depth"] > hq_depth and cur_hq is not None and not has_child:
            rows.append({"hq": cur_hq, "hqCount": cur_hq_count, "team": n["label"], "teamCount": n["count"]})
    return rows


def build_full_tree(items: list[dict]) -> list[dict]:
    """평탄 노드 목록(전위순회, depth) → 본부 이하 **전체 깊이** 트리를 라벨 경로로 반환.

    ERP 조직을 깊이 그대로 미러링한다(경영본부>재무자원관리그룹>자재팀 등 중간 그룹 보존).
    회사(company)·사업장(business) 최상위는 제외하고 본부(=business+1) 이하만 담는다.
    반환 [{path:[상위라벨...,self], label, count, is_leaf}] 를 전위순서(부모 먼저)로.
    is_leaf = 자식 없음(=말단 팀 → 비용구분 대상). 노드 식별은 정규화 라벨 경로(안정 ERP 코드 없음).
    """
    biz_depth = next((n["depth"] for n in items if n["type"] == "business"), 2)
    hq_depth = biz_depth + 1
    depts = [n for n in items if n["type"] == "dept" and n["label"]]

    nodes: list[dict] = []
    stack: list[tuple[int, str]] = []  # 현재 조상 경로 [(depth, label)]
    for i, n in enumerate(depts):
        d = n["depth"]
        if d < hq_depth:
            continue  # 본부보다 위 — 방어(정상 트리엔 없음)
        while stack and stack[-1][0] >= d:  # 조상 스택을 현재 depth 미만까지 되감기
            stack.pop()
        path = [lb for (_, lb) in stack] + [n["label"]]
        is_leaf = not (i + 1 < len(depts) and depts[i + 1]["depth"] > d)
        nodes.append(
            {"path": path, "label": n["label"], "count": n.get("count"), "is_leaf": is_leaf}
        )
        stack.append((d, n["label"]))
    return nodes


async def _fetch_org_items_via_api(page, req) -> list[dict]:
    """캡처한 gw102A01 요청을 isTreeAllOpen:true 로 재요청해 **전량** 트리 items 획득.

    위젯이 쏜 요청의 인증 헤더(Authorization/session-id/wehago-sign 등)를 그대로 재사용하되
    body 의 isTreeAllOpen 만 true 로 바꾼다(wehago-sign 은 body 를 서명하지 않아 통과 — 실측).
    page.request 는 페이지 컨텍스트의 네트워크라 CORS·쿠키를 그대로 탄다. 실패는 예외로 올려
    호출부가 DOM 스크레이프로 폴백하게 한다.
    """
    headers = {k: v for k, v in (await req.all_headers()).items() if k.lower() not in _ORG_API_DROP_HEADERS}
    body = json.loads(req.post_data or "{}")
    body["isTreeAllOpen"] = True
    resp = await page.request.post(req.url, headers=headers, data=json.dumps(body))
    if not resp.ok:
        raise RuntimeError(f"조직도 API HTTP {resp.status}")
    j = await resp.json()
    if j.get("resultCode") != 0:
        raise RuntimeError(f"조직도 API 실패: {j.get('resultMsg')}")
    tree_list = (j.get("resultData") or {}).get("treeList") or []
    items = api_tree_to_items(tree_list)
    if not items:
        raise RuntimeError("조직도 API treeList 가 비어 있습니다")
    return items


async def fetch_org_tree(userid: str, password: str, browser_factory) -> dict:
    """헤드리스로 조직도 트리 획득 → {raw, flat, nodes, via}.

    API 우선: 브라우저로 조직도를 한 번 열어(위젯이 gw102A01 을 쏨) 그 요청 헤더를 캡처한 뒤
    isTreeAllOpen:true 로 재요청해 **전량** 트리를 받는다 — DOM 스크레이프가 한 번도 안 펼친
    깊은 팀(Kendo lazy-load)을 누락하던 완전성 버그를 해소한다(실측). API 실패 시 DOM
    스크레이프(FULL_TREE_JS)로 폴백. ERP_API_SYNC_ENABLED=false 면 DOM 만 쓴다.
    raw=전 노드, flat=본부▸팀 2단계(레거시 카탈로그용), nodes=전체 깊이 트리(org_units 미러링용).
    조직도는 랜딩에 있어 로그인만 하면 된다(사용자유형 전환·메뉴이동 불필요). 읽기 전용.
    """
    prefer_api = get_settings().erp_api_sync_enabled
    browser = await browser_factory()
    try:
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        captured: dict = {"req": None}
        if prefer_api:

            def _on_req(req) -> None:
                if captured["req"] is None and _ORG_API_MARKER in req.url and req.method == "POST":
                    captured["req"] = req

            page.on("request", _on_req)

        await ensure_logged_in(page, userid, password, get_settings().erp_base)
        await page.wait_for_timeout(1200)
        await _open_org_chart(page)  # 위젯이 gw102A01 을 쏘고 DOM 트리도 렌더(폴백용).

        items: list[dict] | None = None
        via = "browser"
        if prefer_api and captured["req"] is not None:
            try:
                items = await _fetch_org_items_via_api(page, captured["req"])
                via = "api"
            except Exception:  # noqa: BLE001 — API 실패는 DOM 스크레이프로 폴백.
                logger.exception("조직도 API 경로 실패 — DOM 스크레이프 폴백")
                items = None
        if not items:
            full = await page.evaluate(FULL_TREE_JS)
            items = (full or {}).get("items", [])
            via = "browser"
        return {
            "raw": items,
            "flat": flatten_to_hq_team(items),
            "nodes": build_full_tree(items),
            "via": via,
        }
    finally:
        await browser.close()
