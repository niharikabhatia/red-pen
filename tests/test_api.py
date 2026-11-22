"""API tests with FastAPI's TestClient and a fake LLM."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.index as api_module
from factcheck.llm import LLMError
from tests.test_pipeline import FakeLLM

client = TestClient(api_module.app)
PAGES = [{"page": 1, "text": "Google holds 98% of the global search market. Nvidia was founded in 1993."}]


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    llm = FakeLLM({"98%": {"verdict": "Inaccurate", "correct_fact": "About 90%", "confidence": 88}})
    llm.made = []  # (provider, key, model) of every client built

    def make_client(provider, key, model):
        llm.made.append((provider, key, model))
        return llm

    monkeypatch.setattr(api_module.factcheck, "make_client", make_client)
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "GEMINI_MODEL", "OPENAI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    return llm


def test_health():
    body = client.get("/api/health").json()
    assert body["ok"] and body["server_key"]
    assert body["default_provider"] == "openai"
    assert body["providers"]["openai"]["server_key"] is True
    assert body["providers"]["gemini"]["server_key"] is False


def test_gemini_is_default_when_its_key_is_set(monkeypatch, fake_llm):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    assert client.get("/api/health").json()["default_provider"] == "gemini"
    client.post("/api/extract", json={"pages": PAGES})
    assert fake_llm.made[-1] == ("gemini", "g-key", "gemini-2.5-flash")


def test_provider_header_and_user_key(fake_llm):
    r = client.post("/api/extract", json={"pages": PAGES},
                    headers={"X-LLM-Provider": "gemini", "X-API-Key": "mine", "X-LLM-Model": "gemini-2.5-pro"})
    assert r.status_code == 200
    assert fake_llm.made[-1] == ("gemini", "mine", "gemini-2.5-pro")


def test_extract_and_verify_flow():
    claims = client.post("/api/extract", json={"pages": PAGES}).json()["claims"]
    assert claims[0]["text"].startswith("Google")
    result = client.post("/api/verify", json={"claim": claims[0]}).json()
    assert result["verdict"] == "Inaccurate" and result["needs_second_opinion"] is False


def test_missing_key_returns_401(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    r = client.post("/api/extract", json={"pages": PAGES})
    assert r.status_code == 401 and "API key" in r.json()["detail"]
    # ...but a user-supplied key works (legacy header too)
    assert client.post("/api/extract", json={"pages": PAGES}, headers={"X-OpenAI-Key": "mine"}).status_code == 200


def test_rejects_unknown_model_and_provider():
    assert client.post("/api/extract", json={"pages": PAGES}, headers={"X-LLM-Model": "gpt-9"}).status_code == 400
    assert client.post("/api/extract", json={"pages": PAGES}, headers={"X-LLM-Provider": "bard"}).status_code == 400


def test_empty_and_oversized_documents():
    assert client.post("/api/extract", json={"pages": [{"page": 1, "text": "  "}]}).status_code == 422
    huge = [{"page": 1, "text": "x" * 130_000}]
    assert client.post("/api/extract", json={"pages": huge}).status_code == 413


def test_non_retryable_failure_is_502(monkeypatch, fake_llm):
    def boom(*a, **k):
        raise LLMError("OpenAI API quota exhausted.")

    monkeypatch.setattr(fake_llm, "complete", boom)
    r = client.post("/api/extract", json={"pages": PAGES})
    assert r.status_code == 502 and "quota" in r.json()["detail"]


def test_rate_limit_is_429_with_retry_after(monkeypatch, fake_llm):
    def limited(*a, **k):
        raise LLMError("Gemini rate limit reached", retryable=True, retry_after=33)

    monkeypatch.setattr(fake_llm, "complete", limited)
    claim = {"id": 1, "text": "Google holds 98%.", "quote": "98%"}
    for path, body in [("/api/extract", {"pages": PAGES}), ("/api/verify", {"claim": claim})]:
        r = client.post(path, json=body)
        assert r.status_code == 429, path
        assert r.headers["retry-after"] == "33" and r.json()["retry_after"] == 33


def test_consistency_and_correct():
    claims = [{"id": 1, "text": "A 98%", "quote": "98%"}, {"id": 2, "text": "B 50%"}]
    assert client.post("/api/consistency", json={"claims": claims}).json()["contradictions"][0]["claim_ids"] == [1, 2]
    results = [{"claim_id": 1, "verdict": "Inaccurate", "correct_fact": "90%"}]
    out = client.post("/api/correct", json={"claims": claims, "results": results}).json()
    assert out["corrections"][0]["claim_id"] == 1
