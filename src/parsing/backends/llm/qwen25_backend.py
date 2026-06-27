"""Qwen2.5-7B LLM extraction backend."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from pydantic import create_model

from src.parsing.backends._interfaces import LLMBackend
from src.parsing.backends._schemas import LLMResponse

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)


class Qwen25LLMBackend(LLMBackend):
    """Wraps Phase 3 InstructorWrapper for the pluggable parsing API."""

    def __init__(self, config: Config) -> None:
        llm_config = config.parsing.llm_config
        self._config = config
        self._model_key = llm_config.model_key
        self._device = llm_config.device
        self._max_tokens = llm_config.max_tokens
        self._instructor_wrapper = None

    def _empty_response(self) -> LLMResponse:
        return LLMResponse(
            raw_text="",
            parsed_json=None,
            confidence=0.0,
            backend_used="qwen25_7b",
        )

    def extract(
        self, text: str, system_prompt: str, output_schema: dict[str, Any]
    ) -> LLMResponse:
        """Extract structured data from text via Qwen2.5 + Instructor."""
        try:
            if self._instructor_wrapper is None:
                from src.datasheet.phase3_extract.extractor import InstructorWrapper

                model_path = self._config.get_model_path(self._model_key)
                self._instructor_wrapper = InstructorWrapper(
                    model_path=model_path,
                    device=self._device,
                )

            dynamic_model = create_model(
                "DynamicExtractionModel",
                **{
                    field_name: (Optional[str], None)
                    for field_name in output_schema.get("properties", {}).keys()
                },
            )

            result = self._instructor_wrapper.extract(
                response_model=dynamic_model,
                system_prompt=system_prompt,
                user_content=text,
            )

            if result is None:
                return self._empty_response()

            return LLMResponse(
                raw_text=str(result),
                parsed_json=result.model_dump(exclude_none=True),
                confidence=0.85,
                backend_used="qwen25_7b",
            )
        except Exception as exc:
            logger.error("Qwen25LLMBackend.extract failed: %s", exc)
            return self._empty_response()
