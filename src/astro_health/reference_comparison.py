# Made in cooperation with ChatGPT
# File: src/astro_health/reference_comparison.py
"""Optional mechanical comparison with EXTERNALLY SOURCED offline JSON rules.

No thresholds are bundled. Nothing here assesses safety, diagnoses disease,
sets Reading.quality='ok', or establishes clinical validity. Context-specific
medical decisions require independently reviewed source criteria later.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from astro_health.fixed_tests import FIELDS_BY_MEASUREMENT
from astro_health.models import Reading


class ReferenceError(ValueError):
    """Reference JSON missing required provenance or containing bad units."""


@dataclass(frozen=True)
class ReferenceRule:
    measurement_type: str
    unit: str
    lower: float | None
    upper: float | None
    source: str
    context: str


@dataclass(frozen=True)
class Comparison:
    measurement_type: str
    value: float
    unit: str
    status: str  # no_reference, within_reference_range, outside_reference_range
    source: str | None = None
    context: str | None = None


def load_reference_rules(path: str | Path) -> dict[str, ReferenceRule]:
    """Load and validate JSON bounds; provenance is mandatory.

    Missing values signify an open bound, not a guessed number. No rule may
    target a field outside the fixed catalog or use incompatible units.
    """
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReferenceError(f"Cannot read reference JSON: {exc}") from exc
    if not isinstance(obj, dict) or obj.get("schema_version") != 1:
        raise ReferenceError("reference schema_version must be 1")
    entries = obj.get("rules")
    if not isinstance(entries, list):
        raise ReferenceError("rules must be a list")
    rules = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReferenceError("Rule must be an object")
        name = entry.get("measurement_type")
        if not isinstance(name, str):
            raise ReferenceError("measurement_type must be a string")
        definition = FIELDS_BY_MEASUREMENT.get(name)
        if definition is None or entry.get("unit") != definition.unit:
            raise ReferenceError(f"Unknown measurement or incompatible unit: {name}")
        if name in rules:
            raise ReferenceError(f"Duplicate rule: {name}")
        lower, upper = entry.get("lower"), entry.get("upper")
        if lower is None and upper is None:
            raise ReferenceError("Rule requires at least one numeric bound")
        for bound in (lower, upper):
            if bound is not None and (
                isinstance(bound, bool)
                or not isinstance(bound, (int, float))
                or not math.isfinite(bound)
            ):
                raise ReferenceError("Bounds must be finite numbers or null")
        if lower is not None and upper is not None and lower > upper:
            raise ReferenceError("Lower bound exceeds upper bound")
        source, context = entry.get("source"), entry.get("context")
        if not all(isinstance(x, str) and x.strip() for x in (source, context)):
            raise ReferenceError("Each rule requires source and context")
        rules[name] = ReferenceRule(name, definition.unit, lower, upper, source, context)
    return rules


def compare_reading(reading: Reading, rules: dict[str, ReferenceRule]) -> tuple[Comparison, ...]:
    """Compare numeric readings; return statuses without medical inference."""
    results = []
    for measurement in reading.measurements:
        rule = rules.get(measurement.measurement_type)
        if (reading.quality == "invalid" or rule is None
                or measurement.unit != rule.unit):
            results.append(Comparison(
                measurement.measurement_type, measurement.value,
                measurement.unit, "no_reference",
            ))
            continue
        within = ((rule.lower is None or measurement.value >= rule.lower)
                  and (rule.upper is None or measurement.value <= rule.upper))
        results.append(Comparison(
            measurement.measurement_type, measurement.value,
            measurement.unit,
            "within_reference_range" if within else "outside_reference_range",
            source=rule.source, context=rule.context,
        ))
    return tuple(results)
