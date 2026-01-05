#!/usr/bin/env python3
"""
MASTER EMAIL MANAGEMENT SYSTEM
==============================
The ultimate email organization system for multiple Gmail accounts.

FEATURES:
- Smart labeling (labels emails without hiding from inbox)
- Unified label structure across all accounts
- Receipt extraction and processing
- Inbox Zero workflow automation
- Email backup and restore
- Spam and promotional cleanup
- VIP sender protection
- Analytics and reporting

Based on research of best practices from:
- SaneBox, Clean Email, Mailstrom methodologies
- Gmail API best practices
- Inbox Zero principles

Author: Built for Brian Kaplan
Date: January 2026
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import re

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = Path(__file__).parent
TOKEN_DIR = BASE_DIR / "gmail_tokens"
CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"
DATA_DIR = BASE_DIR / "email_data"
BACKUP_DIR = BASE_DIR / "email_backups"

# Create directories
DATA_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

# Account configuration
ACCOUNTS = {
    'kaplan.brian@gmail.com': {
        'token_file': 'tokens_kaplan_brian_gmail_com.json',
        'type': 'Personal',
        'priority': 1
    },
    'brian@downhome.com': {
        'token_file': 'tokens_brian_downhome_com.json',
        'type': 'Business',
        'priority': 2
    },
    'brian@musiccityrodeo.com': {
        'token_file': 'tokens_brian_musiccityrodeo_com.json',
        'type': 'Business',
        'priority': 3
    }
}

# Unified label structure (applied to all accounts)
LABEL_STRUCTURE = {
    # Core organizational labels
    'Receipts': {'color': {'backgroundColor': '#16a765', 'textColor': '#ffffff'}},
    'Notifications': {'color': {'backgroundColor': '#4986e7', 'textColor': '#ffffff'}},
    'Newsletters': {'color': {'backgroundColor': '#ff7537', 'textColor': '#ffffff'}},

    # Action-based labels (GTD methodology)
    '@Action': {'color': {'backgroundColor': '#fb4c2f', 'textColor': '#ffffff'}},
    '@Waiting': {'color': {'backgroundColor': '#ffad47', 'textColor': '#ffffff'}},
    '@Reference': {'color': {'backgroundColor': '#a479e2', 'textColor': '#ffffff'}},

    # Status labels
    'Processed': {'color': {'backgroundColor': '#98d7e4', 'textColor': '#000000'}},
}

# VIP senders (never auto-process, always show in inbox)
VIP_SENDERS = [
    # Business partners
    'tim@', 'patrick@', 'reba@', 'miranda@', 'luna@',
    # Important services
    'stripe.com', 'square.com', 'anthropic.com',
    # Family/personal
    '@family.com', '@school.edu',
]

# Receipt senders (label as Receipts)
RECEIPT_SENDERS = [
    # E-commerce
    'amazon.com', 'ebay.com', 'walmart.com', 'target.com', 'bestbuy.com',
    'costco.com', 'homedepot.com', 'lowes.com', 'wayfair.com', 'zappos.com',
    # Travel
    'southwest.com', 'delta.com', 'aa.com', 'united.com', 'jetblue.com',
    'hilton.com', 'marriott.com', 'airbnb.com', 'expedia.com', 'booking.com',
    'uber.com', 'lyft.com', 'nationalcar.com', 'avis.com', 'hertz.com',
    # Food
    'doordash.com', 'grubhub.com', 'ubereats.com', 'postmates.com',
    'instacart.com', 'shipt.com', 'chick-fil-a.com',
    # Services
    'stripe.com', 'paypal.com', 'venmo.com', 'squareup.com',
    'spotify.com', 'netflix.com', 'apple.com', 'google.com',
    # Tickets
    'ticketmaster.com', 'livenation.com', 'axs.com', 'seatgeek.com',
    'eventbrite.com', 'stubhub.com',
]

# Notification senders (label as Notifications)
NOTIFICATION_SENDERS = [
    'github.com', 'gitlab.com', 'slack.com', 'notion.so',
    'trello.com', 'asana.com', 'monday.com', 'jira.com',
    'parentsquare.com', 'remind.com', 'schoology.com',
]

# Newsletter patterns (label as Newsletters)
NEWSLETTER_PATTERNS = [
    'newsletter@', 'news@', 'digest@', 'weekly@', 'daily@',
    'substack.com', 'every.to', 'mailchimp.com',
]

# Spam/promotional senders to auto-archive (not delete)
ARCHIVE_SENDERS = [
    'marketing@', 'promo@', 'deals@', 'offer@', 'sale@',
    'noreply@linkedin.com', 'messages-noreply@linkedin.com',
]


class MasterEmailSystem:
    """Master email management system"""

    def __init__(self):
        self.services: Dict[str, object] = {}
        self.labels_cache: Dict[str, Dict] = {}
        self.db = self._init_database()

    def _init_database(self) -> sqlite3.Connection:
        """Initialize SQLite database for tracking"""
        db_path = DATA_DIR / "email_system.db"
        conn = sqlite3.connect(str(db_path))

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                id INTEGER PRIMARY KEY,
                account TEXT NOT NULL,
                message_id TEXT NOT NULL,
                subject TEXT,
                sender TEXT,
                received_date TEXT,
                labels TEXT,
                processed_at TEXT,
                action_taken TEXT,
                UNIQUE(account, message_id)
            );

            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY,
                account TEXT NOT NULL,
                message_id TEXT NOT NULL,
                merchant TEXT,
                amount REAL,
                date TEXT,
                r2_url TEXT,
                extracted_at TEXT,
                matched_transaction_id TEXT,
                UNIQUE(account, message_id)
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY,
                account TEXT NOT NULL,
                sync_type TEXT,
                started_at TEXT,
                completed_at TEXT,
                messages_processed INTEGER,
                errors TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_processed_account ON processed_emails(account);
            CREATE INDEX IF NOT EXISTS idx_receipts_account ON receipts(account);
        """)

        return conn

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    def authenticate(self, account: str) -> bool:
        """Authenticate a Gmail account"""
        if account in self.services:
            return True

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

            with open(token_path, 'r') as f:
                token_data = json.load(f)

            creds = Credentials(
                token=token_data.get('access_token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_config.get('client_id'),
                client_secret=client_config.get('client_secret'),
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
            print(f"Auth error for {account}: {e}")
            return False

    def authenticate_all(self) -> Dict[str, bool]:
        """Authenticate all accounts"""
        results = {}
        for account in ACCOUNTS:
            results[account] = self.authenticate(account)
        return results

    # =========================================================================
    # LABEL MANAGEMENT
    # =========================================================================

    def get_labels(self, account: str) -> Dict[str, dict]:
        """Get all labels for an account"""
        if account in self.labels_cache:
            return self.labels_cache[account]

        if not self.authenticate(account):
            return {}

        try:
            result = self.services[account].users().labels().list(userId='me').execute()
            labels = {}
            for label in result.get('labels', []):
                details = self.services[account].users().labels().get(
                    userId='me', id=label['id']
                ).execute()
                labels[label['name']] = details
            self.labels_cache[account] = labels
            return labels
        except:
            return {}

    def ensure_label_structure(self, account: str) -> Dict[str, str]:
        """Ensure all required labels exist"""
        if not self.authenticate(account):
            return {}

        labels = self.get_labels(account)
        label_ids = {}

        for label_name, config in LABEL_STRUCTURE.items():
            if label_name in labels:
                label_ids[label_name] = labels[label_name]['id']
            else:
                # Create label
                try:
                    body = {
                        'name': label_name,
                        'labelListVisibility': 'labelShow',
                        'messageListVisibility': 'show'
                    }
                    if 'color' in config:
                        body['color'] = config['color']

                    result = self.services[account].users().labels().create(
                        userId='me', body=body
                    ).execute()
                    label_ids[label_name] = result['id']
                    print(f"   Created label: {label_name}")
                except Exception as e:
                    print(f"   Error creating {label_name}: {e}")

        return label_ids

    def delete_duplicate_labels(self, account: str) -> int:
        """Delete duplicate/similar labels"""
        if not self.authenticate(account):
            return 0

        labels = self.get_labels(account)
        deleted = 0

        # Find duplicates (singular vs plural, etc.)
        duplicates = {
            'Receipt': 'Receipts',
            'Newsletter': 'Newsletters',
            'Notification': 'Notifications',
        }

        for old_name, new_name in duplicates.items():
            if old_name in labels and new_name in labels:
                old_label = labels[old_name]
                new_label = labels[new_name]

                # Move messages from old to new
                if old_label.get('messagesTotal', 0) > 0:
                    try:
                        messages = self.services[account].users().messages().list(
                            userId='me', labelIds=[old_label['id']], maxResults=500
                        ).execute().get('messages', [])

                        if messages:
                            self.services[account].users().messages().batchModify(
                                userId='me',
                                body={
                                    'ids': [m['id'] for m in messages],
                                    'addLabelIds': [new_label['id']],
                                    'removeLabelIds': [old_label['id']]
                                }
                            ).execute()
                    except:
                        pass

                # Delete old label
                try:
                    self.services[account].users().labels().delete(
                        userId='me', id=old_label['id']
                    ).execute()
                    deleted += 1
                    print(f"   Deleted duplicate: {old_name}")
                except:
                    pass

        return deleted

    # =========================================================================
    # SMART FILTERING
    # =========================================================================

    def classify_email(self, sender: str, subject: str) -> Tuple[str, bool]:
        """
        Classify an email and determine the appropriate label.
        Returns (label_name, is_vip)
        """
        sender_lower = sender.lower()
        subject_lower = subject.lower()

        # Check VIP first
        for vip in VIP_SENDERS:
            if vip.lower() in sender_lower:
                return (None, True)  # No auto-labeling for VIPs

        # Check receipts
        for pattern in RECEIPT_SENDERS:
            if pattern.lower() in sender_lower:
                return ('Receipts', False)

        # Check subject for receipt keywords
        receipt_keywords = ['receipt', 'invoice', 'order confirmation', 'payment confirmation',
                          'your order', 'order #', 'transaction']
        for kw in receipt_keywords:
            if kw in subject_lower:
                return ('Receipts', False)

        # Check notifications
        for pattern in NOTIFICATION_SENDERS:
            if pattern.lower() in sender_lower:
                return ('Notifications', False)

        # Check newsletters
        for pattern in NEWSLETTER_PATTERNS:
            if pattern.lower() in sender_lower:
                return ('Newsletters', False)

        return (None, False)  # No classification

    def process_new_emails(self, account: str, hours_back: int = 24) -> Dict:
        """Process new emails and apply labels (WITHOUT archiving)"""
        if not self.authenticate(account):
            return {'error': 'Auth failed'}

        label_ids = self.ensure_label_structure(account)
        results = {
            'processed': 0,
            'labeled': defaultdict(int),
            'vip': 0,
            'skipped': 0
        }

        # Get recent emails
        since = (datetime.now() - timedelta(hours=hours_back)).strftime('%Y/%m/%d')
        query = f"after:{since} in:inbox"

        try:
            messages = self.services[account].users().messages().list(
                userId='me', q=query, maxResults=200
            ).execute().get('messages', [])

            for msg in messages:
                try:
                    # Check if already processed
                    cursor = self.db.execute(
                        "SELECT 1 FROM processed_emails WHERE account=? AND message_id=?",
                        (account, msg['id'])
                    )
                    if cursor.fetchone():
                        results['skipped'] += 1
                        continue

                    # Get message details
                    detail = self.services[account].users().messages().get(
                        userId='me', id=msg['id'], format='metadata',
                        metadataHeaders=['Subject', 'From', 'Date']
                    ).execute()

                    headers = {h['name']: h['value'] for h in detail.get('payload', {}).get('headers', [])}
                    sender = headers.get('From', '')
                    subject = headers.get('Subject', '')

                    # Classify
                    label_name, is_vip = self.classify_email(sender, subject)

                    if is_vip:
                        results['vip'] += 1
                        action = 'vip'
                    elif label_name and label_name in label_ids:
                        # Add label (but keep in inbox!)
                        self.services[account].users().messages().modify(
                            userId='me', id=msg['id'],
                            body={'addLabelIds': [label_ids[label_name]]}
                        ).execute()
                        results['labeled'][label_name] += 1
                        action = f'labeled:{label_name}'
                    else:
                        action = 'none'

                    # Record in database
                    self.db.execute("""
                        INSERT OR REPLACE INTO processed_emails
                        (account, message_id, subject, sender, received_date, processed_at, action_taken)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (account, msg['id'], subject[:200], sender[:200],
                          headers.get('Date', ''), datetime.now().isoformat(), action))

                    results['processed'] += 1

                except Exception as e:
                    print(f"   Error processing {msg['id']}: {e}")

            self.db.commit()

        except Exception as e:
            results['error'] = str(e)

        return results

    # =========================================================================
    # RECEIPT EXTRACTION
    # =========================================================================

    def extract_receipts(self, account: str, days_back: int = 30) -> List[Dict]:
        """Extract receipt data from Receipts label"""
        if not self.authenticate(account):
            return []

        labels = self.get_labels(account)
        if 'Receipts' not in labels:
            return []

        receipts_label_id = labels['Receipts']['id']
        since = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')

        receipts = []
        try:
            messages = self.services[account].users().messages().list(
                userId='me', labelIds=[receipts_label_id],
                q=f"after:{since}", maxResults=100
            ).execute().get('messages', [])

            for msg in messages:
                try:
                    # Check if already extracted
                    cursor = self.db.execute(
                        "SELECT 1 FROM receipts WHERE account=? AND message_id=?",
                        (account, msg['id'])
                    )
                    if cursor.fetchone():
                        continue

                    detail = self.services[account].users().messages().get(
                        userId='me', id=msg['id'], format='full'
                    ).execute()

                    headers = {h['name']: h['value'] for h in detail.get('payload', {}).get('headers', [])}

                    receipt = {
                        'account': account,
                        'message_id': msg['id'],
                        'subject': headers.get('Subject', ''),
                        'sender': headers.get('From', ''),
                        'date': headers.get('Date', ''),
                        'merchant': self._extract_merchant(headers.get('From', '')),
                        'amount': self._extract_amount(detail),
                    }

                    receipts.append(receipt)

                    # Save to database
                    self.db.execute("""
                        INSERT OR REPLACE INTO receipts
                        (account, message_id, merchant, amount, date, extracted_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (account, msg['id'], receipt['merchant'], receipt['amount'],
                          receipt['date'], datetime.now().isoformat()))

                except Exception as e:
                    print(f"   Error extracting {msg['id']}: {e}")

            self.db.commit()

        except Exception as e:
            print(f"Error: {e}")

        return receipts

    def _extract_merchant(self, from_addr: str) -> str:
        """Extract merchant name from sender"""
        # Try to get domain
        match = re.search(r'@([a-zA-Z0-9.-]+)', from_addr)
        if match:
            domain = match.group(1).lower()
            # Clean up
            domain = domain.replace('.com', '').replace('.net', '').replace('.org', '')
            domain = domain.replace('mail.', '').replace('email.', '').replace('e.', '')
            return domain.title()
        return 'Unknown'

    def _extract_amount(self, message: dict) -> Optional[float]:
        """Extract amount from email"""
        # Get body
        body = self._get_message_body(message)
        if not body:
            return None

        # Look for dollar amounts
        patterns = [
            r'Total[:\s]+\$?([\d,]+\.?\d*)',
            r'Amount[:\s]+\$?([\d,]+\.?\d*)',
            r'\$\s?([\d,]+\.\d{2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except:
                    continue

        return None

    def _get_message_body(self, message: dict) -> str:
        """Extract body text from message"""
        import base64
        try:
            payload = message.get('payload', {})

            if 'body' in payload and 'data' in payload['body']:
                return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')

            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        if 'data' in part.get('body', {}):
                            return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
            return ''
        except:
            return ''

    # =========================================================================
    # INBOX ZERO
    # =========================================================================

    def get_inbox_stats(self, account: str) -> Dict:
        """Get inbox statistics"""
        if not self.authenticate(account):
            return {}

        try:
            profile = self.services[account].users().getProfile(userId='me').execute()
            labels = self.get_labels(account)

            stats = {
                'total_messages': profile.get('messagesTotal', 0),
                'total_threads': profile.get('threadsTotal', 0),
            }

            # Get counts for key labels
            for label_name in ['INBOX', 'UNREAD', 'Receipts', 'Newsletters', 'Notifications']:
                if label_name in labels:
                    stats[label_name.lower()] = labels[label_name].get('messagesTotal', 0)
                    stats[f'{label_name.lower()}_unread'] = labels[label_name].get('messagesUnread', 0)

            return stats

        except Exception as e:
            return {'error': str(e)}

    def archive_processed(self, account: str, label_name: str, older_than_days: int = 7) -> int:
        """Archive emails that have been labeled and are older than N days"""
        if not self.authenticate(account):
            return 0

        labels = self.get_labels(account)
        if label_name not in labels:
            return 0

        label_id = labels[label_name]['id']
        inbox_id = labels.get('INBOX', {}).get('id')
        if not inbox_id:
            return 0

        cutoff = (datetime.now() - timedelta(days=older_than_days)).strftime('%Y/%m/%d')

        try:
            messages = self.services[account].users().messages().list(
                userId='me',
                q=f"before:{cutoff} in:inbox label:{label_name}",
                maxResults=200
            ).execute().get('messages', [])

            if messages:
                self.services[account].users().messages().batchModify(
                    userId='me',
                    body={
                        'ids': [m['id'] for m in messages],
                        'removeLabelIds': [inbox_id]
                    }
                ).execute()

            return len(messages)

        except:
            return 0

    # =========================================================================
    # BACKUP & RESTORE
    # =========================================================================

    def backup_account(self, account: str) -> str:
        """Create full backup of account settings"""
        if not self.authenticate(account):
            return None

        backup = {
            'account': account,
            'backed_up_at': datetime.now().isoformat(),
            'labels': [],
            'filters': []
        }

        try:
            # Backup labels
            labels = self.services[account].users().labels().list(userId='me').execute()
            for label in labels.get('labels', []):
                detail = self.services[account].users().labels().get(
                    userId='me', id=label['id']
                ).execute()
                backup['labels'].append(detail)

            # Backup filters
            filters = self.services[account].users().settings().filters().list(
                userId='me'
            ).execute()
            backup['filters'] = filters.get('filter', [])

        except Exception as e:
            backup['error'] = str(e)

        # Save
        safe_name = account.replace('@', '_at_').replace('.', '_')
        backup_file = BACKUP_DIR / f"{safe_name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(backup_file, 'w') as f:
            json.dump(backup, f, indent=2)

        return str(backup_file)

    def restore_to_inbox(self, account: str, label_name: str, days_back: int = 7) -> int:
        """Restore emails from a label back to inbox"""
        if not self.authenticate(account):
            return 0

        labels = self.get_labels(account)
        if label_name not in labels:
            return 0

        label_id = labels[label_name]['id']
        inbox_id = labels.get('INBOX', {}).get('id')
        if not inbox_id:
            return 0

        since = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')

        try:
            messages = self.services[account].users().messages().list(
                userId='me',
                q=f"after:{since} -in:inbox label:{label_name}",
                maxResults=500
            ).execute().get('messages', [])

            if messages:
                self.services[account].users().messages().batchModify(
                    userId='me',
                    body={
                        'ids': [m['id'] for m in messages],
                        'addLabelIds': [inbox_id]
                    }
                ).execute()

            return len(messages)

        except:
            return 0

    # =========================================================================
    # MAIN WORKFLOW
    # =========================================================================

    def run_full_sync(self) -> Dict:
        """Run full sync on all accounts"""
        print("\n" + "=" * 70)
        print("📧 MASTER EMAIL SYSTEM - FULL SYNC")
        print("=" * 70)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        results = {}

        for account in ACCOUNTS:
            print(f"\n📬 Processing: {account}")

            if not self.authenticate(account):
                results[account] = {'error': 'Auth failed'}
                continue

            # 1. Ensure labels
            print("   Setting up labels...")
            self.ensure_label_structure(account)

            # 2. Clean up duplicates
            print("   Cleaning duplicate labels...")
            self.delete_duplicate_labels(account)

            # 3. Process new emails
            print("   Processing new emails...")
            process_results = self.process_new_emails(account, hours_back=48)

            # 4. Extract receipts
            print("   Extracting receipts...")
            receipts = self.extract_receipts(account, days_back=30)

            # 5. Get stats
            print("   Getting stats...")
            stats = self.get_inbox_stats(account)

            results[account] = {
                'processed': process_results,
                'receipts_extracted': len(receipts),
                'stats': stats
            }

            print(f"   ✅ Done: {process_results.get('processed', 0)} processed, "
                  f"{len(receipts)} receipts extracted")

        print("\n" + "=" * 70)
        print("✅ SYNC COMPLETE")
        print("=" * 70)

        return results

    def get_dashboard_data(self) -> Dict:
        """Get data for dashboard display"""
        data = {
            'accounts': {},
            'totals': {
                'messages': 0,
                'inbox': 0,
                'unread': 0,
                'receipts': 0
            }
        }

        for account in ACCOUNTS:
            if self.authenticate(account):
                stats = self.get_inbox_stats(account)
                data['accounts'][account] = stats

                data['totals']['messages'] += stats.get('total_messages', 0)
                data['totals']['inbox'] += stats.get('inbox', 0)
                data['totals']['unread'] += stats.get('unread', 0)
                data['totals']['receipts'] += stats.get('receipts', 0)

        return data


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    if not GMAIL_API_AVAILABLE:
        print("Gmail API libraries not available")
        return

    system = MasterEmailSystem()

    if len(sys.argv) < 2:
        print("""
MASTER EMAIL SYSTEM
===================
Usage:
  python email_master_system.py sync        - Full sync all accounts
  python email_master_system.py stats       - Show dashboard stats
  python email_master_system.py backup      - Backup all accounts
  python email_master_system.py receipts    - Extract receipts
  python email_master_system.py restore     - Restore archived to inbox
        """)
        return

    cmd = sys.argv[1]

    if cmd == 'sync':
        system.run_full_sync()

    elif cmd == 'stats':
        data = system.get_dashboard_data()
        print("\n📊 EMAIL DASHBOARD")
        print("=" * 50)
        for account, stats in data['accounts'].items():
            print(f"\n{account}:")
            print(f"  Inbox: {stats.get('inbox', 0):,}")
            print(f"  Unread: {stats.get('unread', 0):,}")
            print(f"  Receipts: {stats.get('receipts', 0):,}")
        print(f"\n📈 TOTALS:")
        print(f"  Total messages: {data['totals']['messages']:,}")
        print(f"  Total inbox: {data['totals']['inbox']:,}")
        print(f"  Total unread: {data['totals']['unread']:,}")

    elif cmd == 'backup':
        for account in ACCOUNTS:
            print(f"Backing up {account}...")
            backup_file = system.backup_account(account)
            print(f"  Saved: {backup_file}")

    elif cmd == 'receipts':
        for account in ACCOUNTS:
            print(f"\nExtracting from {account}...")
            receipts = system.extract_receipts(account)
            print(f"  Found {len(receipts)} receipts")
            for r in receipts[:5]:
                print(f"    - {r['merchant']}: ${r.get('amount', '?')}")

    elif cmd == 'restore':
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        for account in ACCOUNTS:
            print(f"\nRestoring {account}...")
            for label in ['Receipts', 'Notifications', 'Newsletters']:
                count = system.restore_to_inbox(account, label, days)
                print(f"  {label}: restored {count} emails")


if __name__ == '__main__':
    main()
