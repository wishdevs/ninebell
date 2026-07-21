"""읽기전용 타깃 검증 — 미지급금 법인카드 참조문서 검색 0건 원인(결재함 스코프 vs 특정 번호) 확정.

오케스트레이터 지시(2026-07-21): 사용자 확정 "결제번호=GWDOCU_NO(결재번호)"가 맞다는 전제 하에,
GWDOCU_NO 로 참조문서 검색 시 0건이었던 원인을 라이브로 하나만 확정한다 — 결재함 드롭다운
스코프 또는 테스트했던 특정 번호(참조문서 없는 건) 여부.

절차: 전표조회승인(일반) 조회 → 결의서조회승인(GLDDOC00400)에서 **결의구분=카드** 필터로 조회
→ 결과 1건의 ABDOCU_NO/GWDOCU_NO/DOCU_NO 확정(매핑) → 전표조회승인 탭 복귀 → 그 행(DOCU_NO)의
결제(EAP) 팝업 1건만 열기 → 참조문서 선택 → 필터 확장 → 문서번호=GWDOCU_NO 입력 → **결재함
드롭다운 옵션 덤프** → 옵션별로 몇 개 시도 → 매치 확인.

⚠ 절대 안전: 항목 선택·아래버튼·확인·상신 전부 미클릭. dialog 취소·결제창 close. 결제창은
정확히 1건만 연다.

Usage:
    cd backend && .venv/bin/python e2e/voucher_card_refdoc_verify_probe.py
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
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.omnisol.modals import dismiss_blocking_modals, dismiss_notice_popup  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

from app.agents.voucher_receivable import js as vr_js  # noqa: E402
from app.agents.voucher_receivable import steps as vr_steps  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

C = lambda s: (s or "")  # noqa: E731 — placeholder, real normalize done in-page.

VISIBLE_GRIDS_DUMP_JS = r"""(limit) => {
  const grids = [...document.querySelectorAll('.dews-ui-grid')].filter(el => el.offsetParent !== null);
  const results = [];
  for (const el of grids) {
    try {
      const ctrl = window.jQuery(el).data('dewsControl');
      const g = ctrl && ctrl._grid;
      if (!g) { results.push({ ok: false, reason: 'no-dewsControl' }); continue; }
      const cols = g.getColumns().map(c => ({ field: c.fieldName, header: (c.header && c.header.text) || c.name }));
      const ds = g.getDataSource();
      const n = ds.getRowCount();
      const take = Math.min(n, limit || 10);
      const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
      results.push({ ok: true, n, cols, rows });
    } catch (e) { results.push({ ok: false, reason: String(e).slice(0,150) }); }
  }
  return results;
}"""

VISIBLE_LOOKUP_BTN_RECT_JS = r"""() => {
  const btns = [...document.querySelectorAll('button.main-button.lookup')].filter(b => b.offsetParent !== null);
  if (!btns.length) return null;
  const r = btns[0].getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    context = await browser.new_context(viewport=LIVE_VIEWPORT)
    raw_page = await context.new_page()
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    report: dict = {}
    child = None

    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, base)
        await page.wait_for_timeout(1_500)

        # ── Phase A: 전표조회승인(전표유형=일반) 조회 ────────────────────────
        print("\n===== PHASE A: 전표조회승인(전표유형=일반) 조회 =====", flush=True)
        await vr_steps.expand_condition_panel(page)
        await vr_steps.set_dept_all(page)
        await vr_steps.set_period_this_month(page)
        await vr_steps.clear_writer(page)
        await vr_steps.set_docu_status(page)
        await vr_steps.set_gwaprvlst(page)
        await vr_steps.set_docu_types(page, ("일반",))
        rq = await vr_steps.run_query(page)
        print(f"[A] 조회 실행 = {rq}", flush=True)

        # ── Phase B: 결의서조회승인 탭 열기 → 결의구분=카드 조회 ────────────
        print("\n===== PHASE B: 결의서조회승인 탭 → 결의구분=카드 조회 =====", flush=True)
        await dismiss_notice_popup(page, appear_cap_ms=0)
        await dismiss_blocking_modals(page, rounds=1)
        link_sel = 'a.nav-text[href="/FI/GLDDOC00400"]'
        try:
            await raw_page.click(link_sel, timeout=8_000)
        except Exception as exc:  # noqa: BLE001
            print(f"[B] 1차 클릭 실패({exc.__class__.__name__}) — 재시도", flush=True)
            await dismiss_notice_popup(page, appear_cap_ms=0)
            await dismiss_blocking_modals(page, rounds=1)
            await raw_page.click(link_sel, timeout=8_000)
        await page.wait_for_timeout(2_000)

        # 결의부서 전체선택 + 결의자 비움(D6 순서).
        if await vr_steps._open_picker(page, "결의부서"):
            await raw_page.evaluate(vr_js.POPUP_CHECK_ALL_JS)
            await vr_steps._apply_popup(page)
        await raw_page.evaluate(
            "() => { try { window.jQuery(document.querySelector('#WRT_EMP_NO_C'))"
            ".data('dewsControl').clear(); return true; } catch (e) { return String(e); } }"
        )
        await page.wait_for_timeout(500)

        # 결의구분 = 카드 (native dews dropdownlist, KENDO_SET_DROPDOWN_BY_TEXT_JS 재사용).
        gubun_res = await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": "#ABDOCU_FG_CD", "text": "카드"}
        )
        print(f"[B] 결의구분=카드 세팅 = {gubun_res}", flush=True)
        await page.wait_for_timeout(500)

        lookup_rect = await raw_page.evaluate(VISIBLE_LOOKUP_BTN_RECT_JS)
        print(f"[B] 가시 조회버튼 rect = {lookup_rect}", flush=True)
        if lookup_rect:
            await mouse_click(page, lookup_rect["x"], lookup_rect["y"])
        else:
            await js_click(page, selectors.BTN_LOOKUP)
        await page.wait_for_timeout(2_000)

        grids = await raw_page.evaluate(VISIBLE_GRIDS_DUMP_JS, 10)
        g0 = grids[0] if grids else {}
        print(f"[B] 결의구분=카드 조회 결과 grid[0].n = {g0.get('n')}", flush=True)
        report["phase_b"] = {"gubun_res": gubun_res, "grid0": g0}
        (ARTIFACTS / "voucher_card_refdoc_b_grid0.json").write_text(
            json.dumps(g0, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_card_refdoc_b_result.png"), full_page=True)

        if not (g0.get("ok") and g0.get("n")):
            print("[B] FAIL: 결의구분=카드 결과 0건 — 중단", flush=True)
            return

        row0 = g0["rows"][0]
        target_abdocu_no = row0.get("ABDOCU_NO")
        target_gwdocu_no = row0.get("GWDOCU_NO")
        target_docu_no = row0.get("DOCU_NO")
        print(
            f"[B] 매핑: ABDOCU_NO={target_abdocu_no!r} GWDOCU_NO={target_gwdocu_no!r} "
            f"DOCU_NO={target_docu_no!r}",
            flush=True,
        )
        report["mapping"] = {
            "abdocu_no": target_abdocu_no,
            "gwdocu_no": target_gwdocu_no,
            "docu_no": target_docu_no,
        }

        # ── Phase C: 전표조회승인 탭 복귀 → 대상 행 찾기 → 결제(EAP) 팝업 1건 ──
        print("\n===== PHASE C: 전표조회승인 탭 복귀 → 대상 행 체크 → 결제창 =====", flush=True)
        await raw_page.click('li.tab-item:has-text("전표조회승인")', timeout=5_000)
        await page.wait_for_timeout(1_000)

        master_dump = await raw_page.evaluate(r"""() => {
          const grids = [...document.querySelectorAll('.dews-ui-grid')].filter(el => el.offsetParent !== null);
          if (!grids.length) return { ok: false };
          try {
            const g = window.jQuery(grids[0]).data('dewsControl')._grid;
            const ds = g.getDataSource();
            const n = ds.getRowCount();
            const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
            return { ok: true, n, rows: rows.map(r => r.DOCU_NO) };
          } catch (e) { return { ok: false, reason: String(e) }; }
        }""")
        print(f"[C] 마스터 DOCU_NO 목록 = {master_dump}", flush=True)
        idx = None
        if master_dump.get("ok"):
            docu_nos = master_dump.get("rows", [])
            if target_docu_no in docu_nos:
                idx = docu_nos.index(target_docu_no)
        print(f"[C] 대상 행 idx = {idx}", flush=True)
        report["phase_c_row_idx"] = idx

        if idx is None:
            print("[C] FAIL: 대상 DOCU_NO 행을 전표조회승인 마스터에서 찾지 못함 — 중단", flush=True)
            return

        await vr_steps.uncheck_all_rows(page)
        checked = await vr_steps.check_row(page, idx)
        print(f"[C] checkRow({idx}) = {checked}", flush=True)
        child = await vr_steps.open_approval(page)
        if child is None:
            print("[C] FAIL: 결제창이 열리지 않음 — 중단", flush=True)
            return
        print(f"[C] 결제창 열림 url={child.url}", flush=True)
        top = await vr_steps.poll_child_ready(child)
        child_docu = await vr_steps.read_child_docu_no(child)
        print(f"[C] 결제창 상단버튼={top} / 표시 전표번호={child_docu} (대상 {target_docu_no})", flush=True)
        report["phase_c_child"] = {"top": top, "child_docu": child_docu}

        # ── Phase D: 참조문서 선택 dialog → 필터 확장 → 결재함 옵션 덤프 ────
        print("\n===== PHASE D: 참조문서 선택 → 결재함 옵션 덤프 =====", flush=True)
        await child.evaluate(r"""() => {
          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
          const b = [...document.querySelectorAll('button')].find(b => {
            const row = b.closest('tr') || b.closest('li') || (b.parentElement && b.parentElement.parentElement);
            return row && c(row.innerText).replace(/\s+/g,'').includes('참조문서');
          });
          if (b) b.scrollIntoView({ block: 'center' });
        }""")
        await child.wait_for_timeout(500)
        sel_rect = await child.evaluate(r"""() => {
          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
          const b = [...document.querySelectorAll('button')].find(b => {
            const row = b.closest('tr') || b.closest('li') || (b.parentElement && b.parentElement.parentElement);
            return row && c(row.innerText).replace(/\s+/g,'').includes('참조문서');
          });
          if (!b) return null;
          const r = b.getBoundingClientRect();
          return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
        }""")
        print(f"[D] '참조문서 선택' 버튼 좌표 = {sel_rect}", flush=True)
        if not sel_rect:
            print("[D] FAIL: 참조문서 선택 버튼을 못 찾음 — 중단", flush=True)
            return
        await child.mouse.click(sel_rect["x"], sel_rect["y"])
        await child.wait_for_timeout(1_500)

        await child.click("#tutorial-conditionPanel-collapse")
        await child.wait_for_timeout(800)
        await child.screenshot(path=str(ARTIFACTS / "voucher_card_refdoc_d_expanded.png"))

        # 결재함 드롭다운 — ⚠ 자가수정(가설 1개, 직전 시도로 라벨 자체를 오클릭 확인):
        # 라벨 "결재함"의 행(row)에서 마지막 큰 자손을 트리거로 가정했더니 실제로는 라벨의
        # 툴팁 래퍼(OBTConditionItem_labelTextOverflowTooltip, 라벨과 같은 위치)를 잡았다
        # (스크린샷: 클릭해도 드롭다운이 안 열림) — 현재 표시값 텍스트('전체')를 가진 리프
        # 요소를 라벨과 별개로 직접 찾아 그 좌표를 트리거로 쓴다.
        gyeoljaeham_trigger = await child.evaluate(r"""() => {
          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
          const lbl = [...document.querySelectorAll('*')].find(
            el => el.children.length === 0 && c(el.innerText) === '결재함'
          );
          if (!lbl) return null;
          const lblRect = lbl.getBoundingClientRect();
          // '결재함' 라벨과 같은 세로대(±15px) 안에서, 라벨 자신이 아니면서 현재 값 텍스트를
          // 담은 리프 요소(예: '전체')를 찾는다 — 라벨보다 오른쪽에 있어야 값 박스다.
          const candidates = [...document.querySelectorAll('*')].filter(el => {
            if (el === lbl || el.children.length > 0) return false;
            const r = el.getBoundingClientRect();
            if (r.width <= 0) return false;
            return Math.abs(r.y - lblRect.y) < 15 && r.x > lblRect.x;
          });
          if (!candidates.length) return null;
          const el = candidates[0];
          const r = el.getBoundingClientRect();
          return { kind: 'custom', text: c(el.innerText), cls: (el.className||'').toString().slice(0,80),
            x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
        }""")
        print(f"[D] 결재함 트리거 = {gyeoljaeham_trigger}", flush=True)
        report["gyeoljaeham_trigger"] = gyeoljaeham_trigger

        gyeoljaeham_options: list[str] = []
        if gyeoljaeham_trigger:
            if gyeoljaeham_trigger["kind"] == "select":
                gyeoljaeham_options = await child.evaluate(
                    r"""(pt) => {
                      const el = document.elementFromPoint(pt.x, pt.y);
                      const sel = el && el.closest ? el.closest('select') : null;
                      return sel ? [...sel.options].map(o => o.text) : [];
                    }""",
                    {"x": gyeoljaeham_trigger["x"], "y": gyeoljaeham_trigger["y"]},
                )
            else:
                await child.mouse.click(gyeoljaeham_trigger["x"], gyeoljaeham_trigger["y"])
                await child.wait_for_timeout(500)
                await child.screenshot(path=str(ARTIFACTS / "voucher_card_refdoc_d_dropdown_open.png"))
                # ⚠ 자가수정(가설 1개, 직전 시도 옵션 0개 — 스크린샷엔 7개 옵션이 보임):
                # `children.length===0`(리프 전용) 필터가 `<li><span>텍스트</span></li>` 같은
                # 중첩 구조를 걸러냈다 — 리프 제약 제거, `li` 자체 텍스트를 그대로 읽는다.
                gyeoljaeham_options = await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const opts = [...document.querySelectorAll('li, div[role=option], [class*=option], [class*=Option]')]
                    .filter(el => el.offsetParent !== null)
                    .map(el => c(el.innerText)).filter(t => t && t.length > 0 && t.length < 20 && !t.includes('\n'));
                  return [...new Set(opts)];
                }""")
                # 드롭다운을 다시 닫는다(다음 단계에서 문서번호 필드로 이동하기 전 정리).
                await child.mouse.click(gyeoljaeham_trigger["x"], gyeoljaeham_trigger["y"])
                await child.wait_for_timeout(300)
        print(f"[D] 결재함 옵션 목록 = {gyeoljaeham_options}", flush=True)
        report["gyeoljaeham_options"] = gyeoljaeham_options

        # ── Phase E: 옵션별 문서번호=GWDOCU_NO 조회 시도 ────────────────────
        print("\n===== PHASE E: 결재함 옵션별 문서번호=GWDOCU_NO 조회 시도 =====", flush=True)

        async def fill_doc_no_and_search(value: str) -> dict:
            # ⚠ 자가수정: 직전 시도가 `inp.value=''` 직접 DOM 조작으로 지웠는데 React 컨트롤드
            # 인풋이라 실제 상태는 안 바뀌었다(스크린샷으로 확인: 여전히 이전 값 표시,
            # setValue 오염과 동일 패턴) — 항상 **클릭+Ctrl/Cmd+A+키보드 타이핑**만 사용.
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
            if not doc_no_rect:
                return {"ok": False, "reason": "no-doc-no-input"}
            async def _read_doc_no_value() -> str | None:
                return await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const lbl = [...document.querySelectorAll('label, [class*=label], [class*=Label]')]
                    .find(el => el.children.length <= 1 && c(el.innerText) === '문서번호');
                  if (!lbl) return null;
                  const row = lbl.closest('[class*=row]') || lbl.parentElement;
                  const inp = row ? row.querySelector('input') : null;
                  return inp ? inp.value : null;
                }""")

            # ⚠ 자가수정(가설 1개, 직전 시도 Ctrl+A+Backspace 로 클리어 실패 확인 —
            # readback 이 이전 값 그대로였음): 이 커스텀 인풋이 Ctrl+A 를 안 받는 것으로
            # 보임 — End 후 **Backspace 40회**(길이 상한 이상)로 어떤 길이 값도 강제 삭제.
            await child.mouse.click(doc_no_rect["x"], doc_no_rect["y"])
            await child.keyboard.press("End")
            for _ in range(40):
                await child.keyboard.press("Backspace")
            if value:
                await child.keyboard.type(value)
            await child.wait_for_timeout(300)
            actual_value = await _read_doc_no_value()
            if actual_value != value:
                await child.mouse.click(doc_no_rect["x"], doc_no_rect["y"])
                await child.keyboard.press("End")
                for _ in range(40):
                    await child.keyboard.press("Backspace")
                if value:
                    await child.keyboard.type(value)
                await child.wait_for_timeout(300)
                actual_value = await _read_doc_no_value()
            search_rect = await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const b = [...document.querySelectorAll('button')].find(b => c(b.innerText) === '조회');
              if (!b) return null;
              const r = b.getBoundingClientRect();
              return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
            }""")
            if not search_rect:
                return {"ok": False, "reason": "no-search-button", "actual_value": actual_value}
            await child.mouse.click(search_rect["x"], search_rect["y"])
            # ⚠ 자가수정(가설 1개, 직전 시도 Phase F 무필터 덤프가 빈 결과로 오판됨 — 스크린샷
            # 대조 결과 실제로는 564건 리스트가 정상 렌더돼 있었음): 고정 1.5s 대기 후 1회
            # 판독은 **가상 그리드(564행) 렌더가 느린 케이스**에서 타이밍에 걸린다(0건 '없음'
            # 메시지는 빠르게 뜨지만 대량 리스트 렌더는 더 걸림) — 조건 폴링으로 전환.
            result: dict = {"docNoMatches": [], "noDataText": None}
            re_pattern = __import__("re").compile(r"\(주\)나인벨-\d{4}-\d+")
            for _ in range(8):  # 최대 ~4s(500ms×8), 매치·'없음' 메시지 중 하나라도 뜨면 즉시 break.
                result = await child.evaluate(r"""() => {
                  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                  const re = /\(주\)나인벨-\d{4}-\d+/;
                  const matches = new Set();
                  let noDataText = null;
                  for (const el of document.querySelectorAll('*')) {
                    if (el.children.length > 0) continue;
                    const t = c(el.innerText || el.textContent || '');
                    if (!t) continue;
                    const m = t.match(re);
                    if (m) matches.add(m[0]);
                    if (t.includes('조회된 데이터가 없습니다')) noDataText = t;
                  }
                  return { docNoMatches: [...matches], noDataText };
                }""")
                if result.get("docNoMatches") or result.get("noDataText"):
                    break
                await child.wait_for_timeout(500)
            return {"ok": True, "actual_value": actual_value, "result": result}

        attempts_log = []
        # 시도 1: 결재함 = 현재값(기본 '전체') 그대로.
        r1 = await fill_doc_no_and_search(target_gwdocu_no)
        print(f"[E] 시도1(결재함=기본) = {r1}", flush=True)
        attempts_log.append({"gyeoljaeham": "(기본값)", "result": r1})
        await child.screenshot(path=str(ARTIFACTS / "voucher_card_refdoc_e_attempt1.png"))

        report["attempts"] = attempts_log
        found_any = bool(r1.get("ok") and r1.get("result", {}).get("docNoMatches"))

        # 시도 2+: 결재함 옵션 중 **'기결문서(종결)'을 최우선**(대상 문서 결재상태=종결과 일치)으로,
        # 그 다음 기결문서/상신문서 순으로 재시도(노이즈 옵션 제외, 우선순위 큐레이션).
        priority = ["기결문서(종결)", "기결문서", "상신문서", "수신참조문서", "후결문", "전결함"]
        candidates = [o for o in priority if o in gyeoljaeham_options]
        if not found_any and candidates and gyeoljaeham_trigger:
            for opt in candidates:
                if gyeoljaeham_trigger["kind"] == "custom":
                    await child.mouse.click(gyeoljaeham_trigger["x"], gyeoljaeham_trigger["y"])
                    await child.wait_for_timeout(400)
                    # ⚠ 자가수정: 옵션 추출과 동일하게 리프 제약 제거 — `li` 자체를 클릭.
                    clicked = await child.evaluate(
                        r"""(text) => {
                          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                          const el = [...document.querySelectorAll('li, div[role=option], [class*=option], [class*=Option]')]
                            .find(el => el.offsetParent !== null && c(el.innerText) === text);
                          if (!el) return false;
                          el.click();
                          return true;
                        }""",
                        opt,
                    )
                    print(f"[E] 결재함 옵션 '{opt}' 클릭 = {clicked}", flush=True)
                    await child.wait_for_timeout(400)
                r = await fill_doc_no_and_search(target_gwdocu_no)
                print(f"[E] 시도(결재함={opt}) = {r}", flush=True)
                attempts_log.append({"gyeoljaeham": opt, "result": r})
                if r.get("ok") and r.get("result", {}).get("docNoMatches"):
                    found_any = True
                    await child.screenshot(path=str(ARTIFACTS / f"voucher_card_refdoc_e_match_{opt}.png"))
                    break

        report["found_any"] = found_any
        report["attempts"] = attempts_log
        print(f"\n[E] 매치 발견 = {found_any}", flush=True)

        # ── Phase F: 여전히 0건이면 무필터 참조문서 목록 첫 페이지 전량 덤프 ──
        if not found_any:
            print("\n===== PHASE F: 무필터 참조문서 목록 첫 페이지 전량 덤프 =====", flush=True)
            # ⚠ 문서번호를 real keyboard clear(Ctrl+A+Backspace, 빈 값 타이핑 없음)로 비움 —
            # 위와 동일한 setValue 오염 방지 헬퍼 재사용.
            rf = await fill_doc_no_and_search("")
            print(f"[F] 무필터 조회 결과(문서번호 정규식 매치) = {rf}", flush=True)
            # 문서번호뿐 아니라 제목/문서분류 등 행 전체 텍스트도 육안 대조용으로 별도 덤프.
            unfiltered_full = await child.evaluate(r"""() => {
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
              if (!dlg) return { text: null };
              const grid = dlg.querySelector('.OBTListGrid_grid__2v2Bh, [class*=OBTListGrid_grid]');
              return { text: grid ? c(grid.innerText).slice(0, 2000) : null };
            }""")
            print(f"[F] 무필터 그리드 전체텍스트(2000자) = {unfiltered_full}", flush=True)
            report["phase_f_unfiltered"] = {"regex_result": rf.get("result"), "full_text": unfiltered_full}
            await child.screenshot(path=str(ARTIFACTS / "voucher_card_refdoc_f_unfiltered.png"))

        # ── Phase G: '조회' 버튼 자체가 이 세션에서 항상 0건인지 최종 격리 테스트 ──
        # dialog 를 닫고 **다시 열어**(같은 결제창 안, EAP 팝업 재오픈 아님) 아무 필드도
        # 건드리지 않은 채(문서번호 등 전부 미터치) 곧장 조회를 눌러본다 — 초기 자동 로드된
        # 564건 목록과 달리 "조회" 클릭 자체가 이 세션에서 항상 0건을 내는지 결정적으로 격리.
        print("\n===== PHASE G: dialog 재오픈 → 필드 미터치 → 곧장 조회 =====", flush=True)
        reopen_close_rect = await child.evaluate(r"""() => {
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
        if reopen_close_rect:
            await child.mouse.click(reopen_close_rect["x"], reopen_close_rect["y"])
            await child.wait_for_timeout(500)
        # '참조문서 선택' 버튼 다시 찾아 재클릭.
        await child.evaluate(r"""() => {
          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
          const b = [...document.querySelectorAll('button')].find(b => {
            const row = b.closest('tr') || b.closest('li') || (b.parentElement && b.parentElement.parentElement);
            return row && c(row.innerText).replace(/\s+/g,'').includes('참조문서');
          });
          if (b) b.scrollIntoView({ block: 'center' });
        }""")
        await child.wait_for_timeout(500)
        reopen_sel_rect = await child.evaluate(r"""() => {
          const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
          const b = [...document.querySelectorAll('button')].find(b => {
            const row = b.closest('tr') || b.closest('li') || (b.parentElement && b.parentElement.parentElement);
            return row && c(row.innerText).replace(/\s+/g,'').includes('참조문서');
          });
          if (!b) return null;
          const r = b.getBoundingClientRect();
          return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
        }""")
        print(f"[G] 재오픈용 '참조문서 선택' 좌표 = {reopen_sel_rect}", flush=True)
        if reopen_sel_rect:
            await child.mouse.click(reopen_sel_rect["x"], reopen_sel_rect["y"])
            await child.wait_for_timeout(1_500)
            await child.screenshot(path=str(ARTIFACTS / "voucher_card_refdoc_g_reopened_untouched.png"))
            # 초기(자동) 상태를 필드 미터치로 캡처 — 문서번호는 비어 있어야 정상(재오픈 초기값).
            g_state = await child.evaluate(r"""() => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const re = /\(주\)나인벨-\d{4}-\d+/;
              const matches = new Set();
              let noDataText = null;
              for (const el of document.querySelectorAll('*')) {
                if (el.children.length > 0) continue;
                const t = c(el.innerText || el.textContent || '');
                if (!t) continue;
                const m = t.match(re);
                if (m) matches.add(m[0]);
                if (t.includes('조회된 데이터가 없습니다')) noDataText = t;
              }
              return { docNoMatches: [...matches].slice(0, 5), noDataText };
            }""")
            print(f"[G] 재오픈 직후(필드 미터치, 조회도 미클릭) 상태 = {g_state}", flush=True)
            report["phase_g_reopen_untouched"] = g_state

            # 이제 필드는 그대로 둔 채(진짜 미터치, 필터 확장도 안 함) — dialog 재오픈 직후
            # **접힘 상태의 원래 조회 아이콘 버튼**(#tutorial-conditionPanel-search)을 누른다
            # (지금까지 시도는 전부 '필터 확장' 상태의 텍스트 조회 버튼이었다 — 다른 버튼 격리 테스트).
            g_search_rect = await child.evaluate(r"""() => {
              const b = document.querySelector('#tutorial-conditionPanel-search');
              if (!b) return null;
              const r = b.getBoundingClientRect();
              return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), visible: b.offsetParent !== null };
            }""")
            print(f"[G] '조회' 버튼(접힘 상태, 원래 아이콘) 좌표 = {g_search_rect}", flush=True)
            if g_search_rect:
                await child.mouse.click(g_search_rect["x"], g_search_rect["y"])
                g_after: dict = {"docNoMatches": [], "noDataText": None}
                for _ in range(8):
                    g_after = await child.evaluate(r"""() => {
                      const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
                      const re = /\(주\)나인벨-\d{4}-\d+/;
                      const matches = new Set();
                      let noDataText = null;
                      for (const el of document.querySelectorAll('*')) {
                        if (el.children.length > 0) continue;
                        const t = c(el.innerText || el.textContent || '');
                        if (!t) continue;
                        const m = t.match(re);
                        if (m) matches.add(m[0]);
                        if (t.includes('조회된 데이터가 없습니다')) noDataText = t;
                      }
                      return { docNoMatches: [...matches].slice(0, 5), noDataText };
                    }""")
                    if g_after.get("docNoMatches") or g_after.get("noDataText"):
                        break
                    await child.wait_for_timeout(500)
                print(f"[G] 필드 미터치 + '조회'(접힘상태버튼) 클릭 후 = {g_after}", flush=True)
                report["phase_g_search_untouched"] = g_after
                await child.screenshot(path=str(ARTIFACTS / "voucher_card_refdoc_g_after_search.png"))

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
            print(f"[정리] dialog 닫기(X) = {close_rect}", flush=True)

    finally:
        if child is not None:
            try:
                await vr_steps.close_child(child)
                print("[정리] 결제창 닫음(상신/보관/확인 미클릭)", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[경고] 결제창 닫기 실패(무시): {exc}", flush=True)
        (ARTIFACTS / "voucher_card_refdoc_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"\n[artifact] {ARTIFACTS / 'voucher_card_refdoc_report.json'}", flush=True)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
