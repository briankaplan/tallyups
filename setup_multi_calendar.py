#!/usr/bin/env python3
"""
Setup Multiple Google Calendar Accounts for Receipt Scanner

This script authorizes multiple Google accounts for calendar access.
The Receipt Scanner will aggregate events from all calendars.

Run this script for EACH Google account you want to add:
  python setup_multi_calendar.py
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Check for required packages
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("\nMissing required packages. Install with:")
    print("   pip install google-auth google-auth-oauthlib google-api-python-client")
    exit(1)

# Paths
BASE_DIR = Path(__file__).parent
MULTI_TOKEN_PATH = BASE_DIR / "calendar_tokens.json"
CREDS_PATH = BASE_DIR / "credentials.json"

# Scopes needed for calendar
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
]


def find_credentials():
    """Find Google OAuth credentials file."""
    locations = [
        CREDS_PATH,
        BASE_DIR / "config/credentials.json",
        BASE_DIR / "client_secrets.json",
        Path.home() / ".config/receipt-ai/credentials.json"
    ]

    for path in locations:
        if path.exists():
            return path

    return None


def load_existing_tokens():
    """Load existing tokens from file."""
    if MULTI_TOKEN_PATH.exists():
        try:
            with open(MULTI_TOKEN_PATH, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"accounts": []}


def save_tokens(tokens):
    """Save tokens to file."""
    with open(MULTI_TOKEN_PATH, 'w') as f:
        json.dump(tokens, f, indent=2)


def get_account_email(creds):
    """Get the email address for the authenticated account."""
    try:
        from googleapiclient.discovery import build
        service = build('oauth2', 'v2', credentials=creds)
        user_info = service.userinfo().get().execute()
        return user_info.get('email', 'unknown')
    except:
        # Fallback: get from calendar
        try:
            service = build('calendar', 'v3', credentials=creds)
            calendar = service.calendars().get(calendarId='primary').execute()
            return calendar.get('id', 'unknown')
        except:
            return 'unknown'


def add_account():
    """Add a new Google account for calendar access."""
    print("\n" + "=" * 60)
    print("Add Google Calendar Account")
    print("=" * 60 + "\n")

    # Load existing tokens
    tokens = load_existing_tokens()
    existing_emails = [acc.get('email', '') for acc in tokens.get('accounts', [])]

    if existing_emails:
        print(f"Already connected accounts: {len(existing_emails)}")
        for email in existing_emails:
            print(f"  - {email}")
        print()

    # Find credentials file
    creds_file = find_credentials()
    if not creds_file:
        print("No credentials.json found!")
        print("\nTo set up Calendar integration:")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create OAuth 2.0 credentials (Desktop application)")
        print("3. Download and save as 'credentials.json' in this directory:")
        print(f"   {BASE_DIR}")
        return False

    print(f"Using credentials from: {creds_file}\n")
    print("A browser window will open for authorization...")
    print("Please select your Google account and allow calendar access.\n")
    print("TIP: If you're logged into multiple accounts, make sure to select")
    print("     the RIGHT account in the browser.\n")

    # Run OAuth flow - use random port to avoid conflicts
    import random
    port = random.randint(8100, 8200)
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=port, open_browser=True)

    # Get the email for this account
    email = get_account_email(creds)

    # Check if already added
    if email in existing_emails:
        print(f"\nAccount {email} is already connected!")
        print("Token will be refreshed.\n")
        # Update the existing token
        for acc in tokens['accounts']:
            if acc.get('email') == email:
                acc['token'] = json.loads(creds.to_json())
                break
    else:
        # Add new account
        tokens['accounts'].append({
            'email': email,
            'token': json.loads(creds.to_json()),
            'added_at': datetime.now(timezone.utc).isoformat()
        })
        print(f"\nAdded account: {email}")

    # Save tokens
    save_tokens(tokens)
    print(f"Tokens saved to: {MULTI_TOKEN_PATH}")

    # Test the connection
    print(f"\nTesting calendar access for {email}...")
    try:
        service = build('calendar', 'v3', credentials=creds)
        calendar = service.calendars().get(calendarId='primary').execute()
        print(f"Connected to calendar: {calendar.get('summary', 'Primary')}")

        # Show upcoming events
        now = datetime.now(timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=3,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if events:
            print(f"\nUpcoming events from {email}:")
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                print(f"   - {event['summary']} ({start[:10]})")
        else:
            print("\n(No upcoming events found)")

    except Exception as e:
        print(f"Calendar test failed: {e}")
        return False

    return True


def list_accounts():
    """List all connected accounts."""
    tokens = load_existing_tokens()
    accounts = tokens.get('accounts', [])

    print("\n" + "=" * 60)
    print("Connected Calendar Accounts")
    print("=" * 60 + "\n")

    if not accounts:
        print("No accounts connected yet.")
        print("Run: python setup_multi_calendar.py add")
        return

    for i, acc in enumerate(accounts, 1):
        print(f"{i}. {acc.get('email', 'unknown')}")
        added = acc.get('added_at', 'unknown')
        if added != 'unknown':
            print(f"   Added: {added[:10]}")


def export_for_railway():
    """Export all tokens for Railway deployment."""
    tokens = load_existing_tokens()
    accounts = tokens.get('accounts', [])

    if not accounts:
        print("\nNo accounts to export. Run 'python setup_multi_calendar.py add' first.")
        return

    print("\n" + "=" * 60)
    print("RAILWAY DEPLOYMENT")
    print("=" * 60)
    print(f"\nExporting {len(accounts)} calendar account(s)...\n")

    # Create compact JSON
    export_data = json.dumps(tokens, separators=(',', ':'))

    print("Set this environment variable on Railway:\n")
    print(f"CALENDAR_TOKENS={export_data}")
    print("\n" + "-" * 60)
    print("\nOr copy the JSON below and paste it as CALENDAR_TOKENS env var:\n")
    print(json.dumps(tokens, indent=2))


def main():
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == 'add':
            add_account()
        elif cmd == 'list':
            list_accounts()
        elif cmd == 'export':
            export_for_railway()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python setup_multi_calendar.py [add|list|export]")
    else:
        # Default: add account
        print("\n" + "=" * 60)
        print("Multi-Calendar Setup for Receipt Scanner")
        print("=" * 60)

        tokens = load_existing_tokens()
        accounts = tokens.get('accounts', [])

        print(f"\nCurrently connected: {len(accounts)} account(s)")
        if accounts:
            for acc in accounts:
                print(f"  - {acc.get('email', 'unknown')}")

        print("\nCommands:")
        print("  python setup_multi_calendar.py add     - Add a new Google account")
        print("  python setup_multi_calendar.py list    - List connected accounts")
        print("  python setup_multi_calendar.py export  - Export tokens for Railway")
        print()

        # Ask if they want to add an account
        response = input("Would you like to add a new account now? (y/n): ")
        if response.lower() in ['y', 'yes']:
            add_account()

            # Ask if they want to add another
            while True:
                response = input("\nAdd another account? (y/n): ")
                if response.lower() in ['y', 'yes']:
                    add_account()
                else:
                    break

            # Export for Railway
            print("\n")
            export_for_railway()


if __name__ == "__main__":
    main()
