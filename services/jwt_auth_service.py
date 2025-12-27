"""
JWT Authentication Service for TallyUps
Handles token creation, validation, and refresh token management
"""

import os
import jwt
import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from functools import wraps

# Configure logging
logger = logging.getLogger(__name__)

# JWT Configuration
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', secrets.token_hex(32))
JWT_ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Token types
TOKEN_TYPE_ACCESS = 'access'
TOKEN_TYPE_REFRESH = 'refresh'


class JWTError(Exception):
    """Base exception for JWT errors"""
    pass


class TokenExpiredError(JWTError):
    """Token has expired"""
    pass


class InvalidTokenError(JWTError):
    """Token is invalid"""
    pass


class JWTAuthService:
    """
    JWT Authentication Service

    Handles:
    - Access token creation (short-lived, 15 minutes)
    - Refresh token creation (long-lived, 30 days)
    - Token validation and decoding
    - Token refresh flow
    """

    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or JWT_SECRET_KEY
        self.algorithm = JWT_ALGORITHM

    def create_access_token(
        self,
        user_id: str,
        role: str = 'user',
        additional_claims: Dict[str, Any] = None
    ) -> str:
        """
        Create a short-lived access token.

        Args:
            user_id: The user's UUID
            role: User role ('user' or 'admin')
            additional_claims: Extra claims to include in token

        Returns:
            JWT access token string
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        payload = {
            'sub': user_id,
            'type': TOKEN_TYPE_ACCESS,
            'role': role,
            'iat': now,
            'exp': expires,
            'jti': secrets.token_hex(16)  # Unique token ID
        }

        if additional_claims:
            payload.update(additional_claims)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(
        self,
        user_id: str,
        device_id: str,
        device_name: str = None
    ) -> Tuple[str, str, datetime]:
        """
        Create a long-lived refresh token.

        Args:
            user_id: The user's UUID
            device_id: Unique device identifier
            device_name: Human-readable device name

        Returns:
            Tuple of (refresh_token, token_hash, expires_at)
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        payload = {
            'sub': user_id,
            'type': TOKEN_TYPE_REFRESH,
            'device_id': device_id,
            'device_name': device_name,
            'iat': now,
            'exp': expires,
            'jti': secrets.token_hex(16)
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        token_hash = self._hash_token(token)

        return token, token_hash, expires

    def verify_token(self, token: str, expected_type: str = None) -> Dict[str, Any]:
        """
        Verify and decode a JWT token.

        Args:
            token: The JWT token string
            expected_type: Expected token type ('access' or 'refresh')

        Returns:
            Decoded token payload

        Raises:
            TokenExpiredError: If token has expired
            InvalidTokenError: If token is invalid
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )

            # Verify token type if specified
            if expected_type and payload.get('type') != expected_type:
                raise InvalidTokenError(f"Expected {expected_type} token, got {payload.get('type')}")

            return payload

        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Invalid token: {str(e)}")

    def verify_access_token(self, token: str) -> Dict[str, Any]:
        """Verify an access token and return the payload."""
        return self.verify_token(token, expected_type=TOKEN_TYPE_ACCESS)

    def verify_refresh_token(self, token: str) -> Dict[str, Any]:
        """Verify a refresh token and return the payload."""
        return self.verify_token(token, expected_type=TOKEN_TYPE_REFRESH)

    def refresh_tokens(
        self,
        refresh_token: str,
        device_id: str
    ) -> Tuple[str, str, str, datetime]:
        """
        Refresh access and refresh tokens.

        Args:
            refresh_token: Current refresh token
            device_id: Device ID for validation

        Returns:
            Tuple of (new_access_token, new_refresh_token, new_refresh_hash, expires_at)

        Raises:
            InvalidTokenError: If refresh token is invalid or device_id doesn't match
        """
        payload = self.verify_refresh_token(refresh_token)

        # Verify device_id matches
        if payload.get('device_id') != device_id:
            raise InvalidTokenError("Device ID mismatch")

        user_id = payload['sub']

        # Create new tokens
        new_access_token = self.create_access_token(user_id)
        new_refresh_token, new_hash, expires = self.create_refresh_token(
            user_id,
            device_id,
            payload.get('device_name')
        )

        return new_access_token, new_refresh_token, new_hash, expires

    def get_user_id_from_token(self, token: str) -> Optional[str]:
        """
        Extract user_id from token without full validation.
        Useful for logging/debugging but NOT for auth decisions.

        Args:
            token: JWT token string

        Returns:
            User ID or None if token is invalid
        """
        try:
            # Decode without verification (for inspection only)
            payload = jwt.decode(
                token,
                options={"verify_signature": False}
            )
            return payload.get('sub')
        except Exception:
            return None

    def _hash_token(self, token: str) -> str:
        """Hash a token for secure storage."""
        return hashlib.sha256(token.encode()).hexdigest()

    def verify_token_hash(self, token: str, stored_hash: str) -> bool:
        """Verify a token against a stored hash."""
        return secrets.compare_digest(self._hash_token(token), stored_hash)


# Global service instance
jwt_service = JWTAuthService()


def extract_bearer_token(auth_header: str) -> Optional[str]:
    """
    Extract token from Authorization header.

    Args:
        auth_header: Full Authorization header value

    Returns:
        Token string or None
    """
    if not auth_header:
        return None

    parts = auth_header.split()

    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None

    return parts[1]


# Flask integration helpers
def get_current_user_from_request():
    """
    Get current user from Flask request.

    Checks:
    1. Authorization header (Bearer token)
    2. X-Admin-Key header (legacy admin key)
    3. Session cookie (web interface)

    Returns:
        Dict with user info or None
    """
    from flask import request, session, g

    # Check for cached result
    if hasattr(g, '_current_user'):
        return g._current_user

    user = None

    # 1. Check Authorization header
    auth_header = request.headers.get('Authorization')
    token = extract_bearer_token(auth_header)

    if token:
        try:
            payload = jwt_service.verify_access_token(token)
            user = {
                'user_id': payload['sub'],
                'role': payload.get('role', 'user'),
                'auth_method': 'jwt'
            }
        except JWTError as e:
            logger.debug(f"JWT validation failed: {e}")

    # 2. Check X-Admin-Key header (legacy)
    if not user:
        admin_key = request.headers.get('X-Admin-Key') or request.args.get('admin_key')
        expected_key = os.environ.get('ADMIN_API_KEY')

        if expected_key and admin_key == expected_key:
            # Admin key users are always admins
            user = {
                'user_id': '00000000-0000-0000-0000-000000000001',
                'role': 'admin',
                'auth_method': 'admin_key'
            }

    # 3. Check session (web interface)
    if not user and session.get('authenticated'):
        # Session-based auth is for admin user
        user = {
            'user_id': session.get('user_id', '00000000-0000-0000-0000-000000000001'),
            'role': session.get('role', 'admin'),
            'auth_method': 'session'
        }

    # Cache result
    g._current_user = user
    return user


def user_required(f):
    """
    Decorator to require authenticated user.
    Sets g.user_id and g.user_role for the request.
    """
    from flask import g, jsonify

    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user_from_request()

        if not user:
            return jsonify({'error': 'Authentication required'}), 401

        g.user_id = user['user_id']
        g.user_role = user['role']
        g.auth_method = user['auth_method']

        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    """
    Decorator to require admin role.
    Must be used after @user_required or handles auth itself.
    """
    from flask import g, jsonify

    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user_from_request()

        if not user:
            return jsonify({'error': 'Authentication required'}), 401

        if user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        g.user_id = user['user_id']
        g.user_role = user['role']
        g.auth_method = user['auth_method']

        return f(*args, **kwargs)

    return decorated


def optional_auth(f):
    """
    Decorator that allows optional authentication.
    Sets g.user_id if authenticated, None otherwise.
    """
    from flask import g

    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user_from_request()

        if user:
            g.user_id = user['user_id']
            g.user_role = user['role']
            g.auth_method = user['auth_method']
        else:
            g.user_id = None
            g.user_role = None
            g.auth_method = None

        return f(*args, **kwargs)

    return decorated
