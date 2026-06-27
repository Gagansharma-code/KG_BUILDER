"""PaddleOCR PPStructure image table extraction backend."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.parsing.backends._interfaces import ImageTableBackend
from src.parsing.backends._schemas import GridMatrix
from src.parsing.backends.image_table._html_to_grid import parse_html_to_grid

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)


class PaddleOCRImageTableBackend(ImageTableBackend):
    """Extract table structure from cropped images via PaddleOCR PPStructure."""

    def __init__(self, config: Config) -> None:
        """Initialize backend settings without loading PPStructure.

        Args:
            config: Application configuration with image table settings.
        """
        self._lang = config.parsing.image_table_config.lang
        self._use_gpu = config.parsing.image_table_config.use_gpu
        self._engine: Any | None = None

    def _empty_grid(self) -> GridMatrix:
        return GridMatrix(
            cells=[],
            confidence=0.0,
            backend_used="paddleocr",
            extraction_method="image",
        )

    def extract(self, crop_image: bytes) -> GridMatrix:
        """Extract table grid from a cropped table image.

        Args:
            crop_image: PNG bytes of the cropped table region.

        Returns:
            GridMatrix with extracted cells, or empty grid on failure.
        """
        try:
            if self._engine is None:
                from paddleocr import PPStructure  # type: ignore[import-not-found]

                self._engine = PPStructure(
                    table=True,
                    ocr=True,
                    show_log=False,
                    lang=self._lang,
                    use_gpu=self._use_gpu,
                )

            import cv2
            import numpy as np

            arr = cv2.imdecode(
                np.frombuffer(crop_image, np.uint8),
                cv2.IMREAD_COLOR,
            )
            if arr is None:
                return self._empty_grid()

            result = self._engine(arr)
            table_res = next(
                (r for r in result if r.get("type") == "table"),
                None,
            )
            if table_res is None:
                return self._empty_grid()

            html = table_res["res"].get("html", "")
            return parse_html_to_grid(html, backend_used="paddleocr")
        except Exception as exc:
            logger.error("PaddleOCR table extraction failed: %s", exc)
            return self._empty_grid()
