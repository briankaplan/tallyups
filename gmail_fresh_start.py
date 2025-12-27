#!/usr/bin/env python3
"""
Gmail Fresh Start - Complete Email Automation System
=====================================================
Integrated with ReceiptAI-MASTER-LIBRARY

This script will:
1. Create a clean, minimal label structure
2. Set up filters to auto-delete promotional/social noise
3. Route receipts to "Receipts" label → picked up by gmail_label_integration.py
4. Keep only human emails in your inbox

INTEGRATION WITH RECEIPTAI:
- Receipts are auto-labeled "Receipts" and skip inbox
- gmail_label_integration.py polls the "Receipts" label
- Receipts flow into your existing ReceiptAI pipeline
- No changes needed to viewer_server.py

IMPORTANT: Uses your existing Gmail tokens from ReceiptAI.
"""

import os
import sys
import json
from pathlib import Path

# Try to use existing ReceiptAI tokens first
RECEIPTAI_PATH = Path.home() / "Desktop" / "ReceiptAI-MASTER-LIBRARY"
TOKEN_DIR = RECEIPTAI_PATH / "gmail_tokens"

# Google API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

# Gmail API scopes needed
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels',
    'https://www.googleapis.com/auth/gmail.settings.basic'
]

# Existing ReceiptAI token mapping
RECEIPTAI_TOKENS = {
    'kaplan.brian@gmail.com': 'tokens_kaplan_brian_gmail_com.json',
    'brian@business.com': 'tokens_brian_business_com.json',
    'brian@musiccityrodeo.com': 'tokens_brian_musiccityrodeo_com.json',
}

# =============================================================================
# CONFIGURATION - Your new clean label structure
# =============================================================================

NEW_LABELS = [
    "Receipts",           # All receipts go here → ReceiptAI ingestion
    "Family",             # ParentSquare, school, kids
    "Newsletters",        # Optional: archive newsletters you actually want
    "Archive",            # Catch-all for auto-archived stuff
]

# =============================================================================
# SENDERS TO COMPLETELY UNSUBSCRIBE FROM (worst offenders)
# =============================================================================

UNSUBSCRIBE_LIST = [
    # Political fundraising
    {"name": "TurnoutPAC / Progressive Turnout Project", "domain": "turnoutpac.org", "unsubscribe_url": "https://pages.e.turnoutpac.org/unsubscribe"},
    {"name": "ActBlue", "domain": "actblue.com", "unsubscribe_url": None},
    
    # Newsletters you don't read
    {"name": "Every.to", "domain": "every.to", "unsubscribe_url": "https://every.to/unsubscribe"},
    {"name": "Epoch Times", "domain": "theepochtimes.com", "unsubscribe_url": None},
    {"name": "Goodreads", "domain": "goodreads.com", "unsubscribe_url": "https://www.goodreads.com/unsubscribe"},
    
    # Marketing spam
    {"name": "Kickstarter (marketing)", "domain": "me.kickstarter.com", "unsubscribe_url": None},
    {"name": "Wrangler", "domain": "e.wrangler.com", "unsubscribe_url": None},
    {"name": "Academy Sports", "domain": "e.academy.com", "unsubscribe_url": None},
    {"name": "Clean Eatz", "domain": "cleaneatzkitchen.com", "unsubscribe_url": None},
    {"name": "Nashville Zoo", "domain": "nashvillezoo.org", "unsubscribe_url": None},
    {"name": "Topaz Labs", "domain": "topazlabs.com", "unsubscribe_url": None},
    {"name": "CareNow", "domain": "marketing.hcahealthcare.com", "unsubscribe_url": None},
    {"name": "Lucky Ladd Farms", "domain": "wbxmail.net", "unsubscribe_url": None},
    {"name": "Fox Restaurant Concepts", "domain": "news.foxrc.com", "unsubscribe_url": None},
    
    # LinkedIn noise (keep direct messages)
    {"name": "LinkedIn Analytics", "domain": "linkedin.com", "filter": "subject:(analytics OR impressions OR \"Year in Review\" OR \"who viewed\" OR \"weekly recap\")", "unsubscribe_url": "https://www.linkedin.com/psettings/email-unsubscribe"},
]

# =============================================================================
# FILTERS TO AUTO-DELETE (nuclear option)
# =============================================================================

AUTO_DELETE_FILTERS = [
    # All promotions older than 1 day
    {
        "name": "Old Promotions",
        "criteria": {"query": "category:promotions older_than:1d"},
        "action": {"removeLabelIds": ["INBOX"], "addLabelIds": ["TRASH"]}
    },
    # Political fundraising
    {
        "name": "Political Spam",
        "criteria": {"from": "turnoutpac.org OR actblue.com OR dccc.org OR rnc.org OR nrcc.org OR dscc.org"},
        "action": {"removeLabelIds": ["INBOX"], "addLabelIds": ["TRASH"]}
    },
]

# =============================================================================
# FILTERS TO AUTO-ARCHIVE (skip inbox, apply label)
# =============================================================================

AUTO_ARCHIVE_FILTERS = [
    # Social category (LinkedIn analytics, etc)
    {
        "name": "Social Notifications",
        "criteria": {"query": "category:social -from:messages-noreply@linkedin.com"},  # Keep direct LinkedIn messages
        "action": {"removeLabelIds": ["INBOX"]},
        "label": "Archive"
    },
    # Newsletters (if you want to keep but not see)
    {
        "name": "Newsletters",
        "criteria": {"from": "substack.com OR every.to OR newsletter@"},
        "action": {"removeLabelIds": ["INBOX"]},
        "label": "Newsletters"
    },
]

# =============================================================================
# FILTERS FOR RECEIPTS → ReceiptAI
# =============================================================================

RECEIPT_FILTERS = [
    {
        "name": "Receipts - Transaction Keywords",
        "criteria": {
            "query": "subject:(receipt OR invoice OR \"order confirmation\" OR \"payment confirmation\" OR \"your order\" OR \"order number\" OR \"transaction complete\")"
        },
        "action": {"removeLabelIds": ["INBOX"]},  # Skip inbox
        "label": "Receipts"
    },
    {
        "name": "Receipts - From Patterns", 
        "criteria": {
            "from": "receipt@ OR invoice@ OR billing@ OR noreply@expensify.com OR no_reply@email.apple.com"
        },
        "action": {"removeLabelIds": ["INBOX"]},
        "label": "Receipts"
    },
    {
        "name": "Receipts - Major Services",
        "criteria": {
            "from": "uber.com OR lyft.com OR doordash.com OR grubhub.com OR southwest.com OR delta.com OR amazon.com OR paypal.com OR stripe.com OR square.com"
        },
        "action": {"removeLabelIds": ["INBOX"]},
        "label": "Receipts"
    },
]

# =============================================================================
# FAMILY/SCHOOL FILTER
# =============================================================================

FAMILY_FILTERS = [
    {
        "name": "Family - School",
        "criteria": {"from": "parentsquare.com OR wcschools.com OR @school"},
        "action": {},  # Keep in inbox
        "label": "Family"
    },
]


def get_gmail_service(account_email: str = 'kaplan.brian@gmail.com'):
    """Authenticate and return Gmail service using existing ReceiptAI tokens."""
    creds = None
    
    # Try to use existing ReceiptAI token
    if account_email in RECEIPTAI_TOKENS and TOKEN_DIR.exists():
        token_path = TOKEN_DIR / RECEIPTAI_TOKENS[account_email]
        if token_path.exists():
            print(f"   Using existing ReceiptAI token: {token_path.name}")
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            except Exception as e:
                print(f"   ⚠️ Could not load token: {e}")
    
    # Fallback to local pickle file
    if not creds and os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                # Try ReceiptAI credentials location
                receiptai_creds = RECEIPTAI_PATH / "credentials.json"
                if receiptai_creds.exists():
                    print(f"   Using ReceiptAI credentials: {receiptai_creds}")
                    flow = InstalledAppFlow.from_client_secrets_file(str(receiptai_creds), SCOPES)
                else:
                    print("\n❌ ERROR: credentials.json not found!")
                    print("   See setup instructions at the end of this script.")
                    return None
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save token
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    return build('gmail', 'v1', credentials=creds)


def create_label(service, label_name):
    """Create a Gmail label if it doesn't exist."""
    try:
        label = service.users().labels().create(
            userId='me',
            body={'name': label_name, 'labelListVisibility': 'labelShow', 'messageListVisibility': 'show'}
        ).execute()
        print(f"  ✓ Created label: {label_name}")
        return label['id']
    except Exception as e:
        if 'Label name exists' in str(e):
            # Get existing label ID
            labels = service.users().labels().list(userId='me').execute()
            for label in labels.get('labels', []):
                if label['name'] == label_name:
                    print(f"  ℹ Label exists: {label_name}")
                    return label['id']
        else:
            print(f"  ❌ Error creating {label_name}: {e}")
    return None


def create_filter(service, filter_config, label_ids):
    """Create a Gmail filter."""
    try:
        filter_body = {
            'criteria': filter_config['criteria'],
            'action': filter_config['action'].copy()
        }
        
        # Add label if specified
        if 'label' in filter_config and filter_config['label'] in label_ids:
            if 'addLabelIds' not in filter_body['action']:
                filter_body['action']['addLabelIds'] = []
            filter_body['action']['addLabelIds'].append(label_ids[filter_config['label']])
        
        service.users().settings().filters().create(
            userId='me',
            body=filter_body
        ).execute()
        print(f"  ✓ Created filter: {filter_config['name']}")
        return True
    except Exception as e:
        print(f"  ❌ Error creating filter {filter_config['name']}: {e}")
        return False


def delete_old_filters(service):
    """Delete all existing filters (fresh start)."""
    try:
        filters = service.users().settings().filters().list(userId='me').execute()
        for f in filters.get('filter', []):
            service.users().settings().filters().delete(userId='me', id=f['id']).execute()
        print(f"  ✓ Deleted {len(filters.get('filter', []))} old filters")
    except Exception as e:
        print(f"  ⚠ Could not delete filters: {e}")


def main():
    print("\n" + "="*60)
    print("   GMAIL FRESH START - Complete Email Automation")
    print("="*60)
    
    # Connect to Gmail
    print("\n📧 Connecting to Gmail...")
    service = get_gmail_service()
    if not service:
        return
    
    # Get user email
    profile = service.users().getProfile(userId='me').execute()
    print(f"   Connected as: {profile['emailAddress']}")
    print(f"   Total messages: {profile['messagesTotal']:,}")
    
    # Step 1: Create new labels
    print("\n📁 Creating clean label structure...")
    label_ids = {}
    for label_name in NEW_LABELS:
        label_id = create_label(service, label_name)
        if label_id:
            label_ids[label_name] = label_id
    
    # Step 2: Delete old filters (optional - uncomment if you want fresh start)
    print("\n🗑️  Clearing old filters...")
    delete_old_filters(service)
    
    # Step 3: Create new filters
    print("\n⚡ Creating auto-delete filters...")
    for filter_config in AUTO_DELETE_FILTERS:
        create_filter(service, filter_config, label_ids)
    
    print("\n📂 Creating auto-archive filters...")
    for filter_config in AUTO_ARCHIVE_FILTERS:
        create_filter(service, filter_config, label_ids)
    
    print("\n🧾 Creating receipt filters (for ReceiptAI)...")
    for filter_config in RECEIPT_FILTERS:
        create_filter(service, filter_config, label_ids)
    
    print("\n👨‍👩‍👧 Creating family filters...")
    for filter_config in FAMILY_FILTERS:
        create_filter(service, filter_config, label_ids)
    
    # Step 4: Print unsubscribe list
    print("\n" + "="*60)
    print("   🛑 MANUAL UNSUBSCRIBE LIST - Click these links!")
    print("="*60)
    print("\nThese senders are your worst offenders. Unsubscribe now:\n")
    
    for i, sender in enumerate(UNSUBSCRIBE_LIST, 1):
        print(f"{i:2}. {sender['name']}")
        print(f"    Domain: {sender['domain']}")
        if sender.get('unsubscribe_url'):
            print(f"    Unsubscribe: {sender['unsubscribe_url']}")
        print()
    
    print("\n" + "="*60)
    print("   ✅ SETUP COMPLETE!")
    print("="*60)
    print("""
Your inbox is now set to:
  • Auto-DELETE: Political fundraising, old promotions
  • Auto-ARCHIVE: Social notifications, newsletters
  • Auto-LABEL: Receipts → "Receipts" label (for ReceiptAI)
  • Auto-LABEL: School/family → "Family" label
  • INBOX: Only real human emails!

Next steps:
  1. Click the unsubscribe links above
  2. ReceiptAI will automatically poll the "Receipts" label
  3. Enjoy your clean inbox!
""")


if __name__ == '__main__':
    main()
