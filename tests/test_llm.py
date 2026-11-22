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


GEMINI_FREE_TIER_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, "
    "please check your plan and billing details. Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 10, model: "
    "gemini-2.5-flash. Please retry in 33.4s.', 'status': 'RESOURCE_EXHAUSTED', 'details': "
    "[{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}]}}"
)


def test_gemini_free_tier_429_is_retryable_despite_billing_wording():
    err = classify_error("gemini", Exception(GEMINI_FREE_TIER_429))
    assert err.retryable and err.retry_after == 33


def test_gemini_daily_quota_is_not_retryable():
    msg = GEMINI_FREE_TIER_429.replace("PerMinute", "PerDay")
    assert not classify_error("gemini", Exception(msg)).retryable


def test_gemini_citations_use_real_domain():
    response = NS(candidates=[NS(grounding_metadata=NS(grounding_chunks=[
        NS(web=NS(uri="https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                  title="Search Engine Market Share", domain="gs.statcounter.com")),
        NS(web=NS(uri="https://vertexaisearch.cloud.google.com/grounding-api-redirect/def",
                  title="reuters.com", domain="reuters.com")),
    ]))])
    labels = [s.title for s in _gemini_citations(response)]
    assert labels == ["gs.statcounter.com · Search Engine Market Share", "reuters.com"]


def test_complete_json_recovers_prose_with_formatting_pass():
    from factcheck.llm import LLMResponse, Source, complete_json

    class Prose:
        model = "x"
        def __init__(self):
            self.calls = []
        def complete(self, instructions, prompt, web_search=False):
            self.calls.append(web_search)
            if len(self.calls) == 1:
                return LLMResponse("The claim is inaccurate; Google has about 91%.",
                                   citations=[Source(title="s", url="https://s.example")])
            return LLMResponse('{"verdict": "Inaccurate", "correct_fact": "~91%"}')

    llm = Prose()
    data, response = complete_json(llm, 'Respond with JSON only: {"verdict": "..."}', "CLAIM: x", web_search=True)
    assert data["verdict"] == "Inaccurate"
    assert llm.calls == [True, False]  # formatting pass runs without search
    assert response.citations[0].url == "https://s.example"
