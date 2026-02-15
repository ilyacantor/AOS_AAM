"""
Preset/seed data admin operations
"""
import json
from collections import defaultdict
from typing import Optional

from . import supabase_client as sb


TABLE_PK_MAP = {
    "drift_events": "drift_id",
    "pipe_versions": "version_id",
    "declared_pipes": "pipe_id",
    "observations": "observation_id",
    "collector_runs": "run_id",
    "connection_candidates": "candidate_id",
    "tee_requests": "tee_id",
    "fabric_planes": "plane_id",
    "sor_declarations": "sor_id",
    "sor_dispositions": "disposition_id",
    "aod_policy_manifest": "policy_id",
    "aod_handoff_log": "handoff_id",
}

ALLOWED_TABLES = frozenset(TABLE_PK_MAP.keys())


def reset_aod_state():
    """
    Clear candidate/fabric/SOR data so a fresh handoff can repopulate it.

    Preserves collectors (infrastructure config) only.
    The handoff log must be cleared because process_handoff() uses it for
    idempotency checks — a stale log entry would short-circuit re-ingestion.
    """
    counts = {}
    for table in ALLOWED_TABLES:
        rows = sb.select(table)
        counts[table] = len(rows) if isinstance(rows, list) else 0
        if counts[table] > 0:
            pk = TABLE_PK_MAP[table]
            sb.delete(table, raw_params={pk: "not.is.null"})

    total_deleted = sum(counts.values())
    return {"reset": True, "tables_cleared": counts, "total_rows_deleted": total_deleted}


def clear_all_data():
    """Alias for reset_aod_state — clears repopulated tables."""
    return reset_aod_state()


def get_pipe_stats() -> dict:
    """Get statistics about pipes by fabric_plane and modality.

    Queries connection_candidates (the single source of truth) instead of
    declared_pipes.
    """
    stats = {
        "total_pipes": 0,
        "by_fabric_plane": {},
        "by_modality": {},
        "by_source_system": {}
    }

    candidates = sb.select("connection_candidates")
    planes = sb.select("fabric_planes")

    planes_dict = {p["plane_id"]: p for p in planes}

    stats["total_pipes"] = len(candidates)

    by_plane: dict[str, int] = defaultdict(int)
    by_modality: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)

    for c in candidates:
        fpid = c.get("fabric_plane_id")
        if fpid and fpid in planes_dict:
            plane_label = (planes_dict[fpid].get("plane_type") or "UNMAPPED").upper()
        elif c.get("connected_via_plane"):
            plane_label = c["connected_via_plane"].upper()
        else:
            plane_label = "UNMAPPED"
        by_plane[plane_label] += 1

        cat = c.get("category") or "unknown"
        by_modality[cat] += 1

        vendor = c.get("vendor_name") or "unknown"
        by_source[vendor] += 1

    stats["by_fabric_plane"] = dict(by_plane)
    stats["by_modality"] = dict(by_modality)
    stats["by_source_system"] = dict(by_source)

    return stats
