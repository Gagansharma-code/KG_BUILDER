"""Nexar GraphQL API adapter for datasheet URL resolution."""

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

logger = logging.getLogger(__name__)

NEXAR_GRAPHQL_URL = "https://api.nexar.com/graphql"
NEXAR_TOKEN_URL = "https://identity.nexar.com/connect/token"
NEXAR_BATCH_SIZE = 50
NEXAR_TIMEOUT_S = 30


def _escape_graphql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _select_pdf_url(documents: list[dict[str, Any]]) -> Optional[str]:
    pdf_docs = [
        d for d in documents
        if isinstance(d.get("url"), str) and d["url"].lower().endswith(".pdf")
    ]
    if not pdf_docs:
        return None
    for doc in pdf_docs:
        name = doc.get("name") or ""
        if "datasheet" in str(name).lower():
            return doc["url"]
    return pdf_docs[0]["url"]


def _extract_pdf_from_part(part: Optional[dict[str, Any]]) -> Optional[str]:
    if not part:
        return None
    collections = part.get("documentCollections") or []
    all_docs: list[dict[str, Any]] = []
    for coll in collections:
        if isinstance(coll, dict):
            all_docs.extend(coll.get("documents") or [])
    return _select_pdf_url(all_docs)


class NexarAdapter(SourceAdapter):
    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    @property
    def name(self) -> str:
        return "nexar"

    def _has_credentials(self) -> bool:
        return bool(
            os.environ.get("NEXAR_CLIENT_ID")
            and os.environ.get("NEXAR_CLIENT_SECRET")
        )

    def _get_access_token(self) -> Optional[str]:
        if not self._has_credentials():
            return None
        if self._access_token and time.time() < self._expires_at:
            return self._access_token
        try:
            client_id = os.environ["NEXAR_CLIENT_ID"]
            client_secret = os.environ["NEXAR_CLIENT_SECRET"]
            body = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }).encode("utf-8")
            req = urllib.request.Request(
                NEXAR_TOKEN_URL,
                data=body,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=NEXAR_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            token = data.get("access_token")
            if not token:
                return None
            expires_in = int(data.get("expires_in", 3600))
            self._access_token = token
            self._expires_at = time.time() + max(expires_in - 60, 0)
            return self._access_token
        except Exception as exc:
            logger.debug("Nexar token fetch failed: %s", exc)
            return None

    def _execute_query(self, query_str: str) -> dict:
        """Execute Nexar GraphQL via urllib.request; return parsed JSON."""
        token = self._get_access_token()
        if not token:
            return {}
        body = json.dumps({"query": query_str}).encode("utf-8")
        req = urllib.request.Request(
            NEXAR_GRAPHQL_URL,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=NEXAR_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _result_from_response(
        self, mpn: str, response: dict, alias: Optional[str] = None,
    ) -> FetchResult:
        try:
            data = response.get("data") or {}
            if alias:
                block = data.get(alias) or {}
            else:
                block = data.get("supSearchMpn") or {}
            results = block.get("results") or []
            part = results[0].get("part") if results else None
            pdf_url = _extract_pdf_from_part(part)
            if pdf_url:
                return FetchResult(
                    pdf_url=pdf_url,
                    content_type="application/pdf",
                    source=self.name,
                    mpn=mpn,
                )
        except Exception as exc:
            logger.debug("Nexar parse failed for %s: %s", mpn, exc)
        return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)

    def fetch(self, mpn: str) -> FetchResult:
        """Single MPN fetch. Returns FetchResult."""
        if not self._has_credentials():
            logger.warning("Nexar credentials missing; returning None for %s", mpn)
            return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)
        try:
            escaped = _escape_graphql_string(mpn)
            query = f'''
            query FetchDatasheet {{
              supSearchMpn(q: "{escaped}", limit: 1) {{
                results {{
                  part {{
                    mpn
                    documentCollections {{
                      documents {{
                        url
                        name
                      }}
                    }}
                  }}
                }}
              }}
            }}
            '''
            response = self._execute_query(query)
            return self._result_from_response(mpn, response)
        except Exception as exc:
            logger.debug("NexarAdapter.fetch failed for %s: %s", mpn, exc)
            return FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)

    def fetch_batch(self, mpns: list[str]) -> dict[str, FetchResult]:
        """Batch fetch up to NEXAR_BATCH_SIZE MPNs."""
        results: dict[str, FetchResult] = {
            mpn: FetchResult(pdf_url=None, content_type=None, source=self.name, mpn=mpn)
            for mpn in mpns
        }
        if not mpns:
            return results
        if not self._has_credentials():
            logger.warning("Nexar credentials missing; batch fetch skipped")
            return results
        try:
            batch = mpns[:NEXAR_BATCH_SIZE]
            parts: list[str] = []
            for i, mpn in enumerate(batch):
                escaped = _escape_graphql_string(mpn)
                parts.append(f'''
              part_{i}: supSearchMpn(q: "{escaped}", limit: 1) {{
                results {{
                  part {{
                    mpn
                    documentCollections {{
                      documents {{ url name }}
                    }}
                  }}
                }}
              }}''')
            query = "query BatchDatasheets {\n" + "\n".join(parts) + "\n}"
            response = self._execute_query(query)
            for i, mpn in enumerate(batch):
                results[mpn] = self._result_from_response(
                    mpn, response, alias=f"part_{i}"
                )
        except Exception as exc:
            logger.debug("NexarAdapter.fetch_batch failed: %s", exc)
        return results
