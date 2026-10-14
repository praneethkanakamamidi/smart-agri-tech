"""Importing this package registers every tool in REGISTRY."""
from src.agents.tools import (  # noqa: F401
    admin, approvals, discovery, disputes, listings, negotiation, orders,
)
from src.agents.tools.base import REGISTRY, ToolError, ToolExecutor, tool_catalogue  # noqa: F401
