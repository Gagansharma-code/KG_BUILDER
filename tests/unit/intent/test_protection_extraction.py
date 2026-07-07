"""Gate tests for protection_requirements LLM extraction (schema review §4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.completion.engine import CompletionEngineError
from src.intent.parser import TypedConstraintExtraction, _sanitize_protection_requirements, parse_intent
from src.schemas.intent import ProtectionRequirement

MODULE = "src.intent.parser"


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.model_paths = {"qwen25_7b": "/tmp/mock_model"}
    return config


def _entry004_prompt2_extraction() -> TypedConstraintExtraction:
    return TypedConstraintExtraction(
        protection_requirements=[
            ProtectionRequirement(
                kind="reverse_current",
                raw_text="reverse-current protection",
            ),
            ProtectionRequirement(
                kind="kelvin_sensing",
                raw_text="Kelvin sensing",
            ),
        ],
    )


class TestProtectionLLMExtraction:
    def test_llm_extraction_populates_protection_requirements(self, mock_config):
        prompt = (
            "Design a precision constant-current source with reverse-current "
            "protection and Kelvin sensing on the sense resistor."
        )
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.return_value = _entry004_prompt2_extraction()
            intent = parse_intent(prompt, mock_config)

        kinds = {req.kind for req in intent.protection_requirements}
        assert kinds == {"reverse_current", "kelvin_sensing"}
        raw_texts = {req.raw_text for req in intent.protection_requirements}
        assert "reverse-current protection" in raw_texts
        assert "Kelvin sensing" in raw_texts

    def test_malformed_protection_entry_does_not_raise(
        self, mock_config, caplog
    ):
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.return_value = TypedConstraintExtraction(
                protection_requirements=[
                    ProtectionRequirement(
                        kind="esd",
                        raw_text="ESD protection",
                    ),
                    {"kind": "esd"},  # type: ignore[list-item]
                ],
            )
            with caplog.at_level("WARNING"):
                sanitized = _sanitize_protection_requirements(
                    [
                        ProtectionRequirement(kind="esd", raw_text="ok"),
                        {"kind": "esd"},
                    ]
                )

        assert len(sanitized) == 1
        assert "Dropping malformed protection requirement" in caplog.text

        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.side_effect = CompletionEngineError("validation failed")
            intent = parse_intent("design with ESD protection", mock_config)

        assert intent.protection_requirements == []
