"""
AAM Database Package — re-exports all domain functions for backward compatibility.
"""
from .connection import get_db, get_connection  # noqa: F401
from .schema import init_db  # noqa: F401
from .candidates import create_candidate, get_candidate, list_candidates, update_candidate_status  # noqa: F401
from .pipes import create_pipe, get_pipe, list_pipes, get_pipe_versions, update_pipe_with_version  # noqa: F401
from .drift import create_drift_event, get_drift_events, list_all_drift_events  # noqa: F401
from .observations import create_observation, get_observations_for_candidate, get_unprocessed_observations, mark_observation_processed  # noqa: F401
from .collectors import list_collectors, update_collector_last_run, create_collector_run, complete_collector_run, get_collector_run, list_collector_runs  # noqa: F401
from .drift_status import update_drift_status  # noqa: F401
from .candidate_match import update_candidate_match, update_candidate_deferred  # noqa: F401
from .tee import list_tee_requests, get_drift_event, get_tee_request, create_tee_request, update_tee_request_status  # noqa: F401
from .admin import reset_aod_state, clear_all_data, get_pipe_stats  # noqa: F401
from .topology import get_topology_data, get_topology_for_pipe, get_topology_for_fabric_plane  # noqa: F401
from .handoff import create_handoff_log, get_handoff_log, list_handoff_logs  # noqa: F401
from .policy import save_policy_manifest, get_active_policy_manifest, list_policy_manifests, get_candidates_by_aod_run  # noqa: F401
from .fabric_planes import store_fabric_plane, get_fabric_planes, find_fabric_plane_by_vendor  # noqa: F401
from .reconciliation import get_aod_reconciliation, get_latest_aod_run  # noqa: F401
from .stats import get_canonical_stats  # noqa: F401

# Re-export DATABASE for monkeypatching in tests
from .connection import DATABASE  # noqa: F401
