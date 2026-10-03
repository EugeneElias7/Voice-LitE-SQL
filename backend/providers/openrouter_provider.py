from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from backend.providers.base import LLMProvider

DEFAULT_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731:free")
DEFAULT_ALLOWLIST = [
    "deepseek/deepseek-v4-flash-0731:free",
    "openai/gpt-4o-mini",
    "meta-llama/llama-3.1-8b-instruct",
]


def _model_label(model_id: str) -> str:
    cleaned = model_id.split(":", 1)[0].split("/")[-1].replace("-", " ").replace("_", " ")
    if not cleaned:
        return "Model"
    return cleaned.title().replace("Gpt", "GPT").replace("Llama", "Llama").replace("Deepseek", "DeepSeek")


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL, default_model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.default_model = default_model or DEFAULT_MODEL

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/voice-lite-sql",
            "X-Title": "Voice-LitE-SQL",
        }

    def _allowlisted_models(self) -> List[str]:
        configured = os.environ.get("OPENROUTER_MODELS", "")
        if configured.strip():
            return [item.strip() for item in configured.split(",") if item.strip()]
        env_default = os.environ.get("OPENROUTER_MODEL")
        if env_default:
            return [env_default]
        return DEFAULT_ALLOWLIST

    def list_models(self) -> List[Dict[str, Any]]:
        allowlist = self._allowlisted_models()
        if not self.api_key:
            return [
                {
                    "id": model,
                    "name": model.split("/")[-1].replace(":free", "").replace(":", " "),
                    "provider": "openrouter",
                    "source": "cloud",
                    "available": False,
                    "free": "free" in model.lower(),
                }
                for model in allowlist
            ]
        try:
            response = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=8)
        except requests.RequestException:
            return [
                {
                    "id": model,
                    "name": model.split("/")[-1].replace(":free", "").replace(":", " "),
                    "provider": "openrouter",
                    "source": "cloud",
                    "available": False,
                    "free": "free" in model.lower(),
                }
                for model in allowlist
            ]
        if response.status_code != 200:
            return [
                {
                    "id": model,
                    "name": model.split("/")[-1].replace(":free", "").replace(":", " "),
                    "provider": "openrouter",
                    "source": "cloud",
                    "available": False,
                    "free": "free" in model.lower(),
                }
                for model in allowlist
            ]
        try:
            payload = response.json() or {}
        except ValueError:
            payload = {}
        available_ids = {entry.get("id") for entry in payload.get("data", []) if isinstance(entry, dict) and entry.get("id")}
        models: List[Dict[str, Any]] = []
        for model in allowlist:
            if model in available_ids or not available_ids:
                available = True
            else:
                available = False
            models.append({
                "id": model,
                "name": _model_label(model),
                "provider": "openrouter",
                "source": "cloud",
                "available": available,
                "free": "free" in model.lower(),
            })
        return models

    def is_available(self) -> bool:
        return bool(self.api_key) and any(model.get("available") for model in self.list_models())

    def generate(self, messages, model: Optional[str] = None, **kwargs):
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        model_name = model or self.default_model
        timeout = kwargs.get("timeout", 30)
        temperature = kwargs.get("temperature", 0.0)
        payload = {
            "model": model_name,
            "messages": messages if isinstance(messages, list) else [{"role": "user", "content": str(messages)}],
            "temperature": temperature,
            "stream": False,
        }
        try:
            response = requests.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers(), timeout=timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
        if response.status_code != 200:
            raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(f"OpenRouter returned invalid JSON: {exc}") from exc
        choice = (body.get("choices") or [{}])[0]
        text = choice.get("message", {}).get("content", "")
        return {
            "content": text,
            "raw": body,
            "provider": "openrouter",
            "model": model_name,
        }
