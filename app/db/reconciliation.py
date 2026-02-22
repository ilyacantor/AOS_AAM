"""
AOD reconciliation operations.

Decomposed into focused sub-functions, each handling one reconciliation
concern.  The top-level get_aod_reconciliation() orchestrates them.
"""
import json
from collections import defaultdict
from typing import Optional

from . import supabase_client as sb
from ..constants import SOR_CATEGORIES
from ..logger import get_logger

_log = get_logger("db.reconciliation")


def _get_handoff_summary(aod_run_id: str) -> Optional[dict]:
    """Return handoff log row, basic counts, and top-vendor breakdown."""
    handoff_rows = sb.select(
        "aod_handoff_log",
        filters={"aod_run_id": aod_run_id},
        order="handoff_timestamp.desc",
        limit=1,
    )
    if not handoff_rows:
        return None
    handoff_row = handoff_rows[0]

    candidates = sb.select("connection_candidates", filters={"aod_run_id": aod_run_id})
    candidates_stored = len(candidates)

    fabric_planes = sb.select("fabric_planes", filters={"aod_run_id": aod_run_id})
    fabric_planes_stored = len(fabric_planes)

    sor_categories = SOR_CATEGORIES
    sors_stored = sum(
        1 for c in candidates
        if (c.get("category") or "").lower() in sor_categories
    )

    fabrics_by_type: dict[str, int] = defaultdict(int)
    plane_id_to_type = {fp["plane_id"]: fp["plane_type"] for fp in fabric_planes}
    for fp in fabric_planes:
        pt = fp["plane_type"]
        linked = sum(
            1 for c in candidates
            if c.get("fabric_plane_id") == fp["plane_id"]
        )
        fabrics_by_type[pt] = fabrics_by_type.get(pt, 0) + linked

    candidates_by_category: dict[str, int] = defaultdict(int)
    for c in candidates:
        cat = (c.get("category") or "unknown").lower()
        candidates_by_category[cat] += 1
    candidates_by_category = dict(sorted(candidates_by_category.items(), key=lambda x: -x[1]))

    vendor_cat_counts: dict[tuple, int] = defaultdict(int)
    for c in candidates:
        vendor = c.get("vendor_name") or "unknown"
        cat = (c.get("category") or "unknown").lower()
        vendor_cat_counts[(vendor, cat)] += 1
    top_vendors_sorted = sorted(vendor_cat_counts.items(), key=lambda x: -x[1])[:20]
    top_vendors = [
        {"vendor": k[0], "category": k[1], "count": v}
        for k, v in top_vendors_sorted
    ]

    return {
        "handoff_row": handoff_row,
        "snapshot_name": handoff_row.get("snapshot_name"),
        "candidates_stored": candidates_stored,
        "fabric_planes_stored": fabric_planes_stored,
        "sors_stored": sors_stored,
        "fabrics_by_type": dict(fabrics_by_type),
        "candidates_by_category": dict(candidates_by_category),
        "top_vendors": top_vendors,
    }


def _check_vendor_duplicates(aod_run_id: str) -> dict:
    """Find vendors stored under different casings (e.g. Salesforce vs salesforce)."""
    candidates = sb.select("connection_candidates", filters={"aod_run_id": aod_run_id})

    vendors_raw: dict[str, int] = defaultdict(int)
    for c in candidates:
        vendor = c.get("vendor_name") or "unknown"
        vendors_raw[vendor] += 1

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

    vendors_stored: dict[str, int] = defaultdict(int)
    for c in candidates:
        vk = (c.get("vendor_name") or "unknown").lower()
        vendors_stored[vk] += 1
    vendors_stored = dict(sorted(vendors_stored.items(), key=lambda x: -x[1]))

    return {
        "total_vendors": len(vendors_stored),
        "vendors_by_count": dict(vendors_stored),
        "case_duplicates": case_duplicates,
        "has_issues": len(case_duplicates) > 0,
    }


def _compare_fabric_planes(aod_run_id: str) -> dict:
    """Compare fabric planes AOD explicitly sent vs what AAM stored.

    Also checks whether each stored plane has candidates linked to it.
    A plane that exists but has 0 candidates is flagged as "match_empty"
    so the operator knows the infrastructure is declared but unused.
    """
    from ..constants import ALL_PLANE_TYPES

    handoff_rows = sb.select(
        "aod_handoff_log",
        filters={"aod_run_id": aod_run_id},
        order="handoff_timestamp.desc",
        limit=1,
    )
    aod_fabric_planes_raw = []
    if handoff_rows:
        meta_row = handoff_rows[0]
        raw_val = meta_row.get("aod_fabric_planes")
        if raw_val:
            try:
                aod_fabric_planes_raw = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
            except (json.JSONDecodeError, TypeError) as exc:
                _log.error(
                    "Corrupt aod_fabric_planes JSON for run %s — fabric plane "
                    "reconciliation will report all planes as AAM-only: %s",
                    aod_run_id, exc,
                )

    aod_vendor_map = {}
    for p in aod_fabric_planes_raw:
        v = p.get("vendor", "unknown")
        aod_vendor_map[v.lower()] = {
            "vendor": v,
            "plane_type": p.get("plane_type", "").upper(),
            "is_healthy": p.get("is_healthy", True),
            "source": p.get("source", "aod_explicit"),
        }

    fabric_planes = sb.select("fabric_planes", filters={"aod_run_id": aod_run_id})
    aam_vendor_map = {}
    for row in fabric_planes:
        v = row["vendor"]
        aam_vendor_map[v.lower()] = {
            "vendor": v,
            "plane_type": (row.get("plane_type") or "").upper(),
            "display_name": row.get("display_name"),
            "plane_id": row["plane_id"],
        }

    candidates = sb.select("connection_candidates", filters={"aod_run_id": aod_run_id})
    candidates_per_plane: dict[str, int] = defaultdict(int)
    for c in candidates:
        fpid = c.get("fabric_plane_id")
        if fpid:
            candidates_per_plane[fpid] += 1

    has_aod_data = len(aod_fabric_planes_raw) > 0
    aod_keys = set(aod_vendor_map)
    aam_keys = set(aam_vendor_map)

    if has_aod_data:
        only_aod = aod_keys - aam_keys
        only_aam = aam_keys - aod_keys
        in_both = aod_keys & aam_keys
    else:
        only_aod = only_aam = in_both = set()

    vendors = []
    all_keys = sorted(aod_keys | aam_keys) if has_aod_data else sorted(aam_keys)
    for vk in all_keys:
        aod_info = aod_vendor_map.get(vk)
        aam_info = aam_vendor_map.get(vk)
        vendor_display = (aod_info or aam_info)["vendor"]

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


_SAAS_SUBTYPES = frozenset({
    "crm", "erp", "hcm", "idp", "itsm",
    "hr", "finance", "identity", "cmdb",
})

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


def _compare_sor_line_items(aod_run_id: str) -> dict:
    """Compare Farm SOR declarations and AOD SOR summary against AAM candidates."""
    from .sor_dispositions import get_sor_dispositions

    farm_sors = sb.select(
        "sor_declarations",
        filters={"aod_run_id": aod_run_id},
        columns="sor_id,domain,vendor,category,confidence,source",
    )

    handoff_rows = sb.select(
        "aod_handoff_log",
        filters={"aod_run_id": aod_run_id},
        order="handoff_timestamp.desc",
        limit=1,
    )
    aod_sor_vendors_raw = []
    if handoff_rows:
        meta_row = handoff_rows[0]
        raw_val = meta_row.get("aod_sor_vendors")
        if raw_val:
            try:
                aod_sor_vendors_raw = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
            except (json.JSONDecodeError, TypeError) as exc:
                _log.error(
                    "Corrupt aod_sor_vendors JSON for run %s — SOR reconciliation "
                    "will report all vendors as AAM-only: %s",
                    aod_run_id, exc,
                )

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

    candidates = sb.select("connection_candidates", filters={"aod_run_id": aod_run_id})
    aam_by_vendor: dict[str, dict] = {}
    for c in candidates:
        vk = (c.get("vendor_name") or "unknown").lower()
        cat = (c.get("category") or "unknown").lower()
        entry = aam_by_vendor.setdefault(vk, {
            "vendor_name": c.get("vendor_name"), "categories": {}, "total": 0,
        })
        entry["categories"][cat] = entry["categories"].get(cat, 0) + 1
        entry["total"] += 1

    line_items = []
    matched = category_mismatches = missing = 0
    checked: set[str] = set()

    def _build_item(vendor, domain, expected_cat, confidence, source):
        nonlocal matched, category_mismatches, missing
        vk = vendor.lower()
        aam_data = aam_by_vendor.get(vk)
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

    for row in farm_sors:
        vendor = row["vendor"]
        checked.add(vendor.lower())
        line_items.append(_build_item(
            vendor, row.get("domain", ""),
            (row.get("category") or "").lower(),
            row.get("confidence"), row.get("source") or "farm",
        ))

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


def _check_schema_completeness(aod_run_id: str) -> dict:
    """Find candidates missing key AOD-provided fields."""
    candidates = sb.select(
        "connection_candidates",
        filters={"aod_run_id": aod_run_id},
        columns="candidate_id,vendor_name,display_name,category,known_endpoints,preferred_modality,connected_via_plane",
    )

    issues = []
    aod_missing = {"vendor_name": 0, "display_name": 0,
                   "category": 0, "known_endpoints": 0,
                   "connected_via_plane": 0}
    enrichment_missing = {"preferred_modality": 0}
    total = 0

    for row in candidates:
        cid = row.get("candidate_id")
        vendor = row.get("vendor_name")
        display = row.get("display_name")
        cat = row.get("category")
        endpoints = row.get("known_endpoints")
        modality = row.get("preferred_modality")
        plane = row.get("connected_via_plane")
        total += 1
        missing_aod = []
        if not vendor or (vendor or "").lower() in ("unknown", ""):
            missing_aod.append("vendor_name")
            aod_missing["vendor_name"] += 1
        if not display or (display or "").lower() in ("unknown", ""):
            missing_aod.append("display_name")
            aod_missing["display_name"] += 1
        if not cat or (cat or "").lower() in ("unknown", ""):
            missing_aod.append("category")
            aod_missing["category"] += 1
        if not endpoints or endpoints in ("[]", "", "null"):
            missing_aod.append("known_endpoints")
            aod_missing["known_endpoints"] += 1
        if not plane or plane == "":
            aod_missing["connected_via_plane"] += 1
        if not modality or (modality or "").lower() in ("unknown", ""):
            enrichment_missing["preferred_modality"] += 1
        if missing_aod:
            issues.append({
                "candidate_id": cid, "vendor": vendor,
                "display_name": display, "missing_fields": missing_aod,
            })

    score = round((1 - len(issues) / max(total, 1)) * 100, 1)

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


def _check_pipe_schema_content(aod_run_id: str) -> dict:
    """Check whether declared pipes created from this run have real schema content.

    Validates that entity_scope, identity_keys, and schema_info are populated
    after inference — i.e. that DCL will receive actual field definitions,
    not empty placeholders.
    """
    candidates = sb.select(
        "connection_candidates",
        filters={"aod_run_id": aod_run_id},
        columns="candidate_id,vendor_name,matched_pipe_id",
    )

    pipe_ids = set()
    vendor_by_pipe: dict[str, str] = {}
    for c in candidates:
        pid = c.get("matched_pipe_id")
        if pid:
            pipe_ids.add(pid)
            vendor_by_pipe[pid] = c.get("vendor_name") or "unknown"

    if not pipe_ids:
        return {
            "total_pipes": 0,
            "pipes_with_fields": 0,
            "pipes_without_fields": 0,
            "field_coverage_pct": 0,
            "by_source": {},
            "missing_pipes": [],
            "has_issues": False,
        }

    all_pipes = sb.select("declared_pipes")
    pipes = [p for p in all_pipes if p.get("pipe_id") in pipe_ids]

    pipes_with = 0
    pipes_without = 0
    by_source: dict[str, int] = defaultdict(int)
    missing_pipes: list[dict] = []

    for p in pipes:
        pid = p["pipe_id"]
        es_raw = p.get("entity_scope")
        ik_raw = p.get("identity_keys")
        si_raw = p.get("schema_info")

        es = json.loads(es_raw) if isinstance(es_raw, str) else (es_raw or [])
        ik = json.loads(ik_raw) if isinstance(ik_raw, str) else (ik_raw or [])
        si = json.loads(si_raw) if isinstance(si_raw, str) else si_raw

        has_es = isinstance(es, list) and len(es) > 0
        has_ik = isinstance(ik, list) and len(ik) > 0
        has_si = isinstance(si, dict) and bool(si)
        fully_populated = has_es and has_ik and has_si

        if fully_populated:
            pipes_with += 1
            source = si.get("schema_version", "unknown")
            by_source[source] += 1
        else:
            pipes_without += 1
            missing_pipes.append({
                "pipe_id": pid,
                "display_name": p.get("display_name") or "",
                "source_system": p.get("source_system") or "",
                "vendor": vendor_by_pipe.get(pid, "unknown"),
                "entity_scope_count": len(es) if isinstance(es, list) else 0,
                "identity_keys_count": len(ik) if isinstance(ik, list) else 0,
                "has_schema_info": has_si,
            })

    total = pipes_with + pipes_without
    coverage = round((pipes_with / max(total, 1)) * 100, 1)

    return {
        "total_pipes": total,
        "pipes_with_fields": pipes_with,
        "pipes_without_fields": pipes_without,
        "field_coverage_pct": coverage,
        "by_source": dict(by_source),
        "missing_pipes": missing_pipes[:25],
        "has_issues": pipes_without > 0,
    }


def _check_duplicates(aod_run_id: str) -> dict:
    """Find candidates sharing vendor + display_name combination."""
    candidates = sb.select("connection_candidates", filters={"aod_run_id": aod_run_id})

    group_map: dict[tuple, list] = defaultdict(list)
    for c in candidates:
        key = (
            (c.get("vendor_name") or "unknown").lower(),
            (c.get("display_name") or "").lower(),
            (c.get("category") or "unknown").lower(),
        )
        group_map[key].append(c.get("candidate_id"))

    groups = []
    total_rows = 0
    for (vendor, display, cat), ids in sorted(group_map.items(), key=lambda x: -len(x[1])):
        if len(ids) <= 1:
            continue
        groups.append({
            "vendor": vendor, "display_name": display,
            "category": cat, "count": len(ids),
            "candidate_ids": ids,
        })
        total_rows += len(ids)

    return {
        "duplicate_groups": groups[:25],
        "total_groups": len(groups),
        "total_duplicate_rows": total_rows,
        "has_issues": len(groups) > 0,
    }


def get_aod_reconciliation(aod_run_id: str) -> dict:
    """
    Reconcile AOD handoff data with AAM storage.

    Delegates to focused sub-functions for each check, then assembles the
    full report.
    """
    summary = _get_handoff_summary(aod_run_id)
    if summary is None:
        return {"error": f"No handoff found for run {aod_run_id}",
                "aod_run_id": aod_run_id}

    vendor_check = _check_vendor_duplicates(aod_run_id)
    fabric_check = _compare_fabric_planes(aod_run_id)
    sor_check = _compare_sor_line_items(aod_run_id)
    completeness = _check_schema_completeness(aod_run_id)
    duplicates = _check_duplicates(aod_run_id)
    pipe_schema = _check_pipe_schema_content(aod_run_id)

    handoff_row = summary["handoff_row"]
    candidates_stored = summary["candidates_stored"]

    all_candidates = sb.select("connection_candidates", filters={"aod_run_id": aod_run_id})
    aod_origin_stored = sum(
        1 for c in all_candidates
        if not (c.get("asset_key") or "").startswith("infra:")
    )

    fabric_linked = sum(
        v.get("linked_candidates", 0) for v in fabric_check.get("vendors", [])
    )

    real_fabric_issues = fabric_check["mismatches"] if fabric_check["has_aod_data"] else 0
    real_sor_issues = sor_check["mismatches"] if sor_check["has_aod_data"] else 0
    schema_issues = completeness.get("incomplete_count", 0) if completeness.get("has_issues") else 0
    pipe_schema_issues = pipe_schema.get("pipes_without_fields", 0)
    issues_count = (
        len(vendor_check["case_duplicates"])
        + real_fabric_issues
        + real_sor_issues
        + schema_issues
        + duplicates["total_groups"]
        + pipe_schema_issues
    )

    return {
        "aod_run_id": aod_run_id,
        "snapshot_name": summary["snapshot_name"],
        "handoff_timestamp": handoff_row.get("handoff_timestamp"),
        "aod_sent": {
            "candidates": handoff_row.get("candidates_received"),
            "candidates_accepted": handoff_row.get("candidates_accepted"),
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
            "candidates_match": handoff_row.get("candidates_accepted") == aod_origin_stored,
            "discrepancy": (handoff_row.get("candidates_accepted") or 0) - aod_origin_stored,
        },
        "deep_checks": {
            "vendor_matching": vendor_check,
            "fabric_comparison": fabric_check,
            "sor_comparison": sor_check,
            "schema_completeness": completeness,
            "pipe_schema_content": pipe_schema,
            "duplicates": duplicates,
            "total_issues": issues_count,
        },
    }


def get_latest_aod_run() -> Optional[dict]:
    """Get the most recent AOD run information."""
    rows = sb.select(
        "aod_handoff_log",
        order="handoff_timestamp.desc",
        limit=1,
        columns="aod_run_id,snapshot_name,candidates_received,candidates_accepted,handoff_timestamp",
    )
    if rows:
        row = rows[0]
        return {
            "aod_run_id": row.get("aod_run_id"),
            "snapshot_name": row.get("snapshot_name"),
            "candidates_received": row.get("candidates_received"),
            "candidates_accepted": row.get("candidates_accepted"),
            "handoff_timestamp": row.get("handoff_timestamp"),
        }
    return None
