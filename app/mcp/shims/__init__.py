"""Vendor shims — present native vendor REST APIs as MCP tool output JSON.

For the demo: workato_shim + boomi_shim. Both subclass VendorShimBase.
Same code path downstream — no vendor branching outside the shim instance.
"""

from .workato_shim import WorkatoShim
from .boomi_shim import BoomiShim

__all__ = ["WorkatoShim", "BoomiShim"]
