"""Gate tests for Tier 0 KiCad symbol and footprint parsers."""
import pytest
import json
from pathlib import Path
from src.knowledge_base.tier0.symbol_parser import parse_symbol_library
from src.knowledge_base.tier0.footprint_parser import parse_footprint_file
from src.knowledge_base.tier0.map_generator import generate_symbol_map, generate_footprint_map
from src.schemas.documents import DocumentType

# ── Fixtures ─────────────────────────────────────────────────────────────────

SYMBOL_LIB_FIXTURE = """\
(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
  (symbol "OPA189" (in_bom yes) (on_board yes)
    (property "Reference" "U" (id 0) (at 0 0 0))
    (property "Value" "OPA189" (id 1) (at 0 0 0))
    (property "Footprint" "Package_TO_SOT_SMD:SOT-23-5" (id 2) (at 0 0 0))
    (property "Datasheet" "https://www.ti.com/lit/ds/symlink/opa189.pdf" (id 3) (at 0 0 0))
    (property "Description" "Zero-drift op-amp" (id 4) (at 0 0 0))
    (property "ki_keywords" "precision op-amp zero-drift" (id 5) (at 0 0 0))
    (symbol "OPA189_0_1"
      (pin input line (at -10.16 2.54 0) (length 2.54)
        (name "IN+" (effects (font (size 1.27 1.27))))
        (number "3" (effects (font (size 1.27 1.27))))
      )
      (pin input line (at -10.16 -2.54 0) (length 2.54)
        (name "IN-" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27))))
      )
      (pin power_in line (at 0 5.08 270) (length 2.54)
        (name "V+" (effects (font (size 1.27 1.27))))
        (number "7" (effects (font (size 1.27 1.27))))
      )
      (pin output line (at 10.16 0 180) (length 2.54)
        (name "OUT" (effects (font (size 1.27 1.27))))
        (number "6" (effects (font (size 1.27 1.27))))
      )
    )
  )
  (symbol "TL072" (in_bom yes) (on_board yes)
    (property "Reference" "U" (id 0) (at 0 0 0))
    (property "Value" "TL072" (id 1) (at 0 0 0))
    (property "Footprint" "" (id 2) (at 0 0 0))
    (property "Datasheet" "https://www.ti.com/lit/ds/symlink/tl072.pdf" (id 3) (at 0 0 0))
    (property "Description" "Dual op-amp" (id 4) (at 0 0 0))
    (symbol "TL072_1_1"
      (pin input line (at -10.16 2.54 0) (length 2.54)
        (name "IN+" (effects (font (size 1.27 1.27))))
        (number "3" (effects (font (size 1.27 1.27))))
      )
      (pin output line (at 10.16 0 180) (length 2.54)
        (name "OUT" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27))))
      )
    )
    (symbol "TL072_2_1"
      (pin input line (at -10.16 2.54 0) (length 2.54)
        (name "IN+" (effects (font (size 1.27 1.27))))
        (number "5" (effects (font (size 1.27 1.27))))
      )
      (pin output line (at 10.16 0 180) (length 2.54)
        (name "OUT" (effects (font (size 1.27 1.27))))
        (number "7" (effects (font (size 1.27 1.27))))
      )
    )
  )
)
"""

FOOTPRINT_FIXTURE = """\
(footprint "SOT-23-5" (version 20211014) (generator pcbnew)
  (layer "F.Cu")
  (descr "SOT-23-5, 5 pins, 1.6x2.9mm courtyard")
  (attr smd)
  (fp_text reference "REF**" (at 0 -2.05 0) (layer "F.SilkS"))
  (fp_text value "SOT-23-5" (at 0 2.05 0) (layer "F.Fab"))
  (fp_line (start -1.6 -1.5) (end 1.6 -1.5) (layer "F.CrtYd") (width 0.05))
  (fp_line (start 1.6 -1.5) (end 1.6 1.5) (layer "F.CrtYd") (width 0.05))
  (fp_line (start 1.6 1.5) (end -1.6 1.5) (layer "F.CrtYd") (width 0.05))
  (fp_line (start -1.6 1.5) (end -1.6 -1.5) (layer "F.CrtYd") (width 0.05))
  (pad "1" smd rect (at -1.4 0.95 0) (size 0.9 1.3) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at -1.4 -0.95 0) (size 0.9 1.3) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "3" smd rect (at 1.4 -0.95 0) (size 0.9 1.3) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "4" smd rect (at 1.4 0 0) (size 0.9 1.3) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "5" smd rect (at 1.4 0.95 0) (size 0.9 1.3) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""

FOOTPRINT_NO_COURTYARD = """\
(footprint "R_0402" (version 20211014) (generator pcbnew)
  (layer "F.Cu")
  (descr "0402 resistor")
  (attr smd)
  (pad "1" smd rect (at -0.5 0 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 0.5 0 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""


# ── Symbol parser tests ───────────────────────────────────────────────────────

def test_symbol_parser_returns_correct_count(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    assert len(entries) == 2

def test_symbol_parser_correct_document_type(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    for e in entries:
        assert e.document_type == DocumentType.KICAD_SYMBOL

def test_symbol_parser_opa189_fields(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    opa = next(e for e in entries if e.symbol_name == "OPA189")
    assert opa.library_name == "Amplifier_Operational"
    assert opa.description == "Zero-drift op-amp"
    assert opa.datasheet_url == "https://www.ti.com/lit/ds/symlink/opa189.pdf"
    assert "precision" in opa.keywords or "op-amp" in opa.keywords

def test_symbol_parser_opa189_pin_count(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    opa = next(e for e in entries if e.symbol_name == "OPA189")
    assert len(opa.pins) == 4

def test_symbol_parser_opa189_pin_names(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    opa = next(e for e in entries if e.symbol_name == "OPA189")
    pin_names = {p.pin_name for p in opa.pins}
    assert "IN+" in pin_names
    assert "IN-" in pin_names
    assert "OUT" in pin_names
    assert "V+" in pin_names

def test_symbol_parser_pin_type_mapping(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    opa = next(e for e in entries if e.symbol_name == "OPA189")
    pin_types = {p.pin_name: p.pin_type for p in opa.pins}
    assert pin_types["IN+"] == "input"
    assert pin_types["OUT"] == "output"
    assert pin_types["V+"] == "power_in"

def test_symbol_parser_multiunit_collects_all_pins(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    tl = next(e for e in entries if e.symbol_name == "TL072")
    # 2 pins in unit 1 + 2 pins in unit 2
    assert len(tl.pins) == 4

def test_symbol_parser_document_id_is_deterministic(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    e1 = parse_symbol_library(sym_file)
    e2 = parse_symbol_library(sym_file)
    ids1 = {e.document_id for e in e1}
    ids2 = {e.document_id for e in e2}
    assert ids1 == ids2

def test_symbol_parser_ingestion_tier_is_zero(tmp_path):
    sym_file = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    for e in entries:
        assert e.ingestion_tier == 0

def test_symbol_parser_empty_file_returns_empty(tmp_path):
    sym_file = tmp_path / "empty.kicad_sym"
    sym_file.write_text("(kicad_symbol_lib (version 20211014))", encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    assert entries == []

def test_symbol_parser_malformed_file_returns_empty(tmp_path):
    sym_file = tmp_path / "bad.kicad_sym"
    sym_file.write_text("this is not valid sexp ))))", encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    assert entries == []


# ── Footprint parser tests ────────────────────────────────────────────────────

def test_footprint_parser_returns_entry(tmp_path):
    lib_dir = tmp_path / "Package_TO_SOT_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "SOT-23-5.kicad_mod"
    fp_file.write_text(FOOTPRINT_FIXTURE, encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry is not None

def test_footprint_parser_document_type(tmp_path):
    lib_dir = tmp_path / "Package_TO_SOT_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "SOT-23-5.kicad_mod"
    fp_file.write_text(FOOTPRINT_FIXTURE, encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry.document_type == DocumentType.KICAD_FOOTPRINT

def test_footprint_parser_correct_fields(tmp_path):
    lib_dir = tmp_path / "Package_TO_SOT_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "SOT-23-5.kicad_mod"
    fp_file.write_text(FOOTPRINT_FIXTURE, encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry.footprint_name == "SOT-23-5"
    assert entry.library_name == "Package_TO_SOT_SMD.pretty"
    assert entry.pad_count == 5

def test_footprint_parser_courtyard_dimensions(tmp_path):
    lib_dir = tmp_path / "Package_TO_SOT_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "SOT-23-5.kicad_mod"
    fp_file.write_text(FOOTPRINT_FIXTURE, encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry.courtyard_x_mm == pytest.approx(3.2, abs=0.1)
    assert entry.courtyard_y_mm == pytest.approx(3.0, abs=0.1)

def test_footprint_parser_no_courtyard_sets_review_required(tmp_path):
    lib_dir = tmp_path / "Resistor_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "R_0402.kicad_mod"
    fp_file.write_text(FOOTPRINT_NO_COURTYARD, encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry is not None
    assert entry.review_required is True

def test_footprint_parser_description(tmp_path):
    lib_dir = tmp_path / "Package_TO_SOT_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "SOT-23-5.kicad_mod"
    fp_file.write_text(FOOTPRINT_FIXTURE, encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry.description is not None
    assert "SOT-23-5" in entry.description

def test_footprint_parser_ingestion_tier(tmp_path):
    lib_dir = tmp_path / "Package_TO_SOT_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "SOT-23-5.kicad_mod"
    fp_file.write_text(FOOTPRINT_FIXTURE, encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry.ingestion_tier == 0

def test_footprint_parser_malformed_returns_none(tmp_path):
    lib_dir = tmp_path / "Bad.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "bad.kicad_mod"
    fp_file.write_text("not valid )))))", encoding="utf-8")
    entry = parse_footprint_file(fp_file)
    assert entry is None


# ── Map generator tests ───────────────────────────────────────────────────────

def test_generate_symbol_map_writes_json(tmp_path):
    lib_dir = tmp_path / "Amplifier_Operational.kicad_sym"
    sym_file = tmp_path / "test.kicad_sym"
    sym_file.write_text(SYMBOL_LIB_FIXTURE, encoding="utf-8")
    entries = parse_symbol_library(sym_file)
    out = tmp_path / "symbol_map.json"
    count = generate_symbol_map(entries, out)
    assert count == 2
    assert out.exists()
    data = json.loads(out.read_text())
    assert "OPA189" in data
    assert data["OPA189"]["library"] == "test"
    assert data["OPA189"]["symbol"] == "OPA189"

def test_generate_footprint_map_writes_json(tmp_path):
    lib_dir = tmp_path / "Package_TO_SOT_SMD.pretty"
    lib_dir.mkdir()
    fp_file = lib_dir / "SOT-23-5.kicad_mod"
    fp_file.write_text(FOOTPRINT_FIXTURE, encoding="utf-8")
    entries = [parse_footprint_file(fp_file)]
    out = tmp_path / "footprint_map.json"
    count = generate_footprint_map(entries, out)
    assert count == 1
    data = json.loads(out.read_text())
    assert "SOT-23-5" in data
    assert "Package_TO_SOT_SMD" in data["SOT-23-5"]


# ── resolve_kicad_symbol integration ─────────────────────────────────────────

def test_resolve_kicad_symbol_falls_back_to_hardcoded():
    """Without generated map, hardcoded map still works."""
    from src.output.kicad_symbol_map import resolve_kicad_symbol
    ref = resolve_kicad_symbol("TPS62933DRLR", "unknown")
    assert ref.library == "Device"
    assert ref.symbol == "TPS62933"

def test_resolve_kicad_footprint_falls_back_to_hardcoded():
    """Without generated map, hardcoded map still works."""
    from src.output.kicad_footprint_map import resolve_kicad_footprint
    result = resolve_kicad_footprint("SOT-23-5")
    assert "SOT-23-5" in result

def test_resolve_kicad_symbol_uses_generated_map(tmp_path, monkeypatch):
    """When generated map exists, it takes precedence."""
    import json
    from src.output import kicad_symbol_map as ksm
    from src.output.kicad_symbol_map import KiCadSymbolRef
    # Reset cached map
    monkeypatch.setattr(ksm, "_GENERATED_SYMBOL_MAP", None)
    # Write fake generated map
    map_path = tmp_path / "symbol_map.json"
    map_path.write_text(json.dumps({
        "MY_TEST_PART": {"library": "TestLib", "symbol": "MY_TEST_PART"}
    }), encoding="utf-8")
    raw = json.loads(map_path.read_text())
    monkeypatch.setattr(
        ksm, "_load_generated_symbol_map",
        lambda: {
            k: KiCadSymbolRef(library=v["library"], symbol=v["symbol"])
            for k, v in raw.items()
        },
    )
    result = ksm.resolve_kicad_symbol("MY_TEST_PART", "unknown")
    assert result.library == "TestLib"
