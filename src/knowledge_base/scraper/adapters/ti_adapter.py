"""Texas Instruments direct CDN datasheet adapter."""

from __future__ import annotations

import logging
import re

import httpx

from src.knowledge_base.scraper.adapters.base import FetchResult, SourceAdapter

logger = logging.getLogger(__name__)

TI_CDN_PATTERNS = [
    "https://www.ti.com/lit/ds/symlink/{mpn_lower}.pdf",
    "https://www.ti.com/lit/ds/symlink/{mpn_base}.pdf",
    "https://www.ti.com/lit/ds/symlink/{mpn_stripped}.pdf",
]


def _mpn_lower(mpn: str) -> str:
    return mpn.lower()


def _mpn_base(mpn: str) -> str:
    """Strip last contiguous non-digit group from end, then lowercase."""
    base = re.sub(r"[^0-9\-]+$", "", mpn, count=1)
    if not base:
        base = mpn
    return base.lower()


def _mpn_stripped(mpn: str) -> str:
    """Strip all trailing letters, lowercase."""
    stripped = re.sub(r"[A-Za-z]+$", "", mpn)
    if not stripped:
        stripped = mpn
    return stripped.lower()


class TIAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "ti"

    def fetch(self, mpn: str) -> FetchResult:
        """Try TI CDN URL patterns. Returns first URL that resolves."""
        try:
            transforms = {
                "mpn_lower": _mpn_lower(mpn),
                "mpn_base": _mpn_base(mpn),
                "mpn_stripped": _mpn_stripped(mpn),
            }
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                for pattern in TI_CDN_PATTERNS:
                    url = pattern.format(**transforms)
                    try:
                        response = client.head(url)
                        if response.status_code == 404:
                            continue
                        if response.status_code == 200:
                            content_type = response.headers.get("Content-Type", "")
                            if "pdf" in content_type.lower():
                                return FetchResult(
                                    pdf_url=url,
                                    content_type="application/pdf",
                                    source=self.name,
                                    mpn=mpn,
                                )
                        logger.debug(
                            "TI HEAD %s status=%s", url, response.status_code
                        )
                    except Exception as exc:
                        logger.debug("TI HEAD failed for %s: %s", url, exc)
        except Exception as exc:
            logger.debug("TIAdapter.fetch failed for %s: %s", mpn, exc)
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)
