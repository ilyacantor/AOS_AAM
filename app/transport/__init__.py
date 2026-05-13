"""AAM Transport Shims — data movement layer.

HTTPTransport is the demo path. KafkaTransport, SQLTransport, and
StreamTransport are intentionally out of scope for this build.
"""

from .http import HTTPTransport, HTTPTransportError, TransportRecord

__all__ = ["HTTPTransport", "HTTPTransportError", "TransportRecord"]
