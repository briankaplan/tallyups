#!/usr/bin/env python3
"""
Quick sync diagnostic and refresh script.
Run this to check sync status and trigger a fresh sync.

Usage:
    python scripts/sync_diagnose.py           # Show diagnostics only
    python scripts/sync_diagnose.py --refresh # Reset cursor and sync
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_config import get_db_connection


def main():
    refresh = '--refresh' in sys.argv

    conn = get_db_connection()
    if not conn:
        print("❌ Database not configured")
        print("   Set MYSQL_URL or MYSQL* environment variables")
        return 1

    cursor = conn.cursor()

    # Check plaid_items
    print("=" * 60)
    print("PLAID ITEMS")
    print("=" * 60)
    cursor.execute('''
        SELECT item_id, institution_name, status,
               transactions_cursor IS NOT NULL as has_cursor,
               last_successful_sync, error_code, error_message
        FROM plaid_items
        ORDER BY created_at DESC
    ''')
    items = cursor.fetchall()

    if not items:
        print("  No bank connections found!")
        print("  Connect a bank at /bank_accounts.html")
        return 0

    for item in items:
        status_emoji = "✅" if item['status'] == 'active' else "⚠️"
        print(f"\n{status_emoji} {item['institution_name']}")
        print(f"   Item ID: {item['item_id']}")
        print(f"   Status: {item['status']}")
        print(f"   Has cursor: {bool(item['has_cursor'])}")
        if item['last_successful_sync']:
            print(f"   Last sync: {item['last_successful_sync']}")
        if item['error_code']:
            print(f"   ❌ ERROR: {item['error_code']} - {item['error_message']}")

    # Check transaction counts
    print("\n" + "=" * 60)
    print("TRANSACTIONS")
    print("=" * 60)
    cursor.execute('''
        SELECT COUNT(*) as total, MIN(date) as earliest, MAX(date) as latest
        FROM plaid_transactions
    ''')
    tx = cursor.fetchone()
    print(f"  Total: {tx['total']}")
    if tx['total'] > 0:
        print(f"  Date range: {tx['earliest']} to {tx['latest']}")
    else:
        print("  ⚠️  No transactions synced yet!")

    # Check recent sync history
    print("\n" + "=" * 60)
    print("RECENT SYNC HISTORY")
    print("=" * 60)
    cursor.execute('''
        SELECT pi.institution_name, sh.sync_type, sh.status, sh.started_at,
               sh.transactions_added, sh.transactions_modified, sh.error_message
        FROM plaid_sync_history sh
        JOIN plaid_items pi ON sh.item_id = pi.item_id
        ORDER BY sh.started_at DESC
        LIMIT 5
    ''')
    syncs = cursor.fetchall()

    if not syncs:
        print("  No sync history found")
    else:
        for sync in syncs:
            status_emoji = "✅" if sync['status'] == 'success' else "❌"
            added = sync['transactions_added'] or 0
            modified = sync['transactions_modified'] or 0
            print(f"\n  {status_emoji} {sync['institution_name']} ({sync['sync_type']})")
            print(f"     Time: {sync['started_at']}")
            print(f"     Added: {added}, Modified: {modified}")
            if sync['error_message']:
                print(f"     Error: {sync['error_message']}")

    # Refresh if requested
    if refresh and items:
        print("\n" + "=" * 60)
        print("REFRESHING SYNC")
        print("=" * 60)

        for item in items:
            if item['status'] != 'active':
                print(f"\n⚠️  Skipping {item['institution_name']} (status: {item['status']})")
                continue

            print(f"\n🔄 Resetting cursor for {item['institution_name']}...")
            cursor.execute('''
                UPDATE plaid_items
                SET transactions_cursor = NULL, updated_at = NOW()
                WHERE item_id = %s
            ''', (item['item_id'],))
            conn.commit()
            print("   Cursor cleared!")

            print("   Triggering sync...")
            try:
                # Import and use PlaidService
                from services.plaid_service import get_plaid_service
                plaid = get_plaid_service()
                result = plaid.sync_transactions(item['item_id'], sync_type='manual')

                if result.success:
                    print(f"   ✅ Sync complete: +{result.added} transactions")
                else:
                    print(f"   ❌ Sync failed: {result.error_message}")
            except Exception as e:
                print(f"   ❌ Error: {e}")

    conn.close()

    if not refresh:
        print("\n" + "-" * 60)
        print("To trigger a fresh sync, run:")
        print("  python scripts/sync_diagnose.py --refresh")

    return 0


if __name__ == '__main__':
    sys.exit(main())
