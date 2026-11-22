"""HTTP API (FastAPI). Deployed as a single Vercel Python function.

The browser drives the workflow so every request stays short:
  POST /api/extract      pages of text      -> claims
  POST /api/verify       one claim          -> verdict (+ optional second opinion)
  POST /api/consistency  claims             -> internal contradictions
  POST /api/correct      claims + results   -> corrected passages

AI provider: Gemini (Google Search grounding) or OpenAI (web_search). Chosen per
request with the X-LLM-Provider header, else LLM_PROVIDER, else Gemini when a
GEMINI_API_KEY is configured. Rate limits are returned as HTTP 429 + Retry-After
so the browser can wait and retry instead of failing the report.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import factcheck  # noqa: E402
from factcheck import (  # noqa: E402
    DEFAULT_MODELS, MODELS, PROVIDERS, Claim, ClaimResult, Contradiction, Correction, LLMClient,
    LLMError, Page, correct_document, extract_claims, find_contradictions, verify_claim,
)

MAX_PAGES = 25
MAX_CHARS = 120_000
MAX_CLAIMS = 40
KEY_ENV = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
MODEL_ENV = {"gemini": "GEMINI_MODEL", "openai": "OPENAI_MODEL"}

app = FastAPI(title="Red Pen API", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(LLMError)
async def _llm_error(_request, exc: LLMError):
    if exc.retryable:
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc), "retry_after": exc.retry_after, "provider_message": exc.raw},
            headers={"Retry-After": str(exc.retry_after)},
        )
    return JSONResponse(status_code=502, content={"detail": str(exc), "provider_message": exc.raw})


# ----------------------------------------------------------------------------- providers
def server_key(provider: str) -> str:
    return os.getenv(KEY_ENV[provider], "").strip()


def default_model(provider: str) -> str:
    return os.getenv(MODEL_ENV[provider], "").strip() or DEFAULT_MODELS[provider]


def allowed_models(provider: str) -> list[str]:
    return list(dict.fromkeys([default_model(provider), *MODELS[provider]]))


def default_provider() -> str:
    configured = os.getenv("LLM_PROVIDER", "").strip().lower()
    if configured in PROVIDERS:
        return configured
    if server_key("gemini"):
        return "gemini"
    if server_key("openai"):
        return "openai"
    return "gemini"


def get_llm(
    x_llm_provider: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    x_openai_key: str | None = Header(default=None),  # backwards compatible
    x_llm_model: str | None = Header(default=None),
    x_openai_model: str | None = Header(default=None),  # backwards compatible
) -> LLMClient:
    """Build a client from the caller's provider/key/model, falling back to server settings."""
    provider = (x_llm_provider or "").strip().lower() or default_provider()
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unsupported provider: {provider}")
    key = (x_api_key or x_openai_key or "").strip() or server_key(provider)
    name = "Gemini" if provider == "gemini" else "OpenAI"
    if not key:
        raise HTTPException(401, f"No {name} API key configured. Add your own key in Settings.")
    model = (x_llm_model or x_openai_model or "").strip() or default_model(provider)
    # Gemini model names change often; accept any well-formed gemini-* name.
    known = model in allowed_models(provider)
    if not known and not (provider == "gemini" and re.fullmatch(r"gemini-[a-z0-9.\-]{1,40}", model)):
        raise HTTPException(400, f"Unsupported {name} model: {model}")
    return factcheck.make_client(provider, key, model)


# ----------------------------------------------------------------------------- schemas
class ExtractRequest(BaseModel):
    pages: list[Page] = Field(min_length=1)
    max_claims: int = Field(default=25, ge=1, le=MAX_CLAIMS)


class ExtractResponse(BaseModel):
    claims: list[Claim]


class VerifyRequest(BaseModel):
    claim: Claim
    previous: ClaimResult | None = None  # set to request a second opinion


class VerifyResponse(ClaimResult):
    needs_second_opinion: bool = False


class ConsistencyRequest(BaseModel):
    claims: list[Claim]


class ConsistencyResponse(BaseModel):
    contradictions: list[Contradiction]


class CorrectRequest(BaseModel):
    claims: list[Claim]
    results: list[ClaimResult]


class CorrectResponse(BaseModel):
    corrections: list[Correction]


# ----------------------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    providers = {
        p: {"server_key": bool(server_key(p)), "default_model": default_model(p), "models": allowed_models(p)}
        for p in PROVIDERS
    }
    return {
        "ok": True,
        "default_provider": default_provider(),
        "providers": providers,
        # legacy fields
        "server_key": any(v["server_key"] for v in providers.values()),
        "default_model": providers[default_provider()]["default_model"],
        "models": providers[default_provider()]["models"],
    }


@app.post("/api/extract", response_model=ExtractResponse)
def extract(body: ExtractRequest, llm: LLMClient = Depends(get_llm)):
    pages = [p for p in body.pages if p.text.strip()][:MAX_PAGES]
    if not pages:
        raise HTTPException(422, "No selectable text found. Scanned/image-only PDFs are not supported.")
    if sum(len(p.text) for p in pages) > MAX_CHARS:
        raise HTTPException(413, f"Document too long: please upload at most ~{MAX_CHARS // 1000}k characters.")
    return ExtractResponse(claims=extract_claims(llm, pages, body.max_claims))


@app.post("/api/verify", response_model=VerifyResponse)
def verify(body: VerifyRequest, llm: LLMClient = Depends(get_llm)):
    result = verify_claim(llm, body.claim, body.previous)
    return VerifyResponse(**result.model_dump(), needs_second_opinion=result.wants_second_opinion())


@app.post("/api/consistency", response_model=ConsistencyResponse)
def consistency(body: ConsistencyRequest, llm: LLMClient = Depends(get_llm)):
    return ConsistencyResponse(contradictions=find_contradictions(llm, body.claims[:MAX_CLAIMS]))


@app.post("/api/correct", response_model=CorrectResponse)
def correct(body: CorrectRequest, llm: LLMClient = Depends(get_llm)):
    return CorrectResponse(corrections=correct_document(llm, body.claims, body.results))
