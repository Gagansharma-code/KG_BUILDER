"""Test-only stubs for optional heavy native deps (Phase 0 impact runs)."""
from __future__ import annotations

import sys
import types
from typing import Any


def _ensure(name: str) -> types.ModuleType:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


_ul = _ensure("ultralytics")
_ul.YOLO = type("YOLO", (), {"__init__": lambda self, *a, **k: None})

_pdf2image = _ensure("pdf2image")
_pdf2image.convert_from_path = lambda *a, **k: []

_camelot = _ensure("camelot")
_camelot.read_pdf = lambda *a, **k: []

_cv2 = _ensure("cv2")

_torch = _ensure("torch")
_torchvision = _ensure("torchvision")
_spacy = _ensure("spacy")
_transformers = _ensure("transformers")

# Avoid unused warnings under some linters
_: Any = (_torch, _torchvision, _spacy, _transformers, _cv2)
