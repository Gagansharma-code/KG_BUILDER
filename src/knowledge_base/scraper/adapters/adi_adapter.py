"""Analog Devices direct CDN datasheet adapter."""

from __future__ import annotations

import logging
import re

import httpx

from src.knowledge_base.scraper.adapters.base import FetchResult, SourceAdapter

logger = logging.getLogger(__name__)

ADI_CDN_PATTERNS = [
    "https://www.analog.com/media/en/technical-documentation/data-sheets/{mpn_lower}.pdf",
    "https://www.analog.com/media/en/technical-documentation/data-sheets/{mpn_base}.pdf",
]


def _mpn_lower(mpn: str) -> str:
    return mpn.lower().replace("_", "-")


def _mpn_base(mpn: str) -> str:
    """Strip trailing alphanumeric package code, lowercase."""
    base = re.sub(r"[A-Za-z0-9]+$", "", mpn)
    if not base:
        base = mpn
    return base.lower().replace("_", "-")


class ADIAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "adi"

    def fetch(self, mpn: str) -> FetchResult:
        """Try ADI CDN URL patterns. Returns first URL that resolves."""
        try:
            transforms = {
                "mpn_lower": _mpn_lower(mpn),
                "mpn_base": _mpn_base(mpn),
            }
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                for pattern in ADI_CDN_PATTERNS:
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
                            "ADI HEAD %s status=%s", url, response.status_code
                        )
                    except Exception as exc:
                        logger.debug("ADI HEAD failed for %s: %s", url, exc)
        except Exception as exc:
            logger.debug("ADIAdapter.fetch failed for %s: %s", mpn, exc)
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)
