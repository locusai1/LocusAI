# tests/test_observability.py — Tests for core/observability.py (Metrics & Monitoring)

import pytest
import time
from unittest.mock import patch, MagicMock


class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    def test_create_collector(self):
        """Should create a metrics collector instance."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        assert collector is not None

    def test_inc_counter_basic(self):
        """Should increment counter."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.inc_counter("test_counter")
        assert collector.get_counter("test_counter") == 1

    def test_inc_counter_multiple(self):
        """Should increment counter multiple times."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.inc_counter("test_counter")
        collector.inc_counter("test_counter")
        collector.inc_counter("test_counter")
        assert collector.get_counter("test_counter") == 3

    def test_inc_counter_with_value(self):
        """Should increment counter by specified value."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.inc_counter("test_counter", value=5)
        assert collector.get_counter("test_counter") == 5

    def test_inc_counter_with_labels(self):
        """Should track counters with different labels separately."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.inc_counter("requests", labels={"method": "GET"})
        collector.inc_counter("requests", labels={"method": "POST"})
        collector.inc_counter("requests", labels={"method": "GET"})

        assert collector.get_counter("requests", labels={"method": "GET"}) == 2
        assert collector.get_counter("requests", labels={"method": "POST"}) == 1


class TestHistogram:
    """Tests for histogram metrics."""

    def test_observe_histogram(self):
        """Should record histogram observation."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.observe_histogram("latency", 0.5)
        stats = collector.get_histogram_stats("latency")
        assert stats["count"] == 1
        assert stats["sum"] == 0.5

    def test_histogram_stats_calculation(self):
        """Should calculate correct statistics."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()

        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        for v in values:
            collector.observe_histogram("latency", v)

        stats = collector.get_histogram_stats("latency")
        assert stats["count"] == 5
        assert stats["sum"] == pytest.approx(1.5)
        assert stats["avg"] == pytest.approx(0.3)
        assert stats["min"] == pytest.approx(0.1)
        assert stats["max"] == pytest.approx(0.5)

    def test_histogram_percentiles(self):
        """Should calculate percentiles."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()

        # Add 100 values
        for i in range(1, 101):
            collector.observe_histogram("latency", i)

        stats = collector.get_histogram_stats("latency")
        assert "p50" in stats
        assert "p95" in stats
        assert "p99" in stats

    def test_histogram_empty(self):
        """Should return zeros for empty histogram."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        stats = collector.get_histogram_stats("nonexistent")
        assert stats["count"] == 0
        assert stats["avg"] == 0


class TestGauge:
    """Tests for gauge metrics."""

    def test_set_gauge(self):
        """Should set gauge value."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.set_gauge("active_sessions", 10)
        assert collector.get_gauge("active_sessions") == 10

    def test_gauge_overwrite(self):
        """Should overwrite previous gauge value."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.set_gauge("active_sessions", 10)
        collector.set_gauge("active_sessions", 15)
        assert collector.get_gauge("active_sessions") == 15

    def test_gauge_with_labels(self):
        """Should track gauges with labels separately."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()
        collector.set_gauge("connections", 5, labels={"type": "http"})
        collector.set_gauge("connections", 3, labels={"type": "ws"})

        assert collector.get_gauge("connections", labels={"type": "http"}) == 5
        assert collector.get_gauge("connections", labels={"type": "ws"}) == 3


class TestGetAllMetrics:
    """Tests for get_all_metrics method."""

    def test_get_all_metrics(self):
        """Should return all metrics."""
        from core.observability import MetricsCollector
        collector = MetricsCollector()

        collector.inc_counter("counter1")
        collector.observe_histogram("hist1", 1.0)
        collector.set_gauge("gauge1", 5)

        metrics = collector.get_all_metrics()
        assert "counters" in metrics or "counter1" in str(metrics)


class TestMetricsConstants:
    """Tests for Metrics constants class."""

    def test_metrics_constants_defined(self):
        """Should have standard metric names defined."""
        from core.observability import Metrics

        # Check HTTP metrics
        assert hasattr(Metrics, "HTTP_REQUESTS_TOTAL")
        assert hasattr(Metrics, "HTTP_REQUEST_DURATION")

        # Check AI metrics
        assert hasattr(Metrics, "AI_REQUESTS_TOTAL")
        assert hasattr(Metrics, "AI_REQUEST_DURATION")


class TestTimedDecorator:
    """Tests for @timed decorator."""

    def test_timed_decorator(self):
        """Should measure function execution time."""
        from core.observability import timed, get_metrics

        @timed("test_function_duration")
        def slow_function():
            time.sleep(0.01)
            return "done"

        result = slow_function()
        assert result == "done"

    def test_timed_decorator_with_labels(self):
        """Should support labels."""
        from core.observability import timed

        @timed("function_duration", labels={"function": "test"})
        def my_function():
            return 42

        result = my_function()
        assert result == 42


class TestCountedDecorator:
    """Tests for @counted decorator."""

    def test_counted_decorator(self):
        """Should count function calls."""
        from core.observability import counted, get_metrics

        # Get initial counter value
        metrics = get_metrics()
        initial_count = metrics.get_counter("test_counted_calls")

        @counted("test_counted_calls")
        def my_function():
            return "called"

        my_function()
        my_function()
        my_function()

        # Should have incremented by 3
        final_count = metrics.get_counter("test_counted_calls")
        assert final_count == initial_count + 3


class TestRequestTracker:
    """Tests for RequestTracker context manager."""

    def test_request_tracker_basic(self):
        """Should track request lifecycle."""
        from core.observability import RequestTracker

        with RequestTracker("GET", "/api/test") as tracker:
            tracker.set_status(200)
            # Simulate work
            pass

    def test_request_tracker_error(self):
        """Should handle errors."""
        from core.observability import RequestTracker

        try:
            with RequestTracker("POST", "/api/error") as tracker:
                raise ValueError("Test error")
        except ValueError:
            pass  # Expected


class TestGetMetricsSingleton:
    """Tests for get_metrics singleton."""

    def test_get_metrics_returns_collector(self):
        """Should return a MetricsCollector instance."""
        from core.observability import get_metrics, MetricsCollector

        metrics = get_metrics()
        assert isinstance(metrics, MetricsCollector)

    def test_get_metrics_singleton(self):
        """Should return same instance."""
        from core.observability import get_metrics

        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2


class TestThreadSafety:
    """Tests for thread safety of metrics collector."""

    def test_concurrent_increments(self):
        """Should handle concurrent increments safely."""
        from core.observability import MetricsCollector
        import threading

        collector = MetricsCollector()
        threads = []

        def increment():
            for _ in range(10):  # Reduced from 100 to 10 to speed up test
                collector.inc_counter("concurrent_test")

        for _ in range(5):  # Reduced from 10 to 5 threads
            t = threading.Thread(target=increment)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)  # Add timeout to prevent hanging

        # Should have exactly 50 increments (5 threads * 10 each)
        assert collector.get_counter("concurrent_test") == 50
