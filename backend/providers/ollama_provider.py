from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from backend.providers.base import LLMProvider

DEFAULT_HOST = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL") or os.environ.get("LLM_MODEL", "qwen2.5-coder:1.5b")


def _humanize_model_name(model_name: str) -> str:
    if not model_name:
        return "Model"
    cleaned = model_name.split(":", 1)[0].split("/")[-1].replace("-", " ").replace("_", " ")
    return cleaned.title().replace("Qwen", "Qwen").replace("Llama", "Llama")


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str = DEFAULT_HOST, default_model: str = DEFAULT_MODEL, timeout: int = 5):
        self.base_url = (base_url or DEFAULT_HOST).rstrip("/")
        self.default_model = default_model or DEFAULT_MODEL
        self.timeout = timeout

    def _request(self, path: str, **kwargs):
        try:
            return requests.get(f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network safety
            raise RuntimeError(f"Local Ollama is not running: {exc}") from exc

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            response = self._request("/api/tags")
        except RuntimeError:
            return []
        if response.status_code != 200:
            return []
        try:
            payload = response.json() or {}
        except ValueError:
            return []
        records: List[Dict[str, Any]] = []
        for model in payload.get("models", []):
            model_name = (model.get("name") or "").strip()
            if not model_name:
                continue
            records.append({
                "id": model_name,
                "name": _humanize_model_name(model_name),
                "provider": "ollama",
                "source": "local",
                "available": True,
                "free": True,
            })
        return records

    def is_available(self) -> bool:
        return bool(self.list_models())

    def generate(self, messages, model: Optional[str] = None, **kwargs):
        model_name = model or self.default_model
        timeout = kwargs.get("timeout", 30)
        temperature = kwargs.get("temperature", 0.0)
        if isinstance(messages, str):
            prompt = messages
        else:
            prompt = "\n".join(
                f"{entry.get('role', 'user')}: {entry.get('content', '')}"
                for entry in messages if isinstance(entry, dict)
            )
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"Local Ollama is not running: {exc}") from exc
        if response.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Ollama returned invalid JSON: {exc}") from exc
        return {
            "content": body.get("response", ""),
            "raw": body,
            "provider": "ollama",
            "model": model_name,
        }
