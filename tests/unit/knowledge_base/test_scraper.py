"""Gate tests for KB scraping engine."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.knowledge_base.scraper.adapters.base import FetchResult, SourceAdapter
from src.knowledge_base.scraper.adapters.nexar_adapter import NexarAdapter
from src.knowledge_base.scraper.adapters.ti_adapter import TIAdapter
from src.knowledge_base.scraper.adapters.adi_adapter import ADIAdapter
from src.knowledge_base.scraper.adapters.stub_adapter import (
    STAdapter, NXPAdapter, InfineonAdapter, MicrochipAdapter,
)
from src.knowledge_base.scraper.request_tracker import (
    RequestTracker, DIGIKEY_DAILY_BUDGET,
)
from src.knowledge_base.scraper.mpn_discovery import discover_mpns
from src.knowledge_base.scraper.pdf_downloader import (
    build_fallback_chain, download_pdf, resolve_pdf_urls,
)
from src.knowledge_base.scraper.app_note_fetcher import (
    load_app_note_manifest, fetch_all_app_notes,
)


# ── SourceAdapter ABC ──────────────────────────────────────────────────────────

def test_source_adapter_is_abstract():
    with pytest.raises(TypeError):
        SourceAdapter()  # cannot instantiate ABC directly


# ── NexarAdapter ──────────────────────────────────────────────────────────────

def test_nexar_adapter_returns_none_without_credentials(monkeypatch):
    monkeypatch.delenv("NEXAR_CLIENT_ID", raising=False)
    monkeypatch.delenv("NEXAR_CLIENT_SECRET", raising=False)
    adapter = NexarAdapter()
    result = adapter.fetch("TPS7A20DRVR")
    assert result.pdf_url is None
    assert result.source == "nexar"

def test_nexar_adapter_name():
    adapter = NexarAdapter()
    assert adapter.name == "nexar"

def test_nexar_adapter_fetch_returns_pdf_url(monkeypatch):
    monkeypatch.setenv("NEXAR_CLIENT_ID", "fake_id")
    monkeypatch.setenv("NEXAR_CLIENT_SECRET", "fake_secret")
    adapter = NexarAdapter()
    mock_response = {
        "data": {
            "supSearchMpn": {
                "results": [{
                    "part": {
                        "mpn": "TPS7A20DRVR",
                        "documentCollections": [{
                            "documents": [
                                {"url": "https://example.com/TPS7A20.pdf",
                                 "name": "Datasheet"}
                            ]
                        }]
                    }
                }]
            }
        }
    }
    with patch.object(adapter, "_execute_query", return_value=mock_response):
        result = adapter.fetch("TPS7A20DRVR")
    assert result.pdf_url == "https://example.com/TPS7A20.pdf"
    assert result.source == "nexar"

def test_nexar_adapter_fetch_returns_none_on_no_documents(monkeypatch):
    monkeypatch.setenv("NEXAR_CLIENT_ID", "fake_id")
    monkeypatch.setenv("NEXAR_CLIENT_SECRET", "fake_secret")
    adapter = NexarAdapter()
    mock_response = {
        "data": {
            "supSearchMpn": {
                "results": [{
                    "part": {
                        "mpn": "UNKNOWN_PART",
                        "documentCollections": [{"documents": []}]
                    }
                }]
            }
        }
    }
    with patch.object(adapter, "_execute_query", return_value=mock_response):
        result = adapter.fetch("UNKNOWN_PART")
    assert result.pdf_url is None

def test_nexar_fetch_batch_returns_dict(monkeypatch):
    monkeypatch.setenv("NEXAR_CLIENT_ID", "fake_id")
    monkeypatch.setenv("NEXAR_CLIENT_SECRET", "fake_secret")
    adapter = NexarAdapter()
    mpns = ["TPS7A20DRVR", "OPA189IDBVR"]
    mock_batch_response = {
        "data": {
            "part_0": {"results": [{"part": {"mpn": "TPS7A20DRVR",
                "documentCollections": [{"documents": [{"url": "https://ex.com/a.pdf",
                                                         "name": "Datasheet"}]}]}}]},
            "part_1": {"results": [{"part": {"mpn": "OPA189IDBVR",
                "documentCollections": [{"documents": []}]}}]}
        }
    }
    with patch.object(adapter, "_execute_query", return_value=mock_batch_response):
        results = adapter.fetch_batch(mpns)
    assert isinstance(results, dict)
    assert len(results) == 2
    assert results["TPS7A20DRVR"].pdf_url == "https://ex.com/a.pdf"
    assert results["OPA189IDBVR"].pdf_url is None


# ── TIAdapter ──────────────────────────────────────────────────────────────────

def test_ti_adapter_name():
    assert TIAdapter().name == "ti"

def test_ti_adapter_returns_url_on_first_pattern_hit():
    adapter = TIAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "application/pdf"}
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head = MagicMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client
        result = adapter.fetch("TPS7A20DRVR")
    assert result.pdf_url is not None
    assert "ti.com" in result.pdf_url
    assert result.source == "ti"

def test_ti_adapter_returns_none_on_all_404():
    adapter = TIAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.headers = {}
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head = MagicMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client
        result = adapter.fetch("UNKNOWN999XYZ")
    assert result.pdf_url is None

def test_ti_adapter_never_raises():
    adapter = TIAdapter()
    with patch("httpx.Client", side_effect=Exception("network error")):
        result = adapter.fetch("TPS7A20DRVR")
    assert result.pdf_url is None


# ── ADIAdapter ────────────────────────────────────────────────────────────────

def test_adi_adapter_name():
    assert ADIAdapter().name == "adi"

def test_adi_adapter_never_raises():
    adapter = ADIAdapter()
    with patch("httpx.Client", side_effect=Exception("network error")):
        result = adapter.fetch("ADA4522-2ARMZ")
    assert result.pdf_url is None


# ── Stub adapters ─────────────────────────────────────────────────────────────

def test_stub_adapters_return_none():
    for AdapterClass in [STAdapter, NXPAdapter, InfineonAdapter, MicrochipAdapter]:
        adapter = AdapterClass()
        result = adapter.fetch("ANY_MPN")
        assert result.pdf_url is None
        assert result.mpn == "ANY_MPN"


# ── RequestTracker ────────────────────────────────────────────────────────────

def test_request_tracker_starts_at_zero(tmp_path):
    tracker = RequestTracker(path=tmp_path / "tracker.json")
    assert tracker.remaining == DIGIKEY_DAILY_BUDGET

def test_request_tracker_can_request_initially(tmp_path):
    tracker = RequestTracker(path=tmp_path / "tracker.json")
    assert tracker.can_request() is True

def test_request_tracker_increment_persists(tmp_path):
    path = tmp_path / "tracker.json"
    tracker = RequestTracker(path=path)
    tracker.increment()
    tracker2 = RequestTracker(path=path)
    assert tracker2.remaining == DIGIKEY_DAILY_BUDGET - 1

def test_request_tracker_blocks_at_budget(tmp_path):
    tracker = RequestTracker(path=tmp_path / "tracker.json")
    tracker._count = DIGIKEY_DAILY_BUDGET
    tracker._save()
    assert tracker.can_request() is False

def test_request_tracker_resets_on_new_day(tmp_path):
    path = tmp_path / "tracker.json"
    data = {"date": "2020-01-01", "count": 9000}
    path.write_text(json.dumps(data))
    tracker = RequestTracker(path=path)
    assert tracker._count == 0
    assert tracker.can_request() is True


# ── pdf_downloader ────────────────────────────────────────────────────────────

def test_build_fallback_chain_order():
    nexar = MagicMock(spec=NexarAdapter)
    ti = MagicMock(spec=TIAdapter)
    adi = MagicMock(spec=ADIAdapter)
    digikey = MagicMock()
    chain = build_fallback_chain(nexar, ti, adi, digikey)
    assert chain[0] is nexar
    assert chain[1] is ti
    assert chain[2] is adi
    assert chain[3] is digikey

def test_download_pdf_dedup_skips_existing(tmp_path):
    fake_content = b"%PDF-1.4 fake content"
    h = hashlib.sha256(fake_content).hexdigest()
    existing = tmp_path / f"{h}.pdf"
    existing.write_bytes(fake_content)

    def fake_get(*args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.iter_bytes = MagicMock(return_value=iter([fake_content]))
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("httpx.stream", side_effect=fake_get):
        result = download_pdf("https://example.com/fake.pdf", store_path=tmp_path)

    assert result is not None
    local_path, sha256 = result
    assert sha256 == h

def test_download_pdf_returns_none_on_non_pdf_content_type(tmp_path):
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.iter_bytes = MagicMock(return_value=iter([b"<html>"]))
    mock_resp.raise_for_status = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("httpx.stream", return_value=mock_resp):
        result = download_pdf("https://example.com/not-a-pdf", store_path=tmp_path)
    assert result is None

def test_download_pdf_never_raises(tmp_path):
    with patch("httpx.stream", side_effect=Exception("network error")):
        result = download_pdf("https://example.com/fake.pdf", store_path=tmp_path)
    assert result is None


# ── app_note_fetcher ──────────────────────────────────────────────────────────

def test_load_app_note_manifest_returns_list(tmp_path):
    yaml_content = """
guided_app_notes:
  - document_number: SLVA477B
    manufacturer: TI
    topology: ldo
    url: https://www.ti.com/lit/an/slva477b/slva477b.pdf
"""
    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text(yaml_content)
    result = load_app_note_manifest(sources_path)
    assert len(result) == 1
    assert result[0]["document_number"] == "SLVA477B"

def test_load_app_note_manifest_returns_empty_if_no_key(tmp_path):
    yaml_content = "other_key:\n  - value: 1\n"
    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text(yaml_content)
    result = load_app_note_manifest(sources_path)
    assert result == []

def test_load_app_note_manifest_returns_empty_if_missing_file(tmp_path):
    result = load_app_note_manifest(tmp_path / "nonexistent.yaml")
    assert result == []


# ── MPN discovery ─────────────────────────────────────────────────────────────

def test_discover_mpns_loads_from_cache(tmp_path):
    mpn_path = tmp_path / "mpn_list.json"
    mpn_path.write_text(json.dumps(["TPS7A20DRVR", "OPA189IDBVR"]))
    mock_digikey = MagicMock()
    with patch("src.knowledge_base.scraper.mpn_discovery.MPN_LIST_PATH", mpn_path):
        result = discover_mpns(mock_digikey, force_refresh=False)
    assert result == ["TPS7A20DRVR", "OPA189IDBVR"]
    mock_digikey.keyword_search_by_category.assert_not_called()

def test_discover_mpns_deduplicates(tmp_path):
    symbol_map = {"OPA189": {"library": "Amplifier_Operational", "symbol": "OPA189"}}
    symbol_map_path = tmp_path / "symbol_map.json"
    symbol_map_path.write_text(json.dumps(symbol_map))
    mpn_list_path = tmp_path / "mpn_list.json"

    mock_digikey = MagicMock()
    mock_digikey.keyword_search_by_category.return_value = ["OPA189", "TPS7A20"]

    with patch("src.knowledge_base.scraper.mpn_discovery.SYMBOL_MAP_PATH", symbol_map_path):
        with patch("src.knowledge_base.scraper.mpn_discovery.MPN_LIST_PATH", mpn_list_path):
            result = discover_mpns(mock_digikey, force_refresh=True)

    assert result.count("OPA189") == 1


# ── Full chain integration ─────────────────────────────────────────────────────

def test_fallback_chain_uses_ti_when_nexar_misses():
    nexar = MagicMock(spec=NexarAdapter)
    nexar.fetch.return_value = FetchResult(pdf_url=None, content_type=None,
                                            source="nexar", mpn="TPS7A20DRVR")
    ti = MagicMock(spec=TIAdapter)
    ti.fetch.return_value = FetchResult(
        pdf_url="https://ti.com/tps7a20.pdf",
        content_type="application/pdf",
        source="ti",
        mpn="TPS7A20DRVR",
    )
    adi = MagicMock(spec=ADIAdapter)
    digikey = MagicMock()

    chain = [nexar, ti, adi, digikey]
    result = None
    for adapter in chain:
        r = adapter.fetch("TPS7A20DRVR")
        if r.pdf_url is not None:
            result = r
            break

    assert result is not None
    assert result.source == "ti"
    adi.fetch.assert_not_called()
    digikey.fetch.assert_not_called()
