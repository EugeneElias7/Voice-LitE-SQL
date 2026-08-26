"""Voice-LitE-SQL -- Level 3: minimal Ollama HTTP client.

Talks to the local Ollama server over its HTTP API. No model downloads are
triggered from Python -- pulling models is done manually via ``ollama pull``.

Reusable by Level 8 (execution-guided self-correction).
"""

import os

import requests

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "qwen2.5-coder:1.5b"
DEFAULT_TIMEOUT = 120  # seconds


class OllamaError(Exception):
    """Raised when Ollama is unavailable or returns an error."""


def generate(prompt, model=DEFAULT_MODEL, host=DEFAULT_HOST, timeout=DEFAULT_TIMEOUT, temperature=0.0):
    """Generate a completion for ``prompt`` via the Ollama HTTP API.

    Returns ``(text, raw_payload)`` where ``raw_payload`` is the full JSON
    object returned by Ollama.

    Raises :class:`OllamaError` when Ollama cannot be reached or returns an
    error status.
    """
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
        raise OllamaError(f"cannot reach Ollama at {host}: {exc}") from exc
    if response.status_code != 200:
        raise OllamaError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise OllamaError(f"Ollama returned invalid JSON: {exc}") from exc
    return body.get("response", ""), body
