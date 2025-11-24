"""
Google Calendar Service
Blocks time on Google Calendar automatically
"""

import os
import pickle
from datetime import datetime, timedelta
from typing import Optional, Dict
from pathlib import Path

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    print("⚠️ Google API client not installed. Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")


class GoogleCalendarService:
    """
    Service to block time on Google Calendar
    Uses same OAuth tokens as Gmail
    """

    def __init__(self, credentials_dir: str = 'credentials'):
        self.credentials_dir = Path(credentials_dir)
        self.services = {}  # Cache calendar services per account

    def get_calendar_service(self, account_email: str):
        """
        Get authenticated Calendar API service for account
        Uses existing Gmail OAuth tokens
        """
        if not GOOGLE_AVAILABLE:
            return None

        # Check if already cached
        if account_email in self.services:
            return self.services[account_email]

        # Try JSON token first (newer format with refresh tokens)
        token_path_json = self.credentials_dir / f'tokens_{account_email.replace("@", "_").replace(".", "_")}.json'
        token_path_pickle = self.credentials_dir / f'token_{account_email}.pickle'

        token_path = None
        if token_path_json.exists():
            token_path = token_path_json
        elif token_path_pickle.exists():
            token_path = token_path_pickle

        if not token_path:
            print(f"⚠️ No token found for {account_email}. Run Gmail auth first.")
            return None

        try:
            # Load credentials from JSON or pickle
            if str(token_path).endswith('.json'):
                creds = Credentials.from_authorized_user_file(str(token_path))
            else:
                with open(token_path, 'rb') as token:
                    creds = pickle.load(token)

            # Refresh if expired
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                if str(token_path).endswith('.json'):
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
                else:
                    with open(token_path, 'wb') as token:
                        pickle.dump(creds, token)

            # Build Calendar service
            service = build('calendar', 'v3', credentials=creds)
            self.services[account_email] = service

            print(f"✅ Calendar service authenticated for {account_email}")
            return service

        except Exception as e:
            print(f"❌ Failed to authenticate Calendar for {account_email}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def block_time(
        self,
        account_email: str,
        start_time: datetime,
        end_time: datetime,
        reason: str,
        title: str = "Protected Time"
    ) -> Optional[Dict]:
        """
        Block time on Google Calendar

        Args:
            account_email: Which Google account to use
            start_time: Start datetime
            end_time: End datetime
            reason: Why time is being blocked
            title: Event title

        Returns:
            Event details if successful
        """
        service = self.get_calendar_service(account_email)

        if not service:
            return {
                'status': 'error',
                'message': f'Calendar service not available for {account_email}'
            }

        try:
            # Create event
            event = {
                'summary': title,
                'description': reason,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'America/Chicago',  # Brian's timezone
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'America/Chicago',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
                'transparency': 'opaque',  # Shows as busy
                'visibility': 'private',
            }

            # Insert event
            result = service.events().insert(calendarId='primary', body=event).execute()

            print(f"✅ Calendar event created: {result.get('htmlLink')}")

            return {
                'status': 'success',
                'event_id': result.get('id'),
                'event_link': result.get('htmlLink'),
                'start': start_time.isoformat(),
                'end': end_time.isoformat(),
                'title': title,
                'reason': reason
            }

        except Exception as e:
            print(f"❌ Failed to create calendar event: {e}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'error',
                'message': str(e)
            }

    def parse_time_string(self, time_str: str, reference_date: Optional[datetime] = None) -> datetime:
        """
        Parse time strings like "6pm" into datetime

        Args:
            time_str: Time string (e.g., "6pm", "18:00", "6:30pm")
            reference_date: Date to use (defaults to today)

        Returns:
            datetime object
        """
        if reference_date is None:
            reference_date = datetime.now()

        time_str = time_str.lower().strip()

        # Handle common formats
        try:
            # Format: "6pm", "6:30pm"
            if 'pm' in time_str or 'am' in time_str:
                # Remove spaces
                time_str = time_str.replace(' ', '')

                # Parse with am/pm
                if ':' in time_str:
                    parsed = datetime.strptime(time_str, '%I:%M%p')
                else:
                    parsed = datetime.strptime(time_str, '%I%p')

                # Combine with reference date
                return reference_date.replace(
                    hour=parsed.hour,
                    minute=parsed.minute,
                    second=0,
                    microsecond=0
                )

            # Format: "18:00" (24-hour)
            elif ':' in time_str:
                hour, minute = map(int, time_str.split(':'))
                return reference_date.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0
                )

            # Format: "18" (hour only)
            else:
                hour = int(time_str)
                return reference_date.replace(
                    hour=hour,
                    minute=0,
                    second=0,
                    microsecond=0
                )

        except Exception as e:
            print(f"⚠️ Failed to parse time '{time_str}': {e}")
            # Default to reference time
            return reference_date

    def block_evening_time(
        self,
        account_email: str,
        reason: str = "Family time - protected by AI"
    ) -> Optional[Dict]:
        """
        Convenience method to block evening time (6pm-9pm)

        Args:
            account_email: Which Google account
            reason: Why time is being blocked

        Returns:
            Event details if successful
        """
        now = datetime.now()

        # If it's already past 6pm, block for tomorrow
        if now.hour >= 18:
            start = now + timedelta(days=1)
        else:
            start = now

        start = start.replace(hour=18, minute=0, second=0, microsecond=0)
        end = start.replace(hour=21, minute=0)  # 9pm

        return self.block_time(
            account_email=account_email,
            start_time=start,
            end_time=end,
            reason=reason,
            title="🛡️ Protected Family Time"
        )


# Singleton instance
_calendar_service = None


def get_calendar_service(credentials_dir: str = 'credentials') -> GoogleCalendarService:
    """Get or create GoogleCalendarService singleton"""
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = GoogleCalendarService(credentials_dir)
    return _calendar_service
