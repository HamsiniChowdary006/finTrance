import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class StructuredLLM:
    def __init__(self, cache_dir: str | Path = "store/llm_cache",
                 responder: Callable[[str, str, str | None], str] | None = None) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "none")
        self.model = os.getenv("LLM_MODEL", "")
        self.api_key = os.getenv("LLM_API_KEY")
        self.budget = int(os.getenv("LLM_BUDGET", "20"))
        self.calls = 0
        self.responder = responder
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def call(self, prompt: str, schema: type[T]) -> T:
        key = hashlib.sha256(f"{self.provider}:{self.model}:{prompt}".encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        if self.provider == "none" or self.responder is None:
            raise LLMError("LLM_PROVIDER=none; structured extraction is unavailable")
        last_error: Exception | None = None
        for _ in range(2):
            if self.calls >= self.budget:
                raise LLMError("LLM call budget exhausted")
            self.calls += 1
            try:
                result = schema.model_validate_json(self.responder(prompt, self.model, self.api_key))
                path.write_text(result.model_dump_json(), encoding="utf-8")
                return result
            except (TypeError, ValueError, ValidationError) as error:
                last_error = error
        raise LLMError(f"Structured response failed after one retry: {last_error}") from last_error


class ExtractionResponse(BaseModel):
    metric: str
    value: float
    unit: str
    period: str
    quote: str


def cache_response(cache_dir: str | Path, prompt: str, payload: BaseModel) -> Path:
    key = hashlib.sha256(prompt.encode()).hexdigest()
    path = Path(cache_dir) / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload.model_dump()), encoding="utf-8")
    return path
