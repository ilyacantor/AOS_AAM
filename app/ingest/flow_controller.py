"""Flow Controller — dedup, batch assembly, backpressure between transport
and the triple builder.

Dedup key: (pipe_id, record_key, offset).
Batching: hand off when batch_size hit, or when finalize() is called.
Backpressure: drop with explicit reject (logged) if internal buffer would
exceed max_buffer; never silent-drop.

Metrics: received, deduped, batched, rejected. Latency is recorded externally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from ..transport.http import TransportRecord

_log = logging.getLogger("aam.ingest.flow_controller")


@dataclass
class FlowMetrics:
    received: int = 0
    deduped: int = 0
    batched: int = 0
    rejected: int = 0


class FlowController:
    """Buffer records, dedup by composite key, hand to a batch consumer."""

    def __init__(
        self,
        batch_size: int = 50,
        max_buffer: int = 10_000,
        batch_consumer: Callable[[list[TransportRecord]], None] | None = None,
    ):
        if batch_size < 1:
            raise ValueError("FlowController batch_size must be >= 1")
        if max_buffer < batch_size:
            raise ValueError("FlowController max_buffer must be >= batch_size")
        self.batch_size = batch_size
        self.max_buffer = max_buffer
        self.batch_consumer = batch_consumer
        self._seen: set[tuple[str, str, str]] = set()
        self._buffer: list[TransportRecord] = []
        self.metrics = FlowMetrics()

    def submit(self, record: TransportRecord) -> bool:
        """Add one record. Returns True if accepted."""
        self.metrics.received += 1
        key = (record.pipe_id, record.record_key, record.offset)
        if key in self._seen:
            self.metrics.deduped += 1
            return False
        if len(self._buffer) >= self.max_buffer:
            self.metrics.rejected += 1
            _log.warning("flow_controller: buffer full max=%d pipe_id=%s record_key=%s", self.max_buffer, record.pipe_id, record.record_key)
            return False
        self._seen.add(key)
        self._buffer.append(record)
        if len(self._buffer) >= self.batch_size:
            self._flush()
        return True

    def submit_many(self, records: list[TransportRecord]) -> int:
        accepted = 0
        for r in records:
            if self.submit(r):
                accepted += 1
        return accepted

    def finalize(self) -> None:
        """Flush remaining records to the consumer."""
        if self._buffer:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer
        self._buffer = []
        self.metrics.batched += len(batch)
        if self.batch_consumer is not None:
            self.batch_consumer(batch)
