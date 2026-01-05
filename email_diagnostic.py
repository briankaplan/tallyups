#!/usr/bin/env python3
"""
EMAIL DIAGNOSTIC TOOL
=====================
Comprehensive audit of all Gmail accounts to identify:
- Duplicate labels/folders
- Conflicting filters
- Email counts per label
- Missing or orphaned emails
- Configuration issues

Run: python email_diagnostic.py
"""

import os
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
    print("   Run: pip install google-auth google-auth-oauthlib google-api-python-client")

# =============================================================================
# CONFIGURATION
# =============================================================================

TOKEN_DIR = Path(__file__).parent / "gmail_tokens"
CREDENTIALS_FILE = Path(__file__).parent / "config" / "credentials.json"

# Your 3 Gmail accounts
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

# Gmail scopes needed for full diagnostic
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.labels',
    'https://www.googleapis.com/auth/gmail.settings.basic'
]

# =============================================================================
# DIAGNOSTIC CLASS
# =============================================================================

class EmailDiagnostic:
    """Comprehensive Gmail diagnostic tool"""

    def __init__(self):
        self.services = {}
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'accounts': {},
            'issues': [],
            'summary': {}
        }

    def authenticate(self, account: str) -> bool:
        """Authenticate a Gmail account"""
        if account not in ACCOUNTS:
            print(f"❌ Unknown account: {account}")
            return False

        config = ACCOUNTS[account]
        token_path = TOKEN_DIR / config['token_file']

        if not token_path.exists():
            self.results['issues'].append({
                'account': account,
                'type': 'AUTH_ERROR',
                'message': f"Token file not found: {token_path}"
            })
            return False

        # Load OAuth client credentials
        if not CREDENTIALS_FILE.exists():
            self.results['issues'].append({
                'account': account,
                'type': 'AUTH_ERROR',
                'message': f"OAuth credentials file not found: {CREDENTIALS_FILE}"
            })
            return False

        try:
            # Load client credentials
            with open(CREDENTIALS_FILE, 'r') as f:
                creds_data = json.load(f)

            # Handle both 'web' and 'installed' credential types
            client_config = creds_data.get('web') or creds_data.get('installed', {})
            client_id = client_config.get('client_id')
            client_secret = client_config.get('client_secret')

            if not client_id or not client_secret:
                self.results['issues'].append({
                    'account': account,
                    'type': 'AUTH_ERROR',
                    'message': 'Missing client_id or client_secret in credentials file'
                })
                return False

            # Load token data
            with open(token_path, 'r') as f:
                token_data = json.load(f)

            # Build credentials object manually
            creds = Credentials(
                token=token_data.get('access_token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_id,
                client_secret=client_secret,
                scopes=token_data.get('scope', '').split()
            )

            # Refresh if needed
            if creds.expired and creds.refresh_token:
                print(f"   🔄 Refreshing token for {account}...")
                creds.refresh(Request())
                # Save refreshed token
                token_data['access_token'] = creds.token
                with open(token_path, 'w') as f:
                    json.dump(token_data, f, indent=2)

            service = build('gmail', 'v1', credentials=creds)
            self.services[account] = service
            return True

        except Exception as e:
            self.results['issues'].append({
                'account': account,
                'type': 'AUTH_ERROR',
                'message': str(e)
            })
            return False

    def get_labels(self, account: str) -> list:
        """Get all labels for an account"""
        if account not in self.services:
            return []

        try:
            results = self.services[account].users().labels().list(userId='me').execute()
            return results.get('labels', [])
        except HttpError as e:
            self.results['issues'].append({
                'account': account,
                'type': 'API_ERROR',
                'message': f"Failed to get labels: {e}"
            })
            return []

    def get_label_details(self, account: str, label_id: str) -> dict:
        """Get detailed info about a label including message count"""
        if account not in self.services:
            return {}

        try:
            return self.services[account].users().labels().get(
                userId='me',
                id=label_id
            ).execute()
        except:
            return {}

    def get_filters(self, account: str) -> list:
        """Get all filters for an account"""
        if account not in self.services:
            return []

        try:
            results = self.services[account].users().settings().filters().list(userId='me').execute()
            return results.get('filter', [])
        except HttpError as e:
            # Filters API might need different scope
            self.results['issues'].append({
                'account': account,
                'type': 'FILTER_ACCESS',
                'message': f"Cannot access filters (may need gmail.settings.basic scope): {e}"
            })
            return []

    def get_profile(self, account: str) -> dict:
        """Get account profile info"""
        if account not in self.services:
            return {}

        try:
            return self.services[account].users().getProfile(userId='me').execute()
        except:
            return {}

    def search_emails(self, account: str, query: str, max_results: int = 10) -> int:
        """Search emails and return count"""
        if account not in self.services:
            return 0

        try:
            results = self.services[account].users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            # Get total estimate
            return results.get('resultSizeEstimate', len(results.get('messages', [])))
        except:
            return 0

    def analyze_labels(self, account: str, labels: list) -> dict:
        """Analyze labels for issues"""
        analysis = {
            'total': len(labels),
            'system': [],
            'user': [],
            'nested': [],
            'duplicates': [],
            'by_type': defaultdict(list)
        }

        label_names = {}

        for label in labels:
            label_id = label['id']
            label_name = label['name']
            label_type = label.get('type', 'user')

            # Get message counts
            details = self.get_label_details(account, label_id)
            msg_total = details.get('messagesTotal', 0)
            msg_unread = details.get('messagesUnread', 0)

            label_info = {
                'id': label_id,
                'name': label_name,
                'type': label_type,
                'messages_total': msg_total,
                'messages_unread': msg_unread
            }

            # Categorize
            if label_type == 'system':
                analysis['system'].append(label_info)
            else:
                analysis['user'].append(label_info)

            # Check for nested labels
            if '/' in label_name:
                analysis['nested'].append(label_info)

            # Track for duplicate detection
            base_name = label_name.lower().replace('/', '_').replace(' ', '_')
            if base_name in label_names:
                analysis['duplicates'].append({
                    'name1': label_names[base_name],
                    'name2': label_name,
                    'issue': 'Similar label names detected'
                })
            label_names[base_name] = label_name

            analysis['by_type'][label_type].append(label_info)

        return analysis

    def analyze_filters(self, account: str, filters: list) -> dict:
        """Analyze filters for issues"""
        analysis = {
            'total': len(filters),
            'filters': [],
            'duplicates': [],
            'conflicts': []
        }

        filter_signatures = {}

        for f in filters:
            filter_id = f.get('id', 'unknown')
            criteria = f.get('criteria', {})
            action = f.get('action', {})

            # Build a signature for duplicate detection
            sig_parts = []
            if 'from' in criteria:
                sig_parts.append(f"from:{criteria['from']}")
            if 'to' in criteria:
                sig_parts.append(f"to:{criteria['to']}")
            if 'subject' in criteria:
                sig_parts.append(f"subject:{criteria['subject']}")
            if 'query' in criteria:
                sig_parts.append(f"query:{criteria['query']}")

            signature = '|'.join(sorted(sig_parts))

            filter_info = {
                'id': filter_id,
                'criteria': criteria,
                'action': action,
                'signature': signature
            }
            analysis['filters'].append(filter_info)

            # Check for duplicates
            if signature and signature in filter_signatures:
                analysis['duplicates'].append({
                    'filter1_id': filter_signatures[signature],
                    'filter2_id': filter_id,
                    'criteria': criteria,
                    'issue': 'Duplicate filter criteria'
                })
            elif signature:
                filter_signatures[signature] = filter_id

            # Check for conflicting actions
            if action.get('removeLabelIds') and action.get('addLabelIds'):
                overlap = set(action['removeLabelIds']) & set(action['addLabelIds'])
                if overlap:
                    analysis['conflicts'].append({
                        'filter_id': filter_id,
                        'issue': f'Filter adds and removes same labels: {overlap}'
                    })

        return analysis

    def run_diagnostic(self, account: str) -> dict:
        """Run full diagnostic on an account"""
        print(f"\n{'='*60}")
        print(f"📧 DIAGNOSING: {account}")
        print(f"   Type: {ACCOUNTS[account]['type']}")
        print(f"{'='*60}")

        # Authenticate
        print(f"\n🔐 Authenticating...")
        if not self.authenticate(account):
            return {'error': 'Authentication failed'}
        print(f"   ✅ Authenticated")

        # Get profile
        print(f"\n👤 Getting profile...")
        profile = self.get_profile(account)
        email = profile.get('emailAddress', account)
        total_messages = profile.get('messagesTotal', 0)
        total_threads = profile.get('threadsTotal', 0)
        print(f"   Email: {email}")
        print(f"   Total messages: {total_messages:,}")
        print(f"   Total threads: {total_threads:,}")

        # Get and analyze labels
        print(f"\n📁 Analyzing labels...")
        labels = self.get_labels(account)
        label_analysis = self.analyze_labels(account, labels)
        print(f"   Total labels: {label_analysis['total']}")
        print(f"   System labels: {len(label_analysis['system'])}")
        print(f"   User labels: {len(label_analysis['user'])}")
        print(f"   Nested labels: {len(label_analysis['nested'])}")

        if label_analysis['duplicates']:
            print(f"   ⚠️  DUPLICATE LABELS FOUND: {len(label_analysis['duplicates'])}")
            for dup in label_analysis['duplicates']:
                print(f"      - '{dup['name1']}' vs '{dup['name2']}'")

        # Get and analyze filters
        print(f"\n🔧 Analyzing filters...")
        filters = self.get_filters(account)
        filter_analysis = self.analyze_filters(account, filters)
        print(f"   Total filters: {filter_analysis['total']}")

        if filter_analysis['duplicates']:
            print(f"   ⚠️  DUPLICATE FILTERS FOUND: {len(filter_analysis['duplicates'])}")
            for dup in filter_analysis['duplicates']:
                print(f"      - Filter {dup['filter1_id'][:8]}... and {dup['filter2_id'][:8]}...")

        if filter_analysis['conflicts']:
            print(f"   ⚠️  CONFLICTING FILTERS FOUND: {len(filter_analysis['conflicts'])}")
            for conf in filter_analysis['conflicts']:
                print(f"      - {conf['issue']}")

        # Check key folders
        print(f"\n📊 Email distribution:")
        key_searches = {
            'INBOX': 'in:inbox',
            'SENT': 'in:sent',
            'DRAFTS': 'in:drafts',
            'SPAM': 'in:spam',
            'TRASH': 'in:trash',
            'STARRED': 'is:starred',
            'UNREAD': 'is:unread',
            'Archived (no labels)': '-in:inbox -in:spam -in:trash -has:userlabels'
        }

        email_distribution = {}
        for name, query in key_searches.items():
            count = self.search_emails(account, query, max_results=1)
            email_distribution[name] = count
            print(f"   {name}: {count:,}")

        # Check for "lost" emails (not in inbox, sent, or common folders)
        print(f"\n🔍 Checking for potential issues...")

        # Check if sent emails exist
        sent_count = email_distribution.get('SENT', 0)
        if sent_count == 0:
            self.results['issues'].append({
                'account': account,
                'type': 'SENT_EMPTY',
                'message': 'SENT folder appears empty - this is unusual'
            })
            print(f"   ⚠️  SENT folder is empty!")

        # Check for high spam
        spam_count = email_distribution.get('SPAM', 0)
        if spam_count > 1000:
            self.results['issues'].append({
                'account': account,
                'type': 'HIGH_SPAM',
                'message': f'High spam count: {spam_count}'
            })
            print(f"   ⚠️  High spam count: {spam_count}")

        # Check for emails outside inbox that might be "hidden"
        archived = email_distribution.get('Archived (no labels)', 0)
        if archived > 100:
            print(f"   ℹ️  {archived:,} emails are archived (not in inbox, no user labels)")

        return {
            'email': email,
            'profile': profile,
            'labels': label_analysis,
            'filters': filter_analysis,
            'distribution': email_distribution
        }

    def run_all(self):
        """Run diagnostic on all accounts"""
        print("\n" + "="*70)
        print("📧 EMAIL DIAGNOSTIC TOOL")
        print("="*70)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Accounts to check: {len(ACCOUNTS)}")

        # Check token directory
        print(f"\n📂 Token directory: {TOKEN_DIR}")
        if TOKEN_DIR.exists():
            token_files = list(TOKEN_DIR.glob("*.json"))
            print(f"   Found {len(token_files)} token files")

            # Check for duplicate/backup tokens
            backup_tokens = [f for f in token_files if 'backup' in f.name.lower() or ' ' in f.name]
            if backup_tokens:
                print(f"   ⚠️  Found {len(backup_tokens)} backup/duplicate token files:")
                for bt in backup_tokens:
                    print(f"      - {bt.name}")
        else:
            print(f"   ❌ Token directory not found!")
            return

        # Run diagnostic on each account
        for account in ACCOUNTS:
            result = self.run_diagnostic(account)
            self.results['accounts'][account] = result

        # Summary
        self.print_summary()

        # Save results
        self.save_results()

    def print_summary(self):
        """Print summary of findings"""
        print("\n" + "="*70)
        print("📋 SUMMARY")
        print("="*70)

        total_issues = len(self.results['issues'])
        print(f"\n🔴 Total issues found: {total_issues}")

        if self.results['issues']:
            print("\nIssues by type:")
            issues_by_type = defaultdict(list)
            for issue in self.results['issues']:
                issues_by_type[issue['type']].append(issue)

            for issue_type, issues in issues_by_type.items():
                print(f"\n  {issue_type}: {len(issues)}")
                for issue in issues:
                    print(f"    - [{issue['account']}] {issue['message']}")

        # Label summary across accounts
        print("\n📁 Labels across accounts:")
        for account, data in self.results['accounts'].items():
            if 'labels' in data:
                labels = data['labels']
                print(f"\n  {account}:")
                print(f"    Total: {labels['total']}")
                print(f"    User-created: {len(labels['user'])}")
                if labels['duplicates']:
                    print(f"    ⚠️  Duplicates: {len(labels['duplicates'])}")

        # Filter summary
        print("\n🔧 Filters across accounts:")
        for account, data in self.results['accounts'].items():
            if 'filters' in data:
                filters = data['filters']
                print(f"\n  {account}:")
                print(f"    Total: {filters['total']}")
                if filters['duplicates']:
                    print(f"    ⚠️  Duplicates: {len(filters['duplicates'])}")
                if filters['conflicts']:
                    print(f"    ⚠️  Conflicts: {len(filters['conflicts'])}")

        print("\n" + "="*70)
        print("🏁 DIAGNOSTIC COMPLETE")
        print("="*70)

    def save_results(self):
        """Save results to JSON file"""
        output_file = Path(__file__).parent / 'email_diagnostic_results.json'

        # Clean up non-serializable data
        clean_results = json.loads(json.dumps(self.results, default=str))

        with open(output_file, 'w') as f:
            json.dump(clean_results, f, indent=2)

        print(f"\n💾 Results saved to: {output_file}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    if not GMAIL_API_AVAILABLE:
        print("Cannot run diagnostic without Google API libraries")
        exit(1)

    diagnostic = EmailDiagnostic()
    diagnostic.run_all()
