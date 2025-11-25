#!/usr/bin/env python3
"""
Migrate data from SQLite (receipts.db) to MySQL
Transfers all transactions and receipt metadata
"""

import os
import sys
from datetime import datetime

def migrate_data():
    """Migrate all data from SQLite to MySQL"""

    print("=" * 80)
    print("📦 SQLite → MySQL Data Migration")
    print("=" * 80)
    print()

    # Import database modules
    try:
        from db_sqlite import ReceiptDatabase as SQLiteDB
        from db_mysql import MySQLReceiptDatabase as MySQLDB
    except ImportError as e:
        print(f"❌ Failed to import database modules: {e}")
        print("Make sure you're in the correct directory and dependencies are installed.")
        return False

    # Connect to SQLite
    print("1️⃣  Connecting to SQLite...")
    sqlite_db = SQLiteDB('receipts.db')
    if not sqlite_db.use_sqlite:
        print("❌ SQLite database not available or empty")
        return False
    print(f"   ✅ Connected to SQLite: receipts.db")

    # Connect to MySQL
    print("\n2️⃣  Connecting to MySQL...")
    mysql_db = MySQLDB()
    if not mysql_db.use_mysql:
        print("❌ MySQL not available. Make sure MYSQL_URL or MYSQL* environment variables are set.")
        print("\nSet environment variables:")
        print("  export MYSQL_URL='mysql://user:pass@host:port/database'")
        print("  OR")
        print("  export MYSQLHOST='host'")
        print("  export MYSQLPORT='3306'")
        print("  export MYSQLUSER='user'")
        print("  export MYSQLPASSWORD='password'")
        print("  export MYSQLDATABASE='receipts'")
        return False
    print(f"   ✅ Connected to MySQL")

    # Get counts from SQLite
    print("\n3️⃣  Analyzing SQLite data...")
    try:
        sqlite_transactions = sqlite_db.get_all_transactions()
        sqlite_metadata = sqlite_db.get_all_receipt_metadata()
        sqlite_reports = sqlite_db.get_all_reports()

        print(f"   📊 Transactions: {len(sqlite_transactions)}")
        print(f"   📊 Receipt Metadata: {len(sqlite_metadata)}")
        print(f"   📊 Reports: {len(sqlite_reports)}")
    except Exception as e:
        print(f"   ❌ Failed to read SQLite data: {e}")
        return False

    if len(sqlite_transactions) == 0:
        print("\n⚠️  No transactions to migrate")
        return True

    # Confirm migration
    print(f"\n⚠️  This will migrate {len(sqlite_transactions)} transactions to MySQL.")
    print("   Existing MySQL data will NOT be deleted (duplicates may occur).")

    # Check if running in non-interactive mode
    import sys
    if sys.stdin.isatty():
        response = input("\n   Continue? (yes/no): ").lower().strip()
        if response != 'yes':
            print("\n❌ Migration cancelled")
            return False
    else:
        print("\n   ✅ Auto-proceeding (non-interactive mode)")

    # Migrate transactions
    print(f"\n4️⃣  Migrating {len(sqlite_transactions)} transactions...")
    migrated_count = 0
    failed_count = 0

    # Convert DataFrame to list of dicts
    transactions_data = sqlite_transactions.to_dict('records')

    for i, row in enumerate(transactions_data, 1):
        try:
            # Helper function to convert empty strings to None for dates
            def clean_date(val):
                return None if val == '' or val is None else val

            # Map user-facing column names back to database columns
            db_row = {
                '_index': row.get('_index'),
                'chase_date': clean_date(row.get('Chase Date')),
                'chase_description': row.get('Chase Description'),
                'chase_amount': row.get('Chase Amount'),
                'chase_category': row.get('Chase Category'),
                'chase_type': row.get('Chase Type'),
                'receipt_file': row.get('Receipt File'),
                'receipt_url': row.get('receipt_url'),  # R2 receipt URL
                'r2_url': row.get('r2_url'),  # Alternative R2 URL field
                'business_type': row.get('Business Type'),
                'notes': row.get('Notes'),
                'ai_note': row.get('AI Note'),
                'ai_confidence': row.get('AI Confidence'),
                'ai_receipt_merchant': row.get('ai_receipt_merchant'),
                'ai_receipt_date': clean_date(row.get('ai_receipt_date')),
                'ai_receipt_total': row.get('ai_receipt_total'),
                'review_status': row.get('Review Status'),
                'category': row.get('Category'),
                'report_id': row.get('Report ID'),
                'source': row.get('Source'),
                'mi_merchant': row.get('MI Merchant'),
                'mi_category': row.get('MI Category'),
                'mi_description': row.get('MI Description'),
                'mi_confidence': row.get('MI Confidence'),
                'mi_is_subscription': row.get('MI Is Subscription'),
                'mi_subscription_name': row.get('MI Subscription Name'),
                'mi_processed_at': clean_date(row.get('MI Processed At')),
                'is_refund': row.get('Is Refund'),
                'already_submitted': row.get('Already Submitted'),
                'deleted_by_user': row.get('deleted_by_user')
            }

            # Insert into MySQL
            cursor = mysql_db.conn.cursor()

            # Build INSERT statement
            columns = [k for k, v in db_row.items() if v is not None]
            values = [v for k, v in db_row.items() if v is not None]
            placeholders = ', '.join(['%s'] * len(values))
            columns_str = ', '.join(columns)

            sql = f"""
                INSERT INTO transactions ({columns_str})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE
                    chase_date = VALUES(chase_date),
                    chase_description = VALUES(chase_description),
                    chase_amount = VALUES(chase_amount),
                    receipt_file = VALUES(receipt_file),
                    receipt_url = VALUES(receipt_url),
                    r2_url = VALUES(r2_url),
                    business_type = VALUES(business_type),
                    notes = VALUES(notes),
                    ai_note = VALUES(ai_note),
                    ai_confidence = VALUES(ai_confidence),
                    review_status = VALUES(review_status),
                    category = VALUES(category),
                    report_id = VALUES(report_id),
                    mi_merchant = VALUES(mi_merchant),
                    mi_category = VALUES(mi_category),
                    mi_description = VALUES(mi_description),
                    mi_confidence = VALUES(mi_confidence),
                    already_submitted = VALUES(already_submitted)
            """

            cursor.execute(sql, values)
            mysql_db.conn.commit()
            migrated_count += 1

            # Progress indicator
            if i % 100 == 0 or i == len(transactions_data):
                print(f"   ✓ {i}/{len(transactions_data)} transactions migrated", end='\r')

        except Exception as e:
            failed_count += 1
            if failed_count <= 5:  # Only show first 5 errors
                print(f"\n   ⚠️  Failed to migrate row {i}: {e}")

    print(f"\n   ✅ Migrated {migrated_count} transactions")
    if failed_count > 0:
        print(f"   ⚠️  Failed: {failed_count} transactions")

    # Migrate receipt metadata
    if len(sqlite_metadata) > 0:
        print(f"\n5️⃣  Migrating {len(sqlite_metadata)} receipt metadata entries...")
        metadata_migrated = 0

        for meta in sqlite_metadata:
            try:
                mysql_db.cache_receipt_metadata(
                    filename=meta['filename'],
                    merchant=meta.get('merchant', ''),
                    date=meta.get('date', ''),
                    amount=float(meta.get('amount', 0)),
                    raw_text=meta.get('raw_text', '')
                )
                metadata_migrated += 1
            except Exception as e:
                print(f"   ⚠️  Failed to migrate metadata: {e}")

        print(f"   ✅ Migrated {metadata_migrated} metadata entries")

    # Migrate reports
    if len(sqlite_reports) > 0:
        print(f"\n6️⃣  Migrating {len(sqlite_reports)} reports...")
        reports_migrated = 0

        for report in sqlite_reports:
            try:
                cursor = mysql_db.conn.cursor()
                cursor.execute("""
                    INSERT INTO reports (report_id, report_name, business_type, expense_count, total_amount, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        report_name = VALUES(report_name),
                        expense_count = VALUES(expense_count),
                        total_amount = VALUES(total_amount)
                """, (
                    report['report_id'],
                    report['report_name'],
                    report['business_type'],
                    report['expense_count'],
                    report['total_amount'],
                    report.get('created_at', datetime.now().isoformat())
                ))
                mysql_db.conn.commit()
                reports_migrated += 1
            except Exception as e:
                print(f"   ⚠️  Failed to migrate report: {e}")

        print(f"   ✅ Migrated {reports_migrated} reports")

    # Verify migration
    print("\n7️⃣  Verifying migration...")
    try:
        mysql_transactions = mysql_db.get_all_transactions()
        print(f"   ✅ MySQL now has {len(mysql_transactions)} transactions")

        if len(mysql_transactions) >= len(sqlite_transactions):
            print(f"   ✅ Migration successful!")
        else:
            print(f"   ⚠️  Warning: MySQL has fewer transactions than SQLite")
            print(f"      SQLite: {len(sqlite_transactions)} | MySQL: {len(mysql_transactions)}")
    except Exception as e:
        print(f"   ⚠️  Verification failed: {e}")

    print("\n" + "=" * 80)
    print("✅ Migration complete!")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Verify data in MySQL")
    print("2. Deploy to Railway (MySQL will be used automatically)")
    print("3. Keep receipts.db as backup")
    print()

    return True


if __name__ == "__main__":
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    success = migrate_data()
    sys.exit(0 if success else 1)
