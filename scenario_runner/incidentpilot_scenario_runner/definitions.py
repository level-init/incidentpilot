"""Load scenario YAML definitions (N9+). Never reads GroundTruth."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS_DIR = _ROOT / "scenarios" / "definitions"


@dataclass(frozen=True)
class ScenarioDefinition:
    key: str
    title: str
    injector_id: str
    autonomy_level: int = 2
    harness: str = "level2"
    origin_service: str = "payment"
    symptom_services: tuple[str, ...] = ()
    expected_action_types: tuple[str, ...] = ()
    expected_severity: str | None = None
    expected_hypothesis_class: str | None = None
    ground_truth_key: str | None = None
    # Optional domain.change seed for root_cause change_recall (e.g. DEPLOYMENT).
    seed_change_type: str | None = None
    action_parameters: dict[str, Any] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def gt_key(self) -> str:
        return self.ground_truth_key or self.key

    @property
    def primary_action_type(self) -> str:
        if self.expected_action_types:
            return self.expected_action_types[0]
        return "ROLLBACK_DEPLOYMENT"


def _parse(doc: dict[str, Any]) -> ScenarioDefinition:
    key = str(doc["key"]).strip()
    aliases = tuple(str(a).strip() for a in (doc.get("aliases") or []) if str(a).strip())
    symptoms = tuple(str(s).strip() for s in (doc.get("symptom_services") or []) if str(s).strip())
    actions = tuple(
        str(a).strip() for a in (doc.get("expected_action_types") or []) if str(a).strip()
    )
    params = doc.get("action_parameters")
    action_parameters = dict(params) if isinstance(params, dict) else {}
    seed = doc.get("seed_change_type")
    seed_change_type = str(seed).strip() if seed else None
    return ScenarioDefinition(
        key=key,
        title=str(doc.get("title") or key),
        injector_id=str(doc.get("injector_id") or key),
        autonomy_level=int(doc.get("autonomy_level") or 2),
        harness=str(doc.get("harness") or "level2"),
        origin_service=str(doc.get("origin_service") or "payment"),
        symptom_services=symptoms,
        expected_action_types=actions,
        expected_severity=(str(doc["expected_severity"]) if doc.get("expected_severity") else None),
        expected_hypothesis_class=(
            str(doc["expected_hypothesis_class"]) if doc.get("expected_hypothesis_class") else None
        ),
        ground_truth_key=(str(doc["ground_truth_key"]) if doc.get("ground_truth_key") else None),
        seed_change_type=seed_change_type,
        action_parameters=action_parameters,
        aliases=aliases,
        notes=str(doc.get("notes") or "").strip(),
        raw=dict(doc),
    )


def list_definition_paths(*, directory: Path | None = None) -> list[Path]:
    root = directory or DEFINITIONS_DIR
    if not root.is_dir():
        return []
    return sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml"))


def load_all_definitions(*, directory: Path | None = None) -> list[ScenarioDefinition]:
    out: list[ScenarioDefinition] = []
    for path in list_definition_paths(directory=directory):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or "key" not in doc:
            raise ValueError(f"invalid scenario definition: {path}")
        out.append(_parse(doc))
    return out


def resolve_scenario_name(name: str, *, directory: Path | None = None) -> ScenarioDefinition:
    """Resolve catalog key or alias (e.g. bad-deployment → bad_deploy)."""
    needle = name.strip().lower().replace(" ", "_")
    defs = load_all_definitions(directory=directory)
    for d in defs:
        candidates = {d.key.lower(), *(a.lower().replace(" ", "_") for a in d.aliases)}
        # Also accept hyphen/underscore swaps.
        expanded: set[str] = set()
        for c in candidates:
            expanded.add(c)
            expanded.add(c.replace("-", "_"))
            expanded.add(c.replace("_", "-"))
        if needle in expanded or needle.replace("-", "_") in expanded:
            return d
    known = ", ".join(sorted({d.key for d in defs})) or "(none)"
    raise KeyError(f"unknown scenario {name!r}; known keys: {known}")
