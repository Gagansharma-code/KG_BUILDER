"""Unit tests for scripts/kg_snapshot.py.

All docker/subprocess calls, graph.save(), and knowledge_version() are
mocked -- no real Neo4j or Docker required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.kg_snapshot import snapshot

MODULE = "scripts.kg_snapshot"


def _make_config(backend: str = "networkx") -> MagicMock:
    config = MagicMock()
    config.knowledge_graph.backend = backend
    config.graph_path = Path("/nonexistent/graph.graphml")
    return config


def _make_graph(stats: dict | None = None) -> MagicMock:
    graph = MagicMock()
    graph.stats.return_value = stats or {"node_count": 3, "edge_count": 2}
    return graph


@patch(f"{MODULE}.dump_neo4j_native")
@patch(f"{MODULE}._get_graph")
@patch(f"{MODULE}.knowledge_version", return_value="kg-v3.2")
def test_snapshot_produces_matching_dump_and_graphml_names(
    mock_version: MagicMock,
    mock_get_graph: MagicMock,
    mock_dump: MagicMock,
    tmp_path: Path,
) -> None:
    graph = _make_graph()
    mock_get_graph.return_value = graph

    def fake_dump(dest_path: Path) -> None:
        dest_path.write_bytes(b"fake-dump")

    mock_dump.side_effect = fake_dump
    config = _make_config(backend="neo4j")

    result = snapshot("before_pilot_ingest", config, snapshots_dir=tmp_path)

    graphml_path = Path(result["graphml_path"])
    dump_path = Path(result["dump_path"])
    assert graphml_path.parent == tmp_path
    assert dump_path.parent == tmp_path
    assert graphml_path.stem == dump_path.stem
    assert graphml_path.suffix == ".graphml"
    assert dump_path.suffix == ".dump"
    assert "kg-v3.2" in graphml_path.name
    assert "before_pilot_ingest" in graphml_path.name
    graph.save.assert_called_once_with(graphml_path)
    mock_dump.assert_called_once_with(dump_path)


@patch(f"{MODULE}.dump_neo4j_native")
@patch(f"{MODULE}._get_graph")
@patch(f"{MODULE}.knowledge_version", return_value="kg-v0.0")
def test_snapshot_skips_dump_for_non_neo4j_backend(
    mock_version: MagicMock,
    mock_get_graph: MagicMock,
    mock_dump: MagicMock,
    tmp_path: Path,
) -> None:
    mock_get_graph.return_value = _make_graph()
    config = _make_config(backend="networkx")

    result = snapshot("label", config, snapshots_dir=tmp_path)

    mock_dump.assert_not_called()
    assert result["dump_path"] is None
    assert result["dump_error"] is None


@patch(f"{MODULE}._get_graph")
@patch(f"{MODULE}.knowledge_version", return_value="kg-v1.0")
def test_snapshot_appends_exactly_one_log_entry_per_run(
    mock_version: MagicMock,
    mock_get_graph: MagicMock,
    tmp_path: Path,
) -> None:
    mock_get_graph.return_value = _make_graph(stats={"node_count": 5, "edge_count": 1})
    config = _make_config(backend="networkx")

    snapshot("first", config, snapshots_dir=tmp_path)
    log_path = tmp_path / "SNAPSHOT_LOG.md"
    assert log_path.exists()
    first_content = log_path.read_text(encoding="utf-8")
    assert first_content.count("## ") == 1
    assert "kg-v1.0" in first_content
    assert "first" in first_content
    assert "nodes: 5, edges: 1" in first_content

    snapshot("second", config, snapshots_dir=tmp_path)
    second_content = log_path.read_text(encoding="utf-8")
    assert second_content.count("## ") == 2
    assert "second" in second_content
