#!/usr/bin/env python3
"""
System Audit Script
==================
Comprehensive audit of ReceiptAI/Tallyups system:
- Database tables and counts
- OCR coverage
- Receipt matching status
- R2 storage verification
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pymysql
import pymysql.cursors
import json
from datetime import datetime

# Load env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# MySQL connection with retry
def get_mysql_connection(retries=3):
    mysql_url = os.getenv('MYSQL_URL', '')
    if not mysql_url:
        raise ValueError("MYSQL_URL not set")

    parts = mysql_url.replace('mysql://', '').split('@')
    user_pass = parts[0].split(':')
    host_port_db = parts[1].split('/')
    host_port = host_port_db[0].split(':')

    for attempt in range(retries):
        try:
            conn = pymysql.connect(
                host=host_port[0],
                port=int(host_port[1]),
                user=user_pass[0],
                password=user_pass[1],
                database=host_port_db[1],
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=30,
                read_timeout=60
            )
            return conn
        except Exception as e:
            print(f"  Connection attempt {attempt+1} failed: {e}")
            if attempt == retries - 1:
                raise
            import time
            time.sleep(2)

def audit_transactions(cursor):
    """Audit transactions table"""
    print("\n" + "="*60)
    print("📊 TRANSACTIONS TABLE")
    print("="*60)

    cursor.execute("SELECT COUNT(*) as total FROM transactions")
    total = cursor.fetchone()['total']
    print(f"Total transactions: {total}")

    cursor.execute("SELECT COUNT(*) as c FROM transactions WHERE receipt_url IS NOT NULL AND receipt_url != ''")
    with_receipts = cursor.fetchone()['c']
    print(f"With receipt_url: {with_receipts} ({100*with_receipts//total if total else 0}%)")

    cursor.execute("SELECT COUNT(*) as c FROM transactions WHERE r2_url IS NOT NULL AND r2_url != ''")
    with_r2 = cursor.fetchone()['c']
    print(f"With r2_url: {with_r2}")

    cursor.execute("SELECT COUNT(*) as c FROM transactions WHERE ocr_merchant IS NOT NULL")
    with_ocr = cursor.fetchone()['c']
    print(f"With OCR data: {with_ocr}")

    cursor.execute("SELECT COUNT(*) as c FROM transactions WHERE ai_note IS NOT NULL AND ai_note != ''")
    with_notes = cursor.fetchone()['c']
    print(f"With AI notes: {with_notes}")

    # Business type breakdown
    cursor.execute("""
        SELECT business_type, COUNT(*) as c
        FROM transactions
        WHERE business_type IS NOT NULL AND business_type != ''
        GROUP BY business_type
    """)
    print("\nBusiness types:")
    for row in cursor.fetchall():
        print(f"  - {row['business_type']}: {row['c']}")

    return {'total': total, 'with_receipts': with_receipts, 'with_ocr': with_ocr}

def audit_incoming_receipts(cursor):
    """Audit incoming_receipts table"""
    print("\n" + "="*60)
    print("📬 INCOMING_RECEIPTS TABLE")
    print("="*60)

    cursor.execute("SELECT COUNT(*) as total FROM incoming_receipts")
    total = cursor.fetchone()['total']
    print(f"Total incoming receipts: {total}")

    cursor.execute("SELECT COUNT(*) as c FROM incoming_receipts WHERE receipt_image_url IS NOT NULL")
    with_images = cursor.fetchone()['c']
    print(f"With images: {with_images}")

    cursor.execute("SELECT COUNT(*) as c FROM incoming_receipts WHERE ocr_merchant IS NOT NULL")
    with_ocr = cursor.fetchone()['c']
    print(f"With OCR data: {with_ocr} ({100*with_ocr//with_images if with_images else 0}% of images)")

    cursor.execute("SELECT COUNT(*) as c FROM incoming_receipts WHERE matched_transaction_id IS NOT NULL")
    matched = cursor.fetchone()['c']
    print(f"Matched to transactions: {matched}")

    cursor.execute("SELECT COUNT(*) as c FROM incoming_receipts WHERE status = 'pending'")
    pending = cursor.fetchone()['c']
    print(f"Pending review: {pending}")

    # Gmail account breakdown
    cursor.execute("""
        SELECT gmail_account, COUNT(*) as c
        FROM incoming_receipts
        WHERE gmail_account IS NOT NULL
        GROUP BY gmail_account
    """)
    print("\nBy Gmail account:")
    for row in cursor.fetchall():
        print(f"  - {row['gmail_account']}: {row['c']}")

    return {'total': total, 'with_images': with_images, 'with_ocr': with_ocr, 'matched': matched}

def audit_ocr_quality(cursor):
    """Check OCR data quality"""
    print("\n" + "="*60)
    print("🔍 OCR DATA QUALITY")
    print("="*60)

    # Sample OCR extractions with line items
    cursor.execute("""
        SELECT ocr_merchant, ocr_amount, ocr_line_items, subject
        FROM incoming_receipts
        WHERE ocr_line_items IS NOT NULL
        AND JSON_LENGTH(ocr_line_items) > 0
        ORDER BY ocr_extracted_at DESC
        LIMIT 5
    """)
    samples = cursor.fetchall()

    print(f"\nSample OCR extractions with line items ({len(samples)} samples):")
    for i, row in enumerate(samples, 1):
        print(f"\n  [{i}] {row['ocr_merchant'] or 'Unknown'}")
        print(f"      Amount: ${row['ocr_amount'] or 0:.2f}")
        if row['ocr_line_items']:
            items = row['ocr_line_items'] if isinstance(row['ocr_line_items'], list) else json.loads(row['ocr_line_items'])
            if items:
                item_names = [str(i.get('name', i.get('description', '')))[:40] for i in items[:3]]
                print(f"      Items: {', '.join(item_names)}")

def audit_receipt_matching(cursor):
    """Audit receipt matching accuracy"""
    print("\n" + "="*60)
    print("🔗 RECEIPT MATCHING STATUS")
    print("="*60)

    # Check for mismatches (OCR amount vs transaction amount)
    cursor.execute("""
        SELECT
            t._index, t.chase_description, t.chase_amount,
            ir.ocr_merchant, ir.ocr_amount, ir.subject
        FROM transactions t
        JOIN incoming_receipts ir ON ir.matched_transaction_id = t._index
        WHERE ir.ocr_amount IS NOT NULL
        AND ABS(ABS(t.chase_amount) - ir.ocr_amount) > 1.00
        LIMIT 10
    """)
    mismatches = cursor.fetchall()

    print(f"\nPotential amount mismatches (>$1 difference): {len(mismatches)}")
    for m in mismatches[:5]:
        print(f"  - Tx: {m['chase_description'][:30]}... ${abs(float(m['chase_amount'])):.2f}")
        print(f"    Receipt: {m['ocr_merchant'] or 'Unknown'} ${float(m['ocr_amount']):.2f}")

def audit_r2_urls(cursor):
    """Check R2 URL patterns"""
    print("\n" + "="*60)
    print("☁️ R2 STORAGE AUDIT")
    print("="*60)

    # Check URL patterns
    cursor.execute("""
        SELECT
            CASE
                WHEN receipt_image_url LIKE '%bkreceipts%' THEN 'bkreceipts'
                WHEN receipt_image_url LIKE '%tallyups%' THEN 'tallyups-receipts'
                ELSE 'other'
            END as bucket,
            COUNT(*) as c
        FROM incoming_receipts
        WHERE receipt_image_url IS NOT NULL
        GROUP BY bucket
    """)
    print("\nIncoming receipts by bucket:")
    for row in cursor.fetchall():
        print(f"  - {row['bucket']}: {row['c']}")

    cursor.execute("""
        SELECT
            CASE
                WHEN receipt_url LIKE '%bkreceipts%' THEN 'bkreceipts'
                WHEN receipt_url LIKE '%tallyups%' THEN 'tallyups-receipts'
                WHEN receipt_url LIKE 'http%' THEN 'external'
                ELSE 'local/other'
            END as bucket,
            COUNT(*) as c
        FROM transactions
        WHERE receipt_url IS NOT NULL AND receipt_url != ''
        GROUP BY bucket
    """)
    print("\nTransactions by receipt source:")
    for row in cursor.fetchall():
        print(f"  - {row['bucket']}: {row['c']}")

def main():
    print("="*60)
    print("🔎 TALLYUPS SYSTEM AUDIT")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    try:
        print("\nConnecting to database...")
        conn = get_mysql_connection()
        cursor = conn.cursor()
        print("✅ Connected!")

        tx_stats = audit_transactions(cursor)
        ir_stats = audit_incoming_receipts(cursor)
        audit_ocr_quality(cursor)
        audit_receipt_matching(cursor)
        audit_r2_urls(cursor)

        # Summary
        print("\n" + "="*60)
        print("📋 SUMMARY")
        print("="*60)
        print(f"Transactions: {tx_stats['total']} total, {tx_stats['with_receipts']} with receipts")
        print(f"Incoming receipts: {ir_stats['total']} total, {ir_stats['with_ocr']} with OCR")
        print(f"Match rate: {ir_stats['matched']}/{ir_stats['total']} ({100*ir_stats['matched']//ir_stats['total'] if ir_stats['total'] else 0}%)")

        conn.close()
        print("\n✅ Audit complete!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
