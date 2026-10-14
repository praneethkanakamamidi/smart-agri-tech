"""
FarmBridge AI: the stateful, tool-using multi-agent layer of the marketplace.

Agents never touch the database directly. They call typed tools (src/agents/tools), and every
tool re-checks the caller's identity, role and resource ownership and then delegates to the
same domain services the REST API uses (negotiations, order_core, inventory_core, logistics,
disputes). Identity comes from the server-side run context, never from model output or graph
state.
"""
