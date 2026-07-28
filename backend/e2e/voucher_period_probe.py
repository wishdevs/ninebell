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
  const inputs = [...el.querySelectorAll('input')].filter(i => digits(i.value).length >= 6);
  const view = inputs.map(i => digits(i.value));
  let model = null;
  try {
    const ctrl = window.jQuery ? window.jQuery(el).data('dewsControl') : null;
    if (ctrl) {
      for (const k of ['getValue', 'value', 'getPeriod', 'getDate']) {
        if (typeof ctrl[k] === 'function') {
          try { model = JSON.parse(JSON.stringify(ctrl[k]() ?? null)); break; } catch (e) {}
        }
      }
      if (model == null) {
        const pick = {};
        ['startDate','endDate','start','end','from','to','_value','value'].forEach(k => {
          try { const v = ctrl[k]; if (typeof v !== 'function' && v != null)
            pick[k] = JSON.parse(JSON.stringify(v)); } catch (e) {}
        });
        if (Object.keys(pick).length) model = pick;
      }
    }
  } catch (e) { model = '(읽기 실패) ' + String(e); }
  return { found: true, view, model };
}"""


# ── 3) 후보 전략들 — 하나씩 적용해보고 모델이 움직이는지 본다 ─────────────────
# 현재 코드(raw input + input/change 이벤트). (b) 가설이면 view 만 바뀌고 model 은 그대로다.
STRAT_RAW_JS = r"""({ sel, start, end }) => {
  const idBase = sel.replace(/^#/, '');
  const si = document.getElementById(idBase + '_startinput');
  const ei = document.getElementById(idBase + '_endinput');
  if (!si || !ei) return { ok: false, reason: 'guessed-ids-not-found' };
  for (const [inp, val] of [[si, start], [ei, end]]) {
    inp.value = val;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
  }
  return { ok: true };
}"""

# 하위 input 을 순서로 잡고(id 규약에 의존하지 않음) 키보드 대신 값+change+blur 를 준다.
STRAT_ORDINAL_JS = r"""({ sel, start, end }) => {
  const el = document.querySelector(sel);
  if (!el) return { ok: false, reason: 'no-field' };
  const inputs = [...el.querySelectorAll('input')];
  if (inputs.length < 2) return { ok: false, reason: 'inputs<2:' + inputs.length };
  const [si, ei] = inputs;
  for (const [inp, val] of [[si, start], [ei, end]]) {
    inp.focus();
    inp.value = val;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    inp.dispatchEvent(new Event('blur', { bubbles: true }));
  }
  return { ok: true };
}"""

# kendo DatePicker 위젯이면 value(Date) + trigger('change') 가 정석 경로.
STRAT_KENDO_JS = r"""({ sel, start, end }) => {
  const $ = window.jQuery;
  if (!$) return { ok: false, reason: 'no-jquery' };
  const el = document.querySelector(sel);
  if (!el) return { ok: false, reason: 'no-field' };
  const toDate = s => new Date(+s.slice(0,4), +s.slice(4,6) - 1, +s.slice(6,8));
  const inputs = [...el.querySelectorAll('input')];
  let n = 0;
  inputs.forEach((i, idx) => {
    const w = $(i).data('kendoDatePicker') || $(i).data('kendoDateInput');
    if (w && typeof w.value === 'function') {
      w.value(toDate(idx === 0 ? start : end));
      try { w.trigger('change'); } catch (e) {}
      n++;
    }
  });
  return n ? { ok: true, widgets: n } : { ok: false, reason: 'no-kendo-datepicker' };
}"""

# dews 컨트롤이 기간 세터를 갖고 있으면 그게 최선 — 이름 후보를 순서대로 시도한다.
STRAT_CTRL_JS = r"""({ sel, start, end }) => {
  const $ = window.jQuery;
  if (!$) return { ok: false, reason: 'no-jquery' };
  const ctrl = $(document.querySelector(sel)).data('dewsControl');
  if (!ctrl) return { ok: false, reason: 'no-dewsControl' };
  const toDate = s => new Date(+s.slice(0,4), +s.slice(4,6) - 1, +s.slice(6,8));
  const tried = [];
  for (const name of ['setPeriod', 'setRange', 'setValue', 'setDate', 'value']) {
    if (typeof ctrl[name] !== 'function') continue;
    for (const args of [[start, end], [toDate(start), toDate(end)],
                        [{ start: start, end: end }], [{ from: start, to: end }]]) {
      try { ctrl[name].apply(ctrl, args); tried.push({ name: name, args: args.length, ok: true }); }
      catch (e) { tried.push({ name: name, args: args.length, ok: false, err: String(e) }); }
    }
  }
  return tried.length ? { ok: true, tried: tried } : { ok: false, reason: 'no-setter-candidates' };
}"""

# 원상복구 — 당월로 되돌린다(프로브가 화면 상태를 남기지 않게).
RESTORE_JS = r"""(sel) => {
  try { window.jQuery(document.querySelector(sel)).data('dewsControl').setMonth(); return true; }
  catch (e) { return false; }
}"""

STRATEGIES = [
    ("raw_input(현재 구현)", STRAT_RAW_JS),
    ("ordinal_input+blur", STRAT_ORDINAL_JS),
    ("kendo_datepicker.value()", STRAT_KENDO_JS),
    ("dewsControl setter 후보", STRAT_CTRL_JS),
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
            blob = json.dumps(after.get("model"), ensure_ascii=False, default=str)
            trial["model_mentions_target"] = (TARGET_START[-4:] in blob) or (
                f"{TARGET_START[:4]}-{TARGET_START[4:6]}-{TARGET_START[6:]}" in blob
            )
        except Exception as exc:  # noqa: BLE001 — 전략 실패는 기록하고 다음으로.
            trial["error"] = str(exc)
        finally:
            await page.evaluate(RESTORE_JS, sel)
            await page.wait_for_timeout(300)
        trials.append(trial)
    res["trials"] = trials
    return res


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
                f"  - {t['strategy']}: view={t.get('view_matches')} model={t.get('model_mentions_target')}"
                + (f" err={t['error']}" if t.get("error") else "")
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
