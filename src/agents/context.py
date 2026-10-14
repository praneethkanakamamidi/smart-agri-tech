"""
Trusted, server-side run context.

It is built by the runner from the database (run owner -> user -> role) for every invocation
and passed to LangGraph as runtime context, which is not checkpointed. Graph state may carry
an `authenticated_user_id` for display, but nothing reads identity from state or from model
output.
"""
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class RunContext:
    run_id: str | None
    user_id: int
    role: str
    correlation_id: str
    conversation_id: str | None = None
    node: str | None = None
    # Injected collaborators (not serialised): the tool executor and the LLM router.
    tools: Any = field(default=None, compare=False, repr=False)
    llm: Any = field(default=None, compare=False, repr=False)

    def at(self, node: str) -> "RunContext":
        return replace(self, node=node)
