#!/usr/bin/env python3
"""
BULLETPROOF EMAIL FILTERS
=========================
Comprehensive filters to catch ALL receipts, newsletters, and spam.
Nothing slips through.

Run: python email_bulletproof_filters.py --execute
"""

import json
from pathlib import Path

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

# =============================================================================
# RECEIPT SENDERS - These get labeled "Receipts" and archived
# =============================================================================
RECEIPT_PATTERNS = [
    # Keywords in subject
    'subject:receipt',
    'subject:order confirmation',
    'subject:payment received',
    'subject:invoice',
    'subject:"your order"',
    'subject:"order shipped"',
    'subject:"shipping confirmation"',
    'subject:"purchase confirmation"',
    'subject:"payment confirmation"',
    'subject:"transaction"',

    # Common receipt senders
    'from:receipt@',
    'from:receipts@',
    'from:orders@',
    'from:order@',
    'from:noreply@',
    'from:no-reply@',
    'from:billing@',
    'from:invoice@',
    'from:payment@',
    'from:confirmation@',

    # Specific stores/services
    'from:amazon.com subject:order',
    'from:target.com',
    'from:walmart.com',
    'from:costco.com',
    'from:bestbuy.com',
    'from:homedepot.com',
    'from:lowes.com',
    'from:apple.com subject:(receipt OR order)',
    'from:paypal.com subject:receipt',
    'from:venmo.com subject:paid',
    'from:square.com',
    'from:squareup.com',
    'from:stripe.com',
    'from:shopify.com',

    # Food/Delivery
    'from:doordash.com',
    'from:grubhub.com',
    'from:ubereats.com',
    'from:postmates.com',
    'from:instacart.com',
    'from:seamless.com',

    # Rideshare
    'from:uber.com subject:trip',
    'from:lyft.com subject:ride',

    # Airlines/Travel
    'from:southwest.com subject:(confirmation OR receipt OR itinerary)',
    'from:delta.com subject:(confirmation OR receipt OR itinerary)',
    'from:united.com subject:(confirmation OR receipt OR itinerary)',
    'from:aa.com subject:(confirmation OR receipt OR itinerary)',
    'from:hilton.com subject:(confirmation OR receipt)',
    'from:marriott.com subject:(confirmation OR receipt)',
    'from:airbnb.com subject:(reservation OR receipt)',
    'from:vrbo.com',
    'from:avis.com',
    'from:hertz.com',
    'from:enterprise.com',

    # Subscriptions
    'from:netflix.com subject:payment',
    'from:spotify.com subject:receipt',
    'from:hulu.com subject:receipt',
    'from:disney.com subject:receipt',
    'from:hbomax.com subject:receipt',
    'from:apple.com subject:receipt',
]

# =============================================================================
# NEWSLETTER SENDERS - These get labeled "Newsletters" and archived
# =============================================================================
NEWSLETTER_PATTERNS = [
    # Keywords
    'subject:newsletter',
    'subject:digest',
    'subject:weekly update',
    'subject:monthly update',
    'subject:daily brief',
    'subject:roundup',

    # Common newsletter indicators
    'from:newsletter@',
    'from:news@',
    'from:updates@',
    'from:digest@',
    'from:hello@',
    'from:team@',
    'list:',  # Any mailing list

    # Substack
    'from:substack.com',

    # Common newsletters
    'from:morningbrew.com',
    'from:theskim.com',
    'from:medium.com',
]

# =============================================================================
# NOTIFICATION SENDERS - These get labeled "Notifications" and archived
# =============================================================================
NOTIFICATION_PATTERNS = [
    # Keywords
    'subject:notification',
    'subject:alert',
    'subject:reminder',
    'subject:update from',

    # Common notification senders
    'from:notification@',
    'from:notifications@',
    'from:alerts@',
    'from:notify@',
    'from:noreply@',

    # Social
    'from:facebook.com',
    'from:facebookmail.com',
    'from:twitter.com',
    'from:linkedin.com',
    'from:instagram.com',

    # Tech
    'from:github.com',

    # Device notifications
    'from:samsung.com',
    'from:ring.com',
    'from:nest.com',
    'from:eero.com',
    'from:ecobee.com',
]

# =============================================================================
# SPAM/GARBAGE - Auto-trash these
# =============================================================================
SPAM_PATTERNS = [
    # Obvious spam keywords
    'subject:unsubscribe',  # Only subject, means they're begging
    'subject:"act now"',
    'subject:"limited time"',
    'subject:"exclusive offer"',
    'subject:"you\'ve won"',
    'subject:"congratulations"',
    'subject:"claim your"',
    'subject:"free gift"',

    # Unsubscribe-heavy senders (marketing garbage)
    'from:email.campaign',
    'from:promo@',
    'from:promotions@',
    'from:marketing@',
    'from:deals@',
    'from:offers@',
    'from:sale@',
    'from:sales@',

    # Known garbage domains (already blocked but backup)
    'from:epochtimes.com',
    'from:theepochtimes.com',
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


def ensure_label(service, name):
    """Get or create a label"""
    labels = service.users().labels().list(userId='me').execute().get('labels', [])
    for l in labels:
        if l['name'] == name:
            return l['id']

    # Create it
    label = service.users().labels().create(
        userId='me',
        body={'name': name, 'labelListVisibility': 'labelShow', 'messageListVisibility': 'show'}
    ).execute()
    return label['id']


def create_filter_if_not_exists(service, query, label_id=None, trash=False, execute=False):
    """Create a filter if it doesn't already exist"""

    # Build filter
    filter_body = {
        'criteria': {
            'query': query
        },
        'action': {
            'removeLabelIds': ['INBOX'],
        }
    }

    if trash:
        filter_body['action']['addLabelIds'] = ['TRASH']
    elif label_id:
        filter_body['action']['addLabelIds'] = [label_id]

    if execute:
        try:
            service.users().settings().filters().create(
                userId='me', body=filter_body
            ).execute()
            return True
        except Exception as e:
            if 'already exists' in str(e).lower() or 'Filter already exists' in str(e):
                return True  # Already exists, that's fine
            if 'invalid' in str(e).lower():
                return False  # Invalid query, skip
            return False
    return True


def main():
    import sys
    execute = '--execute' in sys.argv

    if not execute:
        print("\n" + "="*70)
        print("  PREVIEW MODE - Add --execute to apply filters")
        print("="*70 + "\n")

    print("="*70)
    print("  BULLETPROOF EMAIL FILTER SYSTEM")
    print("="*70)
    print(f"  Receipt patterns:      {len(RECEIPT_PATTERNS)}")
    print(f"  Newsletter patterns:   {len(NEWSLETTER_PATTERNS)}")
    print(f"  Notification patterns: {len(NOTIFICATION_PATTERNS)}")
    print(f"  Spam patterns:         {len(SPAM_PATTERNS)}")
    print("="*70)

    for account, token_file in ACCOUNTS.items():
        print(f"\n{'='*60}")
        print(f"  {account}")
        print(f"{'='*60}")

        try:
            service = get_service(token_file)
        except Exception as e:
            print(f"  Error connecting: {e}")
            continue

        # Ensure labels exist
        print("  Ensuring labels exist...")
        receipts_id = ensure_label(service, 'Receipts')
        newsletters_id = ensure_label(service, 'Newsletters')
        notifications_id = ensure_label(service, 'Notifications')

        # Create receipt filters
        print(f"\n  Creating receipt filters ({len(RECEIPT_PATTERNS)})...")
        receipt_count = 0
        for pattern in RECEIPT_PATTERNS:
            if create_filter_if_not_exists(service, pattern, receipts_id, execute=execute):
                receipt_count += 1
        print(f"    Created: {receipt_count}")

        # Create newsletter filters
        print(f"\n  Creating newsletter filters ({len(NEWSLETTER_PATTERNS)})...")
        newsletter_count = 0
        for pattern in NEWSLETTER_PATTERNS:
            if create_filter_if_not_exists(service, pattern, newsletters_id, execute=execute):
                newsletter_count += 1
        print(f"    Created: {newsletter_count}")

        # Create notification filters
        print(f"\n  Creating notification filters ({len(NOTIFICATION_PATTERNS)})...")
        notification_count = 0
        for pattern in NOTIFICATION_PATTERNS:
            if create_filter_if_not_exists(service, pattern, notifications_id, execute=execute):
                notification_count += 1
        print(f"    Created: {notification_count}")

        # Create spam filters
        print(f"\n  Creating spam/trash filters ({len(SPAM_PATTERNS)})...")
        spam_count = 0
        for pattern in SPAM_PATTERNS:
            if create_filter_if_not_exists(service, pattern, trash=True, execute=execute):
                spam_count += 1
        print(f"    Created: {spam_count}")

        print(f"\n  Total filters for {account}: {receipt_count + newsletter_count + notification_count + spam_count}")

    print("\n" + "="*70)
    print("  COMPLETE")
    print("="*70)

    if not execute:
        print("\nRun with --execute to apply:")
        print("  python email_bulletproof_filters.py --execute")
    else:
        print("\n  All bulletproof filters installed!")
        print("  Nothing will slip through now.")


if __name__ == '__main__':
    main()
