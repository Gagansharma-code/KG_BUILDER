"""DigiKey API v4 adapter for MPN discovery and datasheet URL lookup."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from src.knowledge_base.scraper.adapters.base import FetchResult, SourceAdapter
from src.knowledge_base.scraper.request_tracker import RequestTracker

logger = logging.getLogger(__name__)

DIGIKEY_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
DIGIKEY_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"
DIGIKEY_DETAIL_URL = "https://api.digikey.com/products/v4/search/{mpn}/productdetails"
DIGIKEY_CATEGORIES_URL = "https://api.digikey.com/products/v4/search/categories"
DIGIKEY_MAX_PER_CAT = 100
DIGIKEY_TIMEOUT_S = 15

DIGIKEY_CATEGORY_IDS: dict[str, int] = {
    "ldo_linear_regulators": 813,
    "buck_converters": 794,
    "boost_converters": 795,
    "voltage_references": 829,
    "power_supervisors": 783,
    "general_purpose_opamps": 696,
    "precision_zero_drift_opamps": 696,
    "instrumentation_amplifiers": 700,
    "comparators": 693,
    "adc_sar": 688,
    "adc_sigma_delta": 688,
    "dac": 689,
    "logic_buffers_level_shifters": 740,
    "usb_uart_bridges": 749,
    "can_rs485_transceivers": 706,
    "tvs_esd_protection": 877,
    "gate_drivers": 726,
    "power_mosfets": 870,
    "bjt": 851,
    "crystal_oscillators": 774,
}


class DigiKeyAdapter(SourceAdapter):
    def __init__(self, tracker: Optional[RequestTracker] = None) -> None:
        self._tracker = tracker or RequestTracker()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    @property
    def name(self) -> str:
        return "digikey"

    @property
    def tracker(self) -> RequestTracker:
        return self._tracker

    def _has_credentials(self) -> bool:
        return bool(
            os.environ.get("DIGIKEY_CLIENT_ID")
            and os.environ.get("DIGIKEY_CLIENT_SECRET")
        )

    def _get_access_token(self) -> Optional[str]:
        if not self._has_credentials():
            return None
        if self._access_token and time.time() < self._expires_at:
            return self._access_token
        try:
            client_id = os.environ["DIGIKEY_CLIENT_ID"]
            client_secret = os.environ["DIGIKEY_CLIENT_SECRET"]
            body = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }).encode("utf-8")
            req = urllib.request.Request(
                DIGIKEY_TOKEN_URL,
                data=body,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=DIGIKEY_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            token = data.get("access_token")
            if not token:
                return None
            expires_in = int(data.get("expires_in", 600))
            self._access_token = token
            self._expires_at = time.time() + max(expires_in - 30, 0)
            return self._access_token
        except Exception as exc:
            logger.debug("DigiKey token fetch failed: %s", exc)
            return None

    def _api_request(
        self,
        url: str,
        method: str = "GET",
        body: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        if not self._tracker.can_request():
            logger.warning("DigiKey daily budget exceeded")
            return None
        token = self._get_access_token()
        if not token:
            logger.warning("DigiKey credentials missing or token unavailable")
            return None
        try:
            data_bytes = None
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            if body is not None:
                data_bytes = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=DIGIKEY_TIMEOUT_S) as resp:
                self._tracker.increment()
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.debug("DigiKey API request failed %s: %s", url, exc)
            return None

    def _verify_category_ids(self) -> None:
        """Log category tree from DigiKey API for operator verification."""
        if not self._has_credentials():
            return
        try:
            data = self._api_request(DIGIKEY_CATEGORIES_URL)
            if data:
                logger.info("DigiKey categories endpoint reachable for ID verification")
        except Exception as exc:
            logger.debug("DigiKey category verification failed: %s", exc)

    def keyword_search_by_category(
        self,
        keyword: str,
        digikey_category_id: int,
        limit: int = DIGIKEY_MAX_PER_CAT,
    ) -> list[str]:
        """Search DigiKey by keyword + category, return list of MPNs."""
        if not self._tracker.can_request():
            return []
        payload = {
            "Keywords": keyword,
            "RecordCount": min(limit, DIGIKEY_MAX_PER_CAT),
            "RecordStartPosition": 0,
            "Filters": {
                "CategoryIds": [digikey_category_id],
                "InStock": True,
            },
            "Sort": {
                "Option": "SortByQuantityAvailable",
                "Direction": "Descending",
            },
        }
        data = self._api_request(DIGIKEY_SEARCH_URL, method="POST", body=payload)
        if not data:
            return []
        products = data.get("Products") or data.get("products") or []
        mpns: list[str] = []
        for product in products:
            mpn = (
                product.get("ManufacturerPartNumber")
                or product.get("manufacturerPartNumber")
                or product.get("Mpn")
                or product.get("mpn")
            )
            if mpn and isinstance(mpn, str):
                mpns.append(mpn)
        if not mpns:
            logger.warning(
                "DigiKey category %d keyword '%s' returned zero results",
                digikey_category_id,
                keyword,
            )
        return mpns

    def fetch(self, mpn: str) -> FetchResult:
        """Look up DatasheetUrl for a single MPN via DigiKey product detail API."""
        try:
            encoded_mpn = urllib.parse.quote(mpn, safe="")
            url = DIGIKEY_DETAIL_URL.format(mpn=encoded_mpn)
            data = self._api_request(url)
            if not data:
                return FetchResult(
                    pdf_url=None, content_type=None, source=self.name, mpn=mpn
                )
            product = data.get("Product") or data.get("product") or data
            datasheet_url = (
                product.get("DatasheetUrl")
                or product.get("datasheetUrl")
                or product.get("PrimaryDatasheet")
            )
            if datasheet_url and isinstance(datasheet_url, str) and datasheet_url.strip():
                return FetchResult(
                    pdf_url=datasheet_url.strip(),
                    content_type="application/pdf",
                    source=self.name,
                    mpn=mpn,
                )
        except Exception as exc:
            logger.debug("DigiKeyAdapter.fetch failed for %s: %s", mpn, exc)
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)
