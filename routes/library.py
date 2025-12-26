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
import hashlib
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, session, make_response

from logging_config import get_logger

logger = get_logger("routes.library")

# Create blueprint
library_bp = Blueprint('library', __name__, url_prefix='/api/library')


# =============================================================================
# PERFORMANCE: In-memory cache for expensive queries
# =============================================================================

class FastCache:
    """Simple TTL cache for API responses - dramatically improves load times."""

    def __init__(self, default_ttl=60):
        self._cache = {}
        self._default_ttl = default_ttl

    def get(self, key):
        """Get value if not expired."""
        if key in self._cache:
            value, expires_at = self._cache[key]
            if datetime.now().timestamp() < expires_at:
                return value
            del self._cache[key]
        return None

    def set(self, key, value, ttl=None):
        """Set value with TTL in seconds."""
        ttl = ttl or self._default_ttl
        expires_at = datetime.now().timestamp() + ttl
        self._cache[key] = (value, expires_at)

    def clear(self):
        """Clear all cached values."""
        self._cache.clear()

    def invalidate_prefix(self, prefix):
        """Invalidate all keys starting with prefix."""
        keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._cache[k]


# Global cache instance - 5 minute default TTL
_api_cache = FastCache(default_ttl=300)


def cached_response(ttl=300, prefix='library'):
    """
    Decorator to cache API responses.
    Cache key is based on endpoint + query string.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Build cache key from request
            cache_key = f"{prefix}:{request.path}:{request.query_string.decode()}"

            # Check cache first
            cached = _api_cache.get(cache_key)
            if cached is not None:
                response = make_response(jsonify(cached))
                response.headers['X-Cache'] = 'HIT'
                response.headers['Cache-Control'] = f'public, max-age={ttl}'
                return response

            # Execute function
            result = f(*args, **kwargs)

            # Cache successful JSON responses
            if isinstance(result, tuple):
                data, status = result
                if status == 200:
                    _api_cache.set(cache_key, data.get_json(), ttl)
                return result
            else:
                # Flask Response object
                if hasattr(result, 'get_json'):
                    try:
                        json_data = result.get_json()
                        if json_data and json_data.get('ok', True):
                            _api_cache.set(cache_key, json_data, ttl)
                    except:
                        pass

                # Add cache headers
                if hasattr(result, 'headers'):
                    result.headers['X-Cache'] = 'MISS'
                    result.headers['Cache-Control'] = f'public, max-age={ttl}'

                return result

        return wrapper
    return decorator


def invalidate_library_cache():
    """Call this when receipts are modified to clear cache."""
    _api_cache.invalidate_prefix('library:')


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


@library_bp.route("/receipts", methods=["GET"])
@cached_response(ttl=120, prefix='library:receipts')  # 2 minute cache for receipt lists
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
        search = request.args.get('search', '') or request.args.get('q', '')
        merchant = request.args.get('merchant', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        business_type = request.args.get('business_type', '')
        status = request.args.get('status', '')
        amount_min = request.args.get('amount_min', '')
        amount_max = request.args.get('amount_max', '')
        limit = min(int(request.args.get('limit', 100)), 500)
        offset = int(request.args.get('offset', 0))

        conn, db_type = get_db_connection()
        receipts = []

        # Query transactions with receipts
        if source in ('transaction', 'all'):
            # Check both r2_url (cloud) and receipt_file (local) for receipt images
            where_clauses = ["((r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != ''))"]
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

            if business_type:
                # Normalize business type filter to match both formats (spaces and underscores)
                if business_type == 'Down Home':
                    where_clauses.append("business_type IN ('Down Home', 'Down_Home')")
                elif business_type == 'Music City Rodeo':
                    where_clauses.append("business_type IN ('Music City Rodeo', 'Music_City_Rodeo', 'MCR')")
                elif business_type == 'EM.co':
                    where_clauses.append("business_type IN ('EM.co', 'EM Co', 'EM_co')")
                else:
                    where_clauses.append("business_type = %s")
                    params.append(business_type)

            if status:
                where_clauses.append("review_status = %s")
                params.append(status)

            if amount_min:
                where_clauses.append("ABS(chase_amount) >= %s")
                params.append(float(amount_min))

            if amount_max:
                where_clauses.append("ABS(chase_amount) <= %s")
                params.append(float(amount_max))

            where_sql = " AND ".join(where_clauses)
            params.extend([limit, offset])

            cursor = db_execute(conn, db_type, f'''
                SELECT _index, chase_date, chase_description, chase_amount,
                       r2_url, receipt_file, ai_note, business_type, review_status,
                       ai_receipt_merchant, ai_receipt_total, ai_confidence
                FROM transactions
                WHERE {where_sql}
                ORDER BY chase_date DESC
                LIMIT %s OFFSET %s
            ''', params)

            for row in cursor.fetchall():
                r = dict(row)
                # Map to proper field names for frontend
                merchant_val = r.get('chase_description') or r.get('ai_receipt_merchant') or 'Unknown'
                amount_val = r.get('chase_amount') or r.get('ai_receipt_total') or 0
                date_val = r.get('chase_date')
                if date_val and hasattr(date_val, 'isoformat'):
                    date_val = date_val.isoformat()
                # Use r2_url first, then receipt_file as fallback
                # Ensure local paths start with / for proper browser loading
                image_url = r.get('r2_url') or ''
                if not image_url:
                    receipt_file = r.get('receipt_file') or ''
                    if receipt_file:
                        if receipt_file.startswith('http'):
                            image_url = receipt_file
                        elif receipt_file.startswith('/'):
                            image_url = receipt_file
                        elif receipt_file.startswith('receipts/') or receipt_file.startswith('incoming/'):
                            image_url = f'/{receipt_file}'
                        else:
                            image_url = f'/receipts/{receipt_file}'

                # Map review_status to frontend-expected status
                review_status = r.get('review_status') or ''
                if review_status in ('good', 'verified'):
                    display_status = 'verified'
                elif review_status == 'needs_review':
                    display_status = 'needs_review'
                elif review_status == 'mismatch':
                    display_status = 'mismatch'
                else:
                    display_status = 'matched'  # Default for receipts with images

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
                    'receipt_url': image_url,  # Frontend expects this field name
                    'thumbnail_url': image_url,
                    'source': 'transaction',
                    'business_type': r.get('business_type') or 'Personal',
                    'notes': '',
                    'ai_notes': r.get('ai_note') or '',
                    'status': display_status,
                    'review_status': review_status,
                    'ocr_merchant': r.get('ai_receipt_merchant') or '',
                    'ocr_amount': float(r.get('ai_receipt_total') or 0) if r.get('ai_receipt_total') else None,
                    'ocr_confidence': float(r.get('ai_confidence') or 0) if r.get('ai_confidence') else 0,
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
                SELECT id, received_date, receipt_date, merchant, amount, subject, from_email,
                       receipt_url, receipt_image_url, thumbnail_url, status, gmail_account,
                       ocr_merchant, ocr_amount, ocr_date, ocr_confidence,
                       ai_notes, category
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
                    # Try to get from from_email
                    from_email = r.get('from_email') or ''
                    if from_email:
                        # Extract name from "Name <email>" format
                        merchant_val = from_email.split('<')[0].strip().strip('"')
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
                    'business_type': 'Personal',  # Not in production DB
                    'notes': '',
                    'ai_notes': r.get('ai_notes') or '',
                    'subject': r.get('subject') or '',
                    'sender': r.get('from_email') or '',  # from_email is the actual column name
                    'gmail_account': r.get('gmail_account') or '',
                    'ocr_merchant': r.get('ocr_merchant') or '',
                    'ocr_amount': float(r.get('ocr_amount') or 0) if r.get('ocr_amount') else None,
                    'ocr_confidence': float(r.get('ocr_confidence') or 0) if r.get('ocr_confidence') else 0,
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
@cached_response(ttl=60, prefix='library:search')  # 1 minute cache for searches
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
                   r2_url, receipt_file, ai_note, business_type,
                   ai_receipt_merchant, ai_receipt_total, ai_confidence
            FROM transactions
            WHERE (chase_description LIKE %s OR ai_note LIKE %s OR ai_receipt_merchant LIKE %s)
            AND ((r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != ''))
            ORDER BY chase_date DESC
            LIMIT %s
        ''', (search_term, search_term, search_term, limit))

        for row in cursor.fetchall():
            r = dict(row)
            merchant_val = r.get('chase_description') or r.get('ai_receipt_merchant') or 'Unknown'
            amount_val = r.get('chase_amount') or r.get('ai_receipt_total') or 0
            date_val = r.get('chase_date')
            if date_val and hasattr(date_val, 'isoformat'):
                date_val = date_val.isoformat()
            # Use r2_url first, then receipt_file as fallback
            # Ensure local paths start with / for proper browser loading
            image_url = r.get('r2_url') or ''
            if not image_url:
                receipt_file = r.get('receipt_file') or ''
                if receipt_file:
                    if receipt_file.startswith('http'):
                        image_url = receipt_file
                    elif receipt_file.startswith('/'):
                        image_url = receipt_file
                    elif receipt_file.startswith('receipts/') or receipt_file.startswith('incoming/'):
                        image_url = f'/{receipt_file}'
                    else:
                        image_url = f'/receipts/{receipt_file}'

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
                'receipt_url': image_url,
                'thumbnail_url': image_url,
                'source': 'transaction',
                'business_type': r.get('business_type') or 'Personal',
                'ai_notes': r.get('ai_note') or '',
            })

        # Search incoming
        cursor = db_execute(conn, db_type, '''
            SELECT id, received_date, merchant, amount, subject, from_email,
                   receipt_image_url, thumbnail_url, status,
                   ocr_merchant, ocr_amount, ocr_confidence
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
                from_email = r.get('from_email') or ''
                if from_email:
                    merchant_val = from_email.split('<')[0].strip().strip('"')
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
@cached_response(ttl=180, prefix='library:counts')  # 3 minute cache for counts
def api_library_counts():
    """Get receipt counts by source, status, and business type."""
    if not check_auth():
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    USE_DATABASE, db, get_db_connection, return_db_connection, db_execute = get_dependencies()

    if not USE_DATABASE or not db:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503

    conn = None
    try:
        conn, db_type = get_db_connection()

        # Transaction receipts - check both r2_url and receipt_file
        cursor = db_execute(conn, db_type, '''
            SELECT COUNT(*) as count FROM transactions
            WHERE (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '')
        ''')
        transaction_count = cursor.fetchone()['count']

        # By business type - normalize different formats to canonical names
        cursor = db_execute(conn, db_type, '''
            SELECT
                CASE
                    WHEN business_type IN ('Down Home', 'Down_Home') THEN 'Down Home'
                    WHEN business_type IN ('Music City Rodeo', 'Music_City_Rodeo', 'MCR') THEN 'Music City Rodeo'
                    WHEN business_type IN ('EM.co', 'EM Co', 'EM_co') THEN 'EM.co'
                    WHEN business_type = 'Personal' THEN 'Personal'
                    ELSE 'Personal'
                END AS normalized_business_type,
                COUNT(*) as count
            FROM transactions
            WHERE (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '')
            GROUP BY normalized_business_type
        ''')
        business_counts = {}
        for row in cursor.fetchall():
            bt = row['normalized_business_type'] or 'Personal'
            business_counts[bt] = row['count']

        # Incoming receipts by status
        cursor = db_execute(conn, db_type, '''
            SELECT status, COUNT(*) as count FROM incoming_receipts
            WHERE receipt_image_url IS NOT NULL
            GROUP BY status
        ''')
        incoming_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Total incoming
        total_incoming = sum(incoming_counts.values())

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'transaction_receipts': transaction_count,
            'incoming_receipts': incoming_counts,
            'total': transaction_count + total_incoming,
            'counts': {
                'total': transaction_count + total_incoming,
                'all': transaction_count + total_incoming,
                'down_home': business_counts.get('Down Home', 0),
                'mcr': business_counts.get('Music City Rodeo', 0),
                'personal': business_counts.get('Personal', 0),
                'ceo': business_counts.get('CEO', 0),
                'favorites': 0,
                'recent': transaction_count,
                'needs_review': incoming_counts.get('needs_review', 0),
                'verified': incoming_counts.get('verified', 0) + incoming_counts.get('matched', 0),
                'matched': transaction_count,
                'processing': incoming_counts.get('processing', 0),
                'duplicates': incoming_counts.get('duplicate', 0),
                'gmail': total_incoming,
                'scanner': 0,
                'upload': 0
            }
        })

    except Exception as e:
        logger.error(f"API library counts error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/stats", methods=["GET"])
@cached_response(ttl=180, prefix='library:stats')  # 3 minute cache for stats
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

        # Total receipts - check both r2_url and receipt_file
        cursor = db_execute(conn, db_type, '''
            SELECT COUNT(*) as count FROM transactions
            WHERE (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '')
        ''')
        total_receipts = cursor.fetchone()['count']

        # By business type - normalize different formats to canonical names
        cursor = db_execute(conn, db_type, '''
            SELECT
                CASE
                    WHEN business_type IN ('Down Home', 'Down_Home') THEN 'Down Home'
                    WHEN business_type IN ('Music City Rodeo', 'Music_City_Rodeo', 'MCR') THEN 'Music City Rodeo'
                    WHEN business_type IN ('EM.co', 'EM Co', 'EM_co') THEN 'EM.co'
                    WHEN business_type = 'Personal' THEN 'Personal'
                    ELSE 'Personal'
                END AS normalized_business_type,
                COUNT(*) as count
            FROM transactions
            WHERE ((r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != ''))
            AND business_type IS NOT NULL AND business_type != ''
            GROUP BY normalized_business_type
        ''')
        by_business = {row['normalized_business_type']: row['count'] for row in cursor.fetchall()}

        # By month (last 12 months)
        cursor = db_execute(conn, db_type, '''
            SELECT DATE_FORMAT(chase_date, '%Y-%m') as month, COUNT(*) as count
            FROM transactions
            WHERE ((r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != ''))
            AND chase_date >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
            GROUP BY DATE_FORMAT(chase_date, '%Y-%m')
            ORDER BY month
        ''')
        by_month = {row['month']: row['count'] for row in cursor.fetchall()}

        # Top merchants
        cursor = db_execute(conn, db_type, '''
            SELECT chase_description as merchant, COUNT(*) as count
            FROM transactions
            WHERE (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '')
            GROUP BY chase_description
            ORDER BY count DESC
            LIMIT 10
        ''')
        top_merchants = [{row['merchant']: row['count']} for row in cursor.fetchall()]

        # Incoming receipts count
        cursor = db_execute(conn, db_type, '''
            SELECT COUNT(*) as count FROM incoming_receipts
            WHERE receipt_image_url IS NOT NULL
        ''')
        incoming_count = cursor.fetchone()['count']

        # Count by review_status for verified badges
        cursor = db_execute(conn, db_type, '''
            SELECT review_status, COUNT(*) as count
            FROM transactions
            WHERE (r2_url IS NOT NULL AND r2_url != '') OR (receipt_file IS NOT NULL AND receipt_file != '')
            GROUP BY review_status
        ''')
        by_status = {}
        for row in cursor.fetchall():
            status = row['review_status'] or 'pending'
            by_status[status] = row['count']

        # Calculate verified count (good or verified status)
        verified_count = by_status.get('good', 0) + by_status.get('verified', 0)
        needs_review_count = by_status.get('needs_review', 0)

        return_db_connection(conn)

        # Build counts object for frontend
        total = total_receipts + incoming_count
        counts = {
            'total': total,
            'all': total,
            'down_home': by_business.get('Down Home', 0),
            'mcr': by_business.get('Music City Rodeo', 0),
            'personal': by_business.get('Personal', 0),
            'ceo': by_business.get('CEO', 0),
            'favorites': 0,
            'recent': total_receipts,
            'needs_review': needs_review_count,
            'verified': verified_count,
            'matched': total_receipts - needs_review_count,
            'processing': 0,
            'duplicates': 0,
            'gmail': incoming_count,
            'scanner': 0,
            'upload': 0
        }

        return jsonify({
            'ok': True,
            'total_receipts': total_receipts,
            'by_business': by_business,
            'by_month': by_month,
            'top_merchants': top_merchants,
            'counts': counts
        })

    except Exception as e:
        logger.error(f"API library stats error: {e}")
        if conn:
            return_db_connection(conn)
        return jsonify({'ok': False, 'error': str(e)}), 500


@library_bp.route("/tags", methods=["GET"])
@cached_response(ttl=300, prefix='library:tags')  # 5 minute cache for tags
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
@cached_response(ttl=300, prefix='library:collections')  # 5 minute cache for collections
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
