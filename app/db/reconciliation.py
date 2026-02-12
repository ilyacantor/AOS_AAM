"""
AOD reconciliation operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# AOD RECONCILIATION
# ============================================================================

def get_aod_reconciliation(aod_run_id: str) -> dict:
    """
    Reconcile AOD handoff data with AAM storage.
    
    Returns counts of:
    - Candidates received vs stored
    - Fabric planes received vs stored
    - SORs identified
    - Pipes (candidates ARE pipes by canonical definition)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get handoff log
    cursor.execute("""
        SELECT candidates_received, candidates_accepted, handoff_timestamp
        FROM aod_handoff_log
        WHERE aod_run_id = ?
        ORDER BY handoff_timestamp DESC
        LIMIT 1
    """, (aod_run_id,))
    handoff_row = cursor.fetchone()
    
    if not handoff_row:
        conn.close()
        return {
            "error": f"No handoff found for run {aod_run_id}",
            "aod_run_id": aod_run_id
        }
    
    # Get actual counts from AAM storage
    cursor.execute("SELECT COUNT(*) FROM connection_candidates WHERE aod_run_id = ?", (aod_run_id,))
    candidates_stored = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM fabric_planes WHERE aod_run_id = ?", (aod_run_id,))
    fabric_planes_stored = cursor.fetchone()[0]
    
    # Get SOR count (candidates with SOR categories)
    from ..constants import SOR_CATEGORIES
    sor_categories = list(SOR_CATEGORIES)
    placeholders = ','.join('?' * len(sor_categories))
    cursor.execute(f"""
        SELECT COUNT(*) FROM connection_candidates
        WHERE aod_run_id = ? AND LOWER(category) IN ({placeholders})
    """, (aod_run_id, *sor_categories))
    sors_stored = cursor.fetchone()[0]
    
    # Get fabric counts by type
    cursor.execute("""
        SELECT plane_type, COUNT(*) as count
        FROM fabric_planes
        WHERE aod_run_id = ?
        GROUP BY plane_type
    """, (aod_run_id,))
    fabrics_by_type = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Get candidates breakdown by category
    cursor.execute("""
        SELECT LOWER(COALESCE(category, 'unknown')) as cat, COUNT(*) as count
        FROM connection_candidates
        WHERE aod_run_id = ?
        GROUP BY cat
        ORDER BY count DESC
    """, (aod_run_id,))
    candidates_by_category = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Get top vendors
    cursor.execute("""
        SELECT COALESCE(vendor_name, 'unknown') as vendor,
               LOWER(COALESCE(category, 'unknown')) as cat,
               COUNT(*) as count
        FROM connection_candidates
        WHERE aod_run_id = ?
        GROUP BY vendor, cat
        ORDER BY count DESC
        LIMIT 20
    """, (aod_run_id,))
    top_vendors = [{"vendor": row[0], "category": row[1], "count": row[2]} for row in cursor.fetchall()]
    
    # Get snapshot_name from handoff log
    cursor.execute("""
        SELECT snapshot_name FROM aod_handoff_log
        WHERE aod_run_id = ?
        ORDER BY handoff_timestamp DESC LIMIT 1
    """, (aod_run_id,))
    snap_row = cursor.fetchone()
    snapshot_name = snap_row[0] if snap_row else None
    
    # ===== DEEP CHECK 1: Per-Vendor Matching =====
    # All unique vendors that AOD sent for this run
    cursor.execute("""
        SELECT LOWER(COALESCE(vendor_name, 'unknown')) as vendor, COUNT(*) as count
        FROM connection_candidates
        WHERE aod_run_id = ?
        GROUP BY vendor
        ORDER BY count DESC
    """, (aod_run_id,))
    vendors_stored = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Check for case-sensitive duplicates (e.g. "Salesforce" vs "salesforce")
    cursor.execute("""
        SELECT vendor_name, COUNT(*) as count
        FROM connection_candidates
        WHERE aod_run_id = ?
        GROUP BY vendor_name
        ORDER BY count DESC
    """, (aod_run_id,))
    vendors_raw = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Find case duplicates: group raw vendor names by lowercase
    vendor_case_groups = {}
    for raw_name, cnt in vendors_raw.items():
        key = (raw_name or "unknown").lower()
        if key not in vendor_case_groups:
            vendor_case_groups[key] = []
        vendor_case_groups[key].append({"name": raw_name, "count": cnt})
    
    vendor_case_duplicates = []
    for key, variants in vendor_case_groups.items():
        if len(variants) > 1:
            vendor_case_duplicates.append({
                "canonical": key,
                "variants": variants,
                "total": sum(v["count"] for v in variants)
            })
    
    # ===== DEEP CHECK 2: Per-Candidate Row Check =====
    # Find candidates from this run that might have issues
    cursor.execute("""
        SELECT candidate_id, vendor_name, display_name, category, status, 
               connected_via_plane, execution_allowed
        FROM connection_candidates
        WHERE aod_run_id = ?
    """, (aod_run_id,))
    all_candidates = cursor.fetchall()
    
    # Check for candidates not connected
    unconnected_candidates = []
    blocked_candidates = []
    for row in all_candidates:
        cid, vendor, display, cat, status, plane, exec_allowed = row
        if status and status.lower() not in ('connected', 'triaged'):
            unconnected_candidates.append({
                "candidate_id": cid,
                "vendor": vendor,
                "display_name": display,
                "category": cat,
                "status": status
            })
        if exec_allowed is not None and not exec_allowed:
            blocked_candidates.append({
                "candidate_id": cid,
                "vendor": vendor,
                "display_name": display,
                "category": cat,
                "status": status
            })
    
    # ===== DEEP CHECK 3: Fabric Plane Comparison (AOD-explicit vs AAM-stored) =====
    # AOD side: what AOD *explicitly* told us about fabric planes (from handoff log)
    # These are ONLY planes AOD sent in the fabric_planes field, NOT AAM-inferred ones
    cursor.execute("""
        SELECT aod_fabric_planes, aod_sor_vendors
        FROM aod_handoff_log
        WHERE aod_run_id = ?
        ORDER BY handoff_timestamp DESC LIMIT 1
    """, (aod_run_id,))
    handoff_meta = cursor.fetchone()
    aod_fabric_planes_raw = []
    aod_sor_vendors_raw = []
    if handoff_meta:
        try:
            if handoff_meta[0]:
                aod_fabric_planes_raw = json.loads(handoff_meta[0])
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            if handoff_meta[1]:
                aod_sor_vendors_raw = json.loads(handoff_meta[1])
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Build AOD vendor list — only explicit planes AOD sent
    aod_vendor_map = {}
    for p in aod_fabric_planes_raw:
        v = p.get("vendor", "unknown")
        aod_vendor_map[v.lower()] = {
            "vendor": v,
            "plane_type": p.get("plane_type", "").upper(),
            "is_healthy": p.get("is_healthy", True),
            "source": p.get("source", "aod_explicit"),
        }
    
    # AAM side: ALL fabric planes currently stored (for this run)
    cursor.execute("""
        SELECT plane_type, vendor, display_name, aod_run_id
        FROM fabric_planes
        WHERE aod_run_id = ?
        ORDER BY plane_type, vendor
    """, (aod_run_id,))
    aam_fabric_rows = cursor.fetchall()
    
    aam_vendor_map = {}
    for row in aam_fabric_rows:
        v = row[1]
        aam_vendor_map[v.lower()] = {
            "vendor": v,
            "plane_type": (row[0] or "").upper(),
            "display_name": row[2],
        }
    
    has_aod_fabric_data = len(aod_fabric_planes_raw) > 0
    
    # Comparison: AOD-explicit planes vs AAM-stored planes
    aod_vendor_keys = set(aod_vendor_map.keys())
    aam_vendor_keys = set(aam_vendor_map.keys())
    
    if has_aod_fabric_data:
        only_in_aod_global = aod_vendor_keys - aam_vendor_keys
        only_in_aam_global = aam_vendor_keys - aod_vendor_keys
        in_both_global = aod_vendor_keys & aam_vendor_keys
    else:
        only_in_aod_global = set()
        only_in_aam_global = set()
        in_both_global = set()
    
    fabric_vendors = []
    all_keys = sorted(aod_vendor_keys | aam_vendor_keys) if has_aod_fabric_data else sorted(aam_vendor_keys)
    for vk in all_keys:
        aod_info = aod_vendor_map.get(vk)
        aam_info = aam_vendor_map.get(vk)
        vendor_display = (aod_info or aam_info)["vendor"]
        
        if has_aod_fabric_data:
            if vk in in_both_global:
                status = "match"
                aod_type = aod_info["plane_type"] if aod_info else None
                aam_type = aam_info["plane_type"] if aam_info else None
                if aod_type and aam_type and aod_type != aam_type:
                    status = "type_mismatch"
            elif vk in only_in_aod_global:
                status = "only_aod"
            else:
                status = "only_aam"
        else:
            status = "aam_inferred"
        
        fabric_vendors.append({
            "vendor": vendor_display,
            "aod_plane_type": aod_info["plane_type"] if aod_info else None,
            "aam_plane_type": aam_info["plane_type"] if aam_info else None,
            "status": status,
        })
    
    fabric_mismatches = 0
    if has_aod_fabric_data:
        fabric_mismatches = len(only_in_aod_global) + len(only_in_aam_global)
        for v in fabric_vendors:
            if v["status"] == "type_mismatch":
                fabric_mismatches += 1
    
    all_plane_types = ["IPAAS", "API_GATEWAY", "EVENT_BUS", "DATA_WAREHOUSE"]
    aod_by_type = {}
    for vk, info in aod_vendor_map.items():
        pt = info["plane_type"]
        if pt not in aod_by_type:
            aod_by_type[pt] = []
        aod_by_type[pt].append(info)
    aam_by_type = {}
    for vk, info in aam_vendor_map.items():
        pt = info["plane_type"]
        if pt not in aam_by_type:
            aam_by_type[pt] = []
        aam_by_type[pt].append(info)
    
    fabric_by_type = []
    for pt in all_plane_types:
        fabric_by_type.append({
            "plane_type": pt,
            "aod_vendors": aod_by_type.get(pt, []),
            "aam_vendors": aam_by_type.get(pt, []),
        })
    
    # ===== DEEP CHECK 3b: SOR Line-Item Ingestion/Classification =====
    # Compare each SOR declaration (from Farm via AOD) against actual AAM candidates.
    # The question: did AAM correctly ingest and classify each SOR vendor?

    # 1. Get authoritative SOR declarations stored from Farm
    cursor.execute("""
        SELECT sor_id, domain, vendor, category, confidence, source
        FROM sor_declarations
        WHERE aod_run_id = ?
        ORDER BY domain, vendor
    """, (aod_run_id,))
    farm_sors = cursor.fetchall()

    # 2. Also build SOR expectations from AOD handoff log (aod_sor_vendors)
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

    # 3. Get AAM candidate data grouped by vendor for comparison
    cursor.execute("""
        SELECT LOWER(COALESCE(vendor_name, 'unknown')) as vendor_key,
               vendor_name, 
               LOWER(COALESCE(category, 'unknown')) as cat,
               COUNT(*) as cnt
        FROM connection_candidates
        WHERE aod_run_id = ?
        GROUP BY vendor_key, cat
        ORDER BY vendor_key
    """, (aod_run_id,))
    aam_candidates_by_vendor = {}
    for row in cursor.fetchall():
        vk = row[0]
        if vk not in aam_candidates_by_vendor:
            aam_candidates_by_vendor[vk] = {
                "vendor_name": row[1],
                "categories": {},
                "total": 0,
            }
        aam_candidates_by_vendor[vk]["categories"][row[2]] = row[3]
        aam_candidates_by_vendor[vk]["total"] += row[3]

    # 4. Build line-item comparison for each SOR
    sor_line_items = []
    sor_matched = 0
    sor_category_mismatches = 0
    sor_missing = 0

    # Track which SOR vendors we've checked (combine Farm declarations + AOD SOR summary)
    checked_vendors = set()

    # First pass: Farm authoritative SOR declarations (highest priority)
    for row in farm_sors:
        sor_id, domain, vendor, expected_cat, confidence, source = row
        vk = vendor.lower()
        checked_vendors.add(vk)

        aam_data = aam_candidates_by_vendor.get(vk)
        if not aam_data:
            sor_line_items.append({
                "domain": domain,
                "vendor": vendor,
                "expected_category": expected_cat.lower() if expected_cat else "",
                "confidence": confidence,
                "source": source or "farm",
                "ingested": False,
                "aam_category": None,
                "aam_count": 0,
                "category_match": False,
                "verdict": "missing",
            })
            sor_missing += 1
            continue

        aam_cats = aam_data["categories"]
        aam_primary_cat = max(aam_cats, key=aam_cats.get) if aam_cats else "unknown"
        expected_lower = expected_cat.lower() if expected_cat else ""

        cat_match = expected_lower == aam_primary_cat or expected_lower in aam_cats

        if cat_match:
            verdict = "ok"
            sor_matched += 1
        else:
            verdict = "category_mismatch"
            sor_category_mismatches += 1

        sor_line_items.append({
            "domain": domain,
            "vendor": vendor,
            "expected_category": expected_lower,
            "confidence": confidence,
            "source": source or "farm",
            "ingested": True,
            "aam_category": aam_primary_cat,
            "aam_all_categories": dict(aam_cats),
            "aam_count": aam_data["total"],
            "category_match": cat_match,
            "verdict": verdict,
        })

    # Second pass: AOD SOR vendors not already covered by Farm declarations
    for vk, aod_info in sorted(aod_sor_all.items()):
        if vk in checked_vendors:
            continue
        checked_vendors.add(vk)

        aam_data = aam_candidates_by_vendor.get(vk)
        expected_cat = aod_info["category"]

        if not aam_data:
            sor_line_items.append({
                "domain": aod_info.get("domain", ""),
                "vendor": aod_info["vendor"],
                "expected_category": expected_cat,
                "confidence": "inferred",
                "source": "aod_candidate",
                "ingested": False,
                "aam_category": None,
                "aam_count": 0,
                "category_match": False,
                "verdict": "missing",
            })
            sor_missing += 1
            continue

        aam_cats = aam_data["categories"]
        aam_primary_cat = max(aam_cats, key=aam_cats.get) if aam_cats else "unknown"
        cat_match = expected_cat == aam_primary_cat or expected_cat in aam_cats

        if cat_match:
            verdict = "ok"
            sor_matched += 1
        else:
            verdict = "category_mismatch"
            sor_category_mismatches += 1

        sor_line_items.append({
            "domain": aod_info.get("domain", ""),
            "vendor": aod_info["vendor"],
            "expected_category": expected_cat,
            "confidence": "inferred",
            "source": "aod_candidate",
            "ingested": True,
            "aam_category": aam_primary_cat,
            "aam_all_categories": dict(aam_cats),
            "aam_count": aam_data["total"],
            "category_match": cat_match,
            "verdict": verdict,
        })

    total_sors = len(sor_line_items)
    has_aod_sor_data = total_sors > 0
    sor_mismatches = sor_category_mismatches + sor_missing

    all_ok = total_sors > 0 and sor_mismatches == 0
    ingestion_accuracy = round((sor_matched / total_sors) * 100, 1) if total_sors > 0 else 0
    
    # ===== DEEP CHECK 4: Schema Completeness =====
    # Find candidates missing key fields
    # IMPORTANT: Separate AOD-provided fields from AAM-enrichment fields
    # AOD fields: vendor_name, display_name, category, known_endpoints
    # AAM enrichment fields: preferred_modality, connected_via_plane (NOT from AOD)
    cursor.execute("""
        SELECT candidate_id, vendor_name, display_name, category, 
               known_endpoints, preferred_modality, priority_score,
               connected_via_plane
        FROM connection_candidates
        WHERE aod_run_id = ?
    """, (aod_run_id,))
    completeness_issues = []
    aod_field_missing = {"vendor_name": 0, "display_name": 0, "category": 0, "known_endpoints": 0}
    enrichment_field_missing = {"preferred_modality": 0, "connected_via_plane": 0}
    total_for_completeness = 0
    
    for row in cursor.fetchall():
        cid, vendor, display, cat, endpoints, modality, score, plane = row
        total_for_completeness += 1
        missing_aod = []
        missing_enrichment = []
        if not vendor or vendor.lower() in ('unknown', ''):
            missing_aod.append("vendor_name")
            aod_field_missing["vendor_name"] += 1
        if not display or display.lower() in ('unknown', ''):
            missing_aod.append("display_name")
            aod_field_missing["display_name"] += 1
        if not cat or cat.lower() in ('unknown', ''):
            missing_aod.append("category")
            aod_field_missing["category"] += 1
        if not endpoints or endpoints in ('[]', '', 'null'):
            missing_aod.append("known_endpoints")
            aod_field_missing["known_endpoints"] += 1
        if not modality or modality.lower() in ('unknown', ''):
            missing_enrichment.append("preferred_modality")
            enrichment_field_missing["preferred_modality"] += 1
        if not plane or plane == '':
            missing_enrichment.append("connected_via_plane")
            enrichment_field_missing["connected_via_plane"] += 1
        if missing_aod:
            completeness_issues.append({
                "candidate_id": cid,
                "vendor": vendor,
                "display_name": display,
                "missing_fields": missing_aod
            })
    
    # Completeness score based ONLY on AOD-provided fields (not enrichment)
    completeness_score = round(
        (1 - len(completeness_issues) / max(total_for_completeness, 1)) * 100, 1
    )
    
    # Combined field_missing_counts for backward compatibility, but tag source
    field_missing_counts = {**aod_field_missing, **enrichment_field_missing}
    
    # ===== DEEP CHECK 5: Duplicate Detection =====
    # Find candidates that share the same vendor + endpoint combination
    cursor.execute("""
        SELECT LOWER(COALESCE(vendor_name, 'unknown')) as vendor,
               LOWER(COALESCE(display_name, '')) as display,
               LOWER(COALESCE(category, 'unknown')) as cat,
               COUNT(*) as count,
               GROUP_CONCAT(candidate_id, '|') as ids
        FROM connection_candidates
        WHERE aod_run_id = ?
        GROUP BY vendor, display
        HAVING count > 1
        ORDER BY count DESC
    """, (aod_run_id,))
    
    duplicates = []
    total_duplicate_rows = 0
    for row in cursor.fetchall():
        vendor, display, cat, count, ids = row
        duplicates.append({
            "vendor": vendor,
            "display_name": display,
            "category": cat,
            "count": count,
            "candidate_ids": ids.split("|") if ids else []
        })
        total_duplicate_rows += count
    
    conn.close()
    
    # Canonical definition: Candidates = Pipes
    pipes_count = candidates_stored
    
    # Overall health scoring
    # Issues = reconciliation errors (AAM didn't store what AOD sent correctly)
    # NOT data quality observations (AOD sent incomplete data - that's informational)
    real_fabric_issues = fabric_mismatches if has_aod_fabric_data else 0
    real_sor_issues = sor_mismatches if has_aod_sor_data else 0
    issues_count = (
        len(vendor_case_duplicates) +
        real_fabric_issues +
        real_sor_issues +
        len(duplicates)
    )
    # Schema completeness is informational (AOD data quality), not a reconciliation error
    # Unconnected candidates are expected state for fresh candidates
    
    return {
        "aod_run_id": aod_run_id,
        "snapshot_name": snapshot_name,
        "handoff_timestamp": handoff_row[2] if handoff_row else None,
        "aod_sent": {
            "candidates": handoff_row[0] if handoff_row else 0,
            "candidates_accepted": handoff_row[1] if handoff_row else 0
        },
        "aam_stored": {
            "candidates": candidates_stored,
            "pipes": pipes_count,
            "fabric_planes": fabric_planes_stored,
            "sors": sors_stored,
            "fabrics_by_type": fabrics_by_type,
            "candidates_by_category": candidates_by_category,
            "top_vendors": top_vendors
        },
        "reconciliation": {
            "candidates_match": handoff_row[1] == candidates_stored if handoff_row else False,
            "pipes_match": handoff_row[1] == pipes_count if handoff_row else False,
            "discrepancy": (handoff_row[1] - candidates_stored) if handoff_row else 0
        },
        "deep_checks": {
            "vendor_matching": {
                "total_vendors": len(vendors_stored),
                "vendors_by_count": vendors_stored,
                "case_duplicates": vendor_case_duplicates,
                "has_issues": len(vendor_case_duplicates) > 0
            },
            "candidate_rows": {
                "total": len(all_candidates),
                "unconnected": unconnected_candidates[:25],
                "unconnected_count": len(unconnected_candidates),
                "blocked": blocked_candidates[:25],
                "blocked_count": len(blocked_candidates),
                "has_issues": len(unconnected_candidates) > 0 or len(blocked_candidates) > 0
            },
            "fabric_comparison": {
                "vendors": fabric_vendors,
                "by_type": fabric_by_type,
                "only_in_aod": [aod_vendor_map[k]["vendor"] for k in sorted(only_in_aod_global)],
                "only_in_aam": [aam_vendor_map[k]["vendor"] for k in sorted(only_in_aam_global)],
                "in_both": [aod_vendor_map[k]["vendor"] for k in sorted(in_both_global)],
                "mismatches": fabric_mismatches,
                "has_aod_data": has_aod_fabric_data,
                "has_issues": real_fabric_issues > 0
            },
            "sor_comparison": {
                "line_items": sor_line_items,
                "total_sors": total_sors,
                "matched": sor_matched,
                "category_mismatches": sor_category_mismatches,
                "missing": sor_missing,
                "mismatches": sor_mismatches,
                "ingestion_accuracy": ingestion_accuracy,
                "all_ok": all_ok,
                "has_aod_data": has_aod_sor_data,
                "has_issues": sor_mismatches > 0,
            },
            "schema_completeness": {
                "total_candidates": total_for_completeness,
                "incomplete_count": len(completeness_issues),
                "incomplete_candidates": completeness_issues[:25],
                "field_missing_counts": field_missing_counts,
                "completeness_score": completeness_score,
                "has_issues": False,
                "data_quality_notes": len(completeness_issues)
            },
            "duplicates": {
                "duplicate_groups": duplicates[:25],
                "total_groups": len(duplicates),
                "total_duplicate_rows": total_duplicate_rows,
                "has_issues": len(duplicates) > 0
            },
            "total_issues": issues_count
        }
    }


def get_latest_aod_run() -> Optional[dict]:
    """Get the most recent AOD run information"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT aod_run_id, snapshot_name, candidates_received, candidates_accepted, handoff_timestamp
        FROM aod_handoff_log
        ORDER BY handoff_timestamp DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "aod_run_id": row[0],
            "snapshot_name": row[1],
            "candidates_received": row[2],
            "candidates_accepted": row[3],
            "handoff_timestamp": row[4]
        }
    return None


