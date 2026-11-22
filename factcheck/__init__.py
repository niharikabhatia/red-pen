"""Fact-Check Agent: extract claims from a document and verify them against the live web."""

from .claims import extract_claims
from .llm import DEFAULT_MODELS, MODELS, PROVIDERS, LLMClient, LLMError, make_client
from .models import Claim, ClaimResult, Contradiction, Correction, Page, Source, Verdict
from .review import correct_document, find_contradictions
from .verifier import verify_claim

__all__ = [
    "DEFAULT_MODELS", "MODELS", "PROVIDERS", "make_client", "Claim", "ClaimResult", "Contradiction", "Correction", "LLMClient", "LLMError", "Page",
    "Source", "Verdict", "correct_document", "extract_claims", "find_contradictions", "verify_claim",
]
