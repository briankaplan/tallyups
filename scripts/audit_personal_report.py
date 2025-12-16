#!/usr/bin/env python3
"""
Personal Report Audit & Fix Script
===================================
1. Audit report math (charges vs refunds vs net)
2. Find duplicate transactions
3. Verify transactions came from original CSV
4. Scan Apple receipts for app names
5. Fix Kit business type (Personal -> Down Home)
6. Fix Apple receipt mismatch
"""

import os
import sys
import json
import pymysql
from datetime import datetime
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_db_connection():
    """Connect to MySQL database"""
    # Try to load from .env
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, val = line.split('=', 1)
                    env[key] = val.strip('"').strip("'")

    return pymysql.connect(
        host=env.get('MYSQL_HOST', os.environ.get('MYSQL_HOST', 'autorack.proxy.rlwy.net')),
        port=int(env.get('MYSQL_PORT', os.environ.get('MYSQL_PORT', 24648))),
        user=env.get('MYSQL_USER', os.environ.get('MYSQL_USER', 'root')),
        password=env.get('MYSQL_PASSWORD', os.environ.get('MYSQL_PASSWORD', '')),
        database=env.get('MYSQL_DATABASE', os.environ.get('MYSQL_DATABASE', 'railway')),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=30,
        read_timeout=60
    )


def audit_personal_report():
    """Audit the Personal report for math errors and duplicates"""
    print("=" * 60)
    print("PERSONAL REPORT AUDIT")
    print("=" * 60)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all Personal transactions
    cursor.execute("""
        SELECT id, _index, chase_date, chase_description, chase_amount,
               r2_url, receipt_file, ocr_merchant, ocr_amount, ocr_date,
               source, notes, ai_note
        FROM transactions
        WHERE business_type = 'Personal'
        ORDER BY chase_date DESC, chase_amount
    """)
    transactions = cursor.fetchall()

    print(f"\nTotal Personal transactions: {len(transactions)}")

    # Calculate totals
    total_charges = 0  # Negative amounts (expenses)
    total_refunds = 0  # Positive amounts (credits)

    for t in transactions:
        amount = float(t['chase_amount'] or 0)
        if amount < 0:
            total_charges += amount
        else:
            total_refunds += amount

    net_total = total_charges + total_refunds

    print(f"\n--- MATH AUDIT ---")
    print(f"Total Charges (expenses):  ${total_charges:,.2f}")
    print(f"Total Refunds (credits):   ${total_refunds:,.2f}")
    print(f"Net Total:                 ${net_total:,.2f}")
    print(f"")
    print(f"Expected display:")
    print(f"  TOTAL CHARGES:    -{abs(total_charges):,.2f}")
    print(f"  REFUNDS/CREDITS:  +{total_refunds:,.2f}")
    print(f"  NET TOTAL:        {'+'if net_total >= 0 else '-'}${abs(net_total):,.2f}")

    # Check for the bug: -$-63,574.75 suggests double negative
    if net_total > 0:
        print(f"\n⚠️  WARNING: Net total is POSITIVE (${net_total:,.2f})")
        print(f"   This means refunds > charges")
        print(f"   The display showing '-$-63,574.75' is a BUG in the formatting")

    # Find duplicates
    print(f"\n--- DUPLICATE CHECK ---")
    duplicates = find_duplicates(transactions)

    # Find transactions with receipts
    with_receipts = [t for t in transactions if t['r2_url'] or t['receipt_file']]
    print(f"\nTransactions with receipts: {len(with_receipts)}")

    conn.close()

    return {
        'total': len(transactions),
        'charges': total_charges,
        'refunds': total_refunds,
        'net': net_total,
        'with_receipts': len(with_receipts),
        'duplicates': duplicates
    }


def find_duplicates(transactions):
    """Find potential duplicate transactions"""
    # Group by date + amount
    by_date_amount = defaultdict(list)
    for t in transactions:
        key = (str(t['chase_date']), float(t['chase_amount'] or 0))
        by_date_amount[key].append(t)

    duplicates = []
    for (date, amount), txns in by_date_amount.items():
        if len(txns) > 1:
            # Check if descriptions are similar
            descs = [t['chase_description'] for t in txns]
            if len(set(descs)) < len(descs):
                # Same description = likely duplicate
                duplicates.append({
                    'date': date,
                    'amount': amount,
                    'count': len(txns),
                    'transactions': txns,
                    'likely_duplicate': True
                })
            else:
                # Different descriptions = might be legitimate
                duplicates.append({
                    'date': date,
                    'amount': amount,
                    'count': len(txns),
                    'transactions': txns,
                    'likely_duplicate': False
                })

    if duplicates:
        print(f"\nFound {len(duplicates)} date+amount combinations with multiple transactions:")
        for d in duplicates[:10]:  # Show first 10
            status = "⚠️ LIKELY DUPLICATE" if d['likely_duplicate'] else "✓ Probably OK (different merchants)"
            print(f"\n  {d['date']} | ${d['amount']:.2f} | {d['count']} transactions | {status}")
            for t in d['transactions']:
                print(f"    - ID:{t['id']} | {t['chase_description'][:40]}")
                print(f"      Receipt: {'YES' if t['r2_url'] or t['receipt_file'] else 'NO'}")
    else:
        print("\n✓ No obvious duplicates found")

    return duplicates


def audit_apple_transactions():
    """Audit Apple transactions for proper descriptions"""
    print("\n" + "=" * 60)
    print("APPLE TRANSACTIONS AUDIT")
    print("=" * 60)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, _index, chase_date, chase_description, chase_amount,
               business_type, r2_url, receipt_file,
               ocr_merchant, ocr_amount, ocr_date, ai_note, notes
        FROM transactions
        WHERE chase_description LIKE '%Apple%'
           OR chase_description LIKE '%APPLE%'
           OR ocr_merchant LIKE '%Apple%'
        ORDER BY chase_date DESC
    """)
    apple_txns = cursor.fetchall()

    print(f"\nTotal Apple transactions: {len(apple_txns)}")

    needs_description = []
    has_good_description = []

    for t in apple_txns:
        # Check if we have a good description (mentions specific app/service)
        desc = (t['ai_note'] or '') + (t['notes'] or '') + (t['chase_description'] or '')
        desc_lower = desc.lower()

        # Keywords that indicate we know what the charge is for
        good_keywords = ['icloud', 'storage', 'music', 'tv+', 'arcade', 'news',
                        'fitness', 'one', 'app store', 'itunes', 'subscription',
                        'apple pay', 'wallet']

        has_detail = any(kw in desc_lower for kw in good_keywords)

        if has_detail:
            has_good_description.append(t)
        else:
            needs_description.append(t)

    print(f"\n✓ Apple transactions with good descriptions: {len(has_good_description)}")
    print(f"⚠️ Apple transactions needing OCR scan: {len(needs_description)}")

    if needs_description:
        print(f"\nTransactions needing receipt scan for app details:")
        for t in needs_description[:15]:
            receipt = t['r2_url'] or t['receipt_file'] or 'NO RECEIPT'
            print(f"  {t['chase_date']} | ${t['chase_amount']:.2f} | {t['chase_description'][:35]}")
            print(f"    Receipt: {receipt[:60]}...")
            print(f"    Current note: {(t['ai_note'] or 'None')[:50]}")

    conn.close()

    return {
        'total': len(apple_txns),
        'with_description': len(has_good_description),
        'needs_description': needs_description
    }


def fix_kit_business_type():
    """Fix Kit transaction business type from Personal to Down Home"""
    print("\n" + "=" * 60)
    print("FIX: Kit Business Type")
    print("=" * 60)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Find Kit transactions marked as Personal
    cursor.execute("""
        SELECT id, _index, chase_date, chase_description, chase_amount, business_type
        FROM transactions
        WHERE chase_description LIKE '%Kit%'
        AND business_type = 'Personal'
    """)
    kit_txns = cursor.fetchall()

    if not kit_txns:
        print("No Kit transactions found with Personal business type")
        conn.close()
        return 0

    print(f"\nFound {len(kit_txns)} Kit transactions marked as Personal:")
    for t in kit_txns:
        print(f"  {t['chase_date']} | {t['chase_description'][:40]} | ${t['chase_amount']:.2f}")

    # Fix them
    response = input("\nUpdate these to 'Down Home'? (yes/no): ")
    if response.lower() == 'yes':
        cursor.execute("""
            UPDATE transactions
            SET business_type = 'Down Home'
            WHERE chase_description LIKE '%Kit%'
            AND business_type = 'Personal'
        """)
        conn.commit()
        print(f"✓ Updated {cursor.rowcount} transactions to 'Down Home'")
    else:
        print("Skipped update")

    conn.close()
    return len(kit_txns)


def check_csv_source():
    """Verify transactions came from original CSV import"""
    print("\n" + "=" * 60)
    print("CSV SOURCE VERIFICATION")
    print("=" * 60)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check source field distribution
    cursor.execute("""
        SELECT source, COUNT(*) as count
        FROM transactions
        WHERE business_type = 'Personal'
        GROUP BY source
        ORDER BY count DESC
    """)
    sources = cursor.fetchall()

    print("\nTransaction sources for Personal:")
    for s in sources:
        print(f"  {s['source'] or 'NULL/Empty'}: {s['count']} transactions")

    # Find transactions without proper source
    cursor.execute("""
        SELECT id, chase_date, chase_description, chase_amount, source
        FROM transactions
        WHERE business_type = 'Personal'
        AND (source IS NULL OR source = '' OR source NOT LIKE '%csv%')
        LIMIT 20
    """)
    no_source = cursor.fetchall()

    if no_source:
        print(f"\n⚠️ Transactions without CSV source ({len(no_source)} shown):")
        for t in no_source:
            print(f"  {t['chase_date']} | {t['chase_description'][:35]} | ${t['chase_amount']:.2f} | source: {t['source']}")
    else:
        print("\n✓ All Personal transactions have CSV source")

    conn.close()


def find_mismatched_receipts():
    """Find receipts that don't match their transactions"""
    print("\n" + "=" * 60)
    print("RECEIPT MISMATCH CHECK")
    print("=" * 60)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Find transactions where OCR amount doesn't match chase_amount
    cursor.execute("""
        SELECT id, chase_date, chase_description, chase_amount,
               ocr_merchant, ocr_amount, ocr_date, r2_url,
               ABS(ABS(chase_amount) - ABS(COALESCE(ocr_amount, 0))) as amount_diff
        FROM transactions
        WHERE business_type = 'Personal'
        AND ocr_amount IS NOT NULL
        AND ABS(ABS(chase_amount) - ABS(ocr_amount)) > 1.00
        ORDER BY amount_diff DESC
        LIMIT 30
    """)
    mismatches = cursor.fetchall()

    if mismatches:
        print(f"\n⚠️ Found {len(mismatches)} potential receipt mismatches (amount diff > $1):")
        for m in mismatches:
            print(f"\n  {m['chase_date']} | {m['chase_description'][:35]}")
            print(f"    Bank: ${m['chase_amount']:.2f}")
            print(f"    OCR:  ${m['ocr_amount']:.2f} ({m['ocr_merchant']})")
            print(f"    Diff: ${m['amount_diff']:.2f}")
    else:
        print("\n✓ No significant receipt mismatches found")

    conn.close()
    return mismatches


def main():
    """Run all audits"""
    print("\n" + "=" * 60)
    print("TALLYUPS PERSONAL REPORT COMPREHENSIVE AUDIT")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        # 1. Audit report math
        report_audit = audit_personal_report()

        # 2. Check CSV sources
        check_csv_source()

        # 3. Find mismatched receipts
        mismatches = find_mismatched_receipts()

        # 4. Audit Apple transactions
        apple_audit = audit_apple_transactions()

        # 5. Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"""
Personal Report:
  - Total transactions: {report_audit['total']}
  - With receipts: {report_audit['with_receipts']}
  - Charges: ${report_audit['charges']:,.2f}
  - Refunds: ${report_audit['refunds']:,.2f}
  - Net: ${report_audit['net']:,.2f}
  - Potential duplicates: {len(report_audit['duplicates'])}

Apple Transactions:
  - Total: {apple_audit['total']}
  - Need OCR for app details: {len(apple_audit['needs_description'])}

Receipt Mismatches: {len(mismatches)}
        """)

        # 6. Offer to fix Kit
        print("\n" + "=" * 60)
        print("FIXES AVAILABLE")
        print("=" * 60)
        fix_kit = input("\nFix Kit business type (Personal -> Down Home)? (yes/no): ")
        if fix_kit.lower() == 'yes':
            fix_kit_business_type()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
