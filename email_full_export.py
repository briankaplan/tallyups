#!/usr/bin/env python3
"""
COMPREHENSIVE EMAIL EXPORT & ANALYSIS
=====================================
Exports EVERYTHING about your email accounts:
- All labels with full details
- All filters with full criteria
- Email counts per label
- Sample emails from each label
- Complete backup of all settings

This creates a complete snapshot BEFORE any changes.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False
    print("❌ Google API libraries not available")

TOKEN_DIR = Path(__file__).parent / "gmail_tokens"
CREDENTIALS_FILE = Path(__file__).parent / "config" / "credentials.json"
EXPORT_DIR = Path(__file__).parent / "email_exports"

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


class EmailFullExport:
    """Complete email account export"""

    def __init__(self):
        self.services = {}
        EXPORT_DIR.mkdir(exist_ok=True)

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

    def export_account(self, account: str) -> dict:
        """Export complete account data"""
        print(f"\n{'='*70}")
        print(f"📤 EXPORTING: {account}")
        print(f"{'='*70}")

        if not self.authenticate(account):
            return {'error': 'Authentication failed'}

        service = self.services[account]
        export = {
            'account': account,
            'type': ACCOUNTS[account]['type'],
            'exported_at': datetime.now().isoformat(),
            'profile': {},
            'labels': [],
            'filters': [],
            'statistics': {}
        }

        # 1. Profile
        print("\n📊 Getting profile...")
        try:
            profile = service.users().getProfile(userId='me').execute()
            export['profile'] = {
                'email': profile.get('emailAddress'),
                'messagesTotal': profile.get('messagesTotal', 0),
                'threadsTotal': profile.get('threadsTotal', 0),
                'historyId': profile.get('historyId')
            }
            print(f"   Total messages: {export['profile']['messagesTotal']:,}")
            print(f"   Total threads: {export['profile']['threadsTotal']:,}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        # 2. All Labels with Full Details
        print("\n📁 Exporting ALL labels...")
        try:
            labels_result = service.users().labels().list(userId='me').execute()
            labels = labels_result.get('labels', [])

            for label in labels:
                label_id = label['id']
                try:
                    # Get full label details
                    details = service.users().labels().get(userId='me', id=label_id).execute()

                    label_export = {
                        'id': label_id,
                        'name': details.get('name'),
                        'type': details.get('type', 'user'),
                        'messageListVisibility': details.get('messageListVisibility'),
                        'labelListVisibility': details.get('labelListVisibility'),
                        'messagesTotal': details.get('messagesTotal', 0),
                        'messagesUnread': details.get('messagesUnread', 0),
                        'threadsTotal': details.get('threadsTotal', 0),
                        'threadsUnread': details.get('threadsUnread', 0),
                        'color': details.get('color')
                    }

                    # Get sample emails from this label (first 5)
                    try:
                        messages = service.users().messages().list(
                            userId='me',
                            labelIds=[label_id],
                            maxResults=5
                        ).execute().get('messages', [])

                        samples = []
                        for msg in messages[:3]:
                            msg_detail = service.users().messages().get(
                                userId='me',
                                id=msg['id'],
                                format='metadata',
                                metadataHeaders=['Subject', 'From', 'Date']
                            ).execute()

                            headers = {h['name']: h['value'] for h in msg_detail.get('payload', {}).get('headers', [])}
                            samples.append({
                                'id': msg['id'],
                                'subject': headers.get('Subject', '')[:100],
                                'from': headers.get('From', '')[:100],
                                'date': headers.get('Date', '')
                            })
                        label_export['sample_emails'] = samples
                    except:
                        pass

                    export['labels'].append(label_export)
                    print(f"   ✅ {label_export['name']:40} {label_export['messagesTotal']:>6} msgs")

                except Exception as e:
                    print(f"   ⚠️ Error getting label {label_id}: {e}")

        except Exception as e:
            print(f"   ❌ Error listing labels: {e}")

        # 3. All Filters with Full Details
        print("\n🔧 Exporting ALL filters...")
        try:
            filters_result = service.users().settings().filters().list(userId='me').execute()
            filters = filters_result.get('filter', [])

            for f in filters:
                filter_export = {
                    'id': f.get('id'),
                    'criteria': f.get('criteria', {}),
                    'action': f.get('action', {}),
                    'analysis': self._analyze_filter(f)
                }
                export['filters'].append(filter_export)

            print(f"   ✅ Exported {len(filters)} filters")

            # Analyze filter patterns
            archive_count = sum(1 for f in export['filters']
                              if 'INBOX' in f.get('action', {}).get('removeLabelIds', []))
            skip_inbox = sum(1 for f in export['filters']
                            if f.get('action', {}).get('skipInbox'))
            auto_label = sum(1 for f in export['filters']
                            if f.get('action', {}).get('addLabelIds'))

            print(f"   📊 Filters that archive: {archive_count}")
            print(f"   📊 Filters that skip inbox: {skip_inbox}")
            print(f"   📊 Filters that add labels: {auto_label}")

        except Exception as e:
            print(f"   ⚠️ Error listing filters: {e}")

        # 4. Key Statistics
        print("\n📈 Gathering statistics...")
        searches = {
            'inbox': 'in:inbox',
            'sent': 'in:sent',
            'drafts': 'in:drafts',
            'spam': 'in:spam',
            'trash': 'in:trash',
            'starred': 'is:starred',
            'unread': 'is:unread',
            'archived': '-in:inbox -in:spam -in:trash',
            'has_attachment': 'has:attachment',
            'from_amazon': 'from:amazon.com',
            'from_apple': 'from:apple.com',
            'from_google': 'from:google.com',
            'from_paypal': 'from:paypal.com',
            'from_stripe': 'from:stripe.com',
            'receipts_label': 'label:receipts' if any(l['name'].lower() == 'receipts' for l in export['labels']) else None,
        }

        for name, query in searches.items():
            if query is None:
                continue
            try:
                result = service.users().messages().list(
                    userId='me', q=query, maxResults=1
                ).execute()
                count = result.get('resultSizeEstimate', 0)
                export['statistics'][name] = count
                print(f"   {name}: {count:,}")
            except:
                pass

        return export

    def _analyze_filter(self, filter_data: dict) -> dict:
        """Analyze a filter for potential issues"""
        analysis = {
            'type': 'unknown',
            'risk_level': 'low',
            'notes': []
        }

        criteria = filter_data.get('criteria', {})
        action = filter_data.get('action', {})

        # Determine filter type
        if 'INBOX' in action.get('removeLabelIds', []):
            analysis['type'] = 'archive'
            analysis['notes'].append('Removes from inbox (archives)')
        elif action.get('addLabelIds'):
            analysis['type'] = 'label'
            analysis['notes'].append('Adds labels')
        elif action.get('forward'):
            analysis['type'] = 'forward'
            analysis['notes'].append('Forwards emails')
        elif 'TRASH' in action.get('addLabelIds', []):
            analysis['type'] = 'delete'
            analysis['risk_level'] = 'high'
            analysis['notes'].append('Moves to trash!')

        # Check for receipt senders being archived
        from_addr = criteria.get('from', '').lower()
        receipt_senders = ['amazon', 'apple', 'google', 'paypal', 'stripe', 'uber', 'lyft', 'doordash']

        if analysis['type'] == 'archive':
            for sender in receipt_senders:
                if sender in from_addr:
                    analysis['risk_level'] = 'medium'
                    analysis['notes'].append(f'Archives {sender} emails - receipts may be hidden!')
                    break

        return analysis

    def run_full_export(self):
        """Export all accounts"""
        print("\n" + "=" * 70)
        print("📤 FULL EMAIL EXPORT - SAFETY BACKUP")
        print("=" * 70)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Export directory: {EXPORT_DIR}")

        all_exports = {
            'exported_at': datetime.now().isoformat(),
            'accounts': {}
        }

        for account in ACCOUNTS:
            export = self.export_account(account)
            all_exports['accounts'][account] = export

            # Save individual account export
            safe_name = account.replace('@', '_at_').replace('.', '_')
            account_file = EXPORT_DIR / f"{safe_name}_export.json"
            with open(account_file, 'w') as f:
                json.dump(export, f, indent=2)
            print(f"\n💾 Saved: {account_file}")

        # Save combined export
        combined_file = EXPORT_DIR / f"full_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(combined_file, 'w') as f:
            json.dump(all_exports, f, indent=2)
        print(f"\n💾 Combined export: {combined_file}")

        # Generate summary report
        self.generate_report(all_exports)

    def generate_report(self, exports: dict):
        """Generate human-readable report"""
        report_file = EXPORT_DIR / "EMAIL_ANALYSIS_REPORT.md"

        with open(report_file, 'w') as f:
            f.write("# EMAIL ANALYSIS REPORT\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            for account, data in exports['accounts'].items():
                if 'error' in data:
                    continue

                f.write(f"## {account}\n")
                f.write(f"**Type:** {data['type']}\n\n")

                # Profile
                profile = data.get('profile', {})
                f.write(f"### Statistics\n")
                f.write(f"- Total Messages: {profile.get('messagesTotal', 0):,}\n")
                f.write(f"- Total Threads: {profile.get('threadsTotal', 0):,}\n\n")

                # Labels
                f.write(f"### Labels ({len(data.get('labels', []))} total)\n\n")
                f.write("| Label | Messages | Unread | Type |\n")
                f.write("|-------|----------|--------|------|\n")

                for label in sorted(data.get('labels', []), key=lambda x: x.get('name', '')):
                    name = label.get('name', 'Unknown')
                    msgs = label.get('messagesTotal', 0)
                    unread = label.get('messagesUnread', 0)
                    ltype = label.get('type', 'user')
                    f.write(f"| {name} | {msgs:,} | {unread:,} | {ltype} |\n")

                f.write("\n")

                # Filters
                filters = data.get('filters', [])
                f.write(f"### Filters ({len(filters)} total)\n\n")

                # Group by risk
                high_risk = [fl for fl in filters if fl.get('analysis', {}).get('risk_level') == 'high']
                medium_risk = [fl for fl in filters if fl.get('analysis', {}).get('risk_level') == 'medium']

                if high_risk:
                    f.write(f"#### ⚠️ HIGH RISK FILTERS ({len(high_risk)})\n")
                    for fl in high_risk:
                        f.write(f"- `{fl.get('criteria', {})}` → {fl.get('analysis', {}).get('notes', [])}\n")
                    f.write("\n")

                if medium_risk:
                    f.write(f"#### 🟡 MEDIUM RISK FILTERS ({len(medium_risk)})\n")
                    for fl in medium_risk:
                        criteria = fl.get('criteria', {})
                        notes = fl.get('analysis', {}).get('notes', [])
                        f.write(f"- from:`{criteria.get('from', 'N/A')}` → {', '.join(notes)}\n")
                    f.write("\n")

                # All filters detail
                f.write("#### All Filters\n\n")
                f.write("| From/Query | Action | Risk |\n")
                f.write("|------------|--------|------|\n")
                for fl in filters[:50]:  # Limit to 50
                    criteria = fl.get('criteria', {})
                    from_addr = criteria.get('from', criteria.get('query', 'N/A'))[:40]
                    analysis = fl.get('analysis', {})
                    action_type = analysis.get('type', 'unknown')
                    risk = analysis.get('risk_level', 'low')
                    f.write(f"| {from_addr} | {action_type} | {risk} |\n")

                f.write("\n---\n\n")

        print(f"\n📄 Report saved: {report_file}")


if __name__ == '__main__':
    if not GMAIL_API_AVAILABLE:
        print("Cannot run export without Google API libraries")
        exit(1)

    exporter = EmailFullExport()
    exporter.run_full_export()
