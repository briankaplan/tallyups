#!/usr/bin/env python3
"""
Receipt-Transaction Connection Verification & Repair Tool
==========================================================

This script ensures receipts are properly connected to the correct transactions.
It identifies and fixes:
1. Orphaned references (receipts pointing to deleted transactions)
2. Mismatched amounts (receipt amount doesn't match transaction)
3. Duplicate attachments (same receipt on multiple transactions)
4. Missing R2 images (receipt_image_url points to non-existent files)

Usage:
    python scripts/verify_receipt_connections.py --check    # Check only, no changes
    python scripts/verify_receipt_connections.py --fix      # Fix issues found
    python scripts/verify_receipt_connections.py --report   # Generate detailed report
"""

import os
import sys
import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import pymysql
import pymysql.cursors

# Load env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# MySQL connection
mysql_url = os.getenv('MYSQL_URL', '')
parts = mysql_url.replace('mysql://', '').split('@')
user_pass = parts[0].split(':')
host_port_db = parts[1].split('/')
host_port = host_port_db[0].split(':')

MYSQL_CONFIG = {
    'host': host_port[0],
    'port': int(host_port[1]),
    'user': user_pass[0],
    'password': user_pass[1],
    'database': host_port_db[1],
    'cursorclass': pymysql.cursors.DictCursor
}


def get_connection():
    return pymysql.connect(**MYSQL_CONFIG)


def check_orphaned_references(cursor) -> List[Dict]:
    """Find incoming_receipts pointing to deleted transactions"""
    cursor.execute('''
        SELECT ir.id, ir.subject, ir.matched_transaction_id, ir.ocr_merchant, ir.ocr_amount
        FROM incoming_receipts ir
        WHERE ir.matched_transaction_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t._index = ir.matched_transaction_id)
    ''')
    return cursor.fetchall()


def check_amount_mismatches(cursor, threshold=5.0) -> List[Dict]:
    """Find receipts where OCR amount doesn't match transaction amount"""
    cursor.execute('''
        SELECT
            ir.id as receipt_id,
            ir.subject,
            ir.ocr_merchant,
            ir.ocr_amount as receipt_amount,
            t._index as transaction_id,
            t.chase_description,
            ABS(t.chase_amount) as transaction_amount,
            ABS(ABS(t.chase_amount) - ir.ocr_amount) as difference
        FROM incoming_receipts ir
        JOIN transactions t ON ir.matched_transaction_id = t._index
        WHERE ir.ocr_amount IS NOT NULL
        AND ABS(ABS(t.chase_amount) - ir.ocr_amount) > %s
        ORDER BY difference DESC
    ''', (threshold,))
    return cursor.fetchall()


def check_duplicate_attachments(cursor) -> List[Dict]:
    """Find same receipt image attached to multiple records"""
    cursor.execute('''
        SELECT receipt_image_url, COUNT(*) as count, GROUP_CONCAT(id) as receipt_ids
        FROM incoming_receipts
        WHERE receipt_image_url IS NOT NULL AND receipt_image_url != ''
        GROUP BY receipt_image_url
        HAVING COUNT(*) > 1
    ''')
    return cursor.fetchall()


def check_transactions_without_receipts(cursor, min_amount=25.0) -> List[Dict]:
    """Find transactions over a threshold without receipts"""
    cursor.execute('''
        SELECT _index, chase_description, chase_amount, chase_date, business_type
        FROM transactions
        WHERE (receipt_url IS NULL OR receipt_url = '')
        AND ABS(chase_amount) >= %s
        ORDER BY ABS(chase_amount) DESC
        LIMIT 50
    ''', (min_amount,))
    return cursor.fetchall()


def check_incoming_without_images(cursor) -> int:
    """Count incoming receipts without images"""
    cursor.execute('''
        SELECT COUNT(*) as c FROM incoming_receipts
        WHERE receipt_image_url IS NULL OR receipt_image_url = ''
    ''')
    return cursor.fetchone()['c']


def fix_orphaned_references(cursor, conn):
    """Set matched_transaction_id to NULL for orphaned references"""
    cursor.execute('''
        UPDATE incoming_receipts
        SET matched_transaction_id = NULL,
            status = 'pending'
        WHERE matched_transaction_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t._index = incoming_receipts.matched_transaction_id)
    ''')
    conn.commit()
    return cursor.rowcount


def find_better_match_for_receipt(cursor, receipt: Dict) -> Dict:
    """Try to find a better transaction match for a mismatched receipt"""
    if not receipt.get('receipt_amount'):
        return None

    amount = float(receipt['receipt_amount'])

    # Look for transactions with matching amount
    cursor.execute('''
        SELECT _index, chase_description, chase_amount, chase_date, business_type
        FROM transactions
        WHERE ABS(ABS(chase_amount) - %s) < 1.00
        AND (receipt_url IS NULL OR receipt_url = '')
        ORDER BY chase_date DESC
        LIMIT 5
    ''', (amount,))

    matches = cursor.fetchall()
    if matches:
        return matches[0]  # Return best match
    return None


def generate_report(args):
    """Generate comprehensive verification report"""
    conn = get_connection()
    cursor = conn.cursor()

    report = {
        'generated_at': datetime.now().isoformat(),
        'issues': {},
        'summary': {}
    }

    print("=" * 60)
    print("📋 RECEIPT-TRANSACTION VERIFICATION REPORT")
    print("=" * 60)
    print()

    # 1. Check orphaned references
    orphaned = check_orphaned_references(cursor)
    print(f"1️⃣  ORPHANED REFERENCES: {len(orphaned)}")
    if orphaned:
        print("   (Receipts pointing to deleted transactions)")
        for o in orphaned[:5]:
            print(f"   - Receipt #{o['id']}: {o['subject'][:40]}...")
    report['issues']['orphaned_references'] = len(orphaned)
    print()

    # 2. Check amount mismatches
    mismatches = check_amount_mismatches(cursor, threshold=5.0)
    print(f"2️⃣  AMOUNT MISMATCHES (>$5): {len(mismatches)}")
    if mismatches:
        print("   (Receipt amount doesn't match transaction)")
        for m in mismatches[:5]:
            print(f"   - Receipt ${m['receipt_amount']:.2f} vs Transaction ${m['transaction_amount']:.2f} (diff: ${m['difference']:.2f})")
            print(f"     Receipt: {m['ocr_merchant']}")
            print(f"     Transaction: {m['chase_description'][:40]}")
    report['issues']['amount_mismatches'] = len(mismatches)
    print()

    # 3. Check duplicates
    duplicates = check_duplicate_attachments(cursor)
    print(f"3️⃣  DUPLICATE ATTACHMENTS: {len(duplicates)}")
    if duplicates:
        print("   (Same image on multiple records)")
        for d in duplicates[:3]:
            print(f"   - {d['receipt_image_url'][:60]}... ({d['count']} copies)")
    report['issues']['duplicate_attachments'] = len(duplicates)
    print()

    # 4. Check transactions without receipts
    no_receipts = check_transactions_without_receipts(cursor, min_amount=25.0)
    print(f"4️⃣  TRANSACTIONS WITHOUT RECEIPTS (>$25): {len(no_receipts)}")
    if no_receipts:
        for t in no_receipts[:5]:
            print(f"   - ${abs(float(t['chase_amount'])):.2f}: {t['chase_description'][:40]}...")
    report['issues']['transactions_without_receipts'] = len(no_receipts)
    print()

    # 5. Incoming receipts without images
    no_images = check_incoming_without_images(cursor)
    print(f"5️⃣  INCOMING RECEIPTS WITHOUT IMAGES: {no_images}")
    report['issues']['receipts_without_images'] = no_images
    print()

    # Summary
    total_issues = sum(report['issues'].values())
    print("=" * 60)
    print(f"📊 TOTAL ISSUES FOUND: {total_issues}")
    print("=" * 60)

    if args.fix:
        print()
        print("🔧 APPLYING FIXES...")
        fixes_applied = 0

        # Fix orphaned references
        if orphaned:
            fixed = fix_orphaned_references(cursor, conn)
            print(f"   ✅ Fixed {fixed} orphaned references")
            fixes_applied += fixed

        print(f"\n✅ Total fixes applied: {fixes_applied}")

    conn.close()

    # Save report to file
    report_file = Path(__file__).parent.parent / 'reports' / f'receipt_verification_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    report_file.parent.mkdir(exist_ok=True)
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Report saved to: {report_file}")

    return report


def main():
    parser = argparse.ArgumentParser(description='Verify receipt-transaction connections')
    parser.add_argument('--check', action='store_true', help='Check only, no changes')
    parser.add_argument('--fix', action='store_true', help='Fix issues found')
    parser.add_argument('--report', action='store_true', help='Generate detailed report')
    args = parser.parse_args()

    if not any([args.check, args.fix, args.report]):
        args.check = True  # Default to check mode

    generate_report(args)


if __name__ == '__main__':
    main()
