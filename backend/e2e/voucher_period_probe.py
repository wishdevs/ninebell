"""회계일 periodpicker **기간 세팅** 진단 프로브 — 왜 날짜가 실제로 안 바뀌는지 규명한다.

배경(2026-07-28 사용자 리포트): 실행 전 폼으로 조회기간을 받도록 했는데 **실제 프로세스에서
날짜가 선택되지 않는다**. 가설은 둘이다.
  (a) 셀렉터 불일치 — `#s_period_startinput`/`_endinput` 이 실제 id 가 아니다(추정으로 작성됨).
  (b) 위젯 모델 미반영 — input.value 만 바꿔서 화면 글자는 변하지만 dews 컨트롤 내부 값은
      그대로라 조회는 당월로 나간다(readback 이 input 을 읽으면 **자기가 쓴 값**을 확인하는
      동어반복이라 성공으로 보인다).

이 프로브는 두 화면(전표조회승인 `#s_period` · 결의서조회승인 `#PERIOD_DT_C`)에 대해
  1) periodpicker DOM/위젯 API 표면을 덤프하고,
  2) 후보 세팅 전략을 하나씩 적용해 **컨트롤 모델 값**이 실제로 움직이는지 확인한다.

⚠ 완전 읽기전용 — 조회(F2)조차 누르지 않는다. 저장·상신·삭제 없음. 조회조건 위젯만 만지고,
   끝나면 원래 값(당월)으로 되돌린다.

Usage (자격증명은 사용자가 직접 주입 — 이 파일에 비밀번호를 쓰지 말 것):
    cd /Users/wishdev/et-works/dashboard-design/backend
    E2E_USERID=<아이디> E2E_PASSWORD=<비밀번호> .venv/bin/python e2e/voucher_period_probe.py

결과: e2e/artifacts/voucher_period_probe.json (+ 화면 스크린샷 2장)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.voucher_card import steps as card_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

# 자격증명은 환경변수 우선, 없으면 backend/.env 에서 읽는다(비밀번호를 명령줄·셸 히스토리에
# 남기지 않기 위함 — .env 는 gitignore 대상이라 커밋되지 않는다).
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

# 시험할 목표 기간 — '당월 일부'라야 setMonth() 경로와 구분된다(사용자 예: 7/1~7/5).
TARGET_START = os.environ.get("E2E_PERIOD_START", "20260701")
TARGET_END = os.environ.get("E2E_PERIOD_END", "20260705")

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "voucher_period_probe.json"


# ── 1) API 표면 덤프 — 이 위젯이 무엇이고 어떤 메서드를 갖는가 ────────────────
DUMP_JS = r"""(sel) => {
  const out = { selector: sel };
  const el = document.querySelector(sel);
  out.found = !!el;
  if (!el) return out;
  out.tag = el.tagName;
  out.className = String(el.className || '');
  // 하위 input 들의 id/name/value — 우리가 쓰는 '<id>_startinput' 규약이 맞는지 확인.
  out.inputs = [...el.querySelectorAll('input')].map(i => ({
    id: i.id, name: i.name, value: i.value, type: i.type, cls: String(i.className || ''),
  }));
  const idBase = sel.replace(/^#/, '');
  out.guessed_ids = {
    start: !!document.getElementById(idBase + '_startinput'),
    end: !!document.getElementById(idBase + '_endinput'),
  };
  try {
    const $ = window.jQuery;
    if (!$) { out.jquery = false; return out; }
    out.jquery = true;
    const data = $(el).data() || {};
    out.data_keys = Object.keys(data);
    const ctrl = data.dewsControl;
    out.has_dewsControl = !!ctrl;
    if (ctrl) {
      // 메서드 이름 전부(프로토타입 포함) — 기간 세터 후보를 눈으로 고르기 위함.
      const names = new Set();
      let o = ctrl;
      while (o && o !== Object.prototype) {
        Object.getOwnPropertyNames(o).forEach(n => names.add(n));
        o = Object.getPrototypeOf(o);
      }
      out.ctrl_members = [...names].sort();
      out.ctrl_methods = [...names].filter(n => {
        try { return typeof ctrl[n] === 'function'; } catch (e) { return false; }
      }).sort();
      // 값처럼 보이는 속성들(현재 모델 값 파악용).
      out.ctrl_valueish = {};
      ['value', 'startDate', 'endDate', 'start', 'end', 'from', 'to', '_value', 'options']
        .forEach(k => { try {
          const v = ctrl[k];
          if (typeof v !== 'function') out.ctrl_valueish[k] = JSON.parse(JSON.stringify(v ?? null));
        } catch (e) { out.ctrl_valueish[k] = '(직렬화 불가)'; } });
    }
    // 하위 input 이 kendo DatePicker 인지(그렇다면 widget.value(Date) 가 정답 경로).
    out.kendo = [...el.querySelectorAll('input')].map(i => {
      const d = $(i).data() || {};
      return { id: i.id, data_keys: Object.keys(d) };
    });
  } catch (e) { out.dump_error = String(e); }
  return out;
}"""


# ── 2) 현재 '모델 값' 읽기 — input 이 아니라 컨트롤이 들고 있는 값 ────────────
READ_JS = r"""(sel) => {
  const digits = v => String(v == null ? '' : v).replace(/\D/g, '');
  const el = document.querySelector(sel);
  if (!el) return { found: false };
  const inputs = [...el.querySelectorAll('input')];
  const view = inputs.map(i => digits(i.value));
  const raw = inputs.map(i => i.value);
  let model = null;
  try {
    const ctrl = window.jQuery ? window.jQuery(el).data('dewsControl') : null;
    if (ctrl) {
      // 실측 API(프로브 1차): getStartDate/getEndDate(Date) + getStartText/getEndText(표시문자열).
      const pick = {};
      for (const k of ['getStartDate', 'getEndDate', 'getStartText', 'getEndText']) {
        if (typeof ctrl[k] === 'function') {
          try {
            const v = ctrl[k]();
            pick[k] = (v && typeof v.getFullYear === 'function')
              ? (v.getFullYear() + String(v.getMonth() + 1).padStart(2, '0') + String(v.getDate()).padStart(2, '0'))
              : String(v == null ? '' : v);
          } catch (e) { pick[k] = '(호출 실패) ' + String(e); }
        }
      }
      model = pick;
    }
  } catch (e) { model = '(읽기 실패) ' + String(e); }
  return { found: true, view, raw, model };
}"""


# ── 3) 후보 전략들 — 하나씩 적용해보고 모델이 움직이는지 본다 ─────────────────
# (대조군) 현재 구현 — raw input 에 'yyyyMMdd' 를 쓴다. 표시 형식은 'yyyy-MM-dd' 라 불일치.
STRAT_RAW_JS = r"""({ sel, start, end }) => {
  const idBase = sel.replace(/^#/, '');
  const si = document.getElementById(idBase + '_startinput');
  const ei = document.getElementById(idBase + '_endinput');
  if (!si || !ei) return { ok: false, reason: 'ids-not-found' };
  for (const [inp, val] of [[si, start], [ei, end]]) {
    inp.value = val;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
  }
  return { ok: true };
}"""

# raw input 이되 **표시 형식(yyyy-MM-dd)** 으로 — 형식만 맞추면 위젯이 파싱하는지 확인.
STRAT_RAW_DASHED_JS = r"""({ sel, start, end }) => {
  const dash = s => s.slice(0,4) + '-' + s.slice(4,6) + '-' + s.slice(6,8);
  const idBase = sel.replace(/^#/, '');
  const si = document.getElementById(idBase + '_startinput');
  const ei = document.getElementById(idBase + '_endinput');
  if (!si || !ei) return { ok: false, reason: 'ids-not-found' };
  for (const [inp, val] of [[si, dash(start)], [ei, dash(end)]]) {
    inp.focus();
    inp.value = val;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    inp.dispatchEvent(new Event('blur', { bubbles: true }));
  }
  return { ok: true };
}"""

# 실측 API — setPeriod(start, end). 인자 형태(문자열 yyyyMMdd / Date)를 순서대로 시도.
STRAT_SETPERIOD_JS = r"""({ sel, start, end }) => {
  const $ = window.jQuery;
  const ctrl = $ ? $(document.querySelector(sel)).data('dewsControl') : null;
  if (!ctrl || typeof ctrl.setPeriod !== 'function') return { ok: false, reason: 'no-setPeriod' };
  const toDate = s => new Date(+s.slice(0,4), +s.slice(4,6) - 1, +s.slice(6,8));
  try { ctrl.setPeriod(start, end); return { ok: true, form: 'string' }; } catch (e) {}
  try { ctrl.setPeriod(toDate(start), toDate(end)); return { ok: true, form: 'Date' }; } catch (e) {
    return { ok: false, reason: String(e) };
  }
}"""

# 실측 API — setStartDate / setEndDate 개별 세터.
STRAT_SETSTARTEND_JS = r"""({ sel, start, end }) => {
  const $ = window.jQuery;
  const ctrl = $ ? $(document.querySelector(sel)).data('dewsControl') : null;
  if (!ctrl || typeof ctrl.setStartDate !== 'function' || typeof ctrl.setEndDate !== 'function') {
    return { ok: false, reason: 'no-setStartDate/setEndDate' };
  }
  const toDate = s => new Date(+s.slice(0,4), +s.slice(4,6) - 1, +s.slice(6,8));
  try { ctrl.setStartDate(start); ctrl.setEndDate(end); return { ok: true, form: 'string' }; } catch (e) {}
  try { ctrl.setStartDate(toDate(start)); ctrl.setEndDate(toDate(end)); return { ok: true, form: 'Date' }; }
  catch (e) { return { ok: false, reason: String(e) }; }
}"""

# 원상복구 — 당월로 되돌린다(프로브가 화면 상태를 남기지 않게).
RESTORE_JS = r"""(sel) => {
  try { window.jQuery(document.querySelector(sel)).data('dewsControl').setMonth(); return true; }
  catch (e) { return false; }
}"""

STRATEGIES = [
    ("raw_input yyyyMMdd(현재 구현)", STRAT_RAW_JS),
    ("raw_input yyyy-MM-dd", STRAT_RAW_DASHED_JS),
    ("ctrl.setPeriod", STRAT_SETPERIOD_JS),
    ("ctrl.setStartDate+setEndDate", STRAT_SETSTARTEND_JS),
]


async def _probe_field(page, sel: str, label: str) -> dict:
    """한 화면의 periodpicker 를 덤프하고 전략들을 차례로 시험한다(각 시험 후 원복)."""
    res: dict = {"label": label, "selector": sel}
    res["dump"] = await page.evaluate(DUMP_JS, sel)
    res["before"] = await page.evaluate(READ_JS, sel)
    trials = []
    for name, js in STRATEGIES:
        trial: dict = {"strategy": name}
        try:
            trial["apply"] = await page.evaluate(js, {"sel": sel, "start": TARGET_START, "end": TARGET_END})
            await page.wait_for_timeout(400)
            after = await page.evaluate(READ_JS, sel)
            trial["after"] = after
            view = after.get("view") or []
            trial["view_matches"] = view[:2] == [TARGET_START, TARGET_END]
            # 모델이 목표 기간을 담고 있는가 — 문자열로 눌러 담아 날짜/문자 표현 차이를 흡수.
            model = after.get("model") or {}
            got = (
                str(model.get("getStartDate") or ""),
                str(model.get("getEndDate") or ""),
            )
            trial["model"] = model
            trial["model_matches"] = got == (TARGET_START, TARGET_END)
        except Exception as exc:  # noqa: BLE001 — 전략 실패는 기록하고 다음으로.
            trial["error"] = str(exc)
        finally:
            await page.evaluate(RESTORE_JS, sel)
            await page.wait_for_timeout(300)
        trials.append(trial)
    res["trials"] = trials
    return res


async def _probe_reset_by_later_fields(page, sel: str) -> dict:
    """회계일 세팅 후 **나머지 조회조건을 실제 순서대로** 적용하며 매 단계 회계일을 재확인한다.

    set_query 는 회계일을 두 번째로 세팅하고 그 뒤 작성자·전표상태·전자결재상태·전표유형을
    건드린다. 그중 하나가 change 핸들러/폼 리로드로 회계일을 당월로 되돌리면, 세팅은 성공으로
    보이는데 조회는 당월로 나간다 — 사용자 증상과 정확히 일치한다. 어느 단계인지 특정한다.
    """
    from app.agents.voucher_receivable import steps as vr

    out: dict = {"target": [TARGET_START, TARGET_END], "timeline": []}

    async def snap(label: str) -> None:
        r = await page.evaluate(READ_JS, sel)
        model = r.get("model") or {}
        got = (str(model.get("getStartDate") or ""), str(model.get("getEndDate") or ""))
        out["timeline"].append({
            "after": label,
            "model": list(got),
            "holds": got == (TARGET_START, TARGET_END),
        })

    # 회계일을 먼저(현재 구현과 동일 경로) 세팅.
    await page.evaluate(STRAT_RAW_JS, {"sel": sel, "start": TARGET_START, "end": TARGET_END})
    await page.wait_for_timeout(400)
    await snap("회계일 세팅 직후")

    for label, fn in [
        ("작성자 비움", vr.clear_writer),
        ("전표상태 미결", vr.set_docu_status),
        ("전자결재상태 저장", vr.set_gwaprvlst),
    ]:
        try:
            await fn(page)
        except Exception as exc:  # noqa: BLE001 — 진단이므로 실패해도 계속.
            out["timeline"].append({"after": label, "error": str(exc)[:200]})
        await page.wait_for_timeout(400)
        await snap(label)

    try:
        await vr.set_docu_types(page, vr.DOCU_TYPES_RECEIVABLE)
    except Exception as exc:  # noqa: BLE001
        out["timeline"].append({"after": "전표유형", "error": str(exc)[:200]})
    await page.wait_for_timeout(600)
    await snap("전표유형(팝업)")
    return out


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 환경변수를 주고 실행하세요.", file=sys.stderr)
        return 2
    settings = get_settings()
    report: dict = {
        "userid": USERID,
        "erp_base": settings.erp_base,
        "target": {"start": TARGET_START, "end": TARGET_END},
    }
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
        page = await ctx.new_page()
        try:
            await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)
            await page.wait_for_timeout(1_200)
            # 전표유형이 optional-area 라 조회조건 패널을 펼쳐야 기간 위젯이 확실히 보인다.
            from app.agents.voucher_receivable import steps as vr_steps

            await vr_steps.expand_condition_panel(page)
            await page.wait_for_timeout(500)
            report["voucher_screen"] = await _probe_field(page, "#s_period", "전표조회승인")
            report["reset_diag"] = await _probe_reset_by_later_fields(page, "#s_period")
            await page.screenshot(path=str(ARTIFACTS / "voucher_period_probe_01_voucher.png"))

            # 결의서조회승인(카드 수집 화면) — 같은 축을 별도 탭에서 확인.
            opened = await card_steps.open_collect_tab(page)
            report["collect_tab_open"] = opened
            if isinstance(opened, dict) and opened.get("ok"):
                await page.wait_for_timeout(1_000)
                report["collect_screen"] = await _probe_field(page, "#PERIOD_DT_C", "결의서조회승인")
                await page.screenshot(path=str(ARTIFACTS / "voucher_period_probe_02_collect.png"))
        finally:
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            await ctx.close()
            await browser.close()
    print(f"완료 — {OUT}")
    for key in ("voucher_screen", "collect_screen"):
        scr = report.get(key)
        if not scr:
            continue
        print(f"\n[{scr['label']}] 추정 id 존재: {scr['dump'].get('guessed_ids')}")
        print(f"  입력 개수: {len(scr['dump'].get('inputs') or [])} / dewsControl: {scr['dump'].get('has_dewsControl')}")
        for t in scr["trials"]:
            print(
                f"  - {t['strategy']:28s}: view={t.get('view_matches')} model={t.get('model_matches')}"
                + (f" err={t['error']}" if t.get("error") else "")
            )
    diag = report.get("reset_diag")
    if diag:
        print("\n[되돌림 진단] 회계일 세팅 후 나머지 조회조건을 순서대로 적용")
        for t in diag["timeline"]:
            mark = "유지" if t.get("holds") else "★되돌려짐"
            print(f"  after {t['after']:20s} model={t.get('model')} {mark}"
                  + (f" err={t['error']}" if t.get("error") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
