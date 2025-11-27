#!/usr/bin/env python3
"""
Google Calendar Service for Receipt Context
Fetches calendar events to provide AI with context for receipt notes.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Calendar token path
CALENDAR_TOKEN_PATH = Path(__file__).parent / "calendar_token.json"
GMAIL_TOKENS_DIR = Path(__file__).parent.parent / "Task/receipt-system/gmail_tokens"

# OAuth scopes needed
CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/gmail.readonly'
]


def get_calendar_service():
    """Get or create Google Calendar API service."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None
        token_data = None

        # Try to load from environment variable first (for Railway)
        env_token = os.getenv('CALENDAR_TOKEN')
        if env_token:
            try:
                token_data = json.loads(env_token)
                creds = Credentials.from_authorized_user_info(token_data)
                print("✅ Calendar: Loaded token from CALENDAR_TOKEN env var")
            except Exception as e:
                print(f"⚠️ Calendar: Could not load from env var: {e}")

        # Fall back to file
        if not creds and CALENDAR_TOKEN_PATH.exists():
            with open(CALENDAR_TOKEN_PATH, 'r') as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data)
            print("✅ Calendar: Loaded token from file")

        # If no valid creds, try to use existing Gmail token with calendar scope added
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                with open(CALENDAR_TOKEN_PATH, 'w') as f:
                    json.dump(json.loads(creds.to_json()), f)
            else:
                # Check for credentials.json
                creds_path = Path(__file__).parent / "credentials.json"
                if not creds_path.exists():
                    # Try alternate location
                    creds_path = GMAIL_TOKENS_DIR / "credentials.json"

                if creds_path.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(creds_path), CALENDAR_SCOPES
                    )
                    creds = flow.run_local_server(port=8099)

                    # Save the token
                    with open(CALENDAR_TOKEN_PATH, 'w') as f:
                        json.dump(json.loads(creds.to_json()), f)
                else:
                    print("No credentials.json found for Calendar auth")
                    return None

        return build('calendar', 'v3', credentials=creds)

    except Exception as e:
        print(f"Calendar service error: {e}")
        return None


def get_events_around_date(receipt_date: str, days_before: int = 1, days_after: int = 1) -> list:
    """
    Fetch calendar events around a receipt date.

    Args:
        receipt_date: Date in YYYY-MM-DD format
        days_before: Days before to search
        days_after: Days after to search

    Returns:
        List of event summaries with times
    """
    try:
        service = get_calendar_service()
        if not service:
            return []

        # Parse date
        try:
            date_obj = datetime.strptime(receipt_date, '%Y-%m-%d')
        except ValueError:
            # Try other formats
            for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d']:
                try:
                    date_obj = datetime.strptime(receipt_date, fmt)
                    break
                except ValueError:
                    continue
            else:
                return []

        # Calculate time range
        time_min = (date_obj - timedelta(days=days_before)).isoformat() + 'Z'
        time_max = (date_obj + timedelta(days=days_after + 1)).isoformat() + 'Z'

        # Fetch events from primary calendar
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            maxResults=20,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        # Format events for AI context
        formatted_events = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Untitled event')
            location = event.get('location', '')
            description = event.get('description', '')

            event_info = {
                'title': summary,
                'start': start,
                'location': location,
                'description': description[:200] if description else ''  # Truncate long descriptions
            }
            formatted_events.append(event_info)

        return formatted_events

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
        if event['location']:
            line += f" (Location: {event['location']})"
        if event['start']:
            # Extract just the date/time portion
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
    amount_float = float(amount.replace('$', '').replace(',', '')) if amount else 0

    for event in events:
        title_lower = event['title'].lower()
        location_lower = (event['location'] or '').lower()

        # Check for travel-related expenses
        travel_keywords = ['trip', 'travel', 'flight', 'conference', 'rodeo', 'competition', 'meeting']
        transport_merchants = ['uber', 'lyft', 'taxi', 'parking', 'gas', 'shell', 'exxon', 'chevron']

        # Match transport receipts to travel events
        if any(kw in merchant_lower for kw in transport_merchants):
            for event in events:
                if any(kw in event['title'].lower() for kw in travel_keywords):
                    return f"{merchant} - {event['title']}"

        # Match restaurants to lunch/dinner meetings
        food_categories = ['food', 'dining', 'restaurant']
        if category and any(cat in category.lower() for cat in food_categories):
            for event in events:
                if any(kw in event['title'].lower() for kw in ['lunch', 'dinner', 'meeting', 'coffee']):
                    return event['title']

        # Match parking to events with locations
        if 'parking' in merchant_lower:
            for event in events:
                if event['location']:
                    return f"Parking - {event['title']}"

    return None


# Test function
if __name__ == "__main__":
    print("Testing Calendar Service...")
    print("-" * 50)

    # Test with today's date
    today = datetime.now().strftime('%Y-%m-%d')
    events = get_events_around_date(today, days_before=3, days_after=3)

    if events:
        print(f"Found {len(events)} events around {today}:")
        for event in events:
            print(f"  - {event['title']} ({event['start']})")
            if event['location']:
                print(f"    Location: {event['location']}")
    else:
        print("No events found (or calendar not connected)")

    print("-" * 50)
    print("\nTo connect calendar, run this script directly.")
    print("It will open a browser for Google OAuth.")
