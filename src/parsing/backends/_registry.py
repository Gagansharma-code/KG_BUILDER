"""Backend registry with lazy import and instance caching."""

from __future__ import annotations

import importlib
import inspect
from typing import TYPE_CHECKING, Any

from src.parsing.backends._interfaces import (
    ImageTableBackend,
    LayoutDetectorBackend,
    LLMBackend,
    VectorTableBackend,
    VLMBackend,
)
from src.parsing.backends._schemas import ParsingConfig

if TYPE_CHECKING:
    from src.config import Config

LAYOUT_DETECTOR_REGISTRY: dict[str, str] = {
    "yolov8": "src.parsing.backends.layout.yolov8_backend.YOLOv8LayoutDetector",
    "surya": "src.parsing.backends.layout.surya_backend.SuryaLayoutDetector",
}

VECTOR_TABLE_REGISTRY: dict[str, str] = {
    "pdfplumber_camelot": (
        "src.parsing.backends.vector_table.pdfplumber_camelot_backend."
        "PdfplumberCamelotVectorTableBackend"
    ),
}

IMAGE_TABLE_REGISTRY: dict[str, str] = {
    "paddleocr": (
        "src.parsing.backends.image_table.paddleocr_backend."
        "PaddleOCRImageTableBackend"
    ),
    "qwen2_vl": (
        "src.parsing.backends.image_table.qwen2_vl_backend."
        "Qwen2VLImageTableBackend"
    ),
}

VLM_REGISTRY: dict[str, str] = {
    "qwen2_vl": "src.parsing.backends.vlm.qwen2_vl_backend.Qwen2VLBackend",
}

LLM_REGISTRY: dict[str, str] = {
    "qwen25_7b": "src.parsing.backends.llm.qwen25_backend.Qwen25LLMBackend",
}


def _load_class(dotted_path: str) -> type:
    """Load a backend class from a fully-qualified module path.

    Args:
        dotted_path: e.g. "src.parsing.backends.layout.yolov8_backend.YOLOv8LayoutDetector"

    Returns:
        The backend class object.

    Raises:
        ImportError: If the module or class cannot be loaded.
    """
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls: type = getattr(module, class_name)
    return cls


def _validate_backend_name(
    config_key: str,
    backend_name: str,
    registry: dict[str, str],
) -> None:
    """Raise ValueError if backend_name is not in registry."""
    if backend_name not in registry:
        valid = ", ".join(sorted(registry.keys()))
        raise ValueError(
            f"Unknown parsing.{config_key} backend '{backend_name}'. "
            f"Valid options: {valid}"
        )


def _instantiate_backend(cls: type, config: Config) -> Any:
    """Instantiate a backend class, passing config when required."""
    try:
        init = cls.__init__  # type: ignore[misc]
        params = inspect.signature(init).parameters
    except (TypeError, ValueError):
        return cls(config)
    if "config" in params:
        return cls(config)
    return cls()


class BackendRegistry:
    """Lazy-loading registry for parsing pipeline backends.

    Validates backend names from config at construction time.
    Instantiates backends on first getter call and caches instances.
    """

    def __init__(self, config: Config) -> None:
        """Initialize registry from application config.

        Args:
            config: Application config with parsing backend name selections.

        Raises:
            ValueError: If any configured backend name is unknown.
        """
        parsing: ParsingConfig = config.parsing
        _validate_backend_name(
            "layout_detector", parsing.layout_detector, LAYOUT_DETECTOR_REGISTRY
        )
        _validate_backend_name(
            "vector_table", parsing.vector_table, VECTOR_TABLE_REGISTRY
        )
        _validate_backend_name(
            "image_table", parsing.image_table, IMAGE_TABLE_REGISTRY
        )
        _validate_backend_name("vlm", parsing.vlm, VLM_REGISTRY)
        _validate_backend_name("llm", parsing.llm, LLM_REGISTRY)

        self._parsing = parsing
        self._config = config
        self._layout_detector: LayoutDetectorBackend | None = None
        self._vector_table: VectorTableBackend | None = None
        self._image_table: ImageTableBackend | None = None
        self._vlm: VLMBackend | None = None
        self._llm: LLMBackend | None = None

    def get_layout_detector(self) -> LayoutDetectorBackend:
        """Return the configured layout detector backend (cached)."""
        if self._layout_detector is not None:
            return self._layout_detector
        dotted_path = LAYOUT_DETECTOR_REGISTRY[self._parsing.layout_detector]
        cls = _load_class(dotted_path)
        self._layout_detector = _instantiate_backend(cls, self._config)
        return self._layout_detector

    def get_vector_table(self) -> VectorTableBackend:
        """Return the configured vector table backend (cached)."""
        if self._vector_table is not None:
            return self._vector_table
        dotted_path = VECTOR_TABLE_REGISTRY[self._parsing.vector_table]
        cls = _load_class(dotted_path)
        self._vector_table = _instantiate_backend(cls, self._config)
        return self._vector_table

    def get_image_table(self) -> ImageTableBackend:
        """Return the configured image table backend (cached)."""
        if self._image_table is not None:
            return self._image_table
        dotted_path = IMAGE_TABLE_REGISTRY[self._parsing.image_table]
        cls = _load_class(dotted_path)
        self._image_table = _instantiate_backend(cls, self._config)
        return self._image_table

    def get_vlm(self) -> VLMBackend:
        """Return the configured VLM backend (cached)."""
        if self._vlm is not None:
            return self._vlm
        dotted_path = VLM_REGISTRY[self._parsing.vlm]
        cls = _load_class(dotted_path)
        self._vlm = _instantiate_backend(cls, self._config)
        return self._vlm

    def get_llm(self) -> LLMBackend:
        """Return the configured LLM backend (cached)."""
        if self._llm is not None:
            return self._llm
        dotted_path = LLM_REGISTRY[self._parsing.llm]
        cls = _load_class(dotted_path)
        self._llm = _instantiate_backend(cls, self._config)
        return self._llm
