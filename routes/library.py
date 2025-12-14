"""
Receipt Library API Blueprint
==============================
Receipt library management, search, tagging, and collections.

Routes:
- GET  /api/library/receipts - List receipts with filtering
- GET  /api/library/search - Search receipts
- GET  /api/library/receipts/<id> - Get receipt details
- PATCH /api/library/receipts/<id> - Update receipt
- DELETE /api/library/receipts/<id> - Delete receipt
- POST /api/library/upload - Upload new receipt
- GET  /api/library/counts - Get receipt counts
- GET  /api/library/stats - Get library statistics
- GET  /api/library/tags - List all tags
- POST /api/library/tags - Create tag
- GET  /api/library/collections - List collections
- POST /api/library/collections - Create collection

This blueprint manages the receipt library system.
"""

import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, session

from logging_config import get_logger

logger = get_logger("routes.library")

# Create blueprint
library_bp = Blueprint('library', __name__, url_prefix='/api/library')


def get_dependencies():
    """Lazy import dependencies to avoid circular imports."""
    from viewer_server import (
        USE_DATABASE,
        db,
        get_db_connection,
        return_db_connection,
        db_execute,
    )
    return USE_DATABASE, db, get_db_connection, return_db_connection, db_execute


def check_auth():
    """Check if request is authenticated."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key == expected_key:
        return True
    if session.get('authenticated'):
        return True
    return False


@library_bp.route("/receipts", methods=["GET"])
def api_library_receipts():
    """
    List receipts with filtering and pagination.

    Query params:
    - source: 'transaction', 'incoming', or 'all'
    - search: text search
    - merchant: filter by merchant
    - date_from, date_to: date range
    - limit: max results (default 100)
    - offset: pagination offset
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        source = request.args.get('source', 'all')
        search = request.args.get('search', '')
        merchant = request.args.get('merchant', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        limit = min(int(request.args.get('limit', 100)), 500)
        offset = int(request.args.get('offset', 0))

        conn, db_type = get_db_connection()
        receipts = []

        # Query transactions with receipts
        if source in ('transaction', 'all'):
            where_clauses = ["(receipt_url IS NOT NULL AND receipt_url != '')"]
            params = []

            if search:
                where_clauses.append("(chase_description LIKE %s OR ai_note LIKE %s OR ocr_merchant LIKE %s)")
                params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

            if merchant:
                where_clauses.append("(chase_description LIKE %s OR ocr_merchant LIKE %s)")
                params.extend([f'%{merchant}%', f'%{merchant}%'])

            if date_from:
                where_clauses.append("chase_date >= %s")
                params.append(date_from)

            if date_to:
                where_clauses.append("chase_date <= %s")
                params.append(date_to)

            where_sql = " AND ".join(where_clauses)
            params.extend([limit, offset])

            cursor = db_execute(conn, db_type, f'''
                SELECT _index, chase_date, chase_description, chase_amount,
                       receipt_url, r2_url, ai_note, business_type, review_status,
                       ocr_merchant, ocr_amount, ocr_date, ocr_confidence, ocr_verified
                FROM transactions
                WHERE {where_sql}
                ORDER BY chase_date DESC
                LIMIT %s OFFSET %s
            ''', params)

            for row in cursor.fetchall():
                r = dict(row)
                # Map to proper field names for frontend
                # Use OCR data as fallback when transaction data is missing
                merchant_val = r.get('chase_description') or r.get('ocr_merchant') or 'Unknown'
                amount_val = r.get('chase_amount') or r.get('ocr_amount') or 0
                date_val = r.get('chase_date')
                if date_val and hasattr(date_val, 'isoformat'):
                    date_val = date_val.isoformat()
                receipt_url = r.get('r2_url') or r.get('receipt_url') or ''

                receipts.append({
                    'id': f"tx_{r['_index']}",
                    'uuid': f"tx_{r['_index']}",
                    'type': 'transaction',
                    'transaction_id': r['_index'],
                    '_index': r['_index'],
                    'merchant': merchant_val,
                    'merchant_name': merchant_val,
                    'amount': float(amount_val) if amount_val else 0,
                    'date': str(date_val) if date_val else '',
                    'receipt_date': str(date_val) if date_val else '',
                    'receipt_url': receipt_url,
                    'thumbnail_url': receipt_url,  # Use same URL for thumbnail
                    'source': 'transaction',
                    'business_type': r.get('business_type') or 'Personal',
                    'notes': '',
                    'ai_notes': r.get('ai_note') or '',
                    'status': 'matched',
                    'ocr_merchant': r.get('ocr_merchant') or '',
                    'ocr_amount': float(r.get('ocr_amount') or 0) if r.get('ocr_amount') else None,
                    'ocr_confidence': float(r.get('ocr_confidence') or 0) if r.get('ocr_confidence') else 0,
                    'ocr_verified': bool(r.get('ocr_verified')),
                })

        # Query incoming receipts
        if source in ('incoming', 'all'):
            where_clauses = ["receipt_image_url IS NOT NULL AND receipt_image_url != ''"]
            params = []

            if search:
                where_clauses.append("(merchant LIKE %s OR subject LIKE %s OR ocr_merchant LIKE %s)")
                params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

            if merchant:
                where_clauses.append("(merchant LIKE %s OR ocr_merchant LIKE %s)")
                params.extend([f'%{merchant}%', f'%{merchant}%'])

            where_sql = " AND ".join(where_clauses)
            params.extend([limit, offset])

            cursor = db_execute(conn, db_type, f'''
                SELECT id, received_date, receipt_date, merchant, amount, subject, sender,
                       receipt_url, receipt_image_url, thumbnail_url, status, gmail_account,
                       ocr_merchant, ocr_amount, ocr_date, ocr_confidence, ocr_verified,
                       business_type, notes, ai_notes, category
                FROM incoming_receipts
                WHERE {where_sql}
                ORDER BY received_date DESC
                LIMIT %s OFFSET %s
            ''', params)

            for row in cursor.fetchall():
                r = dict(row)
                # Map to proper field names for frontend
                # Use OCR data as fallback when incoming data is missing
                merchant_val = r.get('merchant') or r.get('ocr_merchant') or ''
                if not merchant_val or merchant_val == 'Unknown':
                    # Try to get from sender
                    sender = r.get('sender') or ''
                    if sender:
                        merchant_val = sender.split('<')[0].strip().strip('"')
                    if not merchant_val:
                        merchant_val = 'Unknown'

                amount_val = r.get('amount') or r.get('ocr_amount') or 0
                date_val = r.get('received_date') or r.get('receipt_date')
                if date_val and hasattr(date_val, 'isoformat'):
                    date_val = date_val.isoformat()
                receipt_url = r.get('receipt_image_url') or r.get('receipt_url') or ''
                thumbnail = r.get('thumbnail_url') or receipt_url

                receipts.append({
                    'id': f"inc_{r['id']}",
                    'uuid': f"inc_{r['id']}",
                    'type': 'incoming',
                    'incoming_id': r['id'],
                    'merchant': merchant_val,
                    'merchant_name': merchant_val,
                    'amount': float(amount_val) if amount_val else 0,
                    'date': str(date_val) if date_val else '',
                    'receipt_date': str(date_val) if date_val else '',
                    'receipt_url': receipt_url,
                    'thumbnail_url': thumbnail,
                    'source': 'incoming',
                    'status': r.get('status') or 'pending',
                    'business_type': r.get('business_type') or 'Personal',
                    'notes': r.get('notes') or '',
                    'ai_notes': r.get('ai_notes') or '',
                    'subject': r.get('subject') or '',
                    'sender': r.get('sender') or '',
                    'gmail_account': r.get('gmail_account') or '',
                    'ocr_merchant': r.get('ocr_merchant') or '',
                    'ocr_amount': float(r.get('ocr_amount') or 0) if r.get('ocr_amount') else None,
                    'ocr_confidence': float(r.get('ocr_confidence') or 0) if r.get('ocr_confidence') else 0,
                    'ocr_verified': bool(r.get('ocr_verified')),
                    'category': r.get('category') or '',
                })

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'receipts': receipts,
            'count': len(receipts),
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        logger.error(f"API library receipts error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/search", methods=["GET"])
def api_library_search():
    """
    Search receipts across all sources.

    Query params:
    - q: search query
    - limit: max results
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        query = request.args.get('q', '')
        limit = min(int(request.args.get('limit', 50)), 200)

        if not query:
            return jsonify({'ok': True, 'results': [], 'count': 0})

        conn, db_type = get_db_connection()
        results = []
        search_term = f'%{query}%'

        # Search transactions
        cursor = db_execute(conn, db_type, '''
            SELECT _index, chase_date, chase_description, chase_amount,
                   receipt_url, r2_url, ai_note, business_type,
                   ocr_merchant, ocr_amount, ocr_confidence, ocr_verified
            FROM transactions
            WHERE (chase_description LIKE %s OR ai_note LIKE %s OR ocr_merchant LIKE %s)
            AND receipt_url IS NOT NULL AND receipt_url != ''
            ORDER BY chase_date DESC
            LIMIT %s
        ''', (search_term, search_term, search_term, limit))

        for row in cursor.fetchall():
            r = dict(row)
            merchant_val = r.get('chase_description') or r.get('ocr_merchant') or 'Unknown'
            amount_val = r.get('chase_amount') or r.get('ocr_amount') or 0
            date_val = r.get('chase_date')
            if date_val and hasattr(date_val, 'isoformat'):
                date_val = date_val.isoformat()
            receipt_url = r.get('r2_url') or r.get('receipt_url') or ''

            results.append({
                'id': f"tx_{r['_index']}",
                'uuid': f"tx_{r['_index']}",
                'type': 'transaction',
                'transaction_id': r['_index'],
                '_index': r['_index'],
                'merchant': merchant_val,
                'merchant_name': merchant_val,
                'amount': float(amount_val) if amount_val else 0,
                'date': str(date_val) if date_val else '',
                'receipt_date': str(date_val) if date_val else '',
                'receipt_url': receipt_url,
                'thumbnail_url': receipt_url,
                'source': 'transaction',
                'business_type': r.get('business_type') or 'Personal',
                'ai_notes': r.get('ai_note') or '',
            })

        # Search incoming
        cursor = db_execute(conn, db_type, '''
            SELECT id, received_date, merchant, amount, subject, sender,
                   receipt_image_url, thumbnail_url, status,
                   ocr_merchant, ocr_amount, ocr_confidence, ocr_verified
            FROM incoming_receipts
            WHERE (merchant LIKE %s OR subject LIKE %s OR ocr_merchant LIKE %s)
            AND receipt_image_url IS NOT NULL
            ORDER BY received_date DESC
            LIMIT %s
        ''', (search_term, search_term, search_term, limit))

        for row in cursor.fetchall():
            r = dict(row)
            merchant_val = r.get('merchant') or r.get('ocr_merchant') or ''
            if not merchant_val or merchant_val == 'Unknown':
                sender = r.get('sender') or ''
                if sender:
                    merchant_val = sender.split('<')[0].strip().strip('"')
                if not merchant_val:
                    merchant_val = 'Unknown'
            amount_val = r.get('amount') or r.get('ocr_amount') or 0
            date_val = r.get('received_date')
            if date_val and hasattr(date_val, 'isoformat'):
                date_val = date_val.isoformat()
            receipt_url = r.get('receipt_image_url') or ''
            thumbnail = r.get('thumbnail_url') or receipt_url

            results.append({
                'id': f"inc_{r['id']}",
                'uuid': f"inc_{r['id']}",
                'type': 'incoming',
                'incoming_id': r['id'],
                'merchant': merchant_val,
                'merchant_name': merchant_val,
                'amount': float(amount_val) if amount_val else 0,
                'date': str(date_val) if date_val else '',
                'receipt_date': str(date_val) if date_val else '',
                'receipt_url': receipt_url,
                'thumbnail_url': thumbnail,
                'source': 'incoming',
                'status': r.get('status') or 'pending',
                'subject': r.get('subject') or '',
            })

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'results': results,
            'count': len(results),
            'query': query
        })

    except Exception as e:
        logger.error(f"API library search error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/counts", methods=["GET"])
def api_library_counts():
    """Get receipt counts by source and status."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn, db_type = get_db_connection()

        # Transaction receipts
        cursor = db_execute(conn, db_type, '''
            SELECT COUNT(*) as count FROM transactions
            WHERE receipt_url IS NOT NULL AND receipt_url != ''
        ''')
        transaction_count = cursor.fetchone()['count']

        # Incoming receipts by status
        cursor = db_execute(conn, db_type, '''
            SELECT status, COUNT(*) as count FROM incoming_receipts
            WHERE receipt_image_url IS NOT NULL
            GROUP BY status
        ''')
        incoming_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'transaction_receipts': transaction_count,
            'incoming_receipts': incoming_counts,
            'total': transaction_count + sum(incoming_counts.values())
        })

    except Exception as e:
        logger.error(f"API library counts error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/stats", methods=["GET"])
def api_library_stats():
    """Get library statistics."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn, db_type = get_db_connection()

        # Total receipts
        cursor = db_execute(conn, db_type, '''
            SELECT COUNT(*) as count FROM transactions
            WHERE receipt_url IS NOT NULL AND receipt_url != ''
        ''')
        total_receipts = cursor.fetchone()['count']

        # By business type
        cursor = db_execute(conn, db_type, '''
            SELECT business_type, COUNT(*) as count
            FROM transactions
            WHERE receipt_url IS NOT NULL AND receipt_url != ''
            AND business_type IS NOT NULL AND business_type != ''
            GROUP BY business_type
        ''')
        by_business = {row['business_type']: row['count'] for row in cursor.fetchall()}

        # By month (last 12 months)
        cursor = db_execute(conn, db_type, '''
            SELECT DATE_FORMAT(chase_date, '%Y-%m') as month, COUNT(*) as count
            FROM transactions
            WHERE receipt_url IS NOT NULL AND receipt_url != ''
            AND chase_date >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
            GROUP BY DATE_FORMAT(chase_date, '%Y-%m')
            ORDER BY month
        ''')
        by_month = {row['month']: row['count'] for row in cursor.fetchall()}

        # Top merchants
        cursor = db_execute(conn, db_type, '''
            SELECT chase_description as merchant, COUNT(*) as count
            FROM transactions
            WHERE receipt_url IS NOT NULL AND receipt_url != ''
            GROUP BY chase_description
            ORDER BY count DESC
            LIMIT 10
        ''')
        top_merchants = [{row['merchant']: row['count']} for row in cursor.fetchall()]

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'total_receipts': total_receipts,
            'by_business': by_business,
            'by_month': by_month,
            'top_merchants': top_merchants
        })

    except Exception as e:
        logger.error(f"API library stats error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/tags", methods=["GET"])
def api_library_tags():
    """List all tags."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            SELECT id, name, color, created_at
            FROM receipt_tags
            ORDER BY name
        ''')

        tags = []
        for row in cursor.fetchall():
            t = dict(row)
            if t.get('created_at') and hasattr(t['created_at'], 'isoformat'):
                t['created_at'] = t['created_at'].isoformat()
            tags.append(t)

        return_db_connection(conn)

        return jsonify({'ok': True, 'tags': tags})

    except Exception as e:
        logger.error(f"API library tags error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/tags", methods=["POST"])
def api_library_create_tag():
    """Create a new tag."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        color = data.get('color', '#3b82f6')

        if not name:
            return jsonify({'ok': False, 'error': 'Tag name required'}), 400

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            INSERT INTO receipt_tags (name, color, created_at)
            VALUES (%s, %s, NOW())
        ''', (name, color))

        tag_id = cursor.lastrowid
        conn.commit()

        return_db_connection(conn)

        logger.info(f"Created tag: {name}")

        return jsonify({
            'ok': True,
            'tag': {'id': tag_id, 'name': name, 'color': color}
        })

    except Exception as e:
        logger.error(f"API library create tag error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/collections", methods=["GET"])
def api_library_collections():
    """List all collections."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            SELECT c.id, c.name, c.description, c.created_at,
                   COUNT(ci.id) as item_count
            FROM receipt_collections c
            LEFT JOIN receipt_collection_items ci ON c.id = ci.collection_id
            GROUP BY c.id
            ORDER BY c.name
        ''')

        collections = []
        for row in cursor.fetchall():
            c = dict(row)
            if c.get('created_at') and hasattr(c['created_at'], 'isoformat'):
                c['created_at'] = c['created_at'].isoformat()
            collections.append(c)

        return_db_connection(conn)

        return jsonify({'ok': True, 'collections': collections})

    except Exception as e:
        logger.error(f"API library collections error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/collections", methods=["POST"])
def api_library_create_collection():
    """Create a new collection."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        description = data.get('description', '')

        if not name:
            return jsonify({'ok': False, 'error': 'Collection name required'}), 400

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            INSERT INTO receipt_collections (name, description, created_at)
            VALUES (%s, %s, NOW())
        ''', (name, description))

        collection_id = cursor.lastrowid
        conn.commit()

        return_db_connection(conn)

        logger.info(f"Created collection: {name}")

        return jsonify({
            'ok': True,
            'collection': {'id': collection_id, 'name': name, 'description': description}
        })

    except Exception as e:
        logger.error(f"API library create collection error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500
