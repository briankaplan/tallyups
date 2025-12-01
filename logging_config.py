#!/usr/bin/env python3
"""
logging_config.py — Structured Logging Configuration for ReceiptAI
-------------------------------------------------------------------

Provides a consistent, structured logging setup with:
  - JSON-formatted logs for production (machine-parseable)
  - Human-readable colored logs for development
  - Context injection (request IDs, user info, etc.)
  - Performance timing decorators
  - Error tracking with stack traces
  - Log rotation and archival
"""

import os
import sys
import json
import time
import logging
import traceback
import functools
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Callable
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from contextlib import contextmanager

# Thread-local storage for request context
_context = threading.local()


# =============================================================================
# LOG FORMATTERS
# =============================================================================

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging in production."""

    def __init__(self, include_timestamp: bool = True, include_context: bool = True):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_context = include_context

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if self.include_timestamp:
            log_data["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Add context from thread-local storage
        if self.include_context and hasattr(_context, 'data'):
            log_data["context"] = dict(_context.data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info) if record.exc_info[0] else None
            }

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ('name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'pathname', 'process', 'processName', 'relativeCreated',
                          'stack_info', 'exc_info', 'exc_text', 'message', 'thread',
                          'threadName', 'taskName'):
                try:
                    json.dumps(value)  # Check if serializable
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored formatter for development console output."""

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[41m',  # Red background
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)

        # Build the message
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        level = f"{color}{record.levelname:8}{self.RESET}"

        # Add context if available
        context_str = ""
        if hasattr(_context, 'data') and _context.data:
            context_parts = [f"{k}={v}" for k, v in _context.data.items()]
            context_str = f" [{', '.join(context_parts)}]"

        message = record.getMessage()

        # Format the log line
        log_line = f"{timestamp} {level} {record.name:25}{context_str} | {message}"

        # Add exception info if present
        if record.exc_info:
            log_line += f"\n{self.COLORS['ERROR']}"
            log_line += "".join(traceback.format_exception(*record.exc_info))
            log_line += self.RESET

        return log_line


# =============================================================================
# CONTEXT MANAGEMENT
# =============================================================================

def set_context(**kwargs) -> None:
    """Set logging context for the current thread."""
    if not hasattr(_context, 'data'):
        _context.data = {}
    _context.data.update(kwargs)


def clear_context() -> None:
    """Clear logging context for the current thread."""
    if hasattr(_context, 'data'):
        _context.data.clear()


def get_context() -> Dict[str, Any]:
    """Get current logging context."""
    return dict(getattr(_context, 'data', {}))


@contextmanager
def log_context(**kwargs):
    """Context manager for temporary logging context."""
    old_context = get_context()
    try:
        set_context(**kwargs)
        yield
    finally:
        clear_context()
        if old_context:
            set_context(**old_context)


# =============================================================================
# PERFORMANCE TIMING
# =============================================================================

def timed(logger: Optional[logging.Logger] = None, level: int = logging.DEBUG):
    """Decorator to log function execution time."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            log = logger or logging.getLogger(func.__module__)
            start_time = time.perf_counter()

            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start_time) * 1000
                log.log(level, f"{func.__name__} completed in {elapsed:.2f}ms")
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start_time) * 1000
                log.error(f"{func.__name__} failed after {elapsed:.2f}ms: {e}")
                raise

        return wrapper
    return decorator


@contextmanager
def log_timing(logger: logging.Logger, operation: str, level: int = logging.DEBUG):
    """Context manager to log operation timing."""
    start_time = time.perf_counter()
    try:
        yield
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.log(level, f"{operation} completed in {elapsed:.2f}ms")
    except Exception as e:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.error(f"{operation} failed after {elapsed:.2f}ms: {e}")
        raise


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(
    app_name: str = "receiptai",
    log_level: str = "INFO",
    log_dir: Optional[str] = None,
    json_format: bool = False,
    console_output: bool = True,
    file_output: bool = True,
    max_file_size_mb: int = 10,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure structured logging for the application.

    Args:
        app_name: Base name for the application logger
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files (default: ./logs)
        json_format: Use JSON formatting (for production)
        console_output: Output logs to console
        file_output: Output logs to files
        max_file_size_mb: Max size per log file before rotation
        backup_count: Number of backup log files to keep

    Returns:
        The configured root logger
    """
    # Determine log level
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Create log directory if needed
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        if json_format:
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(ColoredFormatter())

        root_logger.addHandler(console_handler)

    # File handlers
    if file_output:
        # Main log file (rotating by size)
        main_log_file = log_path / f"{app_name}.log"
        main_handler = RotatingFileHandler(
            main_log_file,
            maxBytes=max_file_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        main_handler.setLevel(level)
        main_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(main_handler)

        # Error log file (errors and above)
        error_log_file = log_path / f"{app_name}_errors.log"
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=max_file_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(error_handler)

    # Reduce noise from third-party libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


# =============================================================================
# SPECIALIZED LOGGERS
# =============================================================================

class ReceiptLogger:
    """Specialized logger for receipt operations."""

    def __init__(self, name: str = "receiptai.receipts"):
        self.logger = logging.getLogger(name)

    def receipt_matched(self, transaction_id: str, receipt_file: str,
                       score: float, source: str, method: str):
        """Log a successful receipt match."""
        self.logger.info(
            "Receipt matched",
            extra={
                "event": "receipt_matched",
                "transaction_id": transaction_id,
                "receipt_file": receipt_file,
                "match_score": score,
                "source": source,
                "method": method,
            }
        )

    def receipt_not_found(self, transaction_id: str, merchant: str,
                         amount: float, best_score: float = 0):
        """Log a failed receipt match."""
        self.logger.warning(
            "Receipt not found",
            extra={
                "event": "receipt_not_found",
                "transaction_id": transaction_id,
                "merchant": merchant,
                "amount": amount,
                "best_score": best_score,
            }
        )

    def receipt_uploaded(self, filename: str, size_bytes: int,
                        transaction_id: Optional[str] = None):
        """Log a receipt upload."""
        self.logger.info(
            "Receipt uploaded",
            extra={
                "event": "receipt_uploaded",
                "filename": filename,
                "size_bytes": size_bytes,
                "transaction_id": transaction_id,
            }
        )


class APILogger:
    """Specialized logger for API operations."""

    def __init__(self, name: str = "receiptai.api"):
        self.logger = logging.getLogger(name)

    def request_started(self, method: str, path: str, request_id: str):
        """Log API request start."""
        self.logger.debug(
            f"Request started: {method} {path}",
            extra={
                "event": "request_started",
                "method": method,
                "path": path,
                "request_id": request_id,
            }
        )

    def request_completed(self, method: str, path: str, status_code: int,
                         duration_ms: float, request_id: str):
        """Log API request completion."""
        level = logging.INFO if status_code < 400 else logging.WARNING
        self.logger.log(
            level,
            f"Request completed: {method} {path} -> {status_code} ({duration_ms:.2f}ms)",
            extra={
                "event": "request_completed",
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
            }
        )

    def external_api_call(self, service: str, operation: str,
                         success: bool, duration_ms: float,
                         error: Optional[str] = None):
        """Log external API call."""
        level = logging.INFO if success else logging.WARNING
        self.logger.log(
            level,
            f"External API: {service}.{operation} -> {'success' if success else 'failed'}",
            extra={
                "event": "external_api_call",
                "service": service,
                "operation": operation,
                "success": success,
                "duration_ms": duration_ms,
                "error": error,
            }
        )

    def rate_limited(self, service: str, retry_after: float, attempt: int):
        """Log rate limiting event."""
        self.logger.warning(
            f"Rate limited by {service}, retry in {retry_after:.1f}s (attempt {attempt})",
            extra={
                "event": "rate_limited",
                "service": service,
                "retry_after_seconds": retry_after,
                "attempt": attempt,
            }
        )


class SyncLogger:
    """Specialized logger for sync operations."""

    def __init__(self, name: str = "receiptai.sync"):
        self.logger = logging.getLogger(name)

    def sync_started(self, source: str, record_count: int = 0):
        """Log sync operation start."""
        self.logger.info(
            f"Sync started from {source}",
            extra={
                "event": "sync_started",
                "source": source,
                "record_count": record_count,
            }
        )

    def sync_completed(self, source: str, created: int, updated: int,
                      skipped: int, duration_ms: float):
        """Log sync operation completion."""
        self.logger.info(
            f"Sync completed from {source}: {created} created, {updated} updated, {skipped} skipped",
            extra={
                "event": "sync_completed",
                "source": source,
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "duration_ms": duration_ms,
            }
        )

    def sync_conflict(self, source: str, record_id: str,
                     conflicting_fields: list, resolution: str):
        """Log sync conflict."""
        self.logger.warning(
            f"Sync conflict in {source} for {record_id}: {', '.join(conflicting_fields)} -> {resolution}",
            extra={
                "event": "sync_conflict",
                "source": source,
                "record_id": record_id,
                "conflicting_fields": conflicting_fields,
                "resolution": resolution,
            }
        )

    def sync_error(self, source: str, error: str, record_id: Optional[str] = None):
        """Log sync error."""
        self.logger.error(
            f"Sync error from {source}: {error}",
            extra={
                "event": "sync_error",
                "source": source,
                "error": error,
                "record_id": record_id,
            }
        )


class DatabaseLogger:
    """Specialized logger for database operations."""

    def __init__(self, name: str = "receiptai.database"):
        self.logger = logging.getLogger(name)

    def query_executed(self, query_type: str, table: str,
                      duration_ms: float, rows_affected: int = 0):
        """Log database query execution."""
        self.logger.debug(
            f"Query: {query_type} on {table} ({duration_ms:.2f}ms, {rows_affected} rows)",
            extra={
                "event": "query_executed",
                "query_type": query_type,
                "table": table,
                "duration_ms": duration_ms,
                "rows_affected": rows_affected,
            }
        )

    def connection_acquired(self, pool_size: int, available: int):
        """Log connection pool acquisition."""
        self.logger.debug(
            f"Connection acquired (pool: {available}/{pool_size})",
            extra={
                "event": "connection_acquired",
                "pool_size": pool_size,
                "available_connections": available,
            }
        )

    def connection_pool_exhausted(self, wait_time_ms: float):
        """Log connection pool exhaustion."""
        self.logger.warning(
            f"Connection pool exhausted, waited {wait_time_ms:.2f}ms",
            extra={
                "event": "connection_pool_exhausted",
                "wait_time_ms": wait_time_ms,
            }
        )

    def migration_applied(self, migration_name: str, duration_ms: float):
        """Log database migration."""
        self.logger.info(
            f"Migration applied: {migration_name}",
            extra={
                "event": "migration_applied",
                "migration_name": migration_name,
                "duration_ms": duration_ms,
            }
        )


# =============================================================================
# FLASK INTEGRATION
# =============================================================================

def flask_request_logger(app):
    """Add request logging middleware to Flask app."""
    import uuid
    from flask import request, g

    @app.before_request
    def before_request():
        g.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4())[:8])
        g.start_time = time.perf_counter()
        set_context(request_id=g.request_id)

        api_logger = APILogger()
        api_logger.request_started(request.method, request.path, g.request_id)

    @app.after_request
    def after_request(response):
        if hasattr(g, 'start_time'):
            duration_ms = (time.perf_counter() - g.start_time) * 1000
            api_logger = APILogger()
            api_logger.request_completed(
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                getattr(g, 'request_id', 'unknown')
            )

        # Add request ID to response headers
        if hasattr(g, 'request_id'):
            response.headers['X-Request-ID'] = g.request_id

        clear_context()
        return response

    return app


# =============================================================================
# INITIALIZATION
# =============================================================================

# Auto-initialize based on environment
_initialized = False

def init_logging():
    """Initialize logging based on environment variables."""
    global _initialized
    if _initialized:
        return

    env = os.getenv('FLASK_ENV', os.getenv('ENVIRONMENT', 'development'))
    json_format = env in ('production', 'staging')
    log_level = os.getenv('LOG_LEVEL', 'DEBUG' if env == 'development' else 'INFO')

    setup_logging(
        app_name="receiptai",
        log_level=log_level,
        json_format=json_format,
        console_output=True,
        file_output=True,
    )

    _initialized = True
    logging.getLogger(__name__).info(
        f"Logging initialized",
        extra={
            "environment": env,
            "log_level": log_level,
            "json_format": json_format,
        }
    )


# Convenience exports
__all__ = [
    # Setup
    'setup_logging',
    'init_logging',
    'get_logger',

    # Context management
    'set_context',
    'clear_context',
    'get_context',
    'log_context',

    # Timing
    'timed',
    'log_timing',

    # Specialized loggers
    'ReceiptLogger',
    'APILogger',
    'SyncLogger',
    'DatabaseLogger',

    # Flask integration
    'flask_request_logger',

    # Formatters
    'JSONFormatter',
    'ColoredFormatter',
]


if __name__ == '__main__':
    # Test the logging setup
    setup_logging(log_level="DEBUG", json_format=False)

    logger = get_logger("test")

    # Test basic logging
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")

    # Test with context
    with log_context(user_id="12345", request_id="abc123"):
        logger.info("Message with context")

    # Test timing decorator
    @timed(logger)
    def slow_function():
        import time
        time.sleep(0.1)
        return "done"

    slow_function()

    # Test specialized loggers
    receipt_logger = ReceiptLogger()
    receipt_logger.receipt_matched("tx-123", "receipt.jpg", 0.95, "local", "vision")

    api_logger = APILogger()
    api_logger.rate_limited("gemini", 30.0, 2)

    sync_logger = SyncLogger()
    sync_logger.sync_completed("google", 10, 5, 2, 1234.5)

    print("\nLogging test complete!")
