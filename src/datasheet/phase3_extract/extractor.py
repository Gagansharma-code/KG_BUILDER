"""LLM-based semantic extraction using Instructor + Qwen2.5-7B.

Extracts structured Pydantic objects from table grids using local LLM inference.
Uses Instructor library for schema adherence and validation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, TypeVar

from pydantic import BaseModel

from src.datasheet.phase1_dla._schemas import FootnoteMap
from src.datasheet.phase2_tsr._schemas import GridMatrix
from src.datasheet.phase3_extract.prompt_templates import get_prompt_for_table
from src.schemas.datasheet import (
    AbsoluteMaxRating,
    ElectricalParameter,
    ExtractionMethod,
    ExtractedValue,
    PinDefinition,
    TableSectionType,
)

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class InstructorWrapper:
    """Local structured-extraction wrapper for a Qwen2.5-Instruct model.

    Despite the name, this does not use the `instructor` package — that
    library targets OpenAI-compatible chat-completion clients, and this
    class loads a model directly via `transformers` in-process rather than
    running a server. Instead, .extract() does the same thing `instructor`
    does under the hood: prompt for JSON matching the target Pydantic
    model's schema, parse the response, and retry with the validation
    error fed back into the prompt if it doesn't validate. The name is kept
    for backward compatibility with existing callers/imports.
    """

    def __init__(self, model_path: Path, device: str = "cpu") -> None:
        """Initialize the wrapper for a Qwen2.5 model.

        Args:
            model_path: Path to a local Qwen2.5-Instruct model directory
            device: Device to run on (cpu, cuda, etc.)
        """
        self.model_path = model_path
        self.device = device
        self._model: Any | None = None
        self._tokenizer: Any | None = None

    def _load_model(self) -> None:
        """Lazy load model on first use. Cached on self._model/_tokenizer —
        every .extract() call reuses the already-loaded weights instead of
        reloading them from disk."""
        if self._model is not None and self._tokenizer is not None:
            return

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info(f"Loading Qwen2.5 model from {self.model_path}")

            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                device_map=self.device if self.device != "cpu" else None,
                torch_dtype="auto",
                trust_remote_code=True,
            )
            # from_pretrained() does not set eval mode itself — without this,
            # any dropout layers in the checkpoint stay active and inject
            # small randomness into generation even with greedy decoding.
            self._model.eval()

        except Exception as e:
            logger.error(f"Failed to load Qwen2.5 model: {e}")
            raise RuntimeError(f"Could not load LLM from {self.model_path}: {e}") from e

    def _generate(
        self,
        system_prompt: str,
        user_content: str,
        max_new_tokens: int,
        temperature: float = 0.0,
    ) -> str:
        """Run one generation pass and return the model's raw text reply.

        temperature <= 0 keeps greedy decoding (do_sample=False), matching the
        historical default used by datasheet extraction and qwen25_backend.
        temperature > 0 enables sampling so callers like the Idea 2
        self-improvement loop can diversify retries across rounds.
        """
        import torch

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            prompt_text = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
        except Exception:
            # Fallback for a tokenizer without a chat template configured.
            prompt_text = f"{system_prompt}\n\n{user_content}\n\nResponse:"

        inputs = self._tokenizer(prompt_text, return_tensors="pt")
        if self.device != "cpu":
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "pad_token_id": self._tokenizer.eos_token_id,
        }
        if temperature > 0.0:
            generate_kwargs["do_sample"] = True
            generate_kwargs["temperature"] = temperature
        else:
            generate_kwargs["do_sample"] = False

        with torch.no_grad():
            output_ids = self._model.generate(**inputs, **generate_kwargs)

        generated = output_ids[0][inputs["input_ids"].shape[-1]:]
        return str(self._tokenizer.decode(generated, skip_special_tokens=True))

    @staticmethod
    def _extract_json_object(text: str) -> Optional[str]:
        """Pull the first complete top-level {...} object out of a raw
        model reply, using brace-depth matching rather than a naive
        first-'{'/last-'}' search. Small models routinely keep generating
        after a valid JSON object closes — repeating themselves, adding
        commentary, echoing the schema again — and grabbing the last '}'
        anywhere in the text would swallow that trailing content into the
        parsed string and fail validation even though a valid object was
        actually produced. Tracks quoted-string state so braces inside
        string values (net names, etc.) don't throw off the depth count."""
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def extract(
        self,
        response_model: type[T],
        system_prompt: str,
        user_content: str,
        max_retries: int = 2,
        max_new_tokens: int = 512,
        temperature: float = 0.0,
    ) -> Optional[T]:
        """Extract structured data matching response_model from the model.

        Prompts for JSON conforming to response_model's schema, parses the
        reply, and validates it against the schema. On a parse or
        validation failure, retries up to max_retries times with the
        specific error fed back into the prompt (the same "tell it what
        went wrong and ask again" pattern the `instructor` package uses).

        Args:
            response_model: Pydantic model class to extract
            system_prompt: System prompt for the model
            user_content: User content (table text, component list, etc.)
            max_retries: Extra attempts after the first, on parse/validation failure
            max_new_tokens: Generation length cap per attempt
            temperature: Sampling temperature forwarded to _generate().
                <= 0 keeps greedy decoding (default, preserves datasheet /
                qwen25 behaviour). > 0 enables sampling for callers that
                need diversity (Idea 2 self-improvement rounds).

        Returns:
            Extracted model instance, or None if every attempt fails.
            Never raises — model load failures, generation errors, and
            parse/validation failures all fall through to None.
        """
        try:
            self._load_model()
        except Exception as exc:
            logger.error(f"InstructorWrapper.extract: model load failed: {exc}")
            return None

        schema_instructions = (
            "\n\nRespond with a single JSON object only — no prose, no "
            "markdown code fences, no explanation. The JSON must conform "
            f"to this schema:\n{json.dumps(response_model.model_json_schema())}"
        )
        full_system_prompt = system_prompt + schema_instructions

        feedback: Optional[str] = None
        for attempt in range(max_retries + 1):
            user_turn = user_content
            if feedback:
                user_turn += (
                    f"\n\nYour previous response was invalid: {feedback}\n"
                    "Respond again with corrected JSON only."
                )

            try:
                raw_text = self._generate(
                    full_system_prompt,
                    user_turn,
                    max_new_tokens,
                    temperature=temperature,
                )
            except Exception as exc:
                logger.error(f"InstructorWrapper.extract: generation failed: {exc}")
                return None

            json_str = self._extract_json_object(raw_text)
            if json_str is None:
                feedback = "No JSON object found in your response."
                logger.warning(
                    f"InstructorWrapper.extract: attempt {attempt} produced no "
                    "parseable JSON."
                )
                continue

            try:
                return response_model.model_validate_json(json_str)
            except Exception as exc:
                feedback = str(exc)
                logger.warning(
                    f"InstructorWrapper.extract: attempt {attempt} failed schema "
                    f"validation: {exc}"
                )
                continue

        logger.warning(
            f"InstructorWrapper.extract: giving up after {max_retries + 1} attempts."
        )
        return None


class ExtractionResult:
    """Result of semantic extraction from a single table."""

    def __init__(
        self,
        electrical_params: list[ElectricalParameter],
        absolute_max_ratings: list[AbsoluteMaxRating],
        pins: list[PinDefinition],
        section_type: TableSectionType,
        extraction_method: ExtractionMethod,
        confidence: float,
        review_flags: list[str],
    ):
        self.electrical_params = electrical_params
        self.absolute_max_ratings = absolute_max_ratings
        self.pins = pins
        self.section_type = section_type
        self.extraction_method = extraction_method
        self.confidence = confidence
        self.review_flags = review_flags


def _grid_to_text(grid: GridMatrix) -> str:
    """Convert GridMatrix to text representation for LLM.

    Args:
        grid: Input grid matrix

    Returns:
        Text representation suitable for LLM prompt
    """
    lines = []

    # Reconstruct table from cells
    for row_idx in range(grid.num_rows):
        row_cells = sorted(
            [c for c in grid.cells if c.row == row_idx],
            key=lambda c: c.col,
        )
        row_text = " | ".join(c.text for c in row_cells)
        lines.append(row_text)

    return "\n".join(lines)


def _inject_footnotes(
    params: list[ElectricalParameter],
    footnote_maps: list[FootnoteMap],
) -> list[ElectricalParameter]:
    """Inject footnote text into ExtractedValue objects.

    Rule 4: For each extracted ExtractedValue, check if raw_text contains
    a superscript marker and inject matched footnote text.

    Args:
        params: List of ElectricalParameter with ExtractedValue
        footnote_maps: List of FootnoteMap from Phase 2

    Returns:
        Parameters with footnotes injected
    """
    import re

    # Build lookup from all footnote maps
    footnote_lookup: dict[str, str] = {}
    for fm in footnote_maps:
        for marker, text in fm.entries.items():
            footnote_lookup[marker] = text

    if not footnote_lookup:
        return params

    result = []
    for param in params:
        if param.value and param.value.raw_text:
            raw = param.value.raw_text

            # Check for superscript markers: (1), (2), *, etc.
            markers = re.findall(r'\((\d+)\)|([\*\†\‡])', raw)

            if markers:
                # Flatten tuple results from regex
                flat_markers = []
                for m in markers:
                    flat_markers.extend([x for x in m if x])

                # Look up footnote text
                for marker in flat_markers:
                    if marker in footnote_lookup:
                        # Inject footnote
                        updated_value = param.value.model_copy(
                            update={"footnote": footnote_lookup[marker]}
                        )
                        param = param.model_copy(update={"value": updated_value})
                        break

        result.append(param)

    return result


def extract_from_grid(
    grid: GridMatrix,
    footnote_maps: list[FootnoteMap],
    config: Config,
) -> ExtractionResult:
    """Extract semantic data from a single table grid.

    Uses Instructor + Qwen2.5 to extract structured Pydantic objects
    from table text.

    Args:
        grid: GridMatrix from Phase 2
        footnote_maps: Footnote maps for footnote injection
        config: Application configuration

    Returns:
        ExtractionResult with extracted parameters
    """
    section_type = grid.section_type

    # Get appropriate prompt for this section type
    system_prompt = get_prompt_for_table(section_type)

    # Convert grid to text
    table_text = _grid_to_text(grid)

    # Determine extraction method
    extraction_method = (
        ExtractionMethod.P1_VLM
        if grid.extraction_path == "vlm"
        else ExtractionMethod.P1_VECTOR
    )

    # Placeholder extraction - in production this would call Instructor
    logger.info(f"Extracting from {section_type.value} table with {grid.num_rows}x{grid.num_cols} cells")

    # For now, return empty result with review flag
    return ExtractionResult(
        electrical_params=[],
        absolute_max_ratings=[],
        pins=[],
        section_type=section_type,
        extraction_method=extraction_method,
        confidence=grid.confidence * 0.9,  # Slightly reduce confidence
        review_flags=["LLM extraction not fully implemented"],
    )


def extract_from_grids(
    grids: list[GridMatrix],
    footnote_maps: list[FootnoteMap],
    config: Config,
) -> ExtractionResult:
    """Extract semantic data from all grids.

    Aggregates extractions from multiple tables and combines review flags.

    Args:
        grids: List of GridMatrix from Phase 2
        footnote_maps: Footnote maps for injection
        config: Application configuration

    Returns:
        Combined ExtractionResult from all grids
    """
    all_electrical = []
    all_absolute_max = []
    all_pins = []
    all_review_flags = []

    for grid in grids:
        result = extract_from_grid(grid, footnote_maps, config)

        all_electrical.extend(result.electrical_params)
        all_absolute_max.extend(result.absolute_max_ratings)
        all_pins.extend(result.pins)
        all_review_flags.extend(result.review_flags)

    # Calculate aggregate confidence
    if grids:
        mean_confidence = sum(g.confidence for g in grids) / len(grids)
    else:
        mean_confidence = 0.0

    # Determine dominant section type
    section_types = [g.section_type for g in grids]
    if section_types:
        # Use first non-OTHER section type, or OTHER if all are OTHER
        dominant = next(
            (s for s in section_types if s != TableSectionType.OTHER),
            TableSectionType.OTHER,
        )
    else:
        dominant = TableSectionType.OTHER

    # Determine extraction method
    vlm_used = any(g.extraction_path == "vlm" for g in grids)
    method = ExtractionMethod.P1_VLM if vlm_used else ExtractionMethod.P1_VECTOR

    return ExtractionResult(
        electrical_params=all_electrical,
        absolute_max_ratings=all_absolute_max,
        pins=all_pins,
        section_type=dominant,
        extraction_method=method,
        confidence=mean_confidence,
        review_flags=all_review_flags,
    )