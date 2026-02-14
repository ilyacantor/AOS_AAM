"""
AOD reconciliation operations.

Decomposed into focused sub-functions, each handling one reconciliation
concern.  The top-level get_aod_reconciliation() orchestrates them.
"""
import json
from typing import Optional

from .connection import get_connection
from ..constants import SOR_CATEGORIES


# ---------------------------------------------------------------------------
# Sub-function 1: Handoff summary + basic counts
# ---------------------------------------------------------------------------

def _get_handoff_summary(cursor, aod_run_id: str) -> Optional[dict]:
    """Return handoff log row, basic counts, and top-vendor breakdown."""
    cursor.execute("""
        SELECT candidates_received, candidates_accepted, handoff_timestamp,
               snapshot_name
        FROM aod_handoff_log
        WHERE aod_run_id = ?
        ORDER BY handoff_timestamp DESC LIMIT 1
    """, (aod_run_id,))
    handoff_row = cursor.fetchone()
    if not handoff_row:
        return None

    cursor.execute(
        "SELECT COUNT(*) FROM connection_candidates WHERE aod_run_id = ?",
        (aod_run_id,))
    candidates_stored = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM fabric_planes WHERE aod_run_id = ?",
        (aod_run_id,))
    fabric_planes_stored = cursor.fetchone()[0]

    sor_categories = list(SOR_CATEGORIES)
    placeholders = ",".join("?" * len(sor_categories))
    cursor.execute(f"""
        SELECT COUNT(*) FROM connection_candidates
        WHERE aod_run_id = ? AND LOWER(category) IN ({placeholders})
    """, (aod_run_id, *sor_categories))
    sors_stored = cursor.fetchone()[0]

    # Count linked candidates per plane type (not plane records, which is always 1)
    cursor.execute("""
        SELECT fp.plane_type, COUNT(c.candidate_id)
        FROM fabric_planes fp
        LEFT JOIN connection_candidates c ON c.fabric_plane_id = fp.plane_id
            AND c.aod_run_id = ?
        WHERE fp.aod_run_id = ?
        GROUP BY fp.plane_type
    """, (aod_run_id, aod_run_id))
    fabrics_by_type = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT LOWER(COALESCE(category, 'unknown')), COUNT(*)
        FROM connection_candidates WHERE aod_run_id = ?
        GROUP BY 1 ORDER BY 2 DESC
    """, (aod_run_id,))
    candidates_by_category = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT COALESCE(vendor_name, 'unknown'), LOWER(COALESCE(category, 'unknown')),
               COUNT(*)
        FROM connection_candidates WHERE aod_run_id = ?
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20
    """, (aod_run_id,))
    top_vendors = [
        {"vendor": r[0], "category": r[1], "count": r[2]}
        for r in cursor.fetchall()
    ]

    return {
        "handoff_row": handoff_row,
        "snapshot_name": handoff_row[3],
        "candidates_stored": candidates_stored,
        "fabric_planes_stored": fabric_planes_stored,
        "sors_stored": sors_stored,
        "fabrics_by_type": fabrics_by_type,
        "candidates_by_category": candidates_by_category,
        "top_vendors": top_vendors,
    }


# ---------------------------------------------------------------------------
# Sub-function 2: Vendor case-duplicate detection
# ---------------------------------------------------------------------------

def _check_vendor_duplicates(cursor, aod_run_id: str) -> dict:
    """Find vendors stored under different casings (e.g. Salesforce vs salesforce)."""
    cursor.execute("""
        SELECT vendor_name, COUNT(*) FROM connection_candidates
        WHERE aod_run_id = ? GROUP BY vendor_name ORDER BY 2 DESC
    """, (aod_run_id,))
    vendors_raw = {row[0]: row[1] for row in cursor.fetchall()}

    # Group raw names by lowercase key
    groups: dict[str, list] = {}
    for raw_name, cnt in vendors_raw.items():
        key = (raw_name or "unknown").lower()
        groups.setdefault(key, []).append({"name": raw_name, "count": cnt})

    case_duplicates = [
        {"canonical": key, "variants": variants,
         "total": sum(v["count"] for v in variants)}
        for key, variants in groups.items()
        if len(variants) > 1
    ]

    # Lowercase vendor counts (used elsewhere in the report)
    cursor.execute("""
        SELECT LOWER(COALESCE(vendor_name, 'unknown')), COUNT(*)
        FROM connection_candidates WHERE aod_run_id = ?
        GROUP BY 1 ORDER BY 2 DESC
    """, (aod_run_id,))
    vendors_stored = {row[0]: row[1] for row in cursor.fetchall()}

    return {
        "total_vendors": len(vendors_stored),
        "vendors_by_count": vendors_stored,
        "case_duplicates": case_duplicates,
        "has_issues": len(case_duplicates) > 0,
    }


# ---------------------------------------------------------------------------
# Sub-function 3: Fabric plane comparison (AOD-explicit vs AAM-stored)
# ---------------------------------------------------------------------------

def _compare_fabric_planes(cursor, aod_run_id: str) -> dict:
    """Compare fabric planes AOD explicitly sent vs what AAM stored.

    Also checks whether each stored plane has candidates linked to it.
    A plane that exists but has 0 candidates is flagged as "match_empty"
    so the operator knows the infrastructure is declared but unused.
    """
    from ..constants import ALL_PLANE_TYPES

    # --- AOD side: explicit planes from handoff log ---
    cursor.execute("""
        SELECT aod_fabric_planes FROM aod_handoff_log
        WHERE aod_run_id = ? ORDER BY handoff_timestamp DESC LIMIT 1
    """, (aod_run_id,))
    meta_row = cursor.fetchone()
    aod_fabric_planes_raw = []
    if meta_row and meta_row[0]:
        try:
            aod_fabric_planes_raw = json.loads(meta_row[0])
        except (json.JSONDecodeError, TypeError):
            pass

    aod_vendor_map = {}
    for p in aod_fabric_planes_raw:
        v = p.get("vendor", "unknown")
        aod_vendor_map[v.lower()] = {
            "vendor": v,
            "plane_type": p.get("plane_type", "").upper(),
            "is_healthy": p.get("is_healthy", True),
            "source": p.get("source", "aod_explicit"),
        }

    # --- AAM side: stored fabric planes ---
    cursor.execute("""
        SELECT plane_type, vendor, display_name, plane_id
        FROM fabric_planes WHERE aod_run_id = ?
        ORDER BY plane_type, vendor
    """, (aod_run_id,))
    aam_vendor_map = {}
    for row in cursor.fetchall():
        v = row[1]
        aam_vendor_map[v.lower()] = {
            "vendor": v,
            "plane_type": (row[0] or "").upper(),
            "display_name": row[2],
            "plane_id": row[3],
        }

    # --- Candidate counts per plane ---
    cursor.execute("""
        SELECT fabric_plane_id, COUNT(*)
        FROM connection_candidates
        WHERE aod_run_id = ? AND fabric_plane_id IS NOT NULL
        GROUP BY fabric_plane_id
    """, (aod_run_id,))
    candidates_per_plane = {row[0]: row[1] for row in cursor.fetchall()}

    has_aod_data = len(aod_fabric_planes_raw) > 0
    aod_keys = set(aod_vendor_map)
    aam_keys = set(aam_vendor_map)

    if has_aod_data:
        only_aod = aod_keys - aam_keys
        only_aam = aam_keys - aod_keys
        in_both = aod_keys & aam_keys
    else:
        only_aod = only_aam = in_both = set()

    # Per-vendor line items
    vendors = []
    all_keys = sorted(aod_keys | aam_keys) if has_aod_data else sorted(aam_keys)
    for vk in all_keys:
        aod_info = aod_vendor_map.get(vk)
        aam_info = aam_vendor_map.get(vk)
        vendor_display = (aod_info or aam_info)["vendor"]

        # How many candidates are linked to this plane?
        plane_id = aam_info["plane_id"] if aam_info else None
        linked_count = candidates_per_plane.get(plane_id, 0) if plane_id else 0

        if has_aod_data:
            if vk in in_both:
                status = "match"
                if (aod_info["plane_type"] and aam_info["plane_type"]
                        and aod_info["plane_type"] != aam_info["plane_type"]):
                    status = "type_mismatch"
                elif linked_count == 0:
                    status = "match_empty"
            elif vk in only_aod:
                status = "only_aod"
            else:
                status = "only_aam"
        else:
            status = "aam_inferred"

        vendors.append({
            "vendor": vendor_display,
            "aod_plane_type": aod_info["plane_type"] if aod_info else None,
            "aam_plane_type": aam_info["plane_type"] if aam_info else None,
            "linked_candidates": linked_count,
            "status": status,
        })

    mismatches = 0
    if has_aod_data:
        mismatches = len(only_aod) + len(only_aam)
        mismatches += sum(1 for v in vendors if v["status"] in ("type_mismatch", "match_empty"))

    # Group by plane type
    aod_by_type: dict[str, list] = {}
    for info in aod_vendor_map.values():
        aod_by_type.setdefault(info["plane_type"], []).append(info)
    aam_by_type: dict[str, list] = {}
    for info in aam_vendor_map.values():
        aam_by_type.setdefault(info["plane_type"], []).append(info)

    by_type = [
        {"plane_type": pt,
         "aod_vendors": aod_by_type.get(pt, []),
         "aam_vendors": aam_by_type.get(pt, [])}
        for pt in ALL_PLANE_TYPES
    ]

    return {
        "vendors": vendors,
        "by_type": by_type,
        "only_in_aod": [aod_vendor_map[k]["vendor"] for k in sorted(only_aod)],
        "only_in_aam": [aam_vendor_map[k]["vendor"] for k in sorted(only_aam)],
        "in_both": [aod_vendor_map[k]["vendor"] for k in sorted(in_both)],
        "mismatches": mismatches,
        "has_aod_data": has_aod_data,
        "has_issues": mismatches > 0 if has_aod_data else False,
    }


# ---------------------------------------------------------------------------
# Sub-function 4: SOR line-item comparison
# ---------------------------------------------------------------------------


# "SaaS" is a parent category encompassing all SOR application types.
# When Farm declares a vendor as "saas" and AAM finds "crm", that's
# compatible — CRM IS a type of SaaS.  The reverse also holds.
_SAAS_SUBTYPES = frozenset({
    "crm", "erp", "hcm", "idp", "itsm",
    "hr", "finance", "identity", "cmdb",
})

# Vendor name aliases — different names for the same product/company.
# Maps alternative names → canonical name used in AAM candidates.
_VENDOR_ALIASES: dict[str, str] = {
    "quickbooks": "intuit",
    "quick books": "intuit",
    "google bigquery": "bigquery",
    "google cloud bigquery": "bigquery",
    "amazon eventbridge": "eventbridge",
    "aws eventbridge": "eventbridge",
    "amazon redshift": "redshift",
    "aws redshift": "redshift",
    "ms dynamics": "microsoft dynamics",
    "dynamics 365": "microsoft dynamics",
    "jira": "atlassian",
    "bamboo hr": "bamboohr",
}


def _categories_compatible(expected: str, found: str) -> bool:
    """Check if expected and found categories are compatible.

    Treats "saas" as a parent category of all specific SOR types.
    """
    if expected == found:
        return True
    if expected == "saas" and found in _SAAS_SUBTYPES:
        return True
    if found == "saas" and expected in _SAAS_SUBTYPES:
        return True
    return False


def _compare_sor_line_items(cursor, aod_run_id: str) -> dict:
    """Compare Farm SOR declarations and AOD SOR summary against AAM candidates."""
    from .sor_dispositions import get_sor_dispositions

    # 1. Farm authoritative SOR declarations
    cursor.execute("""
        SELECT sor_id, domain, vendor, category, confidence, source
        FROM sor_declarations WHERE aod_run_id = ?
        ORDER BY domain, vendor
    """, (aod_run_id,))
    farm_sors = cursor.fetchall()

    # 2. AOD SOR summary from handoff log
    cursor.execute("""
        SELECT aod_sor_vendors FROM aod_handoff_log
        WHERE aod_run_id = ? ORDER BY handoff_timestamp DESC LIMIT 1
    """, (aod_run_id,))
    meta_row = cursor.fetchone()
    aod_sor_vendors_raw = []
    if meta_row and meta_row[0]:
        try:
            aod_sor_vendors_raw = json.loads(meta_row[0])
        except (json.JSONDecodeError, TypeError):
            pass

    aod_sor_all = {}
    for s in aod_sor_vendors_raw:
        vendor = s.get("vendor", "unknown")
        aod_sor_all[vendor.lower()] = {
            "vendor": vendor,
            "category": s.get("category", "unknown"),
            "count": s.get("count", 0),
            "domain": s.get("domain", ""),
            "authoritative": s.get("authoritative", False),
        }

    # 3. AAM candidates grouped by vendor
    cursor.execute("""
        SELECT LOWER(COALESCE(vendor_name, 'unknown')),
               vendor_name,
               LOWER(COALESCE(category, 'unknown')),
               COUNT(*)
        FROM connection_candidates WHERE aod_run_id = ?
        GROUP BY 1, 3 ORDER BY 1
    """, (aod_run_id,))
    aam_by_vendor: dict[str, dict] = {}
    for row in cursor.fetchall():
        vk = row[0]
        entry = aam_by_vendor.setdefault(vk, {
            "vendor_name": row[1], "categories": {}, "total": 0,
        })
        entry["categories"][row[2]] = row[3]
        entry["total"] += row[3]

    # 4. Build line items
    line_items = []
    matched = category_mismatches = missing = 0
    checked: set[str] = set()

    def _build_item(vendor, domain, expected_cat, confidence, source):
        nonlocal matched, category_mismatches, missing
        vk = vendor.lower()
        aam_data = aam_by_vendor.get(vk)
        # Try vendor aliases if direct lookup misses
        if not aam_data:
            alias = _VENDOR_ALIASES.get(vk)
            if alias:
                aam_data = aam_by_vendor.get(alias)
        if not aam_data:
            missing += 1
            return {
                "domain": domain, "vendor": vendor,
                "expected_category": expected_cat,
                "confidence": confidence, "source": source,
                "ingested": False, "aam_category": None,
                "aam_count": 0, "category_match": False,
                "verdict": "missing",
            }
        aam_cats = aam_data["categories"]
        aam_primary = max(aam_cats, key=aam_cats.get) if aam_cats else "unknown"
        cat_match = (
            _categories_compatible(expected_cat, aam_primary)
            or expected_cat in aam_cats
        )
        if cat_match:
            matched += 1
            verdict = "ok"
        else:
            category_mismatches += 1
            verdict = "category_mismatch"
        return {
            "domain": domain, "vendor": vendor,
            "expected_category": expected_cat,
            "confidence": confidence, "source": source,
            "ingested": True, "aam_category": aam_primary,
            "aam_all_categories": dict(aam_cats),
            "aam_count": aam_data["total"],
            "category_match": cat_match, "verdict": verdict,
        }

    # Pass 1: Farm declarations (highest priority)
    for row in farm_sors:
        _sor_id, domain, vendor, expected_cat, confidence, source = row
        checked.add(vendor.lower())
        line_items.append(_build_item(
            vendor, domain,
            expected_cat.lower() if expected_cat else "",
            confidence, source or "farm",
        ))

    # Pass 2: AOD SOR vendors not already covered
    for vk, aod_info in sorted(aod_sor_all.items()):
        if vk in checked:
            continue
        checked.add(vk)
        line_items.append(_build_item(
            aod_info["vendor"],
            aod_info.get("domain", ""),
            aod_info["category"],
            "inferred", "aod_candidate",
        ))

    total = len(line_items)
    mismatches = category_mismatches + missing
    all_ok = total > 0 and mismatches == 0
    accuracy = round((matched / total) * 100, 1) if total > 0 else 0

    # Merge operator dispositions
    dispositions = get_sor_dispositions(aod_run_id)
    undispositioned = 0
    for item in line_items:
        vk = item["vendor"].lower().strip()
        disp = dispositions.get(vk)
        if disp:
            item["disposition"] = disp["status"]
            item["disposition_reason"] = disp.get("reason")
            item["disposition_notes"] = disp.get("operator_notes")
            item["disposition_updated"] = disp.get("updated_at")
        else:
            item["disposition"] = None
            item["disposition_reason"] = None
            item["disposition_notes"] = None
            item["disposition_updated"] = None
        if item["verdict"] != "ok" and not disp:
            undispositioned += 1

    return {
        "line_items": line_items,
        "total_sors": total,
        "matched": matched,
        "category_mismatches": category_mismatches,
        "missing": missing,
        "mismatches": mismatches,
        "undispositioned": undispositioned,
        "ingestion_accuracy": accuracy,
        "all_ok": all_ok,
        "has_aod_data": total > 0,
        "has_issues": mismatches > 0,
    }


# ---------------------------------------------------------------------------
# Sub-function 5: Schema completeness
# ---------------------------------------------------------------------------

def _check_schema_completeness(cursor, aod_run_id: str) -> dict:
    """Find candidates missing key AOD-provided fields."""
    cursor.execute("""
        SELECT candidate_id, vendor_name, display_name, category,
               known_endpoints, preferred_modality, connected_via_plane
        FROM connection_candidates WHERE aod_run_id = ?
    """, (aod_run_id,))

    issues = []
    aod_missing = {"vendor_name": 0, "display_name": 0,
                   "category": 0, "known_endpoints": 0,
                   "connected_via_plane": 0}
    enrichment_missing = {"preferred_modality": 0}
    total = 0

    for row in cursor.fetchall():
        cid, vendor, display, cat, endpoints, modality, plane = row
        total += 1
        missing_aod = []
        if not vendor or vendor.lower() in ("unknown", ""):
            missing_aod.append("vendor_name")
            aod_missing["vendor_name"] += 1
        if not display or display.lower() in ("unknown", ""):
            missing_aod.append("display_name")
            aod_missing["display_name"] += 1
        if not cat or cat.lower() in ("unknown", ""):
            missing_aod.append("category")
            aod_missing["category"] += 1
        if not endpoints or endpoints in ("[]", "", "null"):
            missing_aod.append("known_endpoints")
            aod_missing["known_endpoints"] += 1
        if not plane or plane == "":
            aod_missing["connected_via_plane"] += 1
        if not modality or modality.lower() in ("unknown", ""):
            enrichment_missing["preferred_modality"] += 1
        if missing_aod:
            issues.append({
                "candidate_id": cid, "vendor": vendor,
                "display_name": display, "missing_fields": missing_aod,
            })

    score = round((1 - len(issues) / max(total, 1)) * 100, 1)

    # Flag as an issue if core AOD fields (vendor, display, category) are missing.
    # known_endpoints is optional so we only count the structural fields.
    core_aod_missing = aod_missing["vendor_name"] + aod_missing["display_name"] + aod_missing["category"]
    return {
        "total_candidates": total,
        "incomplete_count": len(issues),
        "incomplete_candidates": issues[:25],
        "field_missing_counts": {**aod_missing, **enrichment_missing},
        "completeness_score": score,
        "has_issues": core_aod_missing > 0,
        "data_quality_notes": len(issues),
    }


# ---------------------------------------------------------------------------
# Sub-function 6: Duplicate detection
# ---------------------------------------------------------------------------

def _check_duplicates(cursor, aod_run_id: str) -> dict:
    """Find candidates sharing vendor + display_name combination."""
    cursor.execute("""
        SELECT LOWER(COALESCE(vendor_name, 'unknown')),
               LOWER(COALESCE(display_name, '')),
               LOWER(COALESCE(category, 'unknown')),
               COUNT(*),
               GROUP_CONCAT(candidate_id, '|')
        FROM connection_candidates WHERE aod_run_id = ?
        GROUP BY 1, 2 HAVING COUNT(*) > 1
        ORDER BY 4 DESC
    """, (aod_run_id,))

    groups = []
    total_rows = 0
    for row in cursor.fetchall():
        vendor, display, cat, count, ids = row
        groups.append({
            "vendor": vendor, "display_name": display,
            "category": cat, "count": count,
            "candidate_ids": ids.split("|") if ids else [],
        })
        total_rows += count

    return {
        "duplicate_groups": groups[:25],
        "total_groups": len(groups),
        "total_duplicate_rows": total_rows,
        "has_issues": len(groups) > 0,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def get_aod_reconciliation(aod_run_id: str) -> dict:
    """
    Reconcile AOD handoff data with AAM storage.

    Delegates to focused sub-functions for each check, then assembles the
    full report.
    """
    conn = get_connection()
    cursor = conn.cursor()

    summary = _get_handoff_summary(cursor, aod_run_id)
    if summary is None:
        conn.close()
        return {"error": f"No handoff found for run {aod_run_id}",
                "aod_run_id": aod_run_id}

    vendor_check = _check_vendor_duplicates(cursor, aod_run_id)
    fabric_check = _compare_fabric_planes(cursor, aod_run_id)
    sor_check = _compare_sor_line_items(cursor, aod_run_id)
    completeness = _check_schema_completeness(cursor, aod_run_id)
    duplicates = _check_duplicates(cursor, aod_run_id)

    conn.close()

    handoff_row = summary["handoff_row"]
    candidates_stored = summary["candidates_stored"]

    # Count only AOD-origin candidates (exclude AAM-created infra candidates)
    cursor2 = get_connection().cursor()
    cursor2.execute("""
        SELECT COUNT(*) FROM connection_candidates
        WHERE aod_run_id = ? AND asset_key NOT LIKE 'infra:%'
    """, (aod_run_id,))
    aod_origin_stored = cursor2.fetchone()[0]
    cursor2.connection.close()

    # Count candidates with a fabric plane linkage
    fabric_linked = sum(
        v.get("linked_candidates", 0) for v in fabric_check.get("vendors", [])
    )

    real_fabric_issues = fabric_check["mismatches"] if fabric_check["has_aod_data"] else 0
    real_sor_issues = sor_check["mismatches"] if sor_check["has_aod_data"] else 0
    schema_issues = completeness.get("incomplete_count", 0) if completeness.get("has_issues") else 0
    issues_count = (
        len(vendor_check["case_duplicates"])
        + real_fabric_issues
        + real_sor_issues
        + schema_issues
        + duplicates["total_groups"]
    )

    return {
        "aod_run_id": aod_run_id,
        "snapshot_name": summary["snapshot_name"],
        "handoff_timestamp": handoff_row[2],
        "aod_sent": {
            "candidates": handoff_row[0],
            "candidates_accepted": handoff_row[1],
        },
        "aam_stored": {
            "candidates": candidates_stored,
            "aod_origin_candidates": aod_origin_stored,
            "fabric_planes": summary["fabric_planes_stored"],
            "fabric_linked": fabric_linked,
            "sors": summary["sors_stored"],
            "fabrics_by_type": summary["fabrics_by_type"],
            "candidates_by_category": summary["candidates_by_category"],
            "top_vendors": summary["top_vendors"],
        },
        "reconciliation": {
            "candidates_match": handoff_row[1] == aod_origin_stored,
            "discrepancy": handoff_row[1] - aod_origin_stored,
        },
        "deep_checks": {
            "vendor_matching": vendor_check,
            "fabric_comparison": fabric_check,
            "sor_comparison": sor_check,
            "schema_completeness": completeness,
            "duplicates": duplicates,
            "total_issues": issues_count,
        },
    }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_latest_aod_run() -> Optional[dict]:
    """Get the most recent AOD run information."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT aod_run_id, snapshot_name, candidates_received,
               candidates_accepted, handoff_timestamp
        FROM aod_handoff_log
        ORDER BY handoff_timestamp DESC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "aod_run_id": row[0], "snapshot_name": row[1],
            "candidates_received": row[2], "candidates_accepted": row[3],
            "handoff_timestamp": row[4],
        }
    return None
