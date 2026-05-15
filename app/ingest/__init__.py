"""AAM Production Ingest Pipeline.

Wires HTTPTransport records -> semantic triples -> DCL semantic_triples
table via the existing PG writer. The existing
app/converters/triple_converter.py is the canonical /api/aam/infer write
path; this module exposes the field-mapping registry and per-record
triple-build helpers consumed by infer.
"""

from .mappings import MAPPINGS, get_mapping_for_pipe, FieldMapping
from .triples import build_triples, ingest_records, IngestResult

__all__ = [
    "MAPPINGS",
    "get_mapping_for_pipe",
    "FieldMapping",
    "build_triples",
    "ingest_records",
    "IngestResult",
]
