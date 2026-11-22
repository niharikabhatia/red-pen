"""Provider adapters: response parsing and error classification (no network)."""

from __future__ import annotations

from types import SimpleNamespace as NS

from factcheck.llm import GeminiClient, _gemini_citations, classify_error, make_client


def test_gemini_citations_from_grounding_metadata():
    response = NS(candidates=[NS(grounding_metadata=NS(grounding_chunks=[
        NS(web=NS(uri="https://a.example/1", title="statcounter.com")),
        NS(web=NS(uri="https://a.example/1", title="dup")),
        NS(web=NS(uri="https://b.example/2", title=None)),
        NS(web=None),
    ]))])
    sources = _gemini_citations(response)
    assert [s.url for s in sources] == ["https://a.example/1", "https://b.example/2"]
    assert sources[0].title == "statcounter.com" and sources[1].title == "https://b.example/2"


def test_gemini_client_sends_search_tool_only_for_web_search():
    client = make_client("gemini", "fake-key", "gemini-2.5-flash")
    assert isinstance(client, GeminiClient)
    assert client.client._api_client._http_options.api_version == "v1beta"
    calls = []

    def generate_content(model, contents, config):
        calls.append(config)
        return NS(text='{"ok": true}', candidates=[])

    client.client = NS(models=NS(generate_content=generate_content))
    assert client.complete("sys", "hi").text == '{"ok": true}'
    client.complete("sys", "hi", web_search=True)
    assert calls[0].tools is None
    assert calls[1].tools[0].google_search is not None
    assert calls[1].system_instruction == "sys"


def test_classify_rate_limits_are_retryable():
    err = classify_error("gemini", Exception('429 RESOURCE_EXHAUSTED {"retryDelay": "33s"}'))
    assert err.retryable and err.retry_after == 33 and "Gemini" in str(err)
    err = classify_error("openai", Exception("Rate limit reached. Please try again in 12.5s."))
    assert err.retryable and err.retry_after == 12


def test_classify_permanent_errors():
    assert not classify_error("openai", Exception("insufficient_quota")).retryable
    assert "Invalid Gemini API key" in str(classify_error("gemini", Exception("API key not valid")))
    daily = classify_error("gemini", Exception("429 quota exceeded: GenerateRequestsPerDay"))
    assert not daily.retryable and "daily" in str(daily)
