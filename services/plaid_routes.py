#!/usr/bin/env python3
"""
================================================================================
Plaid API Routes
================================================================================
Author: Claude Code
Created: 2025-12-20

Flask Blueprint for Plaid integration endpoints.
Provides REST API for account linking, transaction sync, and webhooks.

ENDPOINTS:
----------
Account Linking:
    POST /api/plaid/link-token       - Create a Plaid Link token
    POST /api/plaid/exchange-token   - Exchange public token for access token

Account Management:
    GET  /api/plaid/items            - List all linked Items
    GET  /api/plaid/items/<id>       - Get Item details
    DELETE /api/plaid/items/<id>     - Remove an Item

    GET  /api/plaid/accounts         - List all accounts
    PUT  /api/plaid/accounts/<id>    - Update account settings

Transactions:
    GET  /api/plaid/transactions        - List transactions
    GET  /api/plaid/transactions/by-source - Get transactions grouped by card/account
    POST /api/plaid/sync                - Trigger manual sync
    GET  /api/plaid/sync/status         - Get sync status
    GET  /api/plaid/sync/diagnose       - Get detailed sync diagnostics
    POST /api/plaid/sync/reset          - Reset sync cursor for fresh sync
    POST /api/plaid/sync/refresh        - Reset cursor and trigger sync
    POST /api/plaid/sync/import         - Import to main transactions table

Webhooks:
    POST /api/plaid/webhook          - Receive Plaid webhooks

SECURITY:
---------
- All endpoints require authentication (except webhook)
- Access tokens are NEVER returned to clients
- Webhook signatures are verified
- Rate limiting is applied

================================================================================
"""

import os
import json
import logging
from functools import wraps
from datetime import datetime
from typing import Optional

from flask import Blueprint, request, jsonify, g, current_app

# Create blueprint
plaid_bp = Blueprint('plaid', __name__, url_prefix='/api/plaid')

# Logger
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


# =============================================================================
# AUTHENTICATION DECORATOR
# =============================================================================

def require_auth(f):
    """
    Decorator to require authentication for Plaid endpoints.

    Uses JWT auth when available, falls back to session for backward compatibility.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Try to get user from JWT or session
        user_id = get_user_id()
        if not user_id or user_id == 'default':
            # Check if we should enforce auth in production
            import os
            if os.environ.get('REQUIRE_AUTH', '').lower() == 'true':
                return jsonify({'success': False, 'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function


def get_user_id():
    """
    Get the current user ID from JWT token, Flask g context, or session.

    Priority:
    1. g.user_id (set by JWT middleware)
    2. session['user_id'] (legacy session auth)
    3. ADMIN_USER_ID (for backward compatibility - all existing data belongs to admin)
    """
    from flask import session, g

    # Admin user ID - all existing data is assigned to this user
    ADMIN_USER_ID = 'admin-00000000-0000-0000-0000-000000000000'

    # First check g.user_id (set by JWT auth middleware)
    if hasattr(g, 'user_id') and g.user_id:
        return g.user_id

    # Fall back to session (legacy auth)
    if 'user_id' in session and session['user_id']:
        return session['user_id']

    # Try to get from db_user_scope helper
    try:
        from db_user_scope import get_current_user_id
        user_id = get_current_user_id()
        if user_id:
            return user_id
    except ImportError:
        pass

    # Default to admin user - all existing data belongs to admin
    return ADMIN_USER_ID


# =============================================================================
# PLAID SERVICE HELPER
# =============================================================================

def get_plaid():
    """Get the Plaid service instance."""
    from services.plaid_service import get_plaid_service, is_plaid_configured

    if not is_plaid_configured():
        raise ValueError("Plaid is not configured. Set PLAID_CLIENT_ID and PLAID_SECRET environment variables.")

    return get_plaid_service()


# =============================================================================
# CONNECTION CACHE (prevents excessive Plaid API calls)
# =============================================================================

import time
from threading import Lock

_connection_cache = {}
_cache_lock = Lock()
_CACHE_TTL_SECONDS = 300  # 5 minutes

# Sync rate limiting - only allow 1 sync per day per item to control Plaid costs
_SYNC_RATE_LIMIT_HOURS = 24  # Minimum hours between syncs


def _get_cached_items(user_id: str):
    """Get cached items for a user, or None if cache is stale/missing."""
    with _cache_lock:
        cache_entry = _connection_cache.get(user_id)
        if cache_entry:
            items, timestamp = cache_entry
            if time.time() - timestamp < _CACHE_TTL_SECONDS:
                return items
    return None


def _set_cached_items(user_id: str, items):
    """Cache items for a user."""
    with _cache_lock:
        _connection_cache[user_id] = (items, time.time())


def _invalidate_cache(user_id: str):
    """Invalidate cache for a user (after connection changes)."""
    with _cache_lock:
        if user_id in _connection_cache:
            del _connection_cache[user_id]


def _check_sync_rate_limit(item) -> dict:
    """
    Check if an item can be synced based on daily rate limit.

    Returns:
        dict with 'allowed' bool, 'hours_until_next' if not allowed,
        and 'last_sync' timestamp
    """
    from datetime import datetime, timedelta

    if not item.last_successful_sync:
        return {'allowed': True, 'last_sync': None}

    now = datetime.now()
    hours_since_sync = (now - item.last_successful_sync).total_seconds() / 3600

    if hours_since_sync >= _SYNC_RATE_LIMIT_HOURS:
        return {
            'allowed': True,
            'last_sync': item.last_successful_sync.isoformat(),
            'hours_since': round(hours_since_sync, 1)
        }
    else:
        hours_until_next = _SYNC_RATE_LIMIT_HOURS - hours_since_sync
        return {
            'allowed': False,
            'last_sync': item.last_successful_sync.isoformat(),
            'hours_since': round(hours_since_sync, 1),
            'hours_until_next': round(hours_until_next, 1),
            'next_sync_allowed': (item.last_successful_sync + timedelta(hours=_SYNC_RATE_LIMIT_HOURS)).isoformat()
        }


# =============================================================================
# LINK TOKEN ENDPOINTS
# =============================================================================

@plaid_bp.route('/check-connections', methods=['GET'])
@require_auth
def check_existing_connections():
    """
    Check user's existing Plaid connections before starting Link flow.

    This helps prevent duplicate connections which cost money.
    Call this before showing the "Add Bank" button.

    Query Parameters:
        institution_id: Optional - check if specific institution is connected

    Response:
        {
            "success": true,
            "has_connections": true,
            "connection_count": 3,
            "connections": [
                {
                    "item_id": "xxx",
                    "institution_id": "ins_xxx",
                    "institution_name": "Chase",
                    "status": "active",
                    "account_count": 2
                }
            ],
            "institution_connected": true,  // Only if institution_id provided
            "warning": "You already have Chase connected..."  // If duplicate
        }
    """
    try:
        plaid = get_plaid()
        user_id = get_user_id()
        institution_id = request.args.get('institution_id')

        # Try to get from cache first
        items = _get_cached_items(user_id)
        if items is None:
            items = plaid.get_items(user_id=user_id)
            _set_cached_items(user_id, items)

        connections = []
        for item in items:
            accounts = plaid.get_accounts(item.item_id)
            connections.append({
                'item_id': item.item_id,
                'institution_id': item.institution_id,
                'institution_name': item.institution_name,
                'status': item.status.value,
                'account_count': len(accounts),
                'last_sync': item.last_successful_sync.isoformat() if item.last_successful_sync else None
            })

        response = {
            'success': True,
            'has_connections': len(connections) > 0,
            'connection_count': len(connections),
            'connections': connections
        }

        # Check specific institution if requested
        if institution_id:
            existing = next(
                (c for c in connections if c['institution_id'] == institution_id and c['status'] == 'active'),
                None
            )
            response['institution_connected'] = existing is not None
            if existing:
                response['warning'] = (
                    f"You already have {existing['institution_name']} connected with "
                    f"{existing['account_count']} account(s). Adding it again will incur additional costs. "
                    f"Use 'Update Connection' instead if you need to re-authenticate."
                )
                response['existing_item_id'] = existing['item_id']

        return jsonify(response)

    except Exception as e:
        logger.error(f"Check connections error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/debug-config', methods=['GET'])
def debug_plaid_config():
    """Debug endpoint to check Plaid configuration (no secrets exposed)."""
    import os
    from services.plaid_service import PlaidConfig, is_plaid_configured, PLAID_SDK_AVAILABLE
    config = PlaidConfig()
    return jsonify({
        'sdk_available': PLAID_SDK_AVAILABLE,
        'configured': is_plaid_configured(),
        'client_id_prefix': config.client_id[:8] + '...' if config.client_id else None,
        'secret_prefix': config.secret[:8] + '...' if config.secret else None,
        'environment': config.environment,
        'env_client_id': os.environ.get('PLAID_CLIENT_ID', '')[:8] + '...' if os.environ.get('PLAID_CLIENT_ID') else 'NOT SET',
        'env_secret': os.environ.get('PLAID_SECRET', '')[:8] + '...' if os.environ.get('PLAID_SECRET') else 'NOT SET',
        'env_plaid_env': os.environ.get('PLAID_ENV', 'NOT SET')
    })


@plaid_bp.route('/link-token', methods=['POST'])
@require_auth
def create_link_token():
    """
    Create a Plaid Link token for account linking.

    Request Body (optional):
        {
            "update_item_id": "item-xxx"  // For re-authentication
        }

    Response:
        {
            "success": true,
            "link_token": "link-sandbox-xxx",
            "expiration": "2025-12-20T18:00:00Z"
        }
    """
    try:
        plaid = get_plaid()

        data = request.get_json() or {}
        update_item_id = data.get('update_item_id')

        # Get redirect URI - REQUIRED for OAuth banks (Chase, BofA, etc.)
        # Must match EXACTLY what's configured in Plaid Dashboard
        redirect_uri = data.get('redirect_uri')
        if not redirect_uri:
            # Use configured base URL or fall back to request host
            base_url = os.environ.get('BASE_URL', '').rstrip('/')
            if not base_url:
                base_url = request.host_url.rstrip('/')
            redirect_uri = f"{base_url}/api/plaid/oauth"
            logger.info(f"Using redirect_uri: {redirect_uri}")

        result = plaid.create_link_token(
            user_id=get_user_id(),
            update_item_id=update_item_id,
            redirect_uri=redirect_uri
        )

        return jsonify({
            'success': True,
            'link_token': result['link_token'],
            'expiration': result['expiration'],
            'request_id': result.get('request_id')
        })

    except ValueError as e:
        logger.warning(f"Link token creation failed: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

    except Exception as e:
        import traceback
        logger.error(f"Link token creation error: {e}")
        logger.error(f"Link token traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'Failed to create link token: {str(e)}',
            'details': str(type(e).__name__)
        }), 500


@plaid_bp.route('/exchange-token', methods=['POST'])
@require_auth
def exchange_public_token():
    """
    Exchange a public token from Plaid Link for an access token.

    Called after user completes the Plaid Link flow.

    IMPORTANT: This creates a new Plaid Item which incurs costs.
    The endpoint checks for duplicate connections to prevent unnecessary charges.

    Request Body:
        {
            "public_token": "public-sandbox-xxx",
            "institution_id": "ins_xxx",  // Optional: for duplicate check
            "force": false  // Optional: skip duplicate check
        }

    Response:
        {
            "success": true,
            "item": {
                "item_id": "xxx",
                "institution_name": "Chase",
                "status": "active"
            },
            "accounts": [...]
        }
    """
    try:
        plaid = get_plaid()
        user_id = get_user_id()

        data = request.get_json()
        if not data or not data.get('public_token'):
            return jsonify({
                'success': False,
                'error': 'public_token is required'
            }), 400

        public_token = data['public_token']
        institution_id = data.get('institution_id')
        force = data.get('force', False)

        # Check for duplicate connection (prevents costly reconnects)
        if not force and institution_id:
            existing_items = plaid.get_items(user_id=user_id)
            existing_connection = next(
                (i for i in existing_items if i.institution_id == institution_id and i.status.value == 'active'),
                None
            )
            if existing_connection:
                logger.warning(
                    f"Duplicate connection attempt: user={user_id} already has {institution_id} "
                    f"(item={existing_connection.item_id})"
                )
                return jsonify({
                    'success': False,
                    'error': 'You already have this bank connected.',
                    'error_code': 'DUPLICATE_CONNECTION',
                    'existing_item': existing_connection.to_dict(include_token=False),
                    'message': f'{existing_connection.institution_name} is already connected. '
                              f'Use the existing connection or remove it first to reconnect.'
                }), 409  # Conflict

        # Exchange token
        item = plaid.exchange_public_token(
            public_token=public_token,
            user_id=user_id
        )

        # Get accounts for response
        accounts = plaid.get_accounts(item.item_id)

        logger.info(f"New Plaid connection: user={user_id}, institution={item.institution_name}, item={item.item_id}")

        # Invalidate cache after adding new connection
        _invalidate_cache(user_id)

        return jsonify({
            'success': True,
            'item': item.to_dict(include_token=False),  # Never expose access token
            'accounts': [a.to_dict() for a in accounts],
            'message': f'Successfully linked {item.institution_name}'
        })

    except Exception as e:
        logger.error(f"Token exchange error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# ITEM MANAGEMENT ENDPOINTS
# =============================================================================

@plaid_bp.route('/items', methods=['GET'])
@require_auth
def list_items():
    """
    List all linked Plaid Items for the current user.

    Response:
        {
            "success": true,
            "items": [
                {
                    "item_id": "xxx",
                    "institution_name": "Chase",
                    "status": "active",
                    "last_successful_sync": "2025-12-20T12:00:00Z",
                    "account_count": 3
                }
            ]
        }
    """
    try:
        plaid = get_plaid()

        items = plaid.get_items(user_id=get_user_id())

        # Enrich with account counts
        items_data = []
        for item in items:
            item_dict = item.to_dict(include_token=False)
            accounts = plaid.get_accounts(item.item_id)
            item_dict['account_count'] = len(accounts)
            items_data.append(item_dict)

        return jsonify({
            'success': True,
            'items': items_data
        })

    except Exception as e:
        logger.error(f"List items error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/items/<item_id>', methods=['GET'])
@require_auth
def get_item(item_id):
    """
    Get details for a specific Plaid Item.

    Response:
        {
            "success": true,
            "item": {...},
            "accounts": [...],
            "sync_stats": {...}
        }
    """
    try:
        plaid = get_plaid()

        # Get item (verifies ownership through user_id)
        items = plaid.get_items(user_id=get_user_id())
        item = next((i for i in items if i.item_id == item_id), None)

        if not item:
            return jsonify({
                'success': False,
                'error': 'Item not found'
            }), 404

        # Get accounts
        accounts = plaid.get_accounts(item_id)

        # Get sync stats from database
        from db_mysql import get_mysql_db
        db = get_mysql_db()
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total_syncs,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_syncs,
                    SUM(transactions_added) as total_added,
                    MAX(completed_at) as last_sync
                FROM plaid_sync_history
                WHERE item_id = %s
            """, (item_id,))
            row = cursor.fetchone()
            sync_stats = {
                'total_syncs': row['total_syncs'] or 0,
                'successful_syncs': row['successful_syncs'] or 0,
                'total_transactions_added': row['total_added'] or 0,
                'last_sync': row['last_sync'].isoformat() if row['last_sync'] else None
            }
        finally:
            db.return_connection(conn)

        return jsonify({
            'success': True,
            'item': item.to_dict(include_token=False),
            'accounts': [a.to_dict() for a in accounts],
            'sync_stats': sync_stats
        })

    except Exception as e:
        logger.error(f"Get item error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/items/<item_id>', methods=['DELETE'])
@require_auth
def remove_item(item_id):
    """
    Remove a linked Plaid Item (disconnect bank connection).

    This revokes access with Plaid but does NOT delete synced transactions.

    Response:
        {
            "success": true,
            "message": "Item removed successfully"
        }
    """
    try:
        plaid = get_plaid()

        # Verify ownership
        items = plaid.get_items(user_id=get_user_id())
        item = next((i for i in items if i.item_id == item_id), None)

        if not item:
            return jsonify({
                'success': False,
                'error': 'Item not found'
            }), 404

        plaid.remove_item(item_id)

        # Invalidate cache after removing connection
        _invalidate_cache(get_user_id())

        return jsonify({
            'success': True,
            'message': 'Bank connection removed successfully'
        })

    except Exception as e:
        logger.error(f"Remove item error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# ACCOUNT MANAGEMENT ENDPOINTS
# =============================================================================

@plaid_bp.route('/accounts', methods=['GET'])
@require_auth
def list_accounts():
    """
    List all accounts across all linked Items.

    Query Parameters:
        item_id: Filter by Item ID

    Response:
        {
            "success": true,
            "accounts": [...]
        }
    """
    try:
        plaid = get_plaid()

        item_id = request.args.get('item_id')

        # If item_id specified, verify ownership
        if item_id:
            items = plaid.get_items(user_id=get_user_id())
            if not any(i.item_id == item_id for i in items):
                return jsonify({
                    'success': False,
                    'error': 'Item not found'
                }), 404

        accounts = plaid.get_accounts(item_id)

        return jsonify({
            'success': True,
            'accounts': [a.to_dict() for a in accounts]
        })

    except Exception as e:
        logger.error(f"List accounts error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/accounts/<account_id>', methods=['PUT'])
@require_auth
def update_account(account_id):
    """
    Update account settings.

    Request Body:
        {
            "sync_enabled": true,
            "default_business_type": "Business",
            "display_name": "My Checking"
        }

    Response:
        {
            "success": true,
            "account": {...}
        }
    """
    try:
        data = request.get_json() or {}

        from db_mysql import get_mysql_db
        db = get_mysql_db()
        conn = db.get_connection()
        try:
            cursor = conn.cursor()

            # Build update query
            updates = []
            params = []

            if 'sync_enabled' in data:
                updates.append("sync_enabled = %s")
                params.append(data['sync_enabled'])

            if 'default_business_type' in data:
                updates.append("default_business_type = %s")
                params.append(data['default_business_type'])

            if 'display_name' in data:
                updates.append("display_name = %s")
                params.append(data['display_name'])

            if not updates:
                return jsonify({
                    'success': False,
                    'error': 'No updates provided'
                }), 400

            updates.append("updated_at = NOW()")
            params.append(account_id)

            cursor.execute(f"""
                UPDATE plaid_accounts
                SET {', '.join(updates)}
                WHERE account_id = %s
            """, params)
            conn.commit()

            # Get updated account
            cursor.execute("""
                SELECT account_id, item_id, name, official_name, mask, type, subtype,
                       balance_available, balance_current, balance_limit, balance_currency,
                       sync_enabled, default_business_type, display_name
                FROM plaid_accounts
                WHERE account_id = %s
            """, (account_id,))
            row = cursor.fetchone()

            if not row:
                return jsonify({
                    'success': False,
                    'error': 'Account not found'
                }), 404

            return jsonify({
                'success': True,
                'account': dict(row)
            })

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Update account error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# TRANSACTION ENDPOINTS
# =============================================================================

@plaid_bp.route('/transactions', methods=['GET'])
@require_auth
def list_transactions():
    """
    List synced transactions.

    Query Parameters:
        account_id: Filter by account
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        pending: Filter by pending status (true/false)
        status: Processing status filter
        limit: Max results (default 100)
        offset: Pagination offset

    Response:
        {
            "success": true,
            "transactions": [...],
            "total": 1234,
            "limit": 100,
            "offset": 0
        }
    """
    try:
        plaid = get_plaid()

        account_id = request.args.get('account_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        pending = request.args.get('pending')
        if pending is not None:
            pending = pending.lower() == 'true'
        status = request.args.get('status')
        limit = min(int(request.args.get('limit', 100)), 500)
        offset = int(request.args.get('offset', 0))

        transactions = plaid.get_transactions(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            pending=pending,
            processing_status=status,
            limit=limit,
            offset=offset,
            user_id=get_user_id()  # Multi-tenant data isolation
        )

        # Get total count (with user scoping)
        from db_mysql import get_mysql_db
        db = get_mysql_db()
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            # Join with items to filter by user_id
            query = """
                SELECT COUNT(*) as total
                FROM plaid_transactions pt
                JOIN plaid_accounts pa ON pt.account_id = pa.account_id
                JOIN plaid_items pi ON pa.item_id = pi.item_id
                WHERE pi.user_id = %s
            """
            params = [get_user_id()]

            if account_id:
                query += " AND pt.account_id = %s"
                params.append(account_id)
            if start_date:
                query += " AND pt.date >= %s"
                params.append(start_date)
            if end_date:
                query += " AND pt.date <= %s"
                params.append(end_date)
            if pending is not None:
                query += " AND pt.pending = %s"
                params.append(pending)
            if status:
                query += " AND pt.processing_status = %s"
                params.append(status)

            cursor.execute(query, params)
            total = cursor.fetchone()['total']
        finally:
            db.return_connection(conn)

        return jsonify({
            'success': True,
            'transactions': transactions,
            'total': total,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        logger.error(f"List transactions error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/transactions/summary', methods=['GET'])
@require_auth
def transactions_summary():
    """
    Get transaction summary statistics.

    Response:
        {
            "success": true,
            "summary": {
                "total_transactions": 1234,
                "matched": 1100,
                "unmatched": 134,
                "total_spending": -5000.00,
                "total_income": 1000.00
            }
        }
    """
    try:
        plaid = get_plaid()

        summary = plaid.get_transactions_summary(user_id=get_user_id())

        return jsonify({
            'success': True,
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Transaction summary error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# SYNC ENDPOINTS
# =============================================================================

@plaid_bp.route('/sync', methods=['POST'])
@require_auth
def trigger_sync():
    """
    Trigger a manual transaction sync.

    RATE LIMITED: Only 1 sync per 24 hours per Item to control Plaid API costs.
    Use force=true to override (not recommended).

    Request Body:
        {
            "item_id": "xxx",  // Optional - sync specific Item, or all if omitted
            "force": false     // Optional - bypass rate limit (use sparingly!)
        }

    Response:
        {
            "success": true,
            "results": [
                {
                    "item_id": "xxx",
                    "added": 5,
                    "modified": 2,
                    "removed": 0
                }
            ],
            "rate_limited": [...]  // Items that were skipped due to rate limit
        }
    """
    try:
        plaid = get_plaid()

        data = request.get_json() or {}
        item_id = data.get('item_id')
        force = data.get('force', False)

        results = []
        rate_limited = []

        if item_id:
            # Sync specific Item
            items = plaid.get_items(user_id=get_user_id())
            item = next((i for i in items if i.item_id == item_id), None)

            if not item:
                return jsonify({
                    'success': False,
                    'error': 'Item not found'
                }), 404

            # Check rate limit (unless forced)
            rate_check = _check_sync_rate_limit(item)
            if not force and not rate_check['allowed']:
                return jsonify({
                    'success': False,
                    'error': 'Sync rate limited to once per 24 hours to control costs.',
                    'error_code': 'RATE_LIMITED',
                    'rate_limit': rate_check,
                    'message': f"Last sync was {rate_check['hours_since']} hours ago. "
                              f"Next sync allowed in {rate_check['hours_until_next']} hours. "
                              f"Use force=true to override (not recommended)."
                }), 429  # Too Many Requests

            result = plaid.sync_transactions(item_id, sync_type='manual')
            results.append(result.to_dict())

        else:
            # Sync all Items (with rate limiting)
            items = plaid.get_items(user_id=get_user_id())
            for item in items:
                if item.status.value == 'active':
                    # Check rate limit for each item
                    rate_check = _check_sync_rate_limit(item)

                    if not force and not rate_check['allowed']:
                        rate_limited.append({
                            'item_id': item.item_id,
                            'institution_name': item.institution_name,
                            'reason': 'Rate limited (1 sync per 24 hours)',
                            'last_sync': rate_check['last_sync'],
                            'hours_until_next': rate_check['hours_until_next'],
                            'next_sync_allowed': rate_check['next_sync_allowed']
                        })
                        continue

                    try:
                        result = plaid.sync_transactions(item.item_id, sync_type='manual')
                        results.append(result.to_dict())
                    except Exception as e:
                        logger.error(f"Sync failed for {item.item_id}: {e}")
                        results.append({
                            'item_id': item.item_id,
                            'success': False,
                            'error': str(e)
                        })

        # Auto-import any new transactions to main table
        import_result = None
        total_added = sum(r.get('added', 0) for r in results if isinstance(r, dict))
        if total_added > 0:
            try:
                import_result = plaid.import_to_transactions(user_id=get_user_id())
                logger.info(f"Auto-imported {import_result.get('imported', 0)} transactions after manual sync")
            except Exception as e:
                logger.warning(f"Auto-import failed: {e}")

        response = {
            'success': True,
            'results': results,
            'import': import_result
        }

        if rate_limited:
            response['rate_limited'] = rate_limited
            response['message'] = f"{len(rate_limited)} item(s) skipped due to daily sync limit. " \
                                 f"Synced {len(results)} item(s)."

        return jsonify(response)

    except Exception as e:
        logger.error(f"Sync error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/sync/status', methods=['GET'])
@require_auth
def sync_status():
    """
    Get the sync status for all Items, including rate limit info.

    Response:
        {
            "success": true,
            "rate_limit_hours": 24,
            "items": [
                {
                    "item_id": "xxx",
                    "institution_name": "Chase",
                    "status": "active",
                    "last_sync": "2025-12-20T12:00:00Z",
                    "needs_reauth": false,
                    "sync_allowed": true,
                    "hours_until_sync": 0,
                    "next_sync_allowed": null
                }
            ]
        }
    """
    try:
        plaid = get_plaid()

        items = plaid.get_items(user_id=get_user_id())

        items_status = []
        for item in items:
            rate_check = _check_sync_rate_limit(item)
            items_status.append({
                'item_id': item.item_id,
                'institution_name': item.institution_name,
                'status': item.status.value,
                'last_sync': item.last_successful_sync.isoformat() if item.last_successful_sync else None,
                'needs_reauth': item.status.value == 'needs_reauth',
                'sync_allowed': rate_check['allowed'],
                'hours_until_sync': rate_check.get('hours_until_next', 0),
                'next_sync_allowed': rate_check.get('next_sync_allowed')
            })

        return jsonify({
            'success': True,
            'rate_limit_hours': _SYNC_RATE_LIMIT_HOURS,
            'items': items_status
        })

    except Exception as e:
        logger.error(f"Sync status error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# WEBHOOK ENDPOINT
# =============================================================================

@plaid_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    Receive Plaid webhooks.

    This endpoint is called by Plaid when events occur:
    - New transactions available
    - Item errors (needs re-auth)
    - Historical transactions ready

    The endpoint does NOT require authentication but verifies
    the webhook signature.

    Response:
        {
            "success": true
        }
    """
    try:
        plaid = get_plaid()

        # Get raw body for signature verification
        body = request.get_data()
        signature = request.headers.get('Plaid-Verification')

        # Verify webhook signature (required in production)
        is_production = os.environ.get('PLAID_ENV') == 'production'
        if is_production:
            if not signature:
                logger.warning("Missing webhook signature in production")
                return jsonify({'success': False, 'error': 'Missing signature'}), 401

            if not plaid.verify_webhook_signature(body, signature):
                logger.warning("Invalid webhook signature")
                return jsonify({'success': False, 'error': 'Invalid signature'}), 401
        elif signature:
            # In non-production, verify if signature is provided
            if not plaid.verify_webhook_signature(body, signature):
                logger.warning("Invalid webhook signature (non-production)")

        # Parse webhook
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid payload'}), 400

        webhook_type = data.get('webhook_type')
        webhook_code = data.get('webhook_code')
        webhook_id = request.headers.get('Plaid-Webhook-ID')

        logger.info(f"Received webhook: {webhook_type}.{webhook_code}")

        # Process webhook
        result = plaid.handle_webhook(
            webhook_type=webhook_type,
            webhook_code=webhook_code,
            payload=data,
            webhook_id=webhook_id
        )

        return jsonify({
            'success': True,
            'result': result
        })

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        # Always return 200 to Plaid to prevent retries
        return jsonify({
            'success': False,
            'error': str(e)
        }), 200


# =============================================================================
# CONFIGURATION CHECK
# =============================================================================

@plaid_bp.route('/status', methods=['GET'])
@require_auth
def plaid_status():
    """
    Check Plaid integration status and configuration.

    Response:
        {
            "success": true,
            "configured": true,
            "environment": "development",
            "sdk_available": true,
            "items_count": 2,
            "accounts_count": 5,
            "transactions_count": 1234
        }
    """
    try:
        from services.plaid_service import is_plaid_configured, is_plaid_available, PlaidConfig

        config = PlaidConfig()
        configured = is_plaid_configured()
        sdk_available = is_plaid_available()

        result = {
            'success': True,
            'configured': configured,
            'environment': config.environment,
            'sdk_available': sdk_available
        }

        if configured and sdk_available:
            plaid = get_plaid()

            items = plaid.get_items(user_id=get_user_id())
            result['items_count'] = len(items)

            accounts = plaid.get_accounts()
            result['accounts_count'] = len(accounts)

            summary = plaid.get_transactions_summary(user_id=get_user_id())
            result['transactions_count'] = summary['total_transactions']

        return jsonify(result)

    except Exception as e:
        logger.error(f"Status check error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# TRANSACTION-RECEIPT MATCHING (NEW)
# =============================================================================

@plaid_bp.route('/transactions/match', methods=['POST'])
@require_auth
def match_transactions_to_receipts():
    """
    Match transactions to receipts in the database.

    Request Body:
        {
            "transaction_ids": ["txn_123", ...],  // Optional: specific transactions
            "date_range": {"start": "2024-01-01", "end": "2024-12-31"},  // Optional
            "auto_link": true  // Whether to automatically link matches
        }

    Response:
        {
            "success": true,
            "matches": [
                {
                    "transaction_id": "txn_123",
                    "receipt_id": "rec_456",
                    "confidence": 0.95,
                    "match_type": "exact_amount_date"
                }
            ],
            "unmatched": 5,
            "auto_linked": 10
        }
    """
    try:
        data = request.get_json() or {}
        transaction_ids = data.get('transaction_ids')
        date_range = data.get('date_range', {})
        auto_link = data.get('auto_link', False)

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        # Get transactions to match
        with db._pool.connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT pt.transaction_id, pt.amount, pt.date, pt.merchant_name, pt.account_id
                FROM plaid_transactions pt
                WHERE pt.user_id = %s
                AND pt.receipt_id IS NULL
            """
            params = [get_user_id()]

            if transaction_ids:
                placeholders = ','.join(['%s'] * len(transaction_ids))
                query += f" AND pt.transaction_id IN ({placeholders})"
                params.extend(transaction_ids)

            if date_range.get('start'):
                query += " AND pt.date >= %s"
                params.append(date_range['start'])
            if date_range.get('end'):
                query += " AND pt.date <= %s"
                params.append(date_range['end'])

            cursor.execute(query, params)
            transactions = cursor.fetchall()

            matches = []
            unmatched = 0
            auto_linked = 0

            for txn in transactions:
                txn_id, amount, txn_date, merchant, account_id = txn

                # Find matching receipt by amount and date (within 3 days)
                cursor.execute("""
                    SELECT id, chase_amount, chase_date, chase_description
                    FROM transactions
                    WHERE ABS(chase_amount) = ABS(%s)
                    AND chase_date BETWEEN DATE_SUB(%s, INTERVAL 3 DAY) AND DATE_ADD(%s, INTERVAL 3 DAY)
                    AND r2_url IS NOT NULL
                    LIMIT 1
                """, (abs(amount), txn_date, txn_date))

                receipt = cursor.fetchone()

                if receipt:
                    confidence = 0.95 if receipt[2] == txn_date else 0.85
                    match_type = 'exact_amount_date' if receipt[2] == txn_date else 'amount_fuzzy_date'

                    matches.append({
                        'transaction_id': txn_id,
                        'receipt_id': receipt[0],
                        'confidence': confidence,
                        'match_type': match_type,
                        'amount': float(amount),
                        'merchant': merchant
                    })

                    if auto_link and confidence >= 0.85:
                        cursor.execute("""
                            UPDATE plaid_transactions SET receipt_id = %s WHERE transaction_id = %s
                        """, (receipt[0], txn_id))
                        auto_linked += 1
                else:
                    unmatched += 1

            if auto_link:
                conn.commit()

        return jsonify({
            'success': True,
            'matches': matches,
            'unmatched': unmatched,
            'auto_linked': auto_linked
        })

    except Exception as e:
        logger.error(f"Transaction matching error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@plaid_bp.route('/transactions/duplicates', methods=['GET'])
@require_auth
def detect_duplicate_transactions():
    """
    Detect potential duplicate transactions across accounts.

    Response:
        {
            "success": true,
            "duplicates": [
                {
                    "transactions": ["txn_1", "txn_2"],
                    "amount": -50.00,
                    "date": "2024-12-20",
                    "confidence": 0.90
                }
            ]
        }
    """
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Find transactions with same amount on same day across different accounts
            cursor.execute("""
                SELECT pt1.transaction_id, pt2.transaction_id,
                       pt1.amount, pt1.date, pt1.merchant_name,
                       pt1.account_id, pt2.account_id
                FROM plaid_transactions pt1
                JOIN plaid_transactions pt2 ON pt1.amount = pt2.amount
                    AND pt1.date = pt2.date
                    AND pt1.transaction_id < pt2.transaction_id
                    AND pt1.account_id != pt2.account_id
                WHERE pt1.user_id = %s
                ORDER BY pt1.date DESC
                LIMIT 100
            """, (get_user_id(),))

            duplicates = []
            for row in cursor.fetchall():
                duplicates.append({
                    'transactions': [row[0], row[1]],
                    'amount': float(row[2]),
                    'date': str(row[3]),
                    'merchant': row[4],
                    'accounts': [row[5], row[6]],
                    'confidence': 0.90
                })

        return jsonify({
            'success': True,
            'duplicates': duplicates,
            'count': len(duplicates)
        })

    except Exception as e:
        logger.error(f"Duplicate detection error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@plaid_bp.route('/accounts/<account_id>/balance/history', methods=['GET'])
@require_auth
def get_balance_history(account_id):
    """
    Get balance history for an account.

    Query Params:
        days: Number of days of history (default 30)

    Response:
        {
            "success": true,
            "history": [
                {"date": "2024-12-20", "balance": 1500.00},
                ...
            ]
        }
    """
    try:
        days = int(request.args.get('days', 30))

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get daily ending balances from transaction history
            cursor.execute("""
                SELECT DATE(date) as txn_date,
                       SUM(amount) OVER (ORDER BY date, transaction_id) as running_balance
                FROM plaid_transactions
                WHERE account_id = %s
                AND date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY date DESC
            """, (account_id, days))

            history = []
            seen_dates = set()
            for row in cursor.fetchall():
                date_str = str(row[0])
                if date_str not in seen_dates:
                    history.append({
                        'date': date_str,
                        'balance': float(row[1]) if row[1] else 0
                    })
                    seen_dates.add(date_str)

        return jsonify({
            'success': True,
            'account_id': account_id,
            'history': history[:days]  # Limit to requested days
        })

    except Exception as e:
        logger.error(f"Balance history error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@plaid_bp.route('/sync/schedule', methods=['GET', 'PUT'])
@require_auth
def sync_schedule():
    """
    Get or update sync schedule configuration.

    PUT Request Body:
        {
            "frequency": "hourly|daily|manual",
            "enabled": true
        }

    Response:
        {
            "success": true,
            "schedule": {
                "frequency": "daily",
                "enabled": true,
                "last_sync": "2024-12-20T10:30:00Z",
                "next_sync": "2024-12-21T10:30:00Z"
            }
        }
    """
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        if request.method == 'PUT':
            data = request.get_json() or {}

            with db._pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO plaid_sync_config (user_id, frequency, enabled, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE frequency = VALUES(frequency),
                                            enabled = VALUES(enabled),
                                            updated_at = NOW()
                """, (get_user_id(), data.get('frequency', 'daily'), data.get('enabled', True)))

        # Get current schedule
        with db._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT frequency, enabled, last_sync, next_sync
                FROM plaid_sync_config
                WHERE user_id = %s
            """, (get_user_id(),))

            row = cursor.fetchone()
            if row:
                schedule = {
                    'frequency': row[0],
                    'enabled': bool(row[1]),
                    'last_sync': str(row[2]) if row[2] else None,
                    'next_sync': str(row[3]) if row[3] else None
                }
            else:
                schedule = {
                    'frequency': 'daily',
                    'enabled': True,
                    'last_sync': None,
                    'next_sync': None
                }

        return jsonify({
            'success': True,
            'schedule': schedule
        })

    except Exception as e:
        logger.error(f"Sync schedule error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@plaid_bp.route('/institution/<institution_id>', methods=['GET'])
@require_auth
def get_institution_details(institution_id):
    """
    Get institution details from Plaid.

    Response:
        {
            "success": true,
            "institution": {
                "name": "Chase",
                "institution_id": "ins_123",
                "products": ["transactions", "auth"],
                "logo": "base64...",
                "primary_color": "#1a73e8"
            }
        }
    """
    try:
        plaid = get_plaid()

        # Get institution from Plaid API
        from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
        from plaid.model.country_code import CountryCode

        request_data = InstitutionsGetByIdRequest(
            institution_id=institution_id,
            country_codes=[CountryCode('US')],
            options={'include_optional_metadata': True}
        )

        response = plaid.client.institutions_get_by_id(request_data)
        inst = response.institution

        return jsonify({
            'success': True,
            'institution': {
                'name': inst.name,
                'institution_id': inst.institution_id,
                'products': [str(p) for p in inst.products],
                'logo': inst.logo if hasattr(inst, 'logo') else None,
                'primary_color': inst.primary_color if hasattr(inst, 'primary_color') else None,
                'url': inst.url if hasattr(inst, 'url') else None
            }
        })

    except Exception as e:
        logger.error(f"Institution details error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# OAUTH REDIRECT HANDLER
# =============================================================================

@plaid_bp.route('/oauth', methods=['GET'])
def plaid_oauth_redirect():
    """
    Handle OAuth redirect from Plaid Link.

    When users connect to OAuth banks (Chase, BofA, Capital One, etc),
    they are redirected to the bank's site, then back through Plaid,
    then to this endpoint with an oauth_state_id.

    This page re-initializes Plaid Link to complete the connection.
    """
    oauth_state_id = request.args.get('oauth_state_id', '')

    # Return HTML page that resumes Plaid Link
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Completing Bank Connection...</title>
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
            background: #0a0f14;
            color: #fff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }}
        .container {{
            text-align: center;
            padding: 40px;
        }}
        .spinner {{
            width: 50px;
            height: 50px;
            border: 4px solid rgba(0, 255, 136, 0.2);
            border-top-color: #00ff88;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }}
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
        h2 {{ color: #00ff88; margin: 0 0 10px; }}
        p {{ color: #999; margin: 0; }}
        .error {{ color: #ff4444; display: none; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="spinner" id="spinner"></div>
        <h2>Completing Bank Connection</h2>
        <p>Please wait while we finalize your connection...</p>
        <p class="error" id="error"></p>
    </div>
    <script>
        const oauthStateId = "{oauth_state_id}";

        async function completePlaidLink() {{
            if (!oauthStateId) {{
                document.getElementById('error').textContent = 'Missing OAuth state. Please try connecting again.';
                document.getElementById('error').style.display = 'block';
                document.getElementById('spinner').style.display = 'none';
                return;
            }}

            try {{
                // Get a new link token for the OAuth flow
                const response = await fetch('/api/plaid/link-token', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    credentials: 'same-origin',
                    body: JSON.stringify({{ receivedRedirectUri: window.location.href }})
                }});

                const data = await response.json();

                if (!data.success) {{
                    throw new Error(data.error || 'Failed to get link token');
                }}

                // Create Plaid Link handler
                const handler = Plaid.create({{
                    token: data.link_token,
                    receivedRedirectUri: window.location.href,
                    onSuccess: async (publicToken, metadata) => {{
                        // Exchange token
                        const exchangeResponse = await fetch('/api/plaid/exchange-token', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            credentials: 'same-origin',
                            body: JSON.stringify({{ public_token: publicToken }})
                        }});

                        const exchangeData = await exchangeResponse.json();

                        if (exchangeData.success) {{
                            // Redirect to bank accounts page
                            window.location.href = '/bank_accounts.html?connected=1';
                        }} else {{
                            throw new Error(exchangeData.error || 'Token exchange failed');
                        }}
                    }},
                    onExit: (err, metadata) => {{
                        if (err) {{
                            document.getElementById('error').textContent = 'Connection was cancelled or failed.';
                            document.getElementById('error').style.display = 'block';
                        }}
                        document.getElementById('spinner').style.display = 'none';
                        // Redirect back after a moment
                        setTimeout(() => window.location.href = '/bank_accounts.html', 2000);
                    }},
                    onEvent: (eventName, metadata) => {{
                        console.log('Plaid event:', eventName, metadata);
                    }}
                }});

                // Open Link to complete OAuth flow
                handler.open();

            }} catch (error) {{
                console.error('OAuth completion error:', error);
                document.getElementById('error').textContent = error.message || 'An error occurred. Please try again.';
                document.getElementById('error').style.display = 'block';
                document.getElementById('spinner').style.display = 'none';
            }}
        }}

        // Start the OAuth completion
        completePlaidLink();
    </script>
</body>
</html>
'''


# =============================================================================
# DIAGNOSTIC ENDPOINTS
# =============================================================================

@plaid_bp.route('/sync/diagnose', methods=['GET'])
@require_auth
def sync_diagnose():
    """
    Get comprehensive sync diagnostics for troubleshooting.

    Returns detailed information about all linked Items including:
    - Item status and configuration
    - Account details and sync settings
    - Recent sync history with success/failure details
    - Transaction counts and date ranges
    - Detected issues and recommendations

    Response:
        {
            "success": true,
            "diagnostics": {
                "summary": {
                    "total_items": 1,
                    "active_items": 1,
                    "total_transactions": 150,
                    "total_issues": 0
                },
                "date_filter": {
                    "enabled": true,
                    "min_date": "2025-09-01",
                    "description": "..."
                },
                "items": [...]
            }
        }
    """
    try:
        plaid = get_plaid()
        diagnostics = plaid.get_sync_diagnostics(user_id=get_user_id())

        return jsonify({
            'success': True,
            'diagnostics': diagnostics
        })

    except Exception as e:
        logger.error(f"Diagnostics error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/sync/reset', methods=['POST'])
@require_auth
def sync_reset():
    """
    Reset the sync cursor to force a fresh transaction sync.

    This clears the stored cursor so the next sync will fetch all
    available transactions from Plaid (subject to date filters).
    Use this when transactions seem to be missing or stuck.

    Request Body:
        {
            "item_id": "xxx"  // Required - the Item to reset
        }

    Response:
        {
            "success": true,
            "item_id": "xxx",
            "institution": "Chase",
            "message": "Sync cursor cleared. Next sync will fetch all available transactions."
        }
    """
    try:
        plaid = get_plaid()

        data = request.get_json() or {}
        item_id = data.get('item_id')

        if not item_id:
            return jsonify({
                'success': False,
                'error': 'item_id is required'
            }), 400

        # Verify ownership
        items = plaid.get_items(user_id=get_user_id())
        if not any(i.item_id == item_id for i in items):
            return jsonify({
                'success': False,
                'error': 'Item not found'
            }), 404

        result = plaid.reset_sync_cursor(item_id)

        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Reset sync error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/sync/import', methods=['GET', 'POST'])
@require_auth
def sync_import():
    """
    Import transactions from plaid_transactions staging table to main transactions table.

    This moves synced Plaid transactions into the main transactions table
    so they appear in the viewer and can be matched with receipts.

    Response:
        {
            "success": true,
            "imported": 150,
            "skipped": 2,
            "message": "Imported 150 transactions to viewer"
        }
    """
    try:
        plaid = get_plaid()
        result = plaid.import_to_transactions(user_id=get_user_id())

        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Import error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/sync/force-import', methods=['GET', 'POST'])
@require_auth
def sync_force_import():
    """
    Reset import status and re-import all transactions.

    This resets the processing_status of 'matched' transactions back to 'new'
    and then runs the import again. Use this if transactions were marked as
    imported but didn't actually appear in the viewer.

    Response:
        {
            "success": true,
            "reset": {"reset": 704, "message": "..."},
            "import": {"imported": 704, "skipped": 0, "message": "..."}
        }
    """
    try:
        plaid = get_plaid()
        user_id = get_user_id()

        # First reset
        reset_result = plaid.reset_import_status(user_id=user_id)

        # Then import
        import_result = plaid.import_to_transactions(user_id=user_id)

        return jsonify({
            'success': True,
            'reset': reset_result,
            'import': import_result
        })

    except Exception as e:
        logger.error(f"Force import error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/sync/refresh', methods=['POST'])
@require_auth
def sync_refresh():
    """
    Reset cursor and immediately trigger a fresh sync.

    This is a convenience endpoint that combines reset + sync.
    Use when you want to re-fetch all transactions for an Item.

    RATE LIMITED: Only 1 sync per 24 hours. Use force=true to override.

    Request Body:
        {
            "item_id": "xxx",  // Required - the Item to refresh
            "force": false     // Optional - bypass rate limit
        }

    Response:
        {
            "success": true,
            "reset": {...},
            "sync": {...}
        }
    """
    try:
        plaid = get_plaid()

        data = request.get_json() or {}
        item_id = data.get('item_id')
        force = data.get('force', False)

        if not item_id:
            return jsonify({
                'success': False,
                'error': 'item_id is required'
            }), 400

        # Verify ownership and get item
        items = plaid.get_items(user_id=get_user_id())
        item = next((i for i in items if i.item_id == item_id), None)

        if not item:
            return jsonify({
                'success': False,
                'error': 'Item not found'
            }), 404

        # Check rate limit (unless forced)
        rate_check = _check_sync_rate_limit(item)
        if not force and not rate_check['allowed']:
            return jsonify({
                'success': False,
                'error': 'Sync rate limited to once per 24 hours to control costs.',
                'error_code': 'RATE_LIMITED',
                'rate_limit': rate_check,
                'message': f"Last sync was {rate_check['hours_since']} hours ago. "
                          f"Next sync allowed in {rate_check['hours_until_next']} hours."
            }), 429

        # Reset cursor
        reset_result = plaid.reset_sync_cursor(item_id)
        if not reset_result['success']:
            return jsonify({
                'success': False,
                'error': reset_result.get('error', 'Reset failed')
            }), 400

        # Trigger sync
        sync_result = plaid.sync_transactions(item_id, sync_type='manual')

        return jsonify({
            'success': True,
            'reset': reset_result,
            'sync': sync_result.to_dict()
        })

    except Exception as e:
        logger.error(f"Refresh sync error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@plaid_bp.route('/transactions/by-source', methods=['GET'])
@require_auth
def transactions_by_source():
    """
    Get transaction summary grouped by source account.

    Useful for:
    - Seeing which cards have the most transactions
    - Finding transactions without receipts by card
    - Receipt matching rules per card

    Response:
        {
            "success": true,
            "sources": [
                {
                    "institution": "Regions Bank",
                    "account_name": "Checking",
                    "account_mask": "1234",
                    "display": "Regions Bank - Checking (...1234)",
                    "transaction_count": 150,
                    "total_amount": -4523.45,
                    "with_receipt": 45,
                    "without_receipt": 105,
                    "date_range": {"earliest": "2025-09-23", "latest": "2025-12-22"}
                }
            ]
        }
    """
    try:
        plaid = get_plaid()
        db = plaid._get_db()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    source_institution,
                    source_account_name,
                    source_account_mask,
                    COUNT(*) AS transaction_count,
                    COALESCE(SUM(chase_amount), 0) AS total_amount,
                    MIN(chase_date) AS earliest_date,
                    MAX(chase_date) AS latest_date,
                    SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' THEN 1 ELSE 0 END) AS with_receipt,
                    SUM(CASE WHEN r2_url IS NULL OR r2_url = '' THEN 1 ELSE 0 END) AS without_receipt
                FROM transactions
                WHERE source_institution IS NOT NULL
                AND (deleted IS NULL OR deleted = 0)
                GROUP BY source_institution, source_account_name, source_account_mask
                ORDER BY transaction_count DESC
            """)

            sources = []
            for row in cursor.fetchall():
                # Build display string
                display = row['source_institution']
                if row['source_account_name']:
                    display += f" - {row['source_account_name']}"
                if row['source_account_mask']:
                    display += f" (...{row['source_account_mask']})"

                sources.append({
                    'institution': row['source_institution'],
                    'account_name': row['source_account_name'],
                    'account_mask': row['source_account_mask'],
                    'display': display,
                    'transaction_count': row['transaction_count'],
                    'total_amount': float(row['total_amount']),
                    'with_receipt': row['with_receipt'],
                    'without_receipt': row['without_receipt'],
                    'date_range': {
                        'earliest': row['earliest_date'].isoformat() if row['earliest_date'] else None,
                        'latest': row['latest_date'].isoformat() if row['latest_date'] else None
                    }
                })

            return jsonify({
                'success': True,
                'sources': sources
            })

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Transactions by source error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# REGISTER BLUEPRINT FUNCTION
# =============================================================================

def register_plaid_routes(app):
    """
    Register Plaid routes with the Flask app.

    Call this from viewer_server.py:
        from services.plaid_routes import register_plaid_routes
        register_plaid_routes(app)

    Args:
        app: Flask application instance
    """
    app.register_blueprint(plaid_bp)
    logger.info("Plaid routes registered at /api/plaid/*")
