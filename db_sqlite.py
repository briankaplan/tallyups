"""
ReceiptAI SQLite Database Layer
Created: 2025-11-13

Provides database operations for ReceiptAI system.
Supports both SQLite and CSV fallback modes.
"""

import os
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
import json

# Cloud-compatible database path
DEFAULT_DB_PATH = os.environ.get('DATABASE_PATH', 'receipts.db')
# For Railway persistent volume
if os.environ.get('RAILWAY_ENVIRONMENT'):
    DEFAULT_DB_PATH = os.environ.get('DATABASE_PATH', '/app/data/receipts.db')

class ReceiptDatabase:
    """SQLite database handler for ReceiptAI"""

    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.conn = None
        self.use_sqlite = False

        # Try to connect to SQLite
        if self.db_path.exists():
            try:
                self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                self.conn.row_factory = sqlite3.Row  # Return dict-like rows
                self.use_sqlite = True
                print(f"✅ Connected to SQLite: {self.db_path}", flush=True)
            except Exception as e:
                print(f"⚠️  SQLite connection failed: {e}", flush=True)
                self.use_sqlite = False
        else:
            print(f"ℹ️  SQLite database not found, using CSV mode", flush=True)
            self.use_sqlite = False

    def __del__(self):
        """Close connection on cleanup"""
        if self.conn:
            self.conn.close()

    def get_all_transactions(self) -> pd.DataFrame:
        """Get all transactions as DataFrame (with UI-friendly column names)"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

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
            # Merchant Intelligence fields
            'mi_merchant': 'MI Merchant',
            'mi_category': 'MI Category',
            'mi_description': 'MI Description',
            'mi_confidence': 'MI Confidence',
            'mi_is_subscription': 'MI Is Subscription',
            'mi_subscription_name': 'MI Subscription Name',
            'mi_processed_at': 'MI Processed At',
            # Refund tracking
            'is_refund': 'Is Refund',
            # Already Submitted tracking
            'already_submitted': 'Already Submitted'
        }

        df = df.rename(columns=column_map)

        # Drop metadata columns
        df = df.drop(columns=['id', 'created_at', 'updated_at'], errors='ignore')

        return df

    def get_transaction_by_index(self, index: int) -> Optional[Dict]:
        """Get single transaction by _index"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE _index = ?", (index,))
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def update_transaction(self, index: int, patch: Dict[str, Any]) -> bool:
        """Update transaction with patch data"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

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

        # Build UPDATE statement
        set_clauses = []
        values = []

        for key, value in patch.items():
            # Map to database column name
            db_col = column_map.get(key, key.lower().replace(' ', '_'))

            # Skip _index (can't update primary key)
            if db_col == '_index':
                continue

            set_clauses.append(f"{db_col} = ?")
            values.append(value)

        if not set_clauses:
            return False

        # Add _index for WHERE clause
        values.append(index)

        sql = f"""
            UPDATE transactions
            SET {', '.join(set_clauses)}
            WHERE _index = ?
        """

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
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        where_clauses = []
        params = []

        if business_type:
            where_clauses.append("business_type = ?")
            params.append(business_type)

        if has_receipt is not None:
            if has_receipt:
                where_clauses.append("receipt_file IS NOT NULL AND receipt_file != ''")
            else:
                where_clauses.append("(receipt_file IS NULL OR receipt_file = '')")

        if date_from:
            where_clauses.append("chase_date >= ?")
            params.append(date_from)

        if date_to:
            where_clauses.append("chase_date <= ?")
            params.append(date_to)

        if review_status:
            where_clauses.append("review_status = ?")
            params.append(review_status)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        query = f"SELECT * FROM transactions WHERE {where_sql} ORDER BY _index"

        df = pd.read_sql_query(query, self.conn, params=params)
        return df

    def get_receipt_metadata(self, filename: str) -> Optional[Dict]:
        """Get cached receipt metadata"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM receipt_metadata WHERE filename = ?",
            (filename,)
        )
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def cache_receipt_metadata(
        self,
        filename: str,
        merchant: str,
        date: str,
        amount: float,
        raw_text: str = ""
    ) -> bool:
        """Cache receipt metadata for fast matching"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        sql = """
            INSERT OR REPLACE INTO receipt_metadata
            (filename, merchant, date, amount, raw_text)
            VALUES (?, ?, ?, ?, ?)
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
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM receipt_metadata ORDER BY filename")
        return [dict(row) for row in cursor.fetchall()]

    def get_analytics(self) -> Dict[str, Any]:
        """Get analytics/stats from database"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        cursor = self.conn.cursor()

        # Total transactions
        cursor.execute("SELECT COUNT(*) FROM transactions")
        total = cursor.fetchone()[0]

        # Transactions with receipts
        cursor.execute("""
            SELECT COUNT(*) FROM transactions
            WHERE receipt_file IS NOT NULL AND receipt_file != ''
        """)
        with_receipts = cursor.fetchone()[0]

        # By business type
        cursor.execute("""
            SELECT business_type, COUNT(*) as count
            FROM transactions
            WHERE business_type IS NOT NULL AND business_type != ''
            GROUP BY business_type
            ORDER BY count DESC
        """)
        by_business = {row[0]: row[1] for row in cursor.fetchall()}

        # AI matched count
        cursor.execute("""
            SELECT COUNT(*) FROM transactions
            WHERE ai_confidence > 0
        """)
        ai_matched = cursor.fetchone()[0]

        # Review status breakdown
        cursor.execute("""
            SELECT review_status, COUNT(*) as count
            FROM transactions
            WHERE review_status IS NOT NULL AND review_status != ''
            GROUP BY review_status
        """)
        by_status = {row[0]: row[1] for row in cursor.fetchall()}

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
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        try:
            df = self.get_all_transactions()

            # Map database columns back to CSV columns
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
                'source': 'Source'
            }

            # Rename columns
            df = df.rename(columns=column_map)

            # Drop metadata columns
            df = df.drop(columns=['id', 'created_at', 'updated_at'], errors='ignore')

            # Save to CSV
            df.to_csv(output_path, index=False)
            print(f"✅ Exported to CSV: {output_path}", flush=True)
            return True

        except Exception as e:
            print(f"❌ CSV export failed: {e}", flush=True)
            return False

    def vacuum(self):
        """Optimize database (reclaim space, rebuild indexes)"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        try:
            self.conn.execute("VACUUM")
            print("✅ Database optimized", flush=True)
        except Exception as e:
            print(f"❌ Vacuum failed: {e}", flush=True)

    def get_missing_receipts(self, limit: int = 100) -> List[Dict]:
        """Get transactions without receipts (for batch matching)"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        query = """
            SELECT * FROM transactions
            WHERE (receipt_file IS NULL OR receipt_file = '')
            AND chase_date IS NOT NULL
            AND chase_description IS NOT NULL
            ORDER BY chase_date DESC
            LIMIT ?
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_statistics(self) -> Dict[str, Any]:
        """Get detailed statistics for dashboard"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        cursor = self.conn.cursor()

        stats = {}

        # Total spending by business type
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
            {'business': row[0], 'total': row[1], 'count': row[2]}
            for row in cursor.fetchall()
        ]

        # Monthly spending
        cursor.execute("""
            SELECT
                strftime('%Y-%m', chase_date) as month,
                SUM(ABS(chase_amount)) as total
            FROM transactions
            WHERE chase_date IS NOT NULL
            GROUP BY month
            ORDER BY month DESC
            LIMIT 12
        """)
        stats['monthly_spending'] = [
            {'month': row[0], 'total': row[1]}
            for row in cursor.fetchall()
        ]

        # Receipt match rate
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN receipt_file IS NOT NULL AND receipt_file != '' THEN 1 ELSE 0 END) as matched
            FROM transactions
        """)
        row = cursor.fetchone()
        total = row[0]
        matched = row[1]
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
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        # Exclude expenses that have already been submitted OR have a report_id
        where_clauses = [
            "(report_id IS NULL OR report_id = '')",
            "(already_submitted IS NULL OR already_submitted = '' OR already_submitted NOT IN ('yes', '1', 'true'))"
        ]
        params = []

        if business_type:
            where_clauses.append("business_type = ?")
            params.append(business_type)

        if date_from:
            where_clauses.append("chase_date >= ?")
            params.append(date_from)

        if date_to:
            where_clauses.append("chase_date <= ?")
            params.append(date_to)

        where_sql = " AND ".join(where_clauses)
        query = f"""
            SELECT * FROM transactions
            WHERE {where_sql}
            ORDER BY chase_date DESC
        """

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def submit_report(
        self,
        report_name: str,
        business_type: str,
        expense_indexes: List[int]
    ) -> str:
        """
        Create a report and assign report_id to selected expenses.
        Returns the generated report_id.
        """
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        # Generate report_id: REPORT-{business_type_abbrev}-{timestamp}
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        business_abbrev = business_type.replace(" ", "")[:3].upper()
        report_id = f"REPORT-{business_abbrev}-{timestamp}"

        # Create reports table if it doesn't exist
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT UNIQUE NOT NULL,
                report_name TEXT NOT NULL,
                business_type TEXT NOT NULL,
                expense_count INTEGER NOT NULL,
                total_amount REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Calculate total amount
        cursor = self.conn.cursor()
        placeholders = ",".join(["?"] * len(expense_indexes))
        cursor.execute(f"""
            SELECT
                COUNT(*) as count,
                SUM(ABS(chase_amount)) as total
            FROM transactions
            WHERE _index IN ({placeholders})
        """, expense_indexes)

        row = cursor.fetchone()
        expense_count = row[0]
        total_amount = row[1] or 0

        # Insert into reports table
        cursor.execute("""
            INSERT INTO reports (report_id, report_name, business_type, expense_count, total_amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            report_id,
            report_name,
            business_type,
            expense_count,
            total_amount,
            datetime.now().isoformat()
        ))

        # Update transactions with report_id and mark as already_submitted
        cursor.execute(f"""
            UPDATE transactions
            SET report_id = ?, already_submitted = 'yes'
            WHERE _index IN ({placeholders})
        """, [report_id] + expense_indexes)

        self.conn.commit()

        print(f"✅ Report created: {report_id} ({expense_count} expenses, ${total_amount:.2f})", flush=True)

        return report_id

    def get_all_reports(self) -> List[Dict]:
        """Get all submitted reports with metadata"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        # Create reports table if it doesn't exist
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT UNIQUE NOT NULL,
                report_name TEXT NOT NULL,
                business_type TEXT NOT NULL,
                expense_count INTEGER NOT NULL,
                total_amount REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM reports
            ORDER BY created_at DESC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def get_report_expenses(self, report_id: str) -> List[Dict]:
        """Get all expenses for a specific report"""
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM transactions
            WHERE report_id = ?
            ORDER BY chase_date DESC
        """, (report_id,))

        return [dict(row) for row in cursor.fetchall()]

    def delete_report(self, report_id: str) -> bool:
        """
        Delete a report and unassign all expenses from it.
        This effectively "unsubmits" a report, returning expenses to the available pool.
        Returns True if successful, False otherwise.
        """
        if not self.use_sqlite or not self.conn:
            raise RuntimeError("SQLite not available")

        try:
            cursor = self.conn.cursor()

            # First check if the report exists
            cursor.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,))
            report = cursor.fetchone()

            if not report:
                print(f"⚠️  Report {report_id} not found", flush=True)
                return False

            # Clear report_id AND already_submitted from all transactions
            # This returns them to the main view
            cursor.execute("""
                UPDATE transactions
                SET report_id = NULL,
                    already_submitted = NULL
                WHERE report_id = ?
            """, (report_id,))

            affected_count = cursor.rowcount

            # Delete the report
            cursor.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))

            self.conn.commit()

            print(f"✅ Report {report_id} deleted. {affected_count} expenses returned to available pool.", flush=True)
            return True

        except Exception as e:
            print(f"❌ Failed to delete report {report_id}: {e}", flush=True)
            self.conn.rollback()
            return False


# Singleton instance
_db_instance = None

def get_db() -> ReceiptDatabase:
    """Get global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = ReceiptDatabase()
    return _db_instance
