#!/usr/bin/env python3
"""
GARBAGE EMAIL BLOCKER
=====================
Blocks identified garbage domains and deletes existing emails from them.

Run: python email_garbage_blocker.py --execute
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
    'brian@downhome.com': 'tokens_brian_downhome_com.json',
    'brian@musiccityrodeo.com': 'tokens_brian_musiccityrodeo_com.json',
}

# GARBAGE DOMAINS TO BLOCK - identified from spam/promo analysis
GARBAGE_DOMAINS = [
    # Political garbage
    'turnoutpac.org',
    'actblue.com',
    'dccc.org',
    'democrats.org',

    # Glasses spam (you don't need 4 glasses companies)
    'glassesusa.com',
    'eyebuydirect.com',
    'mentraglass.com',

    # Random marketing garbage
    'babylonbee.com',
    'topazlabs.com',
    'ridge.com',
    'woodlanddirect.com',
    'patioliving.com',
    'smartistu.com',
    'wrangler.com',
    'overstock.com',
    'cloudhq.net',
    'cofounderslab.com',
    'interestingfacts.com',
    'every.to',

    # Low-value newsletters
    'adventuresci.org',

    # Epoch Times (already blocked but ensure it's here)
    'epochtimes.com',
    'theepochtimes.com',
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


def create_trash_filter(service, domain, execute=False):
    """Create filter to auto-trash emails from domain"""
    filter_body = {
        'criteria': {
            'from': f'@{domain}'
        },
        'action': {
            'removeLabelIds': ['INBOX'],
            'addLabelIds': ['TRASH']
        }
    }

    if execute:
        try:
            service.users().settings().filters().create(
                userId='me', body=filter_body
            ).execute()
            return True
        except Exception as e:
            if 'already exists' in str(e).lower():
                return True  # Already blocked
            return False
    return True


def delete_existing_emails(service, domain, execute=False):
    """Find and delete all emails from domain"""
    try:
        # Search for emails from this domain
        query = f'from:@{domain}'
        messages = []
        page_token = None

        while True:
            result = service.users().messages().list(
                userId='me', q=query, maxResults=500,
                pageToken=page_token
            ).execute()

            messages.extend(result.get('messages', []))
            page_token = result.get('nextPageToken')
            if not page_token:
                break

        if not messages:
            return 0

        if execute:
            # Batch delete (move to trash)
            ids = [m['id'] for m in messages]
            for i in range(0, len(ids), 100):
                batch = ids[i:i+100]
                try:
                    service.users().messages().batchModify(
                        userId='me',
                        body={
                            'ids': batch,
                            'addLabelIds': ['TRASH'],
                            'removeLabelIds': ['INBOX', 'UNREAD']
                        }
                    ).execute()
                except Exception as e:
                    print(f"      Error deleting batch: {e}")

        return len(messages)
    except Exception as e:
        return 0


def main():
    import sys

    execute = '--execute' in sys.argv

    if not execute:
        print("\n" + "="*70)
        print("  PREVIEW MODE - Add --execute to make changes")
        print("="*70 + "\n")

    print("="*70)
    print("  GARBAGE EMAIL BLOCKER")
    print("  Blocking {} domains across all accounts".format(len(GARBAGE_DOMAINS)))
    print("="*70)

    total_deleted = 0
    total_filters = 0

    for account, token_file in ACCOUNTS.items():
        print(f"\n{'='*60}")
        print(f"  {account}")
        print(f"{'='*60}")

        try:
            service = get_service(token_file)
        except Exception as e:
            print(f"  Error connecting: {e}")
            continue

        account_deleted = 0
        account_filters = 0

        print(f"\n  Blocking {len(GARBAGE_DOMAINS)} garbage domains...\n")

        for domain in GARBAGE_DOMAINS:
            # Count existing emails
            count = delete_existing_emails(service, domain, execute=False)

            if count > 0 or True:  # Always create filter
                # Create filter
                if create_trash_filter(service, domain, execute=execute):
                    account_filters += 1

                # Delete existing
                if count > 0:
                    if execute:
                        delete_existing_emails(service, domain, execute=True)
                    print(f"    {domain}: {count} emails deleted, filter created")
                    account_deleted += count

        print(f"\n  Summary for {account}:")
        print(f"    Filters created: {account_filters}")
        print(f"    Emails deleted: {account_deleted}")

        total_deleted += account_deleted
        total_filters += account_filters

    print("\n" + "="*70)
    print("  TOTAL RESULTS")
    print("="*70)
    print(f"  Total filters created: {total_filters}")
    print(f"  Total emails deleted: {total_deleted}")
    print("="*70)

    if not execute:
        print("\nRun with --execute to apply changes:")
        print("  python email_garbage_blocker.py --execute")
    else:
        print("\n  All garbage blocked and deleted!")


if __name__ == '__main__':
    main()
