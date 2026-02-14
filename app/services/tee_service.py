"""
TEE (Tee-off) Service — workflow enforcement for tee requests.
"""
from ..logger import get_logger
from ..db import get_tee_request, get_pipe, update_tee_request_status

_log = get_logger("services.tee")


def validate_tee_transition(tee_id: str, new_status: str, verification_method=None) -> tuple[dict, dict]:
    """
    Validate and execute a TEE status transition.

    Workflow: requested → approved → verified

    Returns (updated_tee, verification_info).
    Raises ValueError or RuntimeError on invalid transitions.
    """
    if new_status not in ("approved", "verified"):
        raise ValueError("Status must be 'approved' or 'verified'")

    tee_req = get_tee_request(tee_id)
    if not tee_req:
        raise LookupError("TEE request not found")

    current_status = tee_req.get("status")

    if new_status == "approved":
        if current_status != "requested":
            raise ValueError(
                f"Cannot approve: TEE request is in '{current_status}' status. "
                "Only 'requested' status can be approved."
            )

    elif new_status == "verified":
        if current_status != "approved":
            raise ValueError(
                f"Cannot verify: TEE request is in '{current_status}' status. "
                "Only 'approved' status can be verified. Approve the request first."
            )
        if not verification_method:
            raise ValueError(
                "Verification requires a verification_method "
                "(e.g., 'manual_test', 'automated_check', 'log_review')"
            )
        pipe = get_pipe(tee_req["pipe_id"])
        if not pipe:
            raise ValueError("Cannot verify: Associated pipe no longer exists")

    updated = update_tee_request_status(tee_id, new_status)
    if not updated:
        raise LookupError("TEE request not found")

    return dict(updated), tee_req
