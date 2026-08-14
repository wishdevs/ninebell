"""LLM 호출별 파일 로그 — 호출 1건 = 메타(.log) + 요청/응답(.json).

세 파일 모두 **유효한 JSON**이어야 한다(jq·스크립트로 바로 파싱). 한글은 이스케이프되지 않고
그대로 보여야 한다.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.agents.common import llm_file_log, prompt_capture
from app.config import get_settings

_URL_GEMINI = "https://llm.example/v1beta/models/gemini-3.6-flash:generateContent"


@pytest.fixture
def llm_dir(tmp_path, monkeypatch):
    """llm_log_dir 을 tmp 로 돌리고 미완 호출 상태를 초기화한다."""
    monkeypatch.setattr(get_settings(), "llm_log_dir", str(tmp_path / "llm"), raising=False)
    llm_file_log._pending.clear()
    yield tmp_path / "llm"
    llm_file_log._pending.clear()


def _trio(d):
    """한 호출이 남긴 (meta, request, response) 를 JSON 으로 읽어 반환."""
    metas = sorted(d.glob("*.log"))
    assert len(metas) == 1, f"메타 파일이 1개여야 하는데 {len(metas)}개"
    meta = json.loads(metas[0].read_text(encoding="utf-8"))
    stem = metas[0].with_suffix("")
    req = json.loads(stem.with_suffix(".request.json").read_text(encoding="utf-8"))
    res_path = stem.with_suffix(".response.json")
    res = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else None
    return meta, req, res


def test_call_produces_meta_request_and_response_files(llm_dir):
    seq = prompt_capture.capture_request("gemini", _URL_GEMINI, {"system": "지시문"})
    prompt_capture.capture_response("gemini", _URL_GEMINI, seq, {"candidates": ["결과"]})

    assert len(list(llm_dir.glob("*"))) == 3
    meta, req, res = _trio(llm_dir)
    assert req == {"system": "지시문"}
    assert res == {"candidates": ["결과"]}
    assert meta["seq"] == seq
    assert meta["provider"] == "gemini"
    assert meta["url"] == _URL_GEMINI


def test_meta_carries_timing_and_sizes(llm_dir):
    seq = prompt_capture.capture_request("gemini", _URL_GEMINI, {"system": "지시문"})
    prompt_capture.capture_response("gemini", _URL_GEMINI, seq, {"ok": 1})

    meta, _, _ = _trio(llm_dir)
    assert meta["requestedAt"] and meta["respondedAt"]
    assert isinstance(meta["elapsedMs"], int) and meta["elapsedMs"] >= 0
    assert meta["requestBytes"] > 0 and meta["responseBytes"] > 0
    assert meta["requestFile"].endswith(".request.json")
    assert meta["responseFile"].endswith(".response.json")


def test_meta_marks_call_without_response(llm_dir):
    """응답이 안 온 호출은 메타의 응답 필드가 비어 있어 바로 식별된다."""
    prompt_capture.capture_request("gemini", _URL_GEMINI, {"system": "지시문"})

    meta, _, res = _trio(llm_dir)
    assert res is None
    assert meta["respondedAt"] is None
    assert meta["elapsedMs"] is None


def test_payload_files_are_valid_json_with_readable_korean(llm_dir):
    """핵심 요구 — 결과물이 JSON 이고, 한글이 \\uXXXX 로 깨지지 않는다."""
    prompt = "당신은 보조자입니다.\n규칙 1: 시각을 보라."
    seq = prompt_capture.capture_request("gemini", _URL_GEMINI, {"system": prompt})
    prompt_capture.capture_response("gemini", _URL_GEMINI, seq, {"결과": "완료"})

    stem = sorted(llm_dir.glob("*.log"))[0].with_suffix("")
    raw_req = stem.with_suffix(".request.json").read_text(encoding="utf-8")
    raw_res = stem.with_suffix(".response.json").read_text(encoding="utf-8")

    assert "당신은 보조자입니다" in raw_req  # ensure_ascii=False.
    assert "\\u" not in raw_req
    assert json.loads(raw_req)["system"] == prompt  # 개행까지 원문 그대로 복원된다.
    assert json.loads(raw_res) == {"결과": "완료"}


def test_filename_is_datetime_plus_url_slug(llm_dir):
    seq = prompt_capture.capture_request(
        "etribe", "http://172.20.50.2:30001/v1/chat/completions", {"model": "ETRIBE-LLM"}
    )
    prompt_capture.capture_response("etribe", "http://x/v1/chat/completions", seq, {"ok": 1})

    name = sorted(llm_dir.glob("*.log"))[0].name
    stamp, slug, tail = name.split("_")
    assert len(stamp) == 15 and stamp[8] == "-" and stamp.replace("-", "").isdigit()
    assert slug == "completion"
    assert tail == f"{seq}.log"


def test_url_slug_distinguishes_providers():
    """앞 10자('https://ge')는 모든 호출이 같아 쓸모없다 — 뒤에서 따는지 확인."""
    assert llm_file_log._slug(_URL_GEMINI) == "generateCo"
    assert llm_file_log._slug("http://y/v1/chat/completions") == "completion"
    assert llm_file_log._slug("https://z/") == "z"


def test_screenshot_and_secrets_not_written(llm_dir):
    """와이어 로그와 같은 위생 규칙 — base64 이미지 생략, 자격증명·쿼리 비밀값 마스킹."""
    blob = "Z" * 4_000
    seq = prompt_capture.capture_request(
        "gemini",
        f"{_URL_GEMINI}?key=AIzaSECRET",
        {"api_key": "sk-LEAK", "parts": [{"inline_data": {"mime_type": "image/jpeg", "data": blob}}]},
    )
    prompt_capture.capture_response("gemini", _URL_GEMINI, seq, {"ok": 1})

    meta, req, _ = _trio(llm_dir)
    dumped = json.dumps([meta, req], ensure_ascii=False)
    assert blob not in dumped
    assert "sk-LEAK" not in dumped
    assert "AIzaSECRET" not in dumped
    assert "image base64 생략" in dumped


def test_disabled_when_dir_unset(tmp_path, monkeypatch):
    """디렉터리 미설정이면 파일을 만들지 않는다 — 배포 기본값."""
    monkeypatch.setattr(get_settings(), "llm_log_dir", "", raising=False)
    llm_file_log._pending.clear()

    seq = prompt_capture.capture_request("gemini", _URL_GEMINI, {"a": 1})
    prompt_capture.capture_response("gemini", _URL_GEMINI, seq, {"b": 2})

    assert list(tmp_path.rglob("*.json")) == []


def test_parallel_calls_do_not_collide(llm_dir):
    """추천은 청크 3개가 동시에 나간다 — 같은 초라도 seq 로 파일이 갈려야 한다."""
    seqs = [prompt_capture.capture_request("gemini", _URL_GEMINI, {"chunk": i}) for i in range(3)]
    for s in seqs:
        prompt_capture.capture_response("gemini", _URL_GEMINI, s, {"done": s})

    metas = sorted(llm_dir.glob("*.log"))
    assert len(metas) == 3
    assert len(list(llm_dir.glob("*.request.json"))) == 3
    assert len(list(llm_dir.glob("*.response.json"))) == 3
    assert {json.loads(m.read_text(encoding="utf-8"))["seq"] for m in metas} == set(seqs)


def test_response_without_request_is_ignored(llm_dir):
    llm_file_log.write_response(999_999, "gemini", _URL_GEMINI, {"orphan": True})

    assert not llm_dir.exists() or list(llm_dir.glob("*")) == []


def test_pending_map_is_bounded(llm_dir):
    """응답이 안 오는 호출(예외·타임아웃)이 쌓여도 메모리를 먹지 않는다."""
    for i in range(llm_file_log._MAX_PENDING + 20):
        prompt_capture.capture_request("gemini", _URL_GEMINI, {"i": i})

    assert len(llm_file_log._pending) <= llm_file_log._MAX_PENDING


def test_write_failure_does_not_raise(llm_dir, monkeypatch, caplog):
    """파일 기록 실패가 LLM 호출을 죽이면 안 된다."""
    caplog.set_level(logging.DEBUG, logger="app.agents.common.llm_file_log")
    monkeypatch.setattr(llm_file_log, "_resolve_dir", lambda: (_ for _ in ()).throw(OSError("boom")))

    seq = prompt_capture.capture_request("gemini", _URL_GEMINI, {"a": 1})

    assert isinstance(seq, int)
