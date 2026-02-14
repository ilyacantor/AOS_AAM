"""Tests for DCL export — verifies unlinked candidates are exported, not silently dropped."""


def test_export_includes_unlinked_candidates(db):
    """Candidates without fabric_plane_id must appear in unlinked_connections[], not vanish."""
    from app.dcl_export import build_dcl_export

    # Create a fabric plane
    db.store_fabric_plane(
        {"plane_type": "IPAAS", "vendor": "mulesoft", "is_healthy": True},
        aod_run_id="run_1",
    )

    # One candidate linked to the plane
    db.create_candidate({
        "asset_key": "mulesoft.com",
        "vendor_name": "MuleSoft",
        "display_name": "MuleSoft - iPaaS",
        "category": "other",
        "status": "connected",
        "fabric_plane_id": "IPAAS:mulesoft",
        "aod_run_id": "run_1",
    })

    # Three SOR candidates — no fabric_plane_id
    for vendor, cat, key in [
        ("Salesforce", "crm", "salesforce.com"),
        ("ServiceNow", "itsm", "servicenow.com"),
        ("Workday", "hcm", "workday.com"),
    ]:
        db.create_candidate({
            "asset_key": key,
            "vendor_name": vendor,
            "display_name": vendor,
            "category": cat,
            "status": "connected",
            "aod_run_id": "run_1",
        })

    result = build_dcl_export(aod_run_id="run_1")

    # Fabric plane has 1 connection
    assert len(result.fabric_planes) == 1
    assert result.fabric_planes[0].connection_count == 1
    assert result.fabric_planes[0].connections[0].vendor == "MuleSoft"

    # Unlinked connections has 3
    assert len(result.unlinked_connections) == 3
    unlinked_vendors = {c.vendor for c in result.unlinked_connections}
    assert unlinked_vendors == {"Salesforce", "ServiceNow", "Workday"}

    # total_connections counts ALL of them
    assert result.total_connections == 4


def test_export_total_connections_matches_ui_pipe_count(db):
    """total_connections must equal the number of candidates — same count the UI shows."""
    from app.dcl_export import build_dcl_export

    for i in range(10):
        db.create_candidate({
            "asset_key": f"vendor{i}.com",
            "vendor_name": f"Vendor{i}",
            "display_name": f"Vendor {i}",
            "category": "crm",
            "status": "connected",
        })

    result = build_dcl_export()

    assert result.total_connections == 10
    assert len(result.unlinked_connections) == 10
    assert len(result.fabric_planes) == 0


def test_export_no_candidates_returns_empty(db):
    """Empty DB → zero everywhere, no crash."""
    from app.dcl_export import build_dcl_export

    result = build_dcl_export()

    assert result.total_connections == 0
    assert result.fabric_planes == []
    assert result.unlinked_connections == []
