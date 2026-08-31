"""
Shared OpenAI client setup for Azure OpenAI and Azure AI Foundry.

Supports:
- Classic Azure OpenAI via AzureOpenAI (resource root + api-version)
- Azure AI Foundry /openai/v1 via OpenAI(base_url=...)
- Standard OpenAI API
"""

from typing import Any, Dict, List, Tuple

from django.conf import settings
from openai import AzureOpenAI, OpenAI


def _is_foundry_style_endpoint(endpoint: str) -> bool:
    """Detect Foundry / OpenAI-compatible v1 endpoints."""
    lower = (endpoint or "").lower().rstrip("/")
    return (
        "/openai/v1" in lower
        or "/api/projects/" in lower
        or "services.ai.azure.com" in lower
    )


def normalize_foundry_base_url(endpoint: str) -> str:
    """Ensure Foundry base_url ends with /openai/v1/."""
    endpoint = (endpoint or "").rstrip("/")
    if endpoint.endswith("/openai/v1"):
        return endpoint + "/"
    return endpoint + "/openai/v1/"


def is_reasoning_model(model: str) -> bool:
    """gpt-5 / o-series models reject some classic chat params."""
    name = (model or "").lower()
    return any(token in name for token in ("gpt-5", "o1", "o3", "o4"))


def create_chat_client() -> Tuple[Any, str, str]:
    """
    Create a chat client from Django settings.

    Returns:
        (client, model_name, mode) where mode is one of:
        'foundry_v1', 'azure_openai', 'openai'
    """
    if not settings.USE_AZURE_OPENAI:
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in settings or environment")
        return OpenAI(api_key=api_key), settings.OPENAI_MODEL, "openai"

    api_key = settings.AZURE_OPENAI_API_KEY
    endpoint = (settings.AZURE_OPENAI_ENDPOINT or "").strip()
    deployment = settings.AZURE_OPENAI_DEPLOYMENT
    api_version = settings.AZURE_OPENAI_API_VERSION

    if not api_key or not endpoint:
        raise ValueError(
            "AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set in settings or environment"
        )

    if _is_foundry_style_endpoint(endpoint):
        base_url = normalize_foundry_base_url(endpoint)
        client = OpenAI(api_key=api_key, base_url=base_url)
        return client, deployment, "foundry_v1"

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )
    return client, deployment, "azure_openai"


def build_chat_completion_kwargs(
    model: str,
    messages: List[Dict[str, str]],
    *,
    max_tokens: int,
    timeout: int,
    temperature: float = 0.1,
) -> Dict[str, Any]:
    """Build chat.completions.create kwargs compatible with gpt-4 and gpt-5.""" 
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "timeout": timeout,
        "response_format": {"type": "json_object"},
    }

    if is_reasoning_model(model):
        # Reasoning models typically reject temperature and max_tokens.
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["temperature"] = temperature
        kwargs["max_tokens"] = max_tokens

    return kwargs
