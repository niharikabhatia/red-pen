"""LLM providers behind one tiny interface.

Every caller uses ``client.complete(instructions, prompt, web_search=...)``:
- ``OpenAIClient``: OpenAI Responses API, live web via the built-in ``web_search`` tool.
- ``GeminiClient``: Google Gemini API, live web via Google Search grounding.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from .models import Source

PROVIDERS = ("gemini", "openai")
DEFAULT_MODELS = {"gemini": "gemini-2.5-flash", "openai": "gpt-4.1-mini"}
MODELS = {
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini"],
}
# One request must finish well inside the 60 s serverless limit.
REQUEST_TIMEOUT_S = 50


class LLMError(Exception):
    """A model call failed or returned unusable output.

    ``retryable`` marks temporary rate limits: the caller should wait
    ``retry_after`` seconds and try again instead of giving up.
    """

    def __init__(self, message: str, retryable: bool = False, retry_after: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass
class LLMResponse:
    text: str
    citations: list[Source] = field(default_factory=list)


class LLMClient(Protocol):
    model: str

    def complete(self, instructions: str, prompt: str, web_search: bool = False) -> LLMResponse: ...


def parse_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences and prose."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError(f"Model did not return valid JSON: {text[:200]!r}")


def _retry_after(text: str, default: int = 20) -> int:
    """Pull a retry delay out of an error message.

    Handles "retryDelay": "33s" (Gemini details), "Please retry in 33.4s" (Gemini text)
    and "try again in 12s" (OpenAI).
    """
    match = re.search(
        r"(?:retrydelay['\"]?\s*[:=]\s*['\"]?|retry in\s*|try again in\s*)(\d+(?:\.\d+)?)\s*s", text, re.I
    )
    return max(5, min(60, int(float(match.group(1))))) if match else default


def classify_error(provider: str, exc: Exception) -> LLMError:
    """Turn a provider SDK exception into a user-friendly LLMError."""
    name = "Gemini" if provider == "gemini" else "OpenAI"
    msg = str(exc)
    low = msg.lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)

    # OpenAI "no credit on the account": waiting will not help.
    if "insufficient_quota" in low:
        return LLMError(f"{name} API quota exhausted: add credit to the account or switch provider in Settings.")
    if status in (401, 403) or "invalid_api_key" in low or "api key not valid" in low or "incorrect api key" in low:
        return LLMError(f"Invalid {name} API key. Check it in Settings or in the server configuration.")
    # Rate limits (Gemini's free-tier 429 also mentions "billing details": still temporary).
    if status == 429 or "rate limit" in low or "resource_exhausted" in low or "429" in low:
        if "perday" in low or "per day" in low:
            return LLMError(f"{name} daily free-tier quota used up. Try again tomorrow or use another key.")
        return LLMError(f"{name} rate limit reached; waiting before retrying.", retryable=True,
                        retry_after=_retry_after(msg))
    if status in (500, 502, 503, 504) or "overloaded" in low or "unavailable" in low:
        return LLMError(f"{name} is temporarily overloaded; retrying shortly.", retryable=True, retry_after=10)
    return LLMError(f"{name} error: {msg[:300]}")


FORMAT_INSTRUCTIONS = """\
You convert an answer into the exact JSON format requested below. Keep every fact,
number, verdict and URL from the answer; do not add new information.
Respond with JSON only.

REQUESTED FORMAT (from the original instructions):
{schema}"""


def complete_json(
    llm: "LLMClient", instructions: str, prompt: str, web_search: bool = False
) -> tuple[dict, LLMResponse]:
    """Call the model and parse its JSON reply.

    Grounded answers occasionally come back as prose. Instead of failing the claim,
    run one cheap formatting pass (no search) that converts the answer to JSON.
    """
    response = llm.complete(instructions, prompt, web_search=web_search)
    try:
        return parse_json(response.text), response
    except LLMError:
        if not response.text.strip():
            raise
    idx = instructions.rfind("Respond with JSON only")
    tail = instructions[idx:] if idx >= 0 else instructions[-800:]
    fixed = llm.complete(FORMAT_INSTRUCTIONS.format(schema=tail), f"ANSWER:\n{response.text}")
    return parse_json(fixed.text), LLMResponse(text=fixed.text, citations=response.citations)


# ----------------------------------------------------------------------------- OpenAI
class OpenAIClient:
    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, max_retries=1, timeout=REQUEST_TIMEOUT_S)
        self.model = model

    def complete(self, instructions: str, prompt: str, web_search: bool = False) -> LLMResponse:
        kwargs: dict = {"model": self.model, "instructions": instructions, "input": prompt}
        if web_search:
            kwargs["tools"] = [{"type": "web_search"}]
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            raise classify_error("openai", exc) from exc
        return LLMResponse(text=response.output_text or "", citations=_openai_citations(response))


def _openai_citations(response) -> list[Source]:
    """Collect url_citation annotations from a Responses API result."""
    seen: dict[str, Source] = {}
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            for ann in getattr(part, "annotations", None) or []:
                if getattr(ann, "type", None) == "url_citation" and ann.url not in seen:
                    seen[ann.url] = Source(title=getattr(ann, "title", "") or ann.url, url=ann.url)
    return list(seen.values())


# ----------------------------------------------------------------------------- Gemini
class GeminiClient:
    def __init__(self, api_key: str, model: str):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(
            api_key=api_key,
            # v1beta is required for system instructions + Google Search grounding.
            http_options=types.HttpOptions(api_version="v1beta", timeout=REQUEST_TIMEOUT_S * 1000),
        )
        self.model = model

    def complete(self, instructions: str, prompt: str, web_search: bool = False) -> LLMResponse:
        types = self.types
        config = types.GenerateContentConfig(
            system_instruction=instructions,
            temperature=0.2,
            tools=[types.Tool(google_search=types.GoogleSearch())] if web_search else None,
        )
        try:
            response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
        except Exception as exc:
            raise classify_error("gemini", exc) from exc
        return LLMResponse(text=_gemini_text(response), citations=_gemini_citations(response))


def _gemini_text(response) -> str:
    try:
        return response.text or ""
    except Exception:  # blocked / empty candidates
        return ""


def _gemini_citations(response) -> list[Source]:
    """Sources from Google Search grounding metadata.

    Grounding URIs are Google redirect links (vertexaisearch.cloud.google.com), so the
    real site's domain is kept in the title for display.
    """
    seen: dict[str, Source] = {}
    for cand in getattr(response, "candidates", None) or []:
        meta = getattr(cand, "grounding_metadata", None)
        for chunk in getattr(meta, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            uri = getattr(web, "uri", None)
            if not uri or uri in seen:
                continue
            domain = getattr(web, "domain", None) or ""
            title = getattr(web, "title", None) or ""
            if domain and title and title != domain:
                label = f"{domain} · {title}"
            else:
                label = domain or title or uri
            seen[uri] = Source(title=label, url=uri)
    return list(seen.values())


def make_client(provider: str, api_key: str, model: str) -> LLMClient:
    if provider == "gemini":
        return GeminiClient(api_key, model)
    if provider == "openai":
        return OpenAIClient(api_key, model)
    raise ValueError(f"Unknown provider: {provider}")
