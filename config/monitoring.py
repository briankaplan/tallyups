"""
ReceiptAI Monitoring and Alerting Configuration
================================================
Provides monitoring, metrics collection, and alerting capabilities.

Features:
- Health check monitoring
- Performance metrics collection
- Error rate tracking
- Alert thresholds and notifications
"""

import os
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    RATE = "rate"


@dataclass
class Alert:
    """Represents an alert."""
    name: str
    severity: AlertSeverity
    message: str
    value: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "severity": self.severity.value,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


@dataclass
class AlertRule:
    """Defines an alert rule."""
    name: str
    metric_name: str
    condition: str  # 'gt', 'lt', 'gte', 'lte', 'eq'
    threshold: float
    severity: AlertSeverity
    message_template: str
    cooldown_seconds: int = 300  # Don't re-alert for 5 minutes
    last_alert_time: Optional[datetime] = None


class MetricsCollector:
    """
    Collects and stores application metrics.

    Thread-safe metrics collection with configurable retention.
    """

    def __init__(self, retention_minutes: int = 60):
        self.retention_minutes = retention_minutes
        self._metrics: Dict[str, deque] = {}
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._lock = threading.Lock()

        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def increment(self, name: str, value: float = 1.0, tags: Dict[str, str] = None):
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, tags)
            self._counters[key] = self._counters.get(key, 0) + value
            self._record_metric(key, self._counters[key], MetricType.COUNTER)

    def gauge(self, name: str, value: float, tags: Dict[str, str] = None):
        """Set a gauge metric."""
        with self._lock:
            key = self._make_key(name, tags)
            self._gauges[key] = value
            self._record_metric(key, value, MetricType.GAUGE)

    def timing(self, name: str, duration_ms: float, tags: Dict[str, str] = None):
        """Record a timing metric."""
        with self._lock:
            key = self._make_key(name, tags)
            self._record_metric(key, duration_ms, MetricType.HISTOGRAM)

    def _make_key(self, name: str, tags: Dict[str, str] = None) -> str:
        """Create a unique key for a metric."""
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"

    def _record_metric(self, key: str, value: float, metric_type: MetricType):
        """Record a metric value with timestamp."""
        if key not in self._metrics:
            self._metrics[key] = deque(maxlen=10000)
        self._metrics[key].append({
            "timestamp": datetime.utcnow(),
            "value": value,
            "type": metric_type.value,
        })

    def get_metric(self, name: str, tags: Dict[str, str] = None,
                   minutes: int = 5) -> List[Dict]:
        """Get recent values for a metric."""
        with self._lock:
            key = self._make_key(name, tags)
            if key not in self._metrics:
                return []

            cutoff = datetime.utcnow() - timedelta(minutes=minutes)
            return [
                m for m in self._metrics[key]
                if m["timestamp"] >= cutoff
            ]

    def get_rate(self, name: str, tags: Dict[str, str] = None,
                 minutes: int = 1) -> float:
        """Calculate rate of a counter over time period."""
        values = self.get_metric(name, tags, minutes)
        if len(values) < 2:
            return 0.0

        time_diff = (values[-1]["timestamp"] - values[0]["timestamp"]).total_seconds()
        if time_diff == 0:
            return 0.0

        value_diff = values[-1]["value"] - values[0]["value"]
        return value_diff / time_diff * 60  # per minute

    def get_average(self, name: str, tags: Dict[str, str] = None,
                    minutes: int = 5) -> float:
        """Calculate average value over time period."""
        values = self.get_metric(name, tags, minutes)
        if not values:
            return 0.0
        return sum(m["value"] for m in values) / len(values)

    def get_percentile(self, name: str, percentile: float,
                       tags: Dict[str, str] = None, minutes: int = 5) -> float:
        """Calculate percentile value over time period."""
        values = self.get_metric(name, tags, minutes)
        if not values:
            return 0.0

        sorted_values = sorted(m["value"] for m in values)
        index = int(len(sorted_values) * percentile / 100)
        return sorted_values[min(index, len(sorted_values) - 1)]

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get summary of all metrics."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "metric_count": len(self._metrics),
            }

    def _cleanup_loop(self):
        """Background thread to clean up old metrics."""
        while True:
            time.sleep(60)  # Run every minute
            self._cleanup_old_metrics()

    def _cleanup_old_metrics(self):
        """Remove metrics older than retention period."""
        with self._lock:
            cutoff = datetime.utcnow() - timedelta(minutes=self.retention_minutes)
            for key in list(self._metrics.keys()):
                # Remove old values
                while self._metrics[key] and self._metrics[key][0]["timestamp"] < cutoff:
                    self._metrics[key].popleft()
                # Remove empty metric
                if not self._metrics[key]:
                    del self._metrics[key]


class AlertManager:
    """
    Manages alert rules and notifications.

    Supports multiple notification channels and alert deduplication.
    """

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics
        self.rules: List[AlertRule] = []
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: deque = deque(maxlen=1000)
        self._lock = threading.Lock()
        self._notifiers: List[Callable[[Alert], None]] = []

        # Register default rules
        self._register_default_rules()

    def _register_default_rules(self):
        """Register default alert rules."""
        # Error rate alert
        self.add_rule(AlertRule(
            name="high_error_rate",
            metric_name="http_errors_total",
            condition="gt",
            threshold=10,  # More than 10 errors per minute
            severity=AlertSeverity.WARNING,
            message_template="High error rate: {value:.1f} errors/min (threshold: {threshold})",
        ))

        # Critical error rate
        self.add_rule(AlertRule(
            name="critical_error_rate",
            metric_name="http_errors_total",
            condition="gt",
            threshold=50,  # More than 50 errors per minute
            severity=AlertSeverity.CRITICAL,
            message_template="CRITICAL error rate: {value:.1f} errors/min (threshold: {threshold})",
        ))

        # Database connection pool
        self.add_rule(AlertRule(
            name="db_pool_exhaustion",
            metric_name="db_pool_utilization",
            condition="gt",
            threshold=90,  # More than 90% pool utilization
            severity=AlertSeverity.ERROR,
            message_template="Database pool nearly exhausted: {value:.1f}% (threshold: {threshold}%)",
        ))

        # Slow response time
        self.add_rule(AlertRule(
            name="slow_responses",
            metric_name="http_request_duration_p99",
            condition="gt",
            threshold=5000,  # p99 > 5 seconds
            severity=AlertSeverity.WARNING,
            message_template="Slow response times: p99={value:.0f}ms (threshold: {threshold}ms)",
        ))

        # Memory usage
        self.add_rule(AlertRule(
            name="high_memory",
            metric_name="process_memory_percent",
            condition="gt",
            threshold=85,
            severity=AlertSeverity.WARNING,
            message_template="High memory usage: {value:.1f}% (threshold: {threshold}%)",
        ))

    def add_rule(self, rule: AlertRule):
        """Add an alert rule."""
        self.rules.append(rule)

    def add_notifier(self, notifier: Callable[[Alert], None]):
        """Add a notification handler."""
        self._notifiers.append(notifier)

    def check_rules(self):
        """Check all rules against current metrics."""
        for rule in self.rules:
            self._check_rule(rule)

    def _check_rule(self, rule: AlertRule):
        """Check a single rule."""
        # Get metric value based on type
        if rule.metric_name.endswith("_total"):
            value = self.metrics.get_rate(rule.metric_name, minutes=1)
        elif rule.metric_name.endswith("_p99"):
            base_name = rule.metric_name.replace("_p99", "")
            value = self.metrics.get_percentile(base_name, 99, minutes=5)
        else:
            value = self.metrics.get_average(rule.metric_name, minutes=1)

        # Check condition
        triggered = False
        if rule.condition == "gt" and value > rule.threshold:
            triggered = True
        elif rule.condition == "lt" and value < rule.threshold:
            triggered = True
        elif rule.condition == "gte" and value >= rule.threshold:
            triggered = True
        elif rule.condition == "lte" and value <= rule.threshold:
            triggered = True
        elif rule.condition == "eq" and value == rule.threshold:
            triggered = True

        with self._lock:
            if triggered:
                self._trigger_alert(rule, value)
            else:
                self._resolve_alert(rule)

    def _trigger_alert(self, rule: AlertRule, value: float):
        """Trigger an alert."""
        # Check cooldown
        if rule.last_alert_time:
            elapsed = (datetime.utcnow() - rule.last_alert_time).total_seconds()
            if elapsed < rule.cooldown_seconds:
                return

        # Create alert
        alert = Alert(
            name=rule.name,
            severity=rule.severity,
            message=rule.message_template.format(value=value, threshold=rule.threshold),
            value=value,
            threshold=rule.threshold,
        )

        # Store alert
        self.active_alerts[rule.name] = alert
        self.alert_history.append(alert)
        rule.last_alert_time = datetime.utcnow()

        # Notify
        self._notify(alert)

        logger.warning(f"Alert triggered: {alert.name} - {alert.message}")

    def _resolve_alert(self, rule: AlertRule):
        """Resolve an active alert."""
        if rule.name not in self.active_alerts:
            return

        alert = self.active_alerts[rule.name]
        alert.resolved = True
        alert.resolved_at = datetime.utcnow()

        del self.active_alerts[rule.name]

        logger.info(f"Alert resolved: {alert.name}")

    def _notify(self, alert: Alert):
        """Send notifications for an alert."""
        for notifier in self._notifiers:
            try:
                notifier(alert)
            except Exception as e:
                logger.error(f"Notifier failed: {e}")

    def get_active_alerts(self) -> List[Dict]:
        """Get all active alerts."""
        with self._lock:
            return [a.to_dict() for a in self.active_alerts.values()]

    def get_alert_history(self, limit: int = 100) -> List[Dict]:
        """Get recent alert history."""
        with self._lock:
            return [a.to_dict() for a in list(self.alert_history)[-limit:]]


class HealthChecker:
    """
    Comprehensive health checking system.

    Checks various system components and reports overall health.
    """

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics
        self._checks: Dict[str, Callable[[], Dict]] = {}
        self._last_results: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def register_check(self, name: str, check_fn: Callable[[], Dict]):
        """Register a health check function."""
        self._checks[name] = check_fn

    def run_checks(self) -> Dict:
        """Run all health checks."""
        results = {}
        overall_healthy = True

        for name, check_fn in self._checks.items():
            try:
                start = time.time()
                result = check_fn()
                duration_ms = (time.time() - start) * 1000

                results[name] = {
                    **result,
                    "duration_ms": round(duration_ms, 2),
                }

                if result.get("status") != "healthy":
                    overall_healthy = False

            except Exception as e:
                results[name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                overall_healthy = False

        with self._lock:
            self._last_results = results

        return {
            "status": "healthy" if overall_healthy else "unhealthy",
            "checks": results,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_last_results(self) -> Dict:
        """Get results from last health check."""
        with self._lock:
            return dict(self._last_results)


# =============================================================================
# NOTIFICATION HANDLERS
# =============================================================================

def slack_notifier(webhook_url: str) -> Callable[[Alert], None]:
    """Create a Slack notification handler."""
    import requests

    def notify(alert: Alert):
        color = {
            AlertSeverity.INFO: "#36a64f",
            AlertSeverity.WARNING: "#ffcc00",
            AlertSeverity.ERROR: "#ff6600",
            AlertSeverity.CRITICAL: "#ff0000",
        }.get(alert.severity, "#808080")

        payload = {
            "attachments": [{
                "color": color,
                "title": f"[{alert.severity.value.upper()}] {alert.name}",
                "text": alert.message,
                "fields": [
                    {"title": "Value", "value": str(alert.value), "short": True},
                    {"title": "Threshold", "value": str(alert.threshold), "short": True},
                ],
                "ts": int(alert.timestamp.timestamp()),
            }]
        }

        try:
            requests.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Slack notification failed: {e}")

    return notify


def log_notifier() -> Callable[[Alert], None]:
    """Create a log-based notification handler (for development)."""
    def notify(alert: Alert):
        level = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.ERROR: logging.ERROR,
            AlertSeverity.CRITICAL: logging.CRITICAL,
        }.get(alert.severity, logging.INFO)

        logger.log(level, f"ALERT: {alert.name} - {alert.message}")

    return notify


# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

# Initialize global instances
metrics_collector = MetricsCollector()
alert_manager = AlertManager(metrics_collector)
health_checker = HealthChecker(metrics_collector)

# Add log notifier by default
alert_manager.add_notifier(log_notifier())

# Add Slack notifier if configured
slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
if slack_webhook:
    alert_manager.add_notifier(slack_notifier(slack_webhook))


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector."""
    return metrics_collector


def get_alert_manager() -> AlertManager:
    """Get the global alert manager."""
    return alert_manager


def get_health_checker() -> HealthChecker:
    """Get the global health checker."""
    return health_checker
