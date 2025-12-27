"""
================================================================================
Calendar API Routes
================================================================================
Flask Blueprint for Google Calendar integration.

ENDPOINTS:
----------
    GET  /api/calendar/events           - List calendar events
    POST /api/calendar/events           - Create calendar event
    GET  /api/calendar/events/<id>      - Get event details
    PUT  /api/calendar/events/<id>      - Update event
    DELETE /api/calendar/events/<id>    - Delete event
    GET  /api/calendar/free-busy        - Find available time slots
    POST /api/calendar/receipts-to-block - Auto-block time based on expenses
    GET  /api/calendar/sync/status      - Get calendar sync status
    GET  /api/calendar/accounts         - List connected calendar accounts

================================================================================
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from flask import Blueprint, request, jsonify

# Create blueprint
calendar_bp = Blueprint('calendar', __name__, url_prefix='/api/calendar')

# Logger
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def get_calendar_service():
    """Get the Google Calendar service instance."""
    from services.google_calendar_service import get_calendar_service
    return get_calendar_service()


def get_user_accounts():
    """Get available calendar accounts."""
    return [
        'brian@business.com',
        'kaplan.brian@gmail.com',
        'brian@secondary.com'
    ]


# =============================================================================
# CALENDAR ACCOUNTS
# =============================================================================

@calendar_bp.route('/accounts', methods=['GET'])
def list_accounts():
    """
    List connected calendar accounts.

    Response:
        {
            "success": true,
            "accounts": [
                {"email": "brian@business.com", "connected": true},
                ...
            ]
        }
    """
    try:
        service = get_calendar_service()
        accounts = []

        for email in get_user_accounts():
            cal_service = service.get_calendar_service(email)
            accounts.append({
                'email': email,
                'connected': cal_service is not None
            })

        return jsonify({
            'success': True,
            'accounts': accounts
        })

    except Exception as e:
        logger.error(f"List accounts error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# CALENDAR EVENTS
# =============================================================================

@calendar_bp.route('/events', methods=['GET'])
def list_events():
    """
    List calendar events.

    Query Params:
        account: Email account to use (default: first available)
        start: Start date (ISO format, default: today)
        end: End date (ISO format, default: 7 days from now)
        max_results: Maximum events to return (default: 50)

    Response:
        {
            "success": true,
            "events": [...]
        }
    """
    try:
        account = request.args.get('account', get_user_accounts()[0])
        start = request.args.get('start', datetime.now().isoformat() + 'Z')
        end_date = datetime.now() + timedelta(days=7)
        end = request.args.get('end', end_date.isoformat() + 'Z')
        max_results = int(request.args.get('max_results', 50))

        service = get_calendar_service()
        cal_service = service.get_calendar_service(account)

        if not cal_service:
            return jsonify({
                'success': False,
                'error': f'Calendar not connected for {account}'
            }), 400

        events_result = cal_service.events().list(
            calendarId='primary',
            timeMin=start,
            timeMax=end,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        return jsonify({
            'success': True,
            'account': account,
            'events': [{
                'id': e.get('id'),
                'summary': e.get('summary'),
                'description': e.get('description'),
                'start': e.get('start', {}).get('dateTime') or e.get('start', {}).get('date'),
                'end': e.get('end', {}).get('dateTime') or e.get('end', {}).get('date'),
                'location': e.get('location'),
                'status': e.get('status'),
                'html_link': e.get('htmlLink')
            } for e in events]
        })

    except Exception as e:
        logger.error(f"List events error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/events', methods=['POST'])
def create_event():
    """
    Create a new calendar event.

    Request Body:
        {
            "account": "brian@business.com",
            "title": "Meeting",
            "description": "Team sync",
            "start": "2024-12-21T10:00:00",
            "end": "2024-12-21T11:00:00",
            "location": "Office",
            "reminders": [10, 30]  // Minutes before
        }

    Response:
        {
            "success": true,
            "event": {...}
        }
    """
    try:
        data = request.get_json() or {}
        account = data.get('account', get_user_accounts()[0])

        service = get_calendar_service()

        result = service.block_time(
            account_email=account,
            start_time=datetime.fromisoformat(data['start']),
            end_time=datetime.fromisoformat(data['end']),
            reason=data.get('description', ''),
            title=data.get('title', 'Calendar Event')
        )

        if result.get('status') == 'error':
            return jsonify({'success': False, 'error': result.get('message')}), 400

        return jsonify({
            'success': True,
            'event': result
        })

    except Exception as e:
        logger.error(f"Create event error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/events/<event_id>', methods=['GET'])
def get_event(event_id):
    """Get a specific calendar event."""
    try:
        account = request.args.get('account', get_user_accounts()[0])

        service = get_calendar_service()
        cal_service = service.get_calendar_service(account)

        if not cal_service:
            return jsonify({'success': False, 'error': 'Calendar not connected'}), 400

        event = cal_service.events().get(calendarId='primary', eventId=event_id).execute()

        return jsonify({
            'success': True,
            'event': {
                'id': event.get('id'),
                'summary': event.get('summary'),
                'description': event.get('description'),
                'start': event.get('start', {}).get('dateTime') or event.get('start', {}).get('date'),
                'end': event.get('end', {}).get('dateTime') or event.get('end', {}).get('date'),
                'location': event.get('location'),
                'status': event.get('status'),
                'html_link': event.get('htmlLink')
            }
        })

    except Exception as e:
        logger.error(f"Get event error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/events/<event_id>', methods=['PUT'])
def update_event(event_id):
    """Update a calendar event."""
    try:
        data = request.get_json() or {}
        account = data.get('account', get_user_accounts()[0])

        service = get_calendar_service()
        cal_service = service.get_calendar_service(account)

        if not cal_service:
            return jsonify({'success': False, 'error': 'Calendar not connected'}), 400

        # Get existing event
        event = cal_service.events().get(calendarId='primary', eventId=event_id).execute()

        # Update fields
        if 'title' in data:
            event['summary'] = data['title']
        if 'description' in data:
            event['description'] = data['description']
        if 'start' in data:
            event['start'] = {'dateTime': data['start'], 'timeZone': 'America/Chicago'}
        if 'end' in data:
            event['end'] = {'dateTime': data['end'], 'timeZone': 'America/Chicago'}
        if 'location' in data:
            event['location'] = data['location']

        updated = cal_service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=event
        ).execute()

        return jsonify({
            'success': True,
            'event': {
                'id': updated.get('id'),
                'summary': updated.get('summary'),
                'html_link': updated.get('htmlLink')
            }
        })

    except Exception as e:
        logger.error(f"Update event error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/events/<event_id>', methods=['DELETE'])
def delete_event(event_id):
    """Delete a calendar event."""
    try:
        account = request.args.get('account', get_user_accounts()[0])

        service = get_calendar_service()
        cal_service = service.get_calendar_service(account)

        if not cal_service:
            return jsonify({'success': False, 'error': 'Calendar not connected'}), 400

        cal_service.events().delete(calendarId='primary', eventId=event_id).execute()

        return jsonify({
            'success': True,
            'message': f'Event {event_id} deleted'
        })

    except Exception as e:
        logger.error(f"Delete event error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# FREE/BUSY & RECEIPT CONTEXT
# =============================================================================

@calendar_bp.route('/free-busy', methods=['GET'])
def get_free_busy():
    """
    Find available time slots.

    Query Params:
        account: Email account
        start: Start datetime (ISO)
        end: End datetime (ISO)
        duration: Desired slot duration in minutes (default: 30)

    Response:
        {
            "success": true,
            "busy": [...],
            "available_slots": [
                {"start": "...", "end": "..."},
                ...
            ]
        }
    """
    try:
        account = request.args.get('account', get_user_accounts()[0])
        start = request.args.get('start', datetime.now().isoformat() + 'Z')
        end_date = datetime.now() + timedelta(days=1)
        end = request.args.get('end', end_date.isoformat() + 'Z')
        duration = int(request.args.get('duration', 30))

        service = get_calendar_service()
        cal_service = service.get_calendar_service(account)

        if not cal_service:
            return jsonify({'success': False, 'error': 'Calendar not connected'}), 400

        body = {
            "timeMin": start,
            "timeMax": end,
            "items": [{"id": "primary"}]
        }

        freebusy = cal_service.freebusy().query(body=body).execute()
        busy = freebusy.get('calendars', {}).get('primary', {}).get('busy', [])

        return jsonify({
            'success': True,
            'account': account,
            'busy': busy,
            'time_range': {'start': start, 'end': end}
        })

    except Exception as e:
        logger.error(f"Free/busy error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/receipts-to-block', methods=['POST'])
def block_time_for_receipts():
    """
    Auto-block calendar time based on expense receipts.

    Creates calendar blocks for business trips, meetings, etc.
    based on receipt patterns (hotels, flights, restaurants).

    Request Body:
        {
            "account": "brian@business.com",
            "business_type": "Business",
            "date_range": {"start": "2024-12-01", "end": "2024-12-31"},
            "create_events": true
        }

    Response:
        {
            "success": true,
            "suggestions": [...],
            "events_created": 3
        }
    """
    try:
        data = request.get_json() or {}
        account = data.get('account', get_user_accounts()[0])
        business_type = data.get('business_type')
        date_range = data.get('date_range', {})
        create_events = data.get('create_events', False)

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        # Find receipts that suggest time blocks (hotels, flights, restaurants for meetings)
        with db._pool.connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT id, chase_date, chase_description, chase_amount, r2_url
                FROM transactions
                WHERE (
                    LOWER(chase_description) LIKE '%hotel%'
                    OR LOWER(chase_description) LIKE '%hilton%'
                    OR LOWER(chase_description) LIKE '%marriott%'
                    OR LOWER(chase_description) LIKE '%airbnb%'
                    OR LOWER(chase_description) LIKE '%airline%'
                    OR LOWER(chase_description) LIKE '%delta%'
                    OR LOWER(chase_description) LIKE '%united%'
                    OR LOWER(chase_description) LIKE '%american air%'
                )
                AND r2_url IS NOT NULL
            """
            params = []

            if business_type:
                query += " AND business_type = %s"
                params.append(business_type)

            if date_range.get('start'):
                query += " AND chase_date >= %s"
                params.append(date_range['start'])
            if date_range.get('end'):
                query += " AND chase_date <= %s"
                params.append(date_range['end'])

            query += " ORDER BY chase_date"
            cursor.execute(query, params)

            suggestions = []
            events_created = 0

            for row in cursor.fetchall():
                receipt_id, date, desc, amount, url = row

                # Determine event type and duration
                desc_lower = desc.lower()
                if any(h in desc_lower for h in ['hotel', 'hilton', 'marriott', 'airbnb']):
                    event_type = 'hotel_stay'
                    title = f"Business Trip - {desc}"
                    duration_hours = 24
                elif any(a in desc_lower for a in ['airline', 'delta', 'united', 'american']):
                    event_type = 'flight'
                    title = f"Travel - {desc}"
                    duration_hours = 4
                else:
                    event_type = 'expense'
                    title = f"Business Expense - {desc}"
                    duration_hours = 2

                suggestion = {
                    'receipt_id': receipt_id,
                    'date': str(date),
                    'description': desc,
                    'amount': float(amount),
                    'event_type': event_type,
                    'suggested_title': title,
                    'suggested_duration_hours': duration_hours
                }
                suggestions.append(suggestion)

                # Create event if requested
                if create_events:
                    service = get_calendar_service()
                    start_time = datetime.combine(date, datetime.min.time().replace(hour=9))
                    end_time = start_time + timedelta(hours=duration_hours)

                    result = service.block_time(
                        account_email=account,
                        start_time=start_time,
                        end_time=end_time,
                        reason=f"Auto-created from receipt: ${abs(amount):.2f}",
                        title=title
                    )

                    if result.get('status') == 'success':
                        events_created += 1
                        suggestion['event_id'] = result.get('event_id')

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'events_created': events_created
        })

    except Exception as e:
        logger.error(f"Receipts-to-block error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/sync/status', methods=['GET'])
def get_sync_status():
    """Get calendar sync status for all accounts."""
    try:
        service = get_calendar_service()
        status = []

        for email in get_user_accounts():
            cal_service = service.get_calendar_service(email)
            status.append({
                'account': email,
                'connected': cal_service is not None,
                'last_sync': None  # Would track in DB
            })

        return jsonify({
            'success': True,
            'accounts': status
        })

    except Exception as e:
        logger.error(f"Sync status error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def register_calendar_routes(app):
    """Register calendar routes with the Flask app."""
    app.register_blueprint(calendar_bp)
    logger.info("Calendar routes registered at /api/calendar/*")
