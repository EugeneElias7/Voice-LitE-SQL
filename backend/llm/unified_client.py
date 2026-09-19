"""Voice-LitE-SQL -- Unified LLM Client.

Supports multiple providers:
- Ollama (local)
- OpenAI API
- Anthropic API
- OpenRouter API (unified access to many models)

Uses environment variables for configuration.
"""

import os
import requests
from typing import Optional, Tuple


class LLMError(Exception):
    """Raised when LLM provider is unavailable or returns an error."""


class LLMProvider:
    """Supported LLM providers."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"


# Default configurations
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:1.5b")
DEFAULT_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))

# Provider-specific defaults
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


def generate(prompt: str,
             model: Optional[str] = None,
             provider: Optional[str] = None,
             timeout: Optional[int] = None,
             temperature: float = 0.0) -> Tuple[str, dict]:
    """Generate a completion using the configured provider.

    Returns (response_text, raw_payload).

    Raises LLMError on failure.
    """
    provider = (provider or DEFAULT_PROVIDER).lower()
    model = model or DEFAULT_MODEL
    timeout = timeout or DEFAULT_TIMEOUT

    if provider == LLMProvider.OLLAMA:
        return _generate_ollama(prompt, model, timeout, temperature)
    elif provider == LLMProvider.OPENAI:
        return _generate_openai(prompt, model, timeout, temperature)
    elif provider == LLMProvider.ANTHROPIC:
        return _generate_anthropic(prompt, model, timeout, temperature)
    elif provider == LLMProvider.OPENROUTER:
        return _generate_openrouter(prompt, model, timeout, temperature)
    else:
        raise LLMError(f"Unknown provider: {provider}")


def _generate_ollama(prompt: str, model: str, timeout: int, temperature: float) -> Tuple[str, dict]:
    host = OLLAMA_HOST
    url = host.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise LLMError(f"Cannot reach Ollama at {host}: {exc}") from exc
    if response.status_code != 200:
        raise LLMError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError(f"Ollama returned invalid JSON: {exc}") from exc
    return body.get("response", ""), body


def _generate_openai(prompt: str, model: str, timeout: int, temperature: float) -> Tuple[str, dict]:
    if not OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY not set")
    url = OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "stream": False,
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise LLMError(f"Cannot reach OpenAI: {exc}") from exc
    if response.status_code != 200:
        raise LLMError(f"OpenAI HTTP {response.status_code}: {response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError(f"OpenAI returned invalid JSON: {exc}") from exc
    text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    return text, body


def _generate_anthropic(prompt: str, model: str, timeout: int, temperature: float) -> Tuple[str, dict]:
    if not ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY not set")
    url = ANTHROPIC_BASE_URL.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise LLMError(f"Cannot reach Anthropic: {exc}") from exc
    if response.status_code != 200:
        raise LLMError(f"Anthropic HTTP {response.status_code}: {response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError(f"Anthropic returned invalid JSON: {exc}") from exc
    text = "".join(block.get("text", "") for block in body.get("content", []))
    return text, body


def _generate_openrouter(prompt: str, model: str, timeout: int, temperature: float) -> Tuple[str, dict]:
    if not OPENROUTER_API_KEY:
        raise LLMError("OPENROUTER_API_KEY not set")
    url = OPENROUTER_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/voice-lite-sql",
        "X-Title": "Voice-LitE-SQL",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise LLMError(f"Cannot reach OpenRouter: {exc}") from exc
    if response.status_code != 200:
        raise LLMError(f"OpenRouter HTTP {response.status_code}: {response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError(f"OpenRouter returned invalid JSON: {exc}") from exc
    text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    return text, body


def probe_llm(model: Optional[str] = None, provider: Optional[str] = None, timeout: int = 30) -> bool:
    """Quick health check for the configured provider."""
    try:
        generate("Reply with exactly: OK", model=model, provider=provider, timeout=timeout)
        return True
    except LLMError:
        return False