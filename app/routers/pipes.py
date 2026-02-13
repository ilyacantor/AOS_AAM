"""
Pipes Router — CRUD operations for declared data pipes.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

from ..db import get_pipe_or_candidate, list_candidates_as_pipes, get_pipe_versions, get_drift_events

router = APIRouter(prefix="/api/pipes", tags=["Pipes"])


@router.get("")
async def get_all_pipes(
    source_system: Optional[str] = Query(None),
    fabric_plane: Optional[str] = Query(None),
):
    """List all declared pipes."""
    pipes = list_candidates_as_pipes(source_system=source_system, fabric_plane=fabric_plane)
    return {"pipes": pipes, "count": len(pipes)}


@router.get("/{pipe_id}")
async def get_single_pipe(pipe_id: str):
    """Get a single pipe by ID."""
    pipe = get_pipe_or_candidate(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")
    return pipe


@router.get("/{pipe_id}/versions")
async def get_pipe_version_history(pipe_id: str):
    """Get version history for a pipe."""
    pipe = get_pipe_or_candidate(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")
    versions = get_pipe_versions(pipe_id)
    return {"pipe_id": pipe_id, "versions": versions, "count": len(versions)}


@router.get("/{pipe_id}/drift")
async def get_pipe_drift_events(pipe_id: str):
    """Get drift events for a pipe."""
    pipe = get_pipe_or_candidate(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")
    events = get_drift_events(pipe_id)
    return {"pipe_id": pipe_id, "drift_events": events, "count": len(events)}
