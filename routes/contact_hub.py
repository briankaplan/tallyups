"""
Contact Hub Routes Blueprint
==============================
ATLAS Contact Hub - Full CRM Integration with relationship intelligence.

Routes (31 total):
- Contact Management (6 routes):
  - GET/POST /api/contact-hub/contacts
  - GET/PUT/PATCH /api/contact-hub/contacts/<id>
  - POST /api/contact-hub/create-from-merchant

- Interactions (5 routes):
  - GET/POST /api/contact-hub/interactions
  - POST /api/contact-hub/interactions/log
  - POST /api/contact-hub/interactions/quick-log
  - GET /api/contact-hub/timeline/<id>

- Expense Integration (7 routes):
  - POST /api/contact-hub/link-expense
  - POST /api/contact-hub/unlink-expense
  - GET /api/contact-hub/contacts/<id>/expenses
  - GET /api/contact-hub/suggest-contacts/<id>
  - GET /api/contact-hub/suggest
  - GET /api/contact-hub/expense-contacts/<id>
  - POST /api/contact-hub/auto-link-expenses
  - GET /api/contact-hub/spending-by-contact

- Relationship Intelligence (6 routes):
  - GET /api/contact-hub/touch-needed
  - GET /api/contact-hub/digest
  - GET /api/contact-hub/intelligence/strength/<id>
  - GET /api/contact-hub/intelligence/insights/<id>
  - GET /api/contact-hub/intelligence/recommendations
  - GET /api/contact-hub/intelligence/analysis
  - GET /api/contact-hub/intelligence/ai-summary/<id>

- Reminders (2 routes):
  - GET/POST /api/contact-hub/reminders

- Calendar (3 routes):
  - POST /api/contact-hub/calendar/sync
  - GET /api/contact-hub/calendar/events
  - GET /api/contact-hub/calendar/upcoming

- Pages (1 route):
  - GET /contact-hub, /contacts, /contacts.html

Dependencies:
- Database with ATLAS tables
- Authentication system
"""

import os
from flask import Blueprint, request, jsonify, session, send_from_directory
from functools import wraps
from db_user_scope import get_current_user_id, USER_SCOPING_ENABLED

# Create blueprint
contact_hub_bp = Blueprint('contact_hub', __name__)


def get_contact_hub_services():
    """
    Lazy import services to avoid circular dependencies.
    Returns dict with service availability and functions.
    """
    services = {
        'available': False,
        'error': None
    }

    try:
        from viewer_server import (
            db,
            USE_DATABASE,
            get_db_connection,
            return_db_connection,
            secure_compare_api_key,
            safe_json,
            is_authenticated,
            BASE_DIR
        )

        services['db'] = db
        services['USE_DATABASE'] = USE_DATABASE
        services['get_db'] = get_db_connection
        services['return_db'] = return_db_connection
        services['secure_compare'] = secure_compare_api_key
        services['safe_json'] = safe_json
        services['is_authenticated'] = is_authenticated
        services['BASE_DIR'] = BASE_DIR
        services['available'] = True

    except ImportError as e:
        services['error'] = f"Contact Hub services not available: {e}"

    return services


def login_required_api(f):
    """Decorator for API routes that require login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function


def check_db_available(services):
    """Check if database is available and return error response if not."""
    if not services.get('USE_DATABASE') or not services.get('db'):
        return jsonify({"error": "Database not available"}), 500
    return None


# =============================================================================
# PAGE ROUTES
# =============================================================================

@contact_hub_bp.route("/contact-hub")
@contact_hub_bp.route("/contacts")
@contact_hub_bp.route("/contacts.html")
def contact_hub_page():
    """ATLAS Contact Hub - Relationship Intelligence Dashboard"""
    if not session.get('authenticated'):
        return jsonify({'error': 'Authentication required'}), 401

    services = get_contact_hub_services()
    if not services['available']:
        return jsonify({'error': 'Contact Hub not available'}), 503

    response = send_from_directory(services['BASE_DIR'], "contacts.html")
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# =============================================================================
# CONTACT CRUD ROUTES
# =============================================================================

@contact_hub_bp.route("/api/contact-hub/contacts", methods=["GET"])
@login_required_api
def api_contact_hub_list():
    """List contacts with ATLAS relationship data"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        search = request.args.get("search", "")
        relationship_type = request.args.get("type", "")
        touch_needed = request.args.get("touch_needed", "false").lower() == "true"
        sort_by = request.args.get("sort", "name")

        result = services['db'].atlas_get_contacts(
            limit=limit,
            offset=offset,
            search=search if search else None,
            relationship_type=relationship_type if relationship_type else None,
            touch_needed=touch_needed,
            sort_by=sort_by
        )

        return jsonify(services['safe_json'](result))
    except Exception as e:
        print(f"Contact list error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/contacts/<int:contact_id>", methods=["GET"])
@login_required_api
def api_contact_hub_get(contact_id):
    """Get single contact with full relationship data"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        contact = services['db'].atlas_get_contact(contact_id)
        if not contact:
            return jsonify({"error": "Contact not found"}), 404
        return jsonify(services['safe_json'](contact))
    except Exception as e:
        print(f"Contact get error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/contacts", methods=["POST"])
@login_required_api
def api_contact_hub_create():
    """Create new contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        contact_id = services['db'].atlas_create_contact(data)
        if contact_id:
            return jsonify({"ok": True, "id": contact_id})
        return jsonify({"error": "Failed to create contact"}), 500
    except Exception as e:
        print(f"Contact create error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/contacts/<int:contact_id>", methods=["PUT", "PATCH"])
@login_required_api
def api_contact_hub_update(contact_id):
    """Update contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        success = services['db'].atlas_update_contact(contact_id, data)
        if success:
            return jsonify({"ok": True})
        return jsonify({"error": "Failed to update contact"}), 500
    except Exception as e:
        print(f"Contact update error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/create-from-merchant", methods=["POST"])
@login_required_api
def api_contact_hub_create_from_merchant():
    """Create a new contact from a merchant name"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        merchant = data.get('merchant')
        transaction_index = data.get('transaction_index')

        if not merchant:
            return jsonify({"error": "Merchant name required"}), 400

        contact_id = services['db'].atlas_create_contact_from_merchant(merchant, transaction_index)
        if contact_id:
            return jsonify({"ok": True, "contact_id": contact_id})
        return jsonify({"error": "Failed to create contact"}), 500
    except Exception as e:
        print(f"Create from merchant error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# INTERACTION ROUTES
# =============================================================================

@contact_hub_bp.route("/api/contact-hub/interactions", methods=["GET"])
@login_required_api
def api_contact_hub_interactions():
    """Get interactions"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        contact_id = request.args.get("contact_id", type=int)
        interaction_type = request.args.get("type", "")
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        result = services['db'].atlas_get_interactions(
            contact_id=contact_id,
            interaction_type=interaction_type if interaction_type else None,
            limit=limit,
            offset=offset
        )

        return jsonify(services['safe_json'](result))
    except Exception as e:
        print(f"Interactions error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/interactions", methods=["POST"])
@login_required_api
def api_contact_hub_create_interaction():
    """Create interaction (call, meeting, note, etc.)"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        interaction_id = services['db'].atlas_create_interaction(data)
        if interaction_id:
            return jsonify({"ok": True, "id": interaction_id})
        return jsonify({"error": "Failed to create interaction"}), 500
    except Exception as e:
        print(f"Interaction create error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/interactions/log", methods=["POST"])
@login_required_api
def api_contact_hub_log_interaction():
    """Log a new interaction"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        interaction_id = services['db'].atlas_log_interaction(data)
        if interaction_id:
            return jsonify({"ok": True, "id": interaction_id})
        return jsonify({"error": "Failed to log interaction"}), 500
    except Exception as e:
        print(f"Log interaction error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/interactions/quick-log", methods=["POST"])
@login_required_api
def api_contact_hub_quick_log():
    """Quick log an interaction (call, meeting, email, note)"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        contact_id = data.get('contact_id')
        interaction_type = data.get('type', 'note')
        note = data.get('note')

        if not contact_id:
            return jsonify({"error": "contact_id required"}), 400

        success = services['db'].atlas_quick_log(contact_id, interaction_type, note)
        return jsonify({"ok": success})
    except Exception as e:
        print(f"Quick log error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/timeline/<int:contact_id>", methods=["GET"])
@login_required_api
def api_contact_hub_timeline(contact_id):
    """Get unified timeline for a contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        limit = request.args.get("limit", 50, type=int)
        timeline = services['db'].atlas_get_contact_timeline(contact_id, limit=limit)
        return jsonify(services['safe_json']({"items": timeline}))
    except Exception as e:
        print(f"Timeline error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# EXPENSE INTEGRATION ROUTES
# =============================================================================

@contact_hub_bp.route("/api/contact-hub/link-expense", methods=["POST"])
@login_required_api
def api_contact_hub_link_expense():
    """Link expense to contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        contact_id = data.get("contact_id")
        transaction_index = data.get("transaction_index")
        link_type = data.get("link_type", "attendee")
        notes = data.get("notes")

        if not contact_id or not transaction_index:
            return jsonify({"error": "Missing contact_id or transaction_index"}), 400

        success = services['db'].atlas_link_expense_to_contact(
            contact_id=contact_id,
            transaction_index=transaction_index,
            link_type=link_type,
            notes=notes
        )

        if success:
            return jsonify({"ok": True})
        return jsonify({"error": "Failed to link expense"}), 500
    except Exception as e:
        print(f"Link expense error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/unlink-expense", methods=["POST"])
@login_required_api
def api_contact_hub_unlink_expense():
    """Remove a contact-expense link"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        contact_id = data.get('contact_id')
        transaction_index = data.get('transaction_index')

        if not contact_id or transaction_index is None:
            return jsonify({"error": "Missing contact_id or transaction_index"}), 400

        success = services['db'].atlas_unlink_expense(contact_id, transaction_index)
        return jsonify({"ok": success})
    except Exception as e:
        print(f"Unlink expense error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/contacts/<int:contact_id>/expenses", methods=["GET"])
@login_required_api
def api_contact_hub_contact_expenses(contact_id):
    """Get all expenses linked to a contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        limit = int(request.args.get('limit', 50))
        expenses = services['db'].atlas_get_contact_expenses(contact_id, limit)
        return jsonify({"ok": True, "expenses": expenses})
    except Exception as e:
        print(f"Contact expenses error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/suggest-contacts/<int:transaction_index>", methods=["GET"])
@login_required_api
def api_contact_hub_suggest_contacts(transaction_index):
    """Suggest contacts for an expense based on merchant name"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        limit = int(request.args.get('limit', 5))
        suggestions = services['db'].atlas_suggest_contacts_for_expense(transaction_index, limit)
        return jsonify({"ok": True, "suggestions": suggestions})
    except Exception as e:
        print(f"Suggest contacts error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/suggest", methods=["GET"])
@login_required_api
def api_contact_hub_suggest_by_merchant():
    """
    Suggest contacts based on merchant name (iOS app endpoint).

    Query params:
    - merchant: Merchant name to search for
    - date: Optional date (YYYY-MM-DD) for context

    Returns: { contacts: [...], total: N }
    """
    services = get_contact_hub_services()
    if not services['available']:
        return jsonify({'contacts': [], 'total': 0, 'error': 'Services not available'})

    merchant = request.args.get('merchant', '')
    limit = int(request.args.get('limit', 10))

    if not merchant:
        return jsonify({'contacts': [], 'total': 0})

    try:
        conn, db_type = services['get_db']()
        cursor = conn.cursor()

        # Search contacts whose company matches the merchant
        search_pattern = f'%{merchant}%'

        # SECURITY: User scoping - only search user's own contacts
        if USER_SCOPING_ENABLED:
            user_id = get_current_user_id()
            cursor.execute('''
                SELECT id, name, first_name, last_name, email, phone, company, job_title, category
                FROM contacts
                WHERE user_id = %s AND (company LIKE %s OR name LIKE %s)
                ORDER BY
                    CASE WHEN company LIKE %s THEN 0 ELSE 1 END,
                    name
                LIMIT %s
            ''', (user_id, search_pattern, search_pattern, search_pattern, limit))
        else:
            cursor.execute('''
                SELECT id, name, first_name, last_name, email, phone, company, job_title, category
                FROM contacts
                WHERE company LIKE %s OR name LIKE %s
                ORDER BY
                    CASE WHEN company LIKE %s THEN 0 ELSE 1 END,
                    name
                LIMIT %s
            ''', (search_pattern, search_pattern, search_pattern, limit))

        rows = cursor.fetchall()
        cursor.close()
        services['return_db'](conn)

        contacts = []
        for row in rows:
            contacts.append({
                'id': str(row.get('id', '')),
                'name': row.get('name') or f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                'email': row.get('email'),
                'phone': row.get('phone'),
                'company': row.get('company'),
                'tags': [row.get('category')] if row.get('category') else []
            })

        return jsonify({
            'contacts': contacts,
            'total': len(contacts)
        })

    except Exception as e:
        print(f"Suggest contacts error: {e}")
        return jsonify({'contacts': [], 'total': 0, 'error': str(e)})


@contact_hub_bp.route("/api/contact-hub/expense-contacts/<int:transaction_index>", methods=["GET"])
@login_required_api
def api_contact_hub_expense_contacts(transaction_index):
    """Get all contacts linked to an expense"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        contacts = services['db'].atlas_get_expense_contacts(transaction_index)
        return jsonify({"ok": True, "contacts": contacts})
    except Exception as e:
        print(f"Expense contacts error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/auto-link-expenses", methods=["POST"])
@login_required_api
def api_contact_hub_auto_link_expenses():
    """Auto-link expenses to contacts by matching merchant to company"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json() or {}
        dry_run = data.get('dry_run', True)
        result = services['db'].atlas_auto_link_expenses(dry_run=dry_run)
        return jsonify({"ok": True, **result})
    except Exception as e:
        print(f"Auto-link error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/spending-by-contact", methods=["GET"])
@login_required_api
def api_contact_hub_spending_by_contact():
    """Get spending summary by contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        limit = int(request.args.get('limit', 20))
        spending = services['db'].atlas_get_spending_by_contact(limit)
        return jsonify({"ok": True, "spending": spending})
    except Exception as e:
        print(f"Spending by contact error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# RELATIONSHIP INTELLIGENCE ROUTES
# =============================================================================

@contact_hub_bp.route("/api/contact-hub/touch-needed", methods=["GET"])
@login_required_api
def api_contact_hub_touch_needed():
    """Get contacts needing touch"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        limit = request.args.get("limit", 20, type=int)
        contacts = services['db'].atlas_get_touch_needed(limit=limit)
        return jsonify(services['safe_json']({"items": contacts}))
    except Exception as e:
        print(f"Touch needed error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/digest", methods=["GET"])
@login_required_api
def api_contact_hub_digest():
    """Get relationship intelligence digest"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        digest = services['db'].atlas_get_relationship_digest()
        return jsonify(services['safe_json'](digest))
    except Exception as e:
        print(f"Digest error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/intelligence/strength/<int:contact_id>", methods=["GET"])
@login_required_api
def api_contact_hub_relationship_strength(contact_id):
    """Calculate and return relationship strength for a contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        strength = services['db'].atlas_calculate_relationship_strength(contact_id)
        return jsonify({"ok": True, **strength})
    except Exception as e:
        print(f"Relationship strength error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/intelligence/insights/<int:contact_id>", methods=["GET"])
@login_required_api
def api_contact_hub_relationship_insights(contact_id):
    """Get relationship insights for a contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        insights = services['db'].atlas_get_relationship_insights(contact_id)
        return jsonify({"ok": True, **insights})
    except Exception as e:
        print(f"Relationship insights error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/intelligence/recommendations", methods=["GET"])
@login_required_api
def api_contact_hub_recommendations():
    """Get recommended actions for contacts"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        limit = int(request.args.get('limit', 10))
        recommendations = services['db'].atlas_get_contact_recommendations(limit)
        return jsonify({"ok": True, "recommendations": recommendations})
    except Exception as e:
        print(f"Recommendations error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/intelligence/analysis", methods=["GET"])
@login_required_api
def api_contact_hub_interaction_analysis():
    """Analyze interaction patterns"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        days = int(request.args.get('days', 30))
        analysis = services['db'].atlas_get_interaction_analysis(days)
        return jsonify({"ok": True, **analysis})
    except Exception as e:
        print(f"Interaction analysis error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/intelligence/ai-summary/<int:contact_id>", methods=["GET"])
@login_required_api
def api_contact_hub_ai_summary(contact_id):
    """Get AI-ready summary for a contact"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        summary = services['db'].atlas_generate_ai_summary(contact_id)
        return jsonify({"ok": True, "summary": summary})
    except Exception as e:
        print(f"AI summary error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# REMINDERS ROUTES
# =============================================================================

@contact_hub_bp.route("/api/contact-hub/reminders", methods=["GET"])
@login_required_api
def api_contact_hub_reminders():
    """Get reminders"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        status = request.args.get("status", "pending")
        limit = request.args.get("limit", 20, type=int)
        reminders = services['db'].atlas_get_reminders(status=status, limit=limit)
        return jsonify(services['safe_json']({"items": reminders}))
    except Exception as e:
        print(f"Reminders error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/reminders", methods=["POST"])
@login_required_api
def api_contact_hub_create_reminder():
    """Create reminder"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        data = request.get_json()
        reminder_id = services['db'].atlas_create_reminder(data)
        if reminder_id:
            return jsonify({"ok": True, "id": reminder_id})
        return jsonify({"error": "Failed to create reminder"}), 500
    except Exception as e:
        print(f"Reminder create error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# CALENDAR ROUTES
# =============================================================================

@contact_hub_bp.route("/api/contact-hub/calendar/sync", methods=["POST"])
def api_contact_hub_calendar_sync():
    """Sync calendar events to ATLAS"""
    services = get_contact_hub_services()
    if not services['available']:
        return jsonify({'error': 'Contact Hub not available'}), 503

    # Auth check - allow admin_key or login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not services['is_authenticated']():
            return jsonify({'error': 'Authentication required'}), 401

    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        stats = services['db'].atlas_sync_all_calendar_events()
        return jsonify({"ok": True, **stats})
    except Exception as e:
        print(f"Calendar sync error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/calendar/events", methods=["GET"])
@contact_hub_bp.route("/api/calendar/events", methods=["GET"])  # iOS app compatibility alias
@login_required_api
def api_contact_hub_calendar_events():
    """Get calendar events"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        contact_id = request.args.get('contact_id', type=int)
        # Support both iOS app params (date, start, end) and web params (start_date, end_date)
        start_date = request.args.get('start_date') or request.args.get('start') or request.args.get('date')
        end_date = request.args.get('end_date') or request.args.get('end') or request.args.get('date')
        limit = request.args.get('limit', 50, type=int)

        events = services['db'].atlas_get_calendar_events(contact_id, start_date, end_date, limit)
        return jsonify({"ok": True, "events": events})
    except Exception as e:
        print(f"Calendar events error: {e}")
        return jsonify({"error": str(e)}), 500


@contact_hub_bp.route("/api/contact-hub/calendar/upcoming", methods=["GET"])
@login_required_api
def api_contact_hub_upcoming_events():
    """Get upcoming events with matched contacts"""
    services = get_contact_hub_services()
    db_error = check_db_available(services)
    if db_error:
        return db_error

    try:
        days = request.args.get('days', 7, type=int)
        events = services['db'].atlas_get_upcoming_events_with_contacts(days)
        return jsonify({"ok": True, "events": events})
    except Exception as e:
        print(f"Upcoming events error: {e}")
        return jsonify({"error": str(e)}), 500
