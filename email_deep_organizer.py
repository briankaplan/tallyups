#!/usr/bin/env python3
"""
DEEP EMAIL ORGANIZER
====================
Comprehensive email organization system that scrutinizes every email.
Creates proper folder structure and organizes ALL emails correctly.

Labels Created:
- Receipts (purchases, orders, shipping)
- Invoices (bills, payment requests)
- Legal (contracts, agreements, DocuSign, Adobe Sign)
- Finance (banking, statements, tax)
- Business (work correspondence)
- Newsletters
- Notifications

Run: python email_deep_organizer.py --execute
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

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
# COMPREHENSIVE CATEGORIZATION RULES
# =============================================================================

# RECEIPTS - Purchase confirmations, orders, shipping
RECEIPT_PATTERNS = {
    'subjects': [
        r'receipt', r'order confirm', r'order #', r'order number',
        r'purchase confirm', r'payment confirm', r'payment received',
        r'your order', r'order shipped', r'shipping confirm', r'has shipped',
        r'delivery confirm', r'out for delivery', r'delivered',
        r'thank you for your order', r'thanks for your order',
        r'booking confirm', r'reservation confirm', r'itinerary',
        r'e-?receipt', r'digital receipt',
    ],
    'senders': [
        r'receipt@', r'receipts@', r'orders@', r'order@', r'billing@',
        r'confirmation@', r'noreply@.*\.(amazon|target|walmart|costco)',
        r'@amazon\.com', r'@target\.com', r'@walmart\.com', r'@costco\.com',
        r'@bestbuy\.com', r'@homedepot\.com', r'@lowes\.com', r'@apple\.com',
        r'@doordash\.com', r'@grubhub\.com', r'@ubereats\.com', r'@postmates\.com',
        r'@instacart\.com', r'@caviar\.com', r'@seamless\.com',
        r'@uber\.com', r'@lyft\.com',
        r'@southwest\.com', r'@delta\.com', r'@united\.com', r'@aa\.com',
        r'@hilton\.com', r'@marriott\.com', r'@airbnb\.com', r'@vrbo\.com',
        r'@avis\.com', r'@hertz\.com', r'@enterprise\.com',
        r'@netflix\.com', r'@spotify\.com', r'@hulu\.com', r'@apple\.com',
        r'@paypal\.com', r'@venmo\.com', r'@square\.com', r'@stripe\.com',
        r'@shopify\.com', r'@etsy\.com', r'@ebay\.com',
        r'@chewy\.com', r'@wayfair\.com', r'@overstock\.com',
        r'@nordstrom\.com', r'@macys\.com', r'@kohls\.com',
        r'@starbucks\.com', r'@chick-?fil-?a\.com', r'@mcdonalds\.com',
        r'@jerseyikes\.com', r'@chipotle\.com', r'@panera\.com',
    ],
}

# INVOICES - Bills, payment requests, subscription charges
INVOICE_PATTERNS = {
    'subjects': [
        r'invoice', r'bill', r'statement', r'payment due', r'payment request',
        r'amount due', r'balance due', r'remittance', r'billing statement',
        r'subscription', r'renewal', r'charged', r'auto-?pay',
        r'monthly charge', r'annual charge', r'membership',
    ],
    'senders': [
        r'invoice@', r'invoices@', r'billing@', r'accounts@', r'ar@',
        r'@quickbooks', r'@intuit\.com', r'@freshbooks\.com', r'@xero\.com',
        r'@bill\.com', r'@expensify\.com',
        r'hive\.co', r'billing@',
    ],
}

# LEGAL - Contracts, agreements, DocuSign, legal documents
LEGAL_PATTERNS = {
    'subjects': [
        r'docusign', r'adobe sign', r'sign.*document', r'signature request',
        r'contract', r'agreement', r'nda', r'non-?disclosure',
        r'terms', r'legal', r'attorney', r'lawyer',
        r'complete with docusign', r'completed.*docusign',
        r'please sign', r'awaiting.*signature', r'action required.*sign',
        r'amendment', r'addendum', r'executed',
    ],
    'senders': [
        r'@docusign', r'dse.*@docusign', r'@adobesign', r'@hellosign',
        r'@pandadoc', r'@dropboxsign',
        r'attorney', r'lawyer', r'legal', r'law\.com', r'lawfirm',
    ],
}

# FINANCE - Banking, statements, tax, financial
FINANCE_PATTERNS = {
    'subjects': [
        r'bank statement', r'account statement', r'monthly statement',
        r'tax', r'w-?2', r'1099', r'1040', r'irs',
        r'direct deposit', r'wire transfer', r'ach',
        r'credit card statement', r'account summary',
        r'investment', r'portfolio', r'dividend',
        r'loan', r'mortgage', r'interest',
    ],
    'senders': [
        r'@chase\.com', r'@bankofamerica\.com', r'@wellsfargo\.com',
        r'@citi\.com', r'@capitalone\.com', r'@usbank\.com',
        r'@schwab\.com', r'@fidelity\.com', r'@vanguard\.com',
        r'@robinhood\.com', r'@coinbase\.com',
        r'@adp\.com', r'@paychex\.com', r'@gusto\.com',
        r'@plaid\.com', r'@teller\.io',
    ],
}

# NEWSLETTERS - Digests, updates, subscriptions
NEWSLETTER_PATTERNS = {
    'subjects': [
        r'newsletter', r'digest', r'weekly', r'daily', r'monthly',
        r'roundup', r'update', r'edition', r'issue #',
    ],
    'senders': [
        r'newsletter@', r'news@', r'digest@', r'updates@',
        r'@substack\.com', r'@medium\.com', r'@mailchimp',
        r'@campaign-?archive', r'list-?id',
    ],
}

# NOTIFICATIONS - Alerts, reminders, system notifications
NOTIFICATION_PATTERNS = {
    'subjects': [
        r'notification', r'alert', r'reminder', r'notice',
        r'security alert', r'new sign.?in', r'login',
        r'password', r'verify', r'confirm.*email',
    ],
    'senders': [
        r'notification@', r'notifications@', r'alerts@', r'notify@',
        r'noreply@', r'no-?reply@', r'donotreply@',
        r'@github\.com', r'@gitlab\.com', r'@bitbucket',
        r'@facebook', r'@twitter', r'@linkedin', r'@instagram',
        r'accounts\.google', r'security@',
    ],
}

# MARKETING/TRASH - Promotional garbage
TRASH_PATTERNS = {
    'subjects': [
        r'\d+%\s*off', r'sale', r'deal', r'promo', r'discount',
        r'limited time', r'act now', r'exclusive offer',
        r'flash sale', r'clearance', r'save \$', r'free shipping',
        r'last chance', r'ends (today|tonight|soon)',
        r'unsubscribe', r"you'?re missing out",
    ],
    'senders': [
        r'promo@', r'promotions@', r'marketing@', r'deals@',
        r'offers@', r'sale@', r'sales@', r'shop@',
        r'@em\.co', r'@mail\d+\.', r'@campaign',
        r'epochtimes', r'turnoutpac', r'actblue',
        r'glassesusa', r'eyebuydirect', r'topazlabs',
        r'seatgeek', r'fandango', r'hoteltonight',
    ],
}


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


def ensure_labels(service):
    """Create all required labels"""
    required = ['Receipts', 'Invoices', 'Legal', 'Finance', 'Newsletters', 'Notifications', 'Business']

    existing = service.users().labels().list(userId='me').execute().get('labels', [])
    existing_names = {l['name']: l['id'] for l in existing}

    label_ids = {}
    for name in required:
        if name in existing_names:
            label_ids[name] = existing_names[name]
        else:
            result = service.users().labels().create(
                userId='me',
                body={
                    'name': name,
                    'labelListVisibility': 'labelShow',
                    'messageListVisibility': 'show'
                }
            ).execute()
            label_ids[name] = result['id']
            print(f"    Created label: {name}")

    return label_ids


def matches_pattern(text, patterns):
    """Check if text matches any pattern"""
    if not text:
        return False
    text = text.lower()
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def categorize_email(sender, subject):
    """Categorize an email based on sender and subject"""
    sender = sender.lower() if sender else ''
    subject = subject.lower() if subject else ''

    # Check LEGAL first (highest priority - contracts, DocuSign)
    if matches_pattern(subject, LEGAL_PATTERNS['subjects']) or \
       matches_pattern(sender, LEGAL_PATTERNS['senders']):
        return 'Legal'

    # Check INVOICES (bills, payment requests)
    if matches_pattern(subject, INVOICE_PATTERNS['subjects']) or \
       matches_pattern(sender, INVOICE_PATTERNS['senders']):
        return 'Invoices'

    # Check RECEIPTS (purchases, orders)
    if matches_pattern(subject, RECEIPT_PATTERNS['subjects']) or \
       matches_pattern(sender, RECEIPT_PATTERNS['senders']):
        return 'Receipts'

    # Check FINANCE (banking, tax)
    if matches_pattern(subject, FINANCE_PATTERNS['subjects']) or \
       matches_pattern(sender, FINANCE_PATTERNS['senders']):
        return 'Finance'

    # Check TRASH (marketing garbage) - before newsletters
    if matches_pattern(subject, TRASH_PATTERNS['subjects']) or \
       matches_pattern(sender, TRASH_PATTERNS['senders']):
        return 'Trash'

    # Check NEWSLETTERS
    if matches_pattern(subject, NEWSLETTER_PATTERNS['subjects']) or \
       matches_pattern(sender, NEWSLETTER_PATTERNS['senders']):
        return 'Newsletters'

    # Check NOTIFICATIONS
    if matches_pattern(subject, NOTIFICATION_PATTERNS['subjects']) or \
       matches_pattern(sender, NOTIFICATION_PATTERNS['senders']):
        return 'Notifications'

    return None  # Don't categorize


def batch_modify(service, ids, add_labels=None, remove_labels=None):
    """Batch modify emails"""
    if not ids:
        return
    add_labels = add_labels or []
    remove_labels = remove_labels or []

    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        body = {'ids': batch}
        if add_labels:
            body['addLabelIds'] = add_labels
        if remove_labels:
            body['removeLabelIds'] = remove_labels
        service.users().messages().batchModify(userId='me', body=body).execute()


def deep_scan_account(service, label_ids, execute=False, max_emails=10000):
    """Deep scan all emails in account"""

    print(f"\n    Fetching emails (up to {max_emails})...")

    # Get all emails
    all_msgs = []
    page_token = None
    while len(all_msgs) < max_emails:
        result = service.users().messages().list(
            userId='me', maxResults=500, pageToken=page_token
        ).execute()
        all_msgs.extend(result.get('messages', []))
        page_token = result.get('nextPageToken')
        if not page_token:
            break

    print(f"    Analyzing {len(all_msgs)} emails...")

    # Categorize all emails
    categorized = defaultdict(list)
    uncategorized = []

    for i, msg in enumerate(all_msgs):
        if i % 500 == 0 and i > 0:
            print(f"      Processed {i}/{len(all_msgs)}...")

        try:
            detail = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From', 'Subject']
            ).execute()

            headers = {h['name']: h['value'] for h in detail.get('payload', {}).get('headers', [])}
            sender = headers.get('From', '')
            subject = headers.get('Subject', '')

            # Get current labels
            current_labels = detail.get('labelIds', [])

            # Skip if already in trash or spam
            if 'TRASH' in current_labels or 'SPAM' in current_labels:
                continue

            # Categorize
            category = categorize_email(sender, subject)

            if category:
                # Check if already has this label
                label_id = label_ids.get(category)
                if label_id and label_id not in current_labels:
                    categorized[category].append({
                        'id': msg['id'],
                        'from': sender[:50],
                        'subject': subject[:50],
                        'current_labels': current_labels
                    })

        except Exception as e:
            pass

    return categorized


def main():
    import sys
    execute = '--execute' in sys.argv

    if not execute:
        print("\n" + "="*70)
        print("  PREVIEW MODE - Add --execute to apply changes")
        print("="*70)

    print("\n" + "="*70)
    print("  DEEP EMAIL ORGANIZER")
    print("  Scrutinizing every email for proper organization")
    print("="*70)

    for account, token_file in ACCOUNTS.items():
        print(f"\n{'='*60}")
        print(f"  {account}")
        print(f"{'='*60}")

        try:
            service = get_service(token_file)
        except Exception as e:
            print(f"    Error: {e}")
            continue

        # Ensure labels exist
        print("\n    Ensuring labels exist...")
        label_ids = ensure_labels(service)

        # Deep scan
        categorized = deep_scan_account(service, label_ids, execute=execute)

        # Report
        print(f"\n    FOUND:")
        total = 0
        for category, emails in sorted(categorized.items(), key=lambda x: -len(x[1])):
            print(f"      {category}: {len(emails)} emails to label")
            total += len(emails)

            # Show samples
            for e in emails[:3]:
                print(f"        - {e['from'][:30]}: {e['subject'][:40]}")

        print(f"\n    TOTAL: {total} emails to organize")

        # Execute
        if execute:
            print(f"\n    APPLYING LABELS...")
            for category, emails in categorized.items():
                if category == 'Trash':
                    # Move to trash
                    batch_modify(service, [e['id'] for e in emails],
                                add_labels=['TRASH'], remove_labels=['INBOX'])
                    print(f"      Trashed {len(emails)} marketing emails")
                else:
                    label_id = label_ids.get(category)
                    if label_id:
                        batch_modify(service, [e['id'] for e in emails],
                                    add_labels=[label_id])
                        print(f"      Labeled {len(emails)} as {category}")

        # Final counts
        print(f"\n    FINAL LABEL COUNTS:")
        for name, lid in label_ids.items():
            try:
                d = service.users().labels().get(userId='me', id=lid).execute()
                print(f"      {name}: {d.get('messagesTotal', 0)}")
            except:
                pass

    print("\n" + "="*70)
    print("  COMPLETE")
    print("="*70)

    if not execute:
        print("\nRun with --execute to apply changes:")
        print("  python email_deep_organizer.py --execute")


if __name__ == '__main__':
    main()
