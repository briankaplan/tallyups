#!/usr/bin/env python3
"""
Receipt Deduplicator Service
============================
Prevents duplicate receipts from being processed multiple times.

Uses multiple signals for deduplication:
1. Exact email message_id match
2. Same merchant + amount + date within 24 hours
3. Content hash (subject + from + amount)
4. Same invoice/order number
5. Perceptual hash of receipt images (future)

This service integrates with incoming_receipts to ensure we don't:
- Process the same email twice
- Create duplicate entries for forwarded receipts
- Match the same receipt to multiple transactions
"""

import re
import json
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Tuple, Any, Set
from dataclasses import dataclass
import pymysql
import pymysql.cursors
import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

MYSQL_CONFIG = {
    # Use MYSQLHOST (Railway's private hostname) to avoid egress fees
    'host': os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST', ''),
    'port': int(os.getenv('MYSQLPORT') or os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQLUSER') or os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQLPASSWORD') or os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQLDATABASE') or os.getenv('MYSQL_DATABASE', 'railway'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

# Deduplication window - receipts within this window are considered potential duplicates
DEDUP_WINDOW_HOURS = 48

# Amount tolerance for "same" amount (handles rounding, tax variations)
AMOUNT_TOLERANCE = 0.50  # $0.50 tolerance


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class DuplicateCheckResult:
    """Result of duplicate check"""
    is_duplicate: bool
    duplicate_of_id: Optional[int] = None
    match_type: str = 'none'  # 'message_id', 'content_hash', 'merchant_amount_date', 'order_number'
    confidence: int = 0  # 0-100
    details: str = ''

    def to_dict(self) -> Dict:
        return {
            'is_duplicate': self.is_duplicate,
            'duplicate_of_id': self.duplicate_of_id,
            'match_type': self.match_type,
            'confidence': self.confidence,
            'details': self.details
        }


# =============================================================================
# RECEIPT DEDUPLICATOR
# =============================================================================

class ReceiptDeduplicator:
    """
    Prevents duplicate receipt processing using multiple signals.
    """

    def __init__(self):
        self._recent_hashes: Set[str] = set()
        self._load_recent_hashes()

    def _get_connection(self):
        """Get database connection"""
        return pymysql.connect(**MYSQL_CONFIG)

    def _load_recent_hashes(self):
        """Load recent content hashes from database for quick lookup"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Load hashes from last 30 days
            cursor.execute('''
                SELECT DISTINCT email_id
                FROM incoming_receipts
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                AND email_id IS NOT NULL
            ''')

            for row in cursor.fetchall():
                self._recent_hashes.add(row['email_id'])

            conn.close()
            print(f"Loaded {len(self._recent_hashes)} recent receipt hashes")

        except Exception as e:
            print(f"Warning: Could not load recent hashes: {e}")

    def generate_content_hash(
        self,
        from_email: str,
        subject: str,
        amount: Optional[float] = None,
        date: Optional[str] = None
    ) -> str:
        """
        Generate a content hash for deduplication.

        This hash is used when we don't have a Gmail message_id
        (e.g., manually uploaded receipts, forwarded emails).
        """
        # Normalize inputs
        from_email = (from_email or '').lower().strip()
        subject = (subject or '').lower().strip()

        # Remove common variations that shouldn't affect uniqueness
        # Remove "fwd:", "re:", etc.
        subject = re.sub(r'^(re:|fwd:|fw:)\s*', '', subject)
        # Remove order numbers (they make each email look unique even if it's a forward)
        # Actually, keep order numbers - they help identify unique orders

        # Round amount to 2 decimal places
        if amount:
            amount = round(float(amount), 2)

        # Build hash input
        hash_input = f"{from_email}|{subject}|{amount or 0}"

        # If date provided, include it (truncated to day)
        if date:
            try:
                if isinstance(date, str):
                    # Parse various date formats
                    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%Y-%m-%dT%H:%M:%S']:
                        try:
                            dt = datetime.strptime(date[:19], fmt)
                            hash_input += f"|{dt.strftime('%Y-%m-%d')}"
                            break
                        except:
                            continue
            except:
                pass

        # Generate SHA256 hash
        return hashlib.sha256(hash_input.encode()).hexdigest()[:32]

    def extract_order_number(self, subject: str, body: str = '') -> Optional[str]:
        """Extract order/invoice number from email"""
        text = f"{subject} {body}"

        patterns = [
            r'order\s*#?\s*([A-Z0-9-]{5,20})',
            r'order\s+(?:number|id):\s*([A-Z0-9-]{5,20})',
            r'invoice\s*#?\s*([A-Z0-9-]{5,20})',
            r'invoice\s+(?:number|id):\s*([A-Z0-9-]{5,20})',
            r'confirmation\s*#?\s*([A-Z0-9-]{5,20})',
            r'reference\s*#?\s*([A-Z0-9-]{5,20})',
            r'transaction\s+id:\s*([A-Z0-9-]{5,20})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        return None

    def check_message_id(self, message_id: str) -> DuplicateCheckResult:
        """Check if we've already processed this Gmail message_id"""
        if not message_id:
            return DuplicateCheckResult(is_duplicate=False)

        # Quick check against in-memory cache
        if message_id in self._recent_hashes:
            return DuplicateCheckResult(
                is_duplicate=True,
                match_type='message_id',
                confidence=100,
                details='Message ID already in cache'
            )

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, merchant, amount, status
                FROM incoming_receipts
                WHERE email_id = %s
                LIMIT 1
            ''', (message_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    duplicate_of_id=row['id'],
                    match_type='message_id',
                    confidence=100,
                    details=f"Exact message_id match: {row['merchant']} ${row['amount']} ({row['status']})"
                )

        except Exception as e:
            print(f"Error checking message_id: {e}")

        return DuplicateCheckResult(is_duplicate=False)

    def check_merchant_amount_date(
        self,
        merchant: str,
        amount: float,
        date: str,
        exclude_id: Optional[int] = None
    ) -> DuplicateCheckResult:
        """Check for duplicate by merchant + amount + date"""
        if not merchant or not amount:
            return DuplicateCheckResult(is_duplicate=False)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Normalize merchant name
            merchant_lower = merchant.lower().strip()

            # Parse date
            receipt_date = None
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%Y-%m-%dT%H:%M:%S']:
                try:
                    receipt_date = datetime.strptime(str(date)[:19], fmt)
                    break
                except:
                    continue

            if not receipt_date:
                conn.close()
                return DuplicateCheckResult(is_duplicate=False)

            # Look for matching receipts within the dedup window
            window_start = receipt_date - timedelta(hours=DEDUP_WINDOW_HOURS)
            window_end = receipt_date + timedelta(hours=DEDUP_WINDOW_HOURS)

            query = '''
                SELECT id, email_id, merchant, amount, received_date, status
                FROM incoming_receipts
                WHERE LOWER(merchant) LIKE %s
                AND ABS(amount - %s) <= %s
                AND received_date >= %s
                AND received_date <= %s
            '''
            params = [
                f'%{merchant_lower}%',
                amount,
                AMOUNT_TOLERANCE,
                window_start.strftime('%Y-%m-%d %H:%M:%S'),
                window_end.strftime('%Y-%m-%d %H:%M:%S')
            ]

            if exclude_id:
                query += ' AND id != %s'
                params.append(exclude_id)

            query += ' LIMIT 1'

            cursor.execute(query, params)
            row = cursor.fetchone()
            conn.close()

            if row:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    duplicate_of_id=row['id'],
                    match_type='merchant_amount_date',
                    confidence=85,
                    details=f"Similar receipt found: {row['merchant']} ${row['amount']} on {row['received_date']}"
                )

        except Exception as e:
            print(f"Error checking merchant/amount/date: {e}")

        return DuplicateCheckResult(is_duplicate=False)

    def check_order_number(
        self,
        order_number: str,
        exclude_id: Optional[int] = None
    ) -> DuplicateCheckResult:
        """Check for duplicate by order/invoice number"""
        if not order_number:
            return DuplicateCheckResult(is_duplicate=False)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Check in subject field (order numbers often appear there)
            query = '''
                SELECT id, merchant, amount, subject, status
                FROM incoming_receipts
                WHERE (subject LIKE %s OR ai_notes LIKE %s)
                AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            '''
            pattern = f'%{order_number}%'
            params = [pattern, pattern]

            if exclude_id:
                query += ' AND id != %s'
                params.append(exclude_id)

            query += ' LIMIT 1'

            cursor.execute(query, params)
            row = cursor.fetchone()
            conn.close()

            if row:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    duplicate_of_id=row['id'],
                    match_type='order_number',
                    confidence=95,
                    details=f"Order number {order_number} found in existing receipt: {row['merchant']} ${row['amount']}"
                )

        except Exception as e:
            print(f"Error checking order number: {e}")

        return DuplicateCheckResult(is_duplicate=False)

    def check_content_hash(
        self,
        content_hash: str,
        exclude_id: Optional[int] = None
    ) -> DuplicateCheckResult:
        """Check for duplicate by content hash"""
        if not content_hash:
            return DuplicateCheckResult(is_duplicate=False)

        # Note: This requires a content_hash column in the database
        # If not present, we skip this check
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Check if content_hash column exists
            cursor.execute("SHOW COLUMNS FROM incoming_receipts LIKE 'content_hash'")
            if not cursor.fetchone():
                conn.close()
                return DuplicateCheckResult(is_duplicate=False)

            query = '''
                SELECT id, merchant, amount, status
                FROM incoming_receipts
                WHERE content_hash = %s
            '''
            params = [content_hash]

            if exclude_id:
                query += ' AND id != %s'
                params.append(exclude_id)

            query += ' LIMIT 1'

            cursor.execute(query, params)
            row = cursor.fetchone()
            conn.close()

            if row:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    duplicate_of_id=row['id'],
                    match_type='content_hash',
                    confidence=90,
                    details=f"Content hash match: {row['merchant']} ${row['amount']}"
                )

        except Exception as e:
            # Column doesn't exist or other error - skip this check
            pass

        return DuplicateCheckResult(is_duplicate=False)

    def is_duplicate(
        self,
        message_id: Optional[str] = None,
        from_email: Optional[str] = None,
        subject: Optional[str] = None,
        merchant: Optional[str] = None,
        amount: Optional[float] = None,
        date: Optional[str] = None,
        body: Optional[str] = None,
        exclude_id: Optional[int] = None
    ) -> DuplicateCheckResult:
        """
        Check if a receipt is a duplicate using all available signals.

        Checks in order of confidence:
        1. Message ID (100% confidence)
        2. Order number (95% confidence)
        3. Content hash (90% confidence)
        4. Merchant + Amount + Date (85% confidence)

        Returns first match found, or DuplicateCheckResult(is_duplicate=False).
        """
        # 1. Check message_id (highest confidence)
        if message_id:
            result = self.check_message_id(message_id)
            if result.is_duplicate:
                return result

        # 2. Check order number
        order_number = self.extract_order_number(subject or '', body or '')
        if order_number:
            result = self.check_order_number(order_number, exclude_id)
            if result.is_duplicate:
                return result

        # 3. Check content hash
        if from_email and subject:
            content_hash = self.generate_content_hash(from_email, subject, amount, date)
            result = self.check_content_hash(content_hash, exclude_id)
            if result.is_duplicate:
                return result

        # 4. Check merchant + amount + date
        if merchant and amount and date:
            result = self.check_merchant_amount_date(merchant, amount, date, exclude_id)
            if result.is_duplicate:
                return result

        return DuplicateCheckResult(is_duplicate=False)

    def register_receipt(self, message_id: str):
        """Register a new receipt in the dedup cache"""
        if message_id:
            self._recent_hashes.add(message_id)

    def find_potential_duplicates(self, receipt_id: int) -> List[Dict]:
        """Find potential duplicates for a specific receipt (for UI display)"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get the receipt details
            cursor.execute('''
                SELECT merchant, amount, received_date, subject
                FROM incoming_receipts
                WHERE id = %s
            ''', (receipt_id,))

            receipt = cursor.fetchone()
            if not receipt:
                conn.close()
                return []

            # Find similar receipts
            merchant_lower = (receipt['merchant'] or '').lower()
            amount = float(receipt['amount'] or 0)

            cursor.execute('''
                SELECT id, merchant, amount, received_date, status, subject
                FROM incoming_receipts
                WHERE id != %s
                AND (
                    (LOWER(merchant) LIKE %s AND ABS(amount - %s) <= %s)
                    OR subject LIKE %s
                )
                ORDER BY received_date DESC
                LIMIT 10
            ''', (
                receipt_id,
                f'%{merchant_lower}%',
                amount,
                AMOUNT_TOLERANCE * 2,
                f'%{receipt["subject"][:50] if receipt["subject"] else ""}%'
            ))

            duplicates = []
            for row in cursor.fetchall():
                duplicates.append({
                    'id': row['id'],
                    'merchant': row['merchant'],
                    'amount': float(row['amount']) if row['amount'] else 0,
                    'date': str(row['received_date']),
                    'status': row['status'],
                    'subject': row['subject']
                })

            conn.close()
            return duplicates

        except Exception as e:
            print(f"Error finding duplicates: {e}")
            return []

    def merge_duplicates(self, keep_id: int, remove_ids: List[int]) -> bool:
        """Merge duplicate receipts, keeping one and deleting others"""
        if not remove_ids:
            return True

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Mark duplicates as merged (don't delete - keep audit trail)
            for remove_id in remove_ids:
                cursor.execute('''
                    UPDATE incoming_receipts
                    SET status = 'duplicate',
                        rejection_reason = %s,
                        reviewed_at = NOW()
                    WHERE id = %s
                ''', (f'Merged into #{keep_id}', remove_id))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"Error merging duplicates: {e}")
            return False


# =============================================================================
# DATABASE SCHEMA UPDATE
# =============================================================================

def add_content_hash_column():
    """Add content_hash column to incoming_receipts if it doesn't exist"""
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()

        cursor.execute("SHOW COLUMNS FROM incoming_receipts LIKE 'content_hash'")
        if not cursor.fetchone():
            cursor.execute('''
                ALTER TABLE incoming_receipts
                ADD COLUMN content_hash VARCHAR(64),
                ADD INDEX idx_content_hash (content_hash)
            ''')
            conn.commit()
            print("Added content_hash column to incoming_receipts")

        conn.close()
        return True

    except Exception as e:
        print(f"Error adding content_hash column: {e}")
        return False


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_deduplicator() -> ReceiptDeduplicator:
    """Get singleton deduplicator instance"""
    if not hasattr(get_deduplicator, '_instance'):
        get_deduplicator._instance = ReceiptDeduplicator()
    return get_deduplicator._instance


def is_duplicate_receipt(
    message_id: str = None,
    from_email: str = None,
    subject: str = None,
    merchant: str = None,
    amount: float = None,
    date: str = None
) -> Dict:
    """Convenience function to check for duplicates"""
    deduplicator = get_deduplicator()
    result = deduplicator.is_duplicate(
        message_id=message_id,
        from_email=from_email,
        subject=subject,
        merchant=merchant,
        amount=amount,
        date=date
    )
    return result.to_dict()


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import sys

    # Initialize
    add_content_hash_column()

    deduplicator = ReceiptDeduplicator()

    if len(sys.argv) > 1:
        # Check specific receipt for duplicates
        receipt_id = int(sys.argv[1])
        duplicates = deduplicator.find_potential_duplicates(receipt_id)
        print(f"\nPotential duplicates for receipt #{receipt_id}:")
        for dup in duplicates:
            print(f"  #{dup['id']}: {dup['merchant']} ${dup['amount']} - {dup['status']}")
    else:
        # Test deduplication
        print("Receipt Deduplicator Test")
        print("=" * 60)

        # Test content hash generation
        hash1 = deduplicator.generate_content_hash(
            'receipts@anthropic.com',
            'Your receipt from Anthropic - $20.00',
            20.00,
            '2024-12-01'
        )
        hash2 = deduplicator.generate_content_hash(
            'receipts@anthropic.com',
            'Your receipt from Anthropic - $20.00',
            20.00,
            '2024-12-01'
        )
        hash3 = deduplicator.generate_content_hash(
            'receipts@anthropic.com',
            'Your receipt from Anthropic - $25.00',  # Different amount
            25.00,
            '2024-12-01'
        )

        print(f"Hash 1: {hash1}")
        print(f"Hash 2: {hash2}")
        print(f"Hash 3: {hash3}")
        print(f"Hash 1 == Hash 2: {hash1 == hash2} (should be True)")
        print(f"Hash 1 == Hash 3: {hash1 == hash3} (should be False)")

        # Test order number extraction
        test_subjects = [
            "Your Amazon.com order #112-3456789-0123456",
            "Order confirmation - Invoice #INV-2024-001",
            "Receipt for order 123456",
        ]

        print("\nOrder Number Extraction:")
        for subject in test_subjects:
            order_num = deduplicator.extract_order_number(subject)
            print(f"  {subject[:40]}... → {order_num}")
