"""
Business Types API Routes

Per-user custom business type management for multi-tenant support.
Each user can have their own business categories (e.g., Personal, Business, Down Home, etc.)
"""

import logging
from flask import Blueprint, request, jsonify, g

from db_mysql import get_mysql_db, db_execute
from db_user_scope import get_current_user_id

logger = logging.getLogger(__name__)

business_types_bp = Blueprint('business_types', __name__, url_prefix='/api/business-types')


@business_types_bp.route('', methods=['GET'])
def get_business_types():
    """
    Get all business types for the current user.

    Returns:
        {
            "success": true,
            "business_types": [
                {
                    "id": 1,
                    "name": "Personal",
                    "display_name": "Personal",
                    "color": "#00FF88",
                    "icon": "person.fill",
                    "is_default": true,
                    "sort_order": 1
                },
                ...
            ]
        }
    """
    try:
        user_id = get_current_user_id()
        db = get_mysql_db()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, display_name, color, icon, is_default, sort_order
                FROM user_business_types
                WHERE user_id = %s AND is_active = TRUE
                ORDER BY sort_order ASC, display_name ASC
            """, (user_id,))

            business_types = []
            for row in cursor.fetchall():
                business_types.append({
                    'id': row['id'],
                    'name': row['name'],
                    'display_name': row['display_name'],
                    'color': row['color'],
                    'icon': row['icon'],
                    'is_default': bool(row['is_default']),
                    'sort_order': row['sort_order']
                })

            # If user has no business types, create defaults
            if not business_types:
                business_types = _create_default_business_types(cursor, conn, user_id)

            return jsonify({
                'success': True,
                'business_types': business_types
            })

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Error fetching business types: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@business_types_bp.route('', methods=['POST'])
def create_business_type():
    """
    Create a new business type for the current user.

    Request Body:
        {
            "name": "My Business",
            "display_name": "My Business",
            "color": "#FF6B6B",
            "icon": "building.2",
            "is_default": false
        }

    Returns:
        {
            "success": true,
            "business_type": {...}
        }
    """
    try:
        user_id = get_current_user_id()
        data = request.get_json() or {}

        name = data.get('name', '').strip()
        display_name = data.get('display_name', name).strip()
        color = data.get('color', '#00FF88')
        icon = data.get('icon', 'briefcase')
        is_default = data.get('is_default', False)

        if not name:
            return jsonify({
                'success': False,
                'error': 'Name is required'
            }), 400

        # Normalize name for database (replace spaces with underscores)
        db_name = name.replace(' ', '_')

        db = get_mysql_db()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()

            # If this is set as default, unset other defaults
            if is_default:
                cursor.execute("""
                    UPDATE user_business_types
                    SET is_default = FALSE
                    WHERE user_id = %s
                """, (user_id,))

            # Get next sort order
            cursor.execute("""
                SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order
                FROM user_business_types
                WHERE user_id = %s
            """, (user_id,))
            next_order = cursor.fetchone()['next_order']

            # Insert new business type
            cursor.execute("""
                INSERT INTO user_business_types
                (user_id, name, display_name, color, icon, is_default, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, db_name, display_name, color, icon, is_default, next_order))

            conn.commit()

            return jsonify({
                'success': True,
                'business_type': {
                    'id': cursor.lastrowid,
                    'name': db_name,
                    'display_name': display_name,
                    'color': color,
                    'icon': icon,
                    'is_default': is_default,
                    'sort_order': next_order
                }
            })

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Error creating business type: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@business_types_bp.route('/<int:type_id>', methods=['PUT'])
def update_business_type(type_id):
    """
    Update a business type.

    Request Body:
        {
            "display_name": "Updated Name",
            "color": "#4ECDC4",
            "icon": "star.fill",
            "is_default": true
        }
    """
    try:
        user_id = get_current_user_id()
        data = request.get_json() or {}

        db = get_mysql_db()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()

            # Verify ownership
            cursor.execute("""
                SELECT id FROM user_business_types
                WHERE id = %s AND user_id = %s
            """, (type_id, user_id))

            if not cursor.fetchone():
                return jsonify({
                    'success': False,
                    'error': 'Business type not found'
                }), 404

            # Build update
            updates = []
            params = []

            if 'display_name' in data:
                updates.append("display_name = %s")
                params.append(data['display_name'])

            if 'color' in data:
                updates.append("color = %s")
                params.append(data['color'])

            if 'icon' in data:
                updates.append("icon = %s")
                params.append(data['icon'])

            if 'is_default' in data and data['is_default']:
                # Unset other defaults first
                cursor.execute("""
                    UPDATE user_business_types
                    SET is_default = FALSE
                    WHERE user_id = %s
                """, (user_id,))
                updates.append("is_default = TRUE")

            if 'sort_order' in data:
                updates.append("sort_order = %s")
                params.append(data['sort_order'])

            if updates:
                params.append(type_id)
                cursor.execute(f"""
                    UPDATE user_business_types
                    SET {', '.join(updates)}
                    WHERE id = %s
                """, params)
                conn.commit()

            return jsonify({'success': True})

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Error updating business type: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@business_types_bp.route('/<int:type_id>', methods=['DELETE'])
def delete_business_type(type_id):
    """
    Delete a business type (soft delete - marks as inactive).
    """
    try:
        user_id = get_current_user_id()

        db = get_mysql_db()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()

            # Verify ownership and not default
            cursor.execute("""
                SELECT id, is_default FROM user_business_types
                WHERE id = %s AND user_id = %s
            """, (type_id, user_id))

            row = cursor.fetchone()
            if not row:
                return jsonify({
                    'success': False,
                    'error': 'Business type not found'
                }), 404

            if row['is_default']:
                return jsonify({
                    'success': False,
                    'error': 'Cannot delete default business type. Set another as default first.'
                }), 400

            # Soft delete
            cursor.execute("""
                UPDATE user_business_types
                SET is_active = FALSE
                WHERE id = %s
            """, (type_id,))
            conn.commit()

            return jsonify({'success': True})

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Error deleting business type: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@business_types_bp.route('/reorder', methods=['POST'])
def reorder_business_types():
    """
    Reorder business types.

    Request Body:
        {
            "order": [3, 1, 2, 5, 4]  // Array of type IDs in new order
        }
    """
    try:
        user_id = get_current_user_id()
        data = request.get_json() or {}
        order = data.get('order', [])

        if not order:
            return jsonify({
                'success': False,
                'error': 'Order array is required'
            }), 400

        db = get_mysql_db()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()

            for idx, type_id in enumerate(order):
                cursor.execute("""
                    UPDATE user_business_types
                    SET sort_order = %s
                    WHERE id = %s AND user_id = %s
                """, (idx + 1, type_id, user_id))

            conn.commit()

            return jsonify({'success': True})

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Error reordering business types: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _create_default_business_types(cursor, conn, user_id):
    """Create default business types for a new user."""
    defaults = [
        ('Personal', 'Personal', '#00FF88', 'person.fill', True, 1),
        ('Business', 'Business', '#4A90D9', 'briefcase.fill', False, 2),
    ]

    business_types = []
    for name, display_name, color, icon, is_default, sort_order in defaults:
        cursor.execute("""
            INSERT INTO user_business_types
            (user_id, name, display_name, color, icon, is_default, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)
        """, (user_id, name, display_name, color, icon, is_default, sort_order))

        business_types.append({
            'id': cursor.lastrowid,
            'name': name,
            'display_name': display_name,
            'color': color,
            'icon': icon,
            'is_default': is_default,
            'sort_order': sort_order
        })

    conn.commit()
    return business_types


def register_business_types_routes(app):
    """Register business types routes with the Flask app."""
    app.register_blueprint(business_types_bp)
    logger.info("Business types routes registered at /api/business-types/*")
