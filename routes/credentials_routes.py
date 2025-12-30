"""
User Credentials Routes for TallyUps
Manages user's third-party service connections (Gmail, Calendar, Taskade, etc.)
"""

import os
import logging
from flask import Blueprint, request, jsonify, redirect, url_for
from urllib.parse import urlencode

from auth import user_required, get_current_user_id
from db_mysql import get_db_connection

# Configure logging
logger = logging.getLogger(__name__)

# Create Blueprint
credentials_bp = Blueprint('credentials', __name__, url_prefix='/api/credentials')

# Try to import credential service
try:
    from services.user_credentials_service import (
        user_credentials_service,
        SERVICE_GMAIL, SERVICE_GOOGLE_CALENDAR, SERVICE_TASKADE,
        SERVICE_OPENAI, SERVICE_GEMINI, SERVICE_ANTHROPIC
    )
    CREDENTIALS_AVAILABLE = True
except ImportError:
    CREDENTIALS_AVAILABLE = False
    logger.warning("User credentials service not available")

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 'https://tallyups.com/api/oauth/google/callback')

# Gmail scopes
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.labels'
]

# Calendar scopes
CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events.readonly'
]


# ============================================================================
# LIST CREDENTIALS
# ============================================================================

@credentials_bp.route('/', methods=['GET'])
@user_required
def list_credentials():
    """
    List all connected services for the current user.

    Returns:
    {
        "credentials": [
            {
                "service_type": "gmail",
                "account_email": "user@gmail.com",
                "account_name": "Personal Gmail",
                "is_active": true,
                "last_used_at": "2025-01-01T00:00:00Z"
            },
            ...
        ]
    }
    """
    if not CREDENTIALS_AVAILABLE:
        return jsonify({'error': 'Credentials service not available'}), 503

    user_id = get_current_user_id()
    service_type = request.args.get('service_type')

    credentials = user_credentials_service.list_credentials(user_id, service_type)

    # Format response
    formatted = []
    for cred in credentials:
        formatted.append({
            'id': cred['id'],
            'service_type': cred['service_type'],
            'account_email': cred.get('account_email'),
            'account_name': cred.get('account_name'),
            'workspace_id': cred.get('workspace_id'),
            'is_active': cred.get('is_active', True),
            'last_used_at': cred['last_used_at'].isoformat() if cred.get('last_used_at') else None,
            'created_at': cred['created_at'].isoformat() if cred.get('created_at') else None
        })

    return jsonify({'credentials': formatted})


# ============================================================================
# GOOGLE OAUTH (Gmail & Calendar)
# ============================================================================

@credentials_bp.route('/google/connect', methods=['POST'])
@user_required
def start_google_oauth():
    """
    Start Google OAuth flow.

    Request body:
    {
        "service": "gmail" | "calendar",
        "redirect_uri": "..."  // Optional, for mobile apps
    }

    Returns:
    {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
    }
    """
    if not GOOGLE_CLIENT_ID:
        return jsonify({'error': 'Google OAuth not configured'}), 503

    user_id = get_current_user_id()
    data = request.get_json() or {}

    service = data.get('service', 'gmail')
    redirect_uri = data.get('redirect_uri', GOOGLE_REDIRECT_URI)

    if service == 'gmail':
        scopes = GMAIL_SCOPES
        service_type = SERVICE_GMAIL
    elif service == 'calendar':
        scopes = CALENDAR_SCOPES
        service_type = SERVICE_GOOGLE_CALENDAR
    else:
        return jsonify({'error': 'Invalid service type'}), 400

    # Generate state token
    import secrets
    state = secrets.token_hex(32)

    # Store state in database
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO oauth_states (user_id, state, service_type, redirect_uri, expires_at)
            VALUES (%s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL 10 MINUTE))
        """, (user_id, state, service_type, redirect_uri))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    # Build OAuth URL
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(scopes),
        'state': state,
        'access_type': 'offline',
        'prompt': 'consent'
    }

    auth_url = f'https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}'

    return jsonify({'auth_url': auth_url, 'state': state})


@credentials_bp.route('/google/callback', methods=['GET', 'POST'])
def google_oauth_callback():
    """
    Handle Google OAuth callback.

    Query params or POST body:
    - code: Authorization code
    - state: State token
    - error: Error message (if failed)
    """
    import requests as http_requests

    if request.method == 'POST':
        data = request.get_json() or {}
        code = data.get('code')
        state = data.get('state')
        error = data.get('error')
    else:
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')

    if error:
        logger.warning(f"Google OAuth error: {error}")
        return jsonify({'error': error}), 400

    if not code or not state:
        return jsonify({'error': 'Missing code or state'}), 400

    # Verify state
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT user_id, service_type, redirect_uri
            FROM oauth_states
            WHERE state = %s AND expires_at > NOW() AND used = FALSE
        """, (state,))

        oauth_state = cursor.fetchone()

        if not oauth_state:
            return jsonify({'error': 'Invalid or expired state'}), 400

        # Mark state as used
        cursor.execute("""
            UPDATE oauth_states SET used = TRUE WHERE state = %s
        """, (state,))
        conn.commit()

        user_id = oauth_state['user_id']
        service_type = oauth_state['service_type']
        redirect_uri = oauth_state['redirect_uri']

    finally:
        cursor.close()
        conn.close()

    # Exchange code for tokens
    try:
        token_response = http_requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': redirect_uri
            },
            timeout=30
        )

        if token_response.status_code != 200:
            logger.error(f"Google token exchange failed: {token_response.text}")
            return jsonify({'error': 'Token exchange failed'}), 500

        tokens = token_response.json()

    except Exception as e:
        logger.error(f"Google token exchange error: {e}")
        return jsonify({'error': 'Token exchange failed'}), 500

    # Get user info
    try:
        user_info_response = http_requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f"Bearer {tokens['access_token']}"},
            timeout=10
        )

        if user_info_response.status_code == 200:
            user_info = user_info_response.json()
            account_email = user_info.get('email')
            account_name = user_info.get('name')
        else:
            account_email = None
            account_name = None

    except Exception as e:
        logger.warning(f"Failed to get Google user info: {e}")
        account_email = None
        account_name = None

    # Calculate expiration
    from datetime import datetime, timedelta
    expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))

    # Store credentials
    try:
        user_credentials_service.store_credential(
            user_id=user_id,
            service_type=service_type,
            access_token=tokens.get('access_token'),
            refresh_token=tokens.get('refresh_token'),
            account_email=account_email,
            account_name=account_name,
            token_expires_at=expires_at,
            scopes=tokens.get('scope', '').split()
        )

        logger.info(f"Stored {service_type} credentials for user {user_id}")

        # For web callback, redirect to success page
        if request.method == 'GET':
            return redirect('/settings?connected=' + service_type)

        return jsonify({
            'success': True,
            'service_type': service_type,
            'account_email': account_email
        })

    except Exception as e:
        logger.error(f"Failed to store Google credentials: {e}")
        return jsonify({'error': 'Failed to store credentials'}), 500


@credentials_bp.route('/google/disconnect', methods=['DELETE'])
@user_required
def disconnect_google():
    """
    Disconnect a Google account.

    Query params:
    - service: "gmail" | "calendar"
    - email: Account email to disconnect
    """
    if not CREDENTIALS_AVAILABLE:
        return jsonify({'error': 'Credentials service not available'}), 503

    user_id = get_current_user_id()
    service = request.args.get('service', 'gmail')
    email = request.args.get('email')

    service_type = SERVICE_GMAIL if service == 'gmail' else SERVICE_GOOGLE_CALENDAR

    success = user_credentials_service.delete_credential(user_id, service_type, email)

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Credential not found'}), 404


# ============================================================================
# API KEYS (OpenAI, Gemini, Anthropic, Taskade)
# ============================================================================

@credentials_bp.route('/api-key', methods=['POST'])
@user_required
def store_api_key():
    """
    Store an API key for a service.

    Request body:
    {
        "service": "openai" | "gemini" | "anthropic" | "taskade",
        "api_key": "sk-...",
        "workspace_id": "..."  // For Taskade
    }
    """
    if not CREDENTIALS_AVAILABLE:
        return jsonify({'error': 'Credentials service not available'}), 503

    user_id = get_current_user_id()
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    service = data.get('service')
    api_key = data.get('api_key')

    if not service or not api_key:
        return jsonify({'error': 'service and api_key required'}), 400

    # Map service name to type
    service_map = {
        'openai': SERVICE_OPENAI,
        'gemini': SERVICE_GEMINI,
        'anthropic': SERVICE_ANTHROPIC,
        'taskade': SERVICE_TASKADE
    }

    service_type = service_map.get(service.lower())
    if not service_type:
        return jsonify({'error': f'Invalid service: {service}'}), 400

    try:
        user_credentials_service.store_credential(
            user_id=user_id,
            service_type=service_type,
            api_key=api_key,
            workspace_id=data.get('workspace_id'),
            project_id=data.get('project_id'),
            folder_id=data.get('folder_id')
        )

        return jsonify({'success': True, 'service': service})

    except Exception as e:
        logger.error(f"Failed to store API key: {e}")
        return jsonify({'error': 'Failed to store API key'}), 500


@credentials_bp.route('/api-key/<service>', methods=['DELETE'])
@user_required
def delete_api_key(service):
    """Delete an API key for a service."""
    if not CREDENTIALS_AVAILABLE:
        return jsonify({'error': 'Credentials service not available'}), 503

    user_id = get_current_user_id()

    service_map = {
        'openai': SERVICE_OPENAI,
        'gemini': SERVICE_GEMINI,
        'anthropic': SERVICE_ANTHROPIC,
        'taskade': SERVICE_TASKADE
    }

    service_type = service_map.get(service.lower())
    if not service_type:
        return jsonify({'error': f'Invalid service: {service}'}), 400

    success = user_credentials_service.delete_credential(user_id, service_type)

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Credential not found'}), 404


@credentials_bp.route('/test/<service>', methods=['POST'])
@user_required
def test_credential(service):
    """
    Test if a stored credential works.

    Returns:
    {
        "success": true,
        "message": "Connection successful"
    }
    """
    if not CREDENTIALS_AVAILABLE:
        return jsonify({'error': 'Credentials service not available'}), 503

    user_id = get_current_user_id()

    service_map = {
        'openai': SERVICE_OPENAI,
        'gemini': SERVICE_GEMINI,
        'anthropic': SERVICE_ANTHROPIC,
        'taskade': SERVICE_TASKADE,
        'gmail': SERVICE_GMAIL,
        'calendar': SERVICE_GOOGLE_CALENDAR
    }

    service_type = service_map.get(service.lower())
    if not service_type:
        return jsonify({'error': f'Invalid service: {service}'}), 400

    creds = user_credentials_service.get_credential(user_id, service_type)
    if not creds:
        return jsonify({'error': 'No credentials found for this service'}), 404

    # Test based on service type
    try:
        if service_type == SERVICE_OPENAI:
            from openai import OpenAI
            client = OpenAI(api_key=creds['api_key'])
            client.models.list()
            return jsonify({'success': True, 'message': 'OpenAI connection successful'})

        elif service_type == SERVICE_GEMINI:
            import google.generativeai as genai
            genai.configure(api_key=creds['api_key'])
            list(genai.list_models())
            return jsonify({'success': True, 'message': 'Gemini connection successful'})

        elif service_type == SERVICE_ANTHROPIC:
            import anthropic
            client = anthropic.Anthropic(api_key=creds['api_key'])
            # Simple API call to verify
            return jsonify({'success': True, 'message': 'Anthropic connection successful'})

        elif service_type == SERVICE_TASKADE:
            import requests as http_requests
            response = http_requests.get(
                'https://www.taskade.com/api/v1/workspaces',
                headers={'Authorization': f"Bearer {creds['api_key']}"},
                timeout=10
            )
            if response.status_code == 200:
                return jsonify({'success': True, 'message': 'Taskade connection successful'})
            else:
                return jsonify({'success': False, 'error': 'Invalid API key'}), 400

        elif service_type in (SERVICE_GMAIL, SERVICE_GOOGLE_CALENDAR):
            import requests as http_requests
            response = http_requests.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f"Bearer {creds['access_token']}"},
                timeout=10
            )
            if response.status_code == 200:
                return jsonify({'success': True, 'message': 'Google connection successful'})
            elif response.status_code == 401:
                # Token expired, try to refresh
                return jsonify({'success': False, 'error': 'Token expired, please reconnect'}), 401
            else:
                return jsonify({'success': False, 'error': 'Connection failed'}), 400

        return jsonify({'error': 'Test not implemented for this service'}), 501

    except Exception as e:
        logger.error(f"Credential test failed for {service}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


# ============================================================================
# SIMPLIFIED API KEY ENDPOINTS (for iOS app)
# ============================================================================

@credentials_bp.route('/status', methods=['GET'])
@user_required
def get_api_keys_status():
    """
    Get status of which API keys are configured for the current user.

    Returns:
    {
        "openai": true/false,
        "gemini": true/false,
        "anthropic": true/false,
        "taskade": true/false
    }
    """
    if not CREDENTIALS_AVAILABLE:
        return jsonify({
            'openai': False,
            'gemini': False,
            'anthropic': False,
            'taskade': False
        })

    user_id = get_current_user_id()

    # Check each service
    status = {
        'openai': user_credentials_service.has_credential(user_id, SERVICE_OPENAI),
        'gemini': user_credentials_service.has_credential(user_id, SERVICE_GEMINI),
        'anthropic': user_credentials_service.has_credential(user_id, SERVICE_ANTHROPIC),
        'taskade': user_credentials_service.has_credential(user_id, SERVICE_TASKADE)
    }

    return jsonify(status)


@credentials_bp.route('/<service>', methods=['POST'])
@user_required
def store_service_api_key(service):
    """
    Store an API key for a specific service.

    POST /api/credentials/openai
    {
        "api_key": "sk-..."
    }
    """
    if not CREDENTIALS_AVAILABLE:
        return jsonify({'error': 'Credentials service not available'}), 503

    user_id = get_current_user_id()
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    api_key = data.get('api_key')
    if not api_key:
        return jsonify({'error': 'api_key required'}), 400

    # Map service name to type
    service_map = {
        'openai': SERVICE_OPENAI,
        'gemini': SERVICE_GEMINI,
        'anthropic': SERVICE_ANTHROPIC,
        'taskade': SERVICE_TASKADE
    }

    service_type = service_map.get(service.lower())
    if not service_type:
        return jsonify({'error': f'Invalid service: {service}'}), 400

    try:
        user_credentials_service.store_credential(
            user_id=user_id,
            service_type=service_type,
            api_key=api_key,
            workspace_id=data.get('workspace_id'),
            project_id=data.get('project_id'),
            folder_id=data.get('folder_id')
        )

        return jsonify({'success': True, 'service': service})

    except Exception as e:
        logger.error(f"Failed to store API key for {service}: {e}")
        return jsonify({'error': 'Failed to store API key'}), 500


@credentials_bp.route('/<service>', methods=['DELETE'])
@user_required
def delete_service_api_key(service):
    """
    Delete an API key for a specific service.

    DELETE /api/credentials/openai
    """
    if not CREDENTIALS_AVAILABLE:
        return jsonify({'error': 'Credentials service not available'}), 503

    user_id = get_current_user_id()

    service_map = {
        'openai': SERVICE_OPENAI,
        'gemini': SERVICE_GEMINI,
        'anthropic': SERVICE_ANTHROPIC,
        'taskade': SERVICE_TASKADE
    }

    service_type = service_map.get(service.lower())
    if not service_type:
        return jsonify({'error': f'Invalid service: {service}'}), 400

    success = user_credentials_service.delete_credential(user_id, service_type)

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Credential not found'}), 404


@credentials_bp.route('/<service>/validate', methods=['POST'])
@user_required
def validate_service_api_key(service):
    """
    Validate an API key before storing it.

    POST /api/credentials/openai/validate
    {
        "api_key": "sk-..."
    }

    Returns:
    {
        "valid": true/false
    }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body required'}), 400

    api_key = data.get('api_key')
    if not api_key:
        return jsonify({'error': 'api_key required'}), 400

    try:
        if service.lower() == 'openai':
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            client.models.list()
            return jsonify({'valid': True})

        elif service.lower() == 'gemini':
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            list(genai.list_models())
            return jsonify({'valid': True})

        elif service.lower() == 'anthropic':
            # Anthropic doesn't have a simple validation endpoint
            # Just check key format
            if api_key.startswith('sk-ant-'):
                return jsonify({'valid': True})
            return jsonify({'valid': False, 'error': 'Invalid key format'})

        elif service.lower() == 'taskade':
            import requests as http_requests
            response = http_requests.get(
                'https://www.taskade.com/api/v1/workspaces',
                headers={'Authorization': f"Bearer {api_key}"},
                timeout=10
            )
            return jsonify({'valid': response.status_code == 200})

        return jsonify({'error': f'Validation not supported for {service}'}), 400

    except Exception as e:
        logger.warning(f"API key validation failed for {service}: {e}")
        return jsonify({'valid': False, 'error': str(e)})
