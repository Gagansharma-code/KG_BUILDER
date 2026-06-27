"""Base interface for all source adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FetchResult:
    """Result from one adapter fetch attempt.

    pdf_url:      Direct URL to the PDF file. None on miss.
    content_type: MIME type hint if known ("application/pdf"). None if unknown.
    source:       Name of the adapter that produced this result.
    mpn:          The MPN that was queried.
    """
    pdf_url:      Optional[str]
    content_type: Optional[str]
    source:       str
    mpn:          str


class SourceAdapter(ABC):
    """Abstract base for all datasheet source adapters.

    Each adapter implements a single fetch() method with a fixed signature.
    The population runner calls adapters in fallback order. First non-None
    pdf_url wins.

    All adapters must:
    - Return FetchResult with pdf_url=None on any failure (never raise)
    - Be safe to call concurrently (but the population runner is sequential)
    - Log failures at DEBUG level, not ERROR (misses are expected)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this adapter (used in logging and FetchResult.source)."""

    @abstractmethod
    def fetch(self, mpn: str) -> FetchResult:
        """Attempt to retrieve a datasheet PDF URL for the given MPN.

        Args:
            mpn: Manufacturer part number, e.g. "TPS7A20DRVR"

        Returns:
            FetchResult with pdf_url set if found, None otherwise.
            Never raises — catches all exceptions internally.
        """
