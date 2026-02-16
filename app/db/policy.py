"""
AOD policy manifest operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb
from .candidates import _row_to_candidate


def save_policy_manifest(policy_data: dict) -> dict:
    """Save or update the AOD policy manifest"""
    policy_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    sb.update(
        "aod_policy_manifest",
        {"is_active": False},
        filters={"is_active": True},
    )

    sb.insert("aod_policy_manifest", {
        "policy_id": policy_id,
        "policy_version": policy_data["policy_version"],
        "governance_rules": json.dumps(policy_data.get("governance_rules", [])),
        "blocking_finding_types": json.dumps(policy_data.get("blocking_finding_types", [])),
        "fabric_plane_routing": json.dumps(policy_data.get("fabric_plane_routing", {})),
        "auto_provision_categories": json.dumps(policy_data.get("auto_provision_categories", [])),
        "require_human_review": json.dumps(policy_data.get("require_human_review", [])),
        "is_active": True,
        "received_at": now,
        "updated_at": now,
    })

    return {
        "policy_id": policy_id,
        "policy_version": policy_data["policy_version"],
        "is_active": True,
        "received_at": now,
    }


def get_active_policy_manifest() -> Optional[dict]:
    """Get the currently active AOD policy manifest"""
    row = sb.select(
        "aod_policy_manifest",
        raw_params={"is_active": "eq.true"},
        single=True,
    )

    if row:
        return {
            "policy_id": row["policy_id"],
            "policy_version": row["policy_version"],
            "governance_rules": json.loads(row["governance_rules"]) if row["governance_rules"] else [],
            "blocking_finding_types": json.loads(row["blocking_finding_types"]) if row["blocking_finding_types"] else [],
            "fabric_plane_routing": json.loads(row["fabric_plane_routing"]) if row["fabric_plane_routing"] else {},
            "auto_provision_categories": json.loads(row["auto_provision_categories"]) if row["auto_provision_categories"] else [],
            "require_human_review": json.loads(row["require_human_review"]) if row["require_human_review"] else [],
            "is_active": True,
            "received_at": row["received_at"],
            "updated_at": row["updated_at"],
        }
    return None


def list_policy_manifests(limit: int = 20) -> list[dict]:
    """List all policy manifests (history)"""
    rows = sb.select(
        "aod_policy_manifest",
        order="received_at.desc",
        limit=limit,
    )

    return [{
        "policy_id": row["policy_id"],
        "policy_version": row["policy_version"],
        "is_active": bool(row["is_active"]),
        "received_at": row["received_at"],
        "updated_at": row["updated_at"],
    } for row in rows]


def get_candidates_by_aod_run(aod_run_id: str) -> list[dict]:
    """Get all candidates from a specific AOD run"""
    rows = sb.select(
        "connection_candidates",
        filters={"aod_run_id": aod_run_id},
        order="created_at.desc",
    )

    return [_row_to_candidate(row) for row in rows]
