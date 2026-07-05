"""Typed schemas for parameterized topology relationships.

ScalingLaw is serialized into KGEdge.constraints (dict[str, Any]) under the
key "scaling_laws" — no KGEdge schema change is needed, and the payload maps
cleanly onto the Neo4j design's constraints_json property
(NEO4J_BACKEND_DESIGN.md §1.2).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Key under which serialized ScalingLaw dicts live in KGEdge.constraints
SCALING_LAWS_KEY = "scaling_laws"


class ScalingLaw(BaseModel):
    """A parameterized relationship between a design parameter and a
    functional block's property.

    Example (Buck Converter switching loop):
        ScalingLaw(
            parameter="switching_frequency_hz",
            affects="loop_area_mm2",
            direction="inverse",
            rationale="Higher f_sw reduces required inductance and loop area",
        )
    """

    model_config = ConfigDict(extra="forbid")

    parameter: str = Field(
        description="Design parameter driving the relationship (snake_case, with unit suffix)"
    )
    affects: str = Field(
        description="Block property affected (snake_case, with unit suffix)"
    )
    direction: Literal["proportional", "inverse"] = Field(
        description="proportional: affects grows with parameter; inverse: shrinks"
    )
    exponent: float = Field(
        default=1.0,
        description="Power-law exponent: affects ∝ parameter**(±exponent)",
    )
    condition: Optional[str] = Field(
        default=None,
        description="Applicability condition, if any (e.g. 'continuous conduction mode')",
    )
    rationale: str = Field(
        description="One-sentence engineering justification",
    )

    def to_constraint_entry(self) -> dict:
        """Serialize for storage in KGEdge.constraints[SCALING_LAWS_KEY]."""
        return self.model_dump()

    @classmethod
    def list_from_edge_constraints(cls, constraints: dict) -> list["ScalingLaw"]:
        """Deserialize all scaling laws from a KGEdge.constraints dict.

        Returns empty list if the key is absent or malformed — never raises.
        """
        raw = constraints.get(SCALING_LAWS_KEY)
        if not isinstance(raw, list):
            return []
        laws: list[ScalingLaw] = []
        for entry in raw:
            try:
                laws.append(cls.model_validate(entry))
            except Exception:
                continue
        return laws
