"""AAM Production Ingest Pipeline (demo path).

Wires HTTPTransport records -> dedup/batch -> semantic triples -> DCL
semantic_triples table via the existing PG writer. The existing
app/converters/triple_converter.py is not extended — this module builds
triple dicts directly in the shape expected by app.db.triple_writer.
"""

from .flow_controller import FlowController, FlowMetrics
from .mappings import MAPPINGS, get_mapping_for_pipe, FieldMapping
from .triples import build_triples, ingest_records, IngestResult

__all__ = [
    "FlowController",
    "FlowMetrics",
    "MAPPINGS",
    "get_mapping_for_pipe",
    "FieldMapping",
    "build_triples",
    "ingest_records",
    "IngestResult",
]
