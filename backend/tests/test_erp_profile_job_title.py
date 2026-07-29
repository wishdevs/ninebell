"""erp.profile 직책 분리 — 패널 이름 "석대현 프로" → 이름/직책 분리(사용자 요청 2026-07-29).

직책이 이름에 섞여 저장되면 법인카드 본인 카드 매칭(카드명 괄호 "(석대현)")에
순수 이름을 쓸 수 없다. split_job_title 이 그 분리 계약의 단일 소스다.
"""

from __future__ import annotations

from app.erp.profile import split_job_title


def test_split_name_with_job_title():
    assert split_job_title("석대현 프로") == ("석대현", "프로")
    assert split_job_title("홍길동 팀장") == ("홍길동", "팀장")


def test_split_name_without_job_title():
    # 직책 토큰이 아니면 원문 유지(외자 이름·복합 이름 보호).
    assert split_job_title("석대현") == ("석대현", "")
    assert split_job_title("김철수 박사") == ("김철수 박사", "")


def test_split_empty_and_whitespace():
    assert split_job_title("") == ("", "")
    assert split_job_title("  석대현   프로  ") == ("석대현", "프로")
