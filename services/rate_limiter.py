"""
Rate Limiter Service for TallyUps
Provides rate limiting capabilities that can be shared across blueprints
"""

import os
import logging
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)

# Try to import Flask-Limiter
RATE_LIMITER_AVAILABLE = False
limiter = None

def init_limiter(app):
    """
    Initialize the rate limiter with the Flask app.
    Should be called from the main app after Flask app is created.
    """
    global limiter, RATE_LIMITER_AVAILABLE

    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address

        # Use Redis in production, memory for development
        storage_uri = os.environ.get('REDIS_URL', 'memory://')

        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=["200 per day", "50 per hour"],
            storage_uri=storage_uri,
        )
        RATE_LIMITER_AVAILABLE = True
        logger.info(f"Rate limiter initialized with storage: {storage_uri}")
        return limiter
    except ImportError as e:
        logger.warning(f"Flask-Limiter not available: {e}")
        return None


def rate_limit(limit_string):
    """
    Decorator factory for rate limiting.

    Usage:
        @rate_limit("5 per minute")
        def my_endpoint():
            ...

    Args:
        limit_string: Rate limit specification (e.g., "5 per minute", "100 per hour")

    Returns:
        Decorator that applies rate limiting if available
    """
    def decorator(f):
        if RATE_LIMITER_AVAILABLE and limiter:
            return limiter.limit(limit_string)(f)
        return f
    return decorator


def get_limiter():
    """Get the limiter instance (for use with blueprints)."""
    return limiter


# Auth-specific rate limits
AUTH_RATE_LIMITS = {
    'login': "5 per minute",           # Strict for login attempts
    'register': "3 per minute",         # Very strict for registration
    'refresh': "30 per minute",         # More relaxed for token refresh
    'password_reset': "3 per hour",     # Very strict for password reset
    'logout': "10 per minute",          # Relaxed for logout
}


def auth_rate_limit(operation: str):
    """
    Get rate limit decorator for auth operations.

    Args:
        operation: One of 'login', 'register', 'refresh', 'password_reset', 'logout'

    Returns:
        Rate limit decorator
    """
    limit = AUTH_RATE_LIMITS.get(operation, "10 per minute")
    return rate_limit(limit)
