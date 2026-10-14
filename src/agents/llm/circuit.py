"""Per-model circuit breaker: a model that keeps failing is skipped for a cool-down period."""
import time
from dataclasses import dataclass


@dataclass
class _State:
    failures: int = 0
    opened_until: float = 0.0
    last_error: str | None = None


class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_s: float, clock=time.monotonic):
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._states: dict[str, _State] = {}

    def allow(self, model_id: str) -> bool:
        state = self._states.get(model_id)
        return not state or state.opened_until <= self._clock()

    def record_success(self, model_id: str):
        self._states.pop(model_id, None)

    def record_failure(self, model_id: str, error_code: str, immediate: bool = False):
        state = self._states.setdefault(model_id, _State())
        state.failures += 1
        state.last_error = error_code
        if immediate or state.failures >= self.failure_threshold:
            state.opened_until = self._clock() + self.cooldown_s
            state.failures = 0

    def snapshot(self) -> dict:
        now = self._clock()
        return {
            model_id: {"open": s.opened_until > now, "seconds_until_retry": max(0, round(s.opened_until - now)),
                       "recent_failures": s.failures, "last_error": s.last_error}
            for model_id, s in self._states.items()
        }
