# tests/test_circuit_breaker.py — Tests for core/circuit_breaker.py
# Tests for circuit breaker pattern implementation

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from core.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    with_circuit_breaker,
    retry_with_backoff,
    resilient_call,
    get_ai_circuit_breaker,
)


# ============================================================================
# CircuitBreaker Basic State Tests
# ============================================================================

class TestCircuitBreakerBasicState:
    """Tests for basic circuit breaker state management."""

    def test_initial_state_is_closed(self):
        """New circuit should start in closed state."""
        breaker = CircuitBreaker()
        assert breaker.is_open("test-service") is False

    def test_get_state_for_new_service(self):
        """Getting state for new service should show closed."""
        breaker = CircuitBreaker()
        state = breaker.get_state("test-service")

        assert state["service"] == "test-service"
        assert state["state"] == CircuitState.CLOSED
        assert state["failures"] == 0

    def test_reset_clears_state(self):
        """Reset should clear circuit state."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Record some failures
        breaker.record_failure("test")
        breaker.record_failure("test")

        # Reset
        breaker.reset("test")

        state = breaker.get_state("test")
        assert state["state"] == CircuitState.CLOSED
        assert state["failures"] == 0


# ============================================================================
# Circuit Opening Tests
# ============================================================================

class TestCircuitOpening:
    """Tests for circuit opening on failures."""

    def test_circuit_opens_after_threshold_failures(self):
        """Circuit should open after failure threshold is reached."""
        breaker = CircuitBreaker(failure_threshold=3)

        # First two failures shouldn't open
        breaker.record_failure("test")
        assert breaker.is_open("test") is False

        breaker.record_failure("test")
        assert breaker.is_open("test") is False

        # Third failure should open
        opened = breaker.record_failure("test")
        assert opened is True
        assert breaker.is_open("test") is True

    def test_circuit_blocks_requests_when_open(self):
        """Open circuit should block all requests."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        breaker.record_failure("test")
        breaker.record_failure("test")

        # Should be blocking
        assert breaker.is_open("test") is True

    def test_failure_returns_false_when_circuit_already_open(self):
        """Recording failure on already-open circuit should return False."""
        breaker = CircuitBreaker(failure_threshold=2)

        breaker.record_failure("test")
        opened = breaker.record_failure("test")
        assert opened is True

        # Already open, shouldn't re-trigger
        opened_again = breaker.record_failure("test")
        assert opened_again is False


# ============================================================================
# Circuit Recovery Tests
# ============================================================================

class TestCircuitRecovery:
    """Tests for circuit recovery behavior."""

    def test_circuit_enters_half_open_after_timeout(self):
        """Circuit should enter half-open state after recovery timeout."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=1  # 1 second for testing
        )

        # Open the circuit
        breaker.record_failure("test")
        breaker.record_failure("test")
        assert breaker.is_open("test") is True

        # Wait for recovery timeout
        time.sleep(1.1)

        # Should now allow one request (half-open)
        assert breaker.is_open("test") is False

        state = breaker.get_state("test")
        assert state["state"] == CircuitState.HALF_OPEN

    def test_success_in_half_open_closes_circuit(self):
        """Success in half-open state should close the circuit."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0,  # Immediate recovery for testing
            half_open_requests=1
        )

        # Open circuit
        breaker.record_failure("test")
        breaker.record_failure("test")

        # Trigger half-open
        breaker.is_open("test")

        # Record success
        breaker.record_success("test")

        state = breaker.get_state("test")
        assert state["state"] == CircuitState.CLOSED
        assert state["failures"] == 0

    def test_failure_in_half_open_reopens_circuit(self):
        """Failure in half-open state should reopen the circuit."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0,
            half_open_requests=1
        )

        # Open circuit
        breaker.record_failure("test")
        breaker.record_failure("test")

        # Trigger half-open
        breaker.is_open("test")

        # Record failure in half-open
        breaker.record_failure("test")

        state = breaker.get_state("test")
        assert state["state"] == CircuitState.OPEN


# ============================================================================
# Success Counter Tests
# ============================================================================

class TestSuccessCounter:
    """Tests for success counting behavior."""

    def test_success_resets_failure_counter_after_threshold(self):
        """Multiple successes should reset failure counter in closed state."""
        breaker = CircuitBreaker(failure_threshold=5)

        # Record some failures
        breaker.record_failure("test")
        breaker.record_failure("test")
        assert breaker.get_state("test")["failures"] == 2

        # Record enough successes to reset
        for _ in range(5):
            breaker.record_success("test")

        state = breaker.get_state("test")
        assert state["failures"] == 0


# ============================================================================
# Multiple Services Tests
# ============================================================================

class TestMultipleServices:
    """Tests for handling multiple services independently."""

    def test_independent_circuits_per_service(self):
        """Each service should have its own circuit."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Open circuit for service1
        breaker.record_failure("service1")
        breaker.record_failure("service1")

        # service1 should be open
        assert breaker.is_open("service1") is True

        # service2 should still be closed
        assert breaker.is_open("service2") is False

    def test_get_stats_returns_all_services(self):
        """get_stats should return info for all tracked services."""
        breaker = CircuitBreaker()

        breaker.record_failure("service1")
        breaker.record_success("service2")

        stats = breaker.get_stats()

        assert "service1" in stats
        assert "service2" in stats
        assert stats["service1"]["failure_count"] == 1
        assert stats["service2"]["success_count"] == 1


# ============================================================================
# Decorator Tests
# ============================================================================

class TestWithCircuitBreakerDecorator:
    """Tests for @with_circuit_breaker decorator."""

    def test_decorator_records_success(self):
        """Successful call should record success."""
        breaker = CircuitBreaker()

        @with_circuit_breaker("test", breaker=breaker)
        def successful_call():
            return "success"

        result = successful_call()
        assert result == "success"

        # get_state returns limited info, check circuit is still closed
        state = breaker.get_state("test")
        assert state["state"] == CircuitState.CLOSED
        assert state["failures"] == 0

    def test_decorator_records_failure(self):
        """Failed call should record failure."""
        breaker = CircuitBreaker()

        @with_circuit_breaker("test", breaker=breaker)
        def failing_call():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_call()

        state = breaker.get_state("test")
        assert state["failures"] == 1

    def test_decorator_uses_fallback_when_open(self):
        """Should use fallback when circuit is open."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        @with_circuit_breaker("test", breaker=breaker, fallback=lambda: "fallback")
        def call():
            raise ValueError("Error")

        # First call fails and opens circuit
        with pytest.raises(ValueError):
            call()

        # Second call should use fallback
        result = call()
        assert result == "fallback"

    def test_decorator_raises_circuit_open_error_without_fallback(self):
        """Should raise CircuitOpenError when no fallback provided."""
        breaker = CircuitBreaker(failure_threshold=1)

        @with_circuit_breaker("test", breaker=breaker)
        def call():
            raise ValueError("Error")

        # First call fails
        with pytest.raises(ValueError):
            call()

        # Second call should raise CircuitOpenError
        with pytest.raises(CircuitOpenError):
            call()


# ============================================================================
# Retry with Backoff Tests
# ============================================================================

class TestRetryWithBackoff:
    """Tests for @retry_with_backoff decorator."""

    def test_retry_succeeds_on_second_attempt(self):
        """Should succeed if retry works."""
        attempts = [0]

        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        def flaky_call():
            attempts[0] += 1
            if attempts[0] < 2:
                raise ValueError("Temporary error")
            return "success"

        result = flaky_call()
        assert result == "success"
        assert attempts[0] == 2

    def test_retry_gives_up_after_max_attempts(self):
        """Should give up after max attempts."""
        attempts = [0]

        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        def always_fails():
            attempts[0] += 1
            raise ValueError("Permanent error")

        with pytest.raises(ValueError):
            always_fails()

        assert attempts[0] == 3

    def test_retry_only_catches_specified_exceptions(self):
        """Should only retry for specified exception types."""
        @retry_with_backoff(max_attempts=3, initial_delay=0.01, exceptions=(ValueError,))
        def raises_type_error():
            raise TypeError("Wrong type")

        # Should not retry, raise immediately
        with pytest.raises(TypeError):
            raises_type_error()


# ============================================================================
# Resilient Call Tests
# ============================================================================

class TestResilientCall:
    """Tests for @resilient_call decorator (combined breaker + retry)."""

    def test_resilient_call_retries_then_succeeds(self):
        """Should retry and eventually succeed."""
        attempts = [0]
        breaker = CircuitBreaker(failure_threshold=5)

        @resilient_call("test", max_retries=2, retry_delay=0.01, breaker=breaker)
        def flaky():
            attempts[0] += 1
            if attempts[0] < 2:
                raise ValueError("Temp error")
            return "success"

        result = flaky()
        assert result == "success"

    def test_resilient_call_uses_fallback_on_circuit_open(self):
        """Should use fallback when circuit is already open."""
        breaker = CircuitBreaker(failure_threshold=1)

        # Open the circuit
        breaker.record_failure("test")

        @resilient_call("test", breaker=breaker, fallback=lambda: "fallback")
        def call():
            return "normal"

        result = call()
        assert result == "fallback"

    def test_resilient_call_uses_fallback_after_all_retries_fail(self):
        """Should use fallback after exhausting retries."""
        breaker = CircuitBreaker(failure_threshold=10)

        @resilient_call("test", max_retries=1, retry_delay=0.01,
                       breaker=breaker, fallback=lambda: "fallback")
        def always_fails():
            raise ValueError("Error")

        result = always_fails()
        assert result == "fallback"


# ============================================================================
# Global Circuit Breaker Tests
# ============================================================================

class TestGlobalCircuitBreaker:
    """Tests for global AI circuit breaker instance."""

    def test_get_ai_circuit_breaker_returns_instance(self):
        """Should return a CircuitBreaker instance."""
        breaker = get_ai_circuit_breaker()
        assert isinstance(breaker, CircuitBreaker)

    def test_get_ai_circuit_breaker_returns_same_instance(self):
        """Should return the same instance on multiple calls."""
        breaker1 = get_ai_circuit_breaker()
        breaker2 = get_ai_circuit_breaker()
        assert breaker1 is breaker2


# ============================================================================
# Thread Safety Tests
# ============================================================================

class TestThreadSafety:
    """Tests for thread safety of circuit breaker."""

    def test_concurrent_failures_handled_safely(self):
        """Multiple threads recording failures shouldn't corrupt state."""
        import threading

        breaker = CircuitBreaker(failure_threshold=100)
        threads = []

        def record_failures():
            for _ in range(10):
                breaker.record_failure("test")

        # Create multiple threads
        for _ in range(10):
            t = threading.Thread(target=record_failures)
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        state = breaker.get_state("test")
        # Should have recorded exactly 100 failures
        assert state["failures"] == 100
