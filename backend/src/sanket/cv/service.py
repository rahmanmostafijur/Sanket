"""Read a CV with the language model: text in, a proposed career profile out. Nothing is saved.

The extraction is the one used for job postings (`run_extraction`): the model's JSON is
validated against `CvExtraction` and, when it does not fit, the model is asked to correct it,
up to MAX_REPAIR_ATTEMPTS times. The answer then becomes a strict `CvProposal`. A provider error
(`LlmError`, `LlmRateLimitError`) propagates to the caller. The CV text goes only to the model: it
is not logged, and a failure is reported without it.
"""

from sanket.config import Settings
from sanket.cv.prompt import SYSTEM_PROMPT, build_cv_text
from sanket.cv.schema import CvExtraction, CvProposal, to_proposal
from sanket.extraction.extract import run_extraction
from sanket.extraction.llm import GeminiClient, LlmClient

RESPONSE_SCHEMA = CvExtraction.model_json_schema()


class CvProposalError(Exception):
    """The model did not give an answer that fits the schema, even after repairs."""


def cv_client_from_settings(config: Settings) -> LlmClient | None:
    """The Gemini client for CV requests, or None without an API key. It is not paced or
    backed off: a person is waiting, so a provider limit is reported at once."""
    if config.gemini_api_key is None:
        return None
    return GeminiClient(config.gemini_api_key, config.gemini_model)


def propose_profile(client: LlmClient, cv_text: str) -> CvProposal:
    """The career profile read from `cv_text`. Raises `CvProposalError`, or the client's
    `LlmError`."""
    result = run_extraction(
        client, build_cv_text(cv_text), SYSTEM_PROMPT, CvExtraction, RESPONSE_SCHEMA
    )
    if result.data is None:
        raise CvProposalError("the answer did not fit the profile fields")
    return to_proposal(result.data)
