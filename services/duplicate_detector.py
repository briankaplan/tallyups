#!/usr/bin/env python3
"""
Multi-Signal Duplicate Detector
================================
Detects duplicate receipts using multiple signals:
- Perceptual image hashing (pHash)
- Content hash (SHA-256)
- Merchant + Amount + Date matching
- Order number matching
- OCR text similarity

Performance target: 95%+ detection rate, <1% false positives
"""

import os
import io
import hashlib
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
from difflib import SequenceMatcher

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from db_mysql import MySQLReceiptDatabase

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

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DuplicateMatch:
    """A potential duplicate match."""
    receipt_id: int
    duplicate_of_id: int
    confidence: float  # 0.0 - 1.0
    reason: str
    detection_method: str
    details: Dict[str, Any] = None

    def to_dict(self) -> Dict:
        return {
            'receipt_id': self.receipt_id,
            'duplicate_of_id': self.duplicate_of_id,
            'confidence': self.confidence,
            'reason': self.reason,
            'detection_method': self.detection_method,
            'details': self.details or {}
        }


@dataclass
class FingerprintResult:
    """Result of fingerprint generation."""
    content_hash: str
    perceptual_hash: Optional[str] = None
    file_size: int = 0
    image_width: Optional[int] = None
    image_height: Optional[int] = None


# =============================================================================
# DUPLICATE DETECTOR
# =============================================================================

class DuplicateDetector:
    """
    Multi-signal duplicate detector for receipts.

    Uses multiple methods to detect duplicates:
    1. Exact content hash (SHA-256) - 100% confidence
    2. Perceptual image hash (pHash) - High confidence for similar images
    3. Same merchant + amount + date - 90% confidence
    4. Same order number - 95% confidence
    5. OCR text similarity - Variable confidence

    Thresholds are tunable to balance detection rate vs false positives.
    """

    # Detection thresholds
    PHASH_THRESHOLD = 8  # Hamming distance for perceptual hash (lower = more similar)
    TEXT_SIMILARITY_THRESHOLD = 0.85  # Minimum text similarity
    DATE_TOLERANCE_DAYS = 3  # Days of tolerance for date matching
    AMOUNT_TOLERANCE_PERCENT = 0.01  # 1% tolerance for amount matching

    def __init__(self):
        self.db = MySQLReceiptDatabase()

    # -------------------------------------------------------------------------
    # FINGERPRINT GENERATION
    # -------------------------------------------------------------------------

    def generate_fingerprints(self, image_data: bytes) -> FingerprintResult:
        """
        Generate all fingerprints for an image.

        Returns content hash and perceptual hash.
        """
        result = FingerprintResult(
            content_hash=self._compute_content_hash(image_data),
            file_size=len(image_data)
        )

        if HAS_PIL:
            try:
                img = Image.open(io.BytesIO(image_data))
                result.image_width, result.image_height = img.size

                if HAS_IMAGEHASH:
                    result.perceptual_hash = str(imagehash.phash(img))
            except Exception as e:
                logger.warning(f"Failed to process image for fingerprinting: {e}")

        return result

    def generate_fingerprints_from_url(self, url: str) -> Optional[FingerprintResult]:
        """Generate fingerprints from a URL."""
        if not HAS_REQUESTS:
            logger.warning("requests library not available")
            return None

        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return self.generate_fingerprints(response.content)
        except Exception as e:
            logger.error(f"Failed to fetch image from {url}: {e}")

        return None

    def generate_fingerprints_from_file(self, file_path: Path) -> Optional[FingerprintResult]:
        """Generate fingerprints from a local file."""
        try:
            with open(file_path, 'rb') as f:
                return self.generate_fingerprints(f.read())
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return None

    # -------------------------------------------------------------------------
    # DUPLICATE DETECTION
    # -------------------------------------------------------------------------

    def find_duplicates(
        self,
        receipt_id: int = None,
        fingerprint: str = None,
        content_hash: str = None,
        merchant_normalized: str = None,
        amount: Decimal = None,
        receipt_date: date = None,
        order_number: str = None,
        ocr_text: str = None,
        exclude_ids: List[int] = None
    ) -> List[DuplicateMatch]:
        """
        Find potential duplicates of a receipt.

        Can search by:
        - Receipt ID (will look up fingerprints)
        - Direct fingerprints/hashes
        - Merchant + amount + date
        - Order number
        - OCR text similarity

        Returns list of potential duplicates sorted by confidence.
        """
        if not self.db.use_mysql:
            return []

        candidates = []
        exclude_ids = exclude_ids or []
        if receipt_id:
            exclude_ids.append(receipt_id)

        # If receipt_id provided, look up its data
        if receipt_id:
            with self.db.pooled_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT fingerprint, content_hash, merchant_normalized,
                           amount, receipt_date, order_number, ocr_raw_text
                    FROM receipt_library WHERE id = %s
                """, (receipt_id,))
                row = cursor.fetchone()
                if row:
                    fingerprint = fingerprint or row.get('fingerprint')
                    content_hash = content_hash or row.get('content_hash')
                    merchant_normalized = merchant_normalized or row.get('merchant_normalized')
                    amount = amount or row.get('amount')
                    receipt_date = receipt_date or row.get('receipt_date')
                    order_number = order_number or row.get('order_number')
                    ocr_text = ocr_text or row.get('ocr_raw_text')

        # 1. Exact content hash match (100% confidence)
        if content_hash:
            hash_matches = self._find_by_content_hash(content_hash, exclude_ids)
            for match_id in hash_matches:
                candidates.append(DuplicateMatch(
                    receipt_id=receipt_id or 0,
                    duplicate_of_id=match_id,
                    confidence=1.0,
                    reason="Identical file content (SHA-256 match)",
                    detection_method="content_hash"
                ))

        # 2. Perceptual hash similarity
        if fingerprint and HAS_IMAGEHASH:
            phash_matches = self._find_by_perceptual_hash(fingerprint, exclude_ids)
            for match_id, distance in phash_matches:
                if match_id not in [c.duplicate_of_id for c in candidates]:
                    # Convert distance to confidence (0 distance = 100% confidence)
                    confidence = max(0, 1.0 - (distance / 64.0))
                    if confidence >= 0.7:  # Only include high confidence matches
                        candidates.append(DuplicateMatch(
                            receipt_id=receipt_id or 0,
                            duplicate_of_id=match_id,
                            confidence=confidence,
                            reason=f"Image similarity: {confidence:.0%} (hamming distance: {distance})",
                            detection_method="perceptual_hash",
                            details={'hamming_distance': distance}
                        ))

        # 3. Same merchant + amount + date
        if merchant_normalized and amount and receipt_date:
            tx_matches = self._find_by_transaction_data(
                merchant_normalized, amount, receipt_date, exclude_ids
            )
            for match in tx_matches:
                if match['id'] not in [c.duplicate_of_id for c in candidates]:
                    candidates.append(DuplicateMatch(
                        receipt_id=receipt_id or 0,
                        duplicate_of_id=match['id'],
                        confidence=0.90,
                        reason=f"Same merchant ({merchant_normalized}), amount (${amount}), and date",
                        detection_method="transaction_match",
                        details={
                            'merchant_match': True,
                            'amount_match': True,
                            'date_diff_days': match.get('date_diff', 0)
                        }
                    ))

        # 4. Same order number
        if order_number:
            order_matches = self._find_by_order_number(order_number, exclude_ids)
            for match_id in order_matches:
                if match_id not in [c.duplicate_of_id for c in candidates]:
                    candidates.append(DuplicateMatch(
                        receipt_id=receipt_id or 0,
                        duplicate_of_id=match_id,
                        confidence=0.95,
                        reason=f"Same order number: {order_number}",
                        detection_method="order_number"
                    ))

        # 5. OCR text similarity (if no other matches found)
        if ocr_text and len(candidates) < 3:
            text_matches = self._find_by_text_similarity(
                ocr_text, exclude_ids + [c.duplicate_of_id for c in candidates]
            )
            for match_id, similarity in text_matches:
                if similarity >= self.TEXT_SIMILARITY_THRESHOLD:
                    candidates.append(DuplicateMatch(
                        receipt_id=receipt_id or 0,
                        duplicate_of_id=match_id,
                        confidence=similarity * 0.85,  # Scale down slightly
                        reason=f"OCR text similarity: {similarity:.0%}",
                        detection_method="text_similarity",
                        details={'text_similarity': similarity}
                    ))

        # Sort by confidence
        candidates.sort(key=lambda x: x.confidence, reverse=True)

        return candidates

    def is_duplicate(self, receipt_id: int, threshold: float = 0.85) -> Tuple[bool, Optional[DuplicateMatch]]:
        """
        Check if a receipt is a duplicate.

        Returns (is_duplicate, best_match).
        """
        matches = self.find_duplicates(receipt_id=receipt_id)
        if matches and matches[0].confidence >= threshold:
            return True, matches[0]
        return False, None

    def mark_as_duplicate(self, receipt_id: int, duplicate_of_id: int,
                         confidence: float, reason: str, method: str) -> bool:
        """Mark a receipt as a duplicate in the database."""
        if not self.db.use_mysql:
            return False

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            try:
                # Update receipt status
                cursor.execute("""
                    UPDATE receipt_library
                    SET status = 'duplicate', duplicate_of_id = %s
                    WHERE id = %s
                """, (duplicate_of_id, receipt_id))

                # Record in duplicates table
                cursor.execute("""
                    INSERT INTO receipt_library_duplicates
                    (receipt_id, duplicate_of_id, confidence, reason, detection_method)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    confidence = VALUES(confidence),
                    reason = VALUES(reason),
                    detection_method = VALUES(detection_method)
                """, (receipt_id, duplicate_of_id, confidence, reason, method))

                conn.commit()
                return True

            except Exception as e:
                logger.error(f"Failed to mark duplicate: {e}")
                conn.rollback()
                return False

    def resolve_duplicate(
        self,
        receipt_id: int,
        action: str,  # 'keep_both', 'keep_original', 'keep_duplicate', 'merge'
        actor: str = "user"
    ) -> bool:
        """Resolve a duplicate detection."""
        if not self.db.use_mysql:
            return False

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    UPDATE receipt_library_duplicates
                    SET resolved = TRUE,
                        resolved_at = NOW(),
                        resolved_action = %s
                    WHERE receipt_id = %s
                """, (action, receipt_id))

                if action == 'keep_original':
                    # Delete the duplicate
                    cursor.execute("""
                        UPDATE receipt_library SET deleted_at = NOW(), status = 'archived'
                        WHERE id = %s
                    """, (receipt_id,))
                elif action == 'keep_both':
                    # Clear duplicate status
                    cursor.execute("""
                        UPDATE receipt_library
                        SET status = 'ready', duplicate_of_id = NULL
                        WHERE id = %s
                    """, (receipt_id,))

                conn.commit()
                return True

            except Exception as e:
                logger.error(f"Failed to resolve duplicate: {e}")
                conn.rollback()
                return False

    # -------------------------------------------------------------------------
    # BATCH PROCESSING
    # -------------------------------------------------------------------------

    def scan_all_for_duplicates(self, limit: int = 1000) -> List[DuplicateMatch]:
        """
        Scan all receipts for duplicates.

        Useful for initial setup or periodic cleanup.
        """
        if not self.db.use_mysql:
            return []

        all_duplicates = []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Get receipts that haven't been checked
            cursor.execute("""
                SELECT id FROM receipt_library
                WHERE deleted_at IS NULL
                  AND status != 'duplicate'
                  AND id NOT IN (
                      SELECT receipt_id FROM receipt_library_duplicates WHERE resolved = FALSE
                  )
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))

            receipt_ids = [row['id'] for row in cursor.fetchall()]

        logger.info(f"Scanning {len(receipt_ids)} receipts for duplicates...")

        for i, receipt_id in enumerate(receipt_ids):
            if i % 100 == 0:
                logger.info(f"Progress: {i}/{len(receipt_ids)}")

            matches = self.find_duplicates(receipt_id=receipt_id)
            for match in matches:
                if match.confidence >= 0.85:
                    all_duplicates.append(match)
                    # Auto-mark high confidence duplicates
                    if match.confidence >= 0.95:
                        self.mark_as_duplicate(
                            match.receipt_id,
                            match.duplicate_of_id,
                            match.confidence,
                            match.reason,
                            match.detection_method
                        )

        logger.info(f"Found {len(all_duplicates)} potential duplicates")
        return all_duplicates

    # -------------------------------------------------------------------------
    # PRIVATE METHODS
    # -------------------------------------------------------------------------

    def _compute_content_hash(self, data: bytes) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(data).hexdigest()

    def _compute_hamming_distance(self, hash1: str, hash2: str) -> int:
        """Compute hamming distance between two hex hash strings."""
        if not hash1 or not hash2:
            return 64  # Maximum distance

        try:
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)
            return h1 - h2
        except Exception:
            return 64

    def _find_by_content_hash(self, content_hash: str, exclude_ids: List[int]) -> List[int]:
        """Find receipts with matching content hash."""
        if not self.db.use_mysql:
            return []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            exclude_clause = ""
            if exclude_ids:
                placeholders = ','.join(['%s'] * len(exclude_ids))
                exclude_clause = f"AND id NOT IN ({placeholders})"

            cursor.execute(f"""
                SELECT id FROM receipt_library
                WHERE content_hash = %s
                  AND deleted_at IS NULL
                  {exclude_clause}
            """, [content_hash] + (exclude_ids or []))

            return [row['id'] for row in cursor.fetchall()]

    def _find_by_perceptual_hash(
        self, fingerprint: str, exclude_ids: List[int]
    ) -> List[Tuple[int, int]]:
        """Find receipts with similar perceptual hash."""
        if not self.db.use_mysql or not HAS_IMAGEHASH:
            return []

        matches = []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            exclude_clause = ""
            if exclude_ids:
                placeholders = ','.join(['%s'] * len(exclude_ids))
                exclude_clause = f"AND id NOT IN ({placeholders})"

            cursor.execute(f"""
                SELECT id, fingerprint FROM receipt_library
                WHERE fingerprint IS NOT NULL
                  AND deleted_at IS NULL
                  {exclude_clause}
                LIMIT 5000
            """, exclude_ids or [])

            for row in cursor.fetchall():
                distance = self._compute_hamming_distance(fingerprint, row['fingerprint'])
                if distance <= self.PHASH_THRESHOLD:
                    matches.append((row['id'], distance))

        # Sort by distance (lower = more similar)
        matches.sort(key=lambda x: x[1])
        return matches[:10]  # Return top 10

    def _find_by_transaction_data(
        self, merchant: str, amount: Decimal, receipt_date: date, exclude_ids: List[int]
    ) -> List[Dict]:
        """Find receipts with matching transaction data."""
        if not self.db.use_mysql:
            return []

        matches = []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Calculate amount tolerance
            amount_float = float(amount)
            amount_min = amount_float * (1 - self.AMOUNT_TOLERANCE_PERCENT)
            amount_max = amount_float * (1 + self.AMOUNT_TOLERANCE_PERCENT)

            # Date range
            date_min = receipt_date - timedelta(days=self.DATE_TOLERANCE_DAYS)
            date_max = receipt_date + timedelta(days=self.DATE_TOLERANCE_DAYS)

            exclude_clause = ""
            params = [merchant, amount_min, amount_max, date_min, date_max]
            if exclude_ids:
                placeholders = ','.join(['%s'] * len(exclude_ids))
                exclude_clause = f"AND id NOT IN ({placeholders})"
                params.extend(exclude_ids)

            cursor.execute(f"""
                SELECT id, merchant_normalized, amount, receipt_date
                FROM receipt_library
                WHERE merchant_normalized = %s
                  AND amount BETWEEN %s AND %s
                  AND receipt_date BETWEEN %s AND %s
                  AND deleted_at IS NULL
                  {exclude_clause}
            """, params)

            for row in cursor.fetchall():
                date_diff = abs((row['receipt_date'] - receipt_date).days) if row['receipt_date'] else 0
                matches.append({
                    'id': row['id'],
                    'date_diff': date_diff
                })

        return matches

    def _find_by_order_number(self, order_number: str, exclude_ids: List[int]) -> List[int]:
        """Find receipts with matching order number."""
        if not self.db.use_mysql or not order_number:
            return []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            exclude_clause = ""
            if exclude_ids:
                placeholders = ','.join(['%s'] * len(exclude_ids))
                exclude_clause = f"AND id NOT IN ({placeholders})"

            cursor.execute(f"""
                SELECT id FROM receipt_library
                WHERE order_number = %s
                  AND deleted_at IS NULL
                  {exclude_clause}
            """, [order_number] + (exclude_ids or []))

            return [row['id'] for row in cursor.fetchall()]

    def _find_by_text_similarity(
        self, ocr_text: str, exclude_ids: List[int], limit: int = 100
    ) -> List[Tuple[int, float]]:
        """Find receipts with similar OCR text."""
        if not self.db.use_mysql or not ocr_text:
            return []

        # Normalize text for comparison
        text_normalized = ' '.join(ocr_text.lower().split())[:1000]

        matches = []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            exclude_clause = ""
            params = []
            if exclude_ids:
                placeholders = ','.join(['%s'] * len(exclude_ids))
                exclude_clause = f"AND id NOT IN ({placeholders})"
                params.extend(exclude_ids)

            # Get candidate receipts (with OCR text)
            cursor.execute(f"""
                SELECT id, SUBSTRING(ocr_raw_text, 1, 1000) as ocr_text
                FROM receipt_library
                WHERE ocr_raw_text IS NOT NULL
                  AND LENGTH(ocr_raw_text) > 50
                  AND deleted_at IS NULL
                  {exclude_clause}
                ORDER BY created_at DESC
                LIMIT %s
            """, params + [limit])

            for row in cursor.fetchall():
                if row['ocr_text']:
                    candidate_text = ' '.join(row['ocr_text'].lower().split())
                    similarity = SequenceMatcher(
                        None, text_normalized, candidate_text
                    ).ratio()
                    if similarity >= self.TEXT_SIMILARITY_THRESHOLD:
                        matches.append((row['id'], similarity))

        # Sort by similarity
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:10]


# =============================================================================
# SINGLETON AND CONVENIENCE FUNCTIONS
# =============================================================================

_detector = None


def get_duplicate_detector() -> DuplicateDetector:
    """Get or create the singleton detector."""
    global _detector
    if _detector is None:
        _detector = DuplicateDetector()
    return _detector


def find_duplicates(receipt_id: int) -> List[DuplicateMatch]:
    """Find potential duplicates of a receipt."""
    return get_duplicate_detector().find_duplicates(receipt_id=receipt_id)


def is_duplicate(receipt_id: int) -> Tuple[bool, Optional[DuplicateMatch]]:
    """Check if a receipt is a duplicate."""
    return get_duplicate_detector().is_duplicate(receipt_id)


def generate_fingerprints(image_data: bytes) -> FingerprintResult:
    """Generate fingerprints for image data."""
    return get_duplicate_detector().generate_fingerprints(image_data)
