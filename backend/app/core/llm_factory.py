"""LLM Factory — centralised model creation.

Supported providers (set LLM_PROVIDER in .env):
  openai    — ChatOpenAI       (requires OPENAI_API_KEY)
  gemini    — ChatGoogleGenerativeAI (requires GEMINI_API_KEY)
  ollama    — ChatOllama       (no key — local Ollama server)
  anthropic — ChatAnthropic    (requires ANTHROPIC_API_KEY)

Default models per provider (used when LLM_MODEL is empty):
  openai    → gpt-4o-mini
  gemini    → gemini-1.5-flash
  ollama    → llama3
  anthropic → claude-3-haiku-20240307

To switch providers you only need to update .env:
  LLM_PROVIDER=gemini
  GEMINI_API_KEY=<your-key>
  # LLM_MODEL=gemini-1.5-pro   # optional override
"""

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_PROVIDER_DEFAULTS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "ollama": "llama3",
    "anthropic": "claude-3-haiku-20240307",
}


def get_llm(temperature: float = 0):
    """Return a configured LangChain chat model for the current provider."""
    provider = (settings.llm_provider or "openai").lower()
    model = settings.llm_model or _PROVIDER_DEFAULTS.get(provider, "gpt-4o-mini")

    logger.debug("Creating LLM", extra={"provider": provider, "model": model})

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            temperature=temperature,
        )

    if provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError(
                "langchain-google-genai is not installed. "
                "Run: pip install langchain-google-genai"
            )
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.gemini_api_key,
            temperature=temperature,
        )

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama is not installed. "
                "Run: pip install langchain-ollama"
            )
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain-anthropic is not installed. "
                "Run: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            temperature=temperature,
        )

    # Unknown provider — fall back to OpenAI
    logger.warning("Unknown LLM_PROVIDER '%s', falling back to OpenAI", provider)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=temperature,
    )


def is_llm_configured() -> bool:
    """Return True if the selected provider has the required credentials."""
    provider = (settings.llm_provider or "openai").lower()
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "gemini":
        return bool(settings.gemini_api_key)
    if provider == "ollama":
        return True  # local — no key needed
    if provider == "anthropic":
        return bool(settings.anthropic_api_key)
    return bool(settings.openai_api_key)
