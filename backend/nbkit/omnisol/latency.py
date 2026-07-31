"""프로세스 전역 지연 배율(latency factor) — 조건 폴링 **상한**만 확대하는 적응형 대기.

배경: verify 커널의 점증 대기(INSTANT 1.38s / HEAVY 6.9s)와 그리드·피커 폴링 상한은 평시
ERP 속도 실측 기준이다. 네트워크·ERP 가 느려지면 정상 진행 중인 작업이 '상한 소진'으로
실패 오판된다 — 실측 지연 관측(actual/expected 비율)을 EMA 로 누적해 배율을 만들고,
**조건 폴링의 상한/대기 스텝에만** 곱한다.

설계 원칙:
  * **성공 경로 불변** — 조건 충족 시 즉시 진행은 그대로, 고정 sleep 추가 금지. 배율 하한
    1.0(현재보다 빨라지게 하지 않음), 상한 4.0 클램프(HEAVY 6.9s → 최대 27.6s).
  * **프로세스 전역** — 같은 서버의 모든 런이 같은 ERP·네트워크를 보므로 전역 EMA 가 적절
    (동시 런이 관측을 공유). 단일 이벤트 루프라 락 불필요, 재시작 시 1.0 리셋.
  * **자기되먹임** — 관측이 빠르면(비율 1.0) 1.0 으로 감쇠, 느리면 상승. 별도 사전 측정
    단계 없음(런을 느리게 만들지 않는다).
  * **delay_scale 과 직교** — delay_scale(runner _ScaledPage)은 정상 경로의 고정 sleep 을
    *축소*하고, 이 배율은 실패·지연 시 재시도 상한만 *확대*한다. 서로 곱하거나 간섭하지
    않는다(verify.py 모듈 docstring 참조).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_ALPHA = 0.3  # EMA 가중 — 최근 관측 반응성과 단발 스파이크 내성의 절충.
FLOOR = 1.0  # 배율 하한 — 상한을 현재보다 줄이지 않는다.
CEIL = 4.0  # 배율 상한 — 폭주 방지(예: HEAVY 6.9s → 최대 27.6s).
_WARN_FROM = 1.5  # 이 배율을 **넘으면** 지연 감지 경고(0.5 단위 전이마다 1회 — 스팸 방지).

_ema: float = FLOOR
_warned_bucket: int = 0  # 마지막 경고 버킷(int(factor*2)). 0 = 미경고/정상.


def record(expected_ms: float, actual_ms: float) -> None:
    """지연 관측 1건 누적 — 비율(actual/expected, 1.0 미만은 1.0)을 EMA 로 흘린다.

    비율의 상한도 CEIL 로 클램프한다 — 단발 이상치(행 걸림·GC 등)가 EMA 를 CEIL 밖으로
    밀어 올려 회복(감쇠)까지 오래 끄는 것을 막는다. 잘못된 인자(expected<=0)는 무시.
    """
    global _ema
    if expected_ms <= 0 or actual_ms < 0:
        return
    ratio = min(CEIL, max(FLOOR, actual_ms / expected_ms))
    _ema = _ema + _ALPHA * (ratio - _ema)
    _maybe_warn()


def factor() -> float:
    """현재 배율 — clamp(EMA, 1.0, 4.0). **상한/대기 스텝에만** 곱한다(고정 sleep 금지)."""
    return min(CEIL, max(FLOOR, _ema))


def budget_ms(base_ms: float) -> int:
    """base 상한(ms) × 배율 = 실효 상한 — monotonic 관찰창·점증 대기 스텝용."""
    return int(base_ms * factor())


def budget_polls(base_polls: int) -> int:
    """폴 **횟수** 상한 × 배율 — 폴 간격은 불변, 회수만 늘려 상한을 확대한다."""
    return int(base_polls * factor())


def reset() -> None:
    """테스트 훅 — EMA·경고 상태를 초기화한다(프로세스 재시작과 동일한 1.0)."""
    global _ema, _warned_bucket
    _ema = FLOOR
    _warned_bucket = 0


def _maybe_warn() -> None:
    """배율 상태 전이 시 1회 경고 — 0.5 단위 버킷이 바뀔 때만 로그(스팸 방지)."""
    global _warned_bucket
    f = factor()
    if f <= _WARN_FROM:
        if _warned_bucket:
            _warned_bucket = 0
            logger.info("ERP 응답 지연 해소 — 대기 상한 배율 ×%.1f 로 복귀", f)
        return
    bucket = int(f * 2)  # 0.5 단위 버킷(1.5<f<2.0 → 3, 2.0≤f<2.5 → 4 …).
    if bucket != _warned_bucket:
        _warned_bucket = bucket
        logger.warning("ERP 응답 지연 감지 — 대기 상한 ×%.1f", f)
