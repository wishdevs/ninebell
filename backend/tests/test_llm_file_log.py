"""LLM 호출별 파일 로그 — 호출 1건 = 파일 1개(요청 URL·바디 + 응답).

핵심 요구는 **눈으로 읽을 수 있을 것**이다. 한 줄 로그(app.llm.wire)는 프롬프트가 수천 자라
읽을 수 없어서 만든 기능이므로, 개행이 펴져 나오는지·한글이 그대로인지를 함께 감시한다.
"""

from __future__ import annotations

import logging

import pytest

from app.agents.common import llm_file_log, prompt_capture
from app.config import get_settings


@pytest.fixture
def llm_dir(tmp_path, monkeypatch):
    """llm_log_dir 을 tmp 로 돌리고 미완 호출 상태를 초기화한다."""
    monkeypatch.setattr(get_settings(), "llm_log_dir", str(tmp_path / "llm"), raising=False)
    llm_file_log._pending.clear()
    yield tmp_path / "llm"
    llm_file_log._pending.clear()


def _only_file(d):
    files = sorted(d.glob("*.log"))
    assert len(files) == 1, f"파일이 1개여야 하는데 {len(files)}개"
    return files[0]


def test_writes_one_file_per_call_with_request_and_response(llm_dir):
    seq = prompt_capture.capture_request(
        "gemini", "https://llm.example/v1beta/models/x:generateContent", {"system": "지시문"}
    )
    prompt_capture.capture_response(
        "gemini", "https://llm.example/v1beta/models/x:generateContent", seq, {"candidates": ["결과"]}
    )

    text = _only_file(llm_dir).read_text(encoding="utf-8")
    assert "REQUEST" in text and "RESPONSE" in text
    assert "url  : https://llm.example/v1beta/models/x:generateContent" in text
    assert "지시문" in text  # 요청 바디
    assert "결과" in text  # 응답 바디
    assert f"seq={seq}" in text
    assert "took :" in text


def test_filename_is_datetime_plus_url_slug(llm_dir):
    seq = prompt_capture.capture_request(
        "etribe", "http://172.20.50.2:30001/v1/chat/completions", {"model": "ETRIBE-LLM"}
    )
    prompt_capture.capture_response("etribe", "http://x/v1/chat/completions", seq, {"ok": 1})

    name = _only_file(llm_dir).name
    # YYYYMMDD-HHMMSS_<url10>_<seq>.log
    stamp, slug, tail = name.split("_")
    assert len(stamp) == 15 and stamp[8] == "-"
    assert stamp.replace("-", "").isdigit()
    assert slug == "completion"  # 마지막 경로 조각의 10자.
    assert tail == f"{seq}.log"


def test_url_slug_distinguishes_providers(llm_dir):
    """앞 10자('https://ge')는 모든 호출이 같아 쓸모없다 — 뒤에서 따는지 확인."""
    assert llm_file_log._slug("https://x/v1beta/models/g:generateContent") == "generateCo"
    assert llm_file_log._slug("http://y/v1/chat/completions") == "completion"
    assert llm_file_log._slug("https://z/") == "z"  # 빈 조각이면 앞으로 물러난다.


def test_content_is_readable_newlines_unescaped(llm_dir):
    """가독성이 핵심 — JSON 이스케이프(\\n)가 아니라 실제 줄바꿈으로 보여야 한다."""
    prompt = "당신은 보조자입니다.\n규칙 1: 시각을 보라.\n규칙 2: 과거 선택을 보라."
    seq = prompt_capture.capture_request("gemini", "https://llm/x:generateContent", {"system": prompt})
    prompt_capture.capture_response("gemini", "https://llm/x:generateContent", seq, {"ok": 1})

    text = _only_file(llm_dir).read_text(encoding="utf-8")
    assert "\\n" not in text  # 이스케이프가 남아 있으면 읽을 수 없다.
    assert "규칙 1: 시각을 보라." in text
    assert "규칙 2: 과거 선택을 보라." in text


def test_screenshot_and_secrets_not_written(llm_dir):
    """와이어 로그와 같은 위생 규칙 — base64 이미지 생략, 자격증명 마스킹."""
    blob = "Z" * 4_000
    seq = prompt_capture.capture_request(
        "gemini",
        "https://llm/x:generateContent?key=AIzaSECRET",
        {"api_key": "sk-LEAK", "parts": [{"inline_data": {"mime_type": "image/jpeg", "data": blob}}]},
    )
    prompt_capture.capture_response("gemini", "https://llm/x:generateContent", seq, {"ok": 1})

    text = _only_file(llm_dir).read_text(encoding="utf-8")
    assert blob not in text
    assert "sk-LEAK" not in text
    assert "AIzaSECRET" not in text
    assert "image base64 생략" in text


def test_disabled_when_dir_unset(tmp_path, monkeypatch):
    """디렉터리 미설정이면 파일을 만들지 않는다 — 배포 기본값."""
    monkeypatch.setattr(get_settings(), "llm_log_dir", "", raising=False)
    llm_file_log._pending.clear()

    seq = prompt_capture.capture_request("gemini", "https://llm/x", {"a": 1})
    prompt_capture.capture_response("gemini", "https://llm/x", seq, {"b": 2})

    assert list(tmp_path.rglob("*.log")) == []


def test_parallel_calls_do_not_collide(llm_dir):
    """추천은 청크 3개가 동시에 나간다 — 같은 초라도 seq 로 파일이 갈려야 한다."""
    seqs = [
        prompt_capture.capture_request("gemini", "https://llm/x:generateContent", {"chunk": i})
        for i in range(3)
    ]
    for s in seqs:
        prompt_capture.capture_response("gemini", "https://llm/x:generateContent", s, {"done": s})

    files = sorted(llm_dir.glob("*.log"))
    assert len(files) == 3
    for s, f in zip(seqs, files, strict=True):
        assert f"seq={s}" in f.read_text(encoding="utf-8")


def test_response_without_request_is_ignored(llm_dir):
    llm_file_log.write_response(999_999, "gemini", "https://llm/x", {"orphan": True})

    assert list(llm_dir.glob("*.log")) == [] if llm_dir.exists() else True


def test_pending_map_is_bounded(llm_dir):
    """응답이 안 오는 호출(예외·타임아웃)이 쌓여도 메모리를 먹지 않는다."""
    for i in range(llm_file_log._MAX_PENDING + 20):
        prompt_capture.capture_request("gemini", "https://llm/x:generateContent", {"i": i})

    assert len(llm_file_log._pending) <= llm_file_log._MAX_PENDING


def test_write_failure_does_not_raise(llm_dir, monkeypatch, caplog):
    """파일 기록 실패가 LLM 호출을 죽이면 안 된다."""
    caplog.set_level(logging.DEBUG, logger="app.agents.common.llm_file_log")
    monkeypatch.setattr(llm_file_log, "_resolve_dir", lambda: (_ for _ in ()).throw(OSError("boom")))

    seq = prompt_capture.capture_request("gemini", "https://llm/x", {"a": 1})  # 예외 없이 통과.

    assert isinstance(seq, int)
