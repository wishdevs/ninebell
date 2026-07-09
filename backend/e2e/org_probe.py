"""HEADLESS 읽기전용 프로브 — 옴니솔 조직도(우상단 DOM 위젯) 구조 실측.

목적: 조직도가 우리 OrgUnit(본부▸팀 + sort)로 싱크 가능한지 확인. 사용자 확정:
  - 렌더 = **그냥 DOM**(RealGrid 캔버스/XHR 아님) → DOM 트리 직접 스크레이프.
  - cost_type(판/제)는 ERP 에 **없음** → 탐색 대상 아님(우리 시스템에서 별도 유지).

⚠ 읽기 전용: 조직도 여는 클릭까지만. 저장/상신/전표 계열 버튼 클릭 금지. 종료 시 미저장 닫기.

계정: 이트라이브2/1111. 로그인 → 랜딩(우상단 조직도) 열기 → 트리 DOM 덤프.
확인 항목: (1) 트리거 위치/여는 법, (3) 노드 필드(부서코드·상위코드·이름·정렬),
          (4) 계층 깊이. 결과 → artifacts/org_probe_*.json + 스크린샷.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/org_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import mouse_click  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)


# '조직도' 텍스트 클릭 후보 나열(버튼/링크/아이콘). 우상단 후보 선별용 좌표 포함.
FIND_ORGDO_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const els = [...document.querySelectorAll('a,button,span,div,li,td,i,img')].filter(e =>
    e.offsetParent !== null &&
    (c(e.innerText || e.textContent || '').includes('조직도') ||
     (e.getAttribute && (c(e.getAttribute('title')).includes('조직도') || c(e.getAttribute('alt')).includes('조직도'))))
  );
  return els.slice(0, 30).map(e => {
    const r = e.getBoundingClientRect();
    return {
      tag: e.tagName,
      text: c(e.innerText || e.textContent || e.getAttribute('title') || e.getAttribute('alt') || '').slice(0, 50),
      id: e.id || '',
      cls: (e.className || '').toString().slice(0, 100),
      x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
      w: Math.round(r.width), h: Math.round(r.height),
    };
  });
}"""


# treeview outerHTML 일부(토글 마크업 확인용).
TREE_HTML_JS = r"""() => {
  const t = document.querySelector('.dews-ui-treeview');
  return t ? t.outerHTML.slice(0, 4000) : null;
}"""

# 전체 조직 트리 덤프 — Kendo TreeView(#organizationTreeView). 접힌 노드도 DOM 에 다 있어
# (display:none) 가시성 필터 없이 전 노드를 읽는다. depth=ul.k-group 조상 수, type=k-sprite 종류
# (company/business/dept/person), count=라벨 끝 (N) 인원수, uid=data-uid(세션 클라이언트 id).
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
    return { depth: d, label: raw.replace(/\s*\(\d+\)\s*$/, ''), count: m ? +m[1] : null, type, uid: li.getAttribute('data-uid') };
  });
  return { total: items.length, items };
}"""

# 접힌(aria-expanded=false) 보이는 노드의 '펼치기 토글' 좌표. 토글 = 노드 라벨 왼쪽 화살표.
# dews/kendo 공통 후보 셀렉터 우선, 없으면 li 왼쪽 가장자리(+10px) 폴백.
COLLAPSED_TOGGLES_JS = r"""() => {
  const vis = e => e && e.offsetParent !== null && e.getBoundingClientRect().width > 0;
  const items = [...document.querySelectorAll('.dews-ui-treeview [aria-expanded=false]')].filter(vis);
  const out = [];
  for (const li of items.slice(0, 300)) {
    let tog = li.querySelector(':scope > .k-icon, :scope > .k-mid > .k-icon, :scope .dews-tree-toggle, :scope [class*=toggle], :scope [class*=expand], :scope [class*=arrow]');
    let x, y;
    if (tog && vis(tog)) { const r = tog.getBoundingClientRect(); x = Math.round(r.x + r.width/2); y = Math.round(r.y + r.height/2); }
    else { const r = li.getBoundingClientRect(); x = Math.round(r.x + 10); y = Math.round(r.y + Math.min(12, r.height/2)); }
    out.push({ x, y });
  }
  return out;
}"""


# 조직도 오픈 후 트리형 구조 덤프 — 다양한 트리 위젯 휴리스틱.
DUMP_TREE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = { trees: [], tables: [], visiblePopupTitles: [] };

  // 떠 있는 팝업/윈도우 제목(조직도 창 식별용).
  out.visiblePopupTitles = [...document.querySelectorAll('.k-window-title,.k-window .k-window-titlebar,.dialog .title,[class*=title]')]
    .filter(e => e.offsetParent !== null).map(e => c(e.innerText)).filter(Boolean).slice(0, 20);

  // 1) 트리 위젯 후보(role=tree / kendo / jstree / dhtmlx / generic ul.tree).
  const treeRoots = [...document.querySelectorAll('[role=tree], .k-treeview, .jstree, ul.tree, .dhx_tree, .dhtmlxTree, .tree, [class*=tree]')]
    .filter(e => e.offsetParent !== null);
  const seen = new Set();
  for (const root of treeRoots) {
    if (seen.has(root)) continue;
    // 중첩 루트 중복 방지 — 조상에 이미 담은 트리가 있으면 건너뜀.
    let anc = root.parentElement, dup = false;
    while (anc) { if (seen.has(anc)) { dup = true; break; } anc = anc.parentElement; }
    if (dup) continue;
    seen.add(root);
    const items = [...root.querySelectorAll('[role=treeitem], li, .k-item, .dhx_tree_item')]
      .filter(e => e.offsetParent !== null).slice(0, 600).map(li => {
        let d = 0, p = li.parentElement;
        while (p && p !== root) { if (p.matches('li,[role=treeitem],.k-item,ul,ol,.dhx_tree_item')) d++; p = p.parentElement; }
        const data = {};
        for (const a of li.attributes) { if (a.name.startsWith('data-') || a.name.startsWith('aria-') || a.name === 'id') data[a.name] = a.value; }
        const own = c([...li.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ')) || c(li.innerText).split('\n')[0];
        return { depth: d, text: own.slice(0, 60), attrs: data };
      });
    if (items.length) out.trees.push({ rootTag: root.tagName, rootCls: (root.className || '').toString().slice(0, 100), count: items.length, items });
    if (out.trees.length >= 6) break;
  }

  // 2) 폴백 — 표/그리드형(행에 부서명·코드가 있을 수 있음).
  const tables = [...document.querySelectorAll('table,[role=grid],.dews-ui-grid')].filter(e => e.offsetParent !== null).slice(0, 4);
  for (const t of tables) {
    const rows = [...t.querySelectorAll('tr,[role=row]')].filter(e => e.offsetParent !== null).slice(0, 60).map(r =>
      [...r.querySelectorAll('th,td,[role=gridcell],[role=columnheader]')].map(cell => c(cell.innerText).slice(0, 40)).filter(Boolean));
    const nonEmpty = rows.filter(r => r.length);
    if (nonEmpty.length) out.tables.push({ cls: (t.className || '').toString().slice(0, 80), rowCount: nonEmpty.length, rows: nonEmpty.slice(0, 40) });
  }
  return out;
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base

    # XHR 관찰(조직도가 혹시 XHR 백드면 잡히게 — 사용자는 DOM 이라 했으나 저비용 보험).
    xhr: list[dict] = []
    page.on(
        "response",
        lambda r: xhr.append({"url": r.url, "status": r.status})
        if any(k in r.url.lower() for k in ("org", "dept", "emp", "조직", "hrm", "team"))
        else None,
    )

    result: dict = {"userid": USERID, "base": base}
    try:
        print("[entry] login…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(ARTIFACTS / "org_probe_landing.png"))

        # 1) 조직도 트리거 후보 탐색.
        cands = await page.evaluate(FIND_ORGDO_JS)
        result["candidates"] = cands
        print(f"[find] 조직도 후보 {len(cands)}개", flush=True)
        for cnd in cands[:10]:
            print(f"   - {cnd['tag']} '{cnd['text']}' @({cnd['x']},{cnd['y']}) id={cnd['id']!r}", flush=True)

        if not cands:
            print("[find] '조직도' 텍스트 요소 없음 — 랜딩 스크린샷 확인 필요.", flush=True)
            result["opened"] = False
        else:
            # 우상단 우선: 화면 안(0≤x≤1600, 0≤y) + 정확히 '조직도' 텍스트 + 클릭 크기(w,h>0).
            # 오프스크린(x<0, 접힌 메뉴)·큰 메뉴 blob(긴 텍스트)은 제외. 그중 위(y 작고)·오른쪽(x 큰) 우선.
            vw = selectors.VIEWPORT["width"]
            clickable = [
                c
                for c in cands
                if c["w"] > 0 and c["h"] > 0 and 0 <= c["x"] <= vw and c["y"] >= 0 and c["text"] == "조직도"
            ]
            clickable.sort(key=lambda c: (c["y"], -c["x"]))
            target = clickable[0] if clickable else next(
                (c for c in cands if c["w"] > 0 and 0 <= c["x"] <= vw), cands[0]
            )
            print(f"[open] 클릭 → '{target['text']}' @({target['x']},{target['y']})", flush=True)
            await mouse_click(page, target["x"], target["y"])

            # 트리/팝업 렌더 폴링(최대 ~8s).
            dump: dict = {}
            for _ in range(16):
                await page.wait_for_timeout(500)
                dump = await page.evaluate(DUMP_TREE_JS)
                if dump.get("trees") or dump.get("tables"):
                    break

            result["treeHtml"] = await page.evaluate(TREE_HTML_JS)

            # 전체 트리 덤프(접힌 노드 포함 — 지연 로드 아님). 로드 정착 위해 잠깐 대기 후 재확인.
            full = await page.evaluate(FULL_TREE_JS)
            for _ in range(6):
                if full and full.get("total", 0) > 2:
                    break
                await page.wait_for_timeout(500)
                full = await page.evaluate(FULL_TREE_JS)
            result["opened"] = True
            result["tree"] = full
            await page.screenshot(path=str(ARTIFACTS / "org_probe_opened.png"), full_page=True)

            if not full:
                print("[dump] 트리 루트 없음", flush=True)
            else:
                items = full["items"]
                depths = sorted({it["depth"] for it in items})
                by_type: dict = {}
                for it in items:
                    by_type[it["type"]] = by_type.get(it["type"], 0) + 1
                print(f"[dump] 전체 노드 {full['total']}개 · depth={depths} · 종류별={by_type}", flush=True)
                for it in items[:70]:
                    pad = "  " * it["depth"]
                    cnt = f" ({it['count']}명)" if it["count"] is not None else ""
                    print(f"   {pad}d{it['depth']} [{it['type']}] {it['label']}{cnt}", flush=True)

        result["xhr"] = xhr
    except Exception as exc:  # noqa: BLE001 — 프로브라 전체 예외 기록.
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[error] {result['error']}", flush=True)
        try:
            await page.screenshot(path=str(ARTIFACTS / "org_probe_error.png"))
        except Exception:
            pass
    finally:
        out = ARTIFACTS / "org_probe.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[done] → {out}", flush=True)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
