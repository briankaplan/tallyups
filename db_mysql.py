"""
ReceiptAI MySQL Database Layer
Created: 2025-11-24

Provides MySQL database operations for ReceiptAI system.
Mirrors the db_sqlite.py interface for drop-in compatibility.
"""

import os
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_index (_index),
                    INDEX idx_date (chase_date),
                    INDEX idx_business (business_type),
                    INDEX idx_review (review_status),
                    INDEX idx_report (report_id)
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

            self.conn.commit()
            print(f"✅ MySQL schema initialized", flush=True)

        except Exception as e:
            print(f"⚠️  Schema initialization failed: {e}", flush=True)
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
            'already_submitted': 'Already Submitted'
        }

        df = df.rename(columns=column_map)
        df = df.drop(columns=['id', 'created_at', 'updated_at'], errors='ignore')

        return df

    def get_transaction_by_index(self, index: int) -> Optional[Dict]:
        """Get single transaction by _index"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE _index = %s", (index,))
        return cursor.fetchone()

    def update_transaction(self, index: int, patch: Dict[str, Any]) -> bool:
        """Update transaction with patch data"""
        if not self.use_mysql or not self.conn:
            raise RuntimeError("MySQL not available")

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


# Singleton instance
_mysql_db_instance = None

def get_mysql_db():
    """Get global MySQL database instance"""
    global _mysql_db_instance
    if _mysql_db_instance is None:
        _mysql_db_instance = MySQLReceiptDatabase()
    return _mysql_db_instance
