# core/circuit_breaker.py — Circuit breaker pattern for external service resilience
# Prevents cascading failures by stopping calls to failing services

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable, Any
from threading import Lock
from functools import wraps

logger = logging.getLogger(__name__)

# ============================================================================
# Circuit Breaker States
# ============================================================================

class CircuitState:
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation - requests allowed
    OPEN = "open"          # Blocking requests - service is failing
    HALF_OPEN = "half_open"  # Testing recovery - limited requests


# ============================================================================
# Circuit Breaker Implementation
# ============================================================================

class CircuitBreaker:
    """Circuit breaker for external service calls.

    Prevents cascading failures by monitoring error rates and temporarily
    blocking requests to failing services.

    Usage:
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        # Check before calling
        if breaker.is_open("openai"):
            return fallback_response()

        try:
            result = call_openai()
            breaker.record_success("openai")
            return result
        except Exception as e:
            breaker.record_failure("openai")
            raise
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_requests: int = 1
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            half_open_requests: Number of requests allowed in half-open state
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests

        # State tracking per service
        # {service: {state, failures, last_failure, half_open_count}}
        self._circuits: Dict[str, Dict] = {}
        self._lock = Lock()

    def _get_circuit(self, service: str) -> Dict:
        """Get or create circuit state for a service."""
        if service not in self._circuits:
            self._circuits[service] = {
                "state": CircuitState.CLOSED,
                "failures": 0,
                "successes": 0,
                "last_failure": None,
                "opened_at": None,
                "half_open_count": 0
            }
        return self._circuits[service]

    def is_open(self, service: str) -> bool:
        """Check if circuit is open (should block calls).

        Returns:
            True if calls should be blocked
        """
        with self._lock:
            circuit = self._get_circuit(service)
            state = circuit["state"]

            if state == CircuitState.CLOSED:
                return False

            if state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                opened_at = circuit.get("opened_at")
                if opened_at:
                    elapsed = (datetime.now() - opened_at).total_seconds()
                    if elapsed >= self.recovery_timeout:
                        # Transition to half-open
                        circuit["state"] = CircuitState.HALF_OPEN
                        circuit["half_open_count"] = 0
                        logger.info(f"Circuit for {service} entering half-open state")
                        return False  # Allow one request
                return True  # Still blocking

            if state == CircuitState.HALF_OPEN:
                # Allow limited requests in half-open state
                if circuit["half_open_count"] < self.half_open_requests:
                    return False
                return True

            return False

    def record_failure(self, service: str, error: Optional[str] = None) -> bool:
        """Record a failure for a service.

        Args:
            service: Service identifier
            error: Optional error message for logging

        Returns:
            True if circuit was opened by this failure
        """
        with self._lock:
            circuit = self._get_circuit(service)
            state = circuit["state"]
            now = datetime.now()

            circuit["failures"] += 1
            circuit["last_failure"] = now
            circuit["successes"] = 0  # Reset success counter

            if state == CircuitState.HALF_OPEN:
                # Failure in half-open state - reopen circuit
                circuit["state"] = CircuitState.OPEN
                circuit["opened_at"] = now
                logger.warning(
                    f"Circuit for {service} reopened after half-open failure: {error}"
                )
                return True

            if state == CircuitState.CLOSED:
                if circuit["failures"] >= self.failure_threshold:
                    # Open the circuit
                    circuit["state"] = CircuitState.OPEN
                    circuit["opened_at"] = now
                    logger.warning(
                        f"Circuit for {service} opened after {circuit['failures']} failures: {error}"
                    )
                    return True

            return False

    def record_success(self, service: str) -> None:
        """Record a successful call for a service."""
        with self._lock:
            circuit = self._get_circuit(service)
            state = circuit["state"]

            circuit["successes"] += 1

            if state == CircuitState.HALF_OPEN:
                circuit["half_open_count"] += 1
                if circuit["half_open_count"] >= self.half_open_requests:
                    # Successful test request - close circuit
                    circuit["state"] = CircuitState.CLOSED
                    circuit["failures"] = 0
                    circuit["opened_at"] = None
                    logger.info(f"Circuit for {service} closed after successful recovery")

            elif state == CircuitState.CLOSED:
                # Reset failure count on success (sliding window reset)
                if circuit["successes"] >= self.failure_threshold:
                    circuit["failures"] = 0
                    circuit["successes"] = 0

    def get_state(self, service: str) -> Dict[str, Any]:
        """Get current state information for a service."""
        with self._lock:
            circuit = self._get_circuit(service)
            return {
                "service": service,
                "state": circuit["state"],
                "failures": circuit["failures"],
                "last_failure": circuit["last_failure"].isoformat() if circuit["last_failure"] else None,
                "opened_at": circuit["opened_at"].isoformat() if circuit["opened_at"] else None,
            }

    def reset(self, service: str) -> None:
        """Manually reset a circuit to closed state."""
        with self._lock:
            if service in self._circuits:
                self._circuits[service] = {
                    "state": CircuitState.CLOSED,
                    "failures": 0,
                    "successes": 0,
                    "last_failure": None,
                    "opened_at": None,
                    "half_open_count": 0
                }
                logger.info(f"Circuit for {service} manually reset")

    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all tracked circuits.

        Returns:
            Dictionary mapping service names to their circuit state info
        """
        with self._lock:
            stats = {}
            for service, circuit in self._circuits.items():
                stats[service] = {
                    "state": circuit["state"],
                    "failure_count": circuit["failures"],
                    "success_count": circuit["successes"],
                    "last_failure": circuit["last_failure"].isoformat() if circuit["last_failure"] else None,
                    "opened_at": circuit["opened_at"].isoformat() if circuit["opened_at"] else None,
                }
            return stats


# ============================================================================
# Global Circuit Breaker Instance
# ============================================================================

# Default circuit breaker for AI services
_ai_circuit_breaker: Optional[CircuitBreaker] = None


def get_ai_circuit_breaker() -> CircuitBreaker:
    """Get the global AI circuit breaker instance."""
    global _ai_circuit_breaker
    if _ai_circuit_breaker is None:
        _ai_circuit_breaker = CircuitBreaker(
            failure_threshold=3,      # Open after 3 failures
            recovery_timeout=60,      # Try recovery after 60 seconds
            half_open_requests=1      # Allow 1 test request
        )
    return _ai_circuit_breaker


# ============================================================================
# Decorator for Circuit Breaker
# ============================================================================

def with_circuit_breaker(
    service: str,
    breaker: Optional[CircuitBreaker] = None,
    fallback: Optional[Callable] = None
):
    """Decorator to wrap a function with circuit breaker protection.

    Args:
        service: Service identifier for the circuit
        breaker: Circuit breaker instance (uses global if None)
        fallback: Optional fallback function to call when circuit is open

    Usage:
        @with_circuit_breaker("openai", fallback=lambda *args: "Service unavailable")
        def call_openai(prompt):
            return openai.chat.completions.create(...)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cb = breaker or get_ai_circuit_breaker()

            if cb.is_open(service):
                logger.warning(f"Circuit open for {service}, using fallback")
                if fallback:
                    return fallback(*args, **kwargs)
                raise CircuitOpenError(f"Circuit breaker open for {service}")

            try:
                result = func(*args, **kwargs)
                cb.record_success(service)
                return result
            except Exception as e:
                cb.record_failure(service, str(e))
                raise

        return wrapper
    return decorator


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and no fallback is available."""
    pass


# ============================================================================
# Retry with Exponential Backoff
# ============================================================================

def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """Decorator to retry a function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts
        initial_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exponential_base: Base for exponential calculation
        exceptions: Tuple of exception types to catch and retry

    Usage:
        @retry_with_backoff(max_attempts=3, exceptions=(TimeoutError, ConnectionError))
        def call_api():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = initial_delay

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay * exponential_base, max_delay)
                    else:
                        logger.error(
                            f"All {max_attempts} attempts failed for {func.__name__}: {e}"
                        )

            raise last_exception

        return wrapper
    return decorator


# ============================================================================
# Combined Circuit Breaker + Retry
# ============================================================================

def resilient_call(
    service: str,
    max_retries: int = 2,
    retry_delay: float = 1.0,
    breaker: Optional[CircuitBreaker] = None,
    fallback: Optional[Callable] = None
):
    """Decorator combining circuit breaker and retry logic.

    Retries within a closed circuit, but fails fast when circuit is open.

    Usage:
        @resilient_call("openai", max_retries=2, fallback=default_response)
        def call_openai(prompt):
            return openai.chat.completions.create(...)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cb = breaker or get_ai_circuit_breaker()

            # Check circuit before any attempts
            if cb.is_open(service):
                logger.warning(f"Circuit open for {service}, using fallback immediately")
                if fallback:
                    return fallback(*args, **kwargs)
                raise CircuitOpenError(f"Circuit breaker open for {service}")

            last_exception = None
            delay = retry_delay

            for attempt in range(max_retries + 1):
                # Re-check circuit on retries
                if attempt > 0 and cb.is_open(service):
                    logger.warning(f"Circuit opened during retries for {service}")
                    if fallback:
                        return fallback(*args, **kwargs)
                    raise CircuitOpenError(f"Circuit breaker open for {service}")

                try:
                    result = func(*args, **kwargs)
                    cb.record_success(service)
                    return result
                except Exception as e:
                    last_exception = e
                    cb.record_failure(service, str(e))

                    if attempt < max_retries:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for {service}: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"All attempts failed for {service}: {e}")

            # All retries exhausted
            if fallback:
                logger.warning(f"Using fallback for {service} after all retries failed")
                return fallback(*args, **kwargs)
            raise last_exception

        return wrapper
    return decorator
