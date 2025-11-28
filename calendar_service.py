#!/usr/bin/env python3
"""
Google Calendar Service for Receipt Context
Fetches calendar events from MULTIPLE Google accounts to provide AI context.

Supports:
- Single account (CALENDAR_TOKEN env var or calendar_token.json)
- Multiple accounts (CALENDAR_TOKENS env var or calendar_tokens.json)
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict

# Token paths
BASE_DIR = Path(__file__).parent
CALENDAR_TOKEN_PATH = BASE_DIR / "calendar_token.json"
MULTI_TOKEN_PATH = BASE_DIR / "calendar_tokens.json"
GMAIL_TOKENS_DIR = BASE_DIR.parent / "Task/receipt-system/gmail_tokens"

# OAuth scopes needed
CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
]


def get_all_calendar_services() -> List[Dict]:
    """
    Get calendar services for ALL connected accounts.

    Returns list of {'email': str, 'service': CalendarService}
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        services = []

        # Try multi-account tokens first (CALENDAR_TOKENS)
        env_tokens = os.getenv('CALENDAR_TOKENS')
        if env_tokens:
            try:
                tokens_data = json.loads(env_tokens)
                accounts = tokens_data.get('accounts', [])
                for acc in accounts:
                    token_data = acc.get('token', {})
                    email = acc.get('email', 'unknown')
                    try:
                        creds = Credentials.from_authorized_user_info(token_data)
                        if creds.expired and creds.refresh_token:
                            creds.refresh(Request())
                        service = build('calendar', 'v3', credentials=creds)
                        services.append({'email': email, 'service': service})
                        print(f"Calendar: Loaded {email} from CALENDAR_TOKENS")
                    except Exception as e:
                        print(f"Calendar: Failed to load {email}: {e}")
                if services:
                    return services
            except Exception as e:
                print(f"Calendar: Could not parse CALENDAR_TOKENS: {e}")

        # Try multi-account file
        if MULTI_TOKEN_PATH.exists():
            try:
                with open(MULTI_TOKEN_PATH, 'r') as f:
                    tokens_data = json.load(f)
                accounts = tokens_data.get('accounts', [])
                for acc in accounts:
                    token_data = acc.get('token', {})
                    email = acc.get('email', 'unknown')
                    try:
                        creds = Credentials.from_authorized_user_info(token_data)
                        if creds.expired and creds.refresh_token:
                            creds.refresh(Request())
                        service = build('calendar', 'v3', credentials=creds)
                        services.append({'email': email, 'service': service})
                        print(f"Calendar: Loaded {email} from file")
                    except Exception as e:
                        print(f"Calendar: Failed to load {email}: {e}")
                if services:
                    return services
            except Exception as e:
                print(f"Calendar: Could not load multi-token file: {e}")

        # Fall back to single account (CALENDAR_TOKEN)
        env_token = os.getenv('CALENDAR_TOKEN')
        if env_token:
            try:
                token_data = json.loads(env_token)
                creds = Credentials.from_authorized_user_info(token_data)
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                service = build('calendar', 'v3', credentials=creds)
                # Get email from calendar
                try:
                    calendar = service.calendars().get(calendarId='primary').execute()
                    email = calendar.get('id', 'primary')
                except:
                    email = 'primary'
                services.append({'email': email, 'service': service})
                print(f"Calendar: Loaded from CALENDAR_TOKEN env var")
                return services
            except Exception as e:
                print(f"Calendar: Could not load from env var: {e}")

        # Fall back to single token file
        if CALENDAR_TOKEN_PATH.exists():
            try:
                with open(CALENDAR_TOKEN_PATH, 'r') as f:
                    token_data = json.load(f)
                creds = Credentials.from_authorized_user_info(token_data)
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                service = build('calendar', 'v3', credentials=creds)
                try:
                    calendar = service.calendars().get(calendarId='primary').execute()
                    email = calendar.get('id', 'primary')
                except:
                    email = 'primary'
                services.append({'email': email, 'service': service})
                print(f"Calendar: Loaded from token file")
                return services
            except Exception as e:
                print(f"Calendar: Could not load from file: {e}")

        return services

    except ImportError as e:
        print(f"Calendar: Missing google libraries: {e}")
        return []
    except Exception as e:
        print(f"Calendar service error: {e}")
        return []


def get_calendar_service():
    """Get a single calendar service (backwards compatibility)."""
    services = get_all_calendar_services()
    if services:
        return services[0]['service']
    return None


def get_enabled_calendars() -> List[str]:
    """Get list of enabled calendar emails from preferences file."""
    prefs_file = BASE_DIR / "calendar_preferences.json"
    if prefs_file.exists():
        try:
            with open(prefs_file, 'r') as f:
                prefs = json.load(f)
            return prefs.get('enabled_calendars', [])
        except:
            pass
    return []  # Empty list means all calendars


def get_events_around_date(receipt_date: str, days_before: int = 1, days_after: int = 1) -> list:
    """
    Fetch calendar events around a receipt date from ENABLED accounts only.

    Args:
        receipt_date: Date in YYYY-MM-DD format
        days_before: Days before to search
        days_after: Days after to search

    Returns:
        List of event summaries with times (aggregated from enabled calendars)
    """
    try:
        services = get_all_calendar_services()
        if not services:
            return []

        # Get enabled calendars (empty list = all enabled)
        enabled_calendars = get_enabled_calendars()

        # Parse date
        date_obj = None
        for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d']:
            try:
                date_obj = datetime.strptime(receipt_date, fmt)
                break
            except ValueError:
                continue

        if not date_obj:
            return []

        # Calculate time range
        time_min = (date_obj - timedelta(days=days_before)).isoformat() + 'Z'
        time_max = (date_obj + timedelta(days=days_after + 1)).isoformat() + 'Z'

        # Aggregate events from enabled accounts only
        all_events = []

        for svc in services:
            email = svc['email']
            service = svc['service']

            # Skip if not in enabled list (unless list is empty = all enabled)
            if enabled_calendars and email not in enabled_calendars:
                continue

            try:
                events_result = service.events().list(
                    calendarId='primary',
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=20,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                events = events_result.get('items', [])

                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    summary = event.get('summary', 'Untitled event')
                    location = event.get('location', '')
                    description = event.get('description', '')

                    event_info = {
                        'title': summary,
                        'start': start,
                        'location': location,
                        'description': description[:200] if description else '',
                        'calendar': email  # Track which calendar it came from
                    }
                    all_events.append(event_info)

            except Exception as e:
                print(f"Calendar: Error fetching from {email}: {e}")

        # Sort all events by start time
        all_events.sort(key=lambda x: x.get('start', ''))

        return all_events

    except Exception as e:
        print(f"Error fetching calendar events: {e}")
        return []


def format_events_for_prompt(events: list) -> str:
    """Format events list into a string for AI prompt."""
    if not events:
        return ""

    lines = ["Calendar events around this date:"]
    for event in events:
        line = f"- {event['title']}"
        if event.get('location'):
            line += f" (Location: {event['location']})"
        if event.get('start'):
            start_str = event['start']
            if 'T' in start_str:
                start_str = start_str.split('T')[1][:5]  # Get HH:MM
                line += f" at {start_str}"
        lines.append(line)

    return "\n".join(lines)


def generate_contextual_note(
    merchant: str,
    amount: str,
    receipt_date: str,
    category: str = None,
    location: str = None
) -> Optional[str]:
    """
    Generate a contextual note for a receipt based on calendar events.

    This is used by the OCR endpoint to enhance receipt notes.
    """
    events = get_events_around_date(receipt_date)

    if not events:
        return None

    # Simple heuristic matching
    merchant_lower = merchant.lower() if merchant else ""
    amount_float = 0
    try:
        amount_float = float(str(amount).replace('$', '').replace(',', ''))
    except:
        pass

    # Check for travel-related expenses
    travel_keywords = ['trip', 'travel', 'flight', 'conference', 'rodeo', 'competition', 'meeting', 'vegas']
    transport_merchants = ['uber', 'lyft', 'taxi', 'parking', 'gas', 'shell', 'exxon', 'chevron', 'spirit', 'southwest', 'american', 'delta', 'united']

    # Match transport receipts to travel events
    if any(kw in merchant_lower for kw in transport_merchants):
        for event in events:
            if any(kw in event['title'].lower() for kw in travel_keywords):
                return f"{merchant} - {event['title']}"

    # Match restaurants to lunch/dinner meetings
    food_categories = ['food', 'dining', 'restaurant']
    if category and any(cat in category.lower() for cat in food_categories):
        for event in events:
            if any(kw in event['title'].lower() for kw in ['lunch', 'dinner', 'meeting', 'coffee', 'breakfast']):
                return event['title']

    # Match parking to events with locations
    if 'parking' in merchant_lower:
        for event in events:
            if event.get('location'):
                return f"Parking - {event['title']}"

    return None


def get_calendar_status() -> Dict:
    """Get status of all connected calendars."""
    services = get_all_calendar_services()

    status = {
        'connected': len(services) > 0,
        'account_count': len(services),
        'accounts': []
    }

    for svc in services:
        email = svc['email']
        try:
            calendar = svc['service'].calendars().get(calendarId='primary').execute()
            status['accounts'].append({
                'email': email,
                'name': calendar.get('summary', 'Primary'),
                'connected': True
            })
        except Exception as e:
            status['accounts'].append({
                'email': email,
                'connected': False,
                'error': str(e)
            })

    return status


# Test function
if __name__ == "__main__":
    print("Testing Multi-Calendar Service...")
    print("-" * 50)

    # Check status
    status = get_calendar_status()
    print(f"\nConnected accounts: {status['account_count']}")
    for acc in status['accounts']:
        print(f"  - {acc['email']}: {acc.get('name', 'N/A')}")

    # Test with today's date
    today = datetime.now().strftime('%Y-%m-%d')
    events = get_events_around_date(today, days_before=3, days_after=3)

    if events:
        print(f"\nFound {len(events)} events around {today}:")
        for event in events:
            calendar = event.get('calendar', 'unknown')
            print(f"  - [{calendar}] {event['title']} ({event['start'][:10]})")
            if event.get('location'):
                print(f"    Location: {event['location']}")
    else:
        print("\nNo events found (or calendar not connected)")

    print("-" * 50)
    print("\nTo connect calendars, run: python setup_multi_calendar.py")
