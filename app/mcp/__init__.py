"""AAM MCP Client Infrastructure.

Universal MCP client + JSON->DeclaredPipe translator + connection registry +
vendor shim base. The shim subclasses present native vendor REST APIs as MCP
tool output, so the universal client and translator work unchanged across
Workato, Boomi, and future vendors.
"""

from .client import MCPClient, MCPClientError, MCPTool, MCPToolResult
from .translator import ToolOutputTranslator, TranslatorError
from .registry import MCPRegistry, RegistryEntry
from .shim_base import VendorShimBase

__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPTool",
    "MCPToolResult",
    "ToolOutputTranslator",
    "TranslatorError",
    "MCPRegistry",
    "RegistryEntry",
    "VendorShimBase",
]
