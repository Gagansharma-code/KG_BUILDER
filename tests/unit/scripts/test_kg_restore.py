"""Unit tests for scripts/kg_restore.py.

All docker/subprocess calls and GraphBackendRegistry are mocked -- no real
Neo4j or Docker required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.kg_restore import restore

MODULE = "scripts.kg_restore"


def _make_config(backend: str = "neo4j") -> MagicMock:
    config = MagicMock()
    config.knowledge_graph.backend = backend
    return config


@patch(f"{MODULE}.load_neo4j_native")
def test_restore_refuses_without_confirm(mock_load: MagicMock, tmp_path: Path) -> None:
    (tmp_path / "snap1.dump").write_bytes(b"data")
    (tmp_path / "snap1.graphml").write_text("<graphml/>")
    config = _make_config(backend="neo4j")

    result = restore("snap1", config, confirm=False, snapshots_dir=tmp_path)

    assert result["status"] == "refused_no_confirm"
    mock_load.assert_not_called()


@patch(f"{MODULE}.load_neo4j_native")
def test_restore_reports_graphml_only_snapshot_without_attempting_native_restore(
    mock_load: MagicMock, tmp_path: Path
) -> None:
    (tmp_path / "snap2.graphml").write_text("<graphml/>")
    config = _make_config(backend="neo4j")

    result = restore("snap2", config, confirm=False, snapshots_dir=tmp_path)

    assert result["status"] == "refused_no_confirm"
    assert result["method"] == "graphml_rebuild"
    mock_load.assert_not_called()


@patch(f"{MODULE}.GraphBackendRegistry")
@patch(f"{MODULE}.load_neo4j_native")
def test_restore_with_confirm_rebuilds_from_graphml_when_only_graphml_exists(
    mock_load: MagicMock, mock_registry: MagicMock, tmp_path: Path
) -> None:
    (tmp_path / "snap2.graphml").write_text("<graphml/>")
    config = _make_config(backend="neo4j")
    graph = MagicMock()
    mock_registry.return_value.get_graph_backend.return_value = graph

    result = restore("snap2", config, confirm=True, snapshots_dir=tmp_path)

    assert result["status"] == "restored"
    assert result["method"] == "graphml_rebuild"
    mock_load.assert_not_called()
    graph.load_into.assert_called_once_with(tmp_path / "snap2.graphml")


@patch(f"{MODULE}.load_neo4j_native")
def test_restore_with_confirm_uses_native_dump_when_available(
    mock_load: MagicMock, tmp_path: Path
) -> None:
    (tmp_path / "snap3.dump").write_bytes(b"data")
    (tmp_path / "snap3.graphml").write_text("<graphml/>")
    config = _make_config(backend="neo4j")

    result = restore("snap3", config, confirm=True, snapshots_dir=tmp_path)

    assert result["status"] == "restored"
    assert result["method"] == "neo4j_native_load"
    mock_load.assert_called_once_with(tmp_path / "snap3.dump")


def test_restore_reports_not_found_for_unknown_snapshot(tmp_path: Path) -> None:
    config = _make_config(backend="neo4j")

    result = restore("missing", config, confirm=True, snapshots_dir=tmp_path)

    assert result["status"] == "not_found"


def test_restore_copies_graphml_directly_for_networkx_backend(tmp_path: Path) -> None:
    (tmp_path / "snap4.graphml").write_text("<graphml/>")
    config = _make_config(backend="networkx")
    config.graph_path = tmp_path / "live" / "graph.graphml"

    result = restore("snap4", config, confirm=True, snapshots_dir=tmp_path)

    assert result["status"] == "restored"
    assert result["method"] == "graphml_copy"
    assert config.graph_path.read_text(encoding="utf-8") == "<graphml/>"
