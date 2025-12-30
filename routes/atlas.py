"""
================================================================================
ATLAS Relationship Intelligence API Routes
================================================================================
Flask Blueprint for ATLAS - Relationship tracking, contact sync, and AI features.

ENDPOINTS:
----------
Status & iMessage:
    GET  /api/atlas/status              - Get ATLAS system status
    GET  /api/atlas/imessage/recent     - Get recent iMessage contacts
    GET  /api/atlas/imessage/conversation/<handle> - Conversation history
    GET  /api/atlas/imessage/payments   - Payment messages from iMessage
    GET  /api/atlas/imessage/payments/stats - Payment statistics
    GET  /api/atlas/imessage/receipts   - Receipt URLs from iMessage
    POST /api/atlas/imessage/search-transaction - Search for transaction match

Relationship Intelligence:
    GET  /api/atlas/relationship/<id>   - Relationship health score
    GET  /api/atlas/meeting-prep/<id>   - Meeting preparation insights
    GET  /api/atlas/nudges              - Engagement suggestions
    GET  /api/atlas/commitments         - Active commitments
    PATCH /api/atlas/commitments/<id>   - Update commitment
    POST /api/atlas/interactions        - Log an interaction

Gmail Integration:
    GET  /api/atlas/gmail/status        - Gmail connection status
    GET  /api/atlas/gmail/recent        - Recent emails
    GET  /api/atlas/gmail/conversation/<email> - Email conversation

People API:
    GET  /api/atlas/people/contacts     - Google People contacts
    GET  /api/atlas/people/search       - Search people
    GET  /api/atlas/people/photo/<id>   - Contact photo

Contact Management:
    GET  /api/atlas/contacts            - List all contacts
    POST /api/atlas/contacts            - Create contact
    GET  /api/atlas/contacts/<id>       - Contact details
    PUT  /api/atlas/contacts/<id>       - Update contact
    DELETE /api/atlas/contacts/<id>     - Delete contact
    POST /api/atlas/contacts/<id>/photo - Upload photo
    DELETE /api/atlas/contacts/<id>/photo - Delete photo
    GET  /api/atlas/contacts/<id>/communications - Communication history

Contact Sync:
    GET  /api/atlas/sync/status         - Sync status
    GET  /api/atlas/sync/pending        - Pending sync items
    POST /api/atlas/sync/mark-modified  - Mark contact modified
    POST /api/atlas/sync/google/push    - Push to Google
    POST /api/atlas/sync/google/pull    - Pull from Google
    POST /api/atlas/sync/resolve-conflict - Resolve sync conflict
    GET  /api/atlas/sync/adapters       - Available sync adapters
    POST /api/atlas/sync/apple          - Sync with Apple
    POST /api/atlas/sync/google         - Full Google sync
    POST /api/atlas/sync/crm            - Sync with CRM
    POST /api/atlas/sync/linkedin       - Sync with LinkedIn

AI Features:
    POST /api/atlas/ai/analyze-contacts - AI contact analysis
    GET  /api/atlas/ai/smart-filters    - Smart filter suggestions
    POST /api/atlas/ai/search           - AI-powered search
    POST /api/atlas/ai/organize         - AI organize contacts

Bulk Operations:
    POST /api/atlas/contacts/enrich     - Enrich contacts
    POST /api/atlas/contacts/<id>/enrich - Enrich single contact
    POST /api/atlas/contacts/find-incomplete - Find incomplete contacts
    POST /api/atlas/contacts/bulk-delete - Bulk delete
    POST /api/atlas/contacts/bulk-update - Bulk update
    GET  /api/atlas/contacts/upcoming-events - Upcoming birthdays/anniversaries
    POST /api/atlas/contacts/migrate    - Migrate contacts
    POST /api/atlas/contacts/upload     - Upload contacts CSV

Interaction Tracking:
    POST /api/atlas/contacts/calculate-scores - Calculate relationship scores
    POST /api/atlas/contacts/sync-email-interactions - Sync email interactions
    POST /api/atlas/contacts/sync-imessage-interactions - Sync iMessage
    POST /api/atlas/contacts/sync-all-interactions - Full sync
    GET  /api/atlas/contacts/frequency-stats - Interaction stats

================================================================================
"""

import os
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

# Create blueprint
atlas_bp = Blueprint('atlas', __name__, url_prefix='/api/atlas')

# Logger setup
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

# =============================================================================
# LAZY IMPORTS - Avoid circular imports by importing inside functions
# =============================================================================

def get_db_helpers():
    """Lazy import database helpers from viewer_server"""
    from viewer_server import get_db_connection, return_db_connection
    return get_db_connection, return_db_connection

def get_auth_helpers():
    """Lazy import auth helpers"""
    from auth import login_required, is_authenticated
    from viewer_server import secure_compare_api_key
    return login_required, is_authenticated, secure_compare_api_key

def get_atlas_services():
    """Lazy import ATLAS services"""
    try:
        from relationship_intelligence import (
            AtlasService,
            iMessageReader,
            InteractionTracker,
            CommitmentTracker,
            RelationshipHealthAnalyzer,
            MeetingPrepGenerator,
            NudgeEngine,
            GmailReader,
            GooglePeopleAPI,
            GMAIL_ACCOUNTS
        )
        return {
            'available': True,
            'AtlasService': AtlasService,
            'iMessageReader': iMessageReader,
            'InteractionTracker': InteractionTracker,
            'CommitmentTracker': CommitmentTracker,
            'RelationshipHealthAnalyzer': RelationshipHealthAnalyzer,
            'MeetingPrepGenerator': MeetingPrepGenerator,
            'NudgeEngine': NudgeEngine,
            'GmailReader': GmailReader,
            'GooglePeopleAPI': GooglePeopleAPI,
            'GMAIL_ACCOUNTS': GMAIL_ACCOUNTS
        }
    except Exception as e:
        logger.warning(f"ATLAS services not available: {e}")
        return {
            'available': False,
            'AtlasService': None,
            'iMessageReader': None,
            'GmailReader': None,
            'GooglePeopleAPI': None,
            'GMAIL_ACCOUNTS': []
        }

def get_contact_sync_engine():
    """Lazy import contact sync engine"""
    try:
        from contact_sync_engine import (
            UniversalSyncEngine,
            AppleContactsAdapter,
            GoogleContactsAdapter,
            LinkedInAdapter,
            SyncDirection,
            SyncResult
        )
        return {
            'available': True,
            'UniversalSyncEngine': UniversalSyncEngine,
            'AppleContactsAdapter': AppleContactsAdapter,
            'GoogleContactsAdapter': GoogleContactsAdapter,
            'LinkedInAdapter': LinkedInAdapter,
            'SyncDirection': SyncDirection,
            'SyncResult': SyncResult
        }
    except Exception as e:
        logger.warning(f"Contact sync engine not available: {e}")
        return {'available': False}


# =============================================================================
# ATLAS STATUS
# =============================================================================

@atlas_bp.route("/status", methods=["GET"])
def atlas_status_api():
    """Get ATLAS system status and capabilities"""
    login_required, is_authenticated, _ = get_auth_helpers()

    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    return jsonify({
        "ok": True,
        "available": atlas['available'],
        "features": {
            "imessage": atlas['available'],
            "interaction_tracking": atlas['available'],
            "commitments": atlas['available'],
            "relationship_health": atlas['available'],
            "meeting_prep": atlas['available'],
            "nudges": atlas['available']
        }
    })


# =============================================================================
# IMESSAGE ENDPOINTS
# =============================================================================

@atlas_bp.route("/imessage/recent", methods=["GET"])
def atlas_imessage_recent():
    """Get recent iMessage contacts with message counts"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        days = request.args.get('days', 7, type=int)
        limit = request.args.get('limit', 20, type=int)

        reader = atlas['iMessageReader']()
        contacts = reader.get_recent_contacts(days=days, limit=limit)

        return jsonify({
            "ok": True,
            "days": days,
            "contacts": contacts
        })
    except Exception as e:
        logger.error(f"ATLAS iMessage error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/imessage/conversation/<path:handle>", methods=["GET"])
def atlas_imessage_conversation(handle: str):
    """Get conversation history with a specific contact"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 100, type=int)

        reader = atlas['iMessageReader']()
        messages = reader.get_messages_with_contact(handle, days=days, limit=limit)

        return jsonify({
            "ok": True,
            "handle": handle,
            "messages": messages
        })
    except Exception as e:
        logger.error(f"ATLAS conversation error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/imessage/payments", methods=["GET"])
def atlas_imessage_payments():
    """Get payment-related messages from iMessage (Square, Toast, Parking, etc.)"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    try:
        # Try to import the shared client
        try:
            from services.shared.imessage_client import iMessageClient, PaymentMessage
            IMESSAGE_CLIENT_AVAILABLE = True
        except ImportError:
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).parent.parent.parent))
                from packages.shared.imessage_client import iMessageClient, PaymentMessage
                IMESSAGE_CLIENT_AVAILABLE = True
            except ImportError:
                IMESSAGE_CLIENT_AVAILABLE = False

        if not IMESSAGE_CLIENT_AVAILABLE:
            return jsonify({'error': 'iMessage client not available'}), 503

        days = request.args.get('days', 30, type=int)
        platform = request.args.get('platform', None)
        platform_type = request.args.get('type', None)

        client = iMessageClient()
        payments = client.get_recent_payments(days=days)

        # Apply filters
        if platform:
            payments = [p for p in payments if p.platform.lower() == platform.lower()]
        if platform_type:
            payments = [p for p in payments if p.platform_type.lower() == platform_type.lower()]

        # Convert to JSON-serializable format
        results = []
        for p in payments:
            results.append({
                'platform': p.platform,
                'platform_type': p.platform_type,
                'amount': p.amount,
                'raw_amount': p.raw_amount,
                'date': p.message.date.isoformat(),
                'sender': p.message.sender,
                'is_from_me': p.message.is_from_me,
                'message_preview': p.message.text[:200] if p.message.text else None,
                'urls': p.urls[:3] if p.urls else [],
            })

        return jsonify({
            "ok": True,
            "days": days,
            "count": len(results),
            "payments": results
        })
    except Exception as e:
        logger.error(f"iMessage payments error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/imessage/payments/stats", methods=["GET"])
def atlas_imessage_payment_stats():
    """Get statistics about payments in iMessages"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    try:
        try:
            from services.shared.imessage_client import iMessageClient
            IMESSAGE_CLIENT_AVAILABLE = True
        except ImportError:
            IMESSAGE_CLIENT_AVAILABLE = False

        if not IMESSAGE_CLIENT_AVAILABLE:
            return jsonify({'error': 'iMessage client not available'}), 503

        days = request.args.get('days', 30, type=int)

        client = iMessageClient()
        stats = client.get_payment_stats(days=days)

        return jsonify({
            "ok": True,
            "days": days,
            "stats": stats
        })
    except Exception as e:
        logger.error(f"iMessage payment stats error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/imessage/receipts", methods=["GET"])
def atlas_imessage_receipts():
    """Get receipt URLs found in iMessages"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    try:
        try:
            from services.shared.imessage_client import iMessageClient
            IMESSAGE_CLIENT_AVAILABLE = True
        except ImportError:
            IMESSAGE_CLIENT_AVAILABLE = False

        if not IMESSAGE_CLIENT_AVAILABLE:
            return jsonify({'error': 'iMessage client not available'}), 503

        days = request.args.get('days', 90, type=int)
        limit = request.args.get('limit', 100, type=int)

        client = iMessageClient()
        receipts = client.find_receipt_urls(days=days)[:limit]

        results = []
        for r in receipts:
            results.append({
                'url': r.url,
                'platform': r.platform,
                'amount': r.amount,
                'date': r.message.date.isoformat(),
                'sender': r.message.sender,
            })

        return jsonify({
            "ok": True,
            "days": days,
            "count": len(results),
            "receipts": results
        })
    except Exception as e:
        logger.error(f"iMessage receipts error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/imessage/search-transaction", methods=["POST"])
def atlas_imessage_search_transaction():
    """Search iMessages for a specific transaction match"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    try:
        try:
            from services.shared.imessage_client import iMessageClient
            IMESSAGE_CLIENT_AVAILABLE = True
        except ImportError:
            IMESSAGE_CLIENT_AVAILABLE = False

        if not IMESSAGE_CLIENT_AVAILABLE:
            return jsonify({'error': 'iMessage client not available'}), 503

        data = request.get_json()
        merchant = data.get('merchant', '')
        amount = float(data.get('amount', 0))
        date_str = data.get('date')
        window_days = data.get('window_days', 5)

        if not merchant or not amount or not date_str:
            return jsonify({'error': 'merchant, amount, and date required'}), 400

        tx_date = datetime.strptime(date_str, '%Y-%m-%d')

        client = iMessageClient()
        matches = client.search_for_transaction(merchant, amount, tx_date, window_days=window_days)

        results = []
        for m in matches:
            results.append({
                'platform': m.platform,
                'platform_type': m.platform_type,
                'amount': m.amount,
                'date': m.message.date.isoformat(),
                'sender': m.message.sender,
                'message_preview': m.message.text[:200] if m.message.text else None,
                'urls': m.urls[:3] if m.urls else [],
            })

        return jsonify({
            "ok": True,
            "query": {"merchant": merchant, "amount": amount, "date": date_str},
            "matches": results,
            "count": len(results)
        })
    except Exception as e:
        logger.error(f"iMessage search transaction error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# RELATIONSHIP INTELLIGENCE ENDPOINTS
# =============================================================================

@atlas_bp.route("/relationship/<path:identifier>", methods=["GET"])
def atlas_relationship_health(identifier: str):
    """Get relationship health score and insights for a contact"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        analyzer = atlas['RelationshipHealthAnalyzer']()
        health = analyzer.get_health_score(identifier)
        return jsonify({"ok": True, "relationship": health})
    except Exception as e:
        logger.error(f"Relationship health error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/meeting-prep/<path:identifier>", methods=["GET"])
def atlas_meeting_prep(identifier: str):
    """Get meeting preparation insights for a contact"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        prep = atlas['MeetingPrepGenerator']()
        insights = prep.generate_prep(identifier)
        return jsonify({"ok": True, "prep": insights})
    except Exception as e:
        logger.error(f"Meeting prep error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/nudges", methods=["GET"])
def atlas_get_nudges():
    """Get proactive engagement suggestions"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        limit = request.args.get('limit', 10, type=int)
        engine = atlas['NudgeEngine']()
        nudges = engine.get_nudges(limit=limit)
        return jsonify({"ok": True, "nudges": nudges})
    except Exception as e:
        logger.error(f"Nudges error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/commitments", methods=["GET"])
def atlas_get_commitments():
    """Get active commitments"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        tracker = atlas['CommitmentTracker']()
        commitments = tracker.get_active_commitments()
        return jsonify({"ok": True, "commitments": commitments})
    except Exception as e:
        logger.error(f"Commitments error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/commitments/<int:commitment_id>", methods=["PATCH"])
def atlas_update_commitment(commitment_id: int):
    """Update a commitment status"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        data = request.get_json()
        tracker = atlas['CommitmentTracker']()
        result = tracker.update_commitment(commitment_id, data)
        return jsonify({"ok": True, "commitment": result})
    except Exception as e:
        logger.error(f"Update commitment error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/interactions", methods=["POST"])
def atlas_log_interaction():
    """Log an interaction with a contact"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available']:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        data = request.get_json()
        tracker = atlas['InteractionTracker']()
        result = tracker.log_interaction(data)
        return jsonify({"ok": True, "interaction": result})
    except Exception as e:
        logger.error(f"Log interaction error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# GMAIL INTEGRATION ENDPOINTS
# =============================================================================

@atlas_bp.route("/gmail/status", methods=["GET"])
def atlas_gmail_status():
    """Get Gmail connection status"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available'] or not atlas['GmailReader']:
        return jsonify({'error': 'Gmail integration not available'}), 503

    try:
        accounts = atlas['GMAIL_ACCOUNTS']
        return jsonify({
            "ok": True,
            "accounts": len(accounts),
            "connected": len(accounts) > 0
        })
    except Exception as e:
        logger.error(f"Gmail status error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/gmail/recent", methods=["GET"])
def atlas_gmail_recent():
    """Get recent emails"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available'] or not atlas['GmailReader']:
        return jsonify({'error': 'Gmail integration not available'}), 503

    try:
        days = request.args.get('days', 7, type=int)
        limit = request.args.get('limit', 50, type=int)

        reader = atlas['GmailReader']()
        emails = reader.get_recent_emails(days=days, limit=limit)
        return jsonify({"ok": True, "emails": emails})
    except Exception as e:
        logger.error(f"Gmail recent error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/gmail/conversation/<path:email>", methods=["GET"])
def atlas_gmail_conversation(email):
    """Get email conversation with a specific contact"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available'] or not atlas['GmailReader']:
        return jsonify({'error': 'Gmail integration not available'}), 503

    try:
        days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 50, type=int)

        reader = atlas['GmailReader']()
        emails = reader.get_conversation_with(email, days=days, limit=limit)
        return jsonify({"ok": True, "email": email, "messages": emails})
    except Exception as e:
        logger.error(f"Gmail conversation error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# PEOPLE API ENDPOINTS
# =============================================================================

@atlas_bp.route("/people/contacts", methods=["GET"])
def atlas_people_contacts():
    """Get contacts from Google People API"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available'] or not atlas['GooglePeopleAPI']:
        return jsonify({'error': 'People API not available'}), 503

    try:
        limit = request.args.get('limit', 100, type=int)
        api = atlas['GooglePeopleAPI']()
        contacts = api.list_contacts(limit=limit)
        return jsonify({"ok": True, "contacts": contacts})
    except Exception as e:
        logger.error(f"People contacts error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/people/search", methods=["GET"])
def atlas_people_search():
    """Search Google People contacts"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available'] or not atlas['GooglePeopleAPI']:
        return jsonify({'error': 'People API not available'}), 503

    try:
        query = request.args.get('q', '')
        if not query:
            return jsonify({'error': 'Query parameter q required'}), 400

        api = atlas['GooglePeopleAPI']()
        results = api.search_contacts(query)
        return jsonify({"ok": True, "query": query, "results": results})
    except Exception as e:
        logger.error(f"People search error: {e}")
        return jsonify({'error': str(e)}), 500


@atlas_bp.route("/people/photo/<path:identifier>", methods=["GET"])
def atlas_people_photo(identifier):
    """Get contact photo from Google People API"""
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    atlas = get_atlas_services()
    if not atlas['available'] or not atlas['GooglePeopleAPI']:
        return jsonify({'error': 'People API not available'}), 503

    try:
        api = atlas['GooglePeopleAPI']()
        photo_url = api.get_photo(identifier)
        return jsonify({"ok": True, "photo_url": photo_url})
    except Exception as e:
        logger.error(f"People photo error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# NOTE: Additional routes will be migrated incrementally
# The following routes remain in viewer_server.py for now:
# - /api/atlas/contacts (CRUD operations)
# - /api/atlas/sync/* (sync operations)
# - /api/atlas/ai/* (AI features)
# - /api/atlas/contacts/bulk-* (bulk operations)
# - /api/atlas/contacts/*-interactions (interaction tracking)
# =============================================================================
