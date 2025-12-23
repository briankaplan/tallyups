#!/usr/bin/env python3
"""
monitoring.py — API Error and Timeout Monitoring for ReceiptAI
--------------------------------------------------------------

Provides comprehensive monitoring and alerting for:
  - API errors (internal and external)
  - Request timeouts
  - Rate limiting events
  - Database connection issues
  - Health check endpoints

Features:
  - In-memory metrics collection with time windows
  - Threshold-based alerting
  - Health check aggregation
  - Prometheus-compatible metrics export
  - Webhook alerting support
"""

import os
import time
import threading
import json
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum
import functools

# Try to import structured logging
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# METRIC TYPES AND CONFIGURATION
# =============================================================================

class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class MetricPoint:
    """A single metric data point."""
    timestamp: float
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class Alert:
    """An alert triggered by monitoring."""
    name: str
    severity: AlertSeverity
    message: str
    timestamp: datetime
    metric_name: str
    metric_value: float
    threshold: float
    labels: Dict[str, str] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "labels": self.labels,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


@dataclass
class AlertRule:
    """Rule for triggering alerts based on metrics."""
    name: str
    metric_name: str
    condition: str  # "gt", "lt", "gte", "lte", "eq"
    threshold: float
    window_seconds: int  # Time window for aggregation
    aggregation: str  # "sum", "avg", "max", "min", "count", "rate"
    severity: AlertSeverity
    message_template: str
    cooldown_seconds: int = 300  # Minimum time between alerts
    labels_filter: Dict[str, str] = field(default_factory=dict)
    last_triggered: Optional[datetime] = None


# =============================================================================
# METRICS COLLECTOR
# =============================================================================

class MetricsCollector:
    """Thread-safe metrics collector with time-windowed storage."""

    def __init__(self, retention_seconds: int = 3600):
        self.retention_seconds = retention_seconds
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        self._gauges: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._started_at = time.time()

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment a counter metric."""
        point = MetricPoint(
            timestamp=time.time(),
            value=value,
            labels=labels or {}
        )
        with self._lock:
            self._metrics[name].append(point)
            self._cleanup_old_metrics(name)

    def gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge metric."""
        key = self._gauge_key(name, labels)
        with self._lock:
            self._gauges[key] = value
            # Also record as time series for history
            point = MetricPoint(
                timestamp=time.time(),
                value=value,
                labels=labels or {}
            )
            self._metrics[name].append(point)
            self._cleanup_old_metrics(name)

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record an observation (for histograms/summaries)."""
        point = MetricPoint(
            timestamp=time.time(),
            value=value,
            labels=labels or {}
        )
        with self._lock:
            self._metrics[name].append(point)
            self._cleanup_old_metrics(name)

    def _gauge_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _cleanup_old_metrics(self, name: str):
        """Remove metrics older than retention period."""
        cutoff = time.time() - self.retention_seconds
        while self._metrics[name] and self._metrics[name][0].timestamp < cutoff:
            self._metrics[name].popleft()

    def get_metrics(self, name: str, window_seconds: Optional[int] = None,
                   labels_filter: Optional[Dict[str, str]] = None) -> List[MetricPoint]:
        """Get metrics for a given name within a time window."""
        with self._lock:
            if name not in self._metrics:
                return []

            cutoff = time.time() - (window_seconds or self.retention_seconds)
            result = []

            for point in self._metrics[name]:
                if point.timestamp < cutoff:
                    continue

                if labels_filter:
                    if not all(point.labels.get(k) == v for k, v in labels_filter.items()):
                        continue

                result.append(point)

            return result

    def aggregate(self, name: str, aggregation: str, window_seconds: int,
                 labels_filter: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Aggregate metrics over a time window."""
        points = self.get_metrics(name, window_seconds, labels_filter)
        if not points:
            return None

        values = [p.value for p in points]

        if aggregation == "sum":
            return sum(values)
        elif aggregation == "avg":
            return statistics.mean(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "min":
            return min(values)
        elif aggregation == "count":
            return float(len(values))
        elif aggregation == "rate":
            # Rate per second
            if len(points) < 2:
                return 0.0
            time_span = points[-1].timestamp - points[0].timestamp
            if time_span <= 0:
                return 0.0
            return sum(values) / time_span
        else:
            return None

    def get_all_metric_names(self) -> List[str]:
        """Get all metric names."""
        with self._lock:
            return list(self._metrics.keys())

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        with self._lock:
            for name, points in self._metrics.items():
                if not points:
                    continue

                # Get most recent value for each label combination
                latest = {}
                for point in points:
                    key = self._gauge_key(name, point.labels)
                    latest[key] = point

                for key, point in latest.items():
                    if point.labels:
                        label_str = ",".join(f'{k}="{v}"' for k, v in point.labels.items())
                        lines.append(f'{name}{{{label_str}}} {point.value}')
                    else:
                        lines.append(f'{name} {point.value}')

        return "\n".join(lines)


# =============================================================================
# ALERT MANAGER
# =============================================================================

class AlertManager:
    """Manages alert rules and triggers alerts based on metrics."""

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics
        self.rules: List[AlertRule] = []
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: deque = deque(maxlen=1000)
        self.webhooks: List[str] = []
        self._lock = threading.Lock()
        self._check_interval = 30  # seconds
        self._running = False
        self._check_thread: Optional[threading.Thread] = None

    def add_rule(self, rule: AlertRule):
        """Add an alert rule."""
        with self._lock:
            self.rules.append(rule)
            logger.info(f"Added alert rule: {rule.name}")

    def remove_rule(self, rule_name: str):
        """Remove an alert rule by name."""
        with self._lock:
            self.rules = [r for r in self.rules if r.name != rule_name]

    def add_webhook(self, url: str):
        """Add a webhook URL for alert notifications."""
        self.webhooks.append(url)

    def start(self):
        """Start the background alert checking thread."""
        if self._running:
            return

        self._running = True
        self._check_thread = threading.Thread(target=self._check_loop, daemon=True)
        self._check_thread.start()
        logger.info("Alert manager started")

    def stop(self):
        """Stop the background alert checking thread."""
        self._running = False
        if self._check_thread:
            self._check_thread.join(timeout=5)

    def _check_loop(self):
        """Background loop to check alert rules."""
        while self._running:
            try:
                self.check_rules()
            except Exception as e:
                logger.error(f"Error checking alert rules: {e}")
            time.sleep(self._check_interval)

    def check_rules(self):
        """Check all alert rules against current metrics."""
        now = datetime.now()

        with self._lock:
            for rule in self.rules:
                # Check cooldown
                if rule.last_triggered:
                    cooldown_delta = timedelta(seconds=rule.cooldown_seconds)
                    if now - rule.last_triggered < cooldown_delta:
                        continue

                # Get aggregated metric value
                value = self.metrics.aggregate(
                    rule.metric_name,
                    rule.aggregation,
                    rule.window_seconds,
                    rule.labels_filter
                )

                if value is None:
                    continue

                # Check condition
                triggered = self._check_condition(value, rule.condition, rule.threshold)

                if triggered:
                    self._trigger_alert(rule, value, now)
                else:
                    # Resolve any existing alert for this rule
                    self._resolve_alert(rule.name, now)

    def _check_condition(self, value: float, condition: str, threshold: float) -> bool:
        """Check if a condition is met."""
        if condition == "gt":
            return value > threshold
        elif condition == "gte":
            return value >= threshold
        elif condition == "lt":
            return value < threshold
        elif condition == "lte":
            return value <= threshold
        elif condition == "eq":
            return value == threshold
        return False

    def _trigger_alert(self, rule: AlertRule, value: float, now: datetime):
        """Trigger an alert for a rule."""
        alert = Alert(
            name=rule.name,
            severity=rule.severity,
            message=rule.message_template.format(value=value, threshold=rule.threshold),
            timestamp=now,
            metric_name=rule.metric_name,
            metric_value=value,
            threshold=rule.threshold,
            labels=rule.labels_filter.copy(),
        )

        self.active_alerts[rule.name] = alert
        self.alert_history.append(alert)
        rule.last_triggered = now

        logger.warning(f"Alert triggered: {alert.name} - {alert.message}")

        # Send webhooks
        self._send_webhooks(alert)

    def _resolve_alert(self, rule_name: str, now: datetime):
        """Resolve an active alert."""
        if rule_name in self.active_alerts:
            alert = self.active_alerts[rule_name]
            alert.resolved = True
            alert.resolved_at = now
            del self.active_alerts[rule_name]
            logger.info(f"Alert resolved: {rule_name}")

    def _send_webhooks(self, alert: Alert):
        """Send alert to configured webhooks."""
        if not self.webhooks:
            return

        import threading

        def send():
            try:
                import requests
                payload = alert.to_dict()
                for url in self.webhooks:
                    try:
                        requests.post(url, json=payload, timeout=10)
                    except Exception as e:
                        logger.error(f"Failed to send webhook to {url}: {e}")
            except ImportError:
                logger.warning("requests library not available for webhooks")

        threading.Thread(target=send, daemon=True).start()

    def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        with self._lock:
            return list(self.active_alerts.values())

    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """Get recent alert history."""
        with self._lock:
            return list(self.alert_history)[-limit:]


# =============================================================================
# API MONITOR
# =============================================================================

class APIMonitor:
    """High-level API monitoring with pre-configured metrics and alerts."""

    def __init__(self):
        self.metrics = MetricsCollector(retention_seconds=3600)
        self.alerts = AlertManager(self.metrics)
        self._setup_default_rules()

    def _setup_default_rules(self):
        """Set up default alert rules."""
        # High error rate
        self.alerts.add_rule(AlertRule(
            name="high_error_rate",
            metric_name="api_errors_total",
            condition="gte",
            threshold=10,
            window_seconds=60,
            aggregation="count",
            severity=AlertSeverity.ERROR,
            message_template="High error rate: {value:.0f} errors in last minute (threshold: {threshold})",
        ))

        # Slow response times
        self.alerts.add_rule(AlertRule(
            name="slow_response_time",
            metric_name="api_response_time_ms",
            condition="gt",
            threshold=5000,  # 5 seconds
            window_seconds=60,
            aggregation="avg",
            severity=AlertSeverity.WARNING,
            message_template="Slow response times: {value:.0f}ms average (threshold: {threshold}ms)",
        ))

        # Rate limiting
        self.alerts.add_rule(AlertRule(
            name="excessive_rate_limiting",
            metric_name="api_rate_limited_total",
            condition="gte",
            threshold=5,
            window_seconds=300,  # 5 minutes
            aggregation="count",
            severity=AlertSeverity.WARNING,
            message_template="Excessive rate limiting: {value:.0f} events in last 5 minutes",
        ))

        # Database connection issues
        self.alerts.add_rule(AlertRule(
            name="db_connection_errors",
            metric_name="db_connection_errors_total",
            condition="gte",
            threshold=3,
            window_seconds=60,
            aggregation="count",
            severity=AlertSeverity.CRITICAL,
            message_template="Database connection issues: {value:.0f} errors in last minute",
        ))

        # External API failures
        self.alerts.add_rule(AlertRule(
            name="external_api_failures",
            metric_name="external_api_errors_total",
            condition="gte",
            threshold=5,
            window_seconds=300,
            aggregation="count",
            severity=AlertSeverity.ERROR,
            message_template="External API failures: {value:.0f} errors in last 5 minutes",
        ))

    def start(self):
        """Start the monitoring system."""
        self.alerts.start()
        logger.info("API monitoring started")

    def stop(self):
        """Stop the monitoring system."""
        self.alerts.stop()

    # Metric recording methods

    def record_request(self, method: str, path: str, status_code: int, duration_ms: float):
        """Record an API request."""
        labels = {"method": method, "path": path, "status": str(status_code)}

        self.metrics.increment("api_requests_total", labels=labels)
        self.metrics.observe("api_response_time_ms", duration_ms, labels=labels)

        if status_code >= 400:
            self.metrics.increment("api_errors_total", labels=labels)

    def record_timeout(self, service: str, operation: str, timeout_seconds: float):
        """Record a timeout event."""
        labels = {"service": service, "operation": operation}
        self.metrics.increment("api_timeouts_total", labels=labels)
        self.metrics.observe("api_timeout_duration_s", timeout_seconds, labels=labels)

    def record_rate_limit(self, service: str, retry_after: float):
        """Record a rate limiting event."""
        labels = {"service": service}
        self.metrics.increment("api_rate_limited_total", labels=labels)
        self.metrics.observe("api_rate_limit_retry_s", retry_after, labels=labels)

    def record_external_api(self, service: str, operation: str, success: bool, duration_ms: float):
        """Record an external API call."""
        labels = {"service": service, "operation": operation}
        self.metrics.increment("external_api_calls_total", labels=labels)
        self.metrics.observe("external_api_duration_ms", duration_ms, labels=labels)

        if not success:
            self.metrics.increment("external_api_errors_total", labels=labels)

    def record_db_operation(self, operation: str, success: bool, duration_ms: float):
        """Record a database operation."""
        labels = {"operation": operation}
        self.metrics.increment("db_operations_total", labels=labels)
        self.metrics.observe("db_operation_duration_ms", duration_ms, labels=labels)

        if not success:
            self.metrics.increment("db_connection_errors_total", labels=labels)

    def record_receipt_match(self, source: str, success: bool, score: float):
        """Record a receipt matching attempt."""
        labels = {"source": source}
        self.metrics.increment("receipt_match_attempts_total", labels=labels)

        if success:
            self.metrics.increment("receipt_match_success_total", labels=labels)
            self.metrics.observe("receipt_match_score", score, labels=labels)
        else:
            self.metrics.increment("receipt_match_failures_total", labels=labels)

    # Health check methods

    def health_check(self) -> Dict[str, Any]:
        """Get overall system health status."""
        active_alerts = self.alerts.get_active_alerts()

        # Determine overall status
        if any(a.severity == AlertSeverity.CRITICAL for a in active_alerts):
            status = "critical"
        elif any(a.severity == AlertSeverity.ERROR for a in active_alerts):
            status = "degraded"
        elif any(a.severity == AlertSeverity.WARNING for a in active_alerts):
            status = "warning"
        else:
            status = "healthy"

        # Get recent metrics
        request_count = self.metrics.aggregate("api_requests_total", "count", 300) or 0
        error_count = self.metrics.aggregate("api_errors_total", "count", 300) or 0
        avg_response_time = self.metrics.aggregate("api_response_time_ms", "avg", 300) or 0

        return {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "active_alerts": len(active_alerts),
            "alerts": [a.to_dict() for a in active_alerts],
            "metrics": {
                "requests_5m": int(request_count),
                "errors_5m": int(error_count),
                "error_rate_5m": error_count / request_count if request_count > 0 else 0,
                "avg_response_time_ms": round(avg_response_time, 2),
            }
        }


# =============================================================================
# DECORATORS FOR AUTOMATIC MONITORING
# =============================================================================

# Global monitor instance
_monitor: Optional[APIMonitor] = None


def get_monitor() -> APIMonitor:
    """Get or create the global API monitor."""
    global _monitor
    if _monitor is None:
        _monitor = APIMonitor()
        _monitor.start()
    return _monitor


def monitored_request(func: Callable) -> Callable:
    """Decorator to automatically monitor Flask route handlers."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from flask import request
        monitor = get_monitor()
        start_time = time.perf_counter()

        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Get status code from result
            if hasattr(result, 'status_code'):
                status_code = result.status_code
            elif isinstance(result, tuple) and len(result) >= 2:
                status_code = result[1]
            else:
                status_code = 200

            monitor.record_request(
                request.method,
                request.path,
                status_code,
                duration_ms
            )
            return result

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            monitor.record_request(
                request.method,
                request.path,
                500,
                duration_ms
            )
            raise

    return wrapper


def monitored_external_api(service: str, operation: str):
    """Decorator to monitor external API calls."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            monitor = get_monitor()
            start_time = time.perf_counter()

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                monitor.record_external_api(service, operation, True, duration_ms)
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                monitor.record_external_api(service, operation, False, duration_ms)

                # Check for timeout
                if 'timeout' in str(e).lower():
                    monitor.record_timeout(service, operation, duration_ms / 1000)

                # Check for rate limiting
                if any(term in str(e).lower() for term in ['429', 'rate', 'quota']):
                    monitor.record_rate_limit(service, 30.0)  # Default retry

                raise

        return wrapper
    return decorator


def monitored_db_operation(operation: str):
    """Decorator to monitor database operations."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            monitor = get_monitor()
            start_time = time.perf_counter()

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                monitor.record_db_operation(operation, True, duration_ms)
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                monitor.record_db_operation(operation, False, duration_ms)
                raise

        return wrapper
    return decorator


# =============================================================================
# FLASK INTEGRATION
# =============================================================================

def setup_flask_monitoring(app):
    """Set up monitoring endpoints for Flask app."""
    monitor = get_monitor()

    @app.route('/health')
    def health():
        """Health check endpoint with bank sync diagnostics."""
        from flask import jsonify

        # Start with basic monitoring health
        health_data = monitor.health_check()

        # Add bank sync diagnostics
        try:
            from services.plaid_service import is_plaid_configured, get_plaid_service
            if is_plaid_configured():
                plaid = get_plaid_service()
                diagnostics = plaid.get_sync_diagnostics(user_id='default')

                health_data["bank_sync"] = {
                    "total_items": diagnostics['summary']['total_items'],
                    "active_items": diagnostics['summary']['active_items'],
                    "total_transactions": diagnostics['summary']['total_transactions'],
                    "issues_detected": diagnostics['summary']['total_issues'],
                    "date_filter": diagnostics['date_filter']['min_date'],
                    "items": []
                }

                for item in diagnostics['items']:
                    health_data["bank_sync"]["items"].append({
                        "institution": item['institution'],
                        "status": item['status'],
                        "has_cursor": item['has_cursor'],
                        "last_sync": item['last_successful_sync'],
                        "transactions": item['transactions']['total'],
                        "tx_range": f"{item['transactions']['earliest_date']} to {item['transactions']['latest_date']}" if item['transactions']['earliest_date'] else None,
                        "issues": item['issues'],
                        "recent_syncs": item['recent_syncs'][:3] if item.get('recent_syncs') else []
                    })
        except Exception as e:
            health_data["bank_sync"] = {"error": str(e)}

        return jsonify(health_data)

    @app.route('/metrics')
    def metrics():
        """Prometheus metrics endpoint."""
        from flask import Response
        return Response(
            monitor.metrics.export_prometheus(),
            mimetype='text/plain'
        )

    @app.route('/api/alerts')
    def alerts():
        """Get active alerts."""
        from flask import jsonify
        return jsonify({
            "active": [a.to_dict() for a in monitor.alerts.get_active_alerts()],
            "recent": [a.to_dict() for a in monitor.alerts.get_alert_history(50)],
        })

    # Automatically monitor all requests
    @app.before_request
    def before_request():
        from flask import g
        g.request_start_time = time.perf_counter()

    @app.after_request
    def after_request(response):
        from flask import request, g
        if hasattr(g, 'request_start_time'):
            duration_ms = (time.perf_counter() - g.request_start_time) * 1000
            monitor.record_request(
                request.method,
                request.path,
                response.status_code,
                duration_ms
            )
        return response

    logger.info("Flask monitoring endpoints configured")
    return app


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

__all__ = [
    # Core classes
    'MetricsCollector',
    'AlertManager',
    'APIMonitor',

    # Types
    'MetricType',
    'AlertSeverity',
    'MetricPoint',
    'Alert',
    'AlertRule',

    # Functions
    'get_monitor',
    'setup_flask_monitoring',

    # Decorators
    'monitored_request',
    'monitored_external_api',
    'monitored_db_operation',
]


if __name__ == '__main__':
    # Test the monitoring system
    monitor = get_monitor()

    # Simulate some metrics
    for i in range(10):
        monitor.record_request("GET", "/api/receipts", 200, 50 + i * 10)

    monitor.record_request("GET", "/api/error", 500, 100)
    monitor.record_request("GET", "/api/error", 500, 100)

    monitor.record_external_api("gemini", "analyze", True, 1500)
    monitor.record_external_api("openai", "generate", False, 5000)

    monitor.record_rate_limit("gemini", 30.0)

    monitor.record_receipt_match("local", True, 0.85)
    monitor.record_receipt_match("gmail", False, 0.45)

    # Get health status
    print("\n=== Health Check ===")
    health = monitor.health_check()
    print(json.dumps(health, indent=2))

    # Get Prometheus metrics
    print("\n=== Prometheus Metrics ===")
    print(monitor.metrics.export_prometheus())

    # Wait a moment and check for alerts
    print("\n=== Waiting for alert checks ===")
    time.sleep(35)  # Wait for at least one check cycle

    print("\n=== Active Alerts ===")
    for alert in monitor.alerts.get_active_alerts():
        print(f"  {alert.severity.value.upper()}: {alert.name} - {alert.message}")

    monitor.stop()
    print("\nMonitoring test complete!")
