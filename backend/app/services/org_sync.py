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

from app.config import get_settings
from nbkit.browser.actions import mouse_click
from nbkit.patterns.login_flow import ensure_logged_in

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


async def fetch_org_tree(userid: str, password: str, browser_factory) -> dict:
    """헤드리스로 조직도 스크레이프 → {raw:[...], flat:[...], nodes:[...]}.

    raw=전 노드, flat=본부▸팀 2단계(레거시 카탈로그용), nodes=전체 깊이 트리(org_units 미러링용).
    조직도는 랜딩에 있어 로그인만 하면 된다(사용자유형 전환·메뉴이동 불필요). 읽기 전용.
    """
    browser = await browser_factory()
    try:
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        await ensure_logged_in(page, userid, password, get_settings().erp_base)
        await page.wait_for_timeout(1200)
        await _open_org_chart(page)
        full = await page.evaluate(FULL_TREE_JS)
        items = (full or {}).get("items", [])
        return {"raw": items, "flat": flatten_to_hq_team(items), "nodes": build_full_tree(items)}
    finally:
        await browser.close()
