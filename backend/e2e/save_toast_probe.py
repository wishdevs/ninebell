"""HEADLESS 검증 프로브 — 저장(F7) 검증 실패 시 마스터 그리드 결의번호 필드 + 하단 토스트 DOM 실측.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 상신(결재) 절대 금지.
  - F3 새 행(필수값 미입력) 상태에서 F7 을 누르는 것은 **의도적 검증 실패 유발**이 목적이다 —
    증빙유형·금액·예산단위 등을 채우지 않아 저장이 거부될 것으로 예상한다.
  - 만약 예상과 달리 실제로 저장(채번)돼 버리면 **즉시 F6 삭제**로 정리하고 그 사실을 보고한다
    (삭제 가드레일: 결의자=로그인계정 + 결의구분 일치 + 미결(전표번호 공백) — e2e_smoke.py 의
    _row_is_ours 그대로 재사용).

card_owner_col_probe.py/card_owner_match_verify_probe.py(2026-07-29)와 동일한 진입 경로(login→
user_type(회계)→menu_nav→set_gubun(카드)→add_row)를 재사용해 F3 새 행까지 만든 뒤, 증빙유형 선택
등 후속 단계를 **일부러 건너뛰고** 곧바로 F7 을 눌러 검증 실패를 유발한다. 마스터 그리드 컬럼 덤프는
e2e_smoke.py 의 MASTER_DUMP_JS(GLDDOC00300 검증/삭제용으로 이미 검증된 JS)를 그대로 재사용한다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/save_toast_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) ────────────────────────────────────────────────────────
from app.config import get_settings  # noqa: E402
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS  # noqa: E402  (GLDDOC00300 마스터 그리드 덤프·버튼좌표 JS 그대로)
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
VIEWPORT = {"width": 1440, "height": 900}

# 결의번호/상태/전표번호 후보 필드 키 추정(더존 관행) — 실측으로 확정, 없으면 무시.
CANDIDATE_FIELD_HINTS = [
    "ABDOCU_NO", "RESL_NO", "DOCU_NO", "RDOCU_ST_CD", "RDOCU_ST_NM",
    "STATUS", "ST_NM", "ABDOCU_FG_CD", "WRT_EMP_NM", "ACTG_DT",
]

# ── 신규 작성분(이 검증 고유) ────────────────────────────────────────────────────
# F7 직전에 설치하는 MutationObserver — 저장 실패 토스트가 뜨고/사라지는 것을 텍스트 매칭이
# 아니라 **DOM 구조 변화**로 포착한다(신규 문구가 나올 때마다 문구 블랙리스트를 패치하는
# VALIDATION_TOAST_JS 의 구조적 한계를 보완하기 위한 실측). 노이즈(캔버스 그리드 리페인트) 를
# 줄이려고 (1) CANVAS/SCRIPT 노드 제외 (2) 텍스트 길이 2~300자만 채택 (3) attribute 관찰은
# style/class 만 본다.
INSTALL_TOAST_OBSERVER_JS = r"""() => {
  if (window.__toastObs) { try { window.__toastObs.disconnect(); } catch(e) {} }
  window.__toastEvents = [];
  const t0 = performance.now();
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const describe = (el) => {
    if (!(el instanceof Element)) return null;
    const text = c(el.innerText || el.textContent || '');
    return { tag: el.tagName, id: el.id || null,
             className: (el.className && el.className.toString) ? el.className.toString() : null,
             text: text.slice(0, 200), textLen: text.length };
  };
  const parentChain = (el) => {
    const chain = []; let p = el.parentElement; let depth = 0;
    while (p && depth < 6) {
      chain.push({ tag: p.tagName, id: p.id || null,
                   className: (p.className && p.className.toString) ? p.className.toString() : null });
      p = p.parentElement; depth++;
    }
    return chain;
  };
  const obs = new MutationObserver((mutations) => {
    if (window.__toastEvents.length > 400) return;  // 폭주 방지 캡.
    for (const m of mutations) {
      if (m.type === 'childList') {
        for (const node of m.addedNodes) {
          if (!(node instanceof Element) || node.tagName === 'CANVAS' || node.tagName === 'SCRIPT') continue;
          const d = describe(node);
          if (!d || d.textLen < 2 || d.textLen > 300) continue;
          window.__toastEvents.push({ t: Math.round(performance.now() - t0), kind: 'added', ...d,
            outerHTML: (node.outerHTML || '').slice(0, 800), parentChain: parentChain(node) });
        }
        for (const node of m.removedNodes) {
          if (!(node instanceof Element)) continue;
          const d = describe(node);
          if (!d || d.textLen < 2 || d.textLen > 300) continue;
          window.__toastEvents.push({ t: Math.round(performance.now() - t0), kind: 'removed', ...d,
            outerHTML: (node.outerHTML || '').slice(0, 800) });
        }
      } else if (m.type === 'attributes') {
        const el = m.target;
        if (!(el instanceof Element)) continue;
        const d = describe(el);
        if (!d || d.textLen < 2 || d.textLen > 300) continue;
        window.__toastEvents.push({ t: Math.round(performance.now() - t0), kind: 'attr:' + m.attributeName, ...d,
          outerHTML: (el.outerHTML || '').slice(0, 800), parentChain: parentChain(el) });
      }
    }
  });
  obs.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
  window.__toastObs = obs;
  return { ok: true };
}"""

READ_TOAST_EVENTS_JS = "() => (window.__toastEvents || [])"
STOP_TOAST_OBSERVER_JS = "() => { try { window.__toastObs && window.__toastObs.disconnect(); } catch(e) {} return true; }"


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"save_toast_probe_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


def _extract_candidates(row: dict | None) -> dict:
    if not isinstance(row, dict):
        return {}
    return {k: row.get(k) for k in CANDIDATE_FIELD_HINTS if k in row}


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page: Page = await (await browser.new_context(viewport=VIEWPORT)).new_page()
        try:
            print("[step] login")
            await ensure_logged_in(page, USERID, PASSWORD, base)

            print("[step] user_type 회계")
            await ensure_user_type(page, "회계")

            print("[step] menu_nav (결의서입력)")
            await navigate_schema(page, EXPENSE_CARD, base)

            print("[step] set_gubun 카드")
            for _ in range(50):
                if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                    break
                await page.wait_for_timeout(300)
            r = await page.evaluate(
                js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
                {"selector": selectors.GUBUN_SELECT, "text": "카드"},
            )
            print("  gubun result:", r)

            print("[step] 가설1 — add_row(F3) 전 마스터 그리드 덤프")
            master_before = await page.evaluate(MASTER_DUMP_JS, 0)
            print("  master_before n:", master_before.get("n"), "cols:", len(master_before.get("columns") or []))
            _dump("master_before_addrow", master_before)

            print("[step] add_row (F3)")
            await js_click(page, selectors.BTN_ADD)
            rows = -1
            for _ in range(33):
                await page.wait_for_timeout(300)
                rows = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                if isinstance(rows, int) and rows > 0:
                    break
            print("  detail rows:", rows)
            if not (isinstance(rows, int) and rows > 0):
                raise RuntimeError("add_row 실패 — 입력 행이 생성되지 않았습니다")

            print("[step] 가설1 — add_row(F3) 후 마스터 그리드 덤프(미저장 상태 값)")
            master_after = await page.evaluate(MASTER_DUMP_JS, 0)
            row0 = (master_after.get("rows") or [None])[0]
            candidates_before_save = _extract_candidates(row0)
            print("  master_after n:", master_after.get("n"), "fieldKeys:", master_after.get("fieldKeys"))
            print("  후보 필드(미저장 값):", candidates_before_save)
            _dump("master_after_addrow", master_after)
            await page.screenshot(path=str(ARTIFACTS / "save_toast_probe_1_before_f7.png"))

            print("[step] F7 전 포커스 정리 — add_row 직후 열린 회계일 셀 에디터가 F7 을 삼킬 수 있어")
            # 실측(1차 시도): add_row 직후 열린 회계일 셀 에디터(파란 테두리)에 포커스가 남은 채
            # F7 을 누르면 스크린샷/토스트/모달/observer 전부 무반응(before==after 완전 동일) —
            # 프로덕션 save_document 는 apply_pass2 의 버튼 클릭들 뒤에 F7 을 눌러 이 상태가 아니다.
            # 셀 에디터를 닫고 그리드 밖 중립 지점을 클릭해 포커스를 뗀 뒤 재시도한다.
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
            await page.mouse.click(700, 115)  # 툴바 아래·그리드 위 여백(중립 지점)
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(ARTIFACTS / "save_toast_probe_1b_after_blur.png"))

            print("[step] 가설2 — MutationObserver 설치 후 F7(의도적 검증 실패 유발)")
            await page.evaluate(INSTALL_TOAST_OBSERVER_JS)
            await page.keyboard.press("F7")

            # 3~8초 관찰(save_document 의 실측 관찰창(3~16s)과 동형) — 매 300ms 모달/토스트/
            # 스크린샷을 함께 수집한다.
            modals_seen: list = []
            toasts_seen: list = []
            shots = 0
            for i in range(24):  # 300ms * 24 = ~7.2s
                await page.wait_for_timeout(300)
                toasts = await page.evaluate(js_lib.VALIDATION_TOAST_JS)
                if toasts:
                    toasts_seen.extend(t for t in toasts if t not in toasts_seen)
                modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
                if modals:
                    for m in modals:
                        if m not in modals_seen:
                            modals_seen.append(m)
                if (toasts or modals) and shots < 3:
                    shots += 1
                    await page.screenshot(path=str(ARTIFACTS / f"save_toast_probe_2_during_f7_{shots}.png"))
            await page.screenshot(path=str(ARTIFACTS / "save_toast_probe_3_after_f7.png"))

            events = await page.evaluate(READ_TOAST_EVENTS_JS)
            await page.evaluate(STOP_TOAST_OBSERVER_JS)
            print(f"  toasts_seen(문구매칭)={toasts_seen}")
            print(f"  modals_seen={len(modals_seen)}건")
            print(f"  observer events={len(events)}건")
            _dump("toasts_and_modals", {"toasts_seen": toasts_seen, "modals_seen": modals_seen})
            _dump("observer_events", events)

            print("[step] F7 후 마스터 그리드 재덤프 — 결의번호류 필드 값 재확인(미저장 검증)")
            master_post = await page.evaluate(MASTER_DUMP_JS, 0)
            row0_post = (master_post.get("rows") or [None])[0]
            candidates_after_save = _extract_candidates(row0_post)
            print("  후보 필드(F7 후 값):", candidates_after_save)
            _dump("master_after_f7", master_post)

            # 안전가드 — 예상과 달리 실제 저장(채번)됐는지: 후보 필드 중 하나라도 F7 전엔
            # 비어 있다가 F7 후 값이 생겼으면 저장 성공 가능성 → 규율대로 F6 삭제 시도.
            newly_filled = {
                k: v for k, v in candidates_after_save.items()
                if v not in (None, "", 0) and candidates_before_save.get(k) in (None, "", 0)
            }
            delete_report: dict = {"attempted": False}
            if newly_filled:
                print(f"  ⚠ 저장(채번) 의심 — 새로 채워진 필드: {newly_filled} → F6 삭제 시도")
                delete_report = await _attempt_delete(page)
            else:
                print("  저장(채번) 신호 없음 — 예상대로 미저장 상태 유지.")

            result = {
                "master_columns": master_after.get("columns"),
                "master_field_keys": master_after.get("fieldKeys"),
                "candidates_before_save": candidates_before_save,
                "candidates_after_save": candidates_after_save,
                "newly_filled_after_f7": newly_filled,
                "toasts_seen_phrase_match": toasts_seen,
                "modals_seen": modals_seen,
                "observer_event_count": len(events),
                "observer_events": events,
                "delete_report": delete_report,
            }
            _dump("result", result)

            print("\n=== SUMMARY ===")
            print(json.dumps(
                {
                    "master_field_keys": result["master_field_keys"],
                    "candidates_before_save": candidates_before_save,
                    "candidates_after_save": candidates_after_save,
                    "newly_filled_after_f7": newly_filled,
                    "toasts_seen_phrase_match": toasts_seen,
                    "modals_seen_count": len(modals_seen),
                    "observer_event_count": len(events),
                    "delete_report": delete_report,
                },
                ensure_ascii=False, indent=2, default=str,
            ))
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {exc}")
            try:
                await page.screenshot(path=str(ARTIFACTS / "save_toast_probe_FAIL.png"))
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            await browser.close()


async def _attempt_delete(page: Page) -> dict:
    """안전가드 — 의도치 않게 저장된 경우에만 호출. e2e_smoke.py 의 삭제 가드레일과 동형
    (결의자=로그인계정 + 결의구분 일치 + 미결(DOCU_NO 공백))을 이 자리에서 재확인 후 F6.
    """
    dump = await page.evaluate(MASTER_DUMP_JS, 0)
    rows = dump.get("rows") or []
    ours = [
        r for r in rows
        if str(r.get("WRT_EMP_NM") or "").strip() == USERID
        and str(r.get("ABDOCU_FG_CD") or "") == "52"
        and not str(r.get("DOCU_NO") or "").strip()
    ]
    if not ours:
        return {"attempted": False, "reason": "삭제 가드레일 미충족(내 행 아님/전표번호 있음) — 삭제 중단", "rows": rows}
    dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
    if dbox:
        await page.mouse.click(dbox["x"], dbox["y"])
    else:
        await page.keyboard.press("F6")
    delete_modals: list = []
    for _ in range(20):
        await page.wait_for_timeout(300)
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        if modals:
            delete_modals.extend(modals)
            clicked = False
            for label in ("예", "확인", "삭제"):
                btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    clicked = True
                    break
            if clicked:
                continue
        else:
            break
    dump2 = await page.evaluate(MASTER_DUMP_JS, 0)
    post_n = dump2.get("n", -1)
    return {"attempted": True, "delete_modals": delete_modals[:5], "post_delete_count": post_n, "deleted": post_n == 0}


if __name__ == "__main__":
    asyncio.run(run())
