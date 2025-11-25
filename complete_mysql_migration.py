#!/usr/bin/env python3
"""
Complete MySQL Migration Script
Migrates ALL tables and ALL data from SQLite to MySQL

Tables to migrate:
- transactions (830 rows)
- reports (1 row)
- incoming_receipts (306 rows)
- rejected_receipts (24 rows)
- merchants (279 rows)
- contacts (1495 rows)
- receipt_metadata (0 rows)
- incoming_rejection_patterns (0 rows)
"""

import sqlite3
import pymysql
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# MySQL connection config (Railway)
MYSQL_CONFIG = {
    'host': os.environ.get('MYSQLHOST', 'autorack.proxy.rlwy.net'),
    'port': int(os.environ.get('MYSQLPORT', '52253')),
    'user': os.environ.get('MYSQLUSER', 'root'),
    'password': os.environ.get('MYSQLPASSWORD', 'tWVdCjmGEKdyGLCqXVNuwWPYNrNRAzdb'),
    'database': os.environ.get('MYSQLDATABASE', 'railway'),
    'charset': 'utf8mb4'
}

SQLITE_PATH = 'receipts.db'


def get_sqlite_conn():
    """Get SQLite connection"""
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_mysql_conn():
    """Get MySQL connection"""
    return pymysql.connect(**MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)


def create_mysql_tables(cursor):
    """Create all MySQL tables with proper schema"""

    # Transactions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            _index INT NOT NULL UNIQUE,
            chase_date DATE,
            chase_description TEXT,
            chase_amount DECIMAL(10,2),
            chase_category VARCHAR(255),
            chase_type VARCHAR(100),
            receipt_file VARCHAR(500),
            receipt_url VARCHAR(1000),
            r2_url VARCHAR(1000),
            business_type VARCHAR(255),
            notes TEXT,
            ai_note TEXT,
            ai_confidence INT,
            ai_receipt_merchant VARCHAR(255),
            ai_receipt_date VARCHAR(100),
            ai_receipt_total VARCHAR(100),
            review_status VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            category VARCHAR(255) DEFAULT '',
            report_id VARCHAR(255),
            source VARCHAR(100) DEFAULT 'Chase',
            mi_merchant VARCHAR(255),
            mi_category VARCHAR(255),
            mi_description TEXT,
            mi_confidence DECIMAL(5,2),
            mi_is_subscription TINYINT DEFAULT 0,
            mi_subscription_name VARCHAR(255),
            mi_processed_at DATETIME,
            deleted_by_user TINYINT DEFAULT 0,
            already_submitted VARCHAR(50) DEFAULT ''
        )
    """)

    # Reports table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INT AUTO_INCREMENT PRIMARY KEY,
            report_id VARCHAR(255) UNIQUE NOT NULL,
            report_name VARCHAR(500) NOT NULL,
            business_type VARCHAR(255) NOT NULL,
            expense_count INT NOT NULL,
            total_amount DECIMAL(10,2) NOT NULL,
            created_at DATETIME NOT NULL
        )
    """)

    # Incoming receipts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incoming_receipts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email_id VARCHAR(255) UNIQUE NOT NULL,
            gmail_account VARCHAR(255) NOT NULL,
            subject TEXT,
            from_email VARCHAR(255),
            from_domain VARCHAR(255),
            received_date DATETIME,
            body_snippet TEXT,
            has_attachment TINYINT,
            attachment_count INT DEFAULT 0,
            receipt_files TEXT,
            merchant VARCHAR(255),
            amount DECIMAL(10,2),
            transaction_date DATE,
            ocr_confidence INT,
            is_receipt TINYINT DEFAULT 1,
            is_marketing TINYINT DEFAULT 0,
            confidence_score INT,
            status VARCHAR(50) DEFAULT 'pending',
            reviewed_at DATETIME,
            accepted_as_transaction_id INT,
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at DATETIME,
            description TEXT,
            is_subscription TINYINT DEFAULT 0,
            matched_transaction_id INT,
            match_type VARCHAR(100),
            attachments TEXT,
            is_refund TINYINT DEFAULT 0
        )
    """)

    # Rejected receipts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rejected_receipts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            transaction_date VARCHAR(50),
            transaction_description TEXT,
            transaction_amount VARCHAR(50),
            receipt_path VARCHAR(500) NOT NULL,
            rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason VARCHAR(255) DEFAULT 'user_manually_removed',
            transaction_index INT,
            UNIQUE KEY unique_rejection (receipt_path(255))
        )
    """)

    # Merchants table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS merchants (
            id INT AUTO_INCREMENT PRIMARY KEY,
            raw_description VARCHAR(500) UNIQUE NOT NULL,
            normalized_name VARCHAR(255) NOT NULL,
            category VARCHAR(255),
            is_subscription TINYINT DEFAULT 0,
            frequency INT DEFAULT 0,
            avg_amount DECIMAL(10,2),
            primary_business_type VARCHAR(255),
            aliases TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Contacts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            title VARCHAR(255),
            company VARCHAR(255),
            category VARCHAR(255),
            priority VARCHAR(50),
            notes TEXT,
            relationship VARCHAR(255),
            status VARCHAR(100),
            strategic_notes TEXT,
            connected_on VARCHAR(100),
            name_tokens TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Receipt metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receipt_metadata (
            filename VARCHAR(500) PRIMARY KEY,
            merchant VARCHAR(255),
            date VARCHAR(100),
            amount DECIMAL(10,2),
            raw_text TEXT,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Incoming rejection patterns table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incoming_rejection_patterns (
            id INT AUTO_INCREMENT PRIMARY KEY,
            pattern_type VARCHAR(100) NOT NULL,
            pattern_value VARCHAR(500) NOT NULL,
            rejection_count INT DEFAULT 1,
            last_rejected_at DATETIME,
            UNIQUE KEY unique_pattern (pattern_type, pattern_value(255))
        )
    """)

    print("✅ All MySQL tables created/verified")


def migrate_transactions(sqlite_cursor, mysql_cursor):
    """Migrate transactions table"""
    print("\n📦 Migrating transactions...")

    sqlite_cursor.execute("SELECT * FROM transactions")
    rows = sqlite_cursor.fetchall()

    migrated = 0
    for row in rows:
        try:
            # Handle date conversion
            chase_date = row['chase_date'] if row['chase_date'] else None

            mysql_cursor.execute("""
                INSERT INTO transactions
                (_index, chase_date, chase_description, chase_amount, chase_category, chase_type,
                 receipt_file, receipt_url, business_type, notes, ai_note, ai_confidence,
                 ai_receipt_merchant, ai_receipt_date, ai_receipt_total, review_status,
                 category, report_id, source, mi_merchant, mi_category, mi_description,
                 mi_confidence, mi_is_subscription, mi_subscription_name, mi_processed_at,
                 deleted_by_user, already_submitted)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    chase_date = VALUES(chase_date),
                    chase_description = VALUES(chase_description),
                    chase_amount = VALUES(chase_amount),
                    receipt_file = VALUES(receipt_file),
                    receipt_url = VALUES(receipt_url),
                    r2_url = VALUES(receipt_url),
                    business_type = VALUES(business_type),
                    notes = VALUES(notes),
                    ai_note = VALUES(ai_note),
                    review_status = VALUES(review_status),
                    category = VALUES(category),
                    report_id = VALUES(report_id),
                    mi_merchant = VALUES(mi_merchant),
                    mi_category = VALUES(mi_category),
                    mi_description = VALUES(mi_description),
                    already_submitted = VALUES(already_submitted)
            """, (
                row['_index'],
                chase_date,
                row['chase_description'],
                row['chase_amount'],
                row['chase_category'],
                row['chase_type'],
                row['receipt_file'],
                row['receipt_url'],
                row['business_type'],
                row['notes'],
                row['ai_note'],
                row['ai_confidence'],
                row['ai_receipt_merchant'],
                row['ai_receipt_date'],
                row['ai_receipt_total'],
                row['review_status'],
                row['category'],
                row['report_id'],
                row['source'],
                row['mi_merchant'],
                row['mi_category'],
                row['mi_description'],
                row['mi_confidence'],
                row['mi_is_subscription'],
                row['mi_subscription_name'],
                row['mi_processed_at'],
                row['deleted_by_user'],
                row['already_submitted']
            ))
            migrated += 1
        except Exception as e:
            print(f"  ⚠️  Failed to migrate transaction _index={row['_index']}: {e}")

    print(f"  ✅ Migrated {migrated}/{len(rows)} transactions")
    return migrated


def migrate_reports(sqlite_cursor, mysql_cursor):
    """Migrate reports table"""
    print("\n📦 Migrating reports...")

    sqlite_cursor.execute("SELECT * FROM reports")
    rows = sqlite_cursor.fetchall()

    migrated = 0
    for row in rows:
        try:
            mysql_cursor.execute("""
                INSERT INTO reports (report_id, report_name, business_type, expense_count, total_amount, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    report_name = VALUES(report_name),
                    expense_count = VALUES(expense_count),
                    total_amount = VALUES(total_amount)
            """, (
                row['report_id'],
                row['report_name'],
                row['business_type'],
                row['expense_count'],
                row['total_amount'],
                row['created_at']
            ))
            migrated += 1
        except Exception as e:
            print(f"  ⚠️  Failed to migrate report {row['report_id']}: {e}")

    print(f"  ✅ Migrated {migrated}/{len(rows)} reports")
    return migrated


def migrate_incoming_receipts(sqlite_cursor, mysql_cursor):
    """Migrate incoming_receipts table"""
    print("\n📦 Migrating incoming_receipts...")

    sqlite_cursor.execute("SELECT * FROM incoming_receipts")
    rows = sqlite_cursor.fetchall()

    migrated = 0
    for row in rows:
        try:
            mysql_cursor.execute("""
                INSERT INTO incoming_receipts
                (email_id, gmail_account, subject, from_email, from_domain, received_date,
                 body_snippet, has_attachment, attachment_count, receipt_files, merchant,
                 amount, transaction_date, ocr_confidence, is_receipt, is_marketing,
                 confidence_score, status, reviewed_at, accepted_as_transaction_id,
                 rejection_reason, processed_at, description, is_subscription,
                 matched_transaction_id, match_type, attachments)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    reviewed_at = VALUES(reviewed_at),
                    merchant = VALUES(merchant),
                    amount = VALUES(amount)
            """, (
                row['email_id'],
                row['gmail_account'],
                row['subject'],
                row['from_email'],
                row['from_domain'],
                row['received_date'],
                row['body_snippet'],
                row['has_attachment'],
                row['attachment_count'],
                row['receipt_files'],
                row['merchant'],
                row['amount'],
                row['transaction_date'],
                row['ocr_confidence'],
                row['is_receipt'],
                row['is_marketing'],
                row['confidence_score'],
                row['status'],
                row['reviewed_at'],
                row['accepted_as_transaction_id'],
                row['rejection_reason'],
                row['processed_at'],
                row['description'],
                row['is_subscription'],
                row['matched_transaction_id'],
                row['match_type'],
                row['attachments']
            ))
            migrated += 1
        except Exception as e:
            print(f"  ⚠️  Failed to migrate incoming_receipt {row['email_id']}: {e}")

    print(f"  ✅ Migrated {migrated}/{len(rows)} incoming_receipts")
    return migrated


def migrate_rejected_receipts(sqlite_cursor, mysql_cursor):
    """Migrate rejected_receipts table"""
    print("\n📦 Migrating rejected_receipts...")

    sqlite_cursor.execute("SELECT * FROM rejected_receipts")
    rows = sqlite_cursor.fetchall()

    migrated = 0
    for row in rows:
        try:
            mysql_cursor.execute("""
                INSERT INTO rejected_receipts
                (transaction_date, transaction_description, transaction_amount, receipt_path, rejected_at, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    reason = VALUES(reason)
            """, (
                row['transaction_date'],
                row['transaction_description'],
                row['transaction_amount'],
                row['receipt_path'],
                row['rejected_at'],
                row['reason']
            ))
            migrated += 1
        except Exception as e:
            print(f"  ⚠️  Failed to migrate rejected_receipt: {e}")

    print(f"  ✅ Migrated {migrated}/{len(rows)} rejected_receipts")
    return migrated


def migrate_merchants(sqlite_cursor, mysql_cursor):
    """Migrate merchants table"""
    print("\n📦 Migrating merchants...")

    sqlite_cursor.execute("SELECT * FROM merchants")
    rows = sqlite_cursor.fetchall()

    migrated = 0
    for row in rows:
        try:
            mysql_cursor.execute("""
                INSERT INTO merchants
                (raw_description, normalized_name, category, is_subscription, frequency, avg_amount, primary_business_type, aliases)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    normalized_name = VALUES(normalized_name),
                    category = VALUES(category)
            """, (
                row['raw_description'],
                row['normalized_name'],
                row['category'],
                row['is_subscription'],
                row['frequency'],
                row['avg_amount'],
                row['primary_business_type'],
                row['aliases']
            ))
            migrated += 1
        except Exception as e:
            print(f"  ⚠️  Failed to migrate merchant {row['raw_description']}: {e}")

    print(f"  ✅ Migrated {migrated}/{len(rows)} merchants")
    return migrated


def migrate_contacts(sqlite_cursor, mysql_cursor):
    """Migrate contacts table"""
    print("\n📦 Migrating contacts...")

    sqlite_cursor.execute("SELECT * FROM contacts")
    rows = sqlite_cursor.fetchall()

    migrated = 0
    for row in rows:
        try:
            mysql_cursor.execute("""
                INSERT INTO contacts
                (name, first_name, last_name, title, company, category, priority, notes, relationship, status, strategic_notes, connected_on, name_tokens)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name)
            """, (
                row['name'],
                row['first_name'],
                row['last_name'],
                row['title'],
                row['company'],
                row['category'],
                row['priority'],
                row['notes'],
                row['relationship'],
                row['status'],
                row['strategic_notes'],
                row['connected_on'],
                row['name_tokens']
            ))
            migrated += 1
        except Exception as e:
            print(f"  ⚠️  Failed to migrate contact {row['name']}: {e}")

    print(f"  ✅ Migrated {migrated}/{len(rows)} contacts")
    return migrated


def verify_migration(mysql_cursor):
    """Verify migration counts"""
    print("\n🔍 Verifying migration...")

    tables = ['transactions', 'reports', 'incoming_receipts', 'rejected_receipts', 'merchants', 'contacts']

    for table in tables:
        mysql_cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
        count = mysql_cursor.fetchone()['cnt']
        print(f"  📊 {table}: {count} rows")

    # Verify receipt_url data specifically
    mysql_cursor.execute("SELECT COUNT(*) as cnt FROM transactions WHERE receipt_url IS NOT NULL AND receipt_url != ''")
    url_count = mysql_cursor.fetchone()['cnt']
    print(f"  📷 Transactions with receipt_url: {url_count}")


def main():
    print("=" * 80)
    print("📦 Complete SQLite → MySQL Migration")
    print("=" * 80)

    # Connect to databases
    print("\n1️⃣  Connecting to databases...")
    sqlite_conn = get_sqlite_conn()
    sqlite_cursor = sqlite_conn.cursor()

    try:
        mysql_conn = get_mysql_conn()
        mysql_cursor = mysql_conn.cursor()
        print("  ✅ Connected to both databases")
    except Exception as e:
        print(f"  ❌ Failed to connect to MySQL: {e}")
        return False

    # Create tables
    print("\n2️⃣  Creating/verifying MySQL tables...")
    create_mysql_tables(mysql_cursor)
    mysql_conn.commit()

    # Migrate data
    print("\n3️⃣  Migrating data...")
    migrate_transactions(sqlite_cursor, mysql_cursor)
    mysql_conn.commit()

    migrate_reports(sqlite_cursor, mysql_cursor)
    mysql_conn.commit()

    migrate_incoming_receipts(sqlite_cursor, mysql_cursor)
    mysql_conn.commit()

    migrate_rejected_receipts(sqlite_cursor, mysql_cursor)
    mysql_conn.commit()

    migrate_merchants(sqlite_cursor, mysql_cursor)
    mysql_conn.commit()

    migrate_contacts(sqlite_cursor, mysql_cursor)
    mysql_conn.commit()

    # Verify
    verify_migration(mysql_cursor)

    # Cleanup
    sqlite_conn.close()
    mysql_conn.close()

    print("\n" + "=" * 80)
    print("✅ Migration complete!")
    print("=" * 80)

    return True


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
