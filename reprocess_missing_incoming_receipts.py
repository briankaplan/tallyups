#!/usr/bin/env python3
"""
Re-process incoming receipts that were accepted but never got their files downloaded.
This script finds transactions from incoming_receipts that have no receipt file,
then re-downloads the attachments from Gmail and uploads to R2.
"""

import os
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from incoming_receipts_service import (
    process_receipt_files,
    load_gmail_service,
    RECEIPTS_DIR
)

# Database connection
USE_MYSQL = os.getenv('MYSQL_HOST') or os.getenv('MYSQLHOST')

def get_db_connection():
    """Get database connection - MySQL or SQLite"""
    if USE_MYSQL:
        import pymysql
        conn = pymysql.connect(
            host=os.getenv('MYSQL_HOST') or os.getenv('MYSQLHOST'),
            port=int(os.getenv('MYSQL_PORT') or os.getenv('MYSQLPORT') or 3306),
            user=os.getenv('MYSQL_USER') or os.getenv('MYSQLUSER'),
            password=os.getenv('MYSQL_PASSWORD') or os.getenv('MYSQLPASSWORD'),
            database=os.getenv('MYSQL_DATABASE') or os.getenv('MYSQLDATABASE'),
            cursorclass=pymysql.cursors.DictCursor
        )
        return conn, 'mysql'
    else:
        import sqlite3
        conn = sqlite3.connect('receipts.db')
        conn.row_factory = sqlite3.Row
        return conn, 'sqlite'

def db_execute(conn, db_type, query, params=None):
    """Execute query with proper placeholder syntax"""
    cursor = conn.cursor()
    if db_type == 'mysql':
        query = query.replace('?', '%s')
    cursor.execute(query, params or ())
    return cursor

def reprocess_missing_receipts():
    """Find and re-process incoming receipts that have no files"""

    conn, db_type = get_db_connection()
    print(f"📊 Connected to {db_type.upper()} database")

    # Find accepted incoming receipts that have transactions with no receipt files
    query = '''
        SELECT
            ir.id as incoming_id,
            ir.email_id,
            ir.gmail_account,
            ir.subject,
            ir.merchant,
            ir.amount,
            ir.attachments,
            ir.accepted_as_transaction_id,
            t._index as txn_index,
            t.receipt_file,
            t.receipt_url
        FROM incoming_receipts ir
        LEFT JOIN transactions t ON t._index = ir.accepted_as_transaction_id
        WHERE ir.status = 'accepted'
        AND ir.email_id IS NOT NULL
        AND ir.gmail_account IS NOT NULL
        AND (t.receipt_file IS NULL OR t.receipt_file = '')
        AND (t.receipt_url IS NULL OR t.receipt_url = '')
    '''

    cursor = db_execute(conn, db_type, query)
    rows = cursor.fetchall()

    if not rows:
        print("✅ No missing receipts found - all accepted incoming receipts have files!")
        conn.close()
        return

    print(f"\n🔍 Found {len(rows)} accepted receipts with missing files:\n")

    for row in rows:
        row = dict(row)
        print(f"  • ID {row['incoming_id']}: {row['merchant']} ${row['amount']} - Txn #{row['txn_index']}")

    print(f"\n🔄 Re-processing {len(rows)} receipts...\n")

    success_count = 0
    fail_count = 0

    for row in rows:
        row = dict(row)
        incoming_id = row['incoming_id']
        email_id = row['email_id']
        gmail_account = row['gmail_account']
        merchant = row['merchant'] or 'Unknown'
        amount = row['amount'] or 0
        txn_index = row['txn_index']
        attachments_str = row['attachments'] or '[]'

        print(f"📧 Processing: {merchant} ${amount} (Incoming #{incoming_id}, Txn #{txn_index})")

        try:
            # Parse attachments
            attachments = json.loads(attachments_str)

            if not attachments:
                print(f"   ⚠️  No attachments found in record")
                fail_count += 1
                continue

            # Load Gmail service
            service = load_gmail_service(gmail_account)
            if not service:
                print(f"   ❌ Could not load Gmail service for {gmail_account}")
                fail_count += 1
                continue

            # Get HTML body for screenshot fallback
            html_body = None
            try:
                msg_data = service.users().messages().get(
                    userId='me',
                    id=email_id,
                    format='full'
                ).execute()

                # Extract HTML body
                def get_html_body(payload):
                    if 'parts' in payload:
                        for part in payload['parts']:
                            if part.get('mimeType') == 'text/html':
                                import base64
                                data = part.get('body', {}).get('data', '')
                                if data:
                                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    return ''

                html_body = get_html_body(msg_data.get('payload', {}))
            except Exception as e:
                print(f"   ⚠️  Could not get email body: {e}")

            # Process receipt files
            print(f"   📎 Downloading {len(attachments)} attachment(s)...")
            receipt_files = process_receipt_files(service, email_id, attachments, html_body)

            if not receipt_files:
                print(f"   ❌ No files downloaded")
                fail_count += 1
                continue

            print(f"   ✅ Downloaded {len(receipt_files)} file(s)")

            # Separate R2 URLs from local paths
            r2_urls = [f for f in receipt_files if f.startswith('http')]
            local_files = [f for f in receipt_files if not f.startswith('http')]

            receipt_file_str = ', '.join([os.path.basename(f) for f in local_files]) if local_files else ''
            receipt_url_str = r2_urls[0] if r2_urls else ''

            # Update transaction with receipt files
            if txn_index:
                if db_type == 'mysql':
                    update_query = '''
                        UPDATE transactions
                        SET receipt_file = COALESCE(NULLIF(%s, ''), receipt_file),
                            receipt_url = COALESCE(NULLIF(%s, ''), receipt_url)
                        WHERE _index = %s
                    '''
                else:
                    update_query = '''
                        UPDATE transactions
                        SET receipt_file = COALESCE(NULLIF(?, ''), receipt_file),
                            receipt_url = COALESCE(NULLIF(?, ''), receipt_url)
                        WHERE _index = ?
                    '''

                cursor = conn.cursor()
                cursor.execute(update_query, (receipt_file_str, receipt_url_str, txn_index))
                conn.commit()
                print(f"   💾 Updated transaction #{txn_index}")

            # Update incoming_receipts with downloaded files
            if db_type == 'mysql':
                update_ir = 'UPDATE incoming_receipts SET receipt_files = %s WHERE id = %s'
            else:
                update_ir = 'UPDATE incoming_receipts SET receipt_files = ? WHERE id = ?'

            cursor = conn.cursor()
            cursor.execute(update_ir, (json.dumps(receipt_files), incoming_id))
            conn.commit()

            success_count += 1
            print(f"   ✅ Complete!\n")

        except Exception as e:
            print(f"   ❌ Error: {e}\n")
            fail_count += 1
            continue

    conn.close()

    print(f"\n{'='*50}")
    print(f"📊 RESULTS:")
    print(f"   ✅ Success: {success_count}")
    print(f"   ❌ Failed:  {fail_count}")
    print(f"{'='*50}")

if __name__ == '__main__':
    # Ensure receipts directory exists
    os.makedirs(RECEIPTS_DIR, exist_ok=True)

    reprocess_missing_receipts()
