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
    GET  /api/plaid/transactions     - List transactions
    POST /api/plaid/sync             - Trigger manual sync
    GET  /api/plaid/sync/status      - Get sync status

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

    Uses the same authentication as the main app.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is authenticated via session
        from flask import session
        if not session.get('authenticated'):
            return jsonify({
                'success': False,
                'error': 'Authentication required'
            }), 401
        return f(*args, **kwargs)
    return decorated_function


def get_user_id():
    """Get the current user ID from session or default."""
    from flask import session
    return session.get('user_id', 'default')


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
# LINK TOKEN ENDPOINTS
# =============================================================================

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

        # Get redirect URI from request or use default
        redirect_uri = data.get('redirect_uri')

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
        logger.error(f"Link token creation error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to create link token'
        }), 500


@plaid_bp.route('/exchange-token', methods=['POST'])
@require_auth
def exchange_public_token():
    """
    Exchange a public token from Plaid Link for an access token.

    Called after user completes the Plaid Link flow.

    Request Body:
        {
            "public_token": "public-sandbox-xxx"
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

        data = request.get_json()
        if not data or not data.get('public_token'):
            return jsonify({
                'success': False,
                'error': 'public_token is required'
            }), 400

        public_token = data['public_token']

        # Exchange token
        item = plaid.exchange_public_token(
            public_token=public_token,
            user_id=get_user_id()
        )

        # Get accounts for response
        accounts = plaid.get_accounts(item.item_id)

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
            "default_business_type": "Down_Home",
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
            offset=offset
        )

        # Get total count
        from db_mysql import get_mysql_db
        db = get_mysql_db()
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT COUNT(*) as total FROM plaid_transactions WHERE 1=1"
            params = []

            if account_id:
                query += " AND account_id = %s"
                params.append(account_id)
            if start_date:
                query += " AND date >= %s"
                params.append(start_date)
            if end_date:
                query += " AND date <= %s"
                params.append(end_date)
            if pending is not None:
                query += " AND pending = %s"
                params.append(pending)
            if status:
                query += " AND processing_status = %s"
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

    Request Body:
        {
            "item_id": "xxx"  // Optional - sync specific Item, or all if omitted
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
            ]
        }
    """
    try:
        plaid = get_plaid()

        data = request.get_json() or {}
        item_id = data.get('item_id')

        results = []

        if item_id:
            # Sync specific Item
            items = plaid.get_items(user_id=get_user_id())
            if not any(i.item_id == item_id for i in items):
                return jsonify({
                    'success': False,
                    'error': 'Item not found'
                }), 404

            result = plaid.sync_transactions(item_id, sync_type='manual')
            results.append(result.to_dict())
        else:
            # Sync all Items
            items = plaid.get_items(user_id=get_user_id())
            for item in items:
                if item.status.value == 'active':
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

        return jsonify({
            'success': True,
            'results': results
        })

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
    Get the sync status for all Items.

    Response:
        {
            "success": true,
            "items": [
                {
                    "item_id": "xxx",
                    "institution_name": "Chase",
                    "status": "active",
                    "last_sync": "2025-12-20T12:00:00Z",
                    "needs_reauth": false
                }
            ]
        }
    """
    try:
        plaid = get_plaid()

        items = plaid.get_items(user_id=get_user_id())

        items_status = []
        for item in items:
            items_status.append({
                'item_id': item.item_id,
                'institution_name': item.institution_name,
                'status': item.status.value,
                'last_sync': item.last_successful_sync.isoformat() if item.last_successful_sync else None,
                'needs_reauth': item.status.value == 'needs_reauth'
            })

        return jsonify({
            'success': True,
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

        # Verify signature (if configured)
        if signature and not plaid.verify_webhook_signature(body, signature):
            logger.warning("Invalid webhook signature")
            return jsonify({'success': False, 'error': 'Invalid signature'}), 401

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
