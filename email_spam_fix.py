#!/usr/bin/env python3
"""
SPAM & NOTIFICATION FIX
=======================
Fixes wrongly-spammed emails and sets up proper notification handling.

Issues this fixes:
1. Your own domain emails going to spam (MCR)
2. Legitimate services wrongly in spam
3. Proper notification classification

Run: python email_spam_fix.py
"""

import json
from pathlib import Path
from collections import defaultdict

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
except ImportError:
    print("Google API libraries required")
    exit(1)

TOKEN_DIR = Path(__file__).parent / "gmail_tokens"
CREDS_FILE = Path(__file__).parent / "config" / "credentials.json"

ACCOUNTS = {
    'kaplan.brian@gmail.com': 'tokens_kaplan_brian_gmail_com.json',
}

# Domains that should NEVER be in spam
WHITELIST_DOMAINS = [
    # Your own domains
    'musiccityrodeo.com', 'm.musiccityrodeo.com',
    'downhome.com',

    # Airlines & Travel
    'southwest.com', 'iluv.southwest.com',
    'delta.com', 'e.delta.com',
    'united.com', 'aa.com',
    'avis.com', 'e.avis.com',
    'hilton.com', 'marriott.com',

    # Rideshare & Delivery
    'lyft.com', 'lyftmail.com', 'marketing.lyftmail.com',
    'uber.com',
    'doordash.com', 'grubhub.com',

    # Services you use
    'siriusxm.com', 'e.siriusxm.com',
    'pbr.com', 'emails.pbr.com',
    'ihop.com', 'email.ihop.com',
    'buckle.com', 'thebuckle.com',

    # School/Family (critical)
    'parentsquare.com',
    'wilsonk12tn.us', 'wcschools.com',

    # Financial
    'robinhood.com', 'stripe.com', 'paypal.com',
    'venmo.com', 'squareup.com',

    # Tech services
    'github.com', 'google.com', 'apple.com',
    'amazon.com', 'anthropic.com',
]

# Notification senders (for labeling)
NOTIFICATION_SENDERS = [
    # School - CRITICAL
    'parentsquare.com', 'wilsonk12tn.us', 'wcschools.com',

    # Device/Home
    'samsung', 'eero.com', 'ecobee.com', 'ring.com',

    # Health
    'valant.io', 'eclinicalmail.com',

    # Tech notifications
    'github.com', 'accounts.google.com',
]


def get_service(token_file):
    with open(CREDS_FILE) as f:
        creds_data = json.load(f)
    client = creds_data.get('web', {})

    with open(TOKEN_DIR / token_file) as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data.get('access_token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client.get('client_id'),
        client_secret=client.get('client_secret'),
        scopes=token_data.get('scope', '').split()
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data['access_token'] = creds.token
        with open(TOKEN_DIR / token_file, 'w') as f:
            json.dump(token_data, f, indent=2)

    return build('gmail', 'v1', credentials=creds)


def rescue_from_spam(service, execute=False):
    """Move whitelisted emails out of spam"""
    print("\n" + "="*60)
    print("🚨 RESCUING EMAILS FROM SPAM")
    print("="*60)

    # Get spam messages
    messages = service.users().messages().list(
        userId='me', labelIds=['SPAM'], maxResults=200
    ).execute().get('messages', [])

    print(f"Checking {len(messages)} spam messages...")

    to_rescue = []

    for msg in messages:
        try:
            detail = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From']
            ).execute()
            headers = {h['name']: h['value'] for h in detail.get('payload', {}).get('headers', [])}
            sender = headers.get('From', '').lower()

            for domain in WHITELIST_DOMAINS:
                if domain.lower() in sender:
                    to_rescue.append({
                        'id': msg['id'],
                        'from': headers.get('From', ''),
                        'domain': domain
                    })
                    break
        except:
            pass

    print(f"\n✅ Found {len(to_rescue)} emails to rescue from spam:")

    # Group by domain
    by_domain = defaultdict(list)
    for r in to_rescue:
        by_domain[r['domain']].append(r)

    for domain, emails in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        print(f"   {len(emails):3}x  {domain}")

    if execute and to_rescue:
        print("\n🔄 Moving emails out of spam...")

        # Get INBOX label ID
        labels = service.users().labels().list(userId='me').execute().get('labels', [])
        inbox_id = None
        spam_id = None
        for l in labels:
            if l['name'] == 'INBOX':
                inbox_id = l['id']
            if l['name'] == 'SPAM':
                spam_id = l['id']

        if inbox_id and spam_id:
            # Batch in groups of 100
            ids = [r['id'] for r in to_rescue]
            for i in range(0, len(ids), 100):
                batch = ids[i:i+100]
                try:
                    service.users().messages().batchModify(
                        userId='me',
                        body={
                            'ids': batch,
                            'addLabelIds': [inbox_id],
                            'removeLabelIds': [spam_id]
                        }
                    ).execute()
                    print(f"   ✅ Rescued {len(batch)} emails")
                except Exception as e:
                    print(f"   ❌ Error: {e}")

    return to_rescue


def create_never_spam_filter(service, domain, execute=False):
    """Create a filter to prevent domain from going to spam"""
    print(f"\n📋 Creating 'never spam' filter for: {domain}")

    filter_body = {
        'criteria': {
            'from': f'@{domain}'
        },
        'action': {
            'removeLabelIds': ['SPAM'],
            'addLabelIds': ['INBOX']  # Always go to inbox, never spam
        }
    }

    if execute:
        try:
            service.users().settings().filters().create(
                userId='me', body=filter_body
            ).execute()
            print(f"   ✅ Created filter")
            return True
        except Exception as e:
            if 'already exists' in str(e).lower():
                print(f"   ℹ️  Filter already exists")
            else:
                print(f"   ❌ Error: {e}")
            return False
    else:
        print(f"   📋 Would create filter for @{domain}")
        return True


def analyze_notifications(service):
    """Analyze what's being labeled as notifications"""
    print("\n" + "="*60)
    print("🔔 NOTIFICATION ANALYSIS")
    print("="*60)

    # Get user's Notifications label
    labels = service.users().labels().list(userId='me').execute().get('labels', [])

    notif_labels = {}
    for l in labels:
        if 'notif' in l['name'].lower():
            details = service.users().labels().get(userId='me', id=l['id']).execute()
            notif_labels[l['name']] = {
                'id': l['id'],
                'total': details.get('messagesTotal', 0),
                'unread': details.get('messagesUnread', 0)
            }

    print("\nYour notification-related labels:")
    for name, info in notif_labels.items():
        print(f"   {name}: {info['total']} total, {info['unread']} unread")

    # Analyze Gmail's category:updates (Google's "notifications")
    print("\n📊 Gmail's CATEGORY_UPDATES (last 50):")

    messages = service.users().messages().list(
        userId='me', q='category:updates', maxResults=50
    ).execute().get('messages', [])

    senders = defaultdict(int)
    for msg in messages:
        try:
            detail = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From']
            ).execute()
            headers = {h['name']: h['value'] for h in detail.get('payload', {}).get('headers', [])}
            sender = headers.get('From', '')

            import re
            match = re.search(r'@([a-zA-Z0-9.-]+)', sender)
            domain = match.group(1) if match else 'unknown'
            senders[domain] += 1
        except:
            pass

    for domain, count in sorted(senders.items(), key=lambda x: -x[1])[:15]:
        priority = "⭐ IMPORTANT" if any(x in domain for x in ['parentsquare', 'school', 'wcschools']) else ""
        print(f"   {count:3}x  {domain} {priority}")

    return notif_labels


def main():
    import sys

    execute = '--execute' in sys.argv

    if not execute:
        print("\n⚠️  PREVIEW MODE - Add --execute to make changes\n")

    for account, token_file in ACCOUNTS.items():
        print(f"\n{'='*70}")
        print(f"📧 Processing: {account}")
        print(f"{'='*70}")

        service = get_service(token_file)

        # 1. Rescue from spam
        rescued = rescue_from_spam(service, execute=execute)

        # 2. Create filters for key domains
        print("\n" + "="*60)
        print("🛡️ CREATING 'NEVER SPAM' FILTERS")
        print("="*60)

        # Your domains - critical
        key_domains = [
            'musiccityrodeo.com',
            'm.musiccityrodeo.com',
            'downhome.com',
            'parentsquare.com',  # School
            'wilsonk12tn.us',    # School district
        ]

        for domain in key_domains:
            create_never_spam_filter(service, domain, execute=execute)

        # 3. Analyze notifications
        analyze_notifications(service)

    print("\n" + "="*70)
    print("✅ COMPLETE")
    print("="*70)

    if not execute:
        print("\nRun with --execute to apply changes:")
        print("  python email_spam_fix.py --execute")


if __name__ == '__main__':
    main()
