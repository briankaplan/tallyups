"""
================================================================================
Transaction Management API Routes
================================================================================
Flask Blueprint for transaction CRUD operations.

ENDPOINTS:
----------
Core CRUD:
    GET  /api/transactions              - List transactions with pagination
    GET  /api/transactions/<id>         - Get single transaction
    PUT  /api/transactions/<id>         - Update transaction fields
    PUT  /api/transactions/<id>/notes   - Update transaction notes
    PUT  /api/transactions/<id>/description - Update AI description
    POST /api/transaction/update        - Update single field by index

Receipt Linking:
    POST /api/transactions/attach-receipt       - Attach incoming receipt
    POST /api/transactions/<id>/link            - Link receipt to transaction
    POST /api/transactions/<id>/unlink          - Unlink receipt from transaction

Status Management:
    POST /api/transactions/<id>/exclude         - Exclude from matching
    POST /api/transactions/<id>/reject          - Mark as rejected
    POST /api/transactions/fix-business-type    - Bulk fix business type

Report Management:
    POST /api/transactions/move-to-report           - Move to report
    POST /api/transactions/<id>/remove-from-report  - Remove from report
    POST /api/transactions/bulk-remove-from-report  - Bulk remove from report

================================================================================
"""

import os
import logging
from flask import Blueprint, request, jsonify, session

from db_user_scope import get_current_user_id, USER_SCOPING_ENABLED

# Create blueprint
transactions_bp = Blueprint('transactions', __name__, url_prefix='/api')

# Logger setup
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


# =============================================================================
# LAZY IMPORTS - Avoid circular imports
# =============================================================================

def get_db_helpers():
    """Lazy import database helpers"""
    from viewer_server import get_db_connection, return_db_connection, db, USE_DATABASE
    return get_db_connection, return_db_connection, db, USE_DATABASE

def get_auth_helpers():
    """Lazy import auth helpers"""
    from auth import login_required, is_authenticated
    from viewer_server import secure_compare_api_key
    return login_required, is_authenticated, secure_compare_api_key


def check_auth():
    """
    Check authentication using JWT (preferred) or legacy session/admin_key.
    Returns True if authenticated, False otherwise.
    Also sets g.user_id, g.user_role if authenticated via JWT.
    """
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

    # Fall back to legacy auth
    _, is_authenticated, _ = get_auth_helpers()
    return is_authenticated()

def get_user_scope():
    """Lazy import user scoping - returns (get_current_user_id, is_enabled)"""
    try:
        from db_user_scope import get_current_user_id, USER_SCOPING_ENABLED
        return get_current_user_id, USER_SCOPING_ENABLED
    except ImportError:
        def fallback():
            return '00000000-0000-0000-0000-000000000001'
        return fallback, False


# =============================================================================
# TRANSACTION CRUD
# =============================================================================

@transactions_bp.route("/transactions/<int:tx_id>", methods=["GET"])
def get_transaction(tx_id):
    """Get a single transaction by ID.
    Requires authentication via session, admin_key, or JWT token.
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()
    get_current_user_id, user_scoping_enabled = get_user_scope()

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # USER SCOPING: Only return transaction if it belongs to current user (if enabled)
        if user_scoping_enabled:
            user_id = get_current_user_id()
            cursor.execute("""
                SELECT _index, chase_date, chase_description, chase_amount, business_type,
                       category, notes, receipt_file, receipt_url, r2_url, review_status,
                       ocr_verified, ocr_verification_status, ocr_data
                FROM transactions WHERE _index = %s AND user_id = %s
            """, (tx_id, user_id))
        else:
            cursor.execute("""
                SELECT _index, chase_date, chase_description, chase_amount, business_type,
                       category, notes, receipt_file, receipt_url, r2_url, review_status,
                       ocr_verified, ocr_verification_status, ocr_data
                FROM transactions WHERE _index = %s
            """, (tx_id,))

        row = cursor.fetchone()
        cursor.close()
        return_db_connection(conn)

        if not row:
            return jsonify({"error": "Transaction not found"}), 404

        columns = ['_index', 'chase_date', 'chase_description', 'chase_amount', 'business_type',
                   'category', 'notes', 'receipt_file', 'receipt_url', 'r2_url', 'review_status',
                   'ocr_verified', 'ocr_verification_status', 'ocr_data']
        tx = dict(zip(columns, row)) if not isinstance(row, dict) else row

        # Handle date serialization
        if tx.get('chase_date') and hasattr(tx['chase_date'], 'isoformat'):
            tx['chase_date'] = tx['chase_date'].isoformat()

        return jsonify({"ok": True, "transaction": tx})
    except Exception as e:
        logger.error(f"Get transaction error: {e}")
        return jsonify({"error": str(e)}), 500


@transactions_bp.route("/transactions/<int:tx_id>", methods=["PUT"])
def update_transaction(tx_id):
    """Update a transaction's fields (admin only)"""
    _, _, secure_compare_api_key = get_auth_helpers()

    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not secure_compare_api_key(admin_key, expected_key):
        return jsonify({'error': 'Admin key required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Build update query from allowed fields
        allowed_fields = ['chase_date', 'chase_description', 'chase_amount', 'business_type',
                          'review_status', 'notes', 'category', 'receipt_file', 'receipt_url']
        updates = []
        values = []
        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            return jsonify({'error': 'No valid fields to update'}), 400

        values.append(tx_id)
        query = f"UPDATE transactions SET {', '.join(updates)} WHERE _index = %s"
        cursor.execute(query, values)
        conn.commit()

        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'message': f'Transaction {tx_id} updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@transactions_bp.route("/transactions/<int:tx_id>/notes", methods=["PUT"])
def update_transaction_notes(tx_id):
    """Update a transaction's notes field"""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json()
        if data is None:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400

        notes = data.get('notes', '')

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping - only update user's own transactions
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute("UPDATE transactions SET notes = %s WHERE id = %s AND user_id = %s", (notes, tx_id, user_id))
        else:
            cursor.execute("UPDATE transactions SET notes = %s WHERE id = %s", (notes, tx_id))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'message': 'Notes updated'})
    except Exception as e:
        logger.error(f"Update notes error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transactions/<int:tx_id>/description", methods=["PUT"])
def update_transaction_description(tx_id):
    """Update a transaction's ai_note field (description for reports)"""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json()
        if data is None:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400

        ai_note = data.get('ai_note', '')

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping - only update user's own transactions
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute("UPDATE transactions SET ai_note = %s WHERE id = %s AND user_id = %s", (ai_note, tx_id, user_id))
        else:
            cursor.execute("UPDATE transactions SET ai_note = %s WHERE id = %s", (ai_note, tx_id))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'message': 'Description updated'})
    except Exception as e:
        logger.error(f"Update description error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transaction/update", methods=["POST"])
def update_transaction_field():
    """
    Update a single field on a transaction by index.
    Used by the reconciler viewer for quick edits.
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400

        index = data.get('index')
        field = data.get('field')
        value = data.get('value', '')

        if index is None or not field:
            return jsonify({'ok': False, 'error': 'Missing index or field'}), 400

        # SECURITY: Whitelist of allowed field names to prevent SQL injection
        field_map = {
            'Notes': 'notes',
            'notes': 'notes',
            'Business Type': 'business_type',
            'business_type': 'business_type',
            'Category': 'category',
            'category': 'category',
            'ai_category': 'ai_category',
            'ai_note': 'ai_note',
            'Merchant': 'chase_description',
            'merchant': 'chase_description',
            'review_status': 'review_status'
        }

        db_field = field_map.get(field)
        if not db_field:
            logger.warning(f"Rejected unknown field update attempt: {field}")
            return jsonify({'ok': False, 'error': f'Unknown field: {field}'}), 400

        # Validate index is an integer
        try:
            index = int(index)
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'Invalid index'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(f"UPDATE transactions SET {db_field} = %s WHERE `Index` = %s", (value, index))
        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'message': f'Updated {field} for transaction {index}'})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# REPORT MANAGEMENT
# =============================================================================

@transactions_bp.route("/transactions/move-to-report", methods=["POST"])
def move_transactions_to_report():
    """Move transactions to a different report"""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400

        transaction_ids = data.get('transaction_ids', [])
        target_report_id = data.get('target_report_id')

        if not transaction_ids or not target_report_id:
            return jsonify({'ok': False, 'error': 'Missing transaction_ids or target_report_id'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping - verify report belongs to user
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute("SELECT business_type FROM reports WHERE report_id = %s AND user_id = %s", (target_report_id, user_id))
        else:
            cursor.execute("SELECT business_type FROM reports WHERE report_id = %s", (target_report_id,))

        target_report = cursor.fetchone()
        if not target_report:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'ok': False, 'error': 'Target report not found'}), 404

        target_business_type = target_report['business_type'] if isinstance(target_report, dict) else target_report[0]

        # SECURITY: User scoping - only update user's own transactions
        placeholders = ','.join(['%s'] * len(transaction_ids))
        if USER_SCOPING_ENABLED:
            cursor.execute(f"""
                UPDATE transactions
                SET report_id = %s, business_type = %s
                WHERE id IN ({placeholders}) AND user_id = %s
            """, [target_report_id, target_business_type] + list(transaction_ids) + [user_id])
        else:
            cursor.execute(f"""
                UPDATE transactions
                SET report_id = %s, business_type = %s
                WHERE id IN ({placeholders})
            """, [target_report_id, target_business_type] + list(transaction_ids))

        affected = cursor.rowcount
        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'message': f'{affected} transaction(s) moved', 'affected': affected})
    except Exception as e:
        logger.error(f"Move transactions error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transactions/<int:tx_id>/remove-from-report", methods=["POST"])
def remove_transaction_from_report(tx_id):
    """Remove a transaction from its report (returns to reconciliation queue)"""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping - only update user's own transactions
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute("""
                UPDATE transactions
                SET report_id = NULL
                WHERE id = %s AND user_id = %s
            """, (tx_id, user_id))
        else:
            cursor.execute("""
                UPDATE transactions
                SET report_id = NULL
                WHERE id = %s
            """, (tx_id,))

        affected = cursor.rowcount
        conn.commit()
        cursor.close()
        return_db_connection(conn)

        if affected == 0:
            return jsonify({'ok': False, 'error': 'Transaction not found'}), 404

        return jsonify({'ok': True, 'message': 'Transaction removed from report'})
    except Exception as e:
        logger.error(f"Remove from report error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transactions/bulk-remove-from-report", methods=["POST"])
def bulk_remove_transactions_from_report():
    """Remove multiple transactions from their report"""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400

        transaction_ids = data.get('transaction_ids', [])
        if not transaction_ids:
            return jsonify({'ok': False, 'error': 'No transaction_ids provided'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        placeholders = ','.join(['%s'] * len(transaction_ids))

        # SECURITY: User scoping - only update user's own transactions
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute(f"""
                UPDATE transactions
                SET report_id = NULL
                WHERE id IN ({placeholders}) AND user_id = %s
            """, list(transaction_ids) + [user_id])
        else:
            cursor.execute(f"""
                UPDATE transactions
                SET report_id = NULL
                WHERE id IN ({placeholders})
            """, list(transaction_ids))

        affected = cursor.rowcount
        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'message': f'{affected} transaction(s) removed from report', 'affected': affected})
    except Exception as e:
        logger.error(f"Bulk remove from report error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# RECEIPT LINKING
# =============================================================================

@transactions_bp.route("/transactions/attach-receipt", methods=["POST"])
def attach_receipt_to_transaction():
    """Attach a receipt from incoming_receipts to a transaction"""
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400

        transaction_index = data.get('transaction_index')
        incoming_receipt_id = data.get('incoming_receipt_id')

        if not transaction_index or not incoming_receipt_id:
            return jsonify({'ok': False, 'error': 'Missing transaction_index or incoming_receipt_id'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get the incoming receipt's image URL
        cursor.execute('''
            SELECT receipt_image_url, ocr_merchant, ocr_amount, ocr_date
            FROM incoming_receipts WHERE id = %s
        ''', (incoming_receipt_id,))
        receipt = cursor.fetchone()

        if not receipt:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'ok': False, 'error': 'Incoming receipt not found'}), 404

        receipt_url = receipt.get('receipt_image_url') if isinstance(receipt, dict) else receipt[0]
        if not receipt_url:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'ok': False, 'error': 'Receipt has no image URL'}), 400

        # Update the transaction with the receipt
        cursor.execute('''
            UPDATE transactions
            SET r2_url = %s
            WHERE _index = %s
        ''', (receipt_url, transaction_index))

        # Mark the incoming receipt as matched
        cursor.execute('''
            UPDATE incoming_receipts
            SET status = 'matched', matched_transaction_id = %s
            WHERE id = %s
        ''', (transaction_index, incoming_receipt_id))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'receipt_url': receipt_url,
            'message': f'Receipt attached to transaction {transaction_index}'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transactions/<int:tx_id>/link", methods=["POST"])
def link_receipt_to_transaction(tx_id):
    """Link a receipt to a transaction (iOS app endpoint)"""
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json() or {}
        receipt_id = data.get('receipt_id')

        if not receipt_id:
            return jsonify({'ok': False, 'error': 'Missing receipt_id'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get the receipt's URL from incoming_receipts
        receipt_url = None
        cursor.execute('''
            SELECT receipt_image_url, r2_url FROM incoming_receipts WHERE id = %s
        ''', (receipt_id,))
        receipt = cursor.fetchone()
        if receipt:
            if isinstance(receipt, dict):
                receipt_url = receipt.get('r2_url') or receipt.get('receipt_image_url')
            else:
                receipt_url = receipt[1] or receipt[0]

        # If not found, try by transaction _index
        if not receipt_url:
            try:
                cursor.execute('''
                    SELECT r2_url FROM transactions WHERE _index = %s
                ''', (int(receipt_id),))
                tx = cursor.fetchone()
                if tx:
                    receipt_url = tx.get('r2_url') if isinstance(tx, dict) else tx[0]
            except ValueError:
                pass

        if not receipt_url:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'ok': False, 'error': 'Receipt not found'}), 404

        # Update the transaction with the receipt URL
        cursor.execute('''
            UPDATE transactions
            SET r2_url = %s, review_status = 'matched'
            WHERE _index = %s
        ''', (receipt_url, tx_id))

        # Mark incoming receipt as matched
        cursor.execute('''
            UPDATE incoming_receipts
            SET status = 'matched', matched_transaction_id = %s
            WHERE id = %s
        ''', (tx_id, receipt_id))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'Receipt linked to transaction {tx_id}',
            'receipt_url': receipt_url
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transactions/<int:tx_id>/unlink", methods=["POST"])
def unlink_receipt_from_transaction(tx_id):
    """Unlink a receipt from a transaction (iOS app endpoint)"""
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json() or {}
        receipt_id = data.get('receipt_id')

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Clear the receipt URL from the transaction
        cursor.execute('''
            UPDATE transactions
            SET r2_url = NULL, review_status = 'pending'
            WHERE _index = %s
        ''', (tx_id,))

        # If a specific receipt was mentioned, unlink it
        if receipt_id:
            cursor.execute('''
                UPDATE incoming_receipts
                SET status = 'pending', matched_transaction_id = NULL
                WHERE id = %s AND matched_transaction_id = %s
            ''', (receipt_id, tx_id))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'Receipt unlinked from transaction {tx_id}'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# STATUS MANAGEMENT
# =============================================================================

@transactions_bp.route("/transactions/<int:tx_id>/exclude", methods=["POST"])
def exclude_transaction(tx_id):
    """Exclude or unexclude a transaction from receipt matching"""
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        data = request.get_json() or {}
        excluded = data.get('excluded', True)
        reason = data.get('exclusion_reason', '')

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        if excluded:
            cursor.execute('''
                UPDATE transactions
                SET review_status = 'excluded', notes = CONCAT(COALESCE(notes, ''), %s)
                WHERE _index = %s
            ''', (f' [Excluded: {reason}]' if reason else ' [Excluded]', tx_id))
        else:
            cursor.execute('''
                UPDATE transactions
                SET review_status = CASE WHEN r2_url IS NOT NULL THEN 'matched' ELSE 'pending' END
                WHERE _index = %s
            ''', (tx_id,))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'Transaction {tx_id} {"excluded" if excluded else "unexcluded"}',
            'excluded': excluded
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transactions/<int:tx_id>/reject", methods=["POST"])
def reject_transaction(tx_id):
    """Mark a transaction as rejected/hidden"""
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    _, _, db, USE_DATABASE = get_db_helpers()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE transactions
            SET review_status = 'rejected'
            WHERE _index = %s
        ''', (tx_id,))

        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'rejected': tx_id})
    except Exception as e:
        logger.error(f"Transaction reject error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@transactions_bp.route("/transactions/fix-business-type", methods=["POST"])
def fix_business_type():
    """Fix business type for specific transactions"""
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    _, _, db, USE_DATABASE = get_db_helpers()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        data = request.get_json()
        transaction_ids = data.get('transaction_ids', [])
        new_business_type = data.get('business_type')
        description_match = data.get('description_match')

        if not new_business_type:
            return jsonify({'ok': False, 'error': 'business_type required'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()

        if transaction_ids:
            placeholders = ', '.join(['%s'] * len(transaction_ids))
            cursor.execute(f"""
                UPDATE transactions
                SET business_type = %s
                WHERE id IN ({placeholders})
            """, [new_business_type] + transaction_ids)
        elif description_match:
            cursor.execute("""
                UPDATE transactions
                SET business_type = %s
                WHERE chase_description LIKE %s
            """, (new_business_type, description_match))
        else:
            return jsonify({'ok': False, 'error': 'transaction_ids or description_match required'}), 400

        conn.commit()
        updated = cursor.rowcount

        return jsonify({
            'ok': True,
            'updated': updated,
            'new_business_type': new_business_type
        })
    except Exception as e:
        logger.error(f"Fix business type error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


# =============================================================================
# NOTE: The following routes remain in viewer_server.py for now:
# - GET /api/transactions (complex with pandas/dataframe dependencies)
# - /update_row (legacy route with dataframe dependencies)
# - /api/bulk/* routes (depend on ensure_df, update_row_by_index)
# =============================================================================
