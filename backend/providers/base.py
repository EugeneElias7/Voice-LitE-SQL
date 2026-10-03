from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional


class ModelRecord(dict):
    """Normalized model metadata returned by providers."""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def list_models(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def generate(self, messages, model: Optional[str] = None, **kwargs):
        raise NotImplementedError
