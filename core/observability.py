# core/observability.py — Observability utilities for AxisAI
# Provides metrics collection, structured logging, and performance tracking

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable
from functools import wraps
from threading import Lock
from collections import defaultdict

logger = logging.getLogger(__name__)

# ============================================================================
# Metrics Collection
# ============================================================================

class MetricsCollector:
    """Simple in-memory metrics collector.

    For production, integrate with Prometheus, StatsD, or Datadog.

    Collects:
    - Counters: Request counts, error counts, etc.
    - Histograms: Request latency, AI response times, etc.
    - Gauges: Active connections, queue sizes, etc.
    """

    def __init__(self):
        self._lock = Lock()
        self._counters: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._histograms: Dict[str, list] = defaultdict(list)
        self._gauges: Dict[str, float] = {}

        # Keep histogram data only for recent period
        self._histogram_window = timedelta(hours=1)
        self._histogram_timestamps: Dict[str, list] = defaultdict(list)

    def inc_counter(self, name: str, labels: Optional[Dict[str, str]] = None, value: int = 1) -> None:
        """Increment a counter metric.

        Args:
            name: Metric name (e.g., "http_requests_total")
            labels: Optional labels (e.g., {"method": "GET", "status": "200"})
            value: Amount to increment by
        """
        with self._lock:
            label_key = self._labels_to_key(labels)
            self._counters[name][label_key] += value

    def observe_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a histogram observation.

        Args:
            name: Metric name (e.g., "request_latency_seconds")
            value: Observed value
            labels: Optional labels
        """
        with self._lock:
            key = f"{name}:{self._labels_to_key(labels)}"
            now = datetime.now()

            # Clean old data
            self._clean_histogram(key)

            self._histograms[key].append(value)
            self._histogram_timestamps[key].append(now)

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric.

        Args:
            name: Metric name (e.g., "active_sessions")
            value: Current value
            labels: Optional labels
        """
        with self._lock:
            key = f"{name}:{self._labels_to_key(labels)}"
            self._gauges[key] = value

    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> int:
        """Get current counter value."""
        with self._lock:
            label_key = self._labels_to_key(labels)
            return self._counters[name].get(label_key, 0)

    def get_histogram_stats(self, name: str, labels: Optional[Dict[str, str]] = None) -> Dict[str, float]:
        """Get histogram statistics.

        Returns:
            Dict with count, sum, avg, min, max, p50, p95, p99
        """
        with self._lock:
            key = f"{name}:{self._labels_to_key(labels)}"
            self._clean_histogram(key)

            values = self._histograms.get(key, [])
            if not values:
                return {
                    "count": 0, "sum": 0, "avg": 0,
                    "min": 0, "max": 0, "p50": 0, "p95": 0, "p99": 0
                }

            sorted_vals = sorted(values)
            count = len(sorted_vals)

            return {
                "count": count,
                "sum": sum(sorted_vals),
                "avg": sum(sorted_vals) / count,
                "min": sorted_vals[0],
                "max": sorted_vals[-1],
                "p50": self._percentile(sorted_vals, 50),
                "p95": self._percentile(sorted_vals, 95),
                "p99": self._percentile(sorted_vals, 99),
            }

    def get_gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current gauge value."""
        with self._lock:
            key = f"{name}:{self._labels_to_key(labels)}"
            return self._gauges.get(key, 0)

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics as a dictionary."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: self.get_histogram_stats(name.split(":")[0])
                    for name in self._histograms.keys()
                },
                "collected_at": datetime.now().isoformat()
            }

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._histogram_timestamps.clear()
            self._gauges.clear()

    def _labels_to_key(self, labels: Optional[Dict[str, str]]) -> str:
        """Convert labels dict to a string key."""
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))

    def _percentile(self, sorted_values: list, percentile: int) -> float:
        """Calculate percentile from sorted values."""
        if not sorted_values:
            return 0
        idx = int(len(sorted_values) * percentile / 100)
        idx = min(idx, len(sorted_values) - 1)
        return sorted_values[idx]

    def _clean_histogram(self, key: str) -> None:
        """Remove old histogram data outside the window."""
        cutoff = datetime.now() - self._histogram_window

        timestamps = self._histogram_timestamps.get(key, [])
        values = self._histograms.get(key, [])

        if not timestamps:
            return

        # Find first index within window
        valid_idx = 0
        for i, ts in enumerate(timestamps):
            if ts >= cutoff:
                valid_idx = i
                break
        else:
            valid_idx = len(timestamps)

        # Trim lists
        self._histogram_timestamps[key] = timestamps[valid_idx:]
        self._histograms[key] = values[valid_idx:]


# ============================================================================
# Global Metrics Instance
# ============================================================================

_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


# ============================================================================
# Metric Names (Constants)
# ============================================================================

class Metrics:
    """Standard metric names for the application."""
    # HTTP metrics
    HTTP_REQUESTS_TOTAL = "http_requests_total"
    HTTP_REQUEST_DURATION = "http_request_duration_seconds"
    HTTP_ERRORS_TOTAL = "http_errors_total"

    # AI metrics
    AI_REQUESTS_TOTAL = "ai_requests_total"
    AI_REQUEST_DURATION = "ai_request_duration_seconds"
    AI_TOKENS_USED = "ai_tokens_used_total"
    AI_ERRORS_TOTAL = "ai_errors_total"

    # Business metrics
    CONVERSATIONS_TOTAL = "conversations_total"
    BOOKINGS_TOTAL = "bookings_total"
    ESCALATIONS_TOTAL = "escalations_total"

    # Session metrics
    ACTIVE_SESSIONS = "active_sessions"

    # Background job metrics
    JOBS_PROCESSED = "jobs_processed_total"
    JOBS_FAILED = "jobs_failed_total"
    JOB_DURATION = "job_duration_seconds"

    # Voice call metrics
    VOICE_CALLS_TOTAL = "voice_calls_total"
    VOICE_CALL_DURATION = "voice_call_duration_seconds"
    VOICE_CALL_ERRORS = "voice_call_errors_total"
    VOICE_TRANSFERS_TOTAL = "voice_transfers_total"
    VOICE_BOOKINGS_TOTAL = "voice_bookings_total"
    VOICE_COST_CENTS = "voice_cost_cents_total"


# ============================================================================
# Decorators for Automatic Instrumentation
# ============================================================================

def timed(metric_name: str, labels: Optional[Dict[str, str]] = None):
    """Decorator to time function execution and record to histogram.

    Usage:
        @timed("ai_request_duration_seconds", {"model": "gpt-4"})
        def call_openai():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                get_metrics().observe_histogram(metric_name, duration, labels)
        return wrapper
    return decorator


def counted(metric_name: str, labels: Optional[Dict[str, str]] = None):
    """Decorator to count function calls.

    Usage:
        @counted("ai_requests_total", {"model": "gpt-4"})
        def call_openai():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            get_metrics().inc_counter(metric_name, labels)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def instrumented(
    counter_name: str,
    histogram_name: str,
    error_counter_name: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None
):
    """Decorator for full instrumentation (count, time, errors).

    Usage:
        @instrumented(
            "ai_requests_total",
            "ai_request_duration_seconds",
            "ai_errors_total",
            {"model": "gpt-4"}
        )
        def call_openai():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            metrics = get_metrics()
            metrics.inc_counter(counter_name, labels)
            start = time.time()

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                if error_counter_name:
                    error_labels = {**(labels or {}), "error_type": type(e).__name__}
                    metrics.inc_counter(error_counter_name, error_labels)
                raise
            finally:
                duration = time.time() - start
                metrics.observe_histogram(histogram_name, duration, labels)

        return wrapper
    return decorator


# ============================================================================
# Request Tracking Context Manager
# ============================================================================

class RequestTracker:
    """Context manager for tracking request metrics.

    Usage:
        with RequestTracker("GET", "/api/chat") as tracker:
            # handle request
            tracker.set_status(200)
    """

    def __init__(self, method: str, endpoint: str):
        self.method = method
        self.endpoint = endpoint
        self.start_time = None
        self.status = "unknown"
        self.metrics = get_metrics()

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time

        labels = {"method": self.method, "endpoint": self.endpoint, "status": self.status}

        self.metrics.inc_counter(Metrics.HTTP_REQUESTS_TOTAL, labels)
        self.metrics.observe_histogram(Metrics.HTTP_REQUEST_DURATION, duration, labels)

        if exc_type is not None:
            self.metrics.inc_counter(Metrics.HTTP_ERRORS_TOTAL, {
                "method": self.method,
                "endpoint": self.endpoint,
                "error_type": exc_type.__name__
            })

        return False  # Don't suppress exceptions

    def set_status(self, status: int) -> None:
        """Set the response status code."""
        self.status = str(status)


# ============================================================================
# Structured Logging Helpers
# ============================================================================

def log_with_context(
    level: int,
    message: str,
    request_id: Optional[str] = None,
    user_id: Optional[int] = None,
    business_id: Optional[int] = None,
    **extra
) -> None:
    """Log a message with structured context.

    Args:
        level: Logging level (e.g., logging.INFO)
        message: Log message
        request_id: Request ID for correlation
        user_id: User ID if authenticated
        business_id: Business context
        **extra: Additional context fields
    """
    context = {
        "timestamp": datetime.now().isoformat(),
        "request_id": request_id,
        "user_id": user_id,
        "business_id": business_id,
        **extra
    }

    # Remove None values
    context = {k: v for k, v in context.items() if v is not None}

    # Format context as key=value pairs
    context_str = " ".join(f"{k}={v}" for k, v in context.items())

    logger.log(level, f"{message} | {context_str}")


# ============================================================================
# Performance Summary
# ============================================================================

def get_performance_summary() -> Dict[str, Any]:
    """Get a summary of application performance metrics."""
    metrics = get_metrics()

    return {
        "http": {
            "requests": metrics.get_counter(Metrics.HTTP_REQUESTS_TOTAL),
            "errors": metrics.get_counter(Metrics.HTTP_ERRORS_TOTAL),
            "latency": metrics.get_histogram_stats(Metrics.HTTP_REQUEST_DURATION),
        },
        "ai": {
            "requests": metrics.get_counter(Metrics.AI_REQUESTS_TOTAL),
            "errors": metrics.get_counter(Metrics.AI_ERRORS_TOTAL),
            "latency": metrics.get_histogram_stats(Metrics.AI_REQUEST_DURATION),
        },
        "business": {
            "conversations": metrics.get_counter(Metrics.CONVERSATIONS_TOTAL),
            "bookings": metrics.get_counter(Metrics.BOOKINGS_TOTAL),
            "escalations": metrics.get_counter(Metrics.ESCALATIONS_TOTAL),
        },
        "collected_at": datetime.now().isoformat()
    }
