"""YOLOv8 layout detector backend — wraps phase1_dla detection logic."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any

from PIL import Image

from src.datasheet.phase1_dla.detector import (
    _crop_region,
    _detect_tables,
    _load_yolo_model,
)
from src.parsing.backends._interfaces import LayoutDetectorBackend
from src.parsing.backends._schemas import BoundingBox, DetectedRegion

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)

_CLASS_TO_REGION_TYPE: dict[int, str] = {
    3: "table",
    4: "footnote",
    2: "caption",
}


class YOLOv8LayoutDetector(LayoutDetectorBackend):
    """LayoutDetectorBackend adapter over phase1_dla YOLOv8 detection."""

    def __init__(self, config: Config) -> None:
        """Initialize detector settings without loading the model.

        Args:
            config: Application configuration with model paths and thresholds.
        """
        self._config = config
        self._confidence_min = config.parsing.layout_detector_config.confidence_min
        self._model: Any | None = None

    def detect(self, page_image: bytes, page_number: int) -> list[DetectedRegion]:
        """Detect layout regions on a rasterized page image.

        Args:
            page_image: PNG bytes of one full page at 300 DPI
            page_number: 0-indexed page number

        Returns:
            List of DetectedRegion objects. Empty list on any failure.
        """
        try:
            if self._model is None:
                self._model = _load_yolo_model(self._config)

            pil_image = Image.open(io.BytesIO(page_image))
            raw_detections = _detect_tables(
                pil_image,
                self._model,
                self._confidence_min,
            )

            regions: list[DetectedRegion] = []
            for detection in raw_detections:
                class_id = detection["class_id"]
                region_type = _CLASS_TO_REGION_TYPE.get(class_id, "unknown")
                x1, y1, x2, y2 = detection["bounding_box"]
                bbox = BoundingBox(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    page_number=page_number,
                    confidence=detection["confidence"],
                )
                crop_image = _crop_region(pil_image, detection["bounding_box"])
                regions.append(
                    DetectedRegion(
                        region_type=region_type,
                        bbox=bbox,
                        crop_image=crop_image,
                    )
                )
            return regions
        except Exception as exc:
            logger.error("YOLOv8 layout detection failed: %s", exc)
            return []
