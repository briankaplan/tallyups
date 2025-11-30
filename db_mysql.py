"""
ReceiptAI MySQL Database Layer
Created: 2025-11-24

Provides MySQL database operations for ReceiptAI system.
Mirrors the db_sqlite.py interface for drop-in compatibility.
"""

import os
import json
import pymysql
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse

# MySQL connection from Railway environment variables
# Railway provides either MYSQL_URL or individual MYSQL* variables
def get_mysql_config() -> Optional[Dict[str, str]]:
    """Get MySQL configuration from environment variables"""

    # Try MYSQL_URL first (Railway format: mysql://user:pass@host:port/database)
    mysql_url = os.environ.get('MYSQL_URL')
    if mysql_url:
        try:
            parsed = urlparse(mysql_url)
            return {
                'host': parsed.hostname,
                'port': parsed.port or 3306,
                'user': parsed.username,
                'password': parsed.password,
                'database': parsed.path.lstrip('/') if parsed.path else 'receipts',
                'charset': 'utf8mb4'
            }
        except Exception as e:
            print(f"⚠️  Failed to parse MYSQL_URL: {e}", flush=True)

    # Try individual variables (Railway also provides these)
    host = os.environ.get('MYSQLHOST')
    user = os.environ.get('MYSQLUSER')
    password = os.environ.get('MYSQLPASSWORD')
    database = os.environ.get('MYSQLDATABASE', 'receipts')
    port = int(os.environ.get('MYSQLPORT', '3306'))

    if host and user and password:
        return {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database,
            'charset': 'utf8mb4'
        }

    return None


class MySQLReceiptDatabase:
    """MySQL database handler for ReceiptAI"""

    def __init__(self, config: Optional[Dict[str, str]] = None):
        self.config = config or get_mysql_config()
        self.conn = None
        self.use_mysql = False

        if not self.config:
            print(f"ℹ️  MySQL not configured (set MYSQL_URL or MYSQL* variables)", flush=True)
            return

        # Try to connect to MySQL
        try:
            self.conn = pymysql.connect(
                **self.config,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False
            )
            self.use_mysql = True
            print(f"✅ Connected to MySQL: {self.config['host']}:{self.config['port']}/{self.config['database']}", flush=True)

            # Initialize schema if needed
            self._init_schema()

        except Exception as e:
            print(f"⚠️  MySQL connection failed: {e}", flush=True)
            self.use_mysql = False

    def __del__(self):
        """Close connection on cleanup"""
        if self.conn:
            self.conn.close()

    def get_connection(self):
        """Get a NEW connection for direct SQL operations.

        IMPORTANT: Caller is responsible for closing this connection!
        Use this for operations that need direct cursor access.
        """
        if not self.config:
            raise RuntimeError("MySQL not configured")

        return pymysql.connect(
            **self.config,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False
        )

    def ensure_connection(self):
        """Ensure the shared connection is alive, reconnect if needed"""
        if not self.use_mysql:
            return False

        try:
            self.conn.ping(reconnect=True)
            return True
        except Exception as e:
            print(f"⚠️  MySQL connection lost, reconnecting: {e}", flush=True)
            try:
                self.conn = pymysql.connect(
                    **self.config,
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=False
                )
                return True
            except Exception as e2:
                print(f"❌ MySQL reconnection failed: {e2}", flush=True)
                self.use_mysql = False
                return False

    def execute_query(self, query: str, params: tuple = None) -> List[Dict]:
        """Execute a raw SQL query and return results as list of dicts.

        Args:
            query: SQL query string
            params: Optional tuple of parameters for parameterized queries

        Returns:
            List of dictionaries (one per row) for SELECT queries,
            or empty list for non-SELECT queries
        """
        if not self.use_mysql:
            return []

        self.ensure_connection()

        try:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Check if this is a SELECT query
            if query.strip().upper().startswith('SELECT'):
                results = cursor.fetchall()
                cursor.close()
                return list(results) if results else []
            else:
                self.conn.commit()
                cursor.close()
                return []
        except Exception as e:
            print(f"❌ Query error: {e}", flush=True)
            return []

    def _init_schema(self):
        """Initialize database schema (tables, indexes)"""
        if not self.use_mysql or not self.conn:
            return

        try:
            cursor = self.conn.cursor()

            # Create transactions table
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
                    ai_confidence FLOAT,
                    ai_receipt_merchant VARCHAR(255),
                    ai_receipt_date DATE,
                    ai_receipt_total DECIMAL(10,2),
                    review_status VARCHAR(100),
                    category VARCHAR(255),
                    report_id VARCHAR(255),
                    source VARCHAR(255),
                    mi_merchant VARCHAR(255),
                    mi_category VARCHAR(255),
                    mi_description TEXT,
                    mi_confidence DECIMAL(5,4),
                    mi_is_subscription BOOLEAN,
                    mi_subscription_name VARCHAR(255),
                    mi_processed_at DATETIME,
                    is_refund BOOLEAN,
                    already_submitted VARCHAR(50),
                    deleted BOOLEAN DEFAULT FALSE,
                    deleted_by_user BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_index (_index),
                    INDEX idx_date (chase_date),
                    INDEX idx_business (business_type),
                    INDEX idx_review (review_status),
                    INDEX idx_report (report_id),
                    INDEX idx_deleted (deleted),
                    INDEX idx_submitted (already_submitted)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create receipt_metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipt_metadata (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    filename VARCHAR(500) NOT NULL UNIQUE,
                    merchant VARCHAR(255),
                    date DATE,
                    amount DECIMAL(10,2),
                    raw_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_filename (filename),
                    INDEX idx_merchant (merchant),
                    INDEX idx_date (date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create reports table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    report_id VARCHAR(255) NOT NULL UNIQUE,
                    report_name VARCHAR(255) NOT NULL,
                    business_type VARCHAR(255) NOT NULL,
                    expense_count INT NOT NULL,
                    total_amount DECIMAL(10,2) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_report_id (report_id),
                    INDEX idx_business (business_type)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create rejected_receipts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rejected_receipts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    transaction_date VARCHAR(50),
                    transaction_description TEXT,
                    transaction_amount VARCHAR(50),
                    receipt_path VARCHAR(500) NOT NULL,
                    transaction_index INT,
                    reason VARCHAR(255) DEFAULT 'user_manually_removed',
                    rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_receipt_path (receipt_path),
                    INDEX idx_transaction (transaction_index),
                    UNIQUE KEY unique_rejection (transaction_date, transaction_amount, receipt_path(200))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create incoming_receipts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS incoming_receipts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    email_id VARCHAR(255),
                    gmail_account VARCHAR(255),
                    sender VARCHAR(255),
                    from_email VARCHAR(255),
                    subject TEXT,
                    description TEXT,
                    body_snippet TEXT,
                    receipt_date DATE,
                    received_date DATETIME,
                    merchant VARCHAR(255),
                    amount DECIMAL(10,2),
                    confidence_score INT DEFAULT 0,
                    category VARCHAR(255),
                    business_type VARCHAR(255),
                    file_path VARCHAR(500),
                    receipt_file VARCHAR(500),
                    receipt_files TEXT,
                    attachments TEXT,
                    source VARCHAR(100) DEFAULT 'gmail',
                    status VARCHAR(50) DEFAULT 'pending',
                    match_type VARCHAR(100),
                    matched_transaction_id INT,
                    accepted_as_transaction_id INT,
                    is_subscription BOOLEAN DEFAULT FALSE,
                    is_refund BOOLEAN DEFAULT FALSE,
                    notes TEXT,
                    rejection_reason VARCHAR(255),
                    reviewed_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processed_at DATETIME,
                    INDEX idx_status (status),
                    INDEX idx_merchant (merchant),
                    INDEX idx_date (receipt_date),
                    INDEX idx_received (received_date),
                    INDEX idx_source (source)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create incoming_rejection_patterns table for learning
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS incoming_rejection_patterns (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    pattern_type VARCHAR(100) NOT NULL,
                    pattern_value VARCHAR(255) NOT NULL,
                    rejection_count INT DEFAULT 1,
                    last_rejected_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_pattern (pattern_type, pattern_value),
                    INDEX idx_pattern_type (pattern_type)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create merchants table for merchant intelligence/learning
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS merchants (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    raw_description VARCHAR(500) NOT NULL,
                    normalized_name VARCHAR(255) NOT NULL,
                    category VARCHAR(255),
                    is_subscription BOOLEAN DEFAULT FALSE,
                    subscription_name VARCHAR(255),
                    avg_amount DECIMAL(10,2),
                    primary_business_type VARCHAR(255),
                    confidence DECIMAL(5,4) DEFAULT 0.7,
                    transaction_count INT DEFAULT 1,
                    last_seen DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_raw_desc (raw_description(255)),
                    INDEX idx_normalized (normalized_name),
                    INDEX idx_category (category),
                    INDEX idx_subscription (is_subscription)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create contacts table for CRM/attendee matching
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    name_tokens VARCHAR(500),
                    email VARCHAR(255),
                    phone VARCHAR(50),
                    title VARCHAR(255),
                    company VARCHAR(255),
                    category VARCHAR(100),
                    notes TEXT,
                    is_vip BOOLEAN DEFAULT FALSE,
                    team VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_name (name),
                    INDEX idx_first_name (first_name),
                    INDEX idx_name_tokens (name_tokens(100)),
                    INDEX idx_company (company),
                    INDEX idx_category (category),
                    INDEX idx_team (team)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create merchant_learning table for auto-learning from corrections
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS merchant_learning (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    raw_description VARCHAR(500) NOT NULL,
                    learned_merchant VARCHAR(255),
                    learned_category VARCHAR(255),
                    learned_business_type VARCHAR(255),
                    source VARCHAR(100) DEFAULT 'user_correction',
                    confidence DECIMAL(5,4) DEFAULT 0.9,
                    learn_count INT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_raw_desc (raw_description(255)),
                    INDEX idx_learned_merchant (learned_merchant)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            self.conn.commit()

            # Run schema migrations to add columns that might be missing
            self._run_migrations()

            # Initialize ATLAS schema for relationship intelligence
            self._init_atlas_schema()

            print(f"✅ MySQL schema initialized", flush=True)

        except Exception as e:
            print(f"⚠️  Schema initialization failed: {e}", flush=True)
            self.conn.rollback()

    def _run_migrations(self):
        """Add any missing columns to existing tables"""
        try:
            cursor = self.conn.cursor()

            # Check and add missing columns to transactions table
            migrations = [
                ("deleted", "ALTER TABLE transactions ADD COLUMN deleted BOOLEAN DEFAULT FALSE"),
                ("deleted_by_user", "ALTER TABLE transactions ADD COLUMN deleted_by_user BOOLEAN DEFAULT FALSE"),
                ("receipt_url", "ALTER TABLE transactions ADD COLUMN receipt_url VARCHAR(1000)"),
                ("r2_url", "ALTER TABLE transactions ADD COLUMN r2_url VARCHAR(1000)"),
            ]

            # Get existing columns
            cursor.execute("SHOW COLUMNS FROM transactions")
            existing_cols = {row['Field'] for row in cursor.fetchall()}

            for col_name, alter_sql in migrations:
                if col_name not in existing_cols:
                    try:
                        cursor.execute(alter_sql)
                        print(f"  ✅ Added column: {col_name}")
                    except Exception as e:
                        if "Duplicate column" not in str(e):
                            print(f"  ⚠️  Migration for {col_name}: {e}")

            # Add missing indexes for performance
            index_migrations = [
                ("idx_deleted", "CREATE INDEX idx_deleted ON transactions(deleted)"),
                ("idx_submitted", "CREATE INDEX idx_submitted ON transactions(already_submitted)"),
            ]

            # Get existing indexes
            cursor.execute("SHOW INDEX FROM transactions")
            existing_indexes = {row['Key_name'] for row in cursor.fetchall()}

            for idx_name, create_sql in index_migrations:
                if idx_name not in existing_indexes:
                    try:
                        cursor.execute(create_sql)
                        print(f"  ✅ Added index: {idx_name}")
                    except Exception as e:
                        if "Duplicate key name" not in str(e):
                            print(f"  ⚠️  Index migration for {idx_name}: {e}")

            self.conn.commit()
        except Exception as e:
            print(f"⚠️  Migrations error: {e}", flush=True)

    def _init_atlas_schema(self):
        """Initialize ATLAS Relationship Intelligence schema"""
        if not self.use_mysql or not self.conn:
            return

        try:
            cursor = self.conn.cursor()

            # Extend contacts table with ATLAS fields (add missing columns)
            atlas_contact_columns = [
                ("display_name", "VARCHAR(255)"),
                ("nickname", "VARCHAR(100)"),
                ("photo_url", "VARCHAR(500)"),
                ("linkedin_url", "VARCHAR(500)"),
                ("twitter_handle", "VARCHAR(100)"),
                ("birthday", "DATE"),
                ("relationship_type", "VARCHAR(100)"),  # friend, colleague, family, client, vendor
                ("relationship_strength", "DECIMAL(3,2) DEFAULT 0.5"),  # 0-1 score
                ("touch_frequency_days", "INT DEFAULT 30"),  # desired contact frequency
                ("last_touch_date", "DATE"),
                ("next_touch_date", "DATE"),
                ("total_interactions", "INT DEFAULT 0"),
                ("source", "VARCHAR(100)"),  # apple, google, linkedin, manual
                ("source_id", "VARCHAR(255)"),  # external ID from source
                ("google_resource_name", "VARCHAR(255)"),  # Google People API resource
                ("apple_contact_id", "VARCHAR(255)"),
                ("merged_from", "TEXT"),  # JSON array of merged contact IDs
                ("tags", "TEXT"),  # JSON array of tags
                ("context", "TEXT"),  # how you know them
                ("priority_score", "DECIMAL(5,2) DEFAULT 0"),
            ]

            cursor.execute("SHOW COLUMNS FROM contacts")
            existing_cols = {row['Field'] for row in cursor.fetchall()}

            for col_name, col_def in atlas_contact_columns:
                if col_name not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE contacts ADD COLUMN {col_name} {col_def}")
                    except Exception as e:
                        if "Duplicate column" not in str(e):
                            print(f"  ⚠️  Contact column {col_name}: {e}")

            # Create contact_emails table (multiple emails per contact)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_emails (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    email_type VARCHAR(50) DEFAULT 'personal',
                    is_primary BOOLEAN DEFAULT FALSE,
                    verified BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    INDEX idx_email (email),
                    UNIQUE KEY unique_contact_email (contact_id, email),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create contact_phones table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_phones (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT NOT NULL,
                    phone VARCHAR(50) NOT NULL,
                    phone_type VARCHAR(50) DEFAULT 'mobile',
                    is_primary BOOLEAN DEFAULT FALSE,
                    normalized VARCHAR(20),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    INDEX idx_phone (phone),
                    INDEX idx_normalized (normalized),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create contact_addresses table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_addresses (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT NOT NULL,
                    address_type VARCHAR(50) DEFAULT 'home',
                    street VARCHAR(500),
                    city VARCHAR(100),
                    state VARCHAR(100),
                    postal_code VARCHAR(20),
                    country VARCHAR(100),
                    formatted VARCHAR(1000),
                    is_primary BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create interactions table (all touchpoints)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    interaction_type VARCHAR(100) NOT NULL,
                    channel VARCHAR(50),
                    occurred_at DATETIME NOT NULL,
                    content TEXT,
                    summary VARCHAR(500),
                    sentiment VARCHAR(20),
                    is_outgoing BOOLEAN DEFAULT TRUE,
                    duration_minutes INT,
                    location VARCHAR(255),
                    attendees TEXT,
                    expense_id INT,
                    calendar_event_id INT,
                    email_thread_id INT,
                    external_id VARCHAR(255),
                    source VARCHAR(100),
                    ai_summary TEXT,
                    ai_action_items TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_type (interaction_type),
                    INDEX idx_occurred (occurred_at),
                    INDEX idx_channel (channel),
                    INDEX idx_expense (expense_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create interaction_contacts junction table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS interaction_contacts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    interaction_id INT NOT NULL,
                    contact_id INT NOT NULL,
                    role VARCHAR(50) DEFAULT 'participant',
                    INDEX idx_interaction (interaction_id),
                    INDEX idx_contact (contact_id),
                    UNIQUE KEY unique_interaction_contact (interaction_id, contact_id),
                    FOREIGN KEY (interaction_id) REFERENCES interactions(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create calendar_events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    google_event_id VARCHAR(255),
                    calendar_id VARCHAR(255),
                    title VARCHAR(500) NOT NULL,
                    description TEXT,
                    location VARCHAR(500),
                    start_time DATETIME NOT NULL,
                    end_time DATETIME,
                    all_day BOOLEAN DEFAULT FALSE,
                    status VARCHAR(50),
                    attendees TEXT,
                    organizer_email VARCHAR(255),
                    recurring_event_id VARCHAR(255),
                    conference_url VARCHAR(500),
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_google_event (google_event_id),
                    INDEX idx_start (start_time),
                    INDEX idx_calendar (calendar_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create email_threads table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_threads (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    gmail_thread_id VARCHAR(255) NOT NULL,
                    gmail_account VARCHAR(255),
                    subject VARCHAR(500),
                    snippet TEXT,
                    message_count INT DEFAULT 1,
                    last_message_at DATETIME,
                    labels TEXT,
                    is_read BOOLEAN DEFAULT TRUE,
                    is_starred BOOLEAN DEFAULT FALSE,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_thread (gmail_thread_id, gmail_account),
                    INDEX idx_thread (gmail_thread_id),
                    INDEX idx_account (gmail_account),
                    INDEX idx_last_message (last_message_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create email_messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    thread_id INT,
                    gmail_message_id VARCHAR(255) NOT NULL,
                    gmail_account VARCHAR(255),
                    from_email VARCHAR(255),
                    from_name VARCHAR(255),
                    to_emails TEXT,
                    cc_emails TEXT,
                    subject VARCHAR(500),
                    snippet TEXT,
                    body_text TEXT,
                    body_html MEDIUMTEXT,
                    sent_at DATETIME,
                    is_outgoing BOOLEAN DEFAULT FALSE,
                    has_attachments BOOLEAN DEFAULT FALSE,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_message (gmail_message_id, gmail_account),
                    INDEX idx_thread (thread_id),
                    INDEX idx_message (gmail_message_id),
                    INDEX idx_from (from_email),
                    INDEX idx_sent (sent_at),
                    FOREIGN KEY (thread_id) REFERENCES email_threads(id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create reminders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT,
                    reminder_type VARCHAR(100) NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    description TEXT,
                    due_date DATE NOT NULL,
                    due_time TIME,
                    is_recurring BOOLEAN DEFAULT FALSE,
                    recurrence_pattern VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'pending',
                    priority VARCHAR(20) DEFAULT 'normal',
                    snoozed_until DATETIME,
                    completed_at DATETIME,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    INDEX idx_due (due_date),
                    INDEX idx_status (status),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create contact_photos table (for face recognition)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_photos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT NOT NULL,
                    photo_url VARCHAR(1000),
                    photo_data MEDIUMBLOB,
                    is_primary BOOLEAN DEFAULT FALSE,
                    source VARCHAR(100),
                    quality_score DECIMAL(3,2),
                    has_face_encoding BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    INDEX idx_primary (is_primary),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create face_encodings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS face_encodings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT NOT NULL,
                    photo_id INT,
                    encoding BLOB NOT NULL,
                    confidence DECIMAL(3,2) DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    INDEX idx_photo (photo_id),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                    FOREIGN KEY (photo_id) REFERENCES contact_photos(id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create enrichments table (cached external data)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_enrichments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT NOT NULL,
                    enrichment_type VARCHAR(100) NOT NULL,
                    source VARCHAR(100) NOT NULL,
                    data JSON,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    INDEX idx_contact (contact_id),
                    INDEX idx_type (enrichment_type),
                    UNIQUE KEY unique_enrichment (contact_id, enrichment_type, source),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create activity_feed table (denormalized timeline)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_feed (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT,
                    activity_type VARCHAR(100) NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    description TEXT,
                    occurred_at DATETIME NOT NULL,
                    metadata JSON,
                    source_type VARCHAR(50),
                    source_id INT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    INDEX idx_type (activity_type),
                    INDEX idx_occurred (occurred_at),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create contact_expense_links table (link contacts to expenses)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_expense_links (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    contact_id INT NOT NULL,
                    transaction_index INT NOT NULL,
                    link_type VARCHAR(50) DEFAULT 'attendee',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_contact (contact_id),
                    INDEX idx_transaction (transaction_index),
                    UNIQUE KEY unique_link (contact_id, transaction_index),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # Create imessage_sync_state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS imessage_sync_state (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    last_rowid BIGINT DEFAULT 0,
                    last_sync DATETIME,
                    messages_synced INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            self.conn.commit()
            print(f"  ✅ ATLAS schema initialized", flush=True)

        except Exception as e:
            print(f"⚠️  ATLAS schema initialization failed: {e}", flush=True)
            self.conn.rollback()

    def get_all_transactions(self) -> pd.DataFrame:
        """Get all transactions as DataFrame (with UI-friendly column names)"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        query = "SELECT * FROM transactions ORDER BY _index"
        df = pd.read_sql_query(query, self.conn)

        # Map database columns to UI-friendly names
        column_map = {
            '_index': '_index',
            'chase_date': 'Chase Date',
            'chase_description': 'Chase Description',
            'chase_amount': 'Chase Amount',
            'chase_category': 'Chase Category',
            'chase_type': 'Chase Type',
            'receipt_file': 'Receipt File',
            'business_type': 'Business Type',
            'notes': 'Notes',
            'ai_note': 'AI Note',
            'ai_confidence': 'AI Confidence',
            'ai_receipt_merchant': 'ai_receipt_merchant',
            'ai_receipt_date': 'ai_receipt_date',
            'ai_receipt_total': 'ai_receipt_total',
            'review_status': 'Review Status',
            'category': 'Category',
            'report_id': 'Report ID',
            'source': 'Source',
            'mi_merchant': 'MI Merchant',
            'mi_category': 'MI Category',
            'mi_description': 'MI Description',
            'mi_confidence': 'MI Confidence',
            'mi_is_subscription': 'MI Is Subscription',
            'mi_subscription_name': 'MI Subscription Name',
            'mi_processed_at': 'MI Processed At',
            'is_refund': 'Is Refund',
            'already_submitted': 'Already Submitted',
            'deleted': 'deleted',
            'deleted_by_user': 'deleted_by_user',
            'receipt_url': 'Receipt URL',
            'r2_url': 'R2 URL'
        }

        df = df.rename(columns=column_map)
        df = df.drop(columns=['id', 'created_at', 'updated_at'], errors='ignore')

        # Ensure _index is integer type for comparison operations
        if '_index' in df.columns:
            df['_index'] = pd.to_numeric(df['_index'], errors='coerce').fillna(0).astype(int)

        return df

    def get_transaction_by_index(self, index: int) -> Optional[Dict]:
        """Get single transaction by _index"""
        if not self.use_mysql:
            raise RuntimeError("MySQL not available")

        self.ensure_connection()
        cursor = self.conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT * FROM transactions WHERE _index = %s", (index,))
        result = cursor.fetchone()
        cursor.close()
        return result

    def update_transaction(self, index: int, patch: Dict[str, Any]) -> bool:
        """Update transaction with patch data"""
        if not self.use_mysql:
            raise RuntimeError("MySQL not available")

        self.ensure_connection()

        # Map user-facing column names to database columns
        column_map = {
            'Chase Date': 'chase_date',
            'Chase Description': 'chase_description',
            'Chase Amount': 'chase_amount',
            'Chase Category': 'chase_category',
            'Chase Type': 'chase_type',
            'Receipt File': 'receipt_file',
            'Business Type': 'business_type',
            'Notes': 'notes',
            'AI Note': 'ai_note',
            'AI Confidence': 'ai_confidence',
            'ai_receipt_merchant': 'ai_receipt_merchant',
            'ai_receipt_date': 'ai_receipt_date',
            'ai_receipt_total': 'ai_receipt_total',
            'Review Status': 'review_status',
            'Category': 'category',
            'Report ID': 'report_id',
            'Source': 'source'
        }

        set_clauses = []
        values = []

        for key, value in patch.items():
            db_col = column_map.get(key, key.lower().replace(' ', '_'))
            if db_col == '_index':
                continue
            set_clauses.append(f"{db_col} = %s")
            values.append(value)

        if not set_clauses:
            return False

        values.append(index)
        sql = f"UPDATE transactions SET {', '.join(set_clauses)} WHERE _index = %s"

        try:
            cursor = self.conn.cursor()
            cursor.execute(sql, values)
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ Update failed: {e}", flush=True)
            self.conn.rollback()
            return False

    def search_transactions(
        self,
        business_type: Optional[str] = None,
        has_receipt: Optional[bool] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        review_status: Optional[str] = None
    ) -> pd.DataFrame:
        """Search transactions with filters"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        where_clauses = []
        params = []

        if business_type:
            where_clauses.append("business_type = %s")
            params.append(business_type)

        if has_receipt is not None:
            if has_receipt:
                where_clauses.append("receipt_file IS NOT NULL AND receipt_file != ''")
            else:
                where_clauses.append("(receipt_file IS NULL OR receipt_file = '')")

        if date_from:
            where_clauses.append("chase_date >= %s")
            params.append(date_from)

        if date_to:
            where_clauses.append("chase_date <= %s")
            params.append(date_to)

        if review_status:
            where_clauses.append("review_status = %s")
            params.append(review_status)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        query = f"SELECT * FROM transactions WHERE {where_sql} ORDER BY _index"

        df = pd.read_sql_query(query, self.conn, params=params)
        return df

    def get_receipt_metadata(self, filename: str) -> Optional[Dict]:
        """Get cached receipt metadata"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM receipt_metadata WHERE filename = %s", (filename,))
        return cursor.fetchone()

    def cache_receipt_metadata(
        self,
        filename: str,
        merchant: str,
        date: str,
        amount: float,
        raw_text: str = ""
    ) -> bool:
        """Cache receipt metadata for fast matching"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        sql = """
            INSERT INTO receipt_metadata (filename, merchant, date, amount, raw_text)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                merchant = VALUES(merchant),
                date = VALUES(date),
                amount = VALUES(amount),
                raw_text = VALUES(raw_text)
        """

        try:
            cursor = self.conn.cursor()
            cursor.execute(sql, (filename, merchant, date, amount, raw_text))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Cache failed for {filename}: {e}", flush=True)
            self.conn.rollback()
            return False

    def get_all_receipt_metadata(self) -> List[Dict]:
        """Get all cached receipt metadata"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM receipt_metadata ORDER BY filename")
        return cursor.fetchall()

    def get_analytics(self) -> Dict[str, Any]:
        """Get analytics/stats from database"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM transactions")
        total = cursor.fetchone()['count']

        cursor.execute("""
            SELECT COUNT(*) as count FROM transactions
            WHERE receipt_file IS NOT NULL AND receipt_file != ''
        """)
        with_receipts = cursor.fetchone()['count']

        cursor.execute("""
            SELECT business_type, COUNT(*) as count
            FROM transactions
            WHERE business_type IS NOT NULL AND business_type != ''
            GROUP BY business_type
            ORDER BY count DESC
        """)
        by_business = {row['business_type']: row['count'] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT COUNT(*) as count FROM transactions
            WHERE ai_confidence > 0
        """)
        ai_matched = cursor.fetchone()['count']

        cursor.execute("""
            SELECT review_status, COUNT(*) as count
            FROM transactions
            WHERE review_status IS NOT NULL AND review_status != ''
            GROUP BY review_status
        """)
        by_status = {row['review_status']: row['count'] for row in cursor.fetchall()}

        return {
            'total_transactions': total,
            'with_receipts': with_receipts,
            'without_receipts': total - with_receipts,
            'by_business_type': by_business,
            'ai_matched': ai_matched,
            'by_review_status': by_status
        }

    def export_to_csv(self, output_path: str) -> bool:
        """Export database to CSV format"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        try:
            df = self.get_all_transactions()
            df.to_csv(output_path, index=False)
            print(f"✅ Exported to CSV: {output_path}", flush=True)
            return True
        except Exception as e:
            print(f"❌ CSV export failed: {e}", flush=True)
            return False

    def get_missing_receipts(self, limit: int = 100) -> List[Dict]:
        """Get transactions without receipts (for batch matching)"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM transactions
            WHERE (receipt_file IS NULL OR receipt_file = '')
            AND chase_date IS NOT NULL
            AND chase_description IS NOT NULL
            ORDER BY chase_date DESC
            LIMIT %s
        """, (limit,))
        return cursor.fetchall()

    def get_statistics(self) -> Dict[str, Any]:
        """Get detailed statistics for dashboard"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        stats = {}

        cursor.execute("""
            SELECT
                business_type,
                SUM(ABS(chase_amount)) as total,
                COUNT(*) as count
            FROM transactions
            WHERE business_type IS NOT NULL
            GROUP BY business_type
            ORDER BY total DESC
        """)
        stats['spending_by_business'] = [
            {'business': row['business_type'], 'total': float(row['total']), 'count': row['count']}
            for row in cursor.fetchall()
        ]

        cursor.execute("""
            SELECT
                DATE_FORMAT(chase_date, '%Y-%m') as month,
                SUM(ABS(chase_amount)) as total
            FROM transactions
            WHERE chase_date IS NOT NULL
            GROUP BY month
            ORDER BY month DESC
            LIMIT 12
        """)
        stats['monthly_spending'] = [
            {'month': row['month'], 'total': float(row['total'])}
            for row in cursor.fetchall()
        ]

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN receipt_file IS NOT NULL AND receipt_file != '' THEN 1 ELSE 0 END) as matched
            FROM transactions
        """)
        row = cursor.fetchone()
        total = row['total']
        matched = row['matched']
        stats['match_rate'] = {
            'total': total,
            'matched': matched,
            'percentage': round((matched / total * 100), 1) if total > 0 else 0
        }

        return stats

    def get_reportable_expenses(
        self,
        business_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[Dict]:
        """Get expenses that can be added to reports (not already submitted)"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        where_clauses = [
            "(report_id IS NULL OR report_id = '')",
            "(already_submitted IS NULL OR already_submitted = '' OR already_submitted NOT IN ('yes', '1', 'true'))"
        ]
        params = []

        if business_type:
            where_clauses.append("business_type = %s")
            params.append(business_type)

        if date_from:
            where_clauses.append("chase_date >= %s")
            params.append(date_from)

        if date_to:
            where_clauses.append("chase_date <= %s")
            params.append(date_to)

        where_sql = " AND ".join(where_clauses)
        query = f"""
            SELECT * FROM transactions
            WHERE {where_sql}
            ORDER BY chase_date DESC
        """

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def submit_report(
        self,
        report_name: str,
        business_type: str,
        expense_indexes: List[int]
    ) -> str:
        """Create a report and assign report_id to selected expenses"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        business_abbrev = business_type.replace(" ", "")[:3].upper()
        report_id = f"REPORT-{business_abbrev}-{timestamp}"

        cursor = self.conn.cursor()
        placeholders = ",".join(["%s"] * len(expense_indexes))
        cursor.execute(f"""
            SELECT
                COUNT(*) as count,
                SUM(ABS(chase_amount)) as total
            FROM transactions
            WHERE _index IN ({placeholders})
        """, expense_indexes)

        row = cursor.fetchone()
        expense_count = row['count']
        total_amount = float(row['total'] or 0)

        cursor.execute("""
            INSERT INTO reports (report_id, report_name, business_type, expense_count, total_amount)
            VALUES (%s, %s, %s, %s, %s)
        """, (report_id, report_name, business_type, expense_count, total_amount))

        cursor.execute(f"""
            UPDATE transactions
            SET report_id = %s, already_submitted = 'yes'
            WHERE _index IN ({placeholders})
        """, [report_id] + expense_indexes)

        self.conn.commit()

        print(f"✅ Report created: {report_id} ({expense_count} expenses, ${total_amount:.2f})", flush=True)

        return report_id

    def get_all_reports(self) -> List[Dict]:
        """Get all submitted reports with metadata"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM reports ORDER BY created_at DESC")
        return cursor.fetchall()

    def get_report(self, report_id: str) -> Optional[Dict]:
        """Get a single report by ID"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE report_id = %s", (report_id,))
        return cursor.fetchone()

    def get_report_expenses(self, report_id: str) -> List[Dict]:
        """Get all expenses for a specific report"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM transactions
            WHERE report_id = %s
            ORDER BY chase_date DESC
        """, (report_id,))
        return cursor.fetchall()

    def delete_report(self, report_id: str) -> bool:
        """Delete a report and unassign all expenses from it"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        try:
            cursor = self.conn.cursor()

            cursor.execute("SELECT * FROM reports WHERE report_id = %s", (report_id,))
            report = cursor.fetchone()

            if not report:
                print(f"⚠️  Report {report_id} not found", flush=True)
                return False

            cursor.execute("""
                UPDATE transactions
                SET report_id = NULL, already_submitted = NULL
                WHERE report_id = %s
            """, (report_id,))

            affected_count = cursor.rowcount

            cursor.execute("DELETE FROM reports WHERE report_id = %s", (report_id,))

            self.conn.commit()

            print(f"✅ Report {report_id} deleted. {affected_count} expenses returned to available pool.", flush=True)
            return True

        except Exception as e:
            print(f"❌ Failed to delete report {report_id}: {e}", flush=True)
            self.conn.rollback()
            return False

    # =========================================================================
    # MERCHANT INTELLIGENCE METHODS
    # =========================================================================

    def get_all_merchants(self) -> Dict[str, Dict]:
        """Get all merchants as dict keyed by raw_description (uppercase)"""
        if not self.use_mysql or not self.conn:
            return {}

        self.ensure_connection()
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT raw_description, normalized_name, category,
                       is_subscription, avg_amount, primary_business_type
                FROM merchants
            """)
            merchants = {}
            for row in cursor.fetchall():
                merchants[row['raw_description'].upper()] = {
                    'normalized': row['normalized_name'],
                    'category': row['category'],
                    'is_subscription': bool(row['is_subscription']),
                    'avg_amount': float(row['avg_amount']) if row['avg_amount'] else None,
                    'business_type': row['primary_business_type']
                }
            return merchants
        except Exception as e:
            print(f"⚠️ Error loading merchants: {e}")
            return {}
        finally:
            cursor.close()

    def upsert_merchant(
        self,
        raw_description: str,
        normalized_name: str,
        category: str = None,
        is_subscription: bool = False,
        subscription_name: str = None,
        avg_amount: float = None,
        primary_business_type: str = None,
        confidence: float = 0.7
    ) -> bool:
        """Insert or update a merchant in the knowledge base"""
        if not self.use_mysql or not self.conn:
            return False

        self.ensure_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO merchants (
                    raw_description, normalized_name, category, is_subscription,
                    subscription_name, avg_amount, primary_business_type, confidence,
                    transaction_count, last_seen
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, CURDATE())
                ON DUPLICATE KEY UPDATE
                    normalized_name = VALUES(normalized_name),
                    category = COALESCE(VALUES(category), category),
                    is_subscription = VALUES(is_subscription),
                    subscription_name = COALESCE(VALUES(subscription_name), subscription_name),
                    avg_amount = COALESCE(VALUES(avg_amount), avg_amount),
                    primary_business_type = COALESCE(VALUES(primary_business_type), primary_business_type),
                    confidence = GREATEST(confidence, VALUES(confidence)),
                    transaction_count = transaction_count + 1,
                    last_seen = CURDATE()
            """, (raw_description, normalized_name, category, is_subscription,
                  subscription_name, avg_amount, primary_business_type, confidence))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Merchant upsert error: {e}")
            self.conn.rollback()
            return False

    def learn_merchant_correction(
        self,
        raw_description: str,
        learned_merchant: str = None,
        learned_category: str = None,
        learned_business_type: str = None
    ) -> bool:
        """Record a user correction for merchant learning"""
        if not self.use_mysql or not self.conn:
            return False

        self.ensure_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO merchant_learning (
                    raw_description, learned_merchant, learned_category,
                    learned_business_type, source, confidence, learn_count
                ) VALUES (%s, %s, %s, %s, 'user_correction', 0.95, 1)
                ON DUPLICATE KEY UPDATE
                    learned_merchant = COALESCE(VALUES(learned_merchant), learned_merchant),
                    learned_category = COALESCE(VALUES(learned_category), learned_category),
                    learned_business_type = COALESCE(VALUES(learned_business_type), learned_business_type),
                    learn_count = learn_count + 1,
                    confidence = LEAST(0.99, confidence + 0.01)
            """, (raw_description, learned_merchant, learned_category, learned_business_type))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Merchant learning error: {e}")
            self.conn.rollback()
            return False

    def get_learned_merchant(self, raw_description: str) -> Optional[Dict]:
        """Get learned merchant info if it exists"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT learned_merchant, learned_category, learned_business_type, confidence
                FROM merchant_learning
                WHERE raw_description = %s
            """, (raw_description,))
            result = cursor.fetchone()
            cursor.close()
            return result
        except:
            return None

    # =========================================================================
    # CONTACTS/CRM METHODS
    # =========================================================================

    def search_contacts(self, query: str, limit: int = 5) -> List[Dict]:
        """Search contacts by name for note generation"""
        if not self.use_mysql or not self.conn or not query or len(query) < 2:
            return []

        self.ensure_connection()
        try:
            cursor = self.conn.cursor()
            query_lower = query.lower()
            cursor.execute("""
                SELECT name, title, company, category, team
                FROM contacts
                WHERE name_tokens LIKE %s OR name LIKE %s
                ORDER BY
                    CASE WHEN first_name = %s THEN 1
                         WHEN name LIKE %s THEN 2
                         ELSE 3 END
                LIMIT %s
            """, (f'%{query_lower}%', f'%{query}%', query, f'{query}%', limit))
            results = [dict(r) for r in cursor.fetchall()]
            cursor.close()
            return results
        except Exception as e:
            print(f"⚠️ Contact search error: {e}")
            return []

    def upsert_contact(
        self,
        name: str,
        email: str = None,
        phone: str = None,
        title: str = None,
        company: str = None,
        category: str = None,
        team: str = None,
        is_vip: bool = False,
        notes: str = None
    ) -> bool:
        """Insert or update a contact"""
        if not self.use_mysql or not self.conn:
            return False

        # Parse first/last name
        name_parts = name.strip().split()
        first_name = name_parts[0] if name_parts else ''
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        name_tokens = name.lower()

        self.ensure_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO contacts (
                    name, first_name, last_name, name_tokens, email, phone,
                    title, company, category, team, is_vip, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    email = COALESCE(VALUES(email), email),
                    phone = COALESCE(VALUES(phone), phone),
                    title = COALESCE(VALUES(title), title),
                    company = COALESCE(VALUES(company), company),
                    category = COALESCE(VALUES(category), category),
                    team = COALESCE(VALUES(team), team),
                    is_vip = VALUES(is_vip),
                    notes = COALESCE(VALUES(notes), notes)
            """, (name, first_name, last_name, name_tokens, email, phone,
                  title, company, category, team, is_vip, notes))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Contact upsert error: {e}")
            self.conn.rollback()
            return False

    def get_all_contacts(self) -> List[Dict]:
        """Get all contacts"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM contacts ORDER BY name")
            results = cursor.fetchall()
            cursor.close()
            return list(results)
        except:
            return []

    def seed_default_contacts(self):
        """Seed default VIP contacts from contacts_engine.py"""
        VIP_PEOPLE = [
            ("Brian Kaplan", "mcr", True),
            ("Patrick Humes", "mcr", True),
            ("Barry Stephenson", "mcr", True),
            ("Paige", "mcr", True),
            ("Jason Ross", "downhome", True),
            ("Tim Staples", "downhome", True),
            ("Joel Bergvall", "downhome", True),
            ("Kevin Sabbe", "downhome", True),
            ("Andrew Cohen", "downhome", True),
            ("Celeste Stange", "downhome", True),
            ("Tom May", "downhome", True),
            ("Stephen Person", "industry", True),
            ("Tom Etzel", "industry", True),
            ("Cindy Mabe", "industry", True),
            ("Ken Robold", "industry", True),
            ("Taylor Lindsey", "industry", True),
            ("Ben Kline", "industry", True),
            ("Nick Barnes", "industry", True),
            ("Copeland Isaacson", "industry", False),
            ("Margarette Hart", "industry", False),
            ("Sarah Moore", "industry", False),
            ("Shanna Strassberg", "industry", False),
            ("Sarah Hilly", "industry", False),
            ("Sarah DeMarco", "industry", False),
            ("Dawn Gates", "industry", False),
            ("Scott Siman", "industry", True),
        ]
        count = 0
        for name, team, is_vip in VIP_PEOPLE:
            if self.upsert_contact(name=name, team=team, is_vip=is_vip):
                count += 1
        print(f"✅ Seeded {count} default contacts")
        return count


    # =========================================================================
    # ATLAS RELATIONSHIP INTELLIGENCE METHODS
    # =========================================================================

    def atlas_get_contacts(
        self,
        limit: int = 100,
        offset: int = 0,
        search: str = None,
        relationship_type: str = None,
        touch_needed: bool = False,
        sort_by: str = 'name'
    ) -> Dict[str, Any]:
        """Get contacts with ATLAS relationship data"""
        if not self.use_mysql or not self.conn:
            return {"items": [], "total": 0}

        self.ensure_connection()
        cursor = self.conn.cursor()

        where_clauses = ["1=1"]
        params = []

        if search:
            where_clauses.append("(name LIKE %s OR email LIKE %s OR company LIKE %s)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        if relationship_type:
            where_clauses.append("relationship_type = %s")
            params.append(relationship_type)

        if touch_needed:
            where_clauses.append("(next_touch_date IS NULL OR next_touch_date <= CURDATE())")

        where_sql = " AND ".join(where_clauses)

        # Get total count
        cursor.execute(f"SELECT COUNT(*) as total FROM contacts WHERE {where_sql}", params)
        total = cursor.fetchone()['total']

        # Get paginated results
        order_map = {
            'name': 'name ASC',
            'last_touch': 'last_touch_date DESC',
            'priority': 'priority_score DESC',
            'company': 'company ASC',
            'relationship': 'relationship_strength DESC'
        }
        order_by = order_map.get(sort_by, 'name ASC')

        cursor.execute(f"""
            SELECT c.*,
                (SELECT COUNT(*) FROM interaction_contacts ic
                 JOIN interactions i ON ic.interaction_id = i.id
                 WHERE ic.contact_id = c.id) as interaction_count,
                (SELECT COUNT(*) FROM contact_expense_links cel
                 WHERE cel.contact_id = c.id) as expense_count
            FROM contacts c
            WHERE {where_sql}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
        """, params + [limit, offset])

        items = [dict(r) for r in cursor.fetchall()]
        cursor.close()

        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def atlas_get_contact(self, contact_id: int) -> Optional[Dict]:
        """Get single contact with full ATLAS data"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM contacts WHERE id = %s", (contact_id,))
        contact = cursor.fetchone()

        if not contact:
            cursor.close()
            return None

        contact = dict(contact)

        # Get emails
        cursor.execute("SELECT * FROM contact_emails WHERE contact_id = %s", (contact_id,))
        contact['emails'] = [dict(r) for r in cursor.fetchall()]

        # Get phones
        cursor.execute("SELECT * FROM contact_phones WHERE contact_id = %s", (contact_id,))
        contact['phones'] = [dict(r) for r in cursor.fetchall()]

        # Get addresses
        cursor.execute("SELECT * FROM contact_addresses WHERE contact_id = %s", (contact_id,))
        contact['addresses'] = [dict(r) for r in cursor.fetchall()]

        # Get recent interactions
        cursor.execute("""
            SELECT i.* FROM interactions i
            JOIN interaction_contacts ic ON i.id = ic.interaction_id
            WHERE ic.contact_id = %s
            ORDER BY i.occurred_at DESC
            LIMIT 10
        """, (contact_id,))
        contact['recent_interactions'] = [dict(r) for r in cursor.fetchall()]

        # Get linked expenses
        cursor.execute("""
            SELECT t.*, cel.link_type, cel.notes as link_notes
            FROM transactions t
            JOIN contact_expense_links cel ON t._index = cel.transaction_index
            WHERE cel.contact_id = %s
            ORDER BY t.chase_date DESC
            LIMIT 10
        """, (contact_id,))
        contact['linked_expenses'] = [dict(r) for r in cursor.fetchall()]

        cursor.close()
        return contact

    def atlas_create_contact(self, data: Dict) -> Optional[int]:
        """Create a new ATLAS contact"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Parse name
        name = data.get('name', '')
        name_parts = name.strip().split()
        first_name = name_parts[0] if name_parts else ''
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''

        try:
            cursor.execute("""
                INSERT INTO contacts (
                    name, first_name, last_name, name_tokens, email, phone, title, company,
                    category, team, is_vip, notes, display_name, nickname, photo_url,
                    linkedin_url, twitter_handle, birthday, relationship_type,
                    relationship_strength, touch_frequency_days, source, context, tags
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                name, first_name, last_name, name.lower(),
                data.get('email'), data.get('phone'), data.get('title'),
                data.get('company'), data.get('category'), data.get('team'),
                data.get('is_vip', False), data.get('notes'),
                data.get('display_name', name), data.get('nickname'),
                data.get('photo_url'), data.get('linkedin_url'),
                data.get('twitter_handle'), data.get('birthday'),
                data.get('relationship_type', 'professional'),
                data.get('relationship_strength', 0.5),
                data.get('touch_frequency_days', 30),
                data.get('source', 'manual'), data.get('context'),
                json.dumps(data.get('tags', [])) if data.get('tags') else None
            ))
            contact_id = cursor.lastrowid

            # Add multiple emails if provided
            if data.get('emails'):
                for i, email_data in enumerate(data['emails']):
                    cursor.execute("""
                        INSERT INTO contact_emails (contact_id, email, email_type, is_primary)
                        VALUES (%s, %s, %s, %s)
                    """, (contact_id, email_data.get('email'), email_data.get('type', 'personal'), i == 0))

            # Add multiple phones if provided
            if data.get('phones'):
                for i, phone_data in enumerate(data['phones']):
                    cursor.execute("""
                        INSERT INTO contact_phones (contact_id, phone, phone_type, is_primary)
                        VALUES (%s, %s, %s, %s)
                    """, (contact_id, phone_data.get('phone'), phone_data.get('type', 'mobile'), i == 0))

            self.conn.commit()
            cursor.close()
            return contact_id

        except Exception as e:
            print(f"❌ Create contact error: {e}")
            self.conn.rollback()
            cursor.close()
            return None

    def atlas_update_contact(self, contact_id: int, data: Dict) -> bool:
        """Update an ATLAS contact"""
        if not self.use_mysql or not self.conn:
            return False

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Build update statement
        allowed_fields = [
            'name', 'first_name', 'last_name', 'email', 'phone', 'title', 'company',
            'category', 'team', 'is_vip', 'notes', 'display_name', 'nickname',
            'photo_url', 'linkedin_url', 'twitter_handle', 'birthday',
            'relationship_type', 'relationship_strength', 'touch_frequency_days',
            'context', 'tags', 'last_touch_date', 'next_touch_date'
        ]

        set_clauses = []
        params = []
        for field in allowed_fields:
            if field in data:
                set_clauses.append(f"{field} = %s")
                value = data[field]
                if field == 'tags' and isinstance(value, list):
                    value = json.dumps(value)
                params.append(value)

        if not set_clauses:
            return False

        params.append(contact_id)

        try:
            cursor.execute(f"""
                UPDATE contacts SET {', '.join(set_clauses)} WHERE id = %s
            """, params)
            self.conn.commit()
            cursor.close()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ Update contact error: {e}")
            self.conn.rollback()
            cursor.close()
            return False

    def atlas_create_interaction(self, data: Dict) -> Optional[int]:
        """Create a new interaction"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO interactions (
                    interaction_type, channel, occurred_at, content, summary,
                    sentiment, is_outgoing, duration_minutes, location, attendees,
                    expense_id, source, ai_summary
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.get('interaction_type', 'note'),
                data.get('channel'),
                data.get('occurred_at', datetime.now()),
                data.get('content'),
                data.get('summary'),
                data.get('sentiment'),
                data.get('is_outgoing', True),
                data.get('duration_minutes'),
                data.get('location'),
                json.dumps(data.get('attendees', [])) if data.get('attendees') else None,
                data.get('expense_id'),
                data.get('source', 'manual'),
                data.get('ai_summary')
            ))
            interaction_id = cursor.lastrowid

            # Link contacts to interaction
            contact_ids = data.get('contact_ids', [])
            for contact_id in contact_ids:
                cursor.execute("""
                    INSERT INTO interaction_contacts (interaction_id, contact_id, role)
                    VALUES (%s, %s, %s)
                """, (interaction_id, contact_id, 'participant'))

                # Update contact's last touch
                cursor.execute("""
                    UPDATE contacts SET
                        last_touch_date = %s,
                        total_interactions = total_interactions + 1,
                        next_touch_date = DATE_ADD(%s, INTERVAL touch_frequency_days DAY)
                    WHERE id = %s
                """, (data.get('occurred_at', datetime.now()),
                      data.get('occurred_at', datetime.now()), contact_id))

            self.conn.commit()
            cursor.close()
            return interaction_id

        except Exception as e:
            print(f"❌ Create interaction error: {e}")
            self.conn.rollback()
            cursor.close()
            return None

    def atlas_get_interactions(
        self,
        contact_id: int = None,
        interaction_type: str = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get interactions with optional filters"""
        if not self.use_mysql or not self.conn:
            return {"items": [], "total": 0}

        self.ensure_connection()
        cursor = self.conn.cursor()

        where_clauses = ["1=1"]
        params = []

        if contact_id:
            where_clauses.append("""
                i.id IN (SELECT interaction_id FROM interaction_contacts WHERE contact_id = %s)
            """)
            params.append(contact_id)

        if interaction_type:
            where_clauses.append("i.interaction_type = %s")
            params.append(interaction_type)

        where_sql = " AND ".join(where_clauses)

        cursor.execute(f"SELECT COUNT(*) as total FROM interactions i WHERE {where_sql}", params)
        total = cursor.fetchone()['total']

        cursor.execute(f"""
            SELECT i.*,
                GROUP_CONCAT(c.name) as contact_names
            FROM interactions i
            LEFT JOIN interaction_contacts ic ON i.id = ic.interaction_id
            LEFT JOIN contacts c ON ic.contact_id = c.id
            WHERE {where_sql}
            GROUP BY i.id
            ORDER BY i.occurred_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])

        items = [dict(r) for r in cursor.fetchall()]
        cursor.close()

        return {"items": items, "total": total}

    def atlas_get_touch_needed(self, limit: int = 20) -> List[Dict]:
        """Get contacts that need to be touched"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT c.*,
                DATEDIFF(CURDATE(), COALESCE(last_touch_date, DATE_SUB(CURDATE(), INTERVAL 365 DAY))) as days_since_touch,
                DATEDIFF(CURDATE(), next_touch_date) as days_overdue
            FROM contacts c
            WHERE next_touch_date IS NULL OR next_touch_date <= CURDATE()
            ORDER BY
                CASE WHEN is_vip THEN 0 ELSE 1 END,
                priority_score DESC,
                days_since_touch DESC
            LIMIT %s
        """, (limit,))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_get_contact_timeline(self, contact_id: int, limit: int = 50) -> List[Dict]:
        """Get unified timeline for a contact"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Combine interactions, emails, calendar events
        cursor.execute("""
            SELECT
                'interaction' as source_type,
                i.id as source_id,
                i.interaction_type as activity_type,
                COALESCE(i.summary, LEFT(i.content, 100)) as title,
                i.content as description,
                i.occurred_at,
                NULL as metadata
            FROM interactions i
            JOIN interaction_contacts ic ON i.id = ic.interaction_id
            WHERE ic.contact_id = %s

            UNION ALL

            SELECT
                'expense' as source_type,
                t._index as source_id,
                'expense' as activity_type,
                CONCAT('$', ABS(t.chase_amount), ' at ', COALESCE(t.mi_merchant, t.chase_description)) as title,
                t.ai_note as description,
                t.chase_date as occurred_at,
                NULL as metadata
            FROM transactions t
            JOIN contact_expense_links cel ON t._index = cel.transaction_index
            WHERE cel.contact_id = %s

            UNION ALL

            SELECT
                'calendar' as source_type,
                ce.id as source_id,
                'meeting' as activity_type,
                ce.title,
                ce.description,
                ce.start_time as occurred_at,
                JSON_OBJECT('location', ce.location, 'attendees', ce.attendees) as metadata
            FROM calendar_events ce
            WHERE ce.attendees LIKE CONCAT('%%', (SELECT email FROM contacts WHERE id = %s), '%%')

            ORDER BY occurred_at DESC
            LIMIT %s
        """, (contact_id, contact_id, contact_id, limit))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_link_expense_to_contact(self, contact_id: int, transaction_index: int, link_type: str = 'attendee', notes: str = None) -> bool:
        """Link an expense to a contact"""
        if not self.use_mysql or not self.conn:
            return False

        self.ensure_connection()
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO contact_expense_links (contact_id, transaction_index, link_type, notes)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE link_type = VALUES(link_type), notes = VALUES(notes)
            """, (contact_id, transaction_index, link_type, notes))
            self.conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"❌ Link expense error: {e}")
            self.conn.rollback()
            cursor.close()
            return False

    def atlas_get_relationship_digest(self) -> Dict[str, Any]:
        """Get relationship intelligence digest"""
        if not self.use_mysql or not self.conn:
            return {}

        self.ensure_connection()
        cursor = self.conn.cursor()

        digest = {}

        # Contacts needing attention
        cursor.execute("""
            SELECT COUNT(*) as count FROM contacts
            WHERE next_touch_date IS NULL OR next_touch_date <= CURDATE()
        """)
        digest['touch_needed_count'] = cursor.fetchone()['count']

        # VIP contacts needing touch
        cursor.execute("""
            SELECT COUNT(*) as count FROM contacts
            WHERE is_vip = TRUE AND (next_touch_date IS NULL OR next_touch_date <= CURDATE())
        """)
        digest['vip_touch_needed'] = cursor.fetchone()['count']

        # Recent interactions (last 7 days)
        cursor.execute("""
            SELECT COUNT(*) as count FROM interactions
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        digest['recent_interactions'] = cursor.fetchone()['count']

        # Contacts by relationship type
        cursor.execute("""
            SELECT relationship_type, COUNT(*) as count
            FROM contacts
            WHERE relationship_type IS NOT NULL
            GROUP BY relationship_type
        """)
        digest['by_relationship_type'] = {r['relationship_type']: r['count'] for r in cursor.fetchall()}

        # Top contacts by interaction count
        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url, COUNT(ic.id) as interaction_count
            FROM contacts c
            LEFT JOIN interaction_contacts ic ON c.id = ic.contact_id
            GROUP BY c.id
            ORDER BY interaction_count DESC
            LIMIT 10
        """)
        digest['most_active_contacts'] = [dict(r) for r in cursor.fetchall()]

        # Upcoming birthdays (next 30 days)
        cursor.execute("""
            SELECT id, name, birthday, photo_url
            FROM contacts
            WHERE birthday IS NOT NULL
            AND DAYOFYEAR(birthday) BETWEEN DAYOFYEAR(CURDATE()) AND DAYOFYEAR(CURDATE()) + 30
            ORDER BY DAYOFYEAR(birthday)
            LIMIT 10
        """)
        digest['upcoming_birthdays'] = [dict(r) for r in cursor.fetchall()]

        cursor.close()
        return digest

    def atlas_create_reminder(self, data: Dict) -> Optional[int]:
        """Create a reminder"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO reminders (
                    contact_id, reminder_type, title, description, due_date,
                    due_time, is_recurring, recurrence_pattern, priority
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.get('contact_id'),
                data.get('reminder_type', 'follow_up'),
                data.get('title'),
                data.get('description'),
                data.get('due_date'),
                data.get('due_time'),
                data.get('is_recurring', False),
                data.get('recurrence_pattern'),
                data.get('priority', 'normal')
            ))
            reminder_id = cursor.lastrowid
            self.conn.commit()
            cursor.close()
            return reminder_id
        except Exception as e:
            print(f"❌ Create reminder error: {e}")
            self.conn.rollback()
            cursor.close()
            return None

    def atlas_get_reminders(self, status: str = 'pending', limit: int = 20) -> List[Dict]:
        """Get reminders"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT r.*, c.name as contact_name, c.photo_url as contact_photo
            FROM reminders r
            LEFT JOIN contacts c ON r.contact_id = c.id
            WHERE r.status = %s
            ORDER BY r.due_date ASC, r.priority DESC
            LIMIT %s
        """, (status, limit))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_get_contact_expenses(self, contact_id: int, limit: int = 50) -> List[Dict]:
        """Get all expenses linked to a contact"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT t.*, cel.link_type, cel.notes as link_notes, cel.created_at as linked_at
            FROM transactions t
            JOIN contact_expense_links cel ON t._index = cel.transaction_index
            WHERE cel.contact_id = %s
            ORDER BY t.date DESC
            LIMIT %s
        """, (contact_id, limit))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_unlink_expense(self, contact_id: int, transaction_index: int) -> bool:
        """Remove a contact-expense link"""
        if not self.use_mysql or not self.conn:
            return False

        self.ensure_connection()
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM contact_expense_links
                WHERE contact_id = %s AND transaction_index = %s
            """, (contact_id, transaction_index))
            self.conn.commit()
            cursor.close()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ Unlink expense error: {e}")
            self.conn.rollback()
            cursor.close()
            return False

    def atlas_suggest_contacts_for_expense(self, transaction_index: int, limit: int = 5) -> List[Dict]:
        """Suggest contacts based on expense merchant name using fuzzy matching"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Get transaction merchant
        cursor.execute("SELECT merchant, description FROM transactions WHERE _index = %s", (transaction_index,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return []

        merchant = row['merchant'] or ''
        description = row['description'] or ''
        search_text = f"{merchant} {description}".lower()

        # Find contacts whose company or name matches
        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url, c.relationship_type,
                   CASE
                       WHEN LOWER(c.company) = %s THEN 100
                       WHEN LOWER(c.company) LIKE %s THEN 80
                       WHEN LOWER(c.name) LIKE %s THEN 60
                       WHEN LOWER(c.company) LIKE %s THEN 40
                       ELSE 20
                   END as match_score
            FROM contacts c
            WHERE (c.company IS NOT NULL AND c.company != '')
               OR (c.name IS NOT NULL AND c.name != '')
            HAVING match_score > 20
            ORDER BY match_score DESC
            LIMIT %s
        """, (merchant.lower(), f"%{merchant.lower()}%", f"%{merchant.lower()}%", f"%{search_text[:20]}%", limit))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_auto_link_expenses(self, dry_run: bool = True) -> Dict[str, Any]:
        """Auto-link expenses to contacts by matching merchant to company name"""
        if not self.use_mysql or not self.conn:
            return {'linked': 0, 'errors': 0}

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Get unlinked expenses
        cursor.execute("""
            SELECT DISTINCT t._index, LOWER(t.merchant) as merchant
            FROM transactions t
            LEFT JOIN contact_expense_links cel ON t._index = cel.transaction_index
            WHERE cel.id IS NULL
            AND t.merchant IS NOT NULL AND t.merchant != ''
        """)
        expenses = cursor.fetchall()

        # Get all contacts with companies
        cursor.execute("""
            SELECT id, LOWER(company) as company, LOWER(name) as name
            FROM contacts
            WHERE company IS NOT NULL AND company != ''
        """)
        contacts = {r['company']: r['id'] for r in cursor.fetchall()}

        linked = 0
        matches = []

        for exp in expenses:
            merchant = exp['merchant']
            # Try exact match first
            if merchant in contacts:
                matches.append({
                    'transaction_index': exp['_index'],
                    'contact_id': contacts[merchant],
                    'match_type': 'exact'
                })
            else:
                # Try partial match
                for company, contact_id in contacts.items():
                    if company in merchant or merchant in company:
                        matches.append({
                            'transaction_index': exp['_index'],
                            'contact_id': contact_id,
                            'match_type': 'partial'
                        })
                        break

        if not dry_run:
            for match in matches:
                try:
                    cursor.execute("""
                        INSERT IGNORE INTO contact_expense_links (contact_id, transaction_index, link_type, notes)
                        VALUES (%s, %s, 'vendor', %s)
                    """, (match['contact_id'], match['transaction_index'], f"Auto-linked ({match['match_type']} match)"))
                    linked += 1
                except Exception as e:
                    print(f"❌ Auto-link error: {e}")

            self.conn.commit()

        cursor.close()
        return {
            'found': len(matches),
            'linked': linked if not dry_run else 0,
            'matches': matches[:20] if dry_run else [],
            'dry_run': dry_run
        }

    def atlas_get_expense_contacts(self, transaction_index: int) -> List[Dict]:
        """Get all contacts linked to an expense"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url, c.relationship_type,
                   cel.link_type, cel.notes as link_notes
            FROM contacts c
            JOIN contact_expense_links cel ON c.id = cel.contact_id
            WHERE cel.transaction_index = %s
        """, (transaction_index,))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_get_spending_by_contact(self, limit: int = 20) -> List[Dict]:
        """Get spending summary by contact"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url,
                   COUNT(cel.id) as expense_count,
                   SUM(t.amount) as total_spent,
                   MAX(t.date) as last_expense_date
            FROM contacts c
            JOIN contact_expense_links cel ON c.id = cel.contact_id
            JOIN transactions t ON cel.transaction_index = t._index
            GROUP BY c.id
            ORDER BY total_spent DESC
            LIMIT %s
        """, (limit,))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_create_contact_from_merchant(self, merchant: str, transaction_index: int = None) -> Optional[int]:
        """Create a new contact from a merchant name and optionally link an expense"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        cursor = self.conn.cursor()

        try:
            # Create contact with merchant as company
            cursor.execute("""
                INSERT INTO contacts (name, company, relationship_type, source, created_at, updated_at)
                VALUES (%s, %s, 'vendor', 'expense_import', NOW(), NOW())
            """, (merchant, merchant))
            contact_id = cursor.lastrowid

            # Link expense if provided
            if transaction_index:
                cursor.execute("""
                    INSERT INTO contact_expense_links (contact_id, transaction_index, link_type, notes)
                    VALUES (%s, %s, 'vendor', 'Created from expense')
                """, (contact_id, transaction_index))

            self.conn.commit()
            cursor.close()
            return contact_id
        except Exception as e:
            print(f"❌ Create contact from merchant error: {e}")
            self.conn.rollback()
            cursor.close()
            return None

    # =========================================================================
    # AI-Powered Relationship Intelligence
    # =========================================================================

    def atlas_calculate_relationship_strength(self, contact_id: int) -> Dict[str, Any]:
        """Calculate relationship strength based on interactions and touchpoints"""
        if not self.use_mysql or not self.conn:
            return {}

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Get interaction stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_interactions,
                SUM(CASE WHEN occurred_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) as recent_30d,
                SUM(CASE WHEN occurred_at >= DATE_SUB(NOW(), INTERVAL 90 DAY) THEN 1 ELSE 0 END) as recent_90d,
                MAX(occurred_at) as last_interaction,
                MIN(occurred_at) as first_interaction
            FROM interactions i
            JOIN interaction_contacts ic ON i.id = ic.interaction_id
            WHERE ic.contact_id = %s
        """, (contact_id,))
        interaction_stats = dict(cursor.fetchone() or {})

        # Get expense relationship
        cursor.execute("""
            SELECT COUNT(*) as expense_count, SUM(t.amount) as total_spent
            FROM contact_expense_links cel
            JOIN transactions t ON cel.transaction_index = t._index
            WHERE cel.contact_id = %s
        """, (contact_id,))
        expense_stats = dict(cursor.fetchone() or {})

        # Calculate strength score (0-1)
        strength = 0.0
        factors = {}

        # Interaction frequency factor (0-0.4)
        total = interaction_stats.get('total_interactions') or 0
        recent = interaction_stats.get('recent_30d') or 0
        if recent >= 10:
            factors['interaction_frequency'] = 0.4
        elif recent >= 5:
            factors['interaction_frequency'] = 0.3
        elif recent >= 2:
            factors['interaction_frequency'] = 0.2
        elif total >= 5:
            factors['interaction_frequency'] = 0.1
        else:
            factors['interaction_frequency'] = 0.05

        # Recency factor (0-0.3)
        last = interaction_stats.get('last_interaction')
        if last:
            from datetime import datetime
            days_since = (datetime.now() - last).days if hasattr(last, 'days') else 0
            if days_since <= 7:
                factors['recency'] = 0.3
            elif days_since <= 30:
                factors['recency'] = 0.2
            elif days_since <= 90:
                factors['recency'] = 0.1
            else:
                factors['recency'] = 0.05
        else:
            factors['recency'] = 0

        # Longevity factor (0-0.2)
        first = interaction_stats.get('first_interaction')
        if first:
            from datetime import datetime
            days_known = (datetime.now() - first).days if hasattr(first, 'days') else 0
            if days_known >= 365:
                factors['longevity'] = 0.2
            elif days_known >= 180:
                factors['longevity'] = 0.15
            elif days_known >= 90:
                factors['longevity'] = 0.1
            else:
                factors['longevity'] = 0.05
        else:
            factors['longevity'] = 0

        # Financial relationship factor (0-0.1)
        expense_count = expense_stats.get('expense_count') or 0
        if expense_count >= 10:
            factors['financial'] = 0.1
        elif expense_count >= 5:
            factors['financial'] = 0.07
        elif expense_count >= 1:
            factors['financial'] = 0.03
        else:
            factors['financial'] = 0

        strength = sum(factors.values())

        # Update contact's relationship_strength
        cursor.execute("""
            UPDATE contacts SET relationship_strength = %s WHERE id = %s
        """, (round(strength, 2), contact_id))
        self.conn.commit()

        cursor.close()
        return {
            'contact_id': contact_id,
            'strength': round(strength, 2),
            'factors': factors,
            'interaction_stats': interaction_stats,
            'expense_stats': expense_stats
        }

    def atlas_get_relationship_insights(self, contact_id: int) -> Dict[str, Any]:
        """Get AI-ready relationship insights for a contact"""
        if not self.use_mysql or not self.conn:
            return {}

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Get contact details
        cursor.execute("SELECT * FROM contacts WHERE id = %s", (contact_id,))
        contact = dict(cursor.fetchone() or {})

        # Get interaction summary by type
        cursor.execute("""
            SELECT i.type, COUNT(*) as count, MAX(i.occurred_at) as last_date
            FROM interactions i
            JOIN interaction_contacts ic ON i.id = ic.interaction_id
            WHERE ic.contact_id = %s
            GROUP BY i.type
        """, (contact_id,))
        interactions_by_type = [dict(r) for r in cursor.fetchall()]

        # Get spending patterns
        cursor.execute("""
            SELECT
                DATE_FORMAT(t.date, '%%Y-%%m') as month,
                SUM(t.amount) as total,
                COUNT(*) as count
            FROM contact_expense_links cel
            JOIN transactions t ON cel.transaction_index = t._index
            WHERE cel.contact_id = %s
            GROUP BY DATE_FORMAT(t.date, '%%Y-%%m')
            ORDER BY month DESC
            LIMIT 12
        """, (contact_id,))
        spending_by_month = [dict(r) for r in cursor.fetchall()]

        # Get communication patterns (time of day, day of week)
        cursor.execute("""
            SELECT
                HOUR(i.occurred_at) as hour,
                DAYOFWEEK(i.occurred_at) as dow,
                COUNT(*) as count
            FROM interactions i
            JOIN interaction_contacts ic ON i.id = ic.interaction_id
            WHERE ic.contact_id = %s
            GROUP BY HOUR(i.occurred_at), DAYOFWEEK(i.occurred_at)
        """, (contact_id,))
        communication_patterns = [dict(r) for r in cursor.fetchall()]

        cursor.close()
        return {
            'contact': contact,
            'interactions_by_type': interactions_by_type,
            'spending_by_month': spending_by_month,
            'communication_patterns': communication_patterns
        }

    def atlas_get_contact_recommendations(self, limit: int = 10) -> List[Dict]:
        """Get recommended actions for contacts based on patterns"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        recommendations = []

        # 1. VIP contacts that haven't been contacted recently
        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url, c.last_touch_date,
                   DATEDIFF(CURDATE(), c.last_touch_date) as days_since_touch,
                   'vip_needs_attention' as recommendation_type,
                   'VIP contact needs attention' as reason
            FROM contacts c
            WHERE c.is_vip = TRUE
            AND (c.last_touch_date IS NULL OR c.last_touch_date < DATE_SUB(CURDATE(), INTERVAL 14 DAY))
            ORDER BY c.last_touch_date ASC
            LIMIT 5
        """)
        recommendations.extend([dict(r) for r in cursor.fetchall()])

        # 2. Contacts with declining interaction
        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url,
                   'declining_engagement' as recommendation_type,
                   'Interaction frequency has decreased' as reason
            FROM contacts c
            WHERE c.relationship_strength < 0.3
            AND EXISTS (
                SELECT 1 FROM interaction_contacts ic
                JOIN interactions i ON ic.interaction_id = i.id
                WHERE ic.contact_id = c.id
                AND i.occurred_at < DATE_SUB(NOW(), INTERVAL 60 DAY)
            )
            LIMIT 5
        """)
        recommendations.extend([dict(r) for r in cursor.fetchall()])

        # 3. High spenders needing follow-up
        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url,
                   SUM(t.amount) as total_spent,
                   'high_value_followup' as recommendation_type,
                   'High-value contact - consider follow-up' as reason
            FROM contacts c
            JOIN contact_expense_links cel ON c.id = cel.contact_id
            JOIN transactions t ON cel.transaction_index = t._index
            WHERE t.date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY c.id
            HAVING total_spent > 500
            ORDER BY total_spent DESC
            LIMIT 5
        """)
        recommendations.extend([dict(r) for r in cursor.fetchall()])

        # 4. Upcoming birthdays
        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url, c.birthday,
                   DATEDIFF(DATE_ADD(c.birthday, INTERVAL YEAR(CURDATE()) - YEAR(c.birthday) +
                       IF(DAYOFYEAR(CURDATE()) > DAYOFYEAR(c.birthday), 1, 0) YEAR), CURDATE()) as days_until,
                   'birthday_coming' as recommendation_type,
                   'Birthday coming up soon' as reason
            FROM contacts c
            WHERE c.birthday IS NOT NULL
            HAVING days_until BETWEEN 0 AND 14
            ORDER BY days_until ASC
            LIMIT 5
        """)
        recommendations.extend([dict(r) for r in cursor.fetchall()])

        cursor.close()
        return recommendations[:limit]

    def atlas_get_interaction_analysis(self, days: int = 30) -> Dict[str, Any]:
        """Analyze interaction patterns across all contacts"""
        if not self.use_mysql or not self.conn:
            return {}

        self.ensure_connection()
        cursor = self.conn.cursor()

        # Total interactions by type
        cursor.execute("""
            SELECT type, COUNT(*) as count
            FROM interactions
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY type
        """, (days,))
        by_type = {r['type']: r['count'] for r in cursor.fetchall()}

        # Interactions by day of week
        cursor.execute("""
            SELECT DAYOFWEEK(occurred_at) as dow, COUNT(*) as count
            FROM interactions
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY DAYOFWEEK(occurred_at)
        """, (days,))
        by_day = {r['dow']: r['count'] for r in cursor.fetchall()}

        # Interactions by hour
        cursor.execute("""
            SELECT HOUR(occurred_at) as hour, COUNT(*) as count
            FROM interactions
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY HOUR(occurred_at)
        """, (days,))
        by_hour = {r['hour']: r['count'] for r in cursor.fetchall()}

        # Daily trend
        cursor.execute("""
            SELECT DATE(occurred_at) as date, COUNT(*) as count
            FROM interactions
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY DATE(occurred_at)
            ORDER BY date
        """, (days,))
        daily_trend = [{'date': str(r['date']), 'count': r['count']} for r in cursor.fetchall()]

        # Most contacted
        cursor.execute("""
            SELECT c.id, c.name, c.company, c.photo_url, COUNT(*) as interaction_count
            FROM contacts c
            JOIN interaction_contacts ic ON c.id = ic.contact_id
            JOIN interactions i ON ic.interaction_id = i.id
            WHERE i.occurred_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY c.id
            ORDER BY interaction_count DESC
            LIMIT 10
        """, (days,))
        most_contacted = [dict(r) for r in cursor.fetchall()]

        cursor.close()
        return {
            'period_days': days,
            'by_type': by_type,
            'by_day_of_week': by_day,
            'by_hour': by_hour,
            'daily_trend': daily_trend,
            'most_contacted': most_contacted
        }

    def atlas_generate_ai_summary(self, contact_id: int) -> str:
        """Generate an AI-ready summary prompt for a contact"""
        insights = self.atlas_get_relationship_insights(contact_id)
        strength = self.atlas_calculate_relationship_strength(contact_id)

        contact = insights.get('contact', {})
        summary = f"""
Contact: {contact.get('name', 'Unknown')}
Company: {contact.get('company', 'N/A')}
Relationship Type: {contact.get('relationship_type', 'Unknown')}
Relationship Strength: {strength.get('strength', 0)} / 1.0

Interaction Summary:
{', '.join([f"{i['type']}: {i['count']}" for i in insights.get('interactions_by_type', [])])}

Recent Spending: ${sum([m.get('total', 0) for m in insights.get('spending_by_month', [])[:3]])}

Notes: {contact.get('notes', 'None')}

Generate a brief relationship summary and 2-3 actionable recommendations.
"""
        return summary.strip()

    # =========================================================================
    # Calendar Sync and Interaction Logging
    # =========================================================================

    def atlas_sync_calendar_event(self, event_data: Dict) -> Optional[int]:
        """Sync a calendar event to the database"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        cursor = self.conn.cursor()

        try:
            # Extract event data
            google_event_id = event_data.get('id')
            summary = event_data.get('summary', '')
            description = event_data.get('description', '')
            location = event_data.get('location', '')
            calendar_email = event_data.get('calendar_email', '')

            # Parse dates
            start = event_data.get('start', {})
            end = event_data.get('end', {})
            start_time = start.get('dateTime') or start.get('date')
            end_time = end.get('dateTime') or end.get('date')

            # Get attendees
            attendees = event_data.get('attendees', [])
            attendee_emails = [a.get('email') for a in attendees if a.get('email')]

            cursor.execute("""
                INSERT INTO calendar_events (
                    google_event_id, calendar_email, summary, description,
                    location, start_time, end_time, attendees_json, raw_event_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    summary = VALUES(summary),
                    description = VALUES(description),
                    location = VALUES(location),
                    start_time = VALUES(start_time),
                    end_time = VALUES(end_time),
                    attendees_json = VALUES(attendees_json)
            """, (
                google_event_id, calendar_email, summary, description,
                location, start_time, end_time,
                json.dumps(attendee_emails), json.dumps(event_data)
            ))

            event_id = cursor.lastrowid or None

            # Try to link attendees to contacts
            for email in attendee_emails:
                cursor.execute("""
                    SELECT c.id FROM contacts c
                    JOIN contact_emails ce ON c.id = ce.contact_id
                    WHERE ce.email = %s
                    LIMIT 1
                """, (email.lower(),))
                result = cursor.fetchone()
                if result:
                    # Create interaction for this meeting
                    cursor.execute("""
                        INSERT IGNORE INTO interactions (type, channel, occurred_at, summary, source_type, source_id)
                        VALUES ('meeting', 'calendar', %s, %s, 'calendar_event', %s)
                    """, (start_time, summary[:200] if summary else None, google_event_id))

                    interaction_id = cursor.lastrowid
                    if interaction_id:
                        cursor.execute("""
                            INSERT IGNORE INTO interaction_contacts (interaction_id, contact_id)
                            VALUES (%s, %s)
                        """, (interaction_id, result['id']))

            self.conn.commit()
            cursor.close()
            return event_id
        except Exception as e:
            print(f"❌ Sync calendar event error: {e}")
            self.conn.rollback()
            cursor.close()
            return None

    def atlas_get_calendar_events(self, contact_id: int = None, start_date: str = None, end_date: str = None, limit: int = 50) -> List[Dict]:
        """Get calendar events, optionally filtered by contact"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        if contact_id:
            cursor.execute("""
                SELECT DISTINCT ce.*
                FROM calendar_events ce
                JOIN interactions i ON ce.google_event_id = i.source_id AND i.source_type = 'calendar_event'
                JOIN interaction_contacts ic ON i.id = ic.interaction_id
                WHERE ic.contact_id = %s
                ORDER BY ce.start_time DESC
                LIMIT %s
            """, (contact_id, limit))
        else:
            query = "SELECT * FROM calendar_events WHERE 1=1"
            params = []
            if start_date:
                query += " AND start_time >= %s"
                params.append(start_date)
            if end_date:
                query += " AND end_time <= %s"
                params.append(end_date)
            query += " ORDER BY start_time DESC LIMIT %s"
            params.append(limit)
            cursor.execute(query, params)

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_log_interaction(self, data: Dict) -> Optional[int]:
        """Log a new interaction and optionally link to contacts"""
        if not self.use_mysql or not self.conn:
            return None

        self.ensure_connection()
        cursor = self.conn.cursor()

        try:
            interaction_type = data.get('type', 'note')
            channel = data.get('channel')
            occurred_at = data.get('occurred_at')
            summary = data.get('summary')
            content = data.get('content')
            is_outgoing = data.get('is_outgoing', True)
            sentiment = data.get('sentiment')
            contact_ids = data.get('contact_ids', [])

            cursor.execute("""
                INSERT INTO interactions (type, channel, occurred_at, summary, content, is_outgoing, sentiment)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (interaction_type, channel, occurred_at, summary, content, is_outgoing, sentiment))

            interaction_id = cursor.lastrowid

            # Link to contacts
            for contact_id in contact_ids:
                cursor.execute("""
                    INSERT INTO interaction_contacts (interaction_id, contact_id)
                    VALUES (%s, %s)
                """, (interaction_id, contact_id))

                # Update contact's last touch date
                cursor.execute("""
                    UPDATE contacts
                    SET last_touch_date = %s,
                        total_interactions = COALESCE(total_interactions, 0) + 1,
                        next_touch_date = DATE_ADD(%s, INTERVAL COALESCE(touch_frequency_days, 30) DAY)
                    WHERE id = %s
                """, (occurred_at, occurred_at, contact_id))

            self.conn.commit()
            cursor.close()
            return interaction_id
        except Exception as e:
            print(f"❌ Log interaction error: {e}")
            self.conn.rollback()
            cursor.close()
            return None

    def atlas_quick_log(self, contact_id: int, interaction_type: str, note: str = None) -> bool:
        """Quick log an interaction with just a type (call, meeting, email, note)"""
        from datetime import datetime
        return self.atlas_log_interaction({
            'type': interaction_type,
            'occurred_at': datetime.now().isoformat(),
            'summary': note or f"{interaction_type.title()} logged",
            'contact_ids': [contact_id]
        }) is not None

    def atlas_get_upcoming_events_with_contacts(self, days: int = 7) -> List[Dict]:
        """Get upcoming calendar events with matched contacts"""
        if not self.use_mysql or not self.conn:
            return []

        self.ensure_connection()
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT ce.*, GROUP_CONCAT(c.name) as contact_names, GROUP_CONCAT(c.id) as contact_ids
            FROM calendar_events ce
            LEFT JOIN interactions i ON ce.google_event_id = i.source_id AND i.source_type = 'calendar_event'
            LEFT JOIN interaction_contacts ic ON i.id = ic.interaction_id
            LEFT JOIN contacts c ON ic.contact_id = c.id
            WHERE ce.start_time >= NOW()
            AND ce.start_time <= DATE_ADD(NOW(), INTERVAL %s DAY)
            GROUP BY ce.id
            ORDER BY ce.start_time ASC
        """, (days,))

        results = [dict(r) for r in cursor.fetchall()]
        cursor.close()
        return results

    def atlas_sync_all_calendar_events(self) -> Dict[str, int]:
        """Sync all calendar events from the calendar service"""
        stats = {'synced': 0, 'errors': 0}

        try:
            # Import calendar service
            from calendar_service import get_all_calendar_services

            services = get_all_calendar_services()

            for service_info in services:
                email = service_info.get('email', 'unknown')
                service = service_info.get('service')

                if not service:
                    continue

                try:
                    # Get events from last 30 days to next 30 days
                    from datetime import datetime, timedelta
                    time_min = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
                    time_max = (datetime.utcnow() + timedelta(days=30)).isoformat() + 'Z'

                    events_result = service.events().list(
                        calendarId='primary',
                        timeMin=time_min,
                        timeMax=time_max,
                        maxResults=100,
                        singleEvents=True,
                        orderBy='startTime'
                    ).execute()

                    events = events_result.get('items', [])

                    for event in events:
                        event['calendar_email'] = email
                        if self.atlas_sync_calendar_event(event):
                            stats['synced'] += 1
                        else:
                            stats['errors'] += 1

                except Exception as e:
                    print(f"❌ Calendar sync error for {email}: {e}")
                    stats['errors'] += 1

        except ImportError:
            print("❌ Calendar service not available")
            stats['errors'] += 1

        return stats


# Singleton instance
_mysql_db_instance = None

def get_mysql_db():
    """Get global MySQL database instance"""
    global _mysql_db_instance
    if _mysql_db_instance is None:
        _mysql_db_instance = MySQLReceiptDatabase()
    return _mysql_db_instance
