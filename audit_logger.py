#!/usr/bin/env python3
"""
Audit Logger for ReceiptAI System
----------------------------------
Logs all changes to receipts for tracking and debugging.
Addresses user requirement: "when things are changed it needs to be
instantaniously in the db and saved.. and quite honestly logged when
something is done so it can be tracked if its missing"
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

class AuditLogger:
    """Tracks all receipt changes for debugging and accountability"""

    def __init__(self, db_path: str = "receipts.db"):
        self.db_path = Path(db_path)
        self.conn = None

        if self.db_path.exists():
            try:
                self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                self._create_audit_table()
                print(f"✅ Audit logger connected to: {self.db_path}", flush=True)
            except Exception as e:
                print(f"⚠️  Audit logger connection failed: {e}", flush=True)

    def _create_audit_table(self):
        """Create audit_log table if it doesn't exist"""
        if not self.conn:
            return

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                transaction_index INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                source TEXT NOT NULL,
                user_agent TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Create index for fast queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_transaction
            ON audit_log(transaction_index, timestamp)
        """)

        self.conn.commit()

    def log_change(
        self,
        transaction_index: int,
        action_type: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
        source: str = "viewer_ui",
        user_agent: Optional[str] = None,
        notes: Optional[str] = None
    ) -> bool:
        """
        Log a single field change

        Args:
            transaction_index: _index of the transaction
            action_type: 'attach_receipt', 'detach_receipt', 'update_field', 'auto_match', etc.
            field_name: Name of the field changed (e.g., 'Receipt File')
            old_value: Previous value
            new_value: New value
            source: Source of change ('viewer_ui', 'auto_match', 'gmail_search', etc.)
            user_agent: Browser user agent (if from web UI)
            notes: Additional context

        Returns:
            True if logged successfully
        """
        if not self.conn:
            return False

        timestamp = datetime.now().isoformat()

        # Convert values to strings for storage
        old_str = str(old_value) if old_value is not None else ""
        new_str = str(new_value) if new_value is not None else ""

        try:
            self.conn.execute("""
                INSERT INTO audit_log (
                    timestamp, transaction_index, action_type, field_name,
                    old_value, new_value, source, user_agent, notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                transaction_index,
                action_type,
                field_name,
                old_str,
                new_str,
                source,
                user_agent or "",
                notes or "",
                timestamp
            ))

            self.conn.commit()
            return True

        except Exception as e:
            print(f"❌ Audit log failed: {e}", flush=True)
            return False

    def log_receipt_attach(
        self,
        transaction_index: int,
        old_receipt: Optional[str],
        new_receipt: str,
        confidence: float,
        source: str = "viewer_ui",
        notes: Optional[str] = None
    ) -> bool:
        """Log receipt attachment with full context"""
        action = "attach_receipt" if not old_receipt else "replace_receipt"

        full_notes = f"Confidence: {confidence:.1f}%"
        if notes:
            full_notes += f" | {notes}"

        return self.log_change(
            transaction_index=transaction_index,
            action_type=action,
            field_name="Receipt File",
            old_value=old_receipt or "",
            new_value=new_receipt,
            source=source,
            notes=full_notes
        )

    def log_receipt_detach(
        self,
        transaction_index: int,
        old_receipt: str,
        reason: str = "User removed",
        source: str = "viewer_ui"
    ) -> bool:
        """Log receipt removal"""
        return self.log_change(
            transaction_index=transaction_index,
            action_type="detach_receipt",
            field_name="Receipt File",
            old_value=old_receipt,
            new_value="",
            source=source,
            notes=reason
        )

    def get_transaction_history(self, transaction_index: int) -> List[Dict]:
        """Get full audit history for a transaction"""
        if not self.conn:
            return []

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT *
            FROM audit_log
            WHERE transaction_index = ?
            ORDER BY timestamp DESC
        """, (transaction_index,))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_recent_changes(self, limit: int = 100) -> List[Dict]:
        """Get most recent changes across all transactions"""
        if not self.conn:
            return []

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT *
            FROM audit_log
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def search_logs(
        self,
        action_type: Optional[str] = None,
        source: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[Dict]:
        """Search audit logs with filters"""
        if not self.conn:
            return []

        where_clauses = []
        params = []

        if action_type:
            where_clauses.append("action_type = ?")
            params.append(action_type)

        if source:
            where_clauses.append("source = ?")
            params.append(source)

        if date_from:
            where_clauses.append("timestamp >= ?")
            params.append(date_from)

        if date_to:
            where_clauses.append("timestamp <= ?")
            params.append(date_to)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT *
            FROM audit_log
            WHERE {where_sql}
            ORDER BY timestamp DESC
        """, params)

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_statistics(self) -> Dict[str, Any]:
        """Get audit log statistics"""
        if not self.conn:
            return {}

        cursor = self.conn.cursor()

        # Total logs
        cursor.execute("SELECT COUNT(*) FROM audit_log")
        total = cursor.fetchone()[0]

        # By action type
        cursor.execute("""
            SELECT action_type, COUNT(*) as count
            FROM audit_log
            GROUP BY action_type
            ORDER BY count DESC
        """)
        by_action = {row[0]: row[1] for row in cursor.fetchall()}

        # By source
        cursor.execute("""
            SELECT source, COUNT(*) as count
            FROM audit_log
            GROUP BY source
            ORDER BY count DESC
        """)
        by_source = {row[0]: row[1] for row in cursor.fetchall()}

        # Recent activity (last 24 hours)
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_log
            WHERE timestamp >= ?
        """, (cutoff,))
        today = cursor.fetchone()[0]

        return {
            'total_logs': total,
            'by_action_type': by_action,
            'by_source': by_source,
            'changes_today': today
        }


# Singleton instance
_audit_logger = None

def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


# CLI Test
if __name__ == "__main__":
    logger = get_audit_logger()

    print("🔍 Audit Logger Test")
    print("=" * 80)

    # Test logging
    logger.log_receipt_attach(
        transaction_index=1,
        old_receipt=None,
        new_receipt="test_receipt.pdf",
        confidence=95.0,
        source="test_harness",
        notes="Test attachment"
    )

    # Get history
    history = logger.get_transaction_history(1)
    print(f"\nTransaction #1 history: {len(history)} entries")
    for entry in history:
        print(f"  {entry['timestamp']}: {entry['action_type']} - {entry['new_value']}")

    # Get stats
    stats = logger.get_statistics()
    print(f"\nStatistics:")
    print(f"  Total logs: {stats['total_logs']}")
    print(f"  By action: {stats['by_action_type']}")
    print(f"  Changes today: {stats['changes_today']}")
