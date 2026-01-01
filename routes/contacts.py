"""
================================================================================
Contacts/ATLAS API Routes
================================================================================
Flask Blueprint for Contact Management and Relationship Intelligence.

ENDPOINTS:
----------
Contact Management:
    GET  /api/contacts                 - List all contacts
    POST /api/contacts                 - Create contact
    GET  /api/contacts/<id>            - Get contact details
    PUT  /api/contacts/<id>            - Update contact
    DELETE /api/contacts/<id>          - Delete contact

Sync & Conflicts:
    GET  /api/contacts/sync/status     - Get sync status for all sources
    POST /api/contacts/sync            - Trigger sync from sources
    GET  /api/contacts/sync/conflicts  - Get pending conflicts
    POST /api/contacts/sync/conflicts/<id>/resolve - Resolve a conflict
    POST /api/contacts/merge           - Merge duplicate contacts

Relationship Intelligence:
    GET  /api/contacts/<id>/relationship - Get relationship health score
    GET  /api/contacts/relationship-graph - Get network graph data
    GET  /api/contacts/nudges          - Get proactive engagement suggestions

================================================================================
"""

import os
import logging
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session

from db_user_scope import get_current_user_id, USER_SCOPING_ENABLED

# Create blueprint
contacts_bp = Blueprint('contacts', __name__, url_prefix='/api/contacts')

# Logger
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def get_db_helpers():
    """Lazy import database helpers"""
    from viewer_server import get_db_connection, return_db_connection, db, USE_DATABASE
    return get_db_connection, return_db_connection, db, USE_DATABASE


def check_auth():
    """
    Check if request is authenticated.
    Supports JWT tokens (preferred), session auth, and admin_key.
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

    # Check admin API key
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key and expected_key and secrets.compare_digest(str(admin_key), str(expected_key)):
        return True

    # Check session auth
    if session.get('authenticated'):
        return True

    return False


# =============================================================================
# CONTACT CRUD OPERATIONS
# =============================================================================

@contacts_bp.route('', methods=['GET'])
def list_contacts():
    """
    List all contacts with optional filtering.

    Query Params:
        search: Search term for name/email
        source: Filter by source (google, apple, linkedin)
        limit: Max results (default 50)
        offset: Pagination offset

    Response:
        {
            "success": true,
            "contacts": [...],
            "total": 500
        }
    """
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    try:
        search = request.args.get('search')
        source = request.args.get('source')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        # USER SCOPING: Get user_id for filtering
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        get_db_connection, return_db_connection, _, _ = get_db_helpers()
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        try:
            query = """
                SELECT id, name, email, phone, company, job_title,
                       source, last_touch_date, relationship_score,
                       created_at, updated_at
                FROM contacts
                WHERE 1=1
            """
            params = []

            # USER SCOPING: Filter by user_id
            if USER_SCOPING_ENABLED and user_id:
                query += " AND user_id = %s"
                params.append(user_id)

            if search:
                query += " AND (name LIKE %s OR email LIKE %s OR company LIKE %s)"
                search_term = f"%{search}%"
                params.extend([search_term, search_term, search_term])

            if source:
                query += " AND source = %s"
                params.append(source)

            query += " ORDER BY name LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cursor.execute(query, params)

            contacts = []
            for row in cursor.fetchall():
                # Handle both DictCursor (dict) and regular cursor (tuple) results
                if isinstance(row, dict):
                    contacts.append({
                        'id': row.get('id'),
                        'name': row.get('name'),
                        'email': row.get('email'),
                        'phone': row.get('phone'),
                        'company': row.get('company'),
                        'title': row.get('job_title'),
                        'source': row.get('source'),
                        'last_touch_date': str(row.get('last_touch_date')) if row.get('last_touch_date') else None,
                        'relationship_score': float(row.get('relationship_score')) if row.get('relationship_score') else None,
                        'created_at': str(row.get('created_at')),
                        'updated_at': str(row.get('updated_at'))
                    })
                else:
                    contacts.append({
                        'id': row[0],
                        'name': row[1],
                        'email': row[2],
                        'phone': row[3],
                        'company': row[4],
                        'title': row[5],
                        'source': row[6],
                        'last_touch_date': str(row[7]) if row[7] else None,
                        'relationship_score': float(row[8]) if row[8] else None,
                        'created_at': str(row[9]),
                        'updated_at': str(row[10])
                    })

            # Get total (scoped by user)
            if USER_SCOPING_ENABLED and user_id:
                cursor.execute("SELECT COUNT(*) as total FROM contacts WHERE user_id = %s", (user_id,))
            else:
                cursor.execute("SELECT COUNT(*) as total FROM contacts")
            count_row = cursor.fetchone()
            total = count_row.get('total', 0) if isinstance(count_row, dict) else count_row[0]
        finally:
            cursor.close()
            return_db_connection(conn)

        return jsonify({
            'success': True,
            'contacts': contacts,
            'total': total,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        logger.error(f"List contacts error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('', methods=['POST'])
def create_contact():
    """
    Create a new contact.

    Request Body:
        {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1234567890",
            "company": "Acme Inc",
            "title": "CEO",
            "notes": "Met at conference"
        }
    """
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}

        if not data.get('name') and not data.get('email'):
            return jsonify({
                'success': False,
                'error': 'Name or email is required'
            }), 400

        # USER SCOPING: Get user_id for new contact
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            if USER_SCOPING_ENABLED and user_id:
                cursor.execute("""
                    INSERT INTO contacts (name, email, phone, company, job_title, notes, source, user_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'manual', %s, NOW(), NOW())
                """, (
                    data.get('name'),
                    data.get('email'),
                    data.get('phone'),
                    data.get('company'),
                    data.get('title'),
                    data.get('notes'),
                    user_id
                ))
            else:
                cursor.execute("""
                    INSERT INTO contacts (name, email, phone, company, job_title, notes, source, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'manual', NOW(), NOW())
                """, (
                    data.get('name'),
                    data.get('email'),
                    data.get('phone'),
                    data.get('company'),
                    data.get('title'),
                    data.get('notes')
                ))

            contact_id = cursor.lastrowid

        return jsonify({
            'success': True,
            'contact_id': contact_id
        }), 201

    except Exception as e:
        logger.error(f"Create contact error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/<int:contact_id>', methods=['GET'])
def get_contact(contact_id):
    """Get detailed contact information."""
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    try:
        # USER SCOPING: Get user_id for filtering
        user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # USER SCOPING: Add user_id filter to query
            if USER_SCOPING_ENABLED and user_id:
                cursor.execute("""
                    SELECT id, name, email, phone, company, job_title, notes,
                           source, last_touch_date, relationship_score,
                           tags, birthday, linkedin_url, twitter_url,
                           created_at, updated_at
                    FROM contacts WHERE id = %s AND user_id = %s
                """, (contact_id, user_id))
            else:
                cursor.execute("""
                    SELECT id, name, email, phone, company, job_title, notes,
                           source, last_touch_date, relationship_score,
                       interaction_count, created_at, updated_at
                FROM contacts
                WHERE id = %s
            """, (contact_id,))

            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Contact not found'}), 404

            contact = {
                'id': row[0],
                'name': row[1],
                'email': row[2],
                'phone': row[3],
                'company': row[4],
                'title': row[5],
                'notes': row[6],
                'source': row[7],
                'last_touch_date': str(row[8]) if row[8] else None,
                'relationship_score': float(row[9]) if row[9] else None,
                'interaction_count': row[10],
                'created_at': str(row[11]),
                'updated_at': str(row[12])
            }

        return jsonify({
            'success': True,
            'contact': contact
        })

    except Exception as e:
        logger.error(f"Get contact error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/<int:contact_id>', methods=['PUT'])
def update_contact(contact_id):
    """Update a contact."""
    # SECURITY: Authentication required
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            updates = []
            params = []

            for field in ['name', 'email', 'phone', 'company', 'title', 'notes']:
                if field in data:
                    updates.append(f"{field} = %s")
                    params.append(data[field])

            if not updates:
                return jsonify({'success': False, 'error': 'No updates provided'}), 400

            updates.append("updated_at = NOW()")
            params.append(contact_id)

            # SECURITY: User scoping - only update user's own contacts
            if USER_SCOPING_ENABLED:
                user_id = get_current_user_id()
                params.append(user_id)
                cursor.execute(f"""
                    UPDATE contacts SET {', '.join(updates)} WHERE id = %s AND user_id = %s
                """, params)
            else:
                cursor.execute(f"""
                    UPDATE contacts SET {', '.join(updates)} WHERE id = %s
                """, params)

        return jsonify({
            'success': True,
            'message': 'Contact updated'
        })

    except Exception as e:
        logger.error(f"Update contact error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/<int:contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    """Delete a contact."""
    # SECURITY: Authentication required
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # SECURITY: User scoping - only delete user's own contacts
            if USER_SCOPING_ENABLED:
                user_id = get_current_user_id()
                cursor.execute("DELETE FROM contacts WHERE id = %s AND user_id = %s", (contact_id, user_id))
            else:
                cursor.execute("DELETE FROM contacts WHERE id = %s", (contact_id,))

        return jsonify({
            'success': True,
            'message': 'Contact deleted'
        })

    except Exception as e:
        logger.error(f"Delete contact error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# SYNC & CONFLICT RESOLUTION
# =============================================================================

@contacts_bp.route('/sync/status', methods=['GET'])
def get_sync_status():
    """
    Get sync status for all contact sources.

    Response:
        {
            "success": true,
            "sources": [
                {
                    "name": "google",
                    "connected": true,
                    "last_sync": "2024-12-20T10:30:00Z",
                    "contacts_synced": 250,
                    "pending_conflicts": 3
                },
                ...
            ]
        }
    """
    try:
        sources = [
            {'name': 'google', 'display_name': 'Google Contacts'},
            {'name': 'apple', 'display_name': 'Apple Contacts'},
            {'name': 'linkedin', 'display_name': 'LinkedIn'},
            {'name': 'carddav', 'display_name': 'CardDAV'}
        ]

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            result = []
            for source in sources:
                # Count contacts from this source
                cursor.execute("""
                    SELECT COUNT(*), MAX(updated_at)
                    FROM contacts WHERE source = %s
                """, (source['name'],))

                row = cursor.fetchone()

                # Count pending conflicts
                cursor.execute("""
                    SELECT COUNT(*) FROM contact_conflicts
                    WHERE source = %s AND resolved = FALSE
                """, (source['name'],))

                conflicts = cursor.fetchone()[0] if cursor.fetchone() else 0

                result.append({
                    'name': source['name'],
                    'display_name': source['display_name'],
                    'connected': row[0] > 0,
                    'last_sync': str(row[1]) if row and row[1] else None,
                    'contacts_synced': row[0] if row else 0,
                    'pending_conflicts': conflicts
                })

        return jsonify({
            'success': True,
            'sources': result
        })

    except Exception as e:
        logger.error(f"Sync status error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/sync', methods=['POST'])
def trigger_sync():
    """
    Trigger contact sync from specified sources.

    Request Body:
        {
            "sources": ["google", "apple"],  // Optional, defaults to all
            "full_sync": false  // Full sync vs incremental
        }
    """
    try:
        data = request.get_json() or {}
        sources = data.get('sources', ['google', 'apple', 'linkedin'])
        full_sync = data.get('full_sync', False)

        # For now, return success - actual sync would be async
        return jsonify({
            'success': True,
            'message': 'Sync initiated',
            'sources': sources,
            'full_sync': full_sync
        })

    except Exception as e:
        logger.error(f"Trigger sync error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/sync/conflicts', methods=['GET'])
def list_conflicts():
    """
    Get pending sync conflicts.

    Response:
        {
            "success": true,
            "conflicts": [
                {
                    "id": 1,
                    "contact_id": 123,
                    "source": "google",
                    "field": "phone",
                    "local_value": "+1234567890",
                    "remote_value": "+0987654321",
                    "detected_at": "2024-12-20T10:30:00Z"
                },
                ...
            ]
        }
    """
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cc.id, cc.contact_id, cc.source, cc.field_name,
                       cc.local_value, cc.remote_value, cc.detected_at,
                       c.name, c.email
                FROM contact_conflicts cc
                JOIN contacts c ON cc.contact_id = c.id
                WHERE cc.resolved = FALSE
                ORDER BY cc.detected_at DESC
            """)

            conflicts = []
            for row in cursor.fetchall():
                conflicts.append({
                    'id': row[0],
                    'contact_id': row[1],
                    'source': row[2],
                    'field': row[3],
                    'local_value': row[4],
                    'remote_value': row[5],
                    'detected_at': str(row[6]),
                    'contact_name': row[7],
                    'contact_email': row[8]
                })

        return jsonify({
            'success': True,
            'conflicts': conflicts,
            'count': len(conflicts)
        })

    except Exception as e:
        logger.error(f"List conflicts error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/sync/conflicts/<int:conflict_id>/resolve', methods=['POST'])
def resolve_conflict(conflict_id):
    """
    Resolve a sync conflict.

    Request Body:
        {
            "resolution": "local|remote|manual",
            "manual_value": "..."  // Required if resolution is "manual"
        }
    """
    try:
        data = request.get_json() or {}
        resolution = data.get('resolution', 'local')
        manual_value = data.get('manual_value')

        if resolution not in ['local', 'remote', 'manual']:
            return jsonify({
                'success': False,
                'error': 'Invalid resolution type'
            }), 400

        if resolution == 'manual' and not manual_value:
            return jsonify({
                'success': False,
                'error': 'manual_value required for manual resolution'
            }), 400

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get conflict details
            cursor.execute("""
                SELECT contact_id, field_name, local_value, remote_value
                FROM contact_conflicts WHERE id = %s
            """, (conflict_id,))

            conflict = cursor.fetchone()
            if not conflict:
                return jsonify({'success': False, 'error': 'Conflict not found'}), 404

            contact_id, field, local_val, remote_val = conflict

            # Determine final value
            if resolution == 'local':
                final_value = local_val
            elif resolution == 'remote':
                final_value = remote_val
            else:
                final_value = manual_value

            # Update contact
            cursor.execute(f"""
                UPDATE contacts SET {field} = %s, updated_at = NOW() WHERE id = %s
            """, (final_value, contact_id))

            # Mark conflict as resolved
            cursor.execute("""
                UPDATE contact_conflicts
                SET resolved = TRUE, resolution = %s, resolved_value = %s, resolved_at = NOW()
                WHERE id = %s
            """, (resolution, final_value, conflict_id))

        return jsonify({
            'success': True,
            'message': 'Conflict resolved',
            'resolution': resolution,
            'final_value': final_value
        })

    except Exception as e:
        logger.error(f"Resolve conflict error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/merge', methods=['POST'])
def merge_contacts():
    """
    Merge duplicate contacts.

    Request Body:
        {
            "primary_id": 123,  // Contact to keep
            "merge_ids": [124, 125],  // Contacts to merge into primary
            "merge_strategy": "keep_primary|combine"
        }
    """
    try:
        data = request.get_json() or {}
        primary_id = data.get('primary_id')
        merge_ids = data.get('merge_ids', [])
        strategy = data.get('merge_strategy', 'keep_primary')

        if not primary_id or not merge_ids:
            return jsonify({
                'success': False,
                'error': 'primary_id and merge_ids are required'
            }), 400

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get primary contact
            cursor.execute("SELECT * FROM contacts WHERE id = %s", (primary_id,))
            primary = cursor.fetchone()

            if not primary:
                return jsonify({'success': False, 'error': 'Primary contact not found'}), 404

            if strategy == 'combine':
                # Combine data from merge contacts
                for merge_id in merge_ids:
                    cursor.execute("SELECT phone, company, job_title, notes FROM contacts WHERE id = %s", (merge_id,))
                    merge_data = cursor.fetchone()

                    if merge_data:
                        # Fill in missing fields from merged contact
                        updates = []
                        params = []

                        if merge_data[0] and not primary[3]:  # phone
                            updates.append("phone = %s")
                            params.append(merge_data[0])

                        if merge_data[1] and not primary[4]:  # company
                            updates.append("company = %s")
                            params.append(merge_data[1])

                        if merge_data[2] and not primary[5]:  # title
                            updates.append("job_title = %s")
                            params.append(merge_data[2])

                        if updates:
                            params.append(primary_id)
                            cursor.execute(f"""
                                UPDATE contacts SET {', '.join(updates)} WHERE id = %s
                            """, params)

            # Delete merged contacts
            placeholders = ','.join(['%s'] * len(merge_ids))
            cursor.execute(f"DELETE FROM contacts WHERE id IN ({placeholders})", merge_ids)

            # Log the merge
            cursor.execute("""
                INSERT INTO contact_merge_log (primary_id, merged_ids, strategy, merged_at)
                VALUES (%s, %s, %s, NOW())
            """, (primary_id, ','.join(map(str, merge_ids)), strategy))

        return jsonify({
            'success': True,
            'message': f'Merged {len(merge_ids)} contacts into {primary_id}',
            'primary_id': primary_id,
            'merged_count': len(merge_ids)
        })

    except Exception as e:
        logger.error(f"Merge contacts error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# RELATIONSHIP INTELLIGENCE
# =============================================================================

@contacts_bp.route('/<int:contact_id>/relationship', methods=['GET'])
def get_relationship_health(contact_id):
    """
    Get relationship health score and details for a contact.

    Response:
        {
            "success": true,
            "relationship": {
                "score": 0.85,
                "trend": "improving",
                "last_touch_date": "2024-12-20",
                "interaction_count": 15,
                "channels": {"email": 10, "meeting": 3, "call": 2},
                "suggestions": ["Schedule follow-up call"]
            }
        }
    """
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    # USER SCOPING: Get user_id for filtering
    user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get contact relationship data (with user isolation)
            if user_id:
                cursor.execute("""
                    SELECT relationship_score, last_touch_date, interaction_count
                    FROM contacts WHERE id = %s AND user_id = %s
                """, (contact_id, user_id))
            else:
                cursor.execute("""
                    SELECT relationship_score, last_touch_date, interaction_count
                    FROM contacts WHERE id = %s
                """, (contact_id,))

            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Contact not found'}), 404

            score, last_touch_date, count = row

            # Determine trend based on recent activity
            days_since = (datetime.now() - last_touch_date).days if last_touch_date else 999
            if days_since < 7:
                trend = 'strong'
            elif days_since < 30:
                trend = 'stable'
            elif days_since < 90:
                trend = 'cooling'
            else:
                trend = 'dormant'

            # Generate suggestions
            suggestions = []
            if days_since > 30:
                suggestions.append('Schedule a check-in call')
            if days_since > 90:
                suggestions.append('Send a reconnection email')

            relationship = {
                'score': float(score) if score else 0.5,
                'trend': trend,
                'last_touch_date': str(last_touch_date) if last_touch_date else None,
                'days_since_contact': days_since,
                'interaction_count': count or 0,
                'suggestions': suggestions
            }

        return jsonify({
            'success': True,
            'relationship': relationship
        })

    except Exception as e:
        logger.error(f"Get relationship error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/relationship-graph', methods=['GET'])
def get_relationship_graph():
    """
    Get network graph data for contact visualization.

    Response:
        {
            "success": true,
            "nodes": [...],
            "edges": [...],
            "clusters": [...]
        }
    """
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    # USER SCOPING: Get user_id for filtering
    user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get contacts as nodes (with user isolation)
            if user_id:
                cursor.execute("""
                    SELECT id, name, company, relationship_score
                    FROM contacts
                    WHERE user_id = %s
                    ORDER BY relationship_score DESC
                    LIMIT 100
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT id, name, company, relationship_score
                    FROM contacts
                    ORDER BY relationship_score DESC
                    LIMIT 100
                """)

            nodes = []
            for row in cursor.fetchall():
                nodes.append({
                    'id': row[0],
                    'label': row[1],
                    'group': row[2] or 'unknown',
                    'value': float(row[3]) if row[3] else 0.5
                })

            # Get connections (same company = connected)
            edges = []
            companies = {}
            for node in nodes:
                company = node['group']
                if company not in companies:
                    companies[company] = []
                companies[company].append(node['id'])

            for company, contact_ids in companies.items():
                if len(contact_ids) > 1:
                    for i, id1 in enumerate(contact_ids):
                        for id2 in contact_ids[i+1:]:
                            edges.append({
                                'from': id1,
                                'to': id2,
                                'label': company
                            })

        return jsonify({
            'success': True,
            'nodes': nodes,
            'edges': edges,
            'clusters': list(companies.keys())
        })

    except Exception as e:
        logger.error(f"Relationship graph error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/nudges', methods=['GET'])
def get_nudges():
    """
    Get proactive engagement suggestions.

    Response:
        {
            "success": true,
            "nudges": [
                {
                    "contact_id": 123,
                    "contact_name": "John Doe",
                    "reason": "No contact in 45 days",
                    "suggested_action": "Send check-in email",
                    "priority": "high"
                },
                ...
            ]
        }
    """
    # SECURITY: Require authentication
    if not check_auth():
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    # USER SCOPING: Get user_id for filtering
    user_id = get_current_user_id() if USER_SCOPING_ENABLED else None

    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Find contacts that need attention (with user isolation)
            if user_id:
                cursor.execute("""
                    SELECT id, name, email, last_touch_date, relationship_score
                    FROM contacts
                    WHERE user_id = %s
                      AND (last_touch_date < DATE_SUB(NOW(), INTERVAL 30 DAY)
                           OR last_touch_date IS NULL)
                    ORDER BY relationship_score DESC
                    LIMIT 20
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT id, name, email, last_touch_date, relationship_score
                    FROM contacts
                    WHERE last_touch_date < DATE_SUB(NOW(), INTERVAL 30 DAY)
                       OR last_touch_date IS NULL
                    ORDER BY relationship_score DESC
                    LIMIT 20
                """)

            nudges = []
            for row in cursor.fetchall():
                contact_id, name, email, last_int, score = row

                if last_int:
                    days = (datetime.now() - last_int).days
                    reason = f"No contact in {days} days"
                    priority = 'high' if days > 60 else 'medium'
                else:
                    reason = "Never contacted"
                    priority = 'low'

                nudges.append({
                    'contact_id': contact_id,
                    'contact_name': name,
                    'contact_email': email,
                    'reason': reason,
                    'suggested_action': 'Send check-in email',
                    'priority': priority
                })

        return jsonify({
            'success': True,
            'nudges': nudges,
            'count': len(nudges)
        })

    except Exception as e:
        logger.error(f"Get nudges error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# CONTACT INTERACTIONS
# =============================================================================

@contacts_bp.route('/<int:contact_id>/interactions', methods=['GET'])
def get_contact_interactions(contact_id):
    """
    Get all interactions for a contact (emails, transactions, meetings).

    Query Params:
        type: Filter by type (email, expense, meeting, call)
        limit: Max results (default 50)

    Response:
        {
            "success": true,
            "contact": { ... },
            "interactions": [...],
            "summary": { "emails": 10, "expenses": 5, "total_spent": 1500.00 }
        }
    """
    try:
        interaction_type = request.args.get('type')
        limit = int(request.args.get('limit', 50))

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get contact
            cursor.execute("""
                SELECT id, name, email, phone, company, job_title,
                       relationship_score, last_touch_date, interaction_count
                FROM contacts WHERE id = %s
            """, (contact_id,))

            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Contact not found'}), 404

            contact = {
                'id': row[0],
                'name': row[1],
                'email': row[2],
                'phone': row[3],
                'company': row[4],
                'title': row[5],
                'relationship_score': float(row[6]) if row[6] else 50,
                'last_touch_date': str(row[7]) if row[7] else None,
                'interaction_count': row[8] or 0
            }

            # Get interactions
            query = """
                SELECT id, interaction_type, interaction_date, subject, notes,
                       source_type, amount, transaction_id
                FROM contact_interactions
                WHERE contact_id = %s
            """
            params = [contact_id]

            if interaction_type:
                query += " AND interaction_type = %s"
                params.append(interaction_type)

            query += " ORDER BY interaction_date DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)

            interactions = []
            for row in cursor.fetchall():
                interactions.append({
                    'id': row[0],
                    'type': row[1],
                    'date': str(row[2]),
                    'subject': row[3],
                    'notes': row[4],
                    'source': row[5],
                    'amount': float(row[6]) if row[6] else None,
                    'transaction_id': row[7]
                })

            # Get summary stats
            cursor.execute("""
                SELECT interaction_type, COUNT(*), SUM(COALESCE(amount, 0))
                FROM contact_interactions
                WHERE contact_id = %s
                GROUP BY interaction_type
            """, (contact_id,))

            summary = {'total_interactions': 0, 'total_spent': 0.0}
            for row in cursor.fetchall():
                summary[row[0] + 's'] = row[1]
                summary['total_interactions'] += row[1]
                if row[2]:
                    summary['total_spent'] += float(row[2])

        return jsonify({
            'success': True,
            'contact': contact,
            'interactions': interactions,
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Get interactions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/<int:contact_id>/interactions', methods=['POST'])
def add_contact_interaction(contact_id):
    """
    Add a new interaction for a contact.

    Request Body:
        {
            "type": "email|call|meeting|expense|note",
            "subject": "Discussion about project",
            "notes": "Detailed notes...",
            "amount": 150.00  // For expense type
        }
    """
    try:
        data = request.get_json() or {}

        if not data.get('type'):
            return jsonify({
                'success': False,
                'error': 'Interaction type is required'
            }), 400

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Verify contact exists
            cursor.execute("SELECT id FROM contacts WHERE id = %s", (contact_id,))
            if not cursor.fetchone():
                return jsonify({'success': False, 'error': 'Contact not found'}), 404

            # Add interaction
            cursor.execute("""
                INSERT INTO contact_interactions
                (contact_id, interaction_type, interaction_date, subject, notes, amount, source_type)
                VALUES (%s, %s, NOW(), %s, %s, %s, 'manual')
            """, (
                contact_id,
                data['type'],
                data.get('subject'),
                data.get('notes'),
                data.get('amount')
            ))

            interaction_id = cursor.lastrowid

            # Update contact last interaction
            cursor.execute("""
                UPDATE contacts
                SET last_touch_date = NOW(),
                    interaction_count = COALESCE(interaction_count, 0) + 1,
                    updated_at = NOW()
                WHERE id = %s
            """, (contact_id,))

        return jsonify({
            'success': True,
            'interaction_id': interaction_id
        }), 201

    except Exception as e:
        logger.error(f"Add interaction error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@contacts_bp.route('/<int:contact_id>/transactions', methods=['GET'])
def get_contact_transactions(contact_id):
    """
    Get transactions associated with a contact.

    This finds transactions where the merchant matches the contact's company
    or email domain.
    """
    try:
        limit = int(request.args.get('limit', 20))

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get contact
            cursor.execute("""
                SELECT name, email, company FROM contacts WHERE id = %s
            """, (contact_id,))

            contact = cursor.fetchone()
            if not contact:
                return jsonify({'success': False, 'error': 'Contact not found'}), 404

            name, email, company = contact

            # Build search terms
            search_terms = []
            if company:
                search_terms.append(company)
            if email:
                domain = email.split('@')[-1].split('.')[0]
                search_terms.append(domain)
            if name:
                search_terms.append(name.split()[0])

            if not search_terms:
                return jsonify({
                    'success': True,
                    'transactions': [],
                    'message': 'No searchable terms for this contact'
                })

            # Search transactions
            conditions = ' OR '.join(['chase_description LIKE %s'] * len(search_terms))
            params = [f'%{term}%' for term in search_terms]
            params.append(limit)

            cursor.execute(f"""
                SELECT _index, chase_date, chase_description, chase_amount,
                       business_type, receipt_file
                FROM transactions
                WHERE {conditions}
                ORDER BY chase_date DESC
                LIMIT %s
            """, params)

            transactions = []
            for row in cursor.fetchall():
                transactions.append({
                    'id': row[0],
                    'date': str(row[1]),
                    'description': row[2],
                    'amount': float(row[3]) if row[3] else None,
                    'business_type': row[4],
                    'has_receipt': bool(row[5])
                })

        return jsonify({
            'success': True,
            'contact_id': contact_id,
            'search_terms': search_terms,
            'transactions': transactions,
            'count': len(transactions)
        })

    except Exception as e:
        logger.error(f"Get contact transactions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def register_contacts_routes(app):
    """Register contacts routes with the Flask app."""
    app.register_blueprint(contacts_bp)
    logger.info("Contacts routes registered at /api/contacts/*")
