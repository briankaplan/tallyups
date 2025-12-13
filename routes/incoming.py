"""
Incoming Receipts API Blueprint
===============================
Gmail inbox monitoring, receipt processing, and auto-matching.

Routes:
- GET  /api/incoming/receipts - List all incoming receipts
- POST /api/incoming/accept - Accept receipt as transaction
- POST /api/incoming/reject - Reject receipt
- POST /api/incoming/scan - Trigger Gmail scan
- GET  /api/incoming/stats - Get inbox statistics
- POST /api/incoming/cleanup - Clean up old receipts
- And more...

This blueprint handles the Gmail receipt inbox system.
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
    """Check if request is authenticated via admin key or session."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key == expected_key:
        return True
    if session.get('authenticated'):
        return True
    return False


def extract_merchant_from_subject(subject):
    """Smart merchant extraction from email subject lines."""
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

        if status == 'all':
            query = 'SELECT * FROM incoming_receipts ORDER BY received_date DESC LIMIT %s'
            cursor = db_execute(conn, db_type, query, (limit,))
        else:
            query = 'SELECT * FROM incoming_receipts WHERE status = %s ORDER BY received_date DESC LIMIT %s'
            cursor = db_execute(conn, db_type, query, (status, limit))

        receipts = [dict(row) for row in cursor.fetchall()]

        # Get counts by status
        cursor = db_execute(conn, db_type, 'SELECT status, COUNT(*) as count FROM incoming_receipts GROUP BY status')
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
                    except:
                        pass

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
        "accounts": ["email@example.com", ...],  # Optional, defaults to all
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

    accounts = data.get('accounts', [
        'kaplan.brian@gmail.com',
        'brian@downhome.com',
        'brian@musiccityrodeo.com'
    ])
    days_back = int(data.get('days_back', 7))

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

        # Get receipt file URL
        receipt_url = receipt_data.get('receipt_image_url') or receipt_data.get('file_path') or ''

        # Insert new transaction
        cursor = db_execute(conn, db_type, '''
            INSERT INTO transactions (
                _index, chase_date, chase_description, chase_amount,
                business_type, receipt_url, r2_url, source, review_status, created_at
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
    Reject an incoming receipt.

    Body:
    {
        "receipt_id": 123,
        "reason": "Not a receipt"  # Optional
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

        if not receipt_id:
            return jsonify({'ok': False, 'error': 'Missing required field: receipt_id'}), 400

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            UPDATE incoming_receipts
            SET status = 'rejected', rejection_reason = %s, reviewed_at = NOW()
            WHERE id = %s
        ''', (reason, receipt_id))

        conn.commit()
        return_db_connection(conn)

        logger.info(f"Rejected receipt {receipt_id}: {reason}")

        return jsonify({'ok': True, 'receipt_id': receipt_id})

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
