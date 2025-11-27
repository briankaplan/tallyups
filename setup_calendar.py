#!/usr/bin/env python3
"""
Setup Google Calendar Integration for Receipt Scanner

This script authorizes the Receipt Scanner to access your Google Calendar
for contextual expense notes.

Run this once to connect your calendar:
  python setup_calendar.py
"""

import json
import os
from pathlib import Path

# Check for required packages
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("\n❌ Missing required packages. Install with:")
    print("   pip install google-auth google-auth-oauthlib google-api-python-client")
    exit(1)

# Paths
BASE_DIR = Path(__file__).parent
TOKEN_PATH = BASE_DIR / "calendar_token.json"
CREDS_PATH = BASE_DIR / "credentials.json"
GMAIL_TOKENS_DIR = BASE_DIR.parent / "Task/receipt-system/gmail_tokens"

# Scopes needed for calendar
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
]


def find_credentials():
    """Find Google OAuth credentials file."""
    # Check multiple locations
    locations = [
        CREDS_PATH,
        GMAIL_TOKENS_DIR / "credentials.json",
        BASE_DIR / "client_secrets.json",
        Path.home() / ".config/receipt-ai/credentials.json"
    ]

    for path in locations:
        if path.exists():
            return path

    return None


def setup_calendar():
    """Authorize access to Google Calendar."""
    print("\n" + "=" * 60)
    print("📅 Google Calendar Setup for Receipt Scanner")
    print("=" * 60 + "\n")

    # Check for existing token
    creds = None
    if TOKEN_PATH.exists():
        print("Found existing calendar token...")
        try:
            with open(TOKEN_PATH, 'r') as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data)
            print("✅ Token loaded successfully\n")
        except Exception as e:
            print(f"⚠️  Token invalid: {e}\n")
            creds = None

    # Check if token needs refresh
    if creds and creds.expired and creds.refresh_token:
        print("Token expired, refreshing...")
        creds.refresh(Request())
        with open(TOKEN_PATH, 'w') as f:
            json.dump(json.loads(creds.to_json()), f, indent=2)
        print("✅ Token refreshed\n")

    # If no valid creds, need to authorize
    if not creds or not creds.valid:
        print("Need to authorize calendar access.\n")

        # Find credentials file
        creds_file = find_credentials()
        if not creds_file:
            print("❌ No credentials.json found!")
            print("\nTo set up Calendar integration:")
            print("1. Go to https://console.cloud.google.com/apis/credentials")
            print("2. Create OAuth 2.0 credentials (Desktop application)")
            print("3. Download and save as 'credentials.json' in this directory:")
            print(f"   {BASE_DIR}")
            print("\nAlternatively, copy your existing Gmail credentials.json")
            return False

        print(f"Using credentials from: {creds_file}\n")
        print("A browser window will open for authorization...")
        print("Please select your Google account and allow calendar access.\n")

        flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
        creds = flow.run_local_server(port=8099, open_browser=True)

        # Save the token
        with open(TOKEN_PATH, 'w') as f:
            json.dump(json.loads(creds.to_json()), f, indent=2)
        print(f"\n✅ Token saved to: {TOKEN_PATH}")

    # Test the connection
    print("\nTesting calendar access...")
    try:
        service = build('calendar', 'v3', credentials=creds)
        calendar = service.calendars().get(calendarId='primary').execute()
        print(f"✅ Connected to calendar: {calendar.get('summary', 'Primary')}")

        # Show some upcoming events
        from datetime import datetime, timedelta
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if events:
            print(f"\n📅 Your upcoming events:")
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                print(f"   • {event['summary']} ({start[:10]})")
        else:
            print("\n(No upcoming events found)")

        print("\n" + "=" * 60)
        print("✅ Calendar integration is ready!")
        print("=" * 60)
        print("\nWhen you scan receipts, the AI will now use your calendar")
        print("events to generate contextual notes like:")
        print("   • 'Lunch with James Stewart - Business Development'")
        print("   • 'Uber - Dallas trip for American Rodeo'")
        print("   • 'Parking - Emma's Dance Competition'")

        # Export for Railway
        print("\n" + "=" * 60)
        print("🚀 FOR RAILWAY DEPLOYMENT:")
        print("=" * 60)
        with open(TOKEN_PATH, 'r') as f:
            token_json = f.read()

        # Escape for shell
        escaped = token_json.replace('"', '\\"')
        print("\nRun this command to set CALENDAR_TOKEN on Railway:\n")
        print(f'railway variables set CALENDAR_TOKEN=\'{token_json}\'')
        print("\nOr copy this JSON and paste it as CALENDAR_TOKEN env var:\n")
        print(token_json)
        print("\n")
        return True

    except Exception as e:
        print(f"\n❌ Calendar test failed: {e}")
        return False


if __name__ == "__main__":
    setup_calendar()
