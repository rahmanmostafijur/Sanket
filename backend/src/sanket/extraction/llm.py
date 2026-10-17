from google import genai

from sanket.config import settings


def _client() -> genai.Client:
    if settings.gemini_api_key is None:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=settings.gemini_api_key.get_secret_value())
