#!/usr/bin/env python3
"""
EMAIL CLEANUP TOOL
==================
Fix email organization issues:
1. Merge duplicate labels
2. Delete empty labels
3. Remove duplicate/conflicting filters
4. Review archive filters that hide emails

Run: python email_cleanup.py

SAFE MODE: By default, shows what would be done without making changes.
Use --execute to actually make changes.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Google API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False
    print("❌ Google API libraries not available")

# =============================================================================
# CONFIGURATION
# =============================================================================

TOKEN_DIR = Path(__file__).parent / "gmail_tokens"
CREDENTIALS_FILE = Path(__file__).parent / "config" / "credentials.json"

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

# Labels to merge (source -> target)
LABELS_TO_MERGE = {
    'kaplan.brian@gmail.com': {
        'Receipt': 'Receipts',  # Move 1 email from Receipt to Receipts
        'Newsletter': 'Newsletters',
        'Notification': 'Notifications',
        'Zero Inbox': 'Inbox Zero',
        'Zero Inbox/Newsletters': 'Inbox Zero/Unsubscribed',
        'Zero Inbox/Promotions': 'Inbox Zero/Unsubscribed',
    }
}

# Labels to delete if empty
EMPTY_LABELS_TO_DELETE = [
    '@Reference', '@Someday', '@Waiting', 'Reference', 'Waiting',
    'Action', 'Zero Inbox', 'Zero Inbox/Newsletters', 'Zero Inbox/Promotions',
    'Inbox Zero',  # Keep Inbox Zero/Unsubscribed but delete parent if empty
]

# Filters that archive receipt emails (potentially problematic)
RECEIPT_ARCHIVE_SENDERS = [
    'amazon.com', 'apple.com', 'google.com', 'paypal.com',
    'stripe.com', 'square.com', 'uber.com', 'lyft.com'
]


class EmailCleanup:
    """Email cleanup and organization tool"""

    def __init__(self, execute_mode=False):
        self.execute_mode = execute_mode
        self.services = {}
        self.actions_log = []

    def log_action(self, account, action_type, description, executed=False):
        """Log an action (planned or executed)"""
        action = {
            'account': account,
            'type': action_type,
            'description': description,
            'executed': executed,
            'timestamp': datetime.now().isoformat()
        }
        self.actions_log.append(action)
        status = "✅ DONE" if executed else "📋 PLANNED"
        print(f"   {status}: {description}")

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

    def get_labels(self, account: str) -> dict:
        """Get all labels as dict: name -> {id, messagesTotal}"""
        if account not in self.services:
            return {}

        try:
            results = self.services[account].users().labels().list(userId='me').execute()
            labels = {}
            for label in results.get('labels', []):
                details = self.services[account].users().labels().get(
                    userId='me', id=label['id']
                ).execute()
                labels[label['name']] = {
                    'id': label['id'],
                    'type': label.get('type', 'user'),
                    'messagesTotal': details.get('messagesTotal', 0),
                    'messagesUnread': details.get('messagesUnread', 0)
                }
            return labels
        except:
            return {}

    def get_filters(self, account: str) -> list:
        """Get all filters"""
        if account not in self.services:
            return []

        try:
            results = self.services[account].users().settings().filters().list(userId='me').execute()
            return results.get('filter', [])
        except:
            return []

    def merge_labels(self, account: str, source_name: str, target_name: str, labels: dict) -> bool:
        """Move emails from source label to target label, then delete source"""
        if source_name not in labels:
            print(f"   ⚠️  Source label '{source_name}' not found")
            return False

        if target_name not in labels:
            print(f"   ⚠️  Target label '{target_name}' not found")
            return False

        source = labels[source_name]
        target = labels[target_name]

        if source['messagesTotal'] == 0:
            self.log_action(account, 'DELETE_EMPTY_LABEL',
                f"Delete empty label '{source_name}'", self.execute_mode)
            if self.execute_mode:
                try:
                    self.services[account].users().labels().delete(
                        userId='me', id=source['id']
                    ).execute()
                except Exception as e:
                    print(f"   ❌ Error deleting label: {e}")
            return True

        # Move emails from source to target
        self.log_action(account, 'MERGE_LABELS',
            f"Move {source['messagesTotal']} emails from '{source_name}' to '{target_name}'",
            self.execute_mode)

        if self.execute_mode:
            try:
                # Get messages with source label
                messages = self.services[account].users().messages().list(
                    userId='me', labelIds=[source['id']], maxResults=500
                ).execute().get('messages', [])

                # Batch modify: add target, remove source
                if messages:
                    msg_ids = [m['id'] for m in messages]
                    self.services[account].users().messages().batchModify(
                        userId='me',
                        body={
                            'ids': msg_ids,
                            'addLabelIds': [target['id']],
                            'removeLabelIds': [source['id']]
                        }
                    ).execute()

                # Delete source label
                self.services[account].users().labels().delete(
                    userId='me', id=source['id']
                ).execute()

            except Exception as e:
                print(f"   ❌ Error merging: {e}")
                return False

        return True

    def delete_empty_labels(self, account: str, labels: dict) -> int:
        """Delete empty user labels"""
        deleted = 0
        for label_name, label_info in labels.items():
            if label_info['type'] != 'user':
                continue
            if label_info['messagesTotal'] > 0:
                continue
            if label_name not in EMPTY_LABELS_TO_DELETE:
                continue

            self.log_action(account, 'DELETE_EMPTY_LABEL',
                f"Delete empty label '{label_name}'", self.execute_mode)

            if self.execute_mode:
                try:
                    self.services[account].users().labels().delete(
                        userId='me', id=label_info['id']
                    ).execute()
                    deleted += 1
                except Exception as e:
                    print(f"   ❌ Error: {e}")

        return deleted

    def analyze_archive_filters(self, account: str, filters: list) -> list:
        """Find filters that archive receipt-related emails"""
        problematic = []

        for f in filters:
            criteria = f.get('criteria', {})
            action = f.get('action', {})

            # Check if filter archives (removes INBOX)
            if 'INBOX' not in action.get('removeLabelIds', []):
                continue

            # Check if it's a receipt-related sender
            from_addr = criteria.get('from', '').lower()
            for sender in RECEIPT_ARCHIVE_SENDERS:
                if sender in from_addr:
                    problematic.append({
                        'id': f.get('id'),
                        'from': from_addr,
                        'action': 'archive',
                        'issue': f"Archives emails from {sender} - receipts may be hidden"
                    })
                    break

        return problematic

    def find_duplicate_filters(self, filters: list) -> list:
        """Find duplicate filters with same criteria"""
        signatures = {}
        duplicates = []

        for f in filters:
            criteria = f.get('criteria', {})
            sig = json.dumps(criteria, sort_keys=True)

            if sig in signatures:
                duplicates.append({
                    'filter1': signatures[sig],
                    'filter2': f.get('id'),
                    'criteria': criteria
                })
            else:
                signatures[sig] = f.get('id')

        return duplicates

    def cleanup_account(self, account: str):
        """Run cleanup on a single account"""
        print(f"\n{'='*60}")
        print(f"🧹 CLEANING: {account}")
        print(f"{'='*60}")

        if not self.authenticate(account):
            print("   ❌ Authentication failed")
            return

        print("   ✅ Authenticated")

        # Get current state
        labels = self.get_labels(account)
        filters = self.get_filters(account)

        print(f"\n📁 LABEL CLEANUP")
        print("-" * 40)

        # Merge duplicate labels
        if account in LABELS_TO_MERGE:
            for source, target in LABELS_TO_MERGE[account].items():
                self.merge_labels(account, source, target, labels)
                # Refresh labels after merge
                if self.execute_mode:
                    labels = self.get_labels(account)

        # Delete empty labels
        self.delete_empty_labels(account, labels)

        print(f"\n🔧 FILTER ANALYSIS")
        print("-" * 40)

        # Find duplicate filters
        duplicates = self.find_duplicate_filters(filters)
        if duplicates:
            print(f"   ⚠️  Found {len(duplicates)} duplicate filters:")
            for dup in duplicates[:5]:
                print(f"      - {dup['criteria']}")

        # Find problematic archive filters
        archive_filters = self.analyze_archive_filters(account, filters)
        if archive_filters:
            print(f"\n   ⚠️  Found {len(archive_filters)} filters that archive receipt emails:")
            for af in archive_filters[:10]:
                print(f"      - from:{af['from']} -> {af['issue']}")

    def run_all(self):
        """Run cleanup on all accounts"""
        mode = "EXECUTE MODE" if self.execute_mode else "PREVIEW MODE (use --execute to apply changes)"
        print("\n" + "=" * 70)
        print(f"🧹 EMAIL CLEANUP TOOL - {mode}")
        print("=" * 70)

        for account in ACCOUNTS:
            self.cleanup_account(account)

        # Summary
        print("\n" + "=" * 70)
        print("📋 ACTION SUMMARY")
        print("=" * 70)

        actions_by_type = defaultdict(list)
        for action in self.actions_log:
            actions_by_type[action['type']].append(action)

        for action_type, actions in actions_by_type.items():
            executed = sum(1 for a in actions if a['executed'])
            print(f"\n{action_type}: {len(actions)} total, {executed} executed")
            for action in actions[:5]:
                status = "✅" if action['executed'] else "📋"
                print(f"   {status} [{action['account'].split('@')[0]}] {action['description'][:50]}")

        # Save log
        log_file = Path(__file__).parent / 'email_cleanup_log.json'
        with open(log_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'mode': 'execute' if self.execute_mode else 'preview',
                'actions': self.actions_log
            }, f, indent=2)
        print(f"\n💾 Log saved to: {log_file}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    if not GMAIL_API_AVAILABLE:
        print("Cannot run cleanup without Google API libraries")
        exit(1)

    execute_mode = '--execute' in sys.argv

    if not execute_mode:
        print("\n⚠️  PREVIEW MODE - No changes will be made")
        print("   Add --execute flag to apply changes")
        print("   Example: python email_cleanup.py --execute\n")

    cleanup = EmailCleanup(execute_mode=execute_mode)
    cleanup.run_all()
