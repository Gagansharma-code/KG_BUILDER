"""Stub adapters for manufacturers not yet implemented."""

from __future__ import annotations

from src.knowledge_base.scraper.adapters.base import FetchResult, SourceAdapter


class STAdapter(SourceAdapter):
    """STUB — not yet implemented. Falls through to DigiKey fallback."""

    @property
    def name(self) -> str:
        return "st"

    def fetch(self, mpn: str) -> FetchResult:
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)


class NXPAdapter(SourceAdapter):
    """STUB — not yet implemented."""

    @property
    def name(self) -> str:
        return "nxp"

    def fetch(self, mpn: str) -> FetchResult:
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)


class InfineonAdapter(SourceAdapter):
    """STUB — not yet implemented."""

    @property
    def name(self) -> str:
        return "infineon"

    def fetch(self, mpn: str) -> FetchResult:
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)


class MicrochipAdapter(SourceAdapter):
    """STUB — not yet implemented."""

    @property
    def name(self) -> str:
        return "microchip"

    def fetch(self, mpn: str) -> FetchResult:
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)
