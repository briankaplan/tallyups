"""
================================================================================
Incoming Receipts API Blueprint
================================================================================
Gmail inbox monitoring, receipt processing, and intelligent auto-matching.

ENDPOINTS:
----------
Receipt Queue:
    GET  /api/incoming/receipts       - List all incoming receipts
    GET  /api/incoming/receipts/<id>  - Get single receipt details
    POST /api/incoming/accept         - Accept and link to transaction
    POST /api/incoming/reject         - Reject/archive receipt
    POST /api/incoming/archive        - Archive receipt
    DELETE /api/incoming/receipts/<id> - Delete receipt

Gmail Integration:
    POST /api/incoming/scan           - Trigger Gmail scan for new receipts
    GET  /api/incoming/scan-status    - Check scan status
    POST /api/incoming/cleanup        - Clean up old/duplicate receipts

Statistics:
    GET  /api/incoming/stats          - Get inbox statistics
    GET  /api/incoming/pending-count  - Get pending receipt count

Matching:
    POST /api/incoming/auto-match     - Run auto-matching algorithm
    GET  /api/incoming/match-suggestions/<id> - Get match suggestions

WORKFLOW:
---------
1. Gmail receipts are scanned and stored in incoming_receipts table
2. OCR extracts merchant, amount, and date from receipt images
3. Auto-matching attempts to link receipts to bank transactions
4. Unmatched receipts appear in the inbox for manual review
5. Users can accept (link), reject (archive), or delete receipts

RECEIPT STATUSES:
-----------------
- pending: New receipt awaiting review
- matched: Linked to a transaction
- rejected: Marked as not needed
- duplicate: Detected as duplicate
- processing: Currently being processed

SECURITY:
---------
- All endpoints require authentication
- User scoping ensures users only see their own receipts
- Gmail OAuth tokens stored securely in user_credentials table

================================================================================
"""

import os
import re
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session

from logging_config import get_logger

logger = get_logger("routes.incoming")

# Create blueprint
incoming_bp = Blueprint('incoming', __name__, url_prefix='/api/incoming')

# Import user scoping helpers
try:
    from db_user_scope import get_current_user_id, ADMIN_USER_ID, USER_SCOPING_ENABLED
except ImportError:
    ADMIN_USER_ID = '00000000-0000-0000-0000-000000000001'
    USER_SCOPING_ENABLED = False
    def get_current_user_id():
        return ADMIN_USER_ID


def get_dependencies():
    """
    Lazy import dependencies to avoid circular imports.
    """
    from viewer_server import (
        USE_DATABASE,
        db,
        get_db_connection,
        return_db_connection,
        db_execute,
        is_authenticated,
    )
    return USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, is_authenticated


def check_auth():
    """
    Check if request is authenticated.
    Supports JWT tokens (preferred), session auth, and admin_key.
    Also sets g.user_id, g.user_role if authenticated via JWT.
    """
    import secrets
    from flask import g

    # Try JWT auth first
    try:
        from auth import JWT_AVAILABLE
        if JWT_AVAILABLE:
            from services.jwt_auth_service import get_current_user_from_request
            user = get_current_user_from_request()
            if user:
                g.user_id = user['user_id']
                g.user_role = user['role']
                g.auth_method = user['auth_method']
                return True
    except ImportError:
        pass

    # Check admin API key
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key and expected_key and secrets.compare_digest(str(admin_key), str(expected_key)):
        return True

    # Check session auth
    if session.get('authenticated'):
        return True

    return False


def extract_merchant_from_subject(subject):
    """
    Extract merchant name from email subject lines using pattern matching.

    This function uses a prioritized list of regex patterns to identify
    merchant names from various common email receipt formats.

    Args:
        subject (str): The email subject line to parse

    Returns:
        str or None: Extracted merchant name (2-50 chars), or None if not found

    Patterns Recognized:
        - "Your [Merchant] invoice/receipt"
        - "Invoice from [Merchant]"
        - "Receipt from [Merchant]"
        - "Payment from [Merchant]"
        - "Your order from [Merchant]"
        - "[Merchant] Payment Confirmation"
        - Amazon order indicators

    Examples:
        >>> extract_merchant_from_subject("Your Spotify invoice")
        'Spotify'
        >>> extract_merchant_from_subject("Receipt from Apple Inc.")
        'Apple'
        >>> extract_merchant_from_subject("Shipped: Your Amazon.com order")
        'Amazon'
    """
    if not subject:
        return None

    subject = subject.strip()

    # Known merchant patterns in order of specificity
    patterns = [
        (r'^Your\s+([A-Z][A-Za-z0-9\.\s]+?)\s+(?:invoice|receipt|order|payment|subscription)', 1),
        (r'Invoice\s+from\s+([^(\[\n#]+?)(?:\s*[\(\[#]|$)', 1),
        (r'[Pp]ayment\s+(?:request\s+)?from\s+([^(\[\n#-]+?)(?:\s*[\(\[#-]|$)', 1),
        (r'[Rr]eceipt\s+from\s+([^(\[\n#]+?)(?:\s*[\(\[#]|$)', 1),
        (r'[Yy]our\s+order\s+(?:from|with)\s+([^(\[\n#]+?)(?:\s*[\(\[#]|$)', 1),
        (r'^([A-Z][A-Za-z0-9\s]+?)\s+(?:Payment|Receipt)\s*[-–]?\s*(?:Confirmation|Receipt)?', 1),
        (r'[Tt]hank\s+[Yy]ou\s+for\s+[Yy]our\s+[Oo]rder\s+with\s+([A-Za-z0-9\s]+)', 1),
        (r'^(?:Shipped|Ordered|Delivered):\s+"', None),  # Amazon indicator
        (r'[Yy]our\s+(Amazon\.?com?)\s+order', 1),
    ]

    for pattern, group in patterns:
        if group is None:
            if re.match(pattern, subject):
                return "Amazon"
            continue
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            merchant = match.group(group).strip()
            merchant = re.sub(r',?\s*(Inc\.?|LLC|Ltd\.?|PBC|Co\.?)$', '', merchant, flags=re.IGNORECASE).strip()
            merchant = re.sub(r'\s+', ' ', merchant)
            if 2 < len(merchant) < 50:
                return merchant

    return None


@incoming_bp.route("/receipts", methods=["GET"])
def get_incoming_receipts():
    """
    Get all incoming receipts from Gmail.

    Query params:
    - status: 'pending', 'accepted', 'rejected', or 'all' (default: 'all')
    - limit: max number of results (default: 500)
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        status = request.args.get('status', 'all')
        limit = int(request.args.get('limit', 500))

        conn, db_type = get_db_connection()

        # USER SCOPING: Filter by current user's receipts (if enabled)
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            if status == 'all':
                query = 'SELECT * FROM incoming_receipts WHERE user_id = %s ORDER BY received_date DESC LIMIT %s'
                cursor = db_execute(conn, db_type, query, (user_id, limit))
            else:
                query = 'SELECT * FROM incoming_receipts WHERE user_id = %s AND status = %s ORDER BY received_date DESC LIMIT %s'
                cursor = db_execute(conn, db_type, query, (user_id, status, limit))
        else:
            # No user scoping - return all receipts
            if status == 'all':
                query = 'SELECT * FROM incoming_receipts ORDER BY received_date DESC LIMIT %s'
                cursor = db_execute(conn, db_type, query, (limit,))
            else:
                query = 'SELECT * FROM incoming_receipts WHERE status = %s ORDER BY received_date DESC LIMIT %s'
                cursor = db_execute(conn, db_type, query, (status, limit))

        receipts = [dict(row) for row in cursor.fetchall()]

        # Get counts by status
        if USER_SCOPING_ENABLED:
            cursor = db_execute(conn, db_type, 'SELECT status, COUNT(*) as count FROM incoming_receipts WHERE user_id = %s GROUP BY status', (user_id,))
        else:
            cursor = db_execute(conn, db_type, 'SELECT status, COUNT(*) as count FROM incoming_receipts GROUP BY status', ())
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        return_db_connection(conn)

        # Enhance receipts with extracted merchant names
        for receipt in receipts:
            if not receipt.get('merchant') and receipt.get('subject'):
                extracted = extract_merchant_from_subject(receipt['subject'])
                if extracted:
                    receipt['merchant'] = extracted

            # Serialize dates
            for date_field in ['received_date', 'receipt_date', 'created_at', 'processed_at', 'reviewed_at']:
                if receipt.get(date_field) and hasattr(receipt[date_field], 'isoformat'):
                    receipt[date_field] = receipt[date_field].isoformat()

            # Parse JSON fields
            for json_field in ['attachments', 'receipt_files']:
                if receipt.get(json_field) and isinstance(receipt[json_field], str):
                    try:
                        receipt[json_field] = json.loads(receipt[json_field])
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Failed to parse JSON field {json_field}: {e}")
                        receipt[json_field] = []

        return jsonify({
            'ok': True,
            'receipts': receipts,
            'counts': status_counts,
            'total': len(receipts)
        })

    except Exception as e:
        logger.error(f"Error fetching incoming receipts: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/stats", methods=["GET"])
def get_incoming_stats():
    """Get statistics about incoming receipts."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()

        # SECURITY: User scoping - only show user's own stats
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()

            # Get counts by status
            cursor = db_execute(conn, db_type, '''
                SELECT status, COUNT(*) as count
                FROM incoming_receipts
                WHERE user_id = %s
                GROUP BY status
            ''', (user_id,))
            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

            # Get counts by source
            cursor = db_execute(conn, db_type, '''
                SELECT source, COUNT(*) as count
                FROM incoming_receipts
                WHERE user_id = %s
                GROUP BY source
            ''', (user_id,))
            source_counts = {row['source'] or 'unknown': row['count'] for row in cursor.fetchall()}

            # Get recent activity
            cursor = db_execute(conn, db_type, '''
                SELECT DATE(received_date) as date, COUNT(*) as count
                FROM incoming_receipts
                WHERE user_id = %s AND received_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                GROUP BY DATE(received_date)
                ORDER BY date DESC
            ''', (user_id,))
            daily_counts = {str(row['date']): row['count'] for row in cursor.fetchall()}

            # Get top merchants
            cursor = db_execute(conn, db_type, '''
                SELECT merchant, COUNT(*) as count
                FROM incoming_receipts
                WHERE user_id = %s AND merchant IS NOT NULL AND merchant != ''
                GROUP BY merchant
                ORDER BY count DESC
                LIMIT 10
            ''', (user_id,))
            top_merchants = [{row['merchant']: row['count']} for row in cursor.fetchall()]
        else:
            # Get counts by status
            cursor = db_execute(conn, db_type, '''
                SELECT status, COUNT(*) as count
                FROM incoming_receipts
                GROUP BY status
            ''')
            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

            # Get counts by source
            cursor = db_execute(conn, db_type, '''
                SELECT source, COUNT(*) as count
                FROM incoming_receipts
                GROUP BY source
            ''')
            source_counts = {row['source'] or 'unknown': row['count'] for row in cursor.fetchall()}

            # Get recent activity
            cursor = db_execute(conn, db_type, '''
                SELECT DATE(received_date) as date, COUNT(*) as count
                FROM incoming_receipts
                WHERE received_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                GROUP BY DATE(received_date)
                ORDER BY date DESC
            ''')
            daily_counts = {str(row['date']): row['count'] for row in cursor.fetchall()}

            # Get top merchants
            cursor = db_execute(conn, db_type, '''
                SELECT merchant, COUNT(*) as count
                FROM incoming_receipts
                WHERE merchant IS NOT NULL AND merchant != ''
                GROUP BY merchant
                ORDER BY count DESC
                LIMIT 10
            ''')
            top_merchants = [{row['merchant']: row['count']} for row in cursor.fetchall()]

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'status_counts': status_counts,
            'source_counts': source_counts,
            'daily_counts': daily_counts,
            'top_merchants': top_merchants,
            'total': sum(status_counts.values())
        })

    except Exception as e:
        logger.error(f"Error fetching incoming stats: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/scan", methods=["POST"])
def trigger_gmail_scan():
    """
    Trigger a Gmail scan for new receipts.

    Body:
    {
        "accounts": ["email@example.com", ...],  # Optional, defaults to user's connected accounts
        "days_back": 7  # Optional, how many days to look back
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        from incoming_receipts_service import scan_gmail_for_new_receipts, save_incoming_receipt
    except ImportError as e:
        return jsonify({'ok': False, 'error': f'Incoming receipts service not available: {e}'}), 503

    data = request.get_json(force=True) or {}

    # Get user's connected Gmail accounts from database or environment
    user_accounts = []
    try:
        from auth import get_current_user_id, is_admin
        from db_mysql import db
        user_id = get_current_user_id()

        # For admin, use environment-based Gmail tokens (dynamically find all GMAIL_TOKEN_* vars)
        if is_admin():
            import os
            # Find all Gmail tokens in environment variables (GMAIL_TOKEN_*)
            for key, value in os.environ.items():
                if key.startswith('GMAIL_TOKEN_') and value:
                    # Convert env var name back to email: GMAIL_TOKEN_USER_DOMAIN_COM -> user@domain.com
                    email_parts = key.replace('GMAIL_TOKEN_', '').lower().replace('_', '.')
                    # Fix the @ symbol - find the last domain part and insert @
                    parts = email_parts.split('.')
                    if len(parts) >= 3:
                        # Assume format: user.domain.tld -> user@domain.tld
                        # or: user.name.domain.tld -> user.name@domain.tld
                        tld = parts[-1]  # com, net, etc
                        domain = parts[-2]  # gmail, business, etc
                        username = '.'.join(parts[:-2])  # everything else
                        email = f"{username}@{domain}.{tld}"
                        if email not in user_accounts:
                            user_accounts.append(email)

        # Also check database for any user
        if user_id:
            conn = db.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT service_account FROM user_credentials
                WHERE user_id = %s AND service_type = 'gmail'
                AND is_active = TRUE AND service_account IS NOT NULL
            ''', (user_id,))
            db_accounts = [row['service_account'] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            # Add any database accounts not already in list
            for acc in db_accounts:
                if acc not in user_accounts:
                    user_accounts.append(acc)
    except Exception as e:
        logger.warning(f"Could not fetch user Gmail accounts: {e}")

    accounts = data.get('accounts', user_accounts if user_accounts else [])
    days_back = int(data.get('days_back', 7))

    if not accounts:
        return jsonify({
            'ok': False,
            'error': 'No Gmail accounts connected. Please connect a Gmail account in Settings → Connected Services.',
            'message': 'Go to Settings to connect your Gmail account for receipt scanning.'
        }), 400

    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    results = {
        'scanned_accounts': [],
        'total_found': 0,
        'total_saved': 0,
        'errors': []
    }

    for account in accounts:
        try:
            receipts = scan_gmail_for_new_receipts(account, since_date)
            saved = 0
            for receipt in receipts:
                if save_incoming_receipt(receipt):
                    saved += 1

            results['scanned_accounts'].append({
                'account': account,
                'found': len(receipts),
                'saved': saved
            })
            results['total_found'] += len(receipts)
            results['total_saved'] += saved

        except Exception as e:
            results['errors'].append({
                'account': account,
                'error': str(e)
            })
            logger.error(f"Error scanning {account}: {e}")

    results['ok'] = True
    return jsonify(results)


@incoming_bp.route("/accept", methods=["POST"])
def accept_incoming_receipt():
    """
    Accept an incoming receipt and create a transaction.

    Body:
    {
        "receipt_id": 123,
        "merchant": "Anthropic",  # Optional, uses receipt data if not provided
        "amount": 20.00,
        "date": "2024-11-15",
        "business_type": "Personal"
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        data = request.get_json(force=True) or {}
        receipt_id = data.get('receipt_id')

        if not receipt_id:
            return jsonify({'ok': False, 'error': 'Missing required field: receipt_id'}), 400

        conn, db_type = get_db_connection()

        # Get receipt data
        cursor = db_execute(conn, db_type, 'SELECT * FROM incoming_receipts WHERE id = %s', (receipt_id,))
        receipt_row = cursor.fetchone()

        if not receipt_row:
            return_db_connection(conn)
            return jsonify({'ok': False, 'error': 'Receipt not found'}), 404

        receipt_data = dict(receipt_row)

        # Use provided values or fall back to receipt data
        merchant = data.get('merchant') or receipt_data.get('merchant') or receipt_data.get('subject', 'Unknown')[:100]
        amount = float(data.get('amount', 0)) or float(receipt_data.get('amount', 0) or 0)

        # Parse date
        trans_date = data.get('date') or receipt_data.get('receipt_date') or receipt_data.get('received_date', '')
        if trans_date and hasattr(trans_date, 'strftime'):
            trans_date = trans_date.strftime('%Y-%m-%d')
        elif trans_date and 'T' in str(trans_date):
            trans_date = str(trans_date).split('T')[0]

        business_type = data.get('business_type', 'Personal')

        # Get next transaction index
        cursor = db_execute(conn, db_type, 'SELECT MAX(_index) as max_idx FROM transactions')
        max_idx = cursor.fetchone()
        next_index = (max_idx['max_idx'] or 0) + 1

        # Get receipt file URL - try multiple possible columns
        receipt_url = (
            receipt_data.get('receipt_image_url') or
            receipt_data.get('r2_url') or
            receipt_data.get('file_path') or
            ''
        )

        # Log if we couldn't find a receipt URL
        if not receipt_url:
            logger.warning(f"No receipt URL found for receipt {receipt_id}. Available keys: {list(receipt_data.keys())}")

        # Insert new transaction
        cursor = db_execute(conn, db_type, '''
            INSERT INTO transactions (
                _index, chase_date, chase_description, chase_amount,
                business_type, receipt_file, r2_url, source, review_status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ''', (
            next_index, trans_date, merchant, amount,
            business_type, receipt_url, receipt_url, 'gmail_inbox', 'good'
        ))

        # Update incoming receipt status
        cursor = db_execute(conn, db_type, '''
            UPDATE incoming_receipts
            SET status = 'accepted', accepted_as_transaction_id = %s, reviewed_at = NOW()
            WHERE id = %s
        ''', (next_index, receipt_id))

        conn.commit()
        return_db_connection(conn)

        logger.info(f"Accepted receipt {receipt_id} as transaction {next_index}")

        return jsonify({
            'ok': True,
            'transaction_id': next_index,
            'merchant': merchant,
            'amount': amount,
            'date': trans_date
        })

    except Exception as e:
        logger.error(f"Error accepting receipt: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/reject", methods=["POST"])
def reject_incoming_receipt():
    """
    Reject an incoming receipt and learn to block similar senders in the future.

    Body:
    {
        "receipt_id": 123,
        "reason": "Not a receipt",  # Optional
        "block_sender": true        # Optional - permanently block this sender
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        data = request.get_json(force=True) or {}
        receipt_id = data.get('receipt_id')
        reason = data.get('reason', 'user_rejected')
        block_sender = data.get('block_sender', True)  # Default to blocking

        if not receipt_id:
            return jsonify({'ok': False, 'error': 'Missing required field: receipt_id'}), 400

        conn, db_type = get_db_connection()

        # Get the receipt's sender info before rejecting
        sender_email = None
        if block_sender:
            cursor = db_execute(conn, db_type, '''
                SELECT from_email, subject FROM incoming_receipts WHERE id = %s
            ''', (receipt_id,))
            receipt_info = cursor.fetchone()
            if receipt_info:
                sender_email = receipt_info.get('from_email') or receipt_info.get(0)

        # Reject the receipt
        cursor = db_execute(conn, db_type, '''
            UPDATE incoming_receipts
            SET status = 'rejected', rejection_reason = %s, reviewed_at = NOW()
            WHERE id = %s
        ''', (reason, receipt_id))

        # Learn to block this sender pattern for future emails
        blocked_pattern = None
        if block_sender and sender_email:
            try:
                # Add to blocked senders list
                cursor = db_execute(conn, db_type, '''
                    INSERT INTO blocked_email_senders (email_pattern, reason, created_at, rejection_count)
                    VALUES (%s, %s, NOW(), 1)
                    ON DUPLICATE KEY UPDATE rejection_count = rejection_count + 1, updated_at = NOW()
                ''', (sender_email.lower(), reason))
                blocked_pattern = sender_email.lower()
                logger.info(f"Added blocked sender pattern: {blocked_pattern}")
            except Exception as block_err:
                # Table might not exist yet - that's okay
                logger.debug(f"Could not add to blocked senders (table may not exist): {block_err}")

        conn.commit()
        return_db_connection(conn)

        logger.info(f"Rejected receipt {receipt_id}: {reason}" +
                   (f" (blocked: {blocked_pattern})" if blocked_pattern else ""))

        return jsonify({
            'ok': True,
            'receipt_id': receipt_id,
            'blocked_sender': blocked_pattern
        })

    except Exception as e:
        logger.error(f"Error rejecting receipt: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/bulk-reject", methods=["POST"])
def bulk_reject_receipts():
    """
    Reject multiple receipts at once.

    Body:
    {
        "receipt_ids": [1, 2, 3, ...],
        "reason": "Not receipts"
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        data = request.get_json(force=True) or {}
        receipt_ids = data.get('receipt_ids', [])
        reason = data.get('reason', 'bulk_rejected')

        if not receipt_ids:
            return jsonify({'ok': False, 'error': 'No receipt IDs provided'}), 400

        conn, db_type = get_db_connection()

        rejected_count = 0
        for rid in receipt_ids:
            try:
                cursor = db_execute(conn, db_type, '''
                    UPDATE incoming_receipts
                    SET status = 'rejected', rejection_reason = %s, reviewed_at = NOW()
                    WHERE id = %s AND status != 'rejected'
                ''', (reason, rid))
                if cursor.rowcount > 0:
                    rejected_count += 1
            except Exception as e:
                logger.warning(f"Failed to reject receipt {rid}: {e}")

        conn.commit()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'rejected_count': rejected_count,
            'total_requested': len(receipt_ids)
        })

    except Exception as e:
        logger.error(f"Error bulk rejecting receipts: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/cleanup", methods=["POST"])
def cleanup_old_receipts():
    """
    Clean up old rejected receipts.

    Body:
    {
        "days_old": 30  # Delete rejected receipts older than this
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        data = request.get_json(force=True) or {}
        days_old = int(data.get('days_old', 30))

        conn, db_type = get_db_connection()

        # Count before deletion
        cursor = db_execute(conn, db_type, '''
            SELECT COUNT(*) as count FROM incoming_receipts
            WHERE status = 'rejected'
            AND reviewed_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        ''', (days_old,))
        count_before = cursor.fetchone()['count']

        # Delete old rejected receipts
        cursor = db_execute(conn, db_type, '''
            DELETE FROM incoming_receipts
            WHERE status = 'rejected'
            AND reviewed_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        ''', (days_old,))

        conn.commit()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'deleted_count': count_before,
            'days_old': days_old
        })

    except Exception as e:
        logger.error(f"Error cleaning up receipts: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/unreject", methods=["POST"])
def unreject_receipt():
    """
    Move a rejected receipt back to pending.

    Body:
    {
        "receipt_id": 123
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        data = request.get_json(force=True) or {}
        receipt_id = data.get('receipt_id')

        if not receipt_id:
            return jsonify({'ok': False, 'error': 'Missing receipt_id'}), 400

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            UPDATE incoming_receipts
            SET status = 'pending', rejection_reason = NULL, reviewed_at = NULL
            WHERE id = %s
        ''', (receipt_id,))

        conn.commit()
        return_db_connection(conn)

        return jsonify({'ok': True, 'receipt_id': receipt_id})

    except Exception as e:
        logger.error(f"Error unrejecting receipt: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/pending", methods=["GET"])
def get_pending_receipts():
    """
    Get unmatched receipts that can be attached to transactions.

    Query params:
    - limit: Max results (default 50)
    - offset: Pagination offset
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        conn, db_type = get_db_connection()

        # Get pending receipts with images
        cursor = db_execute(conn, db_type, '''
            SELECT id, subject, from_email, received_date, amount,
                   merchant, receipt_image_url, ocr_merchant, ocr_amount, ocr_date
            FROM incoming_receipts
            WHERE status = 'pending'
            AND receipt_image_url IS NOT NULL
            AND receipt_image_url != ''
            ORDER BY received_date DESC
            LIMIT %s OFFSET %s
        ''', (limit, offset))

        receipts = cursor.fetchall()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'receipts': receipts,
            'count': len(receipts)
        })

    except Exception as e:
        logger.error(f"Error getting pending receipts: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/match-candidates", methods=["GET"])
def get_match_candidates():
    """
    Find incoming receipts that might match a given transaction.

    Query params:
    - amount: Transaction amount to match
    - date: Transaction date (YYYY-MM-DD)
    - description: Transaction description (for merchant matching)
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute, _ = get_dependencies()

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        amount = request.args.get('amount', type=float)
        date_str = request.args.get('date', '')
        description = request.args.get('description', '').lower()

        if not amount:
            return jsonify({'ok': False, 'error': 'Amount is required'}), 400

        conn, db_type = get_db_connection()

        # Get pending receipts with images
        cursor = db_execute(conn, db_type, '''
            SELECT id, subject, from_email, received_date, amount,
                   merchant, receipt_image_url, ocr_merchant, ocr_amount, ocr_date
            FROM incoming_receipts
            WHERE status = 'pending'
            AND receipt_image_url IS NOT NULL
            AND receipt_image_url != ''
        ''')

        all_receipts = cursor.fetchall()
        return_db_connection(conn)

        # Score each receipt for match quality
        scored = []
        for r in all_receipts:
            score = 0
            receipt_amount = r.get('ocr_amount') or r.get('amount')

            # Amount matching (most important)
            if receipt_amount:
                diff = abs(float(receipt_amount) - amount)
                if diff < 0.01:  # Exact match
                    score += 50
                elif diff < 1.00:  # Within $1
                    score += 40
                elif diff < 5.00:  # Within $5
                    score += 20
                elif diff < 10.00:  # Within $10
                    score += 10

            # Date matching
            if date_str:
                receipt_date = r.get('ocr_date') or r.get('received_date')
                if receipt_date:
                    receipt_date_str = str(receipt_date)[:10]
                    if receipt_date_str == date_str:
                        score += 30
                    elif abs((datetime.strptime(receipt_date_str, '%Y-%m-%d') -
                              datetime.strptime(date_str[:10], '%Y-%m-%d')).days) <= 3:
                        score += 15

            # Merchant matching
            receipt_merchant = (r.get('ocr_merchant') or r.get('merchant') or
                               r.get('subject') or '').lower()
            if description and receipt_merchant:
                # Check for common words
                desc_words = set(description.split())
                merch_words = set(receipt_merchant.split())
                common = desc_words & merch_words
                if common:
                    score += 10 * len(common)

            if score > 0:
                r['match_score'] = score
                scored.append(r)

        # Sort by score descending
        scored.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        return jsonify({
            'ok': True,
            'receipts': scored[:20],  # Top 20 matches
            'count': len(scored)
        })

    except Exception as e:
        logger.error(f"Error finding match candidates: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@incoming_bp.route("/auto-match", methods=["POST"])
def trigger_auto_match():
    """
    Trigger auto-matching of pending receipts to transactions.

    Body (optional):
    {
        "limit": 50  # Max receipts to process (default 50)
    }

    Returns matching results and stats.
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        from smart_auto_matcher import auto_match_pending_receipts, SmartAutoMatcher

        data = request.get_json(force=True) or {}
        limit = data.get('limit', 50)

        # Run auto-matching
        results = auto_match_pending_receipts(limit=limit)

        return jsonify({
            'ok': True,
            'message': 'Auto-matching complete',
            'results': results
        })

    except ImportError as e:
        logger.error(f"Auto-matcher not available: {e}")
        return jsonify({
            'ok': False,
            'error': 'Auto-matching service not available'
        }), 503

    except Exception as e:
        logger.error(f"Error running auto-match: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
