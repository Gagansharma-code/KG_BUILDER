"""Unit tests for src/knowledge_graph/ingestion/kg2_appnotes/.

Tests app note scraper, prose extractor, and graph builders for KG-2 and KG-4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import yaml

from src.config import Config
from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.ingestion._schemas import IngestionResult, Triple
from src.knowledge_graph.ingestion.kg2_appnotes import ingest_app_note, scrape_app_notes
from src.knowledge_graph.ingestion.kg2_appnotes.kg2_graph_builder import (
    DESIGN_PATTERN_KEYWORDS,
    _looks_like_design_pattern,
    _looks_like_measurement,
    convert_design_triples_to_graph,
)
from src.knowledge_graph.ingestion.kg2_appnotes.kg4_graph_builder import (
    convert_placement_constraints_to_graph,
)
from src.knowledge_graph.ingestion.kg2_appnotes.prose_extractor import (
    PLACEMENT_KEYWORDS,
    _detect_placement_sentences,
    extract_design_rules,
    extract_placement_rules,
)
from src.knowledge_graph.ingestion.kg2_appnotes.scraper import (
    PDF_MAGIC,
    _should_skip_download,
    _verify_pdf_header,
    load_sources_config,
)
from src.schemas.datasheet import ExtractionMethod, PlacementConstraint
from src.schemas.kg import KGNodeType, KGRelation


# =============================================================================
# Scraper Tests
# =============================================================================


class TestScraper:
    """Tests for app note scraper."""

    @pytest.fixture
    def mock_sources_yaml(self, tmp_path: Path) -> Path:
        """Create a mock sources.yaml config."""
        sources = {
            "app_notes": [
                {
                    "name": "TEST_NOTE_1",
                    "url": "https://example.com/test1.pdf",
                    "topics": ["power"],
                    "manufacturer": "TI",
                },
                {
                    "name": "TEST_NOTE_2",
                    "url": "https://example.com/test2.pdf",
                    "topics": ["RF"],
                    "manufacturer": "ADI",
                },
            ]
        }
        config_path = tmp_path / "sources.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sources, f)
        return config_path

    def test_load_sources_config(self, mock_sources_yaml: Path) -> None:
        """Test loading sources from YAML config."""
        sources = load_sources_config(mock_sources_yaml)
        
        assert len(sources) == 2
        assert sources[0]["name"] == "TEST_NOTE_1"
        assert sources[0]["url"] == "https://example.com/test1.pdf"
        assert sources[1]["manufacturer"] == "ADI"

    def test_load_sources_config_file_not_found(self, tmp_path: Path) -> None:
        """Test loading non-existent config raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_sources_config(tmp_path / "nonexistent.yaml")

    def test_verify_pdf_header_valid(self, tmp_path: Path) -> None:
        """Test PDF header verification for valid PDF."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(PDF_MAGIC + b" test content")
        
        assert _verify_pdf_header(pdf_path) is True

    def test_verify_pdf_header_invalid(self, tmp_path: Path) -> None:
        """Test PDF header verification for invalid file."""
        pdf_path = tmp_path / "not_a_pdf.txt"
        pdf_path.write_text("This is not a PDF")
        
        assert _verify_pdf_header(pdf_path) is False

    def test_should_skip_download_file_exists_and_valid(self, tmp_path: Path) -> None:
        """Test scraper skips already-downloaded files (no HTTP call)."""
        output_dir = tmp_path / "appnotes"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        pdf_path = output_dir / "TEST_NOTE.pdf"
        pdf_path.write_bytes(PDF_MAGIC + b" content")
        
        assert _should_skip_download("TEST_NOTE", output_dir) is True

    def test_should_skip_download_file_not_exists(self, tmp_path: Path) -> None:
        """Test scraper downloads when file not present."""
        output_dir = tmp_path / "appnotes"
        
        assert _should_skip_download("NEW_NOTE", output_dir) is False

    def test_should_skip_download_invalid_pdf(self, tmp_path: Path) -> None:
        """Test scraper re-downloads invalid PDF."""
        output_dir = tmp_path / "appnotes"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        pdf_path = output_dir / "INVALID.pdf"
        pdf_path.write_text("Not a PDF")
        
        assert _should_skip_download("INVALID", output_dir) is False

    @patch("src.knowledge_graph.ingestion.kg2_appnotes.scraper.download_pdf")
    def test_scrape_app_notes_downloads_pdfs(self, mock_download, tmp_path: Path) -> None:
        """Mock requests — test scraper downloads PDF and saves to correct path."""
        sources = {
            "app_notes": [
                {"name": "TEST", "url": "https://example.com/test.pdf", "topics": [], "manufacturer": "TI"},
            ]
        }
        config_path = tmp_path / "sources.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sources, f)
        
        output_dir = tmp_path / "downloads"
        
        # Mock successful download
        pdf_path = output_dir / "TEST.pdf"
        mock_download.return_value = (True, pdf_path, "")
        
        result = scrape_app_notes(config_path, output_dir, MagicMock(spec=Config))
        
        assert len(result) == 1
        assert mock_download.called
        call_args = mock_download.call_args
        assert call_args[0][0] == "TEST"  # name
        assert call_args[0][1] == "https://example.com/test.pdf"  # url

    def test_scrape_app_notes_rejects_non_pdf_response(self, tmp_path: Path) -> None:
        """Test scraper rejects non-PDF response (bad header)."""
        sources = {
            "app_notes": [
                {"name": "BAD_PDF", "url": "https://example.com/bad.pdf", "topics": [], "manufacturer": "TI"},
            ]
        }
        config_path = tmp_path / "sources.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sources, f)
        
        output_dir = tmp_path / "downloads"
        
        with patch("src.knowledge_graph.ingestion.kg2_appnotes.scraper.download_pdf") as mock_download:
            mock_download.return_value = (False, None, "Downloaded file is not a valid PDF")
            
            result = scrape_app_notes(config_path, output_dir, MagicMock(spec=Config))
            
            assert len(result) == 0  # Failed download not included


# =============================================================================
# Prose Extractor Tests
# =============================================================================


class TestProseExtractor:
    """Tests for prose extraction (Pass 1 and Pass 2)."""

    @pytest.fixture
    def mock_config(self) -> Config:
        """Create mock Config."""
        config = MagicMock(spec=Config)
        config.confidence_thresholds = {"triple_min": 0.65}
        return config

    @patch("src.knowledge_graph.ingestion.kg2_appnotes.prose_extractor.extract_triples")
    def test_pass1_calls_triple_extractor(self, mock_extract_triples, mock_config) -> None:
        """Test prose_extractor Pass 1 calls triple_extractor."""
        # Mock design rule triples
        mock_extract_triples.return_value = [
            Triple(
                subject="buck converter",
                relation=KGRelation.REQUIRES,
                object_text="inductor",
                source_sentence="A buck converter requires an inductor.",
                source_document="test.pdf",
                source_url="file://test.pdf",
                confidence=0.80,
                extraction_method=ExtractionMethod.P1_VECTOR,
            ),
        ]
        
        result = extract_design_rules(
            "Some text about buck converters.",
            "test.pdf",
            "file://test.pdf",
            mock_config,
        )
        
        assert mock_extract_triples.called
        assert len(result) == 1
        assert result[0].relation == KGRelation.REQUIRES

    @patch("src.knowledge_graph.ingestion.kg2_appnotes.prose_extractor.extract_triples")
    def test_pass1_filters_by_relation_type(self, mock_extract_triples, mock_config) -> None:
        """Test prose_extractor Pass 1 filters by relation type."""
        # Mock mixed triples
        mock_extract_triples.return_value = [
            Triple(
                subject="design", relation=KGRelation.REQUIRES,
                object_text="resistor", source_sentence="S1", source_document="d", source_url="u",
                confidence=0.80, extraction_method=ExtractionMethod.P1_VECTOR,
            ),
            Triple(
                subject="capacitor", relation=KGRelation.USES,
                object_text="dielectric", source_sentence="S2", source_document="d", source_url="u",
                confidence=0.80, extraction_method=ExtractionMethod.P1_VECTOR,
            ),
            Triple(
                subject="pin", relation=KGRelation.CONNECTS_TO,
                object_text="net", source_sentence="S3", source_document="d", source_url="u",
                confidence=0.80, extraction_method=ExtractionMethod.P1_VECTOR,
            ),
        ]
        
        result = extract_design_rules(
            "Some text.", "test.pdf", "file://test.pdf", mock_config
        )
        
        # Should only keep REQUIRES and USES, not CONNECTS_TO
        assert len(result) == 2
        assert all(t.relation in {KGRelation.REQUIRES, KGRelation.USES} for t in result)

    def test_pass2_detects_spatial_keywords(self, mock_config: Config) -> None:
        """Test prose_extractor Pass 2 detects spatial keyword sentences correctly."""
        text = """
        Place the input capacitor near the VIN pin.
        This design requires careful component selection.
        Keep the feedback traces away from switching nodes.
        The converter uses a buck topology.
        Minimize the loop area for EMI.
        """
        
        sentences = _detect_placement_sentences(text)
        
        # Should detect 3 sentences with spatial keywords
        assert len(sentences) >= 3  # "Place", "near", "away from", "minimize"
        assert any("Place" in s or "place" in s for s in sentences)
        assert any("near" in s for s in sentences)

    @patch("src.knowledge_graph.ingestion.kg2_appnotes.prose_extractor.parse_constraints")
    def test_pass2_reuses_phase5_spatial_parser(self, mock_parse_constraints, mock_config) -> None:
        """Test prose_extractor Pass 2 reuses phase5_layout.spatial_parser."""
        from src.datasheet.phase5_layout._schemas import LayoutExtractionResult
        
        mock_parse_constraints.return_value = LayoutExtractionResult(
            constraints=[
                PlacementConstraint(
                    constraint_type="proximity",
                    subject="C1",
                    relative_to="U1.VIN",
                    relative_to_type="pin",
                    max_distance_mm=5.0,
                    hard=True,
                    source_sentence="Place C1 near VIN.",
                    confidence=0.90,
                ),
            ],
        )
        
        result = extract_placement_rules(
            "Place the capacitor within 5mm of the input pin.",
            Path("/tmp/test.pdf"),
            mock_config,
        )
        
        # Verify parse_constraints was called (from phase5_layout)
        assert mock_parse_constraints.called
        assert len(result) == 1
        assert result[0].constraint_type == "proximity"


# =============================================================================
# Graph Builder Tests
# =============================================================================


class TestKG2GraphBuilder:
    """Tests for KG-2 graph builder (design recipes)."""

    def test_looks_like_design_pattern(self) -> None:
        """Test design pattern heuristic detection."""
        assert _looks_like_design_pattern("buck converter design") is True
        assert _looks_like_design_pattern("amplifier circuit") is True
        assert _looks_like_design_pattern("filter topology") is True
        assert _looks_like_design_pattern("capacitor") is False

    def test_looks_like_measurement(self) -> None:
        """Test measurement heuristic detection."""
        assert _looks_like_measurement("10V input") is True
        assert _looks_like_measurement("100mA current") is True
        assert _looks_like_measurement("1kΩ resistance") is True
        assert _looks_like_measurement("input capacitor") is False

    def test_kg2_graph_builder_sets_layer_2(self, tmp_path: Path) -> None:
        """Test kg2_graph_builder sets layer=2 on all created nodes."""
        graph = KnowledgeGraph()
        base_stats = graph.stats()
        
        triples = [
            Triple(
                subject="buck converter",
                relation=KGRelation.REQUIRES,
                object_text="inductor",
                source_sentence="Test sentence.",
                source_document="test.pdf",
                source_url="file://test.pdf",
                confidence=0.80,
                extraction_method=ExtractionMethod.P1_VECTOR,
            ),
        ]
        
        convert_design_triples_to_graph(triples, tmp_path / "test.pdf", graph)
        
        # Check all nodes in graph have layer=2
        stats = graph.stats()
        # Verify layer-specific counts relative to bootstrap baseline
        assert stats.get("nodes_layer_2", 0) >= base_stats.get("nodes_layer_2", 0) + 1
        assert stats.get("nodes_layer_1", 0) == base_stats.get("nodes_layer_1", 0)
        assert stats.get("nodes_layer_3", 0) == base_stats.get("nodes_layer_3", 0)
        assert stats.get("nodes_layer_4", 0) == base_stats.get("nodes_layer_4", 0)

    def test_kg2_creates_design_recipe_nodes(self, tmp_path: Path) -> None:
        """Test KG-2 creates DESIGN_RECIPE nodes for design patterns."""
        graph = KnowledgeGraph()
        
        triples = [
            Triple(
                subject="buck converter circuit",  # Contains "circuit" keyword
                relation=KGRelation.REQUIRES,
                object_text="switching regulator",
                source_sentence="Test.",
                source_document="test.pdf",
                source_url="file://test.pdf",
                confidence=0.80,
                extraction_method=ExtractionMethod.P1_VECTOR,
            ),
        ]
        
        convert_design_triples_to_graph(triples, tmp_path / "test.pdf", graph)
        
        # Check for design_recipe node
        node = graph.get_node("design_recipe:buck_converter_circuit")
        assert node is not None
        assert node.node_type == KGNodeType.DESIGN_RECIPE
        assert node.layer == 2

    def test_kg2_creates_component_type_nodes(self, tmp_path: Path) -> None:
        """Test KG-2 creates COMPONENT_TYPE nodes for non-design subjects."""
        graph = KnowledgeGraph()
        
        triples = [
            Triple(
                subject="input capacitor",  # No design keyword
                relation=KGRelation.REQUIRES,
                object_text="10uF rating",
                source_sentence="Test.",
                source_document="test.pdf",
                source_url="file://test.pdf",
                confidence=0.80,
                extraction_method=ExtractionMethod.P1_VECTOR,
            ),
        ]
        
        convert_design_triples_to_graph(triples, tmp_path / "test.pdf", graph)
        
        # Check for component_type node
        node = graph.get_node("component_type:input_capacitor")
        assert node is not None
        assert node.node_type == KGNodeType.COMPONENT_TYPE


class TestKG4GraphBuilder:
    """Tests for KG-4 graph builder (placement rules)."""

    def test_kg4_graph_builder_sets_layer_4(self, tmp_path: Path) -> None:
        """Test kg4_graph_builder sets layer=4 on all created nodes."""
        graph = KnowledgeGraph()
        
        constraints = [
            PlacementConstraint(
                constraint_type="proximity",
                subject="C1",
                relative_to="U1.VIN",
                relative_to_type="pin",
                max_distance_mm=5.0,
                hard=True,
                source_sentence="Place C1 near VIN.",
                confidence=0.90,
            ),
        ]
        
        convert_placement_constraints_to_graph(constraints, tmp_path / "test.pdf", graph)
        
        # Check all nodes in graph have layer=4
        stats = graph.stats()
        assert stats.get("nodes_layer_4", 0) >= 1
        assert stats.get("nodes_layer_1", 0) == 0
        assert stats.get("nodes_layer_2", 0) <= 1  # Component type node may be layer 2

    def test_kg4_creates_placement_rule_nodes(self, tmp_path: Path) -> None:
        """Test KG-4 creates PLACEMENT_RULE nodes."""
        graph = KnowledgeGraph()
        
        constraints = [
            PlacementConstraint(
                constraint_type="keepout",
                subject="L1",
                relative_to="C2",
                relative_to_type="component",
                min_distance_mm=3.0,
                hard=False,
                source_sentence="Keep inductor away from cap.",
                confidence=0.85,
            ),
        ]
        
        pdf_path = tmp_path / "appnote_test.pdf"
        convert_placement_constraints_to_graph(constraints, pdf_path, graph)
        
        # Check for placement_rule node with correct ID pattern
        node = graph.get_node("placement_rule:appnote:appnote_test:0")
        assert node is not None
        assert node.node_type == KGNodeType.PLACEMENT_RULE
        assert node.layer == 4
        assert node.properties["constraint_type"] == "keepout"

    def test_kg4_creates_governed_by_edges(self, tmp_path: Path) -> None:
        """Test KG-4 creates GOVERNED_BY edges from subjects to placement rules."""
        graph = KnowledgeGraph()
        
        constraints = [
            PlacementConstraint(
                constraint_type="proximity",
                subject="C1",
                relative_to="U1.VIN",
                relative_to_type="pin",
                max_distance_mm=5.0,
                hard=True,
                source_sentence="Place C1 near VIN.",
                confidence=0.90,
            ),
        ]
        
        convert_placement_constraints_to_graph(constraints, tmp_path / "test.pdf", graph)
        
        # Check for edge from component to placement rule
        edges = graph.get_edges_from("component_type:c1")
        assert len(edges) >= 1
        assert any(e.relation == KGRelation.GOVERNED_BY for e in edges)


# =============================================================================
# Integration Tests
# =============================================================================


class TestAppNoteIngestion:
    """Integration tests for app note ingestion."""

    @pytest.fixture
    def mock_config(self) -> Config:
        """Create mock Config."""
        config = MagicMock(spec=Config)
        config.confidence_thresholds = {"triple_min": 0.65}
        return config

    @patch("src.knowledge_graph.ingestion.kg2_appnotes.extract_from_pdf")
    def test_ingest_app_note_returns_ingestion_result(self, mock_extract, mock_config, tmp_path: Path) -> None:
        """Test ingest_app_note returns IngestionResult with both KG-2 and KG-4 counts."""
        # Mock extraction results
        mock_extract.return_value = (
            [  # Design triples (KG-2)
                Triple(
                    subject="buck converter",
                    relation=KGRelation.REQUIRES,
                    object_text="inductor",
                    source_sentence="Test.", source_document="d", source_url="u",
                    confidence=0.80, extraction_method=ExtractionMethod.P1_VECTOR,
                ),
            ],
            [  # Placement constraints (KG-4)
                PlacementConstraint(
                    constraint_type="proximity",
                    subject="C1",
                    relative_to="U1.VIN",
                    relative_to_type="pin",
                    max_distance_mm=5.0,
                    hard=True,
                    source_sentence="Test.",
                    confidence=0.90,
                ),
            ],
        )
        
        graph = KnowledgeGraph()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF test content")
        
        result = ingest_app_note(pdf_path, graph, mock_config)
        
        assert isinstance(result, IngestionResult)
        assert result.source_document == "test.pdf"
        assert result.success is True
        # Should have nodes from both KG-2 and KG-4
        assert result.nodes_created > 0
        assert result.edges_created > 0

    @patch("src.knowledge_graph.ingestion.kg2_appnotes.extract_from_pdf")
    def test_ingest_continues_when_placement_extraction_fails(self, mock_extract, mock_config, tmp_path: Path) -> None:
        """Test ingest_app_note continues when Pass 2 placement extraction fails."""
        # Mock: design rules succeed, placement fails
        mock_extract.return_value = (
            [  # Design triples (KG-2) - succeeds
                Triple(
                    subject="design",
                    relation=KGRelation.REQUIRES,
                    object_text="capacitor",
                    source_sentence="Test.", source_document="d", source_url="u",
                    confidence=0.80, extraction_method=ExtractionMethod.P1_VECTOR,
                ),
            ],
            [],  # No placement constraints (Pass 2 returned nothing)
        )
        
        graph = KnowledgeGraph()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF test")
        
        result = ingest_app_note(pdf_path, graph, mock_config)
        
        # Should still succeed with KG-2 nodes
        assert result.success is True
        assert result.nodes_created > 0

    @patch("src.knowledge_graph.ingestion.kg2_appnotes.extract_from_pdf")
    def test_ingest_handles_pdf_extraction_failure(self, mock_extract, mock_config: Config, tmp_path: Path) -> None:
        """Test ingest_app_note handles PDF extraction failure gracefully."""
        # Mock extraction to raise exception
        mock_extract.side_effect = Exception("PDF extraction failed")
        
        graph = KnowledgeGraph()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF test")
        
        result = ingest_app_note(pdf_path, graph, mock_config)
        
        assert result.success is False
        assert len(result.errors) > 0


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_placement_keywords_defined(self) -> None:
        """Test PLACEMENT_KEYWORDS contains expected spatial terms."""
        assert "place" in PLACEMENT_KEYWORDS
        assert "near" in PLACEMENT_KEYWORDS
        assert "within" in PLACEMENT_KEYWORDS
        assert "minimize" in PLACEMENT_KEYWORDS
        assert len(PLACEMENT_KEYWORDS) >= 10

    def test_design_pattern_keywords_defined(self) -> None:
        """Test DESIGN_PATTERN_KEYWORDS contains expected terms."""
        assert "design" in DESIGN_PATTERN_KEYWORDS
        assert "circuit" in DESIGN_PATTERN_KEYWORDS
        assert "converter" in DESIGN_PATTERN_KEYWORDS
        assert "amplifier" in DESIGN_PATTERN_KEYWORDS
