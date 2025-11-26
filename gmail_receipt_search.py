#!/usr/bin/env python3
"""
Search Gmail accounts for missing receipts
"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DB_PATH = "receipts.db"
GMAIL_TOKENS_DIR = "../Task/receipt-system/gmail_tokens"

# Gmail accounts to search
GMAIL_ACCOUNTS = [
    ("kaplan.brian@gmail.com", "tokens_kaplan_brian_gmail_com.json"),
    ("brian@downhome.com", "tokens_brian_downhome_com.json"),
    ("brian@musiccityrodeo.com", "tokens_brian_musiccityrodeo_com.json"),
]

def load_gmail_service(token_file):
    """Load Gmail service from token file"""
    token_path = os.path.join(GMAIL_TOKENS_DIR, token_file)

    if not os.path.exists(token_path):
        print(f"   ⚠️ Token file not found: {token_path}")
        return None

    try:
        with open(token_path, 'r') as f:
            token_data = json.load(f)

        creds = Credentials.from_authorized_user_info(token_data)
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        print(f"   ⚠️ Error loading service: {e}")
        return None

def search_gmail_for_receipt(service, merchant, amount, date, account_email):
    """Search Gmail for a specific receipt"""

    # Parse transaction date
    tx_date = datetime.strptime(date, '%Y-%m-%d')
    after_date = (tx_date - timedelta(days=3)).strftime('%Y/%m/%d')
    before_date = (tx_date + timedelta(days=3)).strftime('%Y/%m/%d')

    # Clean merchant name for search
    merchant_clean = merchant.replace('*', '').replace('TST', '').strip()
    merchant_words = ' '.join(merchant_clean.split()[:2])  # First 2 words

    # Build search query
    query = f'after:{after_date} before:{before_date} ({merchant_words} OR receipt OR confirmation) has:attachment'

    try:
        # Search Gmail
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=3
        ).execute()

        messages = results.get('messages', [])

        if messages:
            print(f"      📧 {account_email}: Found {len(messages)} email(s)")

            for msg in messages:
                # Get message details
                msg_data = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata',
                    metadataHeaders=['Subject', 'From', 'Date']
                ).execute()

                # Extract headers
                headers = msg_data.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No subject')
                from_email = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')

                print(f"         - {subject[:60]}")
                print(f"           From: {from_email[:50]}")

            return len(messages)

    except Exception as e:
        if "invalid_grant" not in str(e).lower():
            print(f"      ⚠️ {account_email}: Search error - {e}")

    return 0

def search_all_accounts():
    """Search all Gmail accounts for missing receipts"""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get top 20 missing receipts
    cur.execute("""
        SELECT _index, chase_description, chase_amount, chase_date
        FROM transactions
        WHERE (receipt_file IS NULL OR receipt_file = '')
        AND chase_amount > 0
        ORDER BY chase_amount DESC
        LIMIT 20
    """)

    missing = cur.fetchall()

    print(f"\n🔍 SEARCHING GMAIL FOR {len(missing)} HIGH-VALUE MISSING RECEIPTS")
    print(f"=" * 80)

    # Load Gmail services
    services = {}
    for email, token_file in GMAIL_ACCOUNTS:
        print(f"\n📧 Loading {email}...")
        service = load_gmail_service(token_file)
        if service:
            services[email] = service
            print(f"   ✅ Connected")
        else:
            print(f"   ❌ Failed to connect")

    if not services:
        print("\n❌ No Gmail accounts available. Please re-authenticate.")
        return

    print(f"\n{'=' * 80}")
    print(f"Searching {len(services)} Gmail account(s)...\n")

    total_found = 0

    for i, row in enumerate(missing, 1):
        idx = row['_index']
        merchant = row['chase_description']
        amount = row['chase_amount']
        date = row['chase_date']

        print(f"\n[{i}/{len(missing)}] [{idx}] {merchant[:50]} | ${amount:.2f} | {date}")

        found_count = 0
        for email, service in services.items():
            count = search_gmail_for_receipt(service, merchant, amount, date, email)
            found_count += count

        if found_count > 0:
            total_found += 1
        else:
            print(f"      ❌ No emails found in any account")

    print(f"\n{'=' * 80}")
    print(f"✅ SEARCH COMPLETE")
    print(f"Found potential receipts for {total_found}/{len(missing)} transactions")
    print(f"\nNext steps:")
    print(f"1. Review the emails listed above")
    print(f"2. Download attachments from matching emails")
    print(f"3. Save to receipts/ folder with proper naming: merchant_YYYY-MM-DD_amount.ext")
    print(f"4. Run ultra_conservative_matcher.py again to link them")

    conn.close()

if __name__ == "__main__":
    search_all_accounts()
