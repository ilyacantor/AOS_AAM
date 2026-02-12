"""
Export Service — CSV export and reconciliation report generation.
"""
import csv
import io

from ..logger import get_logger
from ..db import get_aod_reconciliation

_log = get_logger("services.export")


def build_reconciliation_csv(aod_run_id: str) -> tuple[str, str]:
    """
    Build a CSV reconciliation summary for an AOD run.

    Returns (csv_content, filename).
    Raises ValueError if the run is not found.
    """
    data = get_aod_reconciliation(aod_run_id)
    if data.get("error"):
        raise ValueError(data["error"])

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["AAM Reconciliation Summary"])
    writer.writerow(["Run ID", data["aod_run_id"]])
    writer.writerow(["Snapshot", data.get("snapshot_name", "")])
    writer.writerow(["Timestamp", data.get("handoff_timestamp", "")])
    writer.writerow(["AOD Candidates Sent", data["aod_sent"]["candidates_accepted"]])
    writer.writerow(["AAM Candidates Stored", data["aam_stored"]["candidates"]])
    writer.writerow([])

    deep = data.get("deep_checks", {})

    writer.writerow(["=" * 60])
    writer.writerow(["CHECK", "STATUS", "ISSUE COUNT"])
    writer.writerow(["=" * 60])

    checks = [
        ("Vendor Name Consistency", deep.get("vendor_matching", {})),
        ("Candidate Row Integrity", deep.get("candidate_rows", {})),
        ("Fabric Plane Comparison", deep.get("fabric_comparison", {})),
        ("SOR Vendor Comparison", deep.get("sor_comparison", {})),
        ("Schema Completeness", deep.get("schema_completeness", {})),
        ("Duplicate Detection", deep.get("duplicates", {})),
    ]
    for name, check in checks:
        has_issues = check.get("has_issues", False)
        status = "FAIL" if has_issues else "PASS"
        writer.writerow([name, status])

    writer.writerow([])

    # Vendor case duplicates
    vm = deep.get("vendor_matching", {})
    case_dups = vm.get("case_duplicates", [])
    if case_dups:
        writer.writerow(["--- VENDOR CASE DUPLICATES ---"])
        writer.writerow(["Canonical Name", "Variants", "Total Count"])
        for d in case_dups:
            variants = "; ".join([f'{v["name"]} ({v["count"]})' for v in d["variants"]])
            writer.writerow([d["canonical"], variants, d["total"]])
        writer.writerow([])

    # Candidate rows
    cr = deep.get("candidate_rows", {})
    for label, key in [("UNCONNECTED CANDIDATES", "unconnected"), ("BLOCKED CANDIDATES", "blocked")]:
        items = cr.get(key, [])
        if items:
            writer.writerow([f"--- {label} ---"])
            writer.writerow(["Candidate ID", "Vendor", "Display Name", "Category", "Status"])
            for c in items:
                writer.writerow([c["candidate_id"], c.get("vendor", ""), c.get("display_name", ""), c.get("category", ""), c.get("status", "")])
            writer.writerow([])

    # Fabric comparison
    fc = deep.get("fabric_comparison", {})
    fc_vendors = fc.get("vendors", [])
    has_aod_fabric = fc.get("has_aod_data", False)
    if fc_vendors:
        writer.writerow(["--- FABRIC PLANE COMPARISON ---"])
        if not has_aod_fabric:
            writer.writerow(["NOTE: Fabric planes derived from AOD candidate data."])
        writer.writerow(["Vendor", "AOD Type", "AAM Type", "Status"])
        for v in fc_vendors:
            writer.writerow([v["vendor"], v.get("aod_plane_type", "-"), v.get("aam_plane_type", "-"), v["status"]])
        writer.writerow([])

    # SOR ingestion/classification
    sc_sor = deep.get("sor_comparison", {})
    sor_items = sc_sor.get("line_items", [])
    has_aod_sor = sc_sor.get("has_aod_data", False)
    if sor_items:
        writer.writerow(["--- SOR INGESTION & CLASSIFICATION ---"])
        writer.writerow([f"Accuracy: {sc_sor.get('ingestion_accuracy', 0)}%",
                         f"Matched: {sc_sor.get('matched', 0)}",
                         f"Mismatches: {sc_sor.get('category_mismatches', 0)}",
                         f"Missing: {sc_sor.get('missing', 0)}"])
        writer.writerow(["Source", "Domain", "Vendor", "Expected Category", "AAM Category", "Candidates", "Verdict"])
        for item in sor_items:
            writer.writerow([
                item.get("source", ""),
                item.get("domain", ""),
                item["vendor"],
                item.get("expected_category", "-"),
                item.get("aam_category", "-"),
                item.get("aam_count", 0),
                item["verdict"],
            ])
        writer.writerow([])

    # Schema completeness
    sc = deep.get("schema_completeness", {})
    field_counts = sc.get("field_missing_counts", {})
    if any(v > 0 for v in field_counts.values()):
        writer.writerow(["--- SCHEMA COMPLETENESS ---"])
        writer.writerow(["Field", "Missing Count", "Source"])
        field_sources = {
            "vendor_name": "AOD (data quality)",
            "display_name": "AOD (data quality)",
            "category": "AOD (data quality)",
            "known_endpoints": "AOD (optional)",
            "preferred_modality": "AAM enrichment (not from AOD)",
            "connected_via_plane": "AAM enrichment (not from AOD)",
        }
        for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
            if count > 0:
                source = field_sources.get(field, "Unknown")
                writer.writerow([field, count, source])
        writer.writerow([])

        incomplete = sc.get("incomplete_candidates", [])
        if incomplete:
            writer.writerow(["--- INCOMPLETE CANDIDATES (sample) ---"])
            writer.writerow(["Candidate ID", "Vendor", "Display Name", "Missing Fields"])
            for c in incomplete:
                aod_missing = [f for f in c.get("missing_fields", []) if f not in ("preferred_modality", "connected_via_plane")]
                if aod_missing:
                    writer.writerow([c["candidate_id"], c.get("vendor", ""), c.get("display_name", ""), "; ".join(aod_missing)])
        writer.writerow([])

    # Duplicates
    dd = deep.get("duplicates", {})
    dup_groups = dd.get("duplicate_groups", [])
    if dup_groups:
        writer.writerow(["--- DUPLICATE CANDIDATES ---"])
        writer.writerow(["Vendor", "Display Name", "Category", "Count"])
        for g in dup_groups:
            writer.writerow([g["vendor"], g["display_name"], g["category"], g["count"]])
        writer.writerow([])

    # Root cause analysis
    writer.writerow(["=" * 60])
    writer.writerow(["ROOT CAUSE ANALYSIS"])
    writer.writerow(["=" * 60])
    writer.writerow([])

    rca_lines = []
    if field_counts.get("preferred_modality", 0) > 0 or field_counts.get("connected_via_plane", 0) > 0:
        rca_lines.append("EXPECTED: preferred_modality and connected_via_plane are AAM-enrichment fields NOT provided by AOD.")
        rca_lines.append("  These are populated during operator assignment or inference - not a data quality issue.")
    if field_counts.get("vendor_name", 0) > 0:
        rca_lines.append(f"DATA QUALITY: {field_counts['vendor_name']} candidates have unknown vendor_name. AOD could not identify vendor.")
    if not has_aod_fabric and len(fc.get("only_in_aam", [])) > 0:
        rca_lines.append(f"NOTE: {len(fc.get('only_in_aam', []))} fabric planes show as 'only in AAM' - derived from AOD candidate data.")
        rca_lines.append("  Not a real mismatch.")
    if has_aod_sor and sc_sor.get("mismatches", 0) > 0:
        only_aod_count = len(sc_sor.get("only_in_aod", []))
        if only_aod_count > 0:
            rca_lines.append(f"NOTE: {only_aod_count} SOR vendors from AOD show as 'not in AAM' - inference has not been run yet.")
            rca_lines.append("  Run inference (POST /api/aam/infer) to create declared pipes from candidates.")

    if not rca_lines:
        rca_lines.append("No significant root causes identified. Data is clean.")

    for line in rca_lines:
        writer.writerow([line])

    csv_content = output.getvalue()
    output.close()

    snapshot = data.get("snapshot_name", aod_run_id)
    filename = f"reconciliation_{snapshot}_{aod_run_id}.csv"
    return csv_content, filename
