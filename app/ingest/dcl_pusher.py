"""AAM -> DCL HTTP ingest pusher.

POSTs batches of semantic triples to DCL's `/api/dcl/ingest-triples` endpoint.
No fallback to direct-PG: if DCL is unreachable or rejects the batch, the
ingest run fails loudly with an informative error per CLAUDE.md silent-fallback
prohibition.

Request shape matches dcl/backend/api/routes/ingest_triples.py:78-88
(IngestRequest):
    tenant_id, dcl_ingest_id, entity_id, run_mode, triples[],
    source_run_tag (opt), source_farm_manifest_id (opt), source_rows (opt),
    snapshot_name (opt)

Each TriplePayload (dcl/.../ingest_triples.py:57-75):
    entity_id, concept, property, value, source_system, confidence_score,
    confidence_tier (required), plus optional period, currency, unit,
    source_table, source_field, pipe_id, canonical_id, resolution_method,
    resolution_confidence, fabric_plane, fabric_product.

Resolution_method is constrained by DCL to {deterministic, fuzzy, manual} —
the caller must translate AAM's richer vocabulary before pushing. See
app/ingest/triple_builder.py _RESOLUTION_METHOD_TO_PG.

Batching: every push uses ?replace=false (no idempotency conflict) — AAM
mints a fresh dcl_ingest_id per ingest run, so a brand-new run_id is always
in play. If the batch is larger than DCL_PUSH_BATCH_SIZE (default 500) the
push slices it: batch 0 is sent as the establishing call, batches 1..N are
sent with ?append=true to add to the same run.

Retries: 3 attempts with exponential backoff (100ms, 200ms, 400ms) for 5xx
and network failures only. 4xx errors raise immediately — no retry on
validation rejection.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx

_log = logging.getLogger("aam.ingest.dcl_pusher")


_DEFAULT_BATCH_SIZE = int(os.environ.get("AAM_DCL_PUSH_BATCH_SIZE", "500"))
_DEFAULT_TIMEOUT_S = float(os.environ.get("AAM_DCL_PUSH_TIMEOUT_S", "30"))
_DEFAULT_MAX_RETRIES = 3


class DCLPushError(RuntimeError):
    """Raised when the DCL ingest-triples endpoint rejects or is unreachable.

    Carries the HTTP status (when applicable) and the response body so the
    operator log shows exactly why the push failed.
    """

    def __init__(self, message: str, *, status_code: Optional[int] = None,
                 body: Optional[str] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class DCLPushRequest:
    """All parameters DCL needs for one ingest-triples call.

    triples are dicts shaped to DCL's TriplePayload — see triple_builder.py
    for the construction. The pusher does not mutate them.
    """
    tenant_id: str
    entity_id: str
    dcl_ingest_id: str
    triples: list[dict[str, Any]]
    run_mode: Literal["Dev", "Prod"] = "Dev"
    source_run_tag: Optional[str] = None
    source_rows: Optional[int] = None


@dataclass
class DCLPushResult:
    """One ingest run's outcome — flat enough for the API response."""
    dcl_ingest_id: str
    entity_id: str
    triples_written: int
    latency_ms: int
    batch_count: int = 0


class DCLPusher:
    """HTTP client for AAM -> DCL semantic-triple ingest.

    base_url comes from app.config.settings (the existing DCL_URL contract)
    so AAM has one canonical DCL endpoint per process. No per-call URL
    override — that would invite multi-target drift.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        if not base_url:
            raise DCLPushError("DCLPusher requires a non-empty base_url")
        self.base_url = base_url.rstrip("/")
        self.ingest_url = f"{self.base_url}/api/dcl/ingest-triples"
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.batch_size = max(1, batch_size)

    def push(self, req: DCLPushRequest) -> DCLPushResult:
        """POST the triples to DCL. Raises DCLPushError on any failure.

        Batches over self.batch_size are sliced; batch 0 uses ?replace=false,
        batches 1..N use ?append=true to land on the same dcl_ingest_id.
        """
        if not req.triples:
            return DCLPushResult(
                dcl_ingest_id=req.dcl_ingest_id,
                entity_id=req.entity_id,
                triples_written=0,
                latency_ms=0,
                batch_count=0,
            )

        # Slice into batches
        batches = [
            req.triples[i:i + self.batch_size]
            for i in range(0, len(req.triples), self.batch_size)
        ]
        total = len(req.triples)
        _log.info(
            "dcl_pusher: pushing %d triples in %d batch(es) to %s "
            "(tenant_id=%s entity_id=%s dcl_ingest_id=%s)",
            total, len(batches), self.ingest_url,
            req.tenant_id, req.entity_id, req.dcl_ingest_id,
        )

        t_start = time.monotonic()
        pushed = 0

        with httpx.Client(timeout=self.timeout_s) as client:
            for batch_idx, batch in enumerate(batches):
                append = batch_idx > 0
                pushed += self._send_batch(
                    client, req, batch, append=append, batch_idx=batch_idx,
                )

        latency_ms = int((time.monotonic() - t_start) * 1000)
        _log.info(
            "dcl_pusher: push complete dcl_ingest_id=%s triples_written=%d "
            "batches=%d latency_ms=%d",
            req.dcl_ingest_id, pushed, len(batches), latency_ms,
        )
        return DCLPushResult(
            dcl_ingest_id=req.dcl_ingest_id,
            entity_id=req.entity_id,
            triples_written=pushed,
            latency_ms=latency_ms,
            batch_count=len(batches),
        )

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _build_body(
        self,
        req: DCLPushRequest,
        triples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "tenant_id": req.tenant_id,
            "entity_id": req.entity_id,
            "dcl_ingest_id": req.dcl_ingest_id,
            "run_mode": req.run_mode,
            "triples": triples,
        }
        if req.source_run_tag is not None:
            body["source_run_tag"] = req.source_run_tag
        if req.source_rows is not None:
            body["source_rows"] = req.source_rows
        return body

    def _send_batch(
        self,
        client: httpx.Client,
        req: DCLPushRequest,
        batch: list[dict[str, Any]],
        *,
        append: bool,
        batch_idx: int,
    ) -> int:
        url = self.ingest_url + ("?append=true" if append else "")
        body = self._build_body(req, batch)
        backoff_s = 0.1  # 100ms, then 200, then 400
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = client.post(url, json=body)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                last_exc = exc
                _log.warning(
                    "dcl_pusher: network error attempt %d/%d batch=%d "
                    "url=%s err=%s (waited %dms)",
                    attempt + 1, self.max_retries + 1, batch_idx,
                    url, exc, duration_ms,
                )
                if attempt < self.max_retries:
                    time.sleep(backoff_s)
                    backoff_s *= 2
                    continue
                raise DCLPushError(
                    f"AAM could not reach DCL at {url} — {type(exc).__name__}: "
                    f"{exc}. Exhausted {self.max_retries} retries. "
                    f"AAM ingest aborted (no direct-PG fallback)."
                ) from exc

            duration_ms = int((time.monotonic() - t0) * 1000)
            if 200 <= resp.status_code < 300:
                count = self._parse_count(resp, fallback=len(batch))
                _log.info(
                    "dcl_pusher: batch %d OK status=%d count=%d latency_ms=%d "
                    "append=%s",
                    batch_idx, resp.status_code, count, duration_ms, append,
                )
                return count

            # 4xx — caller error, do not retry
            if 400 <= resp.status_code < 500:
                _log.error(
                    "dcl_pusher: batch %d rejected status=%d url=%s body=%s",
                    batch_idx, resp.status_code, url, resp.text[:500],
                )
                raise DCLPushError(
                    f"DCL rejected AAM ingest batch {batch_idx} "
                    f"(status={resp.status_code}) at {url}. "
                    f"Response body: {resp.text[:500]}",
                    status_code=resp.status_code,
                    body=resp.text,
                )

            # 5xx — retry
            last_exc = DCLPushError(
                f"DCL returned {resp.status_code}", status_code=resp.status_code,
                body=resp.text,
            )
            _log.warning(
                "dcl_pusher: batch %d 5xx attempt %d/%d status=%d "
                "url=%s body=%s",
                batch_idx, attempt + 1, self.max_retries + 1, resp.status_code,
                url, resp.text[:300],
            )
            if attempt < self.max_retries:
                time.sleep(backoff_s)
                backoff_s *= 2
                continue
            raise DCLPushError(
                f"DCL kept returning {resp.status_code} on batch {batch_idx} "
                f"after {self.max_retries} retries. URL={url} "
                f"Body={resp.text[:500]}",
                status_code=resp.status_code,
                body=resp.text,
            )

        # Defensive — loop should have either returned or raised already.
        raise DCLPushError(
            f"dcl_pusher: batch {batch_idx} exhausted retries without "
            f"a terminal outcome (last_exc={last_exc!r})"
        )

    @staticmethod
    def _parse_count(resp: httpx.Response, *, fallback: int) -> int:
        """Pull triples_written from DCL's IngestResponse. Fallback to batch
        length when the body is missing or malformed.
        """
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return fallback
        if not isinstance(data, dict):
            return fallback
        n = data.get("triples_written")
        if isinstance(n, int):
            return n
        n = data.get("triple_count")
        if isinstance(n, int):
            return n
        return fallback


def make_dcl_ingest_id() -> str:
    """Mint a fresh UUID for one ingest run. Centralized so the orchestrator
    and pusher share a single source of identity.
    """
    return str(uuid.uuid4())
