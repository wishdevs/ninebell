"""nbkit 단위 테스트 공용 픽스처 — 프로세스 전역 지연 배율(latency) 격리.

latency 의 EMA 는 프로세스 전역이라, 한 테스트의 관측(record)이 같은 프로세스에서 도는
다른 테스트(tests/ 포함)의 대기·폴 상한(factor)으로 샌다. 매 테스트 전후 리셋해 모든
테스트가 factor=1.0 에서 시작하게 한다(latency 단위 테스트는 자기 테스트 안에서만 누적).
"""

from __future__ import annotations

import pytest

from nbkit.omnisol import latency


@pytest.fixture(autouse=True)
def _reset_latency():
    latency.reset()
    yield
    latency.reset()
