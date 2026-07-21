"""읽기전용 탐색 프로브 — 미지급금 법인카드(voucher-card) 3대 확장 실측 1단계.

목적: Phase A(전표조회승인, 전표유형=일반 조회 + 결의서번호 컬럼 확정)와, Phase B 진입을 위한
**사이드바 메뉴 트리 구조 탐색**(결의서조회승인의 menu_id/딥링크를 아직 모르므로 DOM 을 덤프해
찾는다). 부작용 0 — 조회(F2)만 실행하고 결제·상신·저장·삭제는 전혀 하지 않는다.

Usage:
    cd backend && .venv/bin/python e2e/voucher_card_discover_probe.py
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
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.omnisol.modals import dismiss_blocking_modals, dismiss_notice_popup  # noqa: E402

from app.agents.voucher_receivable import js as vr_js  # noqa: E402
from app.agents.voucher_receivable import steps as vr_steps  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DOCU_TYPES_CARD = ("일반",)

# 마스터 그리드 전체 컬럼 + 상위 N행(원본 JSON, 필드 상관없이) — 결의서번호 컬럼 확정용.
MASTER_DUMP_FULL_JS = r"""(limit) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const cols = g.getColumns().map(c => ({ field: c.fieldName, header: (c.header && c.header.text) || c.name, visible: c.visible }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(n, limit || 10);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, n, cols, rows };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 200) }; }
}"""

# 상단 로고 오른쪽 탭 바 영역 덤프(멀티 메뉴 탭 구조 탐색용) — 존재하면 텍스트+클래스+rect.
TOP_TABS_DUMP_JS = r"""() => {
  const cands = [...document.querySelectorAll('*')].filter(el => {
    const cls = (el.className || '').toString();
    return /tab/i.test(cls) && el.children.length < 10;
  }).slice(0, 60);
  return cands.map(el => {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName, cls: (el.className||'').toString().slice(0,80),
      text: (el.innerText||'').replace(/\s+/g,' ').trim().slice(0,40),
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      visible: el.offsetParent !== null,
    };
  }).filter(x => x.visible && x.w > 0);
}"""

# 사이드바(좌측 아이콘/메뉴 트리) 전체 텍스트 매치 요소 덤프 — 결의서조회승인 후보 탐색.
SIDEBAR_SEARCH_JS = r"""(needle) => {
  const out = [];
  for (const el of document.querySelectorAll('a, li, div, span')) {
    if (el.children.length > 3) continue;
    const t = (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim();
    if (t && t.includes(needle) && t.length < 40) {
      const r = el.getBoundingClientRect();
      out.push({
        tag: el.tagName, cls: (el.className||'').toString().slice(0,100),
        id: el.id || null, href: el.getAttribute && el.getAttribute('href'),
        text: t, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
        visible: el.offsetParent !== null,
      });
    }
  }
  return out;
}"""

# 좌측 사이드바로 추정되는 최상위 아이콘/네비 요소 덤프(구조 파악용).
NAV_STRUCTURE_JS = r"""() => {
  const sels = ['aside', 'nav', '.gnb', '.lnb', '.sidebar', '.side-menu', '[class*=sidebar]', '[class*=gnb]', '[class*=lnb]'];
  const seen = new Set();
  const out = [];
  for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
      if (seen.has(el)) continue;
      seen.add(el);
      const r = el.getBoundingClientRect();
      out.push({ sel, cls: (el.className||'').toString().slice(0,100), id: el.id || null,
        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
        visible: el.offsetParent !== null });
    }
  }
  return out;
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    context = await browser.new_context(viewport=LIVE_VIEWPORT)
    raw_page = await context.new_page()
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    report: dict = {}

    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, base)
        await page.wait_for_timeout(1_500)

        # ── Phase A: 전표유형=일반 조회 + 결의서번호 컬럼 확정 ──────────────────
        print("\n===== PHASE A: 전표조회승인(전표유형=일반) 조회 =====", flush=True)
        await vr_steps.expand_condition_panel(page)
        r = await vr_steps.set_dept_all(page)
        print(f"[A] 작성부서 전체 = {r}", flush=True)
        r2 = await vr_steps.set_period_this_month(page)
        print(f"[A] 회계일 당월 = {r2}", flush=True)
        r3 = await vr_steps.clear_writer(page)
        print(f"[A] 작성자 비움 = {r3}", flush=True)
        r4 = await vr_steps.set_docu_status(page)
        print(f"[A] 전표상태 미결 = {r4}", flush=True)
        r5 = await vr_steps.set_gwaprvlst(page)
        print(f"[A] 전자결재상태 저장 = {r5}", flush=True)
        r6 = await vr_steps.set_docu_types(page, DOCU_TYPES_CARD)
        print(f"[A] 전표유형=일반 = {r6}", flush=True)

        rq = await vr_steps.run_query(page)
        print(f"[A] 조회 실행 = {rq}", flush=True)

        dump = await raw_page.evaluate(MASTER_DUMP_FULL_JS, 10)
        print(f"[A] 마스터그리드 n={dump.get('n')}", flush=True)
        print(f"[A] 컬럼 = {json.dumps(dump.get('cols'), ensure_ascii=False)}", flush=True)
        if dump.get("rows"):
            print(f"[A] 샘플행[0] = {json.dumps(dump['rows'][0], ensure_ascii=False, default=str)}", flush=True)
        report["phase_a"] = {"set_query": [r, r2, r3, r4, r5, r6], "run_query": rq, "dump": dump}

        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_discover_a_result.png"), full_page=True)
        (ARTIFACTS / "voucher_card_discover_a_dump.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

        # ── Phase B0: 결의서조회승인 메뉴 탐색(사이드바 구조 + 텍스트 매치) ─────
        print("\n===== PHASE B0: 사이드바/탭 구조 탐색 =====", flush=True)
        nav = await raw_page.evaluate(NAV_STRUCTURE_JS)
        print(f"[B0] nav 후보 = {json.dumps(nav, ensure_ascii=False)}", flush=True)

        hits = await raw_page.evaluate(SIDEBAR_SEARCH_JS, "결의서조회승인")
        print(f"[B0] '결의서조회승인' 텍스트 매치 = {json.dumps(hits, ensure_ascii=False)}", flush=True)
        hits_gl = await raw_page.evaluate(SIDEBAR_SEARCH_JS, "총계정원장")
        print(f"[B0] '총계정원장' 텍스트 매치 = {json.dumps(hits_gl, ensure_ascii=False)}", flush=True)
        hits_vm = await raw_page.evaluate(SIDEBAR_SEARCH_JS, "전표관리")
        print(f"[B0] '전표관리' 텍스트 매치 = {json.dumps(hits_vm, ensure_ascii=False)}", flush=True)

        tabs = await raw_page.evaluate(TOP_TABS_DUMP_JS)
        print(f"[B0] 상단 탭류 후보 = {json.dumps(tabs, ensure_ascii=False)}", flush=True)

        report["phase_b0"] = {"nav": nav, "hits_doc": hits, "hits_gl": hits_gl, "hits_vm": hits_vm, "tabs": tabs}

        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_discover_b0_before.png"), full_page=True)

        # ── Phase B1: 결의서조회승인 사이드바 링크 실클릭 → 탭 생성 관찰 ────────
        # ⚠ 자가수정(가설 1개): 1차 시도가 '.k-overlay 가 포인터 이벤트를 가로챔' 으로 실패
        # (공지 팝업의 just-in-time 지연 로드 레이스, _open_picker 와 동일 패턴) — 클릭 직전
        # 공지팝업 재확인(appear_cap_ms=0) + 잔여 확인모달 정리 후 재시도.
        print("\n===== PHASE B1: 결의서조회승인 클릭 → 탭 생성 =====", flush=True)
        link_sel = 'a.nav-text[href="/FI/GLDDOC00400"]'
        await dismiss_notice_popup(page, appear_cap_ms=0)
        await dismiss_blocking_modals(page, rounds=1)
        try:
            await raw_page.click(link_sel, timeout=8_000)
        except Exception as exc:  # noqa: BLE001 — 진단 후 1회 재시도.
            print(f"[B1] 1차 클릭 실패({exc.__class__.__name__}) — 모달 재정리 후 재시도", flush=True)
            await dismiss_notice_popup(page, appear_cap_ms=0)
            await dismiss_blocking_modals(page, rounds=1)
            await raw_page.click(link_sel, timeout=8_000)
        await page.wait_for_timeout(2_000)

        tabs_after = await raw_page.evaluate(TOP_TABS_DUMP_JS)
        print(f"[B1] 탭 클릭 후 상단 탭류 = {json.dumps(tabs_after, ensure_ascii=False)}", flush=True)

        grid_count = await raw_page.evaluate("() => document.querySelectorAll('.dews-ui-grid').length")
        print(f"[B1] 클릭 후 .dews-ui-grid 개수 = {grid_count}", flush=True)

        report["phase_b1"] = {"tabs_after": tabs_after, "grid_count": grid_count}
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_discover_b1_after_click.png"), full_page=True)

        # ── Phase B2: 새 탭(결의서조회승인) 조회폼 필드 라벨 탐색 ──────────────
        # ⚠ 자가수정(가설 1개): '.tab-page.tab-focus' 로 스코프를 좁히면 잔존 tab-focus 클래스가
        # 있는 이전 탭(전표조회승인) DOM 을 오매칭할 수 있다(B1 탭 텍스트엔 '결의부서/결의자'가
        # 보이는데 위 셀렉터로는 '작성부서/작성자'가 잡힘 — 스코프 대신 **가시성**으로 판별).
        print("\n===== PHASE B2: 결의서조회승인 조회폼 필드 탐색 =====", flush=True)
        labels_dump = await raw_page.evaluate(r"""() => {
          const out = [];
          for (const lbl of document.querySelectorAll('label')) {
            if (lbl.offsetParent === null) continue;  // 숨김/비활성 탭 라벨 제외.
            const t = (lbl.innerText || '').replace(/\s+/g,' ').trim();
            if (!t) continue;
            const li = lbl.closest('li') || lbl.parentElement;
            const inputs = li ? [...li.querySelectorAll('input, select, button')].map(el => ({
              tag: el.tagName, type: el.type || null, id: el.id || null,
              cls: (el.className||'').toString().slice(0,80),
              placeholder: el.placeholder || null,
              visible: el.offsetParent !== null,
            })) : [];
            const r = lbl.getBoundingClientRect();
            out.push({ label: t, x: Math.round(r.x), y: Math.round(r.y), inputs });
          }
          return out;
        }""")
        print(f"[B2] 라벨+인풋 덤프 = {json.dumps(labels_dump, ensure_ascii=False)}", flush=True)
        report["phase_b2"] = {"labels_dump": labels_dump}
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_discover_b2_form.png"), full_page=True)

        # ── Phase B2b: 숨은(접힘) 라벨 전량 + 확장 토글 탐색 — 결의서번호 입력란 미확인 ──
        print("\n===== PHASE B2b: 숨은 라벨 + 확장 토글 탐색 =====", flush=True)
        hidden_labels = await raw_page.evaluate(r"""() => {
          const out = [];
          for (const lbl of document.querySelectorAll('label')) {
            const t = (lbl.innerText || '').replace(/\s+/g,' ').trim();
            if (!t) continue;
            out.push({ label: t, visible: lbl.offsetParent !== null });
          }
          return out;
        }""")
        print(f"[B2b] 전체 라벨(visible 포함) = {json.dumps(hidden_labels, ensure_ascii=False)}", flush=True)

        expand_toggles = await raw_page.evaluate(r"""() => {
          const btns = [...document.querySelectorAll('.dews-condition-panel-expand-button')];
          return btns.map(b => {
            const r = b.getBoundingClientRect();
            return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), visible: b.offsetParent !== null };
          });
        }""")
        print(f"[B2b] 확장 토글 후보 = {json.dumps(expand_toggles, ensure_ascii=False)}", flush=True)
        report["phase_b2b"] = {"hidden_labels": hidden_labels, "expand_toggles": expand_toggles}

        # ── Phase B2c: 확장 토글 클릭 → 결의서번호 입력란 노출 확인 ─────────────
        print("\n===== PHASE B2c: 확장 토글 클릭 → 결의서번호 입력란 =====", flush=True)
        visible_toggle = next((t for t in expand_toggles if t.get("visible")), None)
        if visible_toggle:
            await mouse_click(page, visible_toggle["x"], visible_toggle["y"])
            await page.wait_for_timeout(1_000)
            abdocu_dump = await raw_page.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const lbl = [...document.querySelectorAll('label')].find(e => c(e.innerText) === '결의서번호' && e.offsetParent !== null);
              if (!lbl) return { found: false };
              const li = lbl.closest('li') || lbl.parentElement;
              const inputs = [...li.querySelectorAll('input, select, button')].map(el => ({
                tag: el.tagName, type: el.type || null, id: el.id || null,
                cls: (el.className||'').toString().slice(0,80), visible: el.offsetParent !== null,
              }));
              return { found: true, inputs };
            }""")
            print(f"[B2c] 결의서번호 입력란 = {json.dumps(abdocu_dump, ensure_ascii=False)}", flush=True)
            report["phase_b2c"] = {"abdocu_dump": abdocu_dump}
            await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_discover_b2c_expanded.png"), full_page=True)
        else:
            print("[B2c] FAIL: 가시 확장 토글을 찾지 못함", flush=True)
            report["phase_b2c"] = {"error": "no-visible-toggle"}

        # ── Phase B3: 결의부서 전체선택 + 결의자 비움(PROCESS.md D6) → 결의서번호 입력 → 조회 ─
        # ⚠ 자가수정(가설 1개, 직전 시도 n=0): '결의부서/결의자' 기본값(로그인 계정 소속으로
        # 스코프 제한 추정)을 세팅하지 않고 곧장 결의서번호만 넣고 조회 — PROCESS.md D6 순서
        # (결의부서 전체선택 → 결의자 공백 → 결의서번호) 누락이 원인일 가능성. 먼저 그 둘을
        # 세팅한다(voucher_receivable._open_picker/POPUP_CHECK_ALL_JS 재사용 — 라벨 텍스트만 다름).
        print("\n===== PHASE B3: 결의부서 전체선택 + 결의자 비움 → 결의서번호 조회 =====", flush=True)
        if not await vr_steps._open_picker(page, "결의부서"):
            print("[B3] FAIL: 결의부서 돋보기를 찾지 못함", flush=True)
        else:
            dept_res = await raw_page.evaluate(vr_js.POPUP_CHECK_ALL_JS)
            print(f"[B3] 결의부서 전체선택 = {dept_res}", flush=True)
            await vr_steps._apply_popup(page)

        clear_res = await raw_page.evaluate(
            "() => { try { window.jQuery(document.querySelector('#WRT_EMP_NO_C'))"
            ".data('dewsControl').clear(); return true; } catch (e) { return String(e); } }"
        )
        print(f"[B3] 결의자 비움 = {clear_res}", flush=True)
        await page.wait_for_timeout(500)

        abdocu_no = "RN202607030012"  # Phase A 샘플행[0] ABDOCU_NO.
        await raw_page.fill("#ABDOCU_NO_C", abdocu_no)
        await page.wait_for_timeout(300)
        lookup_rect = await raw_page.evaluate(r"""() => {
          const btns = [...document.querySelectorAll('button.main-button.lookup')].filter(b => b.offsetParent !== null);
          if (!btns.length) return null;
          const r = btns[0].getBoundingClientRect();
          return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), n: btns.length };
        }""")
        print(f"[B3] 가시 조회버튼 rect = {lookup_rect}", flush=True)
        if lookup_rect:
            await mouse_click(page, lookup_rect["x"], lookup_rect["y"])
        else:
            await js_click(page, selectors.BTN_LOOKUP)  # 폴백.
        await page.wait_for_timeout(2_000)

        # 현재 보이는(활성 탭) 그리드 중 첫 번째를 결과 마스터그리드로 간주.
        visible_grid_dump = await raw_page.evaluate(r"""(abdocuNo) => {
          const grids = [...document.querySelectorAll('.dews-ui-grid')].filter(el => el.offsetParent !== null);
          if (!grids.length) return { ok: false, reason: 'no-visible-grid', total: document.querySelectorAll('.dews-ui-grid').length };
          const results = [];
          for (const el of grids) {
            try {
              const ctrl = window.jQuery(el).data('dewsControl');
              const g = ctrl && ctrl._grid;
              if (!g) { results.push({ ok: false, reason: 'no-dewsControl' }); continue; }
              const cols = g.getColumns().map(c => ({ field: c.fieldName, header: (c.header && c.header.text) || c.name }));
              const ds = g.getDataSource();
              const n = ds.getRowCount();
              const take = Math.min(n, 10);
              const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
              results.push({ ok: true, n, cols, rows });
            } catch (e) { results.push({ ok: false, reason: String(e).slice(0,150) }); }
          }
          return { ok: true, grids: results };
        }""", abdocu_no)
        print(f"[B3] 조회(결의서번호={abdocu_no}) 후 가시 그리드 덤프 n_grids="
              f"{len(visible_grid_dump.get('grids', []))}", flush=True)
        for i, gd in enumerate(visible_grid_dump.get("grids", [])):
            if gd.get("ok"):
                print(f"[B3] grid[{i}] n={gd.get('n')} cols={[c['field'] for c in gd.get('cols', [])]}", flush=True)
            else:
                print(f"[B3] grid[{i}] FAIL {gd}", flush=True)
        report["phase_b3"] = {"abdocu_no": abdocu_no, "grids": visible_grid_dump}
        (ARTIFACTS / "voucher_card_discover_b3_grids.json").write_text(
            json.dumps(visible_grid_dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_discover_b3_result.png"), full_page=True)

        # grid[0] 마스터행에서 결재번호(GWDOCU_NO, 헤더='결재번호') 추출 — Phase C 참조문서
        # 문서번호 후보(가설: PROCESS.md의 '결제번호'가 실은 이 필드).
        gwdocu_no = None
        g0 = (visible_grid_dump.get("grids") or [{}])[0]
        if g0.get("ok") and g0.get("rows"):
            gwdocu_no = g0["rows"][0].get("GWDOCU_NO")
        print(f"[B3] 결재번호(GWDOCU_NO, 참조문서 후보) = {gwdocu_no!r}", flush=True)
        report["phase_b3"]["gwdocu_no"] = gwdocu_no

        # ── Phase C0: 전표조회승인 탭으로 복귀 → 상태 보존(캐시) 확인 ────────────
        print("\n===== PHASE C0: 전표조회승인 탭 복귀 =====", flush=True)
        tab_back_sel = 'li.tab-item:has-text("전표조회승인")'
        await raw_page.click(tab_back_sel, timeout=5_000)
        await page.wait_for_timeout(1_000)
        back_grid = await raw_page.evaluate(r"""() => {
          const grids = [...document.querySelectorAll('.dews-ui-grid')].filter(el => el.offsetParent !== null);
          if (!grids.length) return { ok: false };
          try {
            const g = window.jQuery(grids[0]).data('dewsControl')._grid;
            return { ok: true, n: g.getDataSource().getRowCount() };
          } catch (e) { return { ok: false, reason: String(e) }; }
        }""")
        print(f"[C0] 복귀 후 첫 가시그리드 = {back_grid} (Phase A rowcount=9 와 비교, 재조회 없이 유지되면 탭 캐시 확인)", flush=True)
        report["phase_c0"] = {"back_grid": back_grid}
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_discover_c0_tab_back.png"), full_page=True)

        # ── Phase C1: 1건 체크 → 결제(EAP) 팝업 열기(딱 1건만 — draft 최소화) ────
        print("\n===== PHASE C1: 결제(EAP) 팝업 열기 =====", flush=True)
        key0 = await vr_steps.read_row_key(page, 0)
        print(f"[C1] 대상 행0 DOCU_NO = {key0}", flush=True)
        await vr_steps.uncheck_all_rows(page)
        checked = await vr_steps.check_row(page, 0)
        print(f"[C1] checkRow(0) = {checked}", flush=True)
        child = await vr_steps.open_approval(page)
        if child is None:
            print("[C1] FAIL: 결제창(별도 팝업)이 열리지 않음 — Phase C 중단", flush=True)
            report["phase_c1"] = {"error": "no-child-page"}
        else:
            print(f"[C1] 결제창 열림 url={child.url}", flush=True)
            top = await vr_steps.poll_child_ready(child)
            print(f"[C1] 결제창 상단 버튼 = {top}", flush=True)
            child_docu = await vr_steps.read_child_docu_no(child)
            print(f"[C1] 결제창 표시 전표번호 후보 = {child_docu} (대상 {key0} 와 대조)", flush=True)
            await child.screenshot(path=str(ARTIFACTS / "voucher_card_discover_c1_child.png"), full_page=True)
            report["phase_c1"] = {"key0": key0, "top": top, "child_docu": child_docu, "url": child.url}

            # ── Phase C2: '참조문서 선택' 버튼 탐색(읽기전용, 리프 텍스트 스캔) ──
            print("\n===== PHASE C2: '참조문서 선택' 버튼 탐색 =====", flush=True)
            ref_btn_scan = await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const out = [];
              for (const el of document.querySelectorAll('*')) {
                if (el.children.length > 0) continue;
                const t = c(el.innerText || el.textContent || '');
                if (t && t.includes('참조문서')) {
                  const r = el.getBoundingClientRect();
                  out.push({ tag: el.tagName, cls: (el.className||'').toString().slice(0,80), text: t,
                    x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), visible: el.offsetParent !== null });
                }
              }
              return out;
            }""")
            print(f"[C2] '참조문서' 텍스트 매치 = {json.dumps(ref_btn_scan, ensure_ascii=False)}", flush=True)
            report["phase_c2"] = {"ref_btn_scan": ref_btn_scan}

            # ⚠ 자가수정(가설 1개): 정확 텍스트 '참조문서' 매치 0건 — 라벨이 다르거나(관련문서/
            # 문서첨부 등) 아이콘 전용 버튼(title/aria-label)일 수 있다. 전체 클릭가능 요소+
            # 문서 관련 키워드로 넓게 재탐색.
            wide_scan = await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const kws = ['참조', '관련문서', '문서첨부', '첨부문서', '문서선택', '연결문서'];
              const out = [];
              for (const el of document.querySelectorAll('button, a, [role=button], [onclick], input[type=button]')) {
                const t = c(el.innerText || el.value || el.title || el.getAttribute('aria-label') || '');
                if (!t) continue;
                if (kws.some(k => t.includes(k))) {
                  const r = el.getBoundingClientRect();
                  out.push({ tag: el.tagName, cls: (el.className||'').toString().slice(0,80), text: t,
                    x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), visible: el.offsetParent !== null });
                }
              }
              return out;
            }""")
            print(f"[C2] 넓은 키워드 매치 = {json.dumps(wide_scan, ensure_ascii=False)}", flush=True)
            report["phase_c2"]["wide_scan"] = wide_scan

            page_height = await child.evaluate("() => document.body.scrollHeight")
            print(f"[C2] child 페이지 전체 높이 = {page_height}", flush=True)
            report["phase_c2"]["page_height"] = page_height

            # ⚠ 자가수정(가설 2개 후보 — iframe 격리 vs 전체 버튼 목록): 키워드 매치 0건 지속 —
            # (a) EAP 문서뷰가 cross-origin iframe 안에 있어 top document.querySelectorAll 이
            # 못 미칠 수 있다, (b) 그냥 화면에 있는 모든 버튼을 라벨 없이 덤프해 육안 대조.
            iframes = await child.evaluate(r"""() => [...document.querySelectorAll('iframe')].map(f => ({
              src: f.src, id: f.id || null, cls: (f.className||'').toString().slice(0,80),
              w: f.getBoundingClientRect().width, h: f.getBoundingClientRect().height,
            }))""")
            print(f"[C2] iframe 목록 = {json.dumps(iframes, ensure_ascii=False)}", flush=True)

            all_buttons = await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const out = [];
              for (const el of document.querySelectorAll('button, a, [role=button], input[type=button]')) {
                const t = c(el.innerText || el.value || el.title || el.getAttribute('aria-label') || '');
                const r = el.getBoundingClientRect();
                out.push({ tag: el.tagName, text: t.slice(0,30), x: Math.round(r.x), y: Math.round(r.y),
                  visible: el.offsetParent !== null });
              }
              return out;
            }""")
            print(f"[C2] 전체 버튼/링크 목록(n={len(all_buttons)}) = {json.dumps(all_buttons, ensure_ascii=False)}", flush=True)
            report["phase_c2"]["iframes"] = iframes
            report["phase_c2"]["all_buttons"] = all_buttons

            # '선택'(222,1635) 버튼 주변 컨텍스트 텍스트 — 어느 라벨(참조문서 후보)에 속하는지.
            select_btn_ctx = await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const btns = [...document.querySelectorAll('button')].filter(b => c(b.innerText) === '선택');
              return btns.map(b => {
                const row = b.closest('tr') || b.closest('li') || b.parentElement.parentElement;
                const r = b.getBoundingClientRect();
                return { text: c(b.innerText), x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2),
                  rowText: row ? c(row.innerText).slice(0, 200) : null };
              });
            }""")
            print(f"[C2] '선택' 버튼 컨텍스트 = {json.dumps(select_btn_ctx, ensure_ascii=False)}", flush=True)
            report["phase_c2"]["select_btn_ctx"] = select_btn_ctx

            await child.mouse.wheel(0, 1600)
            await child.wait_for_timeout(500)
            await child.screenshot(path=str(ARTIFACTS / "voucher_card_discover_c2_scrolled.png"))

            # ── Phase C3: '참조문서 선택'(실제 라벨 '참 조 문 서'…'선택') dialog 오픈 — 구조만 ──
            # ⚠ 자가수정(가설 2, 직전 시도 no-dialog-found 반복): LIVE_VIEWPORT=1440×900 인데
            # 버튼 y≈1635~1649 로 **뷰포트 밖**(스크롤 필요) — child.mouse.wheel(0,1600) 은
            # 기본 마우스 위치(0,0, 상단 고정 헤더 위)에 대고 휠 이벤트를 쏴 내부 스크롤 컨테이너를
            # 못 움직였다(좌표가 스크롤 전후 동일했던 이유). element.scrollIntoView 로 실제
            # 스크롤 컨테이너를 움직인 뒤 좌표를 재계산해서 클릭.
            print("\n===== PHASE C3: 참조문서 선택 dialog 오픈(구조만, 확인/상신 금지) =====", flush=True)
            await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const b = [...document.querySelectorAll('button')].find(b => c(b.innerText) === '선택');
              if (b) b.scrollIntoView({ block: 'center' });
            }""")
            await child.wait_for_timeout(500)  # smooth-scroll 애니메이션 정착 대기.
            fresh_sel = await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const btns = [...document.querySelectorAll('button')].filter(b => c(b.innerText) === '선택');
              const b = btns[0];
              if (!b) return null;
              const r = b.getBoundingClientRect();
              return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
            }""")
            print(f"[C3] scrollIntoView 후 재계산 좌표 = {fresh_sel}", flush=True)
            if fresh_sel:
                await child.mouse.click(fresh_sel["x"], fresh_sel["y"])
                await child.wait_for_timeout(1_500)
                await child.screenshot(path=str(ARTIFACTS / "voucher_card_discover_c3_dialog.png"))

                dialog_dump = await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  // ⚠ 자가수정(가설 1개): k-window/modal/[role=dialog] 등 범용 셀렉터로 못 찾음
                  // (스크린샷 확인 결과 dialog 는 실제로 열려 있음) — '참조문서' 제목 텍스트를
                  // 가진 요소에서 위로 올라가며 '충분히 큰'(폭>400,높이>300) 컨테이너를 찾는다.
                  const heading = [...document.querySelectorAll('*')].find(
                    el => el.children.length === 0 && c(el.innerText) === '참조문서'
                  );
                  if (!heading) return { ok: false, reason: 'no-heading-참조문서' };
                  let dlg = heading;
                  for (let i = 0; i < 8 && dlg; i++) {
                    const r = dlg.getBoundingClientRect();
                    if (r.width > 400 && r.height > 300) break;
                    dlg = dlg.parentElement;
                  }
                  if (!dlg) return { ok: false, reason: 'no-container-found' };
                  const inputs = [...dlg.querySelectorAll('input, select, button, [role=checkbox]')].map(el => {
                    const r = el.getBoundingClientRect();
                    return { tag: el.tagName, type: el.type || null, id: el.id || null,
                      cls: (el.className||'').toString().slice(0,80),
                      text: c(el.innerText || el.value || el.placeholder || ''),
                      x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), visible: el.offsetParent !== null };
                  });
                  const tables = [...dlg.querySelectorAll('table, [role=grid], .k-grid, [class*=grid]')].map(g => {
                    const r = g.getBoundingClientRect();
                    return { tag: g.tagName, cls: (g.className||'').toString().slice(0,100),
                      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
                  });
                  return { ok: true, dlgTag: dlg.tagName, dlgCls: (dlg.className||'').toString().slice(0,150),
                    inputs, tables, html_len: dlg.outerHTML.length };
                }""")
                print(f"[C3] dialog 덤프 = {json.dumps(dialog_dump, ensure_ascii=False)}", flush=True)
                report["phase_c3"] = {"dialog_dump": dialog_dump}
                (ARTIFACTS / "voucher_card_discover_c3_dialog.json").write_text(
                    json.dumps(dialog_dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )

                # ── Phase C4: 필터 확장(collapse 토글) → 문서번호 입력란 탐색 → 조회(읽기전용) ──
                print("\n===== PHASE C4: 필터 확장 → 문서번호 입력 → 조회(읽기전용) =====", flush=True)
                await child.click("#tutorial-conditionPanel-collapse")
                await child.wait_for_timeout(800)
                expanded_labels = await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const heading = [...document.querySelectorAll('*')].find(
                    el => el.children.length === 0 && c(el.innerText) === '참조문서'
                  );
                  let dlg = heading;
                  for (let i = 0; i < 8 && dlg; i++) {
                    const r = dlg.getBoundingClientRect();
                    if (r.width > 400 && r.height > 300) break;
                    dlg = dlg.parentElement;
                  }
                  if (!dlg) return [];
                  const out = [];
                  for (const lbl of dlg.querySelectorAll('label, [class*=label], [class*=Label]')) {
                    if (lbl.children.length > 1) continue;
                    const t = c(lbl.innerText);
                    if (!t) continue;
                    const row = lbl.closest('[class*=row]') || lbl.parentElement;
                    const inp = row ? row.querySelector('input') : null;
                    const r2 = inp ? inp.getBoundingClientRect() : null;
                    out.push({ label: t, inputVisible: !!inp && inp.offsetParent !== null,
                      x: r2 ? Math.round(r2.x+r2.width/2) : null, y: r2 ? Math.round(r2.y+r2.height/2) : null });
                  }
                  return out;
                }""")
                print(f"[C4] 확장 후 라벨 목록 = {json.dumps(expanded_labels, ensure_ascii=False)}", flush=True)
                report["phase_c4"] = {"expanded_labels": expanded_labels}
                await child.screenshot(path=str(ARTIFACTS / "voucher_card_discover_c4_expanded.png"))

                # '결재함' 드롭다운 옵션(전체/기안문서/수신문서 등 스코프 후보) — 읽기전용.
                gyeoljaeham_options = await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const lbl = [...document.querySelectorAll('label, [class*=label], [class*=Label]')]
                    .find(el => el.children.length <= 1 && c(el.innerText) === '결재함');
                  if (!lbl) return null;
                  const row = lbl.closest('[class*=row]') || lbl.parentElement;
                  const sel = row ? row.querySelector('select') : null;
                  if (sel) return [...sel.options].map(o => o.text);
                  // select 가 아니면 커스텀 드롭다운 — 현재 표시값만.
                  const disp = row ? row.querySelector('[class*=value], [class*=Value], input') : null;
                  return disp ? [c(disp.innerText || disp.value)] : null;
                }""")
                print(f"[C4] 결재함 드롭다운 옵션/현재값 = {json.dumps(gyeoljaeham_options, ensure_ascii=False)}", flush=True)
                report["phase_c4"]["gyeoljaeham_options"] = gyeoljaeham_options

                # ── Phase C5: 문서번호=GWDOCU_NO 입력 → 조회(읽기전용) → 매칭 확인 ────
                print("\n===== PHASE C5: 문서번호=결재번호(GWDOCU_NO) 조회(읽기전용) =====", flush=True)
                doc_no_rect = await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const lbl = [...document.querySelectorAll('label, [class*=label], [class*=Label]')]
                    .find(el => el.children.length <= 1 && c(el.innerText) === '문서번호');
                  if (!lbl) return null;
                  const row = lbl.closest('[class*=row]') || lbl.parentElement;
                  const inp = row ? row.querySelector('input') : null;
                  if (!inp) return null;
                  const r = inp.getBoundingClientRect();
                  return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
                }""")
                print(f"[C5] 문서번호 입력란 좌표 = {doc_no_rect}", flush=True)
                if doc_no_rect and gwdocu_no:
                    await child.mouse.click(doc_no_rect["x"], doc_no_rect["y"])
                    await child.keyboard.type(gwdocu_no)
                    await child.wait_for_timeout(300)
                    await child.screenshot(path=str(ARTIFACTS / "voucher_card_discover_c5_before_search.png"))
                    # ⚠ 자가수정(가설 2, 직전 시도 search_rect=None): 스크린샷 확인 결과 필터
                    # 확장 후 원래 아이콘 전용 '#tutorial-conditionPanel-search' 버튼은 사라지고
                    # 필터 아래 텍스트 '조회' 버튼이 새로 나타났다 — id 대신 텍스트로 재탐색.
                    search_rect = await child.evaluate(r"""() => {
                      const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                      const b = [...document.querySelectorAll('button')].find(b => c(b.innerText) === '조회');
                      if (!b) return null;
                      const r = b.getBoundingClientRect();
                      return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), visible: b.offsetParent !== null };
                    }""")
                    print(f"[C5] 조회버튼 rect = {search_rect}", flush=True)
                    if search_rect:
                        await child.mouse.click(search_rect["x"], search_rect["y"])
                    await child.wait_for_timeout(1_500)
                    filtered = await child.evaluate(r"""() => {
                      const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                      const heading = [...document.querySelectorAll('*')].find(
                        el => el.children.length === 0 && c(el.innerText) === '참조문서'
                      );
                      let dlg = heading;
                      for (let i = 0; i < 8 && dlg; i++) {
                        const r = dlg.getBoundingClientRect();
                        if (r.width > 400 && r.height > 300) break;
                        dlg = dlg.parentElement;
                      }
                      if (!dlg) return null;
                      const grid = dlg.querySelector('.OBTListGrid_grid__2v2Bh');
                      if (!grid) return null;
                      const rowsText = [...grid.querySelectorAll('[class*=row], [class*=Row]')]
                        .map(r => c(r.innerText)).filter(t => t).slice(0, 10);
                      return { rowsText };
                    }""")
                    print(f"[C5] 조회 후 목록 행 텍스트 = {json.dumps(filtered, ensure_ascii=False)}", flush=True)
                    report["phase_c5"] = {"doc_no_rect": doc_no_rect, "filtered": filtered}
                    await child.screenshot(path=str(ARTIFACTS / "voucher_card_discover_c5_filtered.png"))
                else:
                    print("[C5] SKIP: 문서번호 입력란 좌표를 못 찾았거나 gwdocu_no 없음", flush=True)
                    report["phase_c5"] = {"error": "no-input-or-no-gwdocu"}

                # dialog 닫기(X) — 확인/선택 절대 미클릭.
                close_rect = await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const heading = [...document.querySelectorAll('*')].find(
                    el => el.children.length === 0 && c(el.innerText) === '참조문서'
                  );
                  let dlg = heading;
                  for (let i = 0; i < 8 && dlg; i++) {
                    const r = dlg.getBoundingClientRect();
                    if (r.width > 400 && r.height > 300) break;
                    dlg = dlg.parentElement;
                  }
                  if (!dlg) return null;
                  const btn = dlg.querySelector('button');
                  if (!btn) return null;
                  const r = btn.getBoundingClientRect();
                  return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
                }""")
                if close_rect:
                    await child.mouse.click(close_rect["x"], close_rect["y"])
                    await child.wait_for_timeout(500)
                    print(f"[C5] dialog 닫기(X) 클릭 = {close_rect} (확인/선택 미클릭)", flush=True)
            else:
                print("[C3] SKIP: '선택' 버튼을 재탐색에서 찾지 못함", flush=True)
                report["phase_c3"] = {"error": "no-select-btn"}

            try:
                await vr_steps.close_child(child)
                print("[C1/C2] 결제창 닫음(상신/보관 미클릭, 비영속 확정)", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[경고] 결제창 닫기 실패(무시): {exc}", flush=True)

    finally:
        (ARTIFACTS / "voucher_card_discover_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"\n[artifact] {ARTIFACTS / 'voucher_card_discover_report.json'}", flush=True)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
