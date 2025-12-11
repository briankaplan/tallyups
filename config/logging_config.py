#!/usr/bin/env python3
"""
ReceiptAI Logging Configuration
===============================

Structured JSON logging for production with:
- Request context tracking
- Error alerting to monitoring services
- Performance timing
- Correlation IDs for request tracing
"""

import os
import sys
import json
import time
import logging
import traceback
from datetime import datetime
from functools import wraps
from typing import Optional, Dict, Any
from contextlib import contextmanager
import threading

# Try to import structlog for better structured logging
try:
    import structlog
    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False


# ==========================================================================
# CUSTOM LOG FORMATTER
# ==========================================================================

class JSONFormatter(logging.Formatter):
    """
    Format logs as JSON for structured logging.

    Compatible with Railway, Datadog, and most log aggregators.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }

        # Add extra fields
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "extra"):
            log_data.update(record.extra)

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Build message
        msg = f"{color}{timestamp} [{record.levelname:8}]{self.RESET} {record.name}: {record.getMessage()}"

        # Add exception
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"

        return msg


# ==========================================================================
# REQUEST CONTEXT
# ==========================================================================

class RequestContext:
    """Thread-local storage for request context."""

    _local = threading.local()

    @classmethod
    def set(cls, **kwargs):
        """Set context values."""
        if not hasattr(cls._local, "context"):
            cls._local.context = {}
        cls._local.context.update(kwargs)

    @classmethod
    def get(cls, key: str, default=None):
        """Get a context value."""
        if not hasattr(cls._local, "context"):
            return default
        return cls._local.context.get(key, default)

    @classmethod
    def clear(cls):
        """Clear all context."""
        cls._local.context = {}

    @classmethod
    def as_dict(cls) -> Dict[str, Any]:
        """Get all context as dict."""
        if not hasattr(cls._local, "context"):
            return {}
        return cls._local.context.copy()


# ==========================================================================
# LOGGER CLASSES
# ==========================================================================

class ContextLogger(logging.LoggerAdapter):
    """Logger that automatically includes request context."""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra.update(RequestContext.as_dict())
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> ContextLogger:
    """
    Get a context-aware logger.

    Usage:
        logger = get_logger(__name__)
        logger.info("Processing receipt", extra={"receipt_id": 123})
    """
    logger = logging.getLogger(name)
    return ContextLogger(logger, {})


# ==========================================================================
# TIMING DECORATOR
# ==========================================================================

def log_timing(operation: str = None):
    """
    Decorator to log function execution time.

    Usage:
        @log_timing("process_receipt")
        def process_receipt(receipt_id):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            logger = get_logger(func.__module__)

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                logger.info(
                    f"{op_name} completed",
                    extra={"operation": op_name, "duration_ms": round(duration_ms, 2), "status": "success"}
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{op_name} failed: {e}",
                    extra={"operation": op_name, "duration_ms": round(duration_ms, 2), "status": "error"},
                    exc_info=True
                )
                raise

        return wrapper
    return decorator


@contextmanager
def log_timing_context(operation: str, logger: Optional[logging.Logger] = None):
    """
    Context manager for timing code blocks.

    Usage:
        with log_timing_context("database_query"):
            result = db.execute(query)
    """
    if logger is None:
        logger = get_logger(__name__)

    start = time.perf_counter()
    try:
        yield
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"{operation} completed",
            extra={"operation": operation, "duration_ms": round(duration_ms, 2)}
        )
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.error(
            f"{operation} failed: {e}",
            extra={"operation": operation, "duration_ms": round(duration_ms, 2)},
            exc_info=True
        )
        raise


# ==========================================================================
# DATABASE LOGGER
# ==========================================================================

class DatabaseLogger:
    """Specialized logger for database operations."""

    def __init__(self):
        self.logger = get_logger("db")

    def query(self, sql: str, duration_ms: float, rows: int = 0):
        """Log a database query."""
        # Truncate long queries
        sql_preview = sql[:200] + "..." if len(sql) > 200 else sql
        self.logger.debug(
            f"Query executed",
            extra={
                "sql_preview": sql_preview,
                "duration_ms": round(duration_ms, 2),
                "rows_affected": rows,
            }
        )

    def slow_query(self, sql: str, duration_ms: float, threshold_ms: float = 1000):
        """Log a slow query warning."""
        if duration_ms > threshold_ms:
            self.logger.warning(
                f"Slow query detected",
                extra={
                    "sql": sql[:500],
                    "duration_ms": round(duration_ms, 2),
                    "threshold_ms": threshold_ms,
                }
            )

    def connection_error(self, error: Exception, retry_count: int = 0):
        """Log a connection error."""
        self.logger.error(
            f"Database connection error: {error}",
            extra={"retry_count": retry_count},
            exc_info=True
        )

    def pool_status(self, available: int, in_use: int, overflow: int):
        """Log pool status."""
        self.logger.debug(
            "Connection pool status",
            extra={
                "pool_available": available,
                "pool_in_use": in_use,
                "pool_overflow": overflow,
            }
        )


# ==========================================================================
# SETUP FUNCTION
# ==========================================================================

def setup_logging(
    app=None,
    level: str = "INFO",
    json_output: bool = None,
    log_file: Optional[str] = None
):
    """
    Configure logging for the application.

    Args:
        app: Flask app (optional)
        level: Logging level
        json_output: Force JSON output (auto-detected for production)
        log_file: Optional log file path
    """
    # Determine if we should use JSON output
    if json_output is None:
        # Use JSON in production, console in development
        env = os.environ.get("RAILWAY_ENVIRONMENT", "development")
        json_output = env == "production"

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))

    if json_output:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)

    # Configure Flask app logging
    if app:
        # Add request context middleware
        @app.before_request
        def add_request_context():
            from flask import request
            import uuid

            RequestContext.clear()
            RequestContext.set(
                request_id=request.headers.get("X-Request-ID", str(uuid.uuid4())[:8]),
                request_path=request.path,
                request_method=request.method,
            )

        @app.after_request
        def log_request(response):
            from flask import request

            logger = get_logger("http")
            logger.info(
                f"{request.method} {request.path} {response.status_code}",
                extra={
                    "status_code": response.status_code,
                    "content_length": response.content_length,
                }
            )
            return response

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger = get_logger(__name__)
    logger.info(f"Logging configured: level={level}, json={json_output}")

    return root_logger


# ==========================================================================
# ERROR ALERTING (for production)
# ==========================================================================

class AlertHandler(logging.Handler):
    """
    Handler that sends alerts for critical errors.

    Integrates with Datadog, PagerDuty, or Slack.
    """

    def __init__(self, webhook_url: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.webhook_url = webhook_url
        self.setLevel(logging.ERROR)

    def emit(self, record: logging.LogRecord):
        if not self.webhook_url:
            return

        try:
            import requests

            payload = {
                "text": f"🚨 *{record.levelname}*: {record.getMessage()}",
                "attachments": [{
                    "color": "danger" if record.levelname == "CRITICAL" else "warning",
                    "fields": [
                        {"title": "Module", "value": record.module, "short": True},
                        {"title": "Function", "value": record.funcName, "short": True},
                    ]
                }]
            }

            if record.exc_info:
                payload["attachments"][0]["fields"].append({
                    "title": "Exception",
                    "value": f"```{traceback.format_exc()[:1000]}```",
                    "short": False,
                })

            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception:
            pass  # Don't fail on alert errors


# ==========================================================================
# EXPORTS
# ==========================================================================

__all__ = [
    "setup_logging",
    "get_logger",
    "log_timing",
    "log_timing_context",
    "RequestContext",
    "DatabaseLogger",
    "JSONFormatter",
    "ConsoleFormatter",
    "AlertHandler",
]
