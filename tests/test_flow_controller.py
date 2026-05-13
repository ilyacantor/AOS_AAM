"""Unit tests for the flow controller — dedup, batching, backpressure."""

from __future__ import annotations

import pytest

from app.ingest.flow_controller import FlowController
from app.transport.http import TransportRecord


def _rec(pipe_id: str, key: str, offset: str = "0", src: str = "Salesforce") -> TransportRecord:
    return TransportRecord(pipe_id=pipe_id, record_key=key, payload={"x": 1}, offset=offset, source_system=src)


def test_dedup_on_pipe_id_record_key_offset():
    seen: list[list[TransportRecord]] = []
    fc = FlowController(batch_size=10, batch_consumer=seen.append)
    fc.submit(_rec("p1", "r1"))
    accepted = fc.submit(_rec("p1", "r1"))  # exact dup
    assert accepted is False
    fc.submit(_rec("p1", "r1", offset="1"))  # different offset — not a dup
    fc.finalize()
    assert sum(len(b) for b in seen) == 2
    assert fc.metrics.deduped == 1
    assert fc.metrics.batched == 2


def test_batch_size_triggers_flush():
    seen: list[list[TransportRecord]] = []
    fc = FlowController(batch_size=2, batch_consumer=seen.append)
    fc.submit(_rec("p", "a"))
    fc.submit(_rec("p", "b"))  # triggers flush at batch_size
    assert len(seen) == 1
    fc.submit(_rec("p", "c"))
    fc.finalize()
    assert len(seen) == 2
    assert fc.metrics.batched == 3


def test_max_buffer_backpressure_rejects_loudly():
    # Buffer holds at most 2; batch_size matches so no auto-flush leaves room.
    seen: list[list[TransportRecord]] = []
    fc = FlowController(batch_size=2, max_buffer=2, batch_consumer=lambda b: None)  # consumer no-op
    # Disable auto-flush by using a very large batch_size after construction
    fc.batch_size = 1000
    fc.submit(_rec("p", "a"))
    fc.submit(_rec("p", "b"))
    accepted = fc.submit(_rec("p", "c"))
    assert accepted is False
    assert fc.metrics.rejected == 1


def test_invalid_config_raises():
    with pytest.raises(ValueError):
        FlowController(batch_size=0)
    with pytest.raises(ValueError):
        FlowController(batch_size=10, max_buffer=5)
