#!/usr/bin/env python3
"""
Quick script to migrate receipt_url from SQLite to MySQL for existing records.
Run this after the initial migration to fix missing receipt URLs.
"""

import sqlite3
import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

# MySQL connection config
MYSQL_CONFIG = {
    'host': os.environ.get('MYSQLHOST', 'autorack.proxy.rlwy.net'),
    'port': int(os.environ.get('MYSQLPORT', '52253')),
    'user': os.environ.get('MYSQLUSER', 'root'),
    'password': os.environ.get('MYSQLPASSWORD', 'tWVdCjmGEKdyGLCqXVNuwWPYNrNRAzdb'),
    'database': os.environ.get('MYSQLDATABASE', 'railway'),
    'charset': 'utf8mb4'
}

def migrate_receipt_urls():
    print("=" * 80)
    print("📦 Migrating receipt_url from SQLite to MySQL")
    print("=" * 80)

    # Connect to SQLite
    print("\n1️⃣  Connecting to SQLite...")
    sqlite_conn = sqlite3.connect('receipts.db')
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    # Get all transactions with receipt_url
    sqlite_cursor.execute("""
        SELECT _index, receipt_url
        FROM transactions
        WHERE receipt_url IS NOT NULL AND receipt_url != ''
    """)
    rows = sqlite_cursor.fetchall()
    print(f"   Found {len(rows)} transactions with receipt URLs in SQLite")

    if len(rows) == 0:
        print("   No receipt URLs to migrate")
        return

    # Connect to MySQL
    print("\n2️⃣  Connecting to MySQL...")
    try:
        mysql_conn = pymysql.connect(**MYSQL_CONFIG)
        mysql_cursor = mysql_conn.cursor()
        print(f"   Connected to MySQL: {MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}")
    except Exception as e:
        print(f"   ❌ Failed to connect to MySQL: {e}")
        return

    # Update receipt_url in MySQL
    print(f"\n3️⃣  Updating receipt_url for {len(rows)} transactions...")
    updated = 0
    failed = 0

    for row in rows:
        idx = row['_index']
        url = row['receipt_url']

        try:
            mysql_cursor.execute("""
                UPDATE transactions
                SET receipt_url = %s, r2_url = %s
                WHERE _index = %s
            """, (url, url, idx))
            updated += 1
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"   ⚠️  Failed to update _index {idx}: {e}")

    mysql_conn.commit()

    print(f"\n   ✅ Updated {updated} transactions")
    if failed > 0:
        print(f"   ⚠️  Failed: {failed} transactions")

    # Verify
    print("\n4️⃣  Verifying migration...")
    mysql_cursor.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE receipt_url IS NOT NULL AND receipt_url != ''
    """)
    count = mysql_cursor.fetchone()[0]
    print(f"   MySQL now has {count} transactions with receipt URLs")

    # Show sample
    mysql_cursor.execute("""
        SELECT _index, receipt_url FROM transactions
        WHERE receipt_url IS NOT NULL AND receipt_url != ''
        LIMIT 3
    """)
    print("\n   Sample URLs:")
    for row in mysql_cursor.fetchall():
        print(f"   _index={row[0]}: {row[1][:60]}...")

    mysql_conn.close()
    sqlite_conn.close()

    print("\n" + "=" * 80)
    print("✅ Receipt URL migration complete!")
    print("=" * 80)

if __name__ == "__main__":
    migrate_receipt_urls()
