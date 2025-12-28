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

@auth_bp.route('/login', methods=['POST'])
@auth_rate_limit('login')  # 5 per minute - prevent brute force
def email_login():
    """
    Login with email and password.
    Used for demo account and email-based users.

    Request body:
    {
        "email": "demo@tallyups.com",
        "password": "...",
        "device_id": "...",       // Unique device identifier
        "device_name": "iPhone"   // Optional
    }

    Returns:
    {
        "success": true,
        "access_token": "...",
        "refresh_token": "...",
        "user": {
            "id": "...",
            "email": "...",
            "name": "...",
            "role": "user",
            "onboarding_completed": true
        }
    }
    """
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'success': False, 'error': 'Multi-user mode not enabled'}), 503

    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    device_id = data.get('device_id', 'unknown')

    if not email:
        return jsonify({'success': False, 'error': 'Email required'}), 400
    if not password:
        return jsonify({'success': False, 'error': 'Password required'}), 400

    try:
        import bcrypt

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Find user by email
        cursor.execute("""
            SELECT id, email, name, password_hash, role, is_active,
                   is_demo_account, onboarding_completed
            FROM users
            WHERE email = %s
        """, (email,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            return jsonify({'success': False, 'error': 'Invalid email or password'}), 401

        if not user.get('password_hash'):
            conn.close()
            return jsonify({'success': False, 'error': 'Password login not enabled for this account'}), 401

        if not user.get('is_active', True):
            conn.close()
            return jsonify({'success': False, 'error': 'Account is disabled'}), 403

        # Verify password
        try:
            password_valid = bcrypt.checkpw(
                password.encode('utf-8'),
                user['password_hash'].encode('utf-8')
            )
        except Exception:
            password_valid = False

        if not password_valid:
            conn.close()
            return jsonify({'success': False, 'error': 'Invalid email or password'}), 401

        # Update last login
        cursor.execute("""
            UPDATE users SET last_login_at = NOW() WHERE id = %s
        """, (user['id'],))
        conn.commit()
        conn.close()

        # Create session/tokens
        if JWT_AVAILABLE:
            tokens = create_session(
                user_id=user['id'],
                device_id=device_id,
                device_name=data.get('device_name'),
                device_type=data.get('device_type', 'ios'),
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string
            )
        else:
            tokens = {'access_token': None, 'refresh_token': None}

        return jsonify({
            'success': True,
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),
            'user': {
                'id': user['id'],
                'email': user['email'],
                'name': user['name'],
                'role': user['role'],
                'onboarding_completed': user.get('onboarding_completed', False)
            }
        })

    except Exception as e:
        logger.error(f"Email login error: {e}")
        return jsonify({'success': False, 'error': 'Login failed'}), 500


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
        # Log the token info for debugging (first 50 chars only for security)
        logger.info(f"Apple Sign In attempt - token length: {len(identity_token)}, token start: {identity_token[:50]}...")

        # Verify Apple identity token
        try:
            apple_user_info = apple_auth_service.verify_identity_token(identity_token)
            logger.info(f"Apple token verified - user_id: {apple_user_info['apple_user_id']}, email: {apple_user_info.get('email')}")
        except Exception as verify_error:
            logger.error(f"Apple token verification failed: {verify_error}")
            # Provide more detail about verification failure
            import jwt
            try:
                # Decode without verification to see the token contents
                unverified = jwt.decode(identity_token, options={"verify_signature": False})
                logger.error(f"Token audience: {unverified.get('aud')}, issuer: {unverified.get('iss')}, sub: {unverified.get('sub')}")
                logger.error(f"Expected audience: {apple_auth_service.bundle_id}")
            except:
                pass
            raise verify_error

        # Get or create user
        user = get_or_create_user(
            apple_user_id=apple_user_info['apple_user_id'],
            email=apple_user_info.get('email'),
            name=data.get('user_name')
        )
        logger.info(f"User retrieved/created: {user['id']}, email: {user.get('email')}")

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

        logger.info(f"Apple Sign In successful for user {user['id']}")

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
        logger.error(f"Apple sign-in error: {e}", exc_info=True)
        return jsonify({'error': f'Authentication failed: {str(e)}'}), 500


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


# ============================================================================
# PASSWORD RESET
# ============================================================================

@auth_bp.route('/forgot-password', methods=['POST'])
@auth_rate_limit('forgot_password')  # 3 per hour per IP
def forgot_password():
    """
    Request a password reset email.

    Request body:
    {
        "email": "user@example.com"
    }

    Always returns success (to prevent email enumeration attacks).
    """
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'success': False, 'error': 'Multi-user mode not enabled'}), 503

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'success': False, 'error': 'Email required'}), 400

    try:
        import secrets
        import hashlib
        from datetime import datetime, timedelta

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check if user exists
        cursor.execute("""
            SELECT id, email, name, reset_attempts, last_reset_request
            FROM users
            WHERE email = %s AND is_active = TRUE
        """, (email,))
        user = cursor.fetchone()

        # Always return success to prevent email enumeration
        if not user:
            logger.info(f"Password reset requested for non-existent email: {email}")
            return jsonify({
                'success': True,
                'message': 'If an account exists with this email, a reset link will be sent.'
            })

        # Rate limit: max 3 reset requests per hour
        if user.get('last_reset_request'):
            time_since_last = datetime.now() - user['last_reset_request']
            if time_since_last < timedelta(minutes=5):
                logger.warning(f"Rate limited password reset for {email}")
                return jsonify({
                    'success': True,
                    'message': 'If an account exists with this email, a reset link will be sent.'
                })

        # Generate reset token (32 bytes = 64 hex chars)
        reset_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(reset_token.encode()).hexdigest()
        expires_at = datetime.now() + timedelta(hours=1)  # Token valid for 1 hour

        # Store token hash (never store the actual token)
        cursor.execute("""
            UPDATE users
            SET reset_token = %s,
                reset_token_expires = %s,
                reset_attempts = COALESCE(reset_attempts, 0) + 1,
                last_reset_request = NOW()
            WHERE id = %s
        """, (token_hash, expires_at, user['id']))

        # Log the request
        cursor.execute("""
            INSERT INTO password_reset_log (user_id, email, token_hash, ip_address, user_agent, status)
            VALUES (%s, %s, %s, %s, %s, 'requested')
        """, (user['id'], email, token_hash[:16], request.remote_addr, request.user_agent.string[:255] if request.user_agent.string else None))

        conn.commit()

        # Send reset email
        reset_url = f"https://tallyups.com/reset-password?token={reset_token}"
        _send_password_reset_email(email, user.get('name', 'User'), reset_url)

        logger.info(f"Password reset email sent to {email}")

        return jsonify({
            'success': True,
            'message': 'If an account exists with this email, a reset link will be sent.'
        })

    except Exception as e:
        logger.error(f"Password reset error: {e}")
        return jsonify({
            'success': True,  # Don't reveal errors
            'message': 'If an account exists with this email, a reset link will be sent.'
        })
    finally:
        cursor.close()
        conn.close()


@auth_bp.route('/reset-password', methods=['POST'])
@auth_rate_limit('reset_password')  # 5 per hour
def reset_password():
    """
    Reset password using a reset token.

    Request body:
    {
        "token": "...",
        "password": "new_password"
    }
    """
    if not MULTI_USER_TABLES_EXIST:
        return jsonify({'success': False, 'error': 'Multi-user mode not enabled'}), 503

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Request body required'}), 400

    token = data.get('token', '')
    new_password = data.get('password', '')

    if not token:
        return jsonify({'success': False, 'error': 'Reset token required'}), 400
    if not new_password:
        return jsonify({'success': False, 'error': 'New password required'}), 400
    if len(new_password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400

    try:
        import bcrypt
        import hashlib
        from datetime import datetime

        # Hash the provided token to compare with stored hash
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Find user with matching token that hasn't expired
        cursor.execute("""
            SELECT id, email, reset_token_expires
            FROM users
            WHERE reset_token = %s
              AND reset_token_expires > NOW()
              AND is_active = TRUE
        """, (token_hash,))
        user = cursor.fetchone()

        if not user:
            # Log failed attempt
            cursor.execute("""
                UPDATE password_reset_log
                SET status = 'invalid', completed_at = NOW()
                WHERE token_hash = %s AND status = 'requested'
            """, (token_hash[:16],))
            conn.commit()

            return jsonify({'success': False, 'error': 'Invalid or expired reset token'}), 400

        # Hash new password
        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Update password and clear reset token
        cursor.execute("""
            UPDATE users
            SET password_hash = %s,
                reset_token = NULL,
                reset_token_expires = NULL,
                updated_at = NOW()
            WHERE id = %s
        """, (password_hash, user['id']))

        # Revoke all existing sessions for security
        cursor.execute("""
            UPDATE user_sessions
            SET is_active = FALSE, revoked_at = NOW()
            WHERE user_id = %s AND is_active = TRUE
        """, (user['id'],))

        # Update reset log
        cursor.execute("""
            UPDATE password_reset_log
            SET status = 'completed', completed_at = NOW()
            WHERE token_hash = %s AND status = 'requested'
        """, (token_hash[:16],))

        # Log the event
        cursor.execute("""
            INSERT INTO session_events (user_id, event_type, ip_address, user_agent)
            VALUES (%s, 'password_reset', %s, %s)
        """, (user['id'], request.remote_addr, request.user_agent.string[:255] if request.user_agent.string else None))

        conn.commit()

        logger.info(f"Password reset successful for user {user['id']}")

        return jsonify({
            'success': True,
            'message': 'Password has been reset successfully. Please log in with your new password.'
        })

    except Exception as e:
        logger.error(f"Password reset error: {e}")
        return jsonify({'success': False, 'error': 'Password reset failed'}), 500
    finally:
        cursor.close()
        conn.close()


def _send_password_reset_email(email: str, name: str, reset_url: str):
    """Send password reset email using SMTP."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_password = os.environ.get('SMTP_PASSWORD', '')
    from_email = os.environ.get('SMTP_FROM', 'noreply@tallyups.com')
    from_name = os.environ.get('SMTP_FROM_NAME', 'TallyUps')

    if not smtp_user or not smtp_password:
        logger.warning("SMTP not configured, skipping password reset email")
        return

    subject = "Reset Your TallyUps Password"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #00FF88 0%, #00CC6A 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
            .header h1 {{ color: white; margin: 0; font-size: 24px; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
            .button {{ display: inline-block; background: #00FF88; color: #000; text-decoration: none; padding: 14px 28px; border-radius: 6px; font-weight: 600; margin: 20px 0; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
            .warning {{ background: #fff3cd; border: 1px solid #ffc107; padding: 12px; border-radius: 6px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TallyUps</h1>
            </div>
            <div class="content">
                <p>Hi {name},</p>
                <p>We received a request to reset your password for your TallyUps account.</p>
                <p>Click the button below to create a new password:</p>
                <p style="text-align: center;">
                    <a href="{reset_url}" class="button">Reset Password</a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666; font-size: 14px;">{reset_url}</p>
                <div class="warning">
                    <strong>This link expires in 1 hour.</strong><br>
                    If you didn't request a password reset, you can safely ignore this email.
                </div>
            </div>
            <div class="footer">
                <p>&copy; 2024 TallyUps. All rights reserved.</p>
                <p>This is an automated message, please do not reply.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
Hi {name},

We received a request to reset your password for your TallyUps account.

Click this link to create a new password:
{reset_url}

This link expires in 1 hour.

If you didn't request a password reset, you can safely ignore this email.

- The TallyUps Team
    """

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{from_name} <{from_email}>"
        msg['To'] = email

        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        logger.info(f"Password reset email sent to {email}")

    except Exception as e:
        logger.error(f"Failed to send password reset email: {e}")
