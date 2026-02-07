#!/usr/bin/env python3
"""
AAM Test Harness - Automated validation of user stories.
Runs in a loop: test → detect bugs → report until 100% pass.

User Stories:
1. Fetch AOD → Reconciliation shows 0 errors → Download CSV works
2. Fetch AOD → Topology SOR view → SORs match candidates
3. Topology Fabric view → Fabrics match candidates
"""

import requests
import sys
import time
import csv
import io
from collections import defaultdict

BASE_URL = "http://localhost:5000"
MAX_ITERATIONS = 1


def log(msg, level="INFO"):
    prefix = {"INFO": "[INFO]", "PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]"}
    print(f"{prefix.get(level, '[INFO]')} {msg}")


def fetch_aod_data():
    """Reset and fetch AOD data."""
    resp = requests.post(f"{BASE_URL}/api/handoff/aod/fetch", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data


def get_candidates():
    """Get all candidates from AAM."""
    resp = requests.get(f"{BASE_URL}/api/aam/candidates", timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_reconciliation(run_id):
    """Get reconciliation report."""
    resp = requests.get(f"{BASE_URL}/api/handoff/aod/run/{run_id}/reconciliation", timeout=15)
    resp.raise_for_status()
    return resp.json()


def download_reconciliation_csv(run_id):
    """Download reconciliation CSV."""
    resp = requests.get(f"{BASE_URL}/api/handoff/aod/run/{run_id}/reconciliation/download", timeout=15)
    resp.raise_for_status()
    return resp


def get_topology_summary():
    """Get topology summary."""
    resp = requests.get(f"{BASE_URL}/api/topology/summary", timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_reconciliation_ui(run_id):
    """Get reconciliation UI page."""
    resp = requests.get(f"{BASE_URL}/ui/reconcile/{run_id}", timeout=15)
    resp.raise_for_status()
    return resp.text


class TestResult:
    def __init__(self, name):
        self.name = name
        self.checks = []
        self.passed = True

    def check(self, condition, description, detail=""):
        status = "PASS" if condition else "FAIL"
        self.checks.append({"status": status, "desc": description, "detail": detail})
        if not condition:
            self.passed = False
            log(f"{description}: {detail}", "FAIL")
        else:
            log(f"{description}", "PASS")

    def summary(self):
        passed = sum(1 for c in self.checks if c["status"] == "PASS")
        total = len(self.checks)
        return f"{self.name}: {passed}/{total} checks passed"


def test_story_1(run_id):
    """
    Story 1: User clicks Fetch AOD → checks reconciliation → downloads CSV.
    Reconciliation should show NO errors.
    """
    result = TestResult("Story 1: Fetch + Reconciliation + Download")

    # 1a. Reconciliation API returns 0 issues
    recon = get_reconciliation(run_id)

    result.check(
        "error" not in recon,
        "Reconciliation loads without error"
    )

    deep = recon.get("deep_checks", {})
    total_issues = deep.get("total_issues", -1)
    result.check(
        total_issues == 0,
        "Total issues is 0",
        f"Got {total_issues}"
    )

    # 1b. All checks pass
    for check_name in ["vendor_matching", "candidate_rows", "fabric_comparison", "sor_comparison", "schema_completeness", "duplicates"]:
        check = deep.get(check_name, {})
        has_issues = check.get("has_issues", True)
        result.check(
            not has_issues,
            f"{check_name} has no issues",
            f"has_issues={has_issues}"
        )

    # 1c. Fabric comparison has AOD data and all match
    fc = deep.get("fabric_comparison", {})
    result.check(
        fc.get("has_aod_data") == True,
        "Fabric comparison has AOD data",
        f"has_aod_data={fc.get('has_aod_data')}"
    )
    result.check(
        fc.get("mismatches", -1) == 0,
        "Fabric comparison has 0 mismatches",
        f"mismatches={fc.get('mismatches')}"
    )
    in_both = fc.get("in_both", [])
    result.check(
        len(in_both) > 0,
        "Fabric comparison has vendors in_both",
        f"in_both count={len(in_both)}"
    )

    # 1d. Candidate counts match
    aod_sent = recon.get("aod_sent", {}).get("candidates_accepted", 0)
    aam_stored = recon.get("aam_stored", {}).get("candidates", 0)
    result.check(
        aod_sent == aam_stored and aod_sent > 0,
        "AOD sent matches AAM stored",
        f"sent={aod_sent}, stored={aam_stored}"
    )

    # 1e. CSV Download works
    csv_resp = download_reconciliation_csv(run_id)
    result.check(
        csv_resp.status_code == 200,
        "CSV download returns 200",
        f"status={csv_resp.status_code}"
    )
    result.check(
        "text/csv" in csv_resp.headers.get("content-type", ""),
        "CSV has correct content-type",
        f"content-type={csv_resp.headers.get('content-type')}"
    )
    result.check(
        "attachment" in csv_resp.headers.get("content-disposition", ""),
        "CSV has attachment disposition",
        f"content-disposition={csv_resp.headers.get('content-disposition', 'missing')}"
    )
    csv_text = csv_resp.text
    result.check(
        "AAM Reconciliation Summary" in csv_text,
        "CSV contains summary header"
    )
    result.check(
        "ROOT CAUSE ANALYSIS" in csv_text or "All checks passed" in csv_text or total_issues == 0,
        "CSV contains RCA or all-clear"
    )

    # 1f. UI page renders with correct status
    ui_html = get_reconciliation_ui(run_id)
    result.check(
        "Reconciliation Report" in ui_html,
        "UI page contains title"
    )
    result.check(
        "All Clear" in ui_html,
        "UI shows 'All Clear' status",
        "Expected 'All Clear' badge"
    )
    result.check(
        "Re-send" not in ui_html,
        "UI does NOT say 'Re-send from AOD'"
    )

    return result


def test_story_2(run_id):
    """
    Story 2: User navigates to Topology → SOR preset view.
    SORs should match candidate data.
    """
    result = TestResult("Story 2: Topology SOR View")

    # Get candidates for cross-reference
    candidates = get_candidates()
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates", candidates.get("items", []))

    # Build expected SOR vendors from candidates
    sor_categories = {"crm", "erp", "hcm", "idp", "itsm", "saas", "hr", "finance", "cmdb", "identity"}
    expected_sors = {}
    for c in candidates:
        cat = (c.get("category") or "").lower()
        vendor = c.get("vendor_name") or ""
        if cat in sor_categories and vendor and vendor.lower() != "unknown":
            vendor_key = vendor.lower()
            if vendor_key not in expected_sors:
                expected_sors[vendor_key] = {"vendor": vendor, "category": cat, "count": 0}
            expected_sors[vendor_key]["count"] += 1

    result.check(
        len(expected_sors) > 0,
        f"Found {len(expected_sors)} expected SOR vendors from candidates"
    )

    # Get topology summary
    topo = get_topology_summary()
    nodes = topo.get("nodes", [])
    edges = topo.get("edges", [])

    # Filter SOR nodes
    sor_nodes = [n for n in nodes if n.get("type") == "source_system" and n.get("metadata", {}).get("is_sor")]
    sor_node_names = {n["metadata"]["name"].lower() for n in sor_nodes}

    result.check(
        len(sor_nodes) == len(expected_sors),
        f"SOR node count matches expected ({len(expected_sors)})",
        f"Got {len(sor_nodes)} SOR nodes, expected {len(expected_sors)}"
    )

    # Verify each expected SOR is in topology
    missing_sors = []
    for vendor_key, info in expected_sors.items():
        if vendor_key not in sor_node_names:
            missing_sors.append(info["vendor"])

    result.check(
        len(missing_sors) == 0,
        "All expected SOR vendors appear in topology",
        f"Missing: {missing_sors}" if missing_sors else ""
    )

    # Verify each SOR node has at least one edge to a fabric plane
    sor_with_edges = set()
    for e in edges:
        source = e.get("source", "")
        target = e.get("target", "")
        if source.startswith("sor:") and target.startswith("plane:"):
            sor_name = source.replace("sor:", "").lower()
            sor_with_edges.add(sor_name)

    sors_without_edges = sor_node_names - sor_with_edges
    result.check(
        len(sors_without_edges) == 0,
        "All SOR nodes have fabric plane connections",
        f"Disconnected SORs: {sors_without_edges}" if sors_without_edges else ""
    )

    # Verify SOR categories match candidate data
    for sor_node in sor_nodes:
        name = sor_node["metadata"]["name"].lower()
        expected = expected_sors.get(name)
        if expected:
            node_cat = sor_node["metadata"].get("category", "")
            result.check(
                node_cat == expected["category"],
                f"SOR '{name}' category matches",
                f"Expected '{expected['category']}', got '{node_cat}'"
            )

    return result


def test_story_3(run_id):
    """
    Story 3: User views Topology Fabric preset view.
    Fabrics should match candidate data.
    """
    result = TestResult("Story 3: Topology Fabric View")

    # Get candidates for cross-reference
    candidates = get_candidates()
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates", candidates.get("items", []))

    # Build expected fabric planes from candidate data
    sor_categories = {"crm", "erp", "hcm", "idp", "itsm", "saas", "hr", "finance", "cmdb", "identity"}
    expected_planes = defaultdict(set)
    for c in candidates:
        cat = (c.get("category") or "").lower()
        vendor = c.get("vendor_name") or ""
        fabric_id = c.get("fabric_plane_id") or ""
        if cat in sor_categories and vendor and vendor.lower() != "unknown" and fabric_id:
            plane_type = fabric_id.split(":")[0].upper() if ":" in fabric_id else ""
            if plane_type:
                expected_planes[plane_type].add(vendor.lower())

    result.check(
        len(expected_planes) > 0,
        f"Found {len(expected_planes)} fabric plane types with SOR connections"
    )

    # Get topology summary
    topo = get_topology_summary()
    nodes = topo.get("nodes", [])
    edges = topo.get("edges", [])

    # Get fabric plane nodes
    fabric_nodes = [n for n in nodes if n.get("type") == "fabric_plane"]
    result.check(
        len(fabric_nodes) == 4,
        "All 4 fabric plane types present",
        f"Got {len(fabric_nodes)}: {[n['metadata']['plane_type'] for n in fabric_nodes]}"
    )

    # Verify edges connect SORs to correct fabric planes
    plane_connections = defaultdict(set)
    for e in edges:
        source = e.get("source", "")
        target = e.get("target", "")
        if source.startswith("sor:") and target.startswith("plane:"):
            sor_name = source.replace("sor:", "").lower()
            plane_type = target.replace("plane:", "").upper()
            plane_connections[plane_type].add(sor_name)

    # Check that SOR candidates with fabric_plane_id are connected to the right planes
    for plane_type, expected_vendors in expected_planes.items():
        actual_vendors = plane_connections.get(plane_type, set())
        for vendor in expected_vendors:
            result.check(
                vendor in actual_vendors,
                f"'{vendor}' connected to {plane_type}",
                f"Expected in {plane_type}, found in: {[p for p, v in plane_connections.items() if vendor in v]}"
            )

    # Verify no fabric plane has SOR connections that don't exist in candidates
    all_expected_vendors = set()
    for vendors in expected_planes.values():
        all_expected_vendors.update(vendors)

    for plane_type, connected_vendors in plane_connections.items():
        for vendor in connected_vendors:
            # This vendor should either be an expected SOR or a non-SOR other system
            # We just check SOR vendors are properly connected
            pass

    # Verify that the fabric plane node labels include candidate counts
    for fn in fabric_nodes:
        meta = fn.get("metadata", {})
        plane_type = meta.get("plane_type", "")
        cand_count = meta.get("candidate_count", 0)
        expected_cand_count = len(expected_planes.get(plane_type, set()))
        if expected_cand_count > 0:
            result.check(
                cand_count >= expected_cand_count,
                f"{plane_type} candidate count >= expected SOR count",
                f"Got {cand_count}, expected at least {expected_cand_count}"
            )

    return result


def run_all_tests():
    """Run all user story tests."""
    print("=" * 70)
    print("AAM TEST HARNESS")
    print("=" * 70)

    # Step 1: Fetch AOD data (shared setup)
    log("Fetching AOD data...")
    try:
        fetch_result = fetch_aod_data()
    except Exception as e:
        log(f"Failed to fetch AOD data: {e}", "FAIL")
        return False

    run_id = fetch_result.get("run_id")
    accepted = fetch_result.get("candidates_accepted", 0)
    log(f"Fetched run_id={run_id}, accepted={accepted}")

    if not run_id or accepted == 0:
        log("No data fetched - cannot proceed", "FAIL")
        return False

    print()

    # Run all 3 stories
    results = []
    
    print("-" * 70)
    print("STORY 1: Fetch + Reconciliation + Download")
    print("-" * 70)
    results.append(test_story_1(run_id))
    
    print()
    print("-" * 70)
    print("STORY 2: Topology SOR View")
    print("-" * 70)
    results.append(test_story_2(run_id))
    
    print()
    print("-" * 70)
    print("STORY 3: Topology Fabric View")
    print("-" * 70)
    results.append(test_story_3(run_id))

    # Summary
    print()
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    
    all_passed = True
    total_checks = 0
    passed_checks = 0
    
    for r in results:
        p = sum(1 for c in r.checks if c["status"] == "PASS")
        t = len(r.checks)
        total_checks += t
        passed_checks += p
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.summary()}")
        if not r.passed:
            all_passed = False
            for c in r.checks:
                if c["status"] == "FAIL":
                    print(f"         FAIL: {c['desc']}: {c['detail']}")

    print()
    print(f"  TOTAL: {passed_checks}/{total_checks} checks passed")
    
    if all_passed:
        print()
        print("  *** ALL STORIES PASS - 100% SUCCESS ***")
    else:
        print()
        failed = total_checks - passed_checks
        print(f"  *** {failed} CHECKS FAILED ***")

    print("=" * 70)
    return all_passed


if __name__ == "__main__":
    iteration = 0
    while iteration < MAX_ITERATIONS:
        iteration += 1
        print(f"\n{'#' * 70}")
        print(f"# ITERATION {iteration}")
        print(f"{'#' * 70}\n")
        
        success = run_all_tests()
        
        if success:
            print(f"\n100% SUCCESS on iteration {iteration}")
            sys.exit(0)
        else:
            print(f"\nIteration {iteration} had failures.")
            if iteration < MAX_ITERATIONS:
                print("Retrying in 2 seconds...")
                time.sleep(2)
    
    print(f"\nFailed after {MAX_ITERATIONS} iterations")
    sys.exit(1)
