#!/usr/bin/env python3
"""
Receipt Library Service
========================
World-class receipt archive system - "Google Photos for receipts"

Provides:
- Receipt CRUD operations
- Advanced search and filtering
- Duplicate detection
- Thumbnail generation
- Statistics and analytics
- Batch operations

Performance targets:
- List 1000 receipts in < 500ms
- Search returns in < 100ms
- Thumbnail generation < 200ms
"""

import os
import io
import uuid
import json
import hashlib
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

# Database imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from db_mysql import MySQLReceiptDatabase, get_pooled_connection
from r2_service import upload_to_r2, get_public_url, R2_PUBLIC_URL

# Optional imports
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS AND DATA CLASSES
# =============================================================================

class ReceiptSource(Enum):
    """Source of receipt - where it came from."""
    GMAIL_PERSONAL = "gmail_personal"
    GMAIL_SECONDARY = "gmail_secondary"  # Secondary business email
    GMAIL_BUSINESS = "gmail_business"
    SCANNER_MOBILE = "scanner_mobile"
    SCANNER_WEB = "scanner_web"
    MANUAL_UPLOAD = "manual_upload"
    FORWARDED_EMAIL = "forwarded_email"
    BANK_STATEMENT_PDF = "bank_statement_pdf"
    IMPORT = "import"


class ReceiptStatus(Enum):
    """Processing status of a receipt."""
    PROCESSING = "processing"
    READY = "ready"
    MATCHED = "matched"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class BusinessType(Enum):
    """
    Generic business type categories.
    User-specific business names are stored separately in user preferences.
    """
    PERSONAL = "personal"
    BUSINESS = "business"      # Primary business
    SECONDARY = "secondary"    # Secondary business
    OTHER = "other"            # Catch-all for other categories


@dataclass
class LineItem:
    """A single line item on a receipt."""
    description: str
    quantity: float = 1.0
    unit_price: Optional[float] = None
    total: Optional[float] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ReceiptLibraryItem:
    """A receipt in the library."""
    id: Optional[int] = None
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Source tracking
    source: str = "import"
    source_id: Optional[str] = None
    source_email: Optional[str] = None
    source_subject: Optional[str] = None

    # Storage
    storage_key: str = ""
    thumbnail_key: Optional[str] = None
    file_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None

    # Fingerprints
    fingerprint: Optional[str] = None
    content_hash: Optional[str] = None

    # OCR
    ocr_status: str = "pending"
    ocr_provider: Optional[str] = None
    ocr_confidence: Optional[float] = None
    ocr_raw_text: Optional[str] = None
    ocr_processed_at: Optional[datetime] = None

    # Extracted fields
    merchant_name: Optional[str] = None
    merchant_normalized: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: str = "USD"
    receipt_date: Optional[date] = None
    receipt_time: Optional[str] = None
    tax_amount: Optional[Decimal] = None
    tip_amount: Optional[Decimal] = None
    subtotal: Optional[Decimal] = None
    payment_method: Optional[str] = None
    last_four: Optional[str] = None
    order_number: Optional[str] = None

    # Line items
    line_items: List[LineItem] = field(default_factory=list)

    # Categorization
    business_type: str = "unknown"
    business_type_confidence: Optional[float] = None
    expense_category: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    # Matching
    status: str = "processing"
    matched_transaction_id: Optional[int] = None
    match_confidence: Optional[float] = None
    match_signals: Optional[Dict] = None
    duplicate_of_id: Optional[int] = None

    # Smart notes
    ai_description: Optional[str] = None
    ai_attendees: List[str] = field(default_factory=list)
    ai_business_purpose: Optional[str] = None
    user_notes: Optional[str] = None

    # Flags
    is_favorite: bool = False
    is_starred: bool = False
    needs_review: bool = False

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        data = {}
        for key, value in asdict(self).items():
            if isinstance(value, (datetime, date)):
                data[key] = value.isoformat() if value else None
            elif isinstance(value, Decimal):
                data[key] = float(value) if value else None
            elif isinstance(value, list) and value and isinstance(value[0], LineItem):
                data[key] = [item.to_dict() for item in value]
            else:
                data[key] = value
        return data

    @classmethod
    def from_db_row(cls, row: Dict) -> 'ReceiptLibraryItem':
        """Create from database row."""
        if not row:
            return None

        item = cls()
        for key, value in row.items():
            if hasattr(item, key):
                if key == 'line_items' and value:
                    if isinstance(value, str):
                        value = json.loads(value)
                    item.line_items = [LineItem(**li) if isinstance(li, dict) else li for li in (value or [])]
                elif key == 'tags' and value:
                    if isinstance(value, str):
                        value = json.loads(value)
                    item.tags = value or []
                elif key == 'ai_attendees' and value:
                    if isinstance(value, str):
                        value = json.loads(value)
                    item.ai_attendees = value or []
                elif key == 'match_signals' and value:
                    if isinstance(value, str):
                        value = json.loads(value)
                    item.match_signals = value
                elif key == 'amount' and value is not None:
                    item.amount = Decimal(str(value))
                elif key in ('tax_amount', 'tip_amount', 'subtotal') and value is not None:
                    setattr(item, key, Decimal(str(value)))
                else:
                    setattr(item, key, value)
        return item


@dataclass
class LibrarySearchQuery:
    """Search query parameters for the library."""
    text: Optional[str] = None
    merchant: Optional[str] = None
    status: Optional[List[str]] = None
    business_type: Optional[List[str]] = None
    source: Optional[List[str]] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    tags: Optional[List[str]] = None
    has_receipt_match: Optional[bool] = None
    needs_review: Optional[bool] = None
    is_favorite: Optional[bool] = None

    # Sorting
    sort_by: str = "created_at"
    sort_order: str = "desc"

    # Pagination
    page: int = 1
    per_page: int = 50


@dataclass
class LibraryStats:
    """Library statistics."""
    total_receipts: int = 0
    by_status: Dict[str, int] = field(default_factory=dict)
    by_business_type: Dict[str, int] = field(default_factory=dict)
    by_source: Dict[str, int] = field(default_factory=dict)
    by_month: List[Dict] = field(default_factory=list)
    top_merchants: List[Dict] = field(default_factory=list)
    total_amount: float = 0.0
    storage_used_bytes: int = 0
    unmatched_count: int = 0
    needs_review_count: int = 0


# =============================================================================
# RECEIPT LIBRARY SERVICE
# =============================================================================

class ReceiptLibraryService:
    """
    Main service for the Receipt Library.

    Handles all CRUD operations, search, and analytics for receipts.
    """

    def __init__(self):
        self.db = MySQLReceiptDatabase()
        self._thumbnail_cache = {}

    # -------------------------------------------------------------------------
    # RECEIPT CRUD OPERATIONS
    # -------------------------------------------------------------------------

    def create_receipt(self, receipt: ReceiptLibraryItem) -> Optional[int]:
        """
        Create a new receipt in the library.

        Returns the receipt ID if successful, None otherwise.
        """
        if not self.db.use_mysql:
            logger.error("MySQL not available")
            return None

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Ensure UUID is set
            if not receipt.uuid:
                receipt.uuid = str(uuid.uuid4())

            # Normalize merchant name
            if receipt.merchant_name and not receipt.merchant_normalized:
                receipt.merchant_normalized = self._normalize_merchant(receipt.merchant_name)

            try:
                cursor.execute("""
                    INSERT INTO receipt_library (
                        uuid, fingerprint, content_hash,
                        source, source_id, source_email, source_subject,
                        storage_key, thumbnail_key, file_type, file_size_bytes,
                        image_width, image_height,
                        ocr_status, ocr_provider, ocr_confidence, ocr_raw_text,
                        merchant_name, merchant_normalized, amount, currency,
                        receipt_date, receipt_time, tax_amount, tip_amount, subtotal,
                        payment_method, last_four, order_number, line_items,
                        business_type, business_type_confidence, expense_category, tags,
                        status, matched_transaction_id, match_confidence, match_signals,
                        duplicate_of_id, ai_description, ai_attendees, ai_business_purpose,
                        user_notes, is_favorite, is_starred, needs_review
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    receipt.uuid, receipt.fingerprint, receipt.content_hash,
                    receipt.source, receipt.source_id, receipt.source_email, receipt.source_subject,
                    receipt.storage_key, receipt.thumbnail_key, receipt.file_type, receipt.file_size_bytes,
                    receipt.image_width, receipt.image_height,
                    receipt.ocr_status, receipt.ocr_provider, receipt.ocr_confidence, receipt.ocr_raw_text,
                    receipt.merchant_name, receipt.merchant_normalized,
                    float(receipt.amount) if receipt.amount else None, receipt.currency,
                    receipt.receipt_date, receipt.receipt_time,
                    float(receipt.tax_amount) if receipt.tax_amount else None,
                    float(receipt.tip_amount) if receipt.tip_amount else None,
                    float(receipt.subtotal) if receipt.subtotal else None,
                    receipt.payment_method, receipt.last_four, receipt.order_number,
                    json.dumps([li.to_dict() for li in receipt.line_items]) if receipt.line_items else None,
                    receipt.business_type, receipt.business_type_confidence, receipt.expense_category,
                    json.dumps(receipt.tags) if receipt.tags else None,
                    receipt.status, receipt.matched_transaction_id, receipt.match_confidence,
                    json.dumps(receipt.match_signals) if receipt.match_signals else None,
                    receipt.duplicate_of_id, receipt.ai_description,
                    json.dumps(receipt.ai_attendees) if receipt.ai_attendees else None,
                    receipt.ai_business_purpose, receipt.user_notes,
                    receipt.is_favorite, receipt.is_starred, receipt.needs_review
                ))

                receipt_id = cursor.lastrowid

                # Update search index
                self._update_search_index(cursor, receipt_id, receipt)

                # Log activity
                self._log_activity(cursor, receipt_id, 'create', actor='system')

                conn.commit()
                logger.info(f"Created receipt {receipt_id} ({receipt.uuid})")
                return receipt_id

            except Exception as e:
                logger.error(f"Failed to create receipt: {e}")
                conn.rollback()
                return None

    def get_receipt(self, receipt_id: int = None, uuid: str = None) -> Optional[ReceiptLibraryItem]:
        """Get a single receipt by ID or UUID."""
        if not self.db.use_mysql:
            return None

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            if receipt_id:
                cursor.execute("SELECT * FROM receipt_library WHERE id = %s AND deleted_at IS NULL", (receipt_id,))
            elif uuid:
                cursor.execute("SELECT * FROM receipt_library WHERE uuid = %s AND deleted_at IS NULL", (uuid,))
            else:
                return None

            row = cursor.fetchone()
            return ReceiptLibraryItem.from_db_row(row) if row else None

    def update_receipt(self, receipt_id: int, updates: Dict[str, Any], actor: str = "user") -> bool:
        """Update a receipt's fields."""
        if not self.db.use_mysql or not updates:
            return False

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Get current values for audit
            cursor.execute("SELECT * FROM receipt_library WHERE id = %s", (receipt_id,))
            old_row = cursor.fetchone()
            if not old_row:
                return False

            # Build update query
            set_clauses = []
            values = []
            for key, value in updates.items():
                if key in ('id', 'uuid', 'created_at'):
                    continue  # Don't update these

                if isinstance(value, (list, dict)):
                    value = json.dumps(value)
                elif isinstance(value, Decimal):
                    value = float(value)
                elif isinstance(value, (datetime, date)):
                    value = value.isoformat() if value else None

                set_clauses.append(f"{key} = %s")
                values.append(value)

            if not set_clauses:
                return False

            values.append(receipt_id)

            try:
                cursor.execute(
                    f"UPDATE receipt_library SET {', '.join(set_clauses)} WHERE id = %s",
                    values
                )

                # Update search index if relevant fields changed
                search_fields = {'merchant_name', 'merchant_normalized', 'amount', 'receipt_date',
                                'ocr_raw_text', 'ai_description', 'user_notes'}
                if search_fields & set(updates.keys()):
                    receipt = self.get_receipt(receipt_id)
                    if receipt:
                        self._update_search_index(cursor, receipt_id, receipt)

                # Log activity
                self._log_activity(cursor, receipt_id, 'update', actor=actor,
                                  old_value=dict(old_row), new_value=updates)

                conn.commit()
                return True

            except Exception as e:
                logger.error(f"Failed to update receipt {receipt_id}: {e}")
                conn.rollback()
                return False

    def delete_receipt(self, receipt_id: int, soft: bool = True, actor: str = "user") -> bool:
        """Delete a receipt (soft delete by default)."""
        if not self.db.use_mysql:
            return False

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            try:
                if soft:
                    cursor.execute(
                        "UPDATE receipt_library SET deleted_at = NOW(), status = 'archived' WHERE id = %s",
                        (receipt_id,)
                    )
                else:
                    cursor.execute("DELETE FROM receipt_library WHERE id = %s", (receipt_id,))

                self._log_activity(cursor, receipt_id, 'delete' if not soft else 'soft_delete', actor=actor)
                conn.commit()
                return cursor.rowcount > 0

            except Exception as e:
                logger.error(f"Failed to delete receipt {receipt_id}: {e}")
                conn.rollback()
                return False

    # -------------------------------------------------------------------------
    # SEARCH AND LISTING
    # -------------------------------------------------------------------------

    def search_receipts(self, query: LibrarySearchQuery) -> Tuple[List[ReceiptLibraryItem], int]:
        """
        Search receipts with advanced filtering.

        Returns (receipts, total_count) tuple.
        """
        if not self.db.use_mysql:
            return [], 0

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Build WHERE clauses
            where_clauses = ["r.deleted_at IS NULL"]
            params = []

            # Full-text search
            if query.text:
                where_clauses.append("""
                    (MATCH(r.merchant_name, r.ocr_raw_text, r.ai_description, r.user_notes)
                     AGAINST(%s IN NATURAL LANGUAGE MODE)
                     OR r.merchant_normalized LIKE %s
                     OR r.order_number LIKE %s)
                """)
                params.extend([query.text, f"%{query.text.lower()}%", f"%{query.text}%"])

            # Merchant filter
            if query.merchant:
                where_clauses.append("r.merchant_normalized LIKE %s")
                params.append(f"%{query.merchant.lower()}%")

            # Status filter
            if query.status:
                placeholders = ','.join(['%s'] * len(query.status))
                where_clauses.append(f"r.status IN ({placeholders})")
                params.extend(query.status)

            # Business type filter
            if query.business_type:
                placeholders = ','.join(['%s'] * len(query.business_type))
                where_clauses.append(f"r.business_type IN ({placeholders})")
                params.extend(query.business_type)

            # Source filter
            if query.source:
                placeholders = ','.join(['%s'] * len(query.source))
                where_clauses.append(f"r.source IN ({placeholders})")
                params.extend(query.source)

            # Date range
            if query.date_from:
                where_clauses.append("r.receipt_date >= %s")
                params.append(query.date_from)

            if query.date_to:
                where_clauses.append("r.receipt_date <= %s")
                params.append(query.date_to)

            # Amount range
            if query.amount_min is not None:
                where_clauses.append("r.amount >= %s")
                params.append(float(query.amount_min))

            if query.amount_max is not None:
                where_clauses.append("r.amount <= %s")
                params.append(float(query.amount_max))

            # Flags
            if query.has_receipt_match is not None:
                if query.has_receipt_match:
                    where_clauses.append("r.matched_transaction_id IS NOT NULL")
                else:
                    where_clauses.append("r.matched_transaction_id IS NULL")

            if query.needs_review is not None:
                where_clauses.append("r.needs_review = %s")
                params.append(query.needs_review)

            if query.is_favorite is not None:
                where_clauses.append("r.is_favorite = %s")
                params.append(query.is_favorite)

            # Tags filter
            if query.tags:
                for tag in query.tags:
                    where_clauses.append("JSON_CONTAINS(r.tags, %s)")
                    params.append(json.dumps(tag))

            where_sql = " AND ".join(where_clauses)

            # Get total count
            cursor.execute(f"SELECT COUNT(*) as count FROM receipt_library r WHERE {where_sql}", params)
            total = cursor.fetchone()['count']

            # Build ORDER BY
            valid_sort_fields = {
                'created_at', 'receipt_date', 'amount', 'merchant_normalized',
                'status', 'business_type', 'updated_at'
            }
            sort_field = query.sort_by if query.sort_by in valid_sort_fields else 'created_at'
            sort_order = 'DESC' if query.sort_order.lower() == 'desc' else 'ASC'

            # Calculate offset
            offset = (query.page - 1) * query.per_page

            # Fetch results
            cursor.execute(f"""
                SELECT r.* FROM receipt_library r
                WHERE {where_sql}
                ORDER BY r.{sort_field} {sort_order}
                LIMIT %s OFFSET %s
            """, params + [query.per_page, offset])

            receipts = [ReceiptLibraryItem.from_db_row(row) for row in cursor.fetchall()]

            return receipts, total

    def list_receipts(
        self,
        page: int = 1,
        per_page: int = 50,
        status: Optional[str] = None,
        business_type: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> Tuple[List[ReceiptLibraryItem], int]:
        """Simple list with basic filters."""
        query = LibrarySearchQuery(
            page=page,
            per_page=per_page,
            status=[status] if status else None,
            business_type=[business_type] if business_type else None,
            sort_by=sort_by,
            sort_order=sort_order
        )
        return self.search_receipts(query)

    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------

    def get_stats(self) -> LibraryStats:
        """Get library statistics."""
        if not self.db.use_mysql:
            return LibraryStats()

        stats = LibraryStats()

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Total receipts
            cursor.execute("""
                SELECT COUNT(*) as total,
                       COALESCE(SUM(amount), 0) as total_amount,
                       COALESCE(SUM(file_size_bytes), 0) as storage
                FROM receipt_library
                WHERE deleted_at IS NULL
            """)
            row = cursor.fetchone()
            stats.total_receipts = row['total']
            stats.total_amount = float(row['total_amount'] or 0)
            stats.storage_used_bytes = row['storage'] or 0

            # By status
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM receipt_library
                WHERE deleted_at IS NULL
                GROUP BY status
            """)
            stats.by_status = {row['status']: row['count'] for row in cursor.fetchall()}

            # By business type
            cursor.execute("""
                SELECT business_type, COUNT(*) as count
                FROM receipt_library
                WHERE deleted_at IS NULL
                GROUP BY business_type
            """)
            stats.by_business_type = {row['business_type']: row['count'] for row in cursor.fetchall()}

            # By source
            cursor.execute("""
                SELECT source, COUNT(*) as count
                FROM receipt_library
                WHERE deleted_at IS NULL
                GROUP BY source
            """)
            stats.by_source = {row['source']: row['count'] for row in cursor.fetchall()}

            # By month (last 12 months)
            cursor.execute("""
                SELECT
                    DATE_FORMAT(receipt_date, '%Y-%m') as month,
                    COUNT(*) as count,
                    COALESCE(SUM(amount), 0) as total
                FROM receipt_library
                WHERE deleted_at IS NULL
                  AND receipt_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
                GROUP BY DATE_FORMAT(receipt_date, '%Y-%m')
                ORDER BY month DESC
            """)
            stats.by_month = [
                {'month': row['month'], 'count': row['count'], 'total': float(row['total'])}
                for row in cursor.fetchall()
            ]

            # Top merchants
            cursor.execute("""
                SELECT merchant_normalized, COUNT(*) as count, COALESCE(SUM(amount), 0) as total
                FROM receipt_library
                WHERE deleted_at IS NULL AND merchant_normalized IS NOT NULL
                GROUP BY merchant_normalized
                ORDER BY count DESC
                LIMIT 20
            """)
            stats.top_merchants = [
                {'merchant': row['merchant_normalized'], 'count': row['count'], 'total': float(row['total'])}
                for row in cursor.fetchall()
            ]

            # Special counts
            stats.unmatched_count = stats.by_status.get('ready', 0)
            cursor.execute("""
                SELECT COUNT(*) as count FROM receipt_library
                WHERE deleted_at IS NULL AND needs_review = TRUE
            """)
            stats.needs_review_count = cursor.fetchone()['count']

        return stats

    # -------------------------------------------------------------------------
    # BULK OPERATIONS
    # -------------------------------------------------------------------------

    def bulk_update(self, receipt_ids: List[int], updates: Dict[str, Any], actor: str = "user") -> int:
        """Update multiple receipts at once. Returns count of updated receipts."""
        if not self.db.use_mysql or not receipt_ids or not updates:
            return 0

        updated = 0
        for receipt_id in receipt_ids:
            if self.update_receipt(receipt_id, updates, actor=actor):
                updated += 1

        return updated

    def bulk_delete(self, receipt_ids: List[int], actor: str = "user") -> int:
        """Delete multiple receipts. Returns count of deleted receipts."""
        if not self.db.use_mysql or not receipt_ids:
            return 0

        deleted = 0
        for receipt_id in receipt_ids:
            if self.delete_receipt(receipt_id, actor=actor):
                deleted += 1

        return deleted

    def bulk_set_business_type(self, receipt_ids: List[int], business_type: str, actor: str = "user") -> int:
        """Set business type for multiple receipts."""
        return self.bulk_update(receipt_ids, {'business_type': business_type}, actor=actor)

    def bulk_add_tags(self, receipt_ids: List[int], tags: List[str], actor: str = "user") -> int:
        """Add tags to multiple receipts."""
        if not self.db.use_mysql or not receipt_ids or not tags:
            return 0

        updated = 0
        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            for receipt_id in receipt_ids:
                try:
                    # Get current tags
                    cursor.execute("SELECT tags FROM receipt_library WHERE id = %s", (receipt_id,))
                    row = cursor.fetchone()
                    if not row:
                        continue

                    current_tags = json.loads(row['tags']) if row['tags'] else []
                    new_tags = list(set(current_tags + tags))

                    cursor.execute(
                        "UPDATE receipt_library SET tags = %s WHERE id = %s",
                        (json.dumps(new_tags), receipt_id)
                    )
                    updated += 1

                except Exception as e:
                    logger.error(f"Failed to add tags to receipt {receipt_id}: {e}")

            conn.commit()

        return updated

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _normalize_merchant(self, merchant: str) -> str:
        """Normalize merchant name for consistent matching."""
        if not merchant:
            return ""

        normalized = merchant.lower().strip()

        # Remove common prefixes
        prefixes = ['sq *', 'sq*', 'tst *', 'tst*', 'dd *', 'dd*', 'pp *', 'pp*',
                   'ppl*', 'zzz*', 'chk*', 'pos ', 'pos*']
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()

        # Remove common suffixes
        suffixes = [' inc', ' llc', ' ltd', ' corp', ' co', ' #']
        for suffix in suffixes:
            if suffix in normalized:
                normalized = normalized.split(suffix)[0].strip()

        # Remove trailing numbers (location codes)
        import re
        normalized = re.sub(r'\s+\d+$', '', normalized)

        return normalized.strip()

    def _update_search_index(self, cursor, receipt_id: int, receipt: ReceiptLibraryItem):
        """Update the search index for a receipt."""
        try:
            # Build search text
            search_parts = []
            if receipt.merchant_name:
                search_parts.append(receipt.merchant_name)
            if receipt.merchant_normalized:
                search_parts.append(receipt.merchant_normalized)
            if receipt.ocr_raw_text:
                search_parts.append(receipt.ocr_raw_text[:5000])  # Limit OCR text
            if receipt.ai_description:
                search_parts.append(receipt.ai_description)
            if receipt.user_notes:
                search_parts.append(receipt.user_notes)
            if receipt.order_number:
                search_parts.append(receipt.order_number)

            search_text = ' '.join(search_parts)

            # Merchant tokens
            merchant_tokens = receipt.merchant_normalized or ''
            if receipt.merchant_name:
                merchant_tokens += ' ' + ' '.join(receipt.merchant_name.lower().split())

            # Amount in cents for integer search
            amount_cents = int(float(receipt.amount) * 100) if receipt.amount else None

            # Date components
            year = receipt.receipt_date.year if receipt.receipt_date else None
            month = receipt.receipt_date.month if receipt.receipt_date else None
            day = receipt.receipt_date.day if receipt.receipt_date else None
            date_key = int(receipt.receipt_date.strftime('%Y%m%d')) if receipt.receipt_date else None

            cursor.execute("""
                INSERT INTO receipt_library_search
                (receipt_id, search_text, merchant_tokens, amount_cents, date_key, year, month, day)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                search_text = VALUES(search_text),
                merchant_tokens = VALUES(merchant_tokens),
                amount_cents = VALUES(amount_cents),
                date_key = VALUES(date_key),
                year = VALUES(year),
                month = VALUES(month),
                day = VALUES(day)
            """, (receipt_id, search_text, merchant_tokens, amount_cents, date_key, year, month, day))

        except Exception as e:
            logger.error(f"Failed to update search index for receipt {receipt_id}: {e}")

    def _log_activity(self, cursor, receipt_id: int, action: str,
                     actor: str = "system", old_value: Dict = None, new_value: Dict = None,
                     details: str = None):
        """Log an activity for audit trail."""
        try:
            cursor.execute("""
                INSERT INTO receipt_library_activity
                (receipt_id, action, actor, old_value, new_value, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                receipt_id, action, actor,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
                details
            ))
        except Exception as e:
            logger.error(f"Failed to log activity: {e}")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_library_service = None


def get_library_service() -> ReceiptLibraryService:
    """Get or create the singleton library service."""
    global _library_service
    if _library_service is None:
        _library_service = ReceiptLibraryService()
    return _library_service


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_receipt(receipt: ReceiptLibraryItem) -> Optional[int]:
    """Create a new receipt."""
    return get_library_service().create_receipt(receipt)


def get_receipt(receipt_id: int = None, uuid: str = None) -> Optional[ReceiptLibraryItem]:
    """Get a receipt by ID or UUID."""
    return get_library_service().get_receipt(receipt_id=receipt_id, uuid=uuid)


def search_receipts(query: LibrarySearchQuery) -> Tuple[List[ReceiptLibraryItem], int]:
    """Search receipts."""
    return get_library_service().search_receipts(query)


def get_library_stats() -> LibraryStats:
    """Get library statistics."""
    return get_library_service().get_stats()
