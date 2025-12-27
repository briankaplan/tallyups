"""
Reports API Blueprint
======================
Expense report management, generation, and export.

Routes:
- GET    /api/reports - List all reports
- POST   /api/reports - Create new report
- PATCH  /api/reports/<id> - Update report (rename, change status)
- DELETE /api/reports/<id> - Delete report (returns transactions to main table)
- POST   /api/reports/<id>/add - Add transaction to report
- POST   /api/reports/<id>/remove - Remove transaction from report
- GET    /api/reports/<id>/items - Get report items
- GET    /api/reports/stats - Report statistics
- GET    /api/reports/dashboard - Dashboard data
- POST   /api/reports/generate - Generate report with AI notes
- GET    /api/reports/<id>/export/<format> - Export report

This blueprint handles expense report workflows.
"""

import os
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, session

from logging_config import get_logger
from db_user_scope import get_current_user_id, USER_SCOPING_ENABLED

logger = get_logger("routes.reports")

# Create blueprint
reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')


def get_dependencies():
    """Lazy import dependencies to avoid circular imports."""
    from viewer_server import (
        USE_DATABASE,
        db,
        login_required,
        validate_business_type,
    )
    return USE_DATABASE, db, login_required, validate_business_type


def check_auth():
    """Check if request is authenticated using constant-time comparison."""
    import secrets
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    # SECURITY: Use constant-time comparison to prevent timing attacks
    if admin_key and expected_key and secrets.compare_digest(str(admin_key), str(expected_key)):
        return True
    if session.get('authenticated'):
        return True
    return False


@reports_bp.route("", methods=["GET"])
def api_reports_list():
    """List all reports."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    try:
        status_filter = request.args.get('status')

        # USER SCOPING: Get user_id for filtering
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        # Get reports (filtered by user if scoping enabled)
        if USER_SCOPING_ENABLED and user_id:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT report_id, report_name, business_type, status, expense_count, total_amount, created_at
                FROM reports WHERE user_id = %s ORDER BY created_at DESC
            ''', (user_id,))
            reports = cursor.fetchall()
            db.return_connection(conn)
        else:
            reports = db.get_all_reports()

        result = []
        for r in reports:
            report_status = r.get('status') or 'draft'
            if status_filter and report_status != status_filter:
                continue

            result.append({
                'report_id': r.get('report_id') or r.get('id'),
                'id': r.get('report_id') or r.get('id'),
                'report_name': r.get('report_name') or r.get('name') or 'Untitled',
                'name': r.get('report_name') or r.get('name') or 'Untitled',
                'total': float(r.get('total_amount') or 0),
                'count': r.get('expense_count') or 0,
                'status': report_status,
                'business_type': r.get('business_type') or '',
                'created_at': str(r.get('created_at') or '')
            })

        return jsonify({'ok': True, 'reports': result})

    except Exception as e:
        logger.error(f"API reports list error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@reports_bp.route("", methods=["POST"])
def api_reports_create():
    """Create a new report."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, validate_business_type = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        data = request.get_json() or {}
        name = data.get('name', f"Report {datetime.now().strftime('%Y-%m-%d')}")
        status = data.get('status', 'draft')
        business_type = data.get('business_type', '')

        # Validate business_type if provided
        if business_type:
            is_valid, error_msg = validate_business_type(business_type)
            if not is_valid:
                return jsonify({'ok': False, 'error': error_msg}), 400

        if status not in ('draft', 'submitted'):
            return jsonify({'ok': False, 'error': "status must be 'draft' or 'submitted'"}), 400

        report_id = f"RPT-{uuid.uuid4().hex[:8].upper()}"

        # USER SCOPING: Get user_id for new report
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        conn = db.get_connection()
        cursor = conn.cursor()

        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                INSERT INTO reports (report_id, report_name, business_type, status, expense_count, total_amount, user_id, created_at)
                VALUES (%s, %s, %s, %s, 0, 0.00, %s, NOW())
            ''', (report_id, name, business_type, status, user_id))
        else:
            cursor.execute('''
                INSERT INTO reports (report_id, report_name, business_type, status, expense_count, total_amount, created_at)
                VALUES (%s, %s, %s, %s, 0, 0.00, NOW())
            ''', (report_id, name, business_type, status))

        conn.commit()

        logger.info(f"Created report {report_id}: {name}")

        return jsonify({
            'ok': True,
            'report_id': report_id,
            'id': report_id,
            'name': name,
            'status': status,
            'total': 0,
            'count': 0
        })

    except Exception as e:
        logger.error(f"API report create error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/<report_id>", methods=["PATCH"])
def api_report_update(report_id):
    """Update a report (rename, change status, etc.)."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        data = request.get_json() or {}
        updates = []
        params = []

        if 'name' in data:
            updates.append("report_name = %s")
            params.append(data['name'])

        if 'status' in data and data['status'] in ('draft', 'submitted'):
            updates.append("status = %s")
            params.append(data['status'])

        if 'business_type' in data:
            updates.append("business_type = %s")
            params.append(data['business_type'])

        if not updates:
            return jsonify({'ok': False, 'error': 'No valid fields to update'}), 400

        params.append(report_id)
        conn = db.get_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping - only update user's own reports
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            params.append(user_id)
            cursor.execute(f'''
                UPDATE reports SET {', '.join(updates)} WHERE report_id = %s AND user_id = %s
            ''', params)
        else:
            cursor.execute(f'''
                UPDATE reports SET {', '.join(updates)} WHERE report_id = %s
            ''', params)

        conn.commit()

        logger.info(f"Updated report {report_id}")

        return jsonify({'ok': True, 'report_id': report_id})

    except Exception as e:
        logger.error(f"API report update error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/<report_id>", methods=["DELETE"])
def api_report_delete(report_id):
    """Delete a report and return all transactions to the main reconciliation table."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # SECURITY: Get user_id for scoping
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        # First, count how many transactions will be returned to main table
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                SELECT COUNT(*) as count FROM transactions WHERE report_id = %s AND user_id = %s
            ''', (report_id, user_id))
        else:
            cursor.execute('''
                SELECT COUNT(*) as count FROM transactions WHERE report_id = %s
            ''', (report_id,))

        result = cursor.fetchone()
        transaction_count = result['count'] if result else 0

        # Return all transactions to main reconciliation table (clear report_id)
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                UPDATE transactions SET report_id = NULL WHERE report_id = %s AND user_id = %s
            ''', (report_id, user_id))
        else:
            cursor.execute('''
                UPDATE transactions SET report_id = NULL WHERE report_id = %s
            ''', (report_id,))

        # Delete the report record (with user scoping)
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                DELETE FROM reports WHERE report_id = %s AND user_id = %s
            ''', (report_id, user_id))
        else:
            cursor.execute('''
                DELETE FROM reports WHERE report_id = %s
            ''', (report_id,))

        if cursor.rowcount == 0:
            db.return_connection(conn)
            return jsonify({'ok': False, 'error': 'Report not found'}), 404

        conn.commit()

        logger.info(f"Deleted report {report_id}, returned {transaction_count} transactions to main table")

        return jsonify({
            'ok': True,
            'report_id': report_id,
            'transactions_returned': transaction_count,
            'message': f'Report deleted. {transaction_count} transaction(s) returned to reconciliation.'
        })

    except Exception as e:
        logger.error(f"API report delete error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/<report_id>/add", methods=["POST"])
def api_report_add_item(report_id):
    """Add a transaction to a report."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        data = request.get_json() or {}
        transaction_index = data.get('_index') or data.get('transaction_index')

        if not transaction_index:
            return jsonify({'ok': False, 'error': 'Missing transaction _index'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()

        # SECURITY: Get user_id for scoping
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        # Update transaction to link to report (with user scoping)
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                UPDATE transactions SET report_id = %s WHERE _index = %s AND user_id = %s
            ''', (report_id, transaction_index, user_id))
        else:
            cursor.execute('''
                UPDATE transactions SET report_id = %s WHERE _index = %s
            ''', (report_id, transaction_index))

        if cursor.rowcount == 0:
            db.return_connection(conn)
            return jsonify({'ok': False, 'error': 'Transaction not found'}), 404

        # CRITICAL: Update report metadata (expense_count and total_amount)
        # Exclude deleted transactions from counts
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                UPDATE reports
                SET expense_count = (SELECT COUNT(*) FROM transactions WHERE report_id = %s AND user_id = %s AND (deleted IS NULL OR deleted = 0)),
                    total_amount = (SELECT COALESCE(SUM(ABS(chase_amount)), 0) FROM transactions WHERE report_id = %s AND user_id = %s AND (deleted IS NULL OR deleted = 0))
                WHERE report_id = %s AND user_id = %s
            ''', (report_id, user_id, report_id, user_id, report_id, user_id))
        else:
            cursor.execute('''
                UPDATE reports
                SET expense_count = (SELECT COUNT(*) FROM transactions WHERE report_id = %s AND (deleted IS NULL OR deleted = 0)),
                    total_amount = (SELECT COALESCE(SUM(ABS(chase_amount)), 0) FROM transactions WHERE report_id = %s AND (deleted IS NULL OR deleted = 0))
                WHERE report_id = %s
            ''', (report_id, report_id, report_id))

        conn.commit()

        # Get updated counts for response
        cursor.execute('''
            SELECT expense_count, total_amount FROM reports WHERE report_id = %s
        ''', (report_id,))
        updated = cursor.fetchone()

        logger.info(f"Added transaction {transaction_index} to report {report_id}")

        return jsonify({
            'ok': True,
            'report_id': report_id,
            '_index': transaction_index,
            'expense_count': updated['expense_count'] if updated else 0,
            'total_amount': float(updated['total_amount']) if updated else 0
        })

    except Exception as e:
        logger.error(f"API report add item error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/<report_id>/remove", methods=["POST"])
def api_report_remove_item(report_id):
    """Remove a transaction from a report."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        data = request.get_json() or {}
        transaction_index = data.get('_index') or data.get('transaction_index')

        if not transaction_index:
            return jsonify({'ok': False, 'error': 'Missing transaction _index'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()

        # SECURITY: Get user_id for scoping
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        # Remove transaction from report (with user scoping)
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                UPDATE transactions SET report_id = NULL WHERE _index = %s AND report_id = %s AND user_id = %s
            ''', (transaction_index, report_id, user_id))
        else:
            cursor.execute('''
                UPDATE transactions SET report_id = NULL WHERE _index = %s AND report_id = %s
            ''', (transaction_index, report_id))

        # CRITICAL: Update report metadata (expense_count and total_amount)
        # Exclude deleted transactions from counts
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                UPDATE reports
                SET expense_count = (SELECT COUNT(*) FROM transactions WHERE report_id = %s AND user_id = %s AND (deleted IS NULL OR deleted = 0)),
                    total_amount = (SELECT COALESCE(SUM(ABS(chase_amount)), 0) FROM transactions WHERE report_id = %s AND user_id = %s AND (deleted IS NULL OR deleted = 0))
                WHERE report_id = %s AND user_id = %s
            ''', (report_id, user_id, report_id, user_id, report_id, user_id))
        else:
            cursor.execute('''
                UPDATE reports
                SET expense_count = (SELECT COUNT(*) FROM transactions WHERE report_id = %s AND (deleted IS NULL OR deleted = 0)),
                    total_amount = (SELECT COALESCE(SUM(ABS(chase_amount)), 0) FROM transactions WHERE report_id = %s AND (deleted IS NULL OR deleted = 0))
                WHERE report_id = %s
            ''', (report_id, report_id, report_id))

        conn.commit()

        # Get updated counts for response
        if USER_SCOPING_ENABLED and user_id:
            cursor.execute('''
                SELECT expense_count, total_amount FROM reports WHERE report_id = %s AND user_id = %s
            ''', (report_id, user_id))
        else:
            cursor.execute('''
                SELECT expense_count, total_amount FROM reports WHERE report_id = %s
            ''', (report_id,))
        updated = cursor.fetchone()

        logger.info(f"Removed transaction {transaction_index} from report {report_id}")

        return jsonify({
            'ok': True,
            'report_id': report_id,
            '_index': transaction_index,
            'expense_count': updated['expense_count'] if updated else 0,
            'total_amount': float(updated['total_amount']) if updated else 0
        })

    except Exception as e:
        logger.error(f"API report remove item error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/<report_id>/items", methods=["GET"])
def api_report_items(report_id):
    """Get all transactions in a report."""
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping - verify report belongs to user
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute('''
                SELECT report_name, business_type, status FROM reports
                WHERE report_id = %s AND user_id = %s
            ''', (report_id, user_id))
        else:
            cursor.execute('''
                SELECT report_name, business_type, status FROM reports WHERE report_id = %s
            ''', (report_id,))
        report_info = cursor.fetchone()

        if not report_info:
            return jsonify({'ok': False, 'error': 'Report not found'}), 404
        report_name = report_info['report_name']

        # SECURITY: User scoping on transactions
        if USER_SCOPING_ENABLED:
            cursor.execute('''
                SELECT _index, chase_date, chase_description, chase_amount, chase_category,
                       business_type, r2_url, receipt_file, ai_note, review_status
                FROM transactions
                WHERE report_id = %s AND user_id = %s AND (deleted IS NULL OR deleted = 0)
                ORDER BY chase_date DESC
            ''', (report_id, user_id))
        else:
            cursor.execute('''
                SELECT _index, chase_date, chase_description, chase_amount, chase_category,
                       business_type, r2_url, receipt_file, ai_note, review_status
                FROM transactions
                WHERE report_id = %s AND (deleted IS NULL OR deleted = 0)
                ORDER BY chase_date DESC
            ''', (report_id,))

        items = []
        total = 0
        for row in cursor.fetchall():
            item = dict(row)
            # Serialize dates
            if item.get('chase_date') and hasattr(item['chase_date'], 'isoformat'):
                item['chase_date'] = item['chase_date'].isoformat()
            # Map r2_url or receipt_file to receipt_url for frontend compatibility
            item['receipt_url'] = item.get('r2_url') or item.get('receipt_file') or ''
            amount = float(item.get('chase_amount') or 0)
            total += abs(amount)
            items.append(item)

        return jsonify({
            'ok': True,
            'report_id': report_id,
            'report_name': report_name,
            'items': items,
            'count': len(items),
            'total': total
        })

    except Exception as e:
        logger.error(f"API report items error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/stats", methods=["GET"])
def api_reports_stats():
    """Get report statistics for dashboard."""
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({
            'total_amount': 0,
            'total_transactions': 0,
            'match_rate': 0,
            'pending_review': 0
        })

    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get YTD totals for dashboard
        year = datetime.now().year

        # SECURITY: User scoping - only show user's own stats
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(ABS(chase_amount)) as total_amount,
                    SUM(CASE WHEN (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '') THEN 1 ELSE 0 END) as with_receipts,
                    SUM(CASE WHEN review_status IS NULL OR review_status = '' THEN 1 ELSE 0 END) as pending
                FROM transactions
                WHERE user_id = %s AND YEAR(chase_date) = %s
                AND (deleted IS NULL OR deleted = 0)
            ''', (user_id, year))
        else:
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(ABS(chase_amount)) as total_amount,
                    SUM(CASE WHEN (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '') THEN 1 ELSE 0 END) as with_receipts,
                    SUM(CASE WHEN review_status IS NULL OR review_status = '' THEN 1 ELSE 0 END) as pending
                FROM transactions
                WHERE YEAR(chase_date) = %s
                AND (deleted IS NULL OR deleted = 0)
            ''', (year,))

        row = cursor.fetchone()

        total = row['total'] or 0
        total_amount = float(row['total_amount'] or 0)
        with_receipts = row['with_receipts'] or 0
        pending = row['pending'] or 0
        match_rate = (with_receipts / total * 100) if total > 0 else 0

        return jsonify({
            'total_amount': round(total_amount, 2),
            'total_transactions': total,
            'match_rate': round(match_rate, 1),
            'pending_review': pending
        })

    except Exception as e:
        logger.error(f"API reports stats error: {e}")
        return jsonify({
            'total_amount': 0,
            'total_transactions': 0,
            'match_rate': 0,
            'pending_review': 0
        })
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/dashboard", methods=["GET"])
def api_reports_dashboard():
    """Get dashboard data for reports page."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        # YTD totals
        if USER_SCOPING_ENABLED:
            cursor.execute('''
                SELECT
                    COUNT(*) as total_transactions,
                    SUM(ABS(chase_amount)) as total_amount,
                    SUM(CASE WHEN (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '') THEN 1 ELSE 0 END) as with_receipts
                FROM transactions
                WHERE user_id = %s AND YEAR(chase_date) = YEAR(NOW())
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT
                    COUNT(*) as total_transactions,
                    SUM(ABS(chase_amount)) as total_amount,
                    SUM(CASE WHEN (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '') THEN 1 ELSE 0 END) as with_receipts
                FROM transactions
                WHERE YEAR(chase_date) = YEAR(NOW())
            ''')
        ytd = cursor.fetchone()

        # By business type - normalize different formats
        if USER_SCOPING_ENABLED:
            cursor.execute('''
                SELECT
                    CASE
                        WHEN business_type IN ('Business', 'Business') THEN 'Business'
                        WHEN business_type IN ('Secondary', 'Secondary', 'MCR') THEN 'Secondary'
                        WHEN business_type IN ('EM.co', 'EM Co', 'EM_co') THEN 'EM.co'
                        WHEN business_type = 'Personal' THEN 'Personal'
                        ELSE 'Personal'
                    END AS normalized_business_type,
                    COUNT(*) as count,
                    SUM(ABS(chase_amount)) as total
                FROM transactions
                WHERE user_id = %s AND YEAR(chase_date) = YEAR(NOW())
                AND business_type IS NOT NULL AND business_type != ''
                GROUP BY normalized_business_type
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT
                    CASE
                        WHEN business_type IN ('Business', 'Business') THEN 'Business'
                        WHEN business_type IN ('Secondary', 'Secondary', 'MCR') THEN 'Secondary'
                        WHEN business_type IN ('EM.co', 'EM Co', 'EM_co') THEN 'EM.co'
                        WHEN business_type = 'Personal' THEN 'Personal'
                        ELSE 'Personal'
                    END AS normalized_business_type,
                    COUNT(*) as count,
                    SUM(ABS(chase_amount)) as total
                FROM transactions
                WHERE YEAR(chase_date) = YEAR(NOW())
                AND business_type IS NOT NULL AND business_type != ''
                GROUP BY normalized_business_type
            ''')
        by_business = {}
        for row in cursor.fetchall():
            by_business[row['normalized_business_type']] = {
                'count': row['count'],
                'total': float(row['total'] or 0)
            }

        # Monthly trend
        if USER_SCOPING_ENABLED:
            cursor.execute('''
                SELECT
                    DATE_FORMAT(chase_date, '%%Y-%%m') as month,
                    SUM(ABS(chase_amount)) as total
                FROM transactions
                WHERE user_id = %s AND chase_date >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
                GROUP BY DATE_FORMAT(chase_date, '%%Y-%%m')
                ORDER BY month
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT
                    DATE_FORMAT(chase_date, '%Y-%m') as month,
                    SUM(ABS(chase_amount)) as total
                FROM transactions
                WHERE chase_date >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
                GROUP BY DATE_FORMAT(chase_date, '%Y-%m')
                ORDER BY month
            ''')
        monthly = []
        for row in cursor.fetchall():
            monthly.append({
                'month': row['month'],
                'total': float(row['total'] or 0)
            })

        # By category
        if USER_SCOPING_ENABLED:
            cursor.execute('''
                SELECT
                    chase_category as category,
                    COUNT(*) as count,
                    SUM(ABS(chase_amount)) as total
                FROM transactions
                WHERE user_id = %s AND YEAR(chase_date) = YEAR(NOW())
                AND chase_category IS NOT NULL AND chase_category != ''
                GROUP BY chase_category
                ORDER BY total DESC
                LIMIT 10
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT
                    chase_category as category,
                    COUNT(*) as count,
                    SUM(ABS(chase_amount)) as total
                FROM transactions
                WHERE YEAR(chase_date) = YEAR(NOW())
                AND chase_category IS NOT NULL AND chase_category != ''
                GROUP BY chase_category
                ORDER BY total DESC
                LIMIT 10
            ''')
        by_category = []
        for row in cursor.fetchall():
            by_category.append({
                'category': row['category'],
                'count': row['count'],
                'total': float(row['total'] or 0)
            })

        # Recent reports - CRITICAL for reports list display
        if USER_SCOPING_ENABLED:
            cursor.execute('''
                SELECT report_id, report_name, business_type, status,
                       total_amount, expense_count, created_at, submitted_at
                FROM reports
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 20
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT report_id, report_name, business_type, status,
                       total_amount, expense_count, created_at, submitted_at
                FROM reports
                ORDER BY created_at DESC
                LIMIT 20
            ''')
        recent_reports = []
        for row in cursor.fetchall():
            created_at = row['created_at']
            submitted_at = row['submitted_at']
            recent_reports.append({
                'report_id': row['report_id'],
                'name': row['report_name'],
                'business_type': row['business_type'],
                'status': row['status'] or 'draft',
                'total_amount': float(row['total_amount'] or 0),
                'expense_count': row['expense_count'] or 0,
                'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(created_at, 'strftime') else str(created_at) if created_at else None,
                'submitted_at': submitted_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(submitted_at, 'strftime') else str(submitted_at) if submitted_at else None
            })

        # Report counts
        report_count = len(recent_reports)
        reports_this_month = sum(1 for r in recent_reports if r['created_at'] and r['created_at'][:7] == datetime.now().strftime('%Y-%m'))

        return jsonify({
            'ok': True,
            'ytd': {
                'total_transactions': ytd['total_transactions'] or 0,
                'total_amount': float(ytd['total_amount'] or 0),
                'with_receipts': ytd['with_receipts'] or 0,
                'receipt_coverage': (ytd['with_receipts'] / ytd['total_transactions'] * 100) if ytd['total_transactions'] else 0,
                'missing_receipts': (ytd['total_transactions'] or 0) - (ytd['with_receipts'] or 0),
                'pending_review': 0,
                'report_count': report_count,
                'reports_this_month': reports_this_month
            },
            'by_business': by_business,
            'monthly_trend': monthly,
            'by_category': by_category,
            'recent_reports': recent_reports
        })

    except Exception as e:
        logger.error(f"API reports dashboard error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/business-summary", methods=["GET"])
def api_business_summary():
    """Get business summary for reports."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        year = request.args.get('year', datetime.now().year)

        conn = db.get_connection()
        cursor = conn.cursor()

        # SECURITY: User scoping - only show user's own data
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute('''
                SELECT
                    CASE
                        WHEN business_type IN ('Business', 'Business') THEN 'Business'
                        WHEN business_type IN ('Secondary', 'Secondary', 'MCR') THEN 'Secondary'
                        WHEN business_type IN ('EM.co', 'EM Co', 'EM_co') THEN 'EM.co'
                        WHEN business_type = 'Personal' THEN 'Personal'
                        ELSE 'Personal'
                    END AS normalized_business_type,
                    COUNT(*) as transaction_count,
                    SUM(ABS(chase_amount)) as total_amount,
                    SUM(CASE WHEN (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '') THEN 1 ELSE 0 END) as with_receipts,
                    SUM(CASE WHEN review_status = 'good' THEN 1 ELSE 0 END) as reviewed
                FROM transactions
                WHERE user_id = %s AND YEAR(chase_date) = %s
                GROUP BY normalized_business_type
            ''', (user_id, year))
        else:
            cursor.execute('''
                SELECT
                    CASE
                        WHEN business_type IN ('Business', 'Business') THEN 'Business'
                        WHEN business_type IN ('Secondary', 'Secondary', 'MCR') THEN 'Secondary'
                        WHEN business_type IN ('EM.co', 'EM Co', 'EM_co') THEN 'EM.co'
                        WHEN business_type = 'Personal' THEN 'Personal'
                        ELSE 'Personal'
                    END AS normalized_business_type,
                    COUNT(*) as transaction_count,
                    SUM(ABS(chase_amount)) as total_amount,
                    SUM(CASE WHEN (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '') THEN 1 ELSE 0 END) as with_receipts,
                    SUM(CASE WHEN review_status = 'good' THEN 1 ELSE 0 END) as reviewed
                FROM transactions
                WHERE YEAR(chase_date) = %s
                GROUP BY normalized_business_type
            ''', (year,))

        summary = []
        for row in cursor.fetchall():
            summary.append({
                'business_type': row['normalized_business_type'] or 'Unassigned',
                'transaction_count': row['transaction_count'],
                'total_amount': float(row['total_amount'] or 0),
                'with_receipts': row['with_receipts'],
                'reviewed': row['reviewed'],
                'receipt_coverage': (row['with_receipts'] / row['transaction_count'] * 100) if row['transaction_count'] else 0
            })

        return jsonify({
            'ok': True,
            'year': year,
            'summary': summary
        })

    except Exception as e:
        logger.error(f"API business summary error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)


@reports_bp.route("/<report_id>/export/<format_type>", methods=["GET"])
def api_report_export(report_id, format_type):
    """Export a report in the specified format (excel, csv, pdf)."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, _, _ = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get report info
        cursor.execute('''
            SELECT report_id, report_name, business_type, status
            FROM reports WHERE report_id = %s
        ''', (report_id,))
        report = cursor.fetchone()

        if not report:
            return jsonify({'ok': False, 'error': 'Report not found'}), 404

        # Get report items
        cursor.execute('''
            SELECT t._index, t.chase_date, t.chase_description, t.chase_amount,
                   t.chase_category, t.business_type, t.r2_url,
                   t.ai_note, t.review_status
            FROM transactions t
            WHERE t.report_id = %s
            ORDER BY t.chase_date DESC
        ''', (report_id,))
        items = cursor.fetchall()

        if format_type == 'csv':
            import csv
            from io import StringIO
            from flask import Response

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['Date', 'Description', 'Amount', 'Category', 'Business Type', 'AI Note', 'Receipt'])

            for item in items:
                writer.writerow([
                    item['chase_date'],
                    item['chase_description'],
                    abs(float(item['chase_amount'] or 0)),
                    item['chase_category'],
                    item['business_type'],
                    item['ai_note'] or '',
                    'Yes' if item['r2_url'] else 'No'
                ])

            response = Response(output.getvalue(), mimetype='text/csv')
            response.headers['Content-Disposition'] = f'attachment; filename="{report["report_name"] or report_id}.csv"'
            return response

        elif format_type == 'excel':
            try:
                import pandas as pd
                from io import BytesIO
                from flask import send_file

                data = []
                for item in items:
                    data.append({
                        'Date': item['chase_date'],
                        'Description': item['chase_description'],
                        'Amount': abs(float(item['chase_amount'] or 0)),
                        'Category': item['chase_category'],
                        'Business Type': item['business_type'],
                        'AI Note': item['ai_note'] or '',
                        'Receipt': 'Yes' if item['r2_url'] else 'No'
                    })

                df = pd.DataFrame(data)
                output = BytesIO()
                df.to_excel(output, index=False, engine='openpyxl')
                output.seek(0)

                return send_file(
                    output,
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    as_attachment=True,
                    download_name=f'{report["report_name"] or report_id}.xlsx'
                )
            except ImportError:
                return jsonify({'ok': False, 'error': 'Excel export requires pandas and openpyxl'}), 500

        elif format_type == 'pdf':
            try:
                from io import BytesIO
                from flask import send_file
                from reportlab.lib import colors
                from reportlab.lib.pagesizes import letter
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import inch
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

                output = BytesIO()
                doc = SimpleDocTemplate(output, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
                styles = getSampleStyleSheet()
                elements = []

                # Title
                title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, spaceAfter=20)
                elements.append(Paragraph(report['report_name'] or report_id, title_style))

                # Summary
                total = sum(abs(float(item['chase_amount'] or 0)) for item in items)
                summary_style = ParagraphStyle('Summary', parent=styles['Normal'], fontSize=10, textColor=colors.grey)
                elements.append(Paragraph(f"Business: {report['business_type'] or 'All'} | Items: {len(items)} | Total: ${total:,.2f}", summary_style))
                elements.append(Spacer(1, 20))

                # Table data
                table_data = [['Date', 'Description', 'Category', 'Amount', 'Receipt']]
                for item in items:
                    table_data.append([
                        str(item['chase_date'] or ''),
                        (item['chase_description'] or '')[:40],
                        (item['chase_category'] or '')[:15],
                        f"${abs(float(item['chase_amount'] or 0)):,.2f}",
                        'Yes' if item['r2_url'] else 'No'
                    ])

                # Create table
                table = Table(table_data, colWidths=[0.9*inch, 2.8*inch, 1.2*inch, 0.9*inch, 0.6*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#00ff88')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                    ('ALIGN', (4, 0), (4, -1), 'CENTER'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('TOPPADDING', (0, 1), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f8f8')]),
                ]))
                elements.append(table)

                # Footer
                elements.append(Spacer(1, 20))
                footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey)
                elements.append(Paragraph(f"Generated by TallyUps on {datetime.now().strftime('%Y-%m-%d %H:%M')}", footer_style))

                doc.build(elements)
                output.seek(0)

                return send_file(
                    output,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'{report["report_name"] or report_id}.pdf'
                )
            except ImportError:
                return jsonify({'ok': False, 'error': 'PDF export requires reportlab. Install with: pip install reportlab'}), 500

        else:
            return jsonify({'ok': False, 'error': f'Unsupported format: {format_type}'}), 400

    except Exception as e:
        logger.error(f"API report export error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if conn:
            db.return_connection(conn)
