"""P1 importer: Convert ComponentDatasheet to KG-3 and KG-4 nodes/edges.

Imports ComponentDatasheet objects (Team A output) into the KnowledgeGraph,
creating KGNode and KGEdge objects for component instances, pins, electrical
properties, and placement rules.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.knowledge_graph.importers._schemas import (
    BatchImportResult,
    ImportResult,
)
from src.schemas.datasheet import (
    ComponentDatasheet,
    ElectricalParameter,
    PinDefinition,
    PlacementConstraint,
)
from src.schemas.kg import (
    EXTRACTION_METHOD_CONFIDENCE,
    KGEdge,
    KGNode,
    KGNodeType,
    KGRelation,
)

if TYPE_CHECKING:
    from src.config import Config
    from src.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# Confidence for pin nodes - pins are highly structured in datasheets
PIN_CONFIDENCE = 0.97


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _create_component_instance_node(
    datasheet: ComponentDatasheet,
    now: str,
) -> KGNode:
    """Create KG-3 ComponentInstance node from ComponentDatasheet.

    Args:
        datasheet: Source ComponentDatasheet
        now: ISO timestamp for created_at

    Returns:
        KGNode for the component instance (Layer 3)
    """
    node_id = f"component_instance:{datasheet.component_id}"

    properties: dict[str, Any] = {
        "manufacturer": datasheet.manufacturer,
        "description": datasheet.description,
        "package": datasheet.package,
        "pin_count": len(datasheet.pins),
        "extraction_confidence": datasheet.extraction_confidence,
    }

    # Add review flags if present
    if datasheet.review_flags:
        properties["review_flags"] = datasheet.review_flags

    return KGNode(
        id=node_id,
        node_type=KGNodeType.COMPONENT_INSTANCE,
        layer=3,
        label=datasheet.component_id,
        properties=properties,
        source=datasheet.source_pdf_hash,
        confidence=datasheet.extraction_confidence,
        extraction_method=datasheet.extraction_method,
        created_at=now,
    )


def _create_pin_nodes(
    datasheet: ComponentDatasheet,
    now: str,
) -> list[KGNode]:
    """Create KG-3 Pin nodes from PinDefinitions.

    Args:
        datasheet: Source ComponentDatasheet
        now: ISO timestamp for created_at

    Returns:
        List of KGNode objects for pins (Layer 3)
    """
    nodes = []
    for pin in datasheet.pins:
        node_id = f"pin:{datasheet.component_id}:{pin.pin_number}"

        properties: dict[str, Any] = {
            "pin_number": pin.pin_number,
            "raw_name": pin.raw_name,
        }

        # Only add normalized_function if present
        if pin.normalized_function is not None:
            properties["normalized_function"] = pin.normalized_function

        if pin.default_function:
            properties["default_function"] = pin.default_function

        if pin.alternate_functions:
            # Structured AFs as plain dicts (JSON-serializable KG property values)
            properties["alternate_functions"] = [
                af.model_dump() for af in pin.alternate_functions
            ]

        if pin.pin_role is not None:
            properties["pin_role"] = pin.pin_role.value

        if pin.pin_type is not None:
            properties["pin_type"] = pin.pin_type

        if pin.description:
            properties["description"] = pin.description

        node = KGNode(
            id=node_id,
            node_type=KGNodeType.PIN,
            layer=3,
            label=pin.raw_name or f"Pin {pin.pin_number}",
            properties=properties,
            source=datasheet.source_pdf_hash,
            confidence=PIN_CONFIDENCE,
            extraction_method=datasheet.extraction_method,
            created_at=now,
        )
        nodes.append(node)

    return nodes


def _create_electrical_property_nodes(
    datasheet: ComponentDatasheet,
    now: str,
) -> list[KGNode]:
    """Create KG-3 ElectricalProperty nodes from ElectricalParameters.

    Args:
        datasheet: Source ComponentDatasheet
        now: ISO timestamp for created_at

    Returns:
        List of KGNode objects for electrical properties (Layer 3)
    """
    nodes = []
    for param in datasheet.electrical_parameters:
        # Skip if symbol is missing
        symbol = param.symbol or "unknown"
        section = param.section_type.value if param.section_type else "unknown"

        node_id = f"property:{datasheet.component_id}:{symbol}:{section}"

        # Build properties from ExtractedValue
        properties: dict[str, Any] = {
            "section_type": section,
        }
        if param.symbol is not None:
            properties["symbol"] = param.symbol
        if param.conditions is not None:
            properties["conditions"] = param.conditions

        if param.value:
            if param.value.min_val is not None:
                properties["min_val"] = param.value.min_val
            if param.value.typ_val is not None:
                properties["typ_val"] = param.value.typ_val
            if param.value.max_val is not None:
                properties["max_val"] = param.value.max_val
            if param.value.unit:
                properties["unit"] = param.value.unit

        # Determine confidence from the parameter value
        confidence = (
            param.value.confidence
            if param.value and param.value.confidence is not None
            else datasheet.extraction_confidence
        )

        node = KGNode(
            id=node_id,
            node_type=KGNodeType.ELECTRICAL_PROPERTY,
            layer=3,
            label=f"{param.parameter_name} ({symbol})" if param.parameter_name else symbol,
            properties=properties,
            source=datasheet.source_pdf_hash,
            confidence=confidence,
            extraction_method=datasheet.extraction_method,
            created_at=now,
        )
        nodes.append(node)

    return nodes


def _create_placement_rule_nodes(
    datasheet: ComponentDatasheet,
    now: str,
) -> list[KGNode]:
    """Create KG-4 PlacementRule nodes from PlacementConstraints.

    Args:
        datasheet: Source ComponentDatasheet
        now: ISO timestamp for created_at

    Returns:
        List of KGNode objects for placement rules (Layer 4)
    """
    nodes = []
    constraints = datasheet.layout_constraints or []

    for i, constraint in enumerate(constraints):
        node_id = f"placement_rule:{datasheet.component_id}:{i}"

        properties: dict[str, Any] = {
            "constraint_type": constraint.constraint_type,
            "subject": constraint.subject,
            "relative_to": constraint.relative_to,
            "relative_to_type": constraint.relative_to_type,
            "hard": constraint.hard,
        }

        if constraint.max_distance_mm is not None:
            properties["max_distance_mm"] = constraint.max_distance_mm
        if constraint.min_distance_mm is not None:
            properties["min_distance_mm"] = constraint.min_distance_mm
        if constraint.layer is not None:
            properties["layer"] = constraint.layer
        if constraint.source_sentence:
            properties["source_sentence"] = constraint.source_sentence

        node = KGNode(
            id=node_id,
            node_type=KGNodeType.PLACEMENT_RULE,
            layer=4,
            label=f"{constraint.constraint_type}: {constraint.subject} → {constraint.relative_to}",
            properties=properties,
            source=datasheet.source_pdf_hash,
            confidence=constraint.confidence,
            extraction_method=datasheet.extraction_method,
            created_at=now,
        )
        nodes.append(node)

    return nodes


def _create_component_to_pin_edges(
    datasheet: ComponentDatasheet,
) -> list[KGEdge]:
    """Create HAS_PROPERTY edges from ComponentInstance to Pin nodes.

    Args:
        datasheet: Source ComponentDatasheet

    Returns:
        List of KGEdge objects connecting component to pins
    """
    edges = []
    component_id = f"component_instance:{datasheet.component_id}"

    for pin in datasheet.pins:
        pin_id = f"pin:{datasheet.component_id}:{pin.pin_number}"

        edge = KGEdge(
            source_id=component_id,
            relation=KGRelation.HAS_PROPERTY,
            target_id=pin_id,
            source_document=datasheet.source_pdf_hash,
            confidence=PIN_CONFIDENCE,
            layer=3,
        )
        edges.append(edge)

    return edges


def _create_component_to_property_edges(
    datasheet: ComponentDatasheet,
) -> list[KGEdge]:
    """Create HAS_PROPERTY edges from ComponentInstance to ElectricalProperty nodes.

    Args:
        datasheet: Source ComponentDatasheet

    Returns:
        List of KGEdge objects connecting component to electrical properties
    """
    edges = []
    component_id = f"component_instance:{datasheet.component_id}"

    for param in datasheet.electrical_parameters:
        symbol = param.symbol or "unknown"
        section = param.section_type.value if param.section_type else "unknown"
        property_id = f"property:{datasheet.component_id}:{symbol}:{section}"

        # Determine confidence from the parameter value
        confidence = (
            param.value.confidence
            if param.value and param.value.confidence is not None
            else datasheet.extraction_confidence
        )

        edge = KGEdge(
            source_id=component_id,
            relation=KGRelation.HAS_PROPERTY,
            target_id=property_id,
            source_document=datasheet.source_pdf_hash,
            confidence=confidence,
            layer=3,
        )
        edges.append(edge)

    return edges


def _create_component_to_rule_edges(
    datasheet: ComponentDatasheet,
) -> list[KGEdge]:
    """Create GOVERNED_BY edges from ComponentInstance to PlacementRule nodes.

    Args:
        datasheet: Source ComponentDatasheet

    Returns:
        List of KGEdge objects connecting component to placement rules
    """
    edges = []
    component_id = f"component_instance:{datasheet.component_id}"
    constraints = datasheet.layout_constraints or []

    for i, constraint in enumerate(constraints):
        rule_id = f"placement_rule:{datasheet.component_id}:{i}"

        edge = KGEdge(
            source_id=component_id,
            relation=KGRelation.GOVERNED_BY,
            target_id=rule_id,
            source_document=datasheet.source_pdf_hash,
            confidence=constraint.confidence,
            layer=4,
        )
        edges.append(edge)

    return edges


def import_datasheet(
    datasheet: ComponentDatasheet,
    graph: KnowledgeGraph,
    config: Config,
) -> ImportResult:
    """Import one ComponentDatasheet into KG-3 and KG-4.

    Idempotent: running twice on same datasheet updates, does not duplicate.
    Never raises — catches all exceptions and logs them to ImportResult.import_errors.

    Creates the following nodes:
    - 1 ComponentInstance node (Layer 3)
    - N Pin nodes (Layer 3, one per pin)
    - M ElectricalProperty nodes (Layer 3, one per electrical parameter)
    - P PlacementRule nodes (Layer 4, one per placement constraint)

    Creates the following edges:
    - ComponentInstance → Pin (HAS_PROPERTY, Layer 3)
    - ComponentInstance → ElectricalProperty (HAS_PROPERTY, Layer 3)
    - ComponentInstance → PlacementRule (GOVERNED_BY, Layer 4)

    Args:
        datasheet: ComponentDatasheet to import
        graph: KnowledgeGraph to add nodes/edges to
        config: Application configuration

    Returns:
        ImportResult with counts and any errors encountered

    Example:
        >>> result = import_datasheet(datasheet, graph, config)
        >>> result.success
        True
        >>> result.nodes_created
        12
    """
    component_id = datasheet.component_id or "unknown"
    now = _now_iso()

    result = ImportResult(component_id=component_id)
    nodes_to_add: list[KGNode] = []
    edges_to_add: list[KGEdge] = []

    try:
        logger.info(f"Importing datasheet for component: {component_id}")

        # Create ComponentInstance node (Layer 3)
        component_node = _create_component_instance_node(datasheet, now)
        nodes_to_add.append(component_node)

        # Check for duplicate (idempotency tracking)
        if graph.node_exists(component_node.id):
            result.skipped_duplicates += 1
            logger.debug(f"Component node exists (will update): {component_node.id}")

        # Create Pin nodes (Layer 3)
        pin_nodes = _create_pin_nodes(datasheet, now)
        for node in pin_nodes:
            if graph.node_exists(node.id):
                result.skipped_duplicates += 1
            nodes_to_add.append(node)

        # Create ElectricalProperty nodes (Layer 3)
        property_nodes = _create_electrical_property_nodes(datasheet, now)
        for node in property_nodes:
            if graph.node_exists(node.id):
                result.skipped_duplicates += 1
            nodes_to_add.append(node)

        # Create PlacementRule nodes (Layer 4)
        rule_nodes = _create_placement_rule_nodes(datasheet, now)
        for node in rule_nodes:
            if graph.node_exists(node.id):
                result.skipped_duplicates += 1
            nodes_to_add.append(node)
        result.placement_rules_imported = len(rule_nodes)

        # Create edges (Component → Pin)
        pin_edges = _create_component_to_pin_edges(datasheet)
        edges_to_add.extend(pin_edges)

        # Create edges (Component → ElectricalProperty)
        property_edges = _create_component_to_property_edges(datasheet)
        edges_to_add.extend(property_edges)

        # Create edges (Component → PlacementRule)
        rule_edges = _create_component_to_rule_edges(datasheet)
        edges_to_add.extend(rule_edges)

        # Add all nodes to graph (updates in place for duplicates)
        for node in nodes_to_add:
            try:
                graph.add_node(node)
                result.nodes_created += 1
            except Exception as e:
                error_msg = f"Failed to add node {node.id}: {e}"
                logger.warning(error_msg)
                result.import_errors.append(error_msg)

        # Add all edges to graph
        for edge in edges_to_add:
            try:
                graph.add_edge(edge)
                result.edges_created += 1
            except Exception as e:
                error_msg = f"Failed to add edge {edge.source_id} → {edge.target_id}: {e}"
                logger.warning(error_msg)
                result.import_errors.append(error_msg)

        logger.info(
            f"Imported {component_id}: {result.nodes_created} nodes, "
            f"{result.edges_created} edges, {result.skipped_duplicates} duplicates"
        )

        # Success if we created at least the component node
        result.success = result.nodes_created > 0 and len(result.import_errors) == 0

    except Exception as e:
        error_msg = f"Critical error importing {component_id}: {e}"
        logger.error(error_msg)
        result.import_errors.append(error_msg)
        result.success = False

    return result


def import_batch(
    datasheets: list[ComponentDatasheet],
    graph: KnowledgeGraph,
    config: Config,
) -> BatchImportResult:
    """Import multiple datasheets. Continues on individual failures.

    Processes each ComponentDatasheet independently. If one import fails,
    continues with the remaining datasheets.

    Args:
        datasheets: List of ComponentDatasheets to import
        graph: KnowledgeGraph to add nodes/edges to
        config: Application configuration

    Returns:
        BatchImportResult with aggregated statistics across all imports

    Example:
        >>> results = import_batch([ds1, ds2, ds3], graph, config)
        >>> results.successful
        2
        >>> results.failed
        1
    """
    total = len(datasheets)
    logger.info(f"Starting batch import of {total} datasheets")

    batch_result = BatchImportResult(total_datasheets=total)

    for datasheet in datasheets:
        try:
            result = import_datasheet(datasheet, graph, config)
            batch_result.results.append(result)

            if result.success:
                batch_result.successful += 1
                batch_result.total_nodes_created += result.nodes_created
                batch_result.total_edges_created += result.edges_created
            else:
                batch_result.failed += 1

        except Exception as e:
            # This should rarely happen since import_datasheet catches exceptions
            # But we handle it to ensure batch continues
            error_msg = f"Unexpected error in batch import: {e}"
            logger.error(error_msg)

            failed_result = ImportResult(
                component_id=getattr(datasheet, "component_id", "unknown"),
                success=False,
                import_errors=[error_msg],
            )
            batch_result.results.append(failed_result)
            batch_result.failed += 1

    logger.info(
        f"Batch import complete: {batch_result.successful}/{total} successful, "
        f"{batch_result.total_nodes_created} total nodes, "
        f"{batch_result.total_edges_created} total edges"
    )

    return batch_result
