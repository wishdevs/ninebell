"""시간축 규율 소스 린트 — '명목 카운터' 루프 재유입 방지(2026-08-07 무결성 감사).

규율: 관찰 **상한**은 항상 실시간(monotonic·latency.budget_ms + verify.DEFAULT_SLEEP)이고,
``page.wait_for_timeout`` 은 delay_scale(_ScaledPage)로 축소되는 **정상 경로 단축** 전용이다.
``await page.wait_for_timeout(N)`` 뒤 ``waited += N`` 으로 세는 루프는 delay_scale=0.4 에서
관찰창이 실효 40%로 붕괴한다(실측: voucher `_apply_popup` 8s→3.2s — set_query 간헐 실패의
배후 증폭기였고 2026-08-07 에 실시간 sleep 으로 전환).

검사 휴리스틱: 누산 줄 위로 8줄 안에 ``wait_for_timeout`` 이 보이면 명목 카운터 루프로 본다.
정당한 예외(예: 명목 누산이 의도적으로 폴 횟수 상한 역할만 하는 자리)는 누산 줄에
``# time-axis: nominal-ok`` 주석을 달아 통과시킨다 — 예외는 근거와 함께.

`tests/test_condition_polling_conversions.py` 가 **동작** 계약을 고정한다면, 이 파일은
**소스 형태** 계약을 고정한다(상보적).
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
# 확산(2026-08-07): steps.py 한정 → 에이전트 전 파일 + nbkit patterns/grid 로 확대.
# (doc_steps.py·expense_card/tools.py 등 steps.py 밖에서 명목 카운터가 재발견된 실측 근거.)
TARGETS = [
    *sorted((BACKEND / "app" / "agents").glob("**/*.py")),
    *sorted((BACKEND / "nbkit" / "omnisol").glob("*.py")),
    *sorted((BACKEND / "nbkit" / "browser").glob("*.py")),
    *sorted((BACKEND / "nbkit" / "patterns").glob("*.py")),
    *sorted((BACKEND / "nbkit" / "grid").glob("*.py")),
]

_LOOKBACK_LINES = 8  # 누산 줄 위로 이만큼 안에서 wait_for_timeout 을 찾는다.


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def test_no_nominal_counter_loops():
    assert TARGETS, "린트 대상 파일 수집 실패(경로 확인)"
    offenders: list[str] = []
    for path in TARGETS:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "waited +=" not in line or "time-axis: nominal-ok" in line or _is_comment(line):
                continue
            # 주석(설명문)에 등장하는 wait_for_timeout 은 오탐 — 코드 줄만 본다.
            window = "\n".join(
                ln for ln in lines[max(0, i - _LOOKBACK_LINES) : i + 1] if not _is_comment(ln)
            )
            if "wait_for_timeout" in window:
                offenders.append(f"{path.relative_to(BACKEND)}:{i + 1}")
    assert not offenders, (
        "명목 카운터 루프(관찰창이 delay_scale 로 붕괴) 발견 — 상한은 latency.budget_ms, "
        f"폴 대기는 verify.DEFAULT_SLEEP(실시간)로 전환하세요: {offenders}"
    )
