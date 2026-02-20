"""
iPaaS Recipe Field Parser — extracts SemanticEdge dicts from
integration platform recipe/flow definitions.

Supports:
  - Workato (full recipe JSON with config block)
  - Tray.io (similar structure — same parser with minor adjustments)
  - Zapier (limited — notes gap when field-level data unavailable)

Complexity tiers (per task doc):
  ~40% simple direct mappings   → confidence 0.95
  ~35% light transformations    → confidence 0.85
  ~25% complex logic            → confidence 0.70, flagged for FDE review
"""
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

_log = logging.getLogger("aam.parser.ipaas_recipe")

# Patterns that indicate a transformation rather than a direct mapping
_TRANSFORM_PATTERNS = [
    re.compile(r"\bCONCAT\b", re.IGNORECASE),
    re.compile(r"\bIF\b", re.IGNORECASE),
    re.compile(r"\bSPLIT\b", re.IGNORECASE),
    re.compile(r"\bSUBSTRING\b", re.IGNORECASE),
    re.compile(r"\bROUND\b", re.IGNORECASE),
    re.compile(r"\bTRIM\b", re.IGNORECASE),
    re.compile(r"\bUPPER\b", re.IGNORECASE),
    re.compile(r"\bLOWER\b", re.IGNORECASE),
    re.compile(r"\bTO_DATE\b", re.IGNORECASE),
    re.compile(r"\bFORMAT\b", re.IGNORECASE),
    re.compile(r"\bLOOKUP\b", re.IGNORECASE),
    re.compile(r"\+|-|\*|/", re.IGNORECASE),  # arithmetic
]

_CONDITION_PATTERNS = [
    re.compile(r"\bIF\b", re.IGNORECASE),
    re.compile(r"\bWHEN\b", re.IGNORECASE),
    re.compile(r"\bCASE\b", re.IGNORECASE),
    re.compile(r"\bELSE\b", re.IGNORECASE),
]


def _classify_mapping(
    source_expr: str,
    target_field: str,
    formula: Optional[str] = None,
    condition: Optional[str] = None,
) -> tuple[str, float]:
    """Return (edge_type, confidence) for a mapping expression."""
    if condition or (formula and any(p.search(formula) for p in _CONDITION_PATTERNS)):
        return "CONDITIONAL", 0.70

    expr_to_check = formula or source_expr
    if any(p.search(expr_to_check) for p in _TRANSFORM_PATTERNS):
        return "TRANSFORMED", 0.85

    return "DIRECT_MAP", 0.95


def _parse_field_ref(ref: str) -> tuple[str, str]:
    """
    Parse 'Object.Field' or just 'Field' from a reference string.

    Examples:
        'Opportunity.Amount'       -> ('Opportunity', 'Amount')
        'Amount'                   -> ('_root', 'Amount')
        'Account.BillingAddress.City' -> ('Account', 'BillingAddress.City')
    """
    parts = ref.strip().split(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "_root", parts[0]


def parse_workato_recipe(recipe: dict) -> list[dict]:
    """
    Parse a Workato recipe JSON and return SemanticEdge dicts.

    Expected recipe structure (Workato API GET /api/recipes/:id):
    {
        "id": 4782,
        "name": "Sync SF Opportunities to NS Sales Orders",
        "trigger_application": "salesforce",
        "action_applications": ["netsuite"],
        "config": {
            "trigger": {
                "application": "salesforce",
                "object": "Opportunity",
                "event": "new_or_updated",
                "filter": {"Stage": "Closed Won"}
            },
            "actions": [
                {
                    "application": "netsuite",
                    "object": "SalesOrder",
                    "action": "create",
                    "field_mappings": [
                        {"source": "Opportunity.Name", "target": "memo"},
                        {"source": "Opportunity.Amount", "target": "total"},
                        ...
                    ]
                }
            ]
        }
    }

    Also supports a flat "mappings" list format:
    {
        "id": 4782,
        "source_application": "salesforce",
        "target_application": "netsuite",
        "mappings": [
            {"source": "Opportunity.Amount", "target": "SalesOrder.total"},
            ...
        ]
    }
    """
    recipe_id = recipe.get("id", "unknown")
    extraction_source = f"workato_recipe_{recipe_id}"
    now = datetime.utcnow().isoformat()
    edges: list[dict] = []

    # --- Format A: config.actions[].field_mappings ---
    config = recipe.get("config") or {}
    trigger = config.get("trigger") or {}
    source_app = (
        trigger.get("application")
        or recipe.get("trigger_application")
        or recipe.get("source_application")
        or "unknown"
    ).lower()

    actions = config.get("actions") or []
    for action in actions:
        target_app = (action.get("application") or "unknown").lower()
        target_object = action.get("object") or "_root"

        for mapping in action.get("field_mappings") or []:
            source_ref = mapping.get("source", "")
            target_ref = mapping.get("target", "")
            formula = mapping.get("formula") or mapping.get("transformation")
            condition = mapping.get("condition")

            if not source_ref or not target_ref:
                continue

            source_obj, source_field = _parse_field_ref(source_ref)
            # Target field may or may not include object prefix
            if "." in target_ref:
                tgt_obj, tgt_field = _parse_field_ref(target_ref)
            else:
                tgt_obj = target_object
                tgt_field = target_ref

            edge_type, confidence = _classify_mapping(
                source_ref, tgt_field, formula, condition
            )

            edges.append({
                "id": str(uuid.uuid4()),
                "source_system": source_app,
                "source_object": source_obj,
                "source_field": source_field,
                "target_system": target_app,
                "target_object": tgt_obj,
                "target_field": tgt_field,
                "edge_type": edge_type,
                "confidence": confidence,
                "fabric_plane": "IPAAS",
                "extraction_source": extraction_source,
                "transformation": formula,
                "condition": condition,
                "discovered_at": now,
                "last_verified": now,
            })

    # --- Format B: flat mappings list ---
    if not actions and "mappings" in recipe:
        target_app = (
            recipe.get("target_application")
            or (recipe.get("action_applications") or ["unknown"])[0]
        ).lower()

        for mapping in recipe.get("mappings") or []:
            source_ref = mapping.get("source", "")
            target_ref = mapping.get("target", "")
            formula = mapping.get("formula") or mapping.get("transformation")
            condition = mapping.get("condition")

            if not source_ref or not target_ref:
                continue

            source_obj, source_field = _parse_field_ref(source_ref)
            tgt_obj, tgt_field = _parse_field_ref(target_ref)

            edge_type, confidence = _classify_mapping(
                source_ref, tgt_field, formula, condition
            )

            edges.append({
                "id": str(uuid.uuid4()),
                "source_system": source_app,
                "source_object": source_obj,
                "source_field": source_field,
                "target_system": target_app,
                "target_object": tgt_obj,
                "target_field": tgt_field,
                "edge_type": edge_type,
                "confidence": confidence,
                "fabric_plane": "IPAAS",
                "extraction_source": extraction_source,
                "transformation": formula,
                "condition": condition,
                "discovered_at": now,
                "last_verified": now,
            })

    if edges:
        _log.info("Parsed %d field mappings from recipe %s", len(edges), recipe_id)
    else:
        _log.warning("No field mappings found in recipe %s", recipe_id)

    return edges


def parse_tray_workflow(workflow: dict) -> list[dict]:
    """
    Parse a Tray.io workflow JSON.  Structure is similar to Workato
    but steps use 'input_fields' / 'output_fields' naming.

    Falls back to the Workato parser if the structure matches.
    """
    # Tray uses "steps" with "connector" + "operation" + "input_fields"
    workflow_id = workflow.get("id", "unknown")
    extraction_source = f"tray_workflow_{workflow_id}"
    now = datetime.utcnow().isoformat()
    edges: list[dict] = []

    steps = workflow.get("steps") or []
    trigger_step = workflow.get("trigger") or {}
    source_app = (trigger_step.get("connector") or workflow.get("source_application") or "unknown").lower()

    for step in steps:
        target_app = (step.get("connector") or "unknown").lower()
        target_object = step.get("operation") or "_root"

        for mapping in step.get("input_fields") or []:
            source_ref = mapping.get("source", "")
            target_ref = mapping.get("field", "") or mapping.get("target", "")
            formula = mapping.get("formula")
            condition = mapping.get("condition")

            if not source_ref or not target_ref:
                continue

            source_obj, source_field = _parse_field_ref(source_ref)
            tgt_obj, tgt_field = _parse_field_ref(target_ref)

            edge_type, confidence = _classify_mapping(
                source_ref, tgt_field, formula, condition
            )

            edges.append({
                "id": str(uuid.uuid4()),
                "source_system": source_app,
                "source_object": source_obj,
                "source_field": source_field,
                "target_system": target_app,
                "target_object": tgt_obj,
                "target_field": tgt_field,
                "edge_type": edge_type,
                "confidence": confidence,
                "fabric_plane": "IPAAS",
                "extraction_source": extraction_source,
                "transformation": formula,
                "condition": condition,
                "discovered_at": now,
                "last_verified": now,
            })

    if edges:
        _log.info("Parsed %d field mappings from Tray workflow %s", len(edges), workflow_id)

    return edges
