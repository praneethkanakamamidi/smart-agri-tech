"""
FarmBridge AI: the stateful, tool-using multi-agent layer of the marketplace.

Agents never touch the database directly. They call typed tools (src/agents/tools), and every
tool re-checks the caller's identity, role and resource ownership and then delegates to the
same domain services the REST API uses (negotiations, order_core, inventory_core, logistics,
disputes). Identity comes from the server-side run context, never from model output or graph
state.
"""
# Tools import domain services, whose models reference each other by name; every mapper must
# be registered before the first one is configured, whichever agent module is imported first.
import src.data_models.registry  # noqa: E402,F401
