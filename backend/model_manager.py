from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from backend.providers.ollama_provider import OllamaProvider
from backend.providers.openrouter_provider import OpenRouterProvider


class ModelManager:
    def __init__(self):
        self.provider_name = (os.environ.get("LLM_PROVIDER") or "ollama").lower()
        self.default_model = os.environ.get("OPENROUTER_MODEL") or os.environ.get("OLLAMA_MODEL") or os.environ.get("LLM_MODEL") or "qwen2.5-coder:1.5b"
        self.ollama = OllamaProvider(
            base_url=os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434",
            default_model=os.environ.get("OLLAMA_MODEL") or os.environ.get("LLM_MODEL") or "qwen2.5-coder:1.5b",
        )
        self.openrouter = OpenRouterProvider(
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url=os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
            default_model=os.environ.get("OPENROUTER_MODEL") or "deepseek/deepseek-v4-flash-0731:free",
        )

    @property
    def provider(self):
        if self.provider_name == "openrouter":
            return self.openrouter
        return self.ollama

    def get_active_model(self) -> str:
        if self.provider_name == "openrouter":
            return os.environ.get("OPENROUTER_MODEL") or self.openrouter.default_model
        return os.environ.get("OLLAMA_MODEL") or os.environ.get("LLM_MODEL") or self.ollama.default_model

    def list_models(self) -> List[Dict[str, Any]]:
        provider = self.provider
        models = provider.list_models()
        if not models:
            return []
        return models

    def is_available(self) -> bool:
        return self.provider.is_available()

    def generate(self, messages, model: Optional[str] = None, **kwargs):
        provider = self.provider
        selected_model = model or self.get_active_model()
        try:
            return provider.generate(messages, model=selected_model, **kwargs)
        except Exception:
            raise

    def select_model(self, model_id: str) -> Dict[str, Any]:
        if model_id.startswith("deepseek/") or model_id.startswith("openai/") or model_id.startswith("meta-llama/") or "/" in model_id:
            self.provider_name = "openrouter"
            os.environ["LLM_PROVIDER"] = "openrouter"
            if model_id:
                os.environ["OPENROUTER_MODEL"] = model_id
            return {"provider": "openrouter", "model": model_id}
        self.provider_name = "ollama"
        os.environ["LLM_PROVIDER"] = "ollama"
        os.environ["OLLAMA_MODEL"] = model_id
        return {"provider": "ollama", "model": model_id}


MODEL_MANAGER = ModelManager()
