#!/usr/bin/env python3
"""
EMAIL FILTER FIX
================
Fixes the problem where all filters archive emails (remove from inbox).

This script offers options:
1. MODIFY filters to KEEP in inbox + add labels (recommended)
2. DELETE all archive filters
3. Restore recent archived emails to inbox

Run: python email_filter_fix.py
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False

TOKEN_DIR = Path(__file__).parent / "gmail_tokens"
CREDENTIALS_FILE = Path(__file__).parent / "config" / "credentials.json"
BACKUP_DIR = Path(__file__).parent / "email_backups"

ACCOUNTS = {
    'kaplan.brian@gmail.com': {
        'token_file': 'tokens_kaplan_brian_gmail_com.json',
        'type': 'Personal'
    },
    'brian@downhome.com': {
        'token_file': 'tokens_brian_downhome_com.json',
        'type': 'Business (Down Home)'
    },
    'brian@musiccityrodeo.com': {
        'token_file': 'tokens_brian_musiccityrodeo_com.json',
        'type': 'Business (MCR)'
    }
}


class EmailFilterFix:
    """Fix email filters that hide emails"""

    def __init__(self):
        self.services = {}
        BACKUP_DIR.mkdir(exist_ok=True)

    def authenticate(self, account: str) -> bool:
        """Authenticate a Gmail account"""
        if account not in ACCOUNTS:
            return False

        config = ACCOUNTS[account]
        token_path = TOKEN_DIR / config['token_file']

        if not token_path.exists() or not CREDENTIALS_FILE.exists():
            return False

        try:
            with open(CREDENTIALS_FILE, 'r') as f:
                creds_data = json.load(f)

            client_config = creds_data.get('web') or creds_data.get('installed', {})
            client_id = client_config.get('client_id')
            client_secret = client_config.get('client_secret')

            with open(token_path, 'r') as f:
                token_data = json.load(f)

            creds = Credentials(
                token=token_data.get('access_token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_id,
                client_secret=client_secret,
                scopes=token_data.get('scope', '').split()
            )

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_data['access_token'] = creds.token
                with open(token_path, 'w') as f:
                    json.dump(token_data, f, indent=2)

            self.services[account] = build('gmail', 'v1', credentials=creds)
            return True
        except Exception as e:
            print(f"   ❌ Auth error: {e}")
            return False

    def backup_filters(self, account: str) -> str:
        """Backup all filters before making changes"""
        if account not in self.services:
            return None

        try:
            filters = self.services[account].users().settings().filters().list(
                userId='me'
            ).execute().get('filter', [])

            backup_file = BACKUP_DIR / f"{account.replace('@', '_at_')}_filters_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            with open(backup_file, 'w') as f:
                json.dump({
                    'account': account,
                    'backed_up_at': datetime.now().isoformat(),
                    'filter_count': len(filters),
                    'filters': filters
                }, f, indent=2)

            print(f"   💾 Backed up {len(filters)} filters to {backup_file}")
            return str(backup_file)

        except Exception as e:
            print(f"   ❌ Backup error: {e}")
            return None

    def get_filters(self, account: str) -> list:
        """Get all filters"""
        if account not in self.services:
            return []
        try:
            return self.services[account].users().settings().filters().list(
                userId='me'
            ).execute().get('filter', [])
        except:
            return []

    def delete_filter(self, account: str, filter_id: str) -> bool:
        """Delete a single filter"""
        try:
            self.services[account].users().settings().filters().delete(
                userId='me', id=filter_id
            ).execute()
            return True
        except Exception as e:
            print(f"      ❌ Error deleting filter: {e}")
            return False

    def create_filter(self, account: str, criteria: dict, action: dict) -> bool:
        """Create a new filter"""
        try:
            self.services[account].users().settings().filters().create(
                userId='me',
                body={'criteria': criteria, 'action': action}
            ).execute()
            return True
        except Exception as e:
            print(f"      ❌ Error creating filter: {e}")
            return False

    def fix_archive_filters(self, account: str, execute: bool = False):
        """
        Fix filters that archive emails.

        Instead of: removeLabelIds: [INBOX], addLabelIds: [Receipts]
        Change to:  addLabelIds: [Receipts] (keeps in inbox)
        """
        print(f"\n{'='*60}")
        print(f"🔧 FIXING FILTERS: {account}")
        print(f"{'='*60}")

        if not self.authenticate(account):
            print("   ❌ Authentication failed")
            return

        # Backup first!
        backup_file = self.backup_filters(account)
        if not backup_file:
            print("   ❌ Cannot proceed without backup")
            return

        filters = self.get_filters(account)
        print(f"   Found {len(filters)} filters")

        fixed_count = 0
        for f in filters:
            criteria = f.get('criteria', {})
            action = f.get('action', {})
            filter_id = f.get('id')

            # Check if this filter archives (removes INBOX)
            if 'INBOX' not in action.get('removeLabelIds', []):
                continue  # Skip filters that don't archive

            # This filter archives - fix it
            from_addr = criteria.get('from', criteria.get('query', 'Unknown'))
            add_labels = action.get('addLabelIds', [])

            print(f"\n   Filter: from:{from_addr[:50]}")
            print(f"      Current: Archives + adds labels {add_labels}")

            if execute:
                # Delete old filter
                if self.delete_filter(account, filter_id):
                    # Create new filter WITHOUT removeLabelIds
                    new_action = {
                        'addLabelIds': add_labels
                        # NOT including removeLabelIds - keeps in INBOX!
                    }
                    if self.create_filter(account, criteria, new_action):
                        print(f"      ✅ Fixed! Now: Keeps in inbox + adds labels")
                        fixed_count += 1
                    else:
                        print(f"      ⚠️ Could not create replacement filter")
            else:
                print(f"      📋 Would change to: Keep in inbox + add labels")
                fixed_count += 1

        print(f"\n   {'Fixed' if execute else 'Would fix'}: {fixed_count} filters")

    def restore_archived_to_inbox(self, account: str, days: int = 7, execute: bool = False):
        """
        Move recently archived emails back to inbox.

        Finds emails that:
        - Are NOT in inbox
        - Have Receipts or Notifications label
        - Are from the last N days
        """
        print(f"\n{'='*60}")
        print(f"📥 RESTORING ARCHIVED EMAILS: {account}")
        print(f"{'='*60}")

        if not self.authenticate(account):
            print("   ❌ Authentication failed")
            return

        service = self.services[account]

        # Get INBOX label ID
        labels = service.users().labels().list(userId='me').execute().get('labels', [])
        inbox_id = None
        for label in labels:
            if label['name'] == 'INBOX':
                inbox_id = label['id']
                break

        if not inbox_id:
            print("   ❌ Could not find INBOX label")
            return

        # Search for archived emails from last N days
        date_cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
        query = f"after:{date_cutoff} -in:inbox (label:receipts OR label:notifications)"

        print(f"   Searching for archived emails from last {days} days...")

        try:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=500
            ).execute()

            messages = results.get('messages', [])
            print(f"   Found {len(messages)} archived emails to restore")

            if not messages:
                print("   ✅ No emails to restore")
                return

            if execute:
                # Batch add INBOX label
                msg_ids = [m['id'] for m in messages]

                # Process in batches of 100
                for i in range(0, len(msg_ids), 100):
                    batch = msg_ids[i:i+100]
                    service.users().messages().batchModify(
                        userId='me',
                        body={
                            'ids': batch,
                            'addLabelIds': [inbox_id]
                        }
                    ).execute()
                    print(f"      ✅ Restored {len(batch)} emails to inbox")

                print(f"   ✅ Restored {len(messages)} emails to inbox!")
            else:
                print(f"   📋 Would restore {len(messages)} emails to inbox")
                # Show sample
                for msg in messages[:5]:
                    try:
                        detail = service.users().messages().get(
                            userId='me',
                            id=msg['id'],
                            format='metadata',
                            metadataHeaders=['Subject', 'From', 'Date']
                        ).execute()
                        headers = {h['name']: h['value'] for h in detail.get('payload', {}).get('headers', [])}
                        print(f"      - {headers.get('Subject', 'N/A')[:50]}")
                    except:
                        pass

        except Exception as e:
            print(f"   ❌ Error: {e}")

    def delete_all_archive_filters(self, account: str, execute: bool = False):
        """Delete ALL filters that archive emails"""
        print(f"\n{'='*60}")
        print(f"🗑️ DELETING ARCHIVE FILTERS: {account}")
        print(f"{'='*60}")

        if not self.authenticate(account):
            return

        backup_file = self.backup_filters(account)
        if not backup_file:
            return

        filters = self.get_filters(account)
        delete_count = 0

        for f in filters:
            action = f.get('action', {})
            if 'INBOX' not in action.get('removeLabelIds', []):
                continue

            criteria = f.get('criteria', {})
            from_addr = criteria.get('from', criteria.get('query', 'Unknown'))
            filter_id = f.get('id')

            if execute:
                if self.delete_filter(account, filter_id):
                    print(f"   ✅ Deleted filter: from:{from_addr[:50]}")
                    delete_count += 1
            else:
                print(f"   📋 Would delete: from:{from_addr[:50]}")
                delete_count += 1

        print(f"\n   {'Deleted' if execute else 'Would delete'}: {delete_count} filters")

    def run_interactive(self):
        """Interactive mode"""
        print("\n" + "=" * 70)
        print("🔧 EMAIL FILTER FIX TOOL")
        print("=" * 70)
        print("\nThis tool fixes filters that hide your emails from inbox.\n")
        print("Options:")
        print("  1. FIX filters (keep in inbox + add labels) - RECOMMENDED")
        print("  2. DELETE all archive filters (fresh start)")
        print("  3. RESTORE recent archived emails to inbox")
        print("  4. Preview only (no changes)")
        print("  5. Exit")

        choice = input("\nSelect option (1-5): ").strip()

        execute = choice != '4'
        if execute:
            confirm = input("⚠️  This will modify your Gmail filters. Continue? (yes/no): ").strip().lower()
            if confirm != 'yes':
                print("Cancelled.")
                return

        for account in ACCOUNTS:
            if choice == '1':
                self.fix_archive_filters(account, execute=execute)
            elif choice == '2':
                self.delete_all_archive_filters(account, execute=execute)
            elif choice == '3':
                days = input("How many days back to restore? (default 7): ").strip()
                days = int(days) if days else 7
                self.restore_archived_to_inbox(account, days=days, execute=execute)
            elif choice == '4':
                self.fix_archive_filters(account, execute=False)
                self.restore_archived_to_inbox(account, days=7, execute=False)


if __name__ == '__main__':
    if not GMAIL_API_AVAILABLE:
        print("Cannot run without Google API libraries")
        exit(1)

    fixer = EmailFilterFix()

    # Check for command line args
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        execute = '--execute' in sys.argv

        if cmd == 'fix':
            for account in ACCOUNTS:
                fixer.fix_archive_filters(account, execute=execute)
        elif cmd == 'delete':
            for account in ACCOUNTS:
                fixer.delete_all_archive_filters(account, execute=execute)
        elif cmd == 'restore':
            days = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 7
            for account in ACCOUNTS:
                fixer.restore_archived_to_inbox(account, days=days, execute=execute)
    else:
        fixer.run_interactive()
