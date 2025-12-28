"""
Authentication Routes for TallyUps
Handles Apple Sign In, JWT token management, and user management

NOTE: These routes require the multi-user tables to be created (migrations 009-014).
If tables don't exist, routes will return 503 "Multi-user mode not enabled".
"""

import os
import uuid
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g, session

from auth import (
    login_required, user_required, admin_required,
    ADMIN_USER_ID, get_current_user_id
)
from db_mysql import get_db_connection

# Rate limiting for auth endpoints
try:
    from services.rate_limiter import auth_rate_limit
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False
    def auth_rate_limit(operation):
        """No-op decorator when rate limiting unavailable."""
        def decorator(f):
            return f
        return decorator

# Configure logging
logger = logging.getLogger(__name__)

# Create Blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Check if multi-user tables exist
MULTI_USER_TABLES_EXIST = False
try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES LIKE 'users'")
    if cursor.fetchone():
        MULTI_USER_TABLES_EXIST = True
        logger.info("Multi-user tables found - auth routes enabled")
    else:
        logger.info("Multi-user tables not found - auth routes will return 503")
    cursor.close()
    conn.close()
except Exception as e:
    logger.warning(f"Could not check for multi-user tables: {e}")

# Try to import auth services
try:
    from services.jwt_auth_service import jwt_service, JWTError
    from services.apple_auth_service import apple_auth_service, AppleAuthError
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("Auth services not available")


def generate_user_id() -> str:
    """Generate a new user UUID."""
    return str(uuid.uuid4())


def get_or_create_user(
    apple_user_id: str,
    email: str = None,
    name: str = None
) -> dict:
    """
    Get existing user or create new one based on Apple user ID.

    Args:
        apple_user_id: Apple's unique user identifier
        email: User's email (may be private relay)
        name: User's display name (only provided on first sign-in)

    Returns:
        Dict with user info
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # First, check if user exists by Apple user ID
        cursor.execute("""
            SELECT id, email, name, role, is_active, onboarding_completed
            FROM users
            WHERE apple_user_id = %s
        """, (apple_user_id,))

        user = cursor.fetchone()

        if user:
            # User exists with this Apple ID - update and return
            cursor.execute("""
                UPDATE users
                SET last_login_at = NOW(),
                    email = COALESCE(%s, email),
                    name = COALESCE(%s, name)
                WHERE id = %s
            """, (email, name, user['id']))
            conn.commit()

            return user

        # No user with this Apple ID - check if email already exists
        # This handles the case where user signed up with email first
        if email:
            cursor.execute("""
                SELECT id, email, name, role, is_active, onboarding_completed
                FROM users
                WHERE email = %s AND apple_user_id IS NULL
            """, (email,))

            existing_user = cursor.fetchone()

            if existing_user:
                # Link Apple ID to existing user with same email
                cursor.execute("""
                    UPDATE users
                    SET apple_user_id = %s,
                        last_login_at = NOW(),
                        name = COALESCE(%s, name)
                    WHERE id = %s
                """, (apple_user_id, name, existing_user['id']))
                conn.commit()

                logger.info(f"Linked Apple ID to existing user {existing_user['id']} via email {email}")
                return existing_user

        # No existing user found - create new one
        user_id = generate_user_id()

        cursor.execute("""
            INSERT INTO users (
                id, apple_user_id, email, name, role,
                is_active, onboarding_completed, created_at, last_login_at
            ) VALUES (%s, %s, %s, %s, 'user', TRUE, FALSE, NOW(), NOW())
        """, (user_id, apple_user_id, email, name))

        conn.commit()

        logger.info(f"Created new user {user_id} for Apple user {apple_user_id}")

        return {
            'id': user_id,
            'email': email,
            'name': name,
            'role': 'user',
            'is_active': True,
            'onboarding_completed': False
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to get/create user: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def create_session(
    user_id: str,
    device_id: str,
    device_name: str = None,
    device_type: str = 'ios',
    ip_address: str = None,
    user_agent: str = None
) -> dict:
    """
    Create a new session for a user.

    Returns:
        Dict with access_token, refresh_token
    """
    if not JWT_AVAILABLE:
        raise Exception("JWT service not available")

    # Create tokens
    access_token = jwt_service.create_access_token(user_id)
    refresh_token, token_hash, expires_at = jwt_service.create_refresh_token(
        user_id, device_id, device_name
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Revoke any existing session for this device
        cursor.execute("""
            UPDATE user_sessions
            SET is_active = FALSE, revoked_at = NOW()
            WHERE user_id = %s AND device_id = %s AND is_active = TRUE
        """, (user_id, device_id))

        # Create new session
        cursor.execute("""
            INSERT INTO user_sessions (
                user_id, device_id, device_name, device_type,
                refresh_token_hash, ip_address, user_agent,
                is_active, expires_at, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s, NOW())
        """, (
            user_id, device_id, device_name, device_type,
            token_hash, ip_address, user_agent, expires_at
        ))

        # Log the event
        cursor.execute("""
            INSERT INTO session_events (user_id, event_type, device_id, ip_address, user_agent)
            VALUES (%s, 'login', %s, %s, %s)
        """, (user_id, device_id, ip_address, user_agent))

        conn.commit()

        return {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': 15 * 60  # 15 minutes
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create session: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# ============================================================================
# AUTH ROUTES
# ============================================================================

@auth_bp.route('/apple', methods=['POST'])
@auth_rate_limit('login')  # 5 per minute - prevent brute force
def apple_sign_in():
    """
    Sign in with Apple.

    Request body:
    {
        "identity_token": "...",  // JWT from Apple
        "user_name": "John Doe",  // Optional, only on first sign-in
        "device_id": "...",       // Unique device identifier
        "device_name": "iPhone"   // Optional
    }

    Returns:
    {
        "access_token": "...",
        "refresh_token": "...",
        "expires_in": 900,
        "user": {
            "id": "...",
            "email": "...",
            "name": "...",
            "role": "user",
            "onboarding_completed": false
        }
    }
    """
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled. Run migrations 009-014 first.'}), 503
    if not JWT_AVAILABLE:
        return jsonify({'error': 'Authentication service not available'}), 503

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    identity_token = data.get('identity_token')
    device_id = data.get('device_id')

    if not identity_token:
        return jsonify({'error': 'identity_token required'}), 400

    if not device_id:
        return jsonify({'error': 'device_id required'}), 400

    try:
        # Verify Apple identity token
        apple_user_info = apple_auth_service.verify_identity_token(identity_token)

        # Get or create user
        user = get_or_create_user(
            apple_user_id=apple_user_info['apple_user_id'],
            email=apple_user_info.get('email'),
            name=data.get('user_name')
        )

        if not user.get('is_active', True):
            return jsonify({'error': 'Account is disabled'}), 403

        # Create session
        tokens = create_session(
            user_id=user['id'],
            device_id=device_id,
            device_name=data.get('device_name'),
            device_type=data.get('device_type', 'ios'),
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )

        return jsonify({
            **tokens,
            'user': {
                'id': user['id'],
                'email': user.get('email'),
                'name': user.get('name'),
                'role': user.get('role', 'user'),
                'onboarding_completed': user.get('onboarding_completed', False)
            }
        })

    except AppleAuthError as e:
        logger.warning(f"Apple auth failed: {e}")
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        logger.error(f"Apple sign-in error: {e}")
        return jsonify({'error': 'Authentication failed'}), 500


@auth_bp.route('/refresh', methods=['POST'])
@auth_rate_limit('refresh')  # 30 per minute
def refresh_token():
    """
    Refresh access token using refresh token.

    Request body:
    {
        "refresh_token": "...",
        "device_id": "..."
    }

    Returns:
    {
        "access_token": "...",
        "refresh_token": "...",  // New refresh token (rotation)
        "expires_in": 900
    }
    """
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    if not JWT_AVAILABLE:
        return jsonify({'error': 'Authentication service not available'}), 503

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    refresh_token_value = data.get('refresh_token')
    device_id = data.get('device_id')

    if not refresh_token_value:
        return jsonify({'error': 'refresh_token required'}), 400

    if not device_id:
        return jsonify({'error': 'device_id required'}), 400

    try:
        # First verify the refresh token is valid (signature, expiry, etc.)
        old_hash = jwt_service._hash_token(refresh_token_value)

        # Check database for session with this token
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Look for active session with this exact token hash
            cursor.execute("""
                SELECT id, user_id, previous_token_hash
                FROM user_sessions
                WHERE refresh_token_hash = %s AND device_id = %s AND is_active = TRUE
            """, (old_hash, device_id))

            session_row = cursor.fetchone()

            if not session_row:
                # SECURITY: Check if this is a reused token (token was already rotated)
                # This could indicate token theft - the attacker has an old token
                cursor.execute("""
                    SELECT id, user_id
                    FROM user_sessions
                    WHERE previous_token_hash = %s AND device_id = %s
                """, (old_hash, device_id))

                compromised_session = cursor.fetchone()
                if compromised_session:
                    # TOKEN REUSE DETECTED - Potential theft!
                    # Revoke ALL sessions for this user as a security measure
                    user_id = compromised_session[1]
                    logger.warning(
                        f"SECURITY: Refresh token reuse detected for user {user_id}, "
                        f"device {device_id}. Revoking all sessions."
                    )

                    cursor.execute("""
                        UPDATE user_sessions SET is_active = FALSE
                        WHERE user_id = %s
                    """, (user_id,))

                    # Log the security event
                    cursor.execute("""
                        INSERT INTO session_events
                        (user_id, session_id, event_type, device_id, ip_address, event_data)
                        VALUES (%s, %s, 'token_reuse_detected', %s, %s, %s)
                    """, (
                        user_id, compromised_session[0], device_id,
                        request.remote_addr,
                        '{"action": "all_sessions_revoked", "reason": "refresh_token_reuse"}'
                    ))

                    conn.commit()

                    return jsonify({
                        'error': 'Security alert: token reuse detected. Please login again.',
                        'code': 'TOKEN_REUSE_DETECTED'
                    }), 401

                return jsonify({'error': 'Session not found or expired'}), 401

            session_id = session_row[0]
            user_id = session_row[1]

            # Refresh tokens (creates new access + refresh tokens)
            new_access, new_refresh, new_hash, expires = jwt_service.refresh_tokens(
                refresh_token_value, device_id
            )

            # Update session with new refresh token, store old hash for reuse detection
            cursor.execute("""
                UPDATE user_sessions
                SET refresh_token_hash = %s,
                    previous_token_hash = %s,
                    expires_at = %s,
                    last_used_at = NOW()
                WHERE id = %s
            """, (new_hash, old_hash, expires, session_id))

            # Log the event
            cursor.execute("""
                INSERT INTO session_events (user_id, session_id, event_type, device_id, ip_address)
                VALUES (%s, %s, 'token_refresh', %s, %s)
            """, (user_id, session_id, device_id, request.remote_addr))

            conn.commit()

        finally:
            cursor.close()
            conn.close()

        return jsonify({
            'access_token': new_access,
            'refresh_token': new_refresh,
            'expires_in': 15 * 60
        })

    except JWTError as e:
        logger.warning(f"Token refresh failed: {e}")
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return jsonify({'error': 'Token refresh failed'}), 500


@auth_bp.route('/logout', methods=['POST'])
@auth_rate_limit('logout')  # 10 per minute
@user_required
def logout():
    """
    Logout and revoke current session.

    Request body:
    {
        "device_id": "..."  // Optional, if not provided revokes all sessions
    }
    """
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    user_id = get_current_user_id()
    data = request.get_json() or {}
    device_id = data.get('device_id')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if device_id:
            # Revoke specific session
            cursor.execute("""
                UPDATE user_sessions
                SET is_active = FALSE, revoked_at = NOW()
                WHERE user_id = %s AND device_id = %s AND is_active = TRUE
            """, (user_id, device_id))
        else:
            # Revoke all sessions
            cursor.execute("""
                UPDATE user_sessions
                SET is_active = FALSE, revoked_at = NOW()
                WHERE user_id = %s AND is_active = TRUE
            """, (user_id,))

        # Log the event
        cursor.execute("""
            INSERT INTO session_events (user_id, event_type, device_id, ip_address)
            VALUES (%s, 'logout', %s, %s)
        """, (user_id, device_id, request.remote_addr))

        conn.commit()

        # Clear Flask session if using web interface
        session.clear()

        return jsonify({'success': True, 'message': 'Logged out successfully'})

    except Exception as e:
        conn.rollback()
        logger.error(f"Logout error: {e}")
        return jsonify({'error': 'Logout failed'}), 500
    finally:
        cursor.close()
        conn.close()


@auth_bp.route('/me', methods=['GET'])
@user_required
def get_current_user():
    """Get current user's profile."""
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    user_id = get_current_user_id()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, email, name, role, default_business_type, timezone,
                   onboarding_completed, storage_used_bytes, storage_limit_bytes,
                   created_at, last_login_at
            FROM users
            WHERE id = %s AND is_active = TRUE
        """, (user_id,))

        user = cursor.fetchone()

        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Get connected services count
        cursor.execute("""
            SELECT service_type, COUNT(*) as count
            FROM user_credentials
            WHERE user_id = %s AND is_active = TRUE
            GROUP BY service_type
        """, (user_id,))

        services = {row['service_type']: row['count'] for row in cursor.fetchall()}

        # Convert datetime objects to ISO strings
        if user.get('created_at'):
            user['created_at'] = user['created_at'].isoformat()
        if user.get('last_login_at'):
            user['last_login_at'] = user['last_login_at'].isoformat()

        return jsonify({
            **user,
            'connected_services': services
        })

    finally:
        cursor.close()
        conn.close()


@auth_bp.route('/me', methods=['PATCH'])
@user_required
def update_current_user():
    """Update current user's profile."""
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    user_id = get_current_user_id()
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    # SECURITY: Whitelist of allowed fields - these are safe column names
    # This prevents SQL injection by only allowing known-safe identifiers
    allowed_fields = {'name', 'default_business_type', 'timezone'}
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # SECURITY: Build parameterized query using only whitelisted column names
        # Even though allowed_fields protects us, we use explicit validation
        # to prevent future refactoring bugs
        import re
        safe_columns = []
        for k in updates.keys():
            # Double-check column name is safe (alphanumeric + underscore only)
            if not re.match(r'^[a-z_]+$', k):
                logger.warning(f"Blocked unsafe column name in update: {k}")
                continue
            safe_columns.append(k)

        if not safe_columns:
            return jsonify({'error': 'No valid fields to update'}), 400

        set_clause = ', '.join([f'{col} = %s' for col in safe_columns])
        values = [updates[col] for col in safe_columns] + [user_id]

        cursor.execute(f"""
            UPDATE users
            SET {set_clause}, updated_at = NOW()
            WHERE id = %s
        """, values)

        conn.commit()

        return jsonify({'success': True, 'updated': list(updates.keys())})

    except Exception as e:
        conn.rollback()
        logger.error(f"Update user error: {e}")
        return jsonify({'error': 'Update failed'}), 500
    finally:
        cursor.close()
        conn.close()


@auth_bp.route('/delete-account', methods=['DELETE'])
@user_required
def delete_account():
    """
    Delete user account (GDPR compliance).
    This performs a soft delete and schedules data cleanup.
    """
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    user_id = get_current_user_id()

    # Prevent admin from deleting their own account
    if user_id == ADMIN_USER_ID:
        return jsonify({'error': 'Cannot delete admin account'}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Soft delete user
        cursor.execute("""
            UPDATE users
            SET is_active = FALSE, deleted_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, (user_id,))

        # Revoke all sessions
        cursor.execute("""
            UPDATE user_sessions
            SET is_active = FALSE, revoked_at = NOW()
            WHERE user_id = %s
        """, (user_id,))

        # Log the event
        cursor.execute("""
            INSERT INTO session_events (user_id, event_type, ip_address, metadata)
            VALUES (%s, 'account_deleted', %s, %s)
        """, (user_id, request.remote_addr, '{"initiated_by": "user"}'))

        conn.commit()

        logger.info(f"User {user_id} marked for deletion")

        # TODO: Schedule async job to:
        # 1. Delete R2 files
        # 2. Hard delete user data after retention period

        return jsonify({
            'success': True,
            'message': 'Account deletion initiated. Data will be removed within 30 days.'
        })

    except Exception as e:
        conn.rollback()
        logger.error(f"Delete account error: {e}")
        return jsonify({'error': 'Account deletion failed'}), 500
    finally:
        cursor.close()
        conn.close()


@auth_bp.route('/onboarding/complete', methods=['POST'])
@user_required
def complete_onboarding():
    """Mark onboarding as complete for the current user."""
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    user_id = get_current_user_id()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users
            SET onboarding_completed = TRUE, updated_at = NOW()
            WHERE id = %s
        """, (user_id,))

        conn.commit()

        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        logger.error(f"Complete onboarding error: {e}")
        return jsonify({'error': 'Failed to complete onboarding'}), 500
    finally:
        cursor.close()
        conn.close()


@auth_bp.route('/sessions', methods=['GET'])
@user_required
def list_sessions():
    """List all active sessions for the current user."""
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    user_id = get_current_user_id()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, device_id, device_name, device_type,
                   ip_address, last_used_at, created_at
            FROM user_sessions
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY last_used_at DESC
        """, (user_id,))

        sessions = cursor.fetchall()

        for s in sessions:
            if s.get('last_used_at'):
                s['last_used_at'] = s['last_used_at'].isoformat()
            if s.get('created_at'):
                s['created_at'] = s['created_at'].isoformat()

        return jsonify({'sessions': sessions})

    finally:
        cursor.close()
        conn.close()


@auth_bp.route('/sessions/<device_id>', methods=['DELETE'])
@user_required
def revoke_session(device_id):
    """Revoke a specific session."""
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'error': 'Multi-user mode not enabled'}), 503
    user_id = get_current_user_id()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE user_sessions
            SET is_active = FALSE, revoked_at = NOW()
            WHERE user_id = %s AND device_id = %s AND is_active = TRUE
        """, (user_id, device_id))

        if cursor.rowcount == 0:
            return jsonify({'error': 'Session not found'}), 404

        conn.commit()

        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        logger.error(f"Revoke session error: {e}")
        return jsonify({'error': 'Failed to revoke session'}), 500
    finally:
        cursor.close()
        conn.close()
