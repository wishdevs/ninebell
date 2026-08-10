"""전자결재(EAP) 진행 문서 취소 e2e — 상신문서 결재취소 → 미결문서 상신취소 → 임시보관문서 삭제.

플로우 (2026-08-07 Playwright codegen 실측 — e2e/artifacts/eap_cancel_codegen.py):
  1. 석대현 계정 로그인 (ensure_logged_in — 석대현 계정은 로그인 중 회사 홈페이지 별도 창이 뜸)
  2. GNB '전자결재' 진입 — 같은 탭, iframe #content_UB (React EAP 앱, dews 그리드 아님)
  3. 사이드바 상신/보관함(#UBA_UBA1000) > 상신문서(#UBA1010_UBA)
  4. 리스트의 '진행' 상태 행을 번호 목록으로 제시 → 취소 대상 선택(대화형 stdin 또는 E2E_TITLES)
  5. 선택 건마다 반복:
     상신문서에서 제목 클릭(문서 팝업 창) → 결재취소 + 확인 →
     결재수신함 > 미결문서(#UBA2020_UBA) 동일 건 → 상신취소 + 확인 →
     상신/보관함 > 임시보관문서(#UBA1020_UBA) 동일 건 → 삭제 + 확인 →
     임시보관문서 리스트에서 부재 확인(성공 판정)
  6. 전 선택 건 성공 시 종료.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 상신·저장(F7)·보관 버튼 절대 클릭 금지. 이 스크립트가 누르는 버튼은
    결재취소/상신취소/삭제/확인 뿐이다.
  - 결재취소·상신취소·삭제는 **비가역** — 사용자가 명시 선택한 '진행' 상태 문서에만 실행한다.
    선택 입력이 비어 있으면 아무것도 하지 않고 종료한다.
  - 자격증명 비저장 — 비밀번호는 E2E_PASSWORD env 로만 주입(하드코딩 없음).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    E2E_PASSWORD=**** .venv/bin/python e2e/eap_approval_cancel_probe.py
    # 읽기 전용(리스트 출력까지만, 취소 없음): E2E_LIST_ONLY=1
    # 비대화형 대상 지정(쉼표구분 부분일치): E2E_TITLES="PIV2026070109"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) ────────────────────────────────────────────────────────
from app.config import get_settings  # noqa: E402
from nbkit.browser.popups import install_notice_autoclose  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

USERID = os.environ.get("E2E_USERID", "석대현")
PASSWORD = os.environ.get("E2E_PASSWORD", "")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
LIST_ONLY = os.environ.get("E2E_LIST_ONLY", "0") == "1"
TITLES = [t.strip() for t in os.environ.get("E2E_TITLES", "").split(",") if t.strip()]
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
VIEWPORT = {"width": 1440, "height": 900}
PROBE = "eap_approval_cancel"

IFRAME = "#content_UB"
MENU_SUBMIT_GROUP = "#UBA_UBA1000"  # 상신/보관함 (codegen 실측)
MENU_SUBMITTED = "#UBA1010_UBA"  # 상신문서
MENU_PENDING = "#UBA2020_UBA"  # 결재수신함 > 미결문서 (그룹 펼침 없이 직접 클릭됨)
MENU_DRAFTBOX = "#UBA1020_UBA"  # 임시보관문서

# 문서 팝업 창에서 누르는 단계별 버튼. (menu_label, leaf, group, button)
PHASES = [
    ("상신문서", MENU_SUBMITTED, MENU_SUBMIT_GROUP, "결재취소"),
    ("미결문서", MENU_PENDING, None, "상신취소"),
    ("임시보관문서", MENU_DRAFTBOX, MENU_SUBMIT_GROUP, "삭제"),
]

# ── 신규 작성분(이 프로브 고유 필요) ──────────────────────────────────────────────
# EAP 리스트는 React 그리드(dewsControl 무효) — 행은 li.listChk (실측 2026-08-07,
# e2e/artifacts/eap_dom_diag.json). 행마다 비어있지 않은 span 은 '기안일: …' 툴팁과 **제목**
# 2개뿐이고, 상태는 행 텍스트 끝의 '진행 (결재자)' / '종결 (…)' 패턴이다.
ROWS_DUMP_JS = """() => {
  const clean = s => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();
  return [...document.querySelectorAll('li.listChk')].map(r => {
    const text = clean(r.innerText);
    const spans = [...r.querySelectorAll('span')].map(s => clean(s.innerText)).filter(Boolean);
    const title = spans.filter(t => !t.startsWith('기안일'))[0] || '';
    const date = clean((r.querySelector('.dateText') || {}).innerText || '');
    const m = [...text.matchAll(/(진행|종결|반려|회수|완료)\\s*\\(/g)];
    const status = m.length ? m[m.length - 1][1] : '';
    return { text, title, date, status };
  }).filter(r => r.text);
}"""

TITLE_COUNT_JS = """(t) =>
  [...document.querySelectorAll('span')].filter(s => (s.innerText || '').includes(t)).length"""


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"{PROBE}_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


async def _shot(page: Page, name: str) -> None:
    await page.screenshot(path=str(ARTIFACTS / f"{PROBE}_{name}.png"))


async def _frame(page: Page):
    """EAP iframe 의 Frame 객체 — evaluate 용. 스테일 방지를 위해 매번 재획득."""
    handle = await page.wait_for_selector(IFRAME, timeout=30_000)
    fr = await handle.content_frame()
    if fr is None:
        raise RuntimeError("EAP iframe(#content_UB) 콘텐츠 프레임을 얻지 못함")
    return fr


async def _click_menu(page: Page, leaf: str, group: str | None) -> None:
    """사이드바 리프 메뉴 클릭 — 안 보이면 그룹을 먼저 펼친다."""
    fl = page.locator(IFRAME).content_frame
    try:
        await fl.locator(leaf).click(timeout=5_000)
    except Exception:
        if group is None:
            raise
        await fl.locator(group).click(timeout=10_000)
        await fl.locator(leaf).click(timeout=10_000)


async def _wait_title(page: Page, title: str, *, present: bool, cap_ms: int = 20_000) -> bool:
    """리스트에 제목이 (나타날/사라질) 때까지 실시간 폴링."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1_000 < cap_ms:
        fr = await _frame(page)
        n = await fr.evaluate(TITLE_COUNT_JS, title)
        if (n > 0) == present:
            return True
        await asyncio.sleep(0.5)
    return False


async def _wait_rows(page: Page, cap_ms: int = 20_000) -> list[dict]:
    """리스트 행(li.listChk)이 렌더될 때까지 폴링 후 전량 덤프."""
    t0 = time.monotonic()
    rows: list[dict] = []
    while (time.monotonic() - t0) * 1_000 < cap_ms:
        fr = await _frame(page)
        rows = await fr.evaluate(ROWS_DUMP_JS)
        if rows:
            return rows
        await asyncio.sleep(0.5)
    return rows


async def _cancel_phase(page: Page, doc_no: int, phase_no: int, title: str,
                        menu_label: str, leaf: str, group: str | None, button: str) -> None:
    print(f"  [phase {phase_no}] {menu_label} → '{button}'")
    await _click_menu(page, leaf, group)
    found = await _wait_title(page, title, present=True, cap_ms=25_000)
    if not found:
        # 서버 반영 지연/리스트 미갱신 대비(실측 2026-08-07: 결재취소 직후 미결문서 도착이
        # 20s 를 넘긴 사례) — 다른 메뉴로 갔다가 재진입해 리스트를 강제 갱신 후 한 번 더 관찰.
        alt = MENU_PENDING if leaf != MENU_PENDING else MENU_SUBMITTED
        await _click_menu(page, alt, None if alt == MENU_PENDING else MENU_SUBMIT_GROUP)
        await _click_menu(page, leaf, group)
        found = await _wait_title(page, title, present=True, cap_ms=25_000)
    if not found:
        raise RuntimeError(f"{menu_label} 리스트에서 '{title}' 행을 찾지 못함")
    fl = page.locator(IFRAME).content_frame
    async with page.expect_popup() as pinfo:
        await fl.locator("span").filter(has_text=title).first.click()
    popup = await pinfo.value
    await popup.wait_for_load_state("domcontentloaded")
    await popup.get_by_text(button, exact=True).first.click(timeout=20_000)
    await popup.get_by_role("button", name="확인").click(timeout=10_000)
    # 확인 후 창이 스스로 닫히기도 한다 — 3초 관찰 후 안 닫혔으면 직접 닫는다(codegen 은 수동 close).
    for _ in range(6):
        if popup.is_closed():
            break
        await asyncio.sleep(0.5)
    if not popup.is_closed():
        await popup.close()
    await _shot(page, f"doc{doc_no}_{phase_no}_{button}")


async def _select_rows(progress: list[dict]) -> list[dict]:
    """취소 대상 선택 — E2E_TITLES 부분일치 우선, 없으면 대화형 stdin."""
    if TITLES:
        picked = [r for r in progress if any(t in r["text"] for t in TITLES)]
        print(f"[select] E2E_TITLES={TITLES} → {len(picked)}건 매칭")
        return picked
    raw = (await asyncio.to_thread(
        input, "취소할 번호를 입력하세요 (쉼표구분, all=전체, 엔터=중단): ")).strip()
    if not raw:
        return []
    if raw.lower() == "all":
        return progress
    picked = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(progress):
            picked.append(progress[int(tok) - 1])
        else:
            print(f"  [warn] 무시된 입력: {tok!r}")
    return picked


async def run() -> None:
    if not PASSWORD:
        sys.exit("E2E_PASSWORD env 가 필요합니다 — 예: E2E_PASSWORD=**** .venv/bin/python e2e/eap_approval_cancel_probe.py")
    base = get_settings().erp_base
    summary: dict = {"userid": USERID, "selected": [], "done": [], "failed": None}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(viewport=VIEWPORT)
        install_notice_autoclose(context)  # 공지 팝업 상시 무시(결재창은 보호됨)
        page: Page = await context.new_page()
        try:
            print("[step] login")
            await ensure_logged_in(page, USERID, PASSWORD, base, read_profile_after=False)
            # 로그인 직후 배너(codegen 실측: aria-label=Close) — 없으면 no-op.
            try:
                await page.get_by_label("Close").click(timeout=3_000)
            except Exception:
                pass
            await _shot(page, "1_login")

            print("[step] 전자결재 진입")
            await page.get_by_role("listitem", name="전자결재").locator("div").click()
            await page.wait_for_selector(IFRAME, timeout=30_000)
            await _shot(page, "2_eap")

            print("[step] 상신/보관함 > 상신문서")
            await _click_menu(page, MENU_SUBMITTED, MENU_SUBMIT_GROUP)
            rows = await _wait_rows(page)
            _dump("rows", rows)
            await _shot(page, "3_submitted_list")

            progress = [r for r in rows if r.get("status") == "진행" and r.get("title")]
            if not progress:
                print("[done] '진행' 상태 문서가 없습니다 — 종료")
                return
            print(f"\n── 진행 중인 결재 문서 {len(progress)}건 ──")
            for i, r in enumerate(progress, 1):
                print(f"  {i}. {r['text']}")
            if LIST_ONLY:
                print("[done] E2E_LIST_ONLY=1 — 리스트 출력까지만 수행")
                return

            async def _process_doc(di: int, title: str, start_phase: int) -> None:
                for pi, (menu_label, leaf, group, button) in enumerate(PHASES, 1):
                    if pi < start_phase:
                        continue
                    await _cancel_phase(page, di, pi, title, menu_label, leaf, group, button)
                # 성공 판정: 삭제 후 임시보관문서 리스트에서 해당 건 부재.
                await _click_menu(page, MENU_DRAFTBOX, MENU_SUBMIT_GROUP)
                if not await _wait_title(page, title, present=False, cap_ms=15_000):
                    raise RuntimeError(f"삭제 후에도 임시보관문서에 '{title}' 가 남아 있음")
                print("  [ok] 취소 완료, 임시보관 잔존 0 확인")
                summary["done"].append(title)

            if TITLES:
                # ── 토큰 모드: 리스트가 30행/페이지라(실측 2026-08-07) **한 건마다 재목록**해
                # 남은 토큰을 재매칭한다(앞 건이 취소되면 뒤 페이지 건이 1페이지로 올라온다).
                # 진행 목록에 없는 토큰은 중간 단계(결재취소만 된 미결문서/상신취소까지 된
                # 임시보관문서)에서 찾아 해당 단계부터 **재개**한다.
                remaining = list(TITLES)
                summary["selected"] = list(TITLES)
                done_n = 0
                while remaining:
                    await _click_menu(page, MENU_SUBMITTED, MENU_SUBMIT_GROUP)
                    rows = await _wait_rows(page)
                    prog = [r for r in rows if r.get("status") == "진행" and r.get("title")]
                    token, title, start = None, None, 1
                    for t in remaining:
                        row = next((r for r in prog if t in r["text"]), None)
                        if row:
                            token, title, start = t, row["title"], 1
                            break
                    if token is None:
                        for t in remaining:  # 중간 단계 재개 탐지(미결 → phase 2, 임시보관 → phase 3).
                            await _click_menu(page, MENU_PENDING, None)
                            if await _wait_title(page, t, present=True, cap_ms=8_000):
                                token, title, start = t, t, 2
                                break
                            await _click_menu(page, MENU_DRAFTBOX, MENU_SUBMIT_GROUP)
                            if await _wait_title(page, t, present=True, cap_ms=8_000):
                                token, title, start = t, t, 3
                                break
                    if token is None:
                        print(f"[warn] 남은 {len(remaining)}건을 진행/미결/임시보관 어디에서도 찾지 못함: {remaining}")
                        break
                    done_n += 1
                    phase_note = "" if start == 1 else f" (phase {start}부터 재개)"
                    print(f"[doc {done_n}] '{title}'{phase_note}")
                    await _process_doc(done_n, title, start)
                    remaining.remove(token)
                if remaining:
                    summary["failed"] = f"미처리 {len(remaining)}건: {remaining}"
                    raise RuntimeError(summary["failed"])
                print(f"\n[PASS] {done_n}건 모두 취소 완료")
                return

            picked = await _select_rows(progress)
            if not picked:
                print("[done] 선택 없음 — 아무 작업도 하지 않고 종료")
                return
            summary["selected"] = [r["text"] for r in picked]

            for di, row in enumerate(picked, 1):
                title = row["title"]
                print(f"[doc {di}/{len(picked)}] '{title}'")
                await _process_doc(di, title, 1)

            print(f"\n[PASS] 선택 {len(picked)}건 모두 취소 완료")
        except Exception as e:
            summary["failed"] = str(e)
            await _shot(page, "FAIL")
            raise
        finally:
            _dump("summary", summary)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
