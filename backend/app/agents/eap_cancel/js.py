"""전자결재(EAP) 리스트 읽기 JS — 읽기 전용 단일 소스.

EAP 는 dews 그리드가 아니라 **React 리스트**다(실측 2026-08-07, e2e/artifacts/eap_dom_diag.json).
행은 `li.listChk` 이고, 행마다 비어있지 않은 span 은 '기안일: …' 툴팁과 **제목** 2개뿐이며,
상태는 행 텍스트 끝의 `진행 (결재자)` / `종결 (…)` 패턴이다. 그래서 dewsControl 계열
프리미티브(js_lib)가 아니라 이 화면 전용 JS 를 둔다.

⚠ 두 JS 모두 화면을 바꾸지 않는다(읽기 전용). 클릭·값설정은 steps.py 가 Playwright 로 한다.
"""

from __future__ import annotations

# 리스트 전 행 덤프. status/approver 는 행 텍스트의 마지막 `상태 (결재자)` 매치에서 뽑는다
# (앞쪽 제목에 같은 낱말이 섞여도 마지막 매치가 상태 배지다 — 프로브 실측 규칙).
ROWS_DUMP_JS = """() => {
  const clean = s => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();
  return [...document.querySelectorAll('li.listChk')].map(r => {
    const text = clean(r.innerText);
    const spans = [...r.querySelectorAll('span')].map(s => clean(s.innerText)).filter(Boolean);
    const title = spans.filter(t => !t.startsWith('기안일'))[0] || '';
    const date = clean((r.querySelector('.dateText') || {}).innerText || '');
    const m = [...text.matchAll(/(진행|종결|반려|회수|완료)\\s*\\(([^)]*)\\)/g)];
    const last = m.length ? m[m.length - 1] : null;
    return {
      text, title, date,
      status: last ? last[1] : '',
      approver: last ? clean(last[2]) : '',
    };
  }).filter(r => r.text);
}"""

# 제목을 포함하는 span 개수 — 리스트에 그 문서가 (있는지/사라졌는지) 판정한다.
# 0=없음, 1=확정, 2+=동명 문서 모호(호출부가 사전 가드로 걸러 여기 도달하지 않게 한다).
TITLE_COUNT_JS = """(t) =>
  [...document.querySelectorAll('span')].filter(s => (s.innerText || '').includes(t)).length"""
