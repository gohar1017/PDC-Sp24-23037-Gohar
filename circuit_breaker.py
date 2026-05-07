"""
circuit_breaker.py
------------------
Implements the Circuit Breaker pattern for protecting the FastAPI app
against a slow/failing external LLM API.
 
States:
  CLOSED   → Normal operation. Requests flow through.
  OPEN     → Too many failures detected. Requests are SHORT-CIRCUITED immediately.
  HALF-OPEN → Cooldown elapsed. One probe request is allowed through to test recovery.
"""
 
import time
import asyncio
from enum import Enum
from typing import Callable, Any
 
 
class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"
 
 
class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""
    pass
 
 
class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
        call_timeout: float = 5.0,
    ):
        """
        Args:
            name:               Identifier for logging.
            failure_threshold:  Consecutive failures before opening the circuit.
            recovery_timeout:   Seconds to wait in OPEN state before trying HALF_OPEN.
            call_timeout:       Max seconds to wait for the protected function to respond.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.call_timeout = call_timeout
 
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
 
    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #
 
    @property
    def state(self) -> CircuitState:
        """Return current state, automatically transitioning OPEN → HALF_OPEN when ready."""
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            print(f"[CircuitBreaker:{self.name}] State → HALF_OPEN (probing recovery)")
        return self._state
 
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute `func` through the circuit breaker.
        Raises CircuitBreakerOpenError immediately if the circuit is OPEN.
        """
        current_state = self.state  # triggers auto-transition check
 
        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"Circuit '{self.name}' is OPEN. Request blocked to protect the system."
            )
 
        try:
            # Enforce a hard timeout so a slow LLM can't block the server thread
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.call_timeout,
            )
            self._on_success()
            return result
 
        except (asyncio.TimeoutError, Exception) as exc:
            self._on_failure()
            raise exc
 
    # ------------------------------------------------------------------ #
    #  Internal state transitions                                          #
    # ------------------------------------------------------------------ #
 
    def _on_success(self):
        if self._state == CircuitState.HALF_OPEN:
            print(f"[CircuitBreaker:{self.name}] Probe succeeded → State: CLOSED")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
 
    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        print(
            f"[CircuitBreaker:{self.name}] Failure #{self._failure_count} recorded."
        )
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            print(
                f"[CircuitBreaker:{self.name}] Threshold reached → State: OPEN "
                f"(will retry after {self.recovery_timeout}s)"
            )
 
    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "recovery_timeout_seconds": self.recovery_timeout,
            "call_timeout_seconds": self.call_timeout,
        }
 