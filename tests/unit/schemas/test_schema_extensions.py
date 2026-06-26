"""Gate tests for schema extension changes."""

import pytest
from datetime import datetime, timezone

from src.schemas.datasheet import ExtractionMethod, EXTRACTION_METHOD_CONFIDENCE
from src.knowledge_graph.ingestion._schemas import IngestionResult
from src.schemas.documents import (
    DocumentType,
    IngestedDocument,
    KiCadPinDef,
    KiCadSymbolEntry,
    KiCadFootprintEntry,
    AppNoteDocument,
    ResearchPaperDocument,
    StandardDocument,
    ReferenceDesignDocument,
    CommunityPostDocument,
)


NOW = datetime.now(timezone.utc).isoformat()
BASE_DOC = dict(
    document_id="00000000-0000-0000-0000-000000000001",
    source_url="https://example.com/doc.pdf",
    content_hash="a" * 64,
    ingestion_tier=2,
    ingested_at=NOW,
)


# ── Step 1 & 2: ExtractionMethod enum and confidence dict ────────────────────

def test_new_extraction_methods_exist():
    assert ExtractionMethod.NOUGAT == "nougat"
    assert ExtractionMethod.HTML_PARSE == "html_parse"
    assert ExtractionMethod.SEXPRESSION_PARSE == "sexpression_parse"
    assert ExtractionMethod.PDF_TEXT_EXTRACT == "pdf_text_extract"
    assert ExtractionMethod.KICAD_LIBRARY == "kicad_library"

def test_all_extraction_methods_have_confidence():
    for method in ExtractionMethod:
        assert method in EXTRACTION_METHOD_CONFIDENCE, (
            f"ExtractionMethod.{method.name} has no entry in EXTRACTION_METHOD_CONFIDENCE"
        )
        score = EXTRACTION_METHOD_CONFIDENCE[method]
        assert 0.0 <= score <= 1.0

def test_new_method_confidence_values():
    assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.SEXPRESSION_PARSE] >= 0.95
    assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.KICAD_LIBRARY] >= 0.95
    assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.NOUGAT] >= 0.80


# ── Step 4: IngestionResult new fields ──────────────────────────────────────

def test_ingestion_result_new_fields_optional():
    r = IngestionResult(source_document="test.pdf")
    assert r.content_hash is None
    assert r.document_type is None
    assert r.ingestion_tier is None
    assert r.source_url is None

def test_ingestion_result_accepts_new_fields():
    r = IngestionResult(
        source_document="test.pdf",
        content_hash="b" * 64,
        document_type="app_note",
        ingestion_tier=2,
        source_url="https://ti.com/lit/an/slva477b.pdf",
    )
    assert r.content_hash == "b" * 64
    assert r.ingestion_tier == 2

def test_ingestion_result_tier_bounds():
    with pytest.raises(Exception):
        IngestionResult(source_document="x", ingestion_tier=4)
    with pytest.raises(Exception):
        IngestionResult(source_document="x", ingestion_tier=-1)


# ── Step 5: documents.py schemas ────────────────────────────────────────────

def test_document_type_enum_values():
    expected = {
        "ic_datasheet", "app_note", "research_paper", "standard",
        "reference_design", "kicad_symbol", "kicad_footprint", "community_post"
    }
    actual = {e.value for e in DocumentType}
    assert actual == expected

def test_kicad_symbol_entry_valid():
    entry = KiCadSymbolEntry(
        **BASE_DOC,
        symbol_name="OPA189",
        library_name="Amplifier_Operational",
        pins=[KiCadPinDef(pin_number="1", pin_name="IN+", pin_type="input",
                          position_x=0.0, position_y=0.0)],
    )
    assert entry.document_type == DocumentType.KICAD_SYMBOL
    assert entry.ingestion_tier == 2
    assert len(entry.pins) == 1

def test_kicad_footprint_entry_valid():
    entry = KiCadFootprintEntry(
        **BASE_DOC,
        footprint_name="SOT-23-5",
        library_name="Package_TO_SOT_SMD",
        pad_count=5,
        courtyard_x_mm=1.8,
        courtyard_y_mm=2.9,
    )
    assert entry.document_type == DocumentType.KICAD_FOOTPRINT

def test_app_note_document_valid():
    doc = AppNoteDocument(
        **BASE_DOC,
        title="Precision Current Source Design",
        document_number="SBOA327",
        manufacturer="Texas Instruments",
        topics=["current_source", "precision_analog"],
        design_recipes_extracted=3,
    )
    assert doc.document_type == DocumentType.APP_NOTE
    assert doc.design_recipes_extracted == 3

def test_research_paper_document_valid():
    doc = ResearchPaperDocument(
        **BASE_DOC,
        title="Libbrecht-Hall precision current source",
        authors=["Libbrecht", "Hall"],
        doi="10.1063/1.1144208",
        year=1993,
        equations_extracted=7,
    )
    assert doc.document_type == DocumentType.RESEARCH_PAPER
    assert doc.year == 1993

def test_standard_document_valid():
    doc = StandardDocument(
        **BASE_DOC,
        standard_body="IPC",
        standard_number="IPC-2221",
        title="Generic Standard on Printed Board Design",
        clauses_extracted=12,
    )
    assert doc.document_type == DocumentType.STANDARD

def test_reference_design_document_valid():
    doc = ReferenceDesignDocument(
        **BASE_DOC,
        title="High-Precision LDO Reference Design",
        manufacturer="Texas Instruments",
        related_components=["TPS7A20", "OPA189"],
        bom_rows_extracted=8,
    )
    assert doc.document_type == DocumentType.REFERENCE_DESIGN

def test_community_post_document_valid():
    doc = CommunityPostDocument(
        **BASE_DOC,
        title="Why does my LDO oscillate at light load?",
        tags=["ldo", "stability", "pcb-design"],
        vote_score=42,
        is_accepted=True,
    )
    assert doc.document_type == DocumentType.COMMUNITY_POST
    assert doc.vote_score == 42

def test_base_document_review_flags_default_empty():
    doc = AppNoteDocument(**BASE_DOC, title="Test")
    assert doc.review_flags == []
    assert doc.review_required is False


# ── Step 3: None guard fixes in p1_importer ─────────────────────────────────
# These tests verify the fix indirectly by importing the importer functions
# and checking that None optional fields are absent from produced KGNode.properties.

def test_none_symbol_not_stored_in_properties():
    """param.symbol=None must not appear as a key in KGNode.properties."""
    from src.schemas.datasheet import (
        ComponentDatasheet, ElectricalParameter, ExtractedValue,
        ExtractionMethod, TableSectionType,
    )
    from src.schemas.kg import KGNodeType
    from src.knowledge_graph.importers.p1_importer import _create_electrical_property_nodes

    param = ElectricalParameter(
        parameter_name="Supply Voltage",
        symbol=None,
        conditions=None,
        value=ExtractedValue(raw_text="3.3", normalized_value=3.3,
                             unit="V", typ_val=3.3, confidence=0.95),
        section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
        source_page=1,
        source_table_index=0,
    )
    ds = ComponentDatasheet(
        component_id="TEST001",
        manufacturer="TestCo",
        description="Test component",
        package="SOT-23-5",
        source_pdf_hash="a" * 64,
        electrical_parameters=[param],
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.9,
        created_at=NOW,
    )
    nodes = _create_electrical_property_nodes(ds, NOW)
    assert len(nodes) == 1
    props = nodes[0].properties
    assert "symbol" not in props, "None symbol must not be stored in properties"
    assert "conditions" not in props, "None conditions must not be stored in properties"

def test_none_pin_type_not_stored_in_properties():
    """pin.pin_type=None must not appear as a key in KGNode.properties."""
    from src.schemas.datasheet import (
        ComponentDatasheet, PinDefinition,
        ExtractionMethod,
    )
    from src.knowledge_graph.importers.p1_importer import _create_pin_nodes

    pin = PinDefinition(
        pin_number="1",
        raw_name="IN+",
        pin_type=None,
    )
    ds = ComponentDatasheet(
        component_id="TEST002",
        manufacturer="TestCo",
        description="Test component",
        package="SOT-23-5",
        source_pdf_hash="b" * 64,
        pins=[pin],
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.9,
        created_at=NOW,
    )
    nodes = _create_pin_nodes(ds, NOW)
    assert len(nodes) == 1
    props = nodes[0].properties
    assert "pin_type" not in props, "None pin_type must not be stored in properties"
