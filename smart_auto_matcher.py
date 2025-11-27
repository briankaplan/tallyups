#!/usr/bin/env python3
"""
Smart Auto-Matcher Service
Automatically matches receipts from Gmail to bank transactions with duplicate detection.

Features:
- Smart matching using amount + date + merchant similarity
- Content-based duplicate detection using perceptual hashing
- Learning from past matches and rejections
- Confidence scoring with configurable thresholds
"""

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from io import BytesIO
from typing import Optional, Dict, List, Tuple
from PIL import Image
import requests

# Database imports
try:
    import pymysql
    from urllib.parse import urlparse
except ImportError:
    pymysql = None

# ============================================================================
# CONFIGURATION
# ============================================================================

# Matching thresholds
AUTO_MATCH_THRESHOLD = 0.75  # 75%+ confidence = auto-attach
REVIEW_THRESHOLD = 0.50     # 50-75% = needs review
DUPLICATE_SIMILARITY = 0.95  # 95%+ similar = duplicate

# Date tolerance (days)
DATE_TOLERANCE_RETAIL = 3       # Retail purchases
DATE_TOLERANCE_SUBSCRIPTION = 7  # Subscriptions can vary
DATE_TOLERANCE_DELIVERY = 14     # Food delivery can charge later

# Amount tolerance
AMOUNT_EXACT = 0.01        # $0.01 = exact match
AMOUNT_CLOSE = 2.00        # $2.00 = very close (fees)
AMOUNT_TIP_VARIANCE = 0.25  # 25% = restaurant tip variance

# ============================================================================
# DUPLICATE DETECTION
# ============================================================================

def compute_image_hash(image_data: bytes) -> str:
    """
    Compute a perceptual hash for an image.
    Uses average hash (aHash) for speed and robustness to minor changes.
    """
    try:
        img = Image.open(BytesIO(image_data))
        # Convert to grayscale and resize to 8x8
        img = img.convert('L').resize((8, 8), Image.Resampling.LANCZOS)

        # Get pixel data
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)

        # Create hash: 1 if pixel > average, 0 otherwise
        bits = ''.join('1' if p > avg else '0' for p in pixels)
        return hex(int(bits, 2))[2:].zfill(16)
    except Exception as e:
        # Fallback to content hash
        return hashlib.md5(image_data).hexdigest()[:16]


def compute_content_hash(content: bytes) -> str:
    """Compute SHA256 hash of raw content for exact duplicate detection."""
    return hashlib.sha256(content).hexdigest()


def hamming_distance(hash1: str, hash2: str) -> int:
    """Calculate Hamming distance between two hex hashes."""
    if len(hash1) != len(hash2):
        return 64  # Max distance

    # Convert hex to binary and count differing bits
    try:
        b1 = bin(int(hash1, 16))[2:].zfill(64)
        b2 = bin(int(hash2, 16))[2:].zfill(64)
        return sum(c1 != c2 for c1, c2 in zip(b1, b2))
    except ValueError:
        return 64


def are_images_similar(hash1: str, hash2: str, threshold: int = 10) -> bool:
    """
    Check if two images are visually similar using perceptual hash.
    Lower hamming distance = more similar.
    threshold=10 means ~85% similar (10 of 64 bits different)
    """
    return hamming_distance(hash1, hash2) <= threshold


class DuplicateDetector:
    """Detects duplicate receipts using multiple strategies."""

    def __init__(self, db_connection=None):
        self.db = db_connection
        self.hash_cache = {}  # In-memory cache of known hashes

    def load_existing_hashes(self):
        """Load existing receipt hashes from database."""
        if not self.db:
            return

        try:
            cursor = self.db.cursor()
            cursor.execute('''
                SELECT receipt_file, content_hash, perceptual_hash
                FROM receipt_hashes
            ''')
            for row in cursor.fetchall():
                self.hash_cache[row['receipt_file']] = {
                    'content': row['content_hash'],
                    'perceptual': row['perceptual_hash']
                }
        except Exception as e:
            print(f"Could not load hashes: {e}")

    def is_duplicate(self, image_data: bytes, filename: str) -> Tuple[bool, Optional[str]]:
        """
        Check if an image is a duplicate of an existing receipt.
        Returns (is_duplicate, matching_file_if_duplicate)
        """
        content_hash = compute_content_hash(image_data)
        perceptual_hash = compute_image_hash(image_data)

        # Check exact duplicates first (fast)
        for existing_file, hashes in self.hash_cache.items():
            if hashes.get('content') == content_hash:
                return True, existing_file

        # Check perceptual similarity (catches resized/recompressed)
        for existing_file, hashes in self.hash_cache.items():
            if hashes.get('perceptual'):
                if are_images_similar(perceptual_hash, hashes['perceptual']):
                    return True, existing_file

        # Not a duplicate - add to cache
        self.hash_cache[filename] = {
            'content': content_hash,
            'perceptual': perceptual_hash
        }

        return False, None

    def store_hash(self, filename: str, image_data: bytes):
        """Store hash for a new receipt in the database."""
        if not self.db:
            return

        content_hash = compute_content_hash(image_data)
        perceptual_hash = compute_image_hash(image_data)

        try:
            cursor = self.db.cursor()
            cursor.execute('''
                INSERT INTO receipt_hashes (receipt_file, content_hash, perceptual_hash, created_at)
                VALUES (%s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    content_hash = VALUES(content_hash),
                    perceptual_hash = VALUES(perceptual_hash)
            ''', (filename, content_hash, perceptual_hash))
            self.db.commit()
        except Exception as e:
            print(f"Could not store hash: {e}")


# ============================================================================
# SMART MATCHING
# ============================================================================

def normalize_merchant(merchant: str) -> str:
    """Normalize merchant name for matching."""
    if not merchant:
        return ""

    # Lowercase
    merchant = merchant.lower().strip()

    # Remove common prefixes/suffixes
    prefixes = ['sq*', 'sq ', 'tst*', 'tst ', 'dd*', 'dd ', 'zzz*', 'ppl*']
    for prefix in prefixes:
        if merchant.startswith(prefix):
            merchant = merchant[len(prefix):]

    # Remove location suffixes
    merchant = re.sub(r'\s*#\d+.*$', '', merchant)
    merchant = re.sub(r'\s+\d{5}.*$', '', merchant)  # ZIP codes
    merchant = re.sub(r'\s+[A-Z]{2}\s*$', '', merchant)  # State codes

    # Remove special characters
    merchant = re.sub(r'[^a-z0-9\s]', ' ', merchant)
    merchant = re.sub(r'\s+', ' ', merchant).strip()

    return merchant


def parse_amount(amount_str) -> float:
    """Parse amount from various formats."""
    if isinstance(amount_str, (int, float)):
        return float(amount_str)
    if not amount_str:
        return 0.0

    # Remove currency symbols and commas
    amount_str = str(amount_str)
    amount_str = re.sub(r'[$,]', '', amount_str)

    try:
        return abs(float(amount_str))
    except ValueError:
        return 0.0


def parse_date(date_str) -> Optional[datetime]:
    """Parse date from various formats."""
    if isinstance(date_str, datetime):
        return date_str
    if not date_str:
        return None

    formats = [
        '%Y-%m-%d',
        '%m/%d/%Y',
        '%m/%d/%y',
        '%d/%m/%Y',
        '%Y/%m/%d',
        '%b %d, %Y',
        '%B %d, %Y',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except ValueError:
            continue

    return None


def calculate_amount_score(receipt_amount: float, transaction_amount: float) -> float:
    """
    Calculate how well amounts match.
    Returns 0.0 to 1.0
    """
    if receipt_amount == 0 or transaction_amount == 0:
        return 0.0

    diff = abs(receipt_amount - transaction_amount)

    # Exact match
    if diff <= AMOUNT_EXACT:
        return 1.0

    # Very close (fees, rounding)
    if diff <= AMOUNT_CLOSE:
        return 0.95

    # Check for tip variance (restaurant)
    if transaction_amount > receipt_amount:
        tip_ratio = (transaction_amount - receipt_amount) / receipt_amount
        if 0.10 <= tip_ratio <= AMOUNT_TIP_VARIANCE:
            return 0.90  # Likely includes tip

    # Percentage difference
    pct_diff = diff / max(receipt_amount, transaction_amount)

    if pct_diff <= 0.02:  # 2%
        return 0.90
    elif pct_diff <= 0.05:  # 5%
        return 0.80
    elif pct_diff <= 0.10:  # 10%
        return 0.60
    elif pct_diff <= 0.20:  # 20%
        return 0.30
    else:
        return 0.0


def calculate_merchant_score(receipt_merchant: str, transaction_merchant: str) -> float:
    """
    Calculate how well merchant names match.
    Returns 0.0 to 1.0
    """
    rm = normalize_merchant(receipt_merchant)
    tm = normalize_merchant(transaction_merchant)

    if not rm or not tm:
        return 0.0

    # Exact match
    if rm == tm:
        return 1.0

    # One contains the other
    if rm in tm or tm in rm:
        return 0.90

    # Sequence matching
    ratio = SequenceMatcher(None, rm, tm).ratio()

    # Boost if first word matches (usually the brand)
    rm_words = rm.split()
    tm_words = tm.split()
    if rm_words and tm_words and rm_words[0] == tm_words[0]:
        ratio = min(1.0, ratio + 0.15)

    return ratio


def calculate_date_score(receipt_date: datetime, transaction_date: datetime,
                         is_subscription: bool = False, is_delivery: bool = False) -> float:
    """
    Calculate how well dates match.
    Returns 0.0 to 1.0
    """
    if not receipt_date or not transaction_date:
        return 0.5  # Neutral if we don't have dates

    days_diff = abs((receipt_date - transaction_date).days)

    # Select tolerance based on transaction type
    if is_delivery:
        tolerance = DATE_TOLERANCE_DELIVERY
    elif is_subscription:
        tolerance = DATE_TOLERANCE_SUBSCRIPTION
    else:
        tolerance = DATE_TOLERANCE_RETAIL

    if days_diff == 0:
        return 1.0
    elif days_diff <= 1:
        return 0.95
    elif days_diff <= tolerance:
        return 0.80
    elif days_diff <= tolerance * 2:
        return 0.50
    else:
        return 0.0


def is_subscription_merchant(merchant: str) -> bool:
    """Check if merchant is a known subscription service."""
    subscription_keywords = [
        'anthropic', 'openai', 'midjourney', 'spotify', 'netflix', 'hulu',
        'apple', 'icloud', 'google', 'microsoft', 'adobe', 'figma',
        'dropbox', 'github', 'notion', 'slack', 'zoom', 'cursor',
        'railway', 'vercel', 'cloudflare', 'aws', 'digitalocean'
    ]
    merchant_lower = merchant.lower() if merchant else ''
    return any(kw in merchant_lower for kw in subscription_keywords)


def is_delivery_merchant(merchant: str) -> bool:
    """Check if merchant is a food delivery service."""
    delivery_keywords = [
        'doordash', 'dd*', 'uber eats', 'grubhub', 'postmates',
        'seamless', 'caviar', 'instacart'
    ]
    merchant_lower = merchant.lower() if merchant else ''
    return any(kw in merchant_lower for kw in delivery_keywords)


class SmartAutoMatcher:
    """
    Intelligent receipt-to-transaction matcher.
    Uses amount, date, and merchant similarity with configurable weights.
    """

    def __init__(self, db_connection=None):
        self.db = db_connection
        self.duplicate_detector = DuplicateDetector(db_connection)

    def calculate_match_score(self, receipt: Dict, transaction: Dict) -> Tuple[float, Dict]:
        """
        Calculate overall match score between a receipt and transaction.
        Returns (score, details_dict)
        """
        # Parse values
        receipt_amount = parse_amount(receipt.get('amount'))
        receipt_merchant = receipt.get('merchant', '')
        receipt_date = parse_date(receipt.get('date') or receipt.get('transaction_date'))

        tx_amount = parse_amount(transaction.get('chase_amount') or transaction.get('amount'))
        tx_merchant = transaction.get('chase_description') or transaction.get('merchant', '')
        tx_date = parse_date(transaction.get('chase_date') or transaction.get('date'))

        # Determine transaction type for date tolerance
        is_sub = is_subscription_merchant(tx_merchant) or receipt.get('is_subscription', False)
        is_delivery = is_delivery_merchant(tx_merchant)

        # Calculate individual scores
        amount_score = calculate_amount_score(receipt_amount, tx_amount)
        merchant_score = calculate_merchant_score(receipt_merchant, tx_merchant)
        date_score = calculate_date_score(receipt_date, tx_date, is_sub, is_delivery)

        # Weighted combination
        # Amount is most important, then merchant, then date
        if amount_score >= 0.90:
            # Near-exact amount = trust it heavily
            weights = {'amount': 0.60, 'merchant': 0.30, 'date': 0.10}
        elif merchant_score >= 0.80:
            # Strong merchant match = balance weights
            weights = {'amount': 0.45, 'merchant': 0.40, 'date': 0.15}
        else:
            # Default weights
            weights = {'amount': 0.50, 'merchant': 0.35, 'date': 0.15}

        total_score = (
            amount_score * weights['amount'] +
            merchant_score * weights['merchant'] +
            date_score * weights['date']
        )

        details = {
            'amount_score': round(amount_score, 3),
            'merchant_score': round(merchant_score, 3),
            'date_score': round(date_score, 3),
            'weights': weights,
            'total_score': round(total_score, 3),
            'receipt_amount': receipt_amount,
            'tx_amount': tx_amount,
            'receipt_merchant': receipt_merchant,
            'tx_merchant': tx_merchant,
            'is_subscription': is_sub,
            'is_delivery': is_delivery
        }

        return total_score, details

    def find_best_match(self, receipt: Dict, transactions: List[Dict],
                        exclude_with_receipts: bool = True) -> Optional[Tuple[Dict, float, Dict]]:
        """
        Find the best matching transaction for a receipt.
        Returns (best_transaction, score, details) or None
        """
        best_match = None
        best_score = 0.0
        best_details = None

        for tx in transactions:
            # Skip transactions that already have receipts
            if exclude_with_receipts:
                if tx.get('receipt_file') or tx.get('receipt_url'):
                    continue

            score, details = self.calculate_match_score(receipt, tx)

            if score > best_score:
                best_score = score
                best_match = tx
                best_details = details

        if best_score >= REVIEW_THRESHOLD:
            return best_match, best_score, best_details

        return None

    def find_matches_for_receipts(self, receipts: List[Dict], transactions: List[Dict]) -> List[Dict]:
        """
        Find matches for multiple receipts.
        Handles conflicts where multiple receipts could match same transaction.
        Returns list of match results.
        """
        results = []
        matched_tx_ids = set()

        # Sort receipts by confidence (if available) to prioritize better receipts
        sorted_receipts = sorted(
            receipts,
            key=lambda r: r.get('confidence_score', 50),
            reverse=True
        )

        for receipt in sorted_receipts:
            # Filter out already-matched transactions
            available_txs = [
                tx for tx in transactions
                if tx.get('_index') not in matched_tx_ids
            ]

            match_result = self.find_best_match(receipt, available_txs)

            if match_result:
                tx, score, details = match_result
                tx_id = tx.get('_index')

                result = {
                    'receipt': receipt,
                    'transaction': tx,
                    'score': score,
                    'details': details,
                    'auto_match': score >= AUTO_MATCH_THRESHOLD,
                    'needs_review': REVIEW_THRESHOLD <= score < AUTO_MATCH_THRESHOLD
                }

                results.append(result)
                matched_tx_ids.add(tx_id)
            else:
                results.append({
                    'receipt': receipt,
                    'transaction': None,
                    'score': 0.0,
                    'details': None,
                    'auto_match': False,
                    'needs_review': False,
                    'no_match_found': True
                })

        return results

    def check_duplicate_receipt(self, image_data: bytes, filename: str) -> Dict:
        """
        Check if a receipt image is a duplicate.
        Returns status dict.
        """
        is_dup, matching_file = self.duplicate_detector.is_duplicate(image_data, filename)

        return {
            'is_duplicate': is_dup,
            'matching_file': matching_file,
            'filename': filename
        }


# ============================================================================
# DATABASE INTEGRATION
# ============================================================================

def get_mysql_connection():
    """Get MySQL connection from environment."""
    mysql_url = os.getenv('MYSQL_URL') or os.getenv('DATABASE_URL')
    if not mysql_url or not pymysql:
        return None

    parsed = urlparse(mysql_url)
    return pymysql.connect(
        host=parsed.hostname,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip('/'),
        port=parsed.port or 3306,
        cursorclass=pymysql.cursors.DictCursor
    )


def ensure_hash_table(conn):
    """Create receipt_hashes table if it doesn't exist."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS receipt_hashes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            receipt_file VARCHAR(500) UNIQUE,
            content_hash VARCHAR(64),
            perceptual_hash VARCHAR(16),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_content_hash (content_hash),
            INDEX idx_perceptual_hash (perceptual_hash)
        )
    ''')
    conn.commit()

    # Also ensure incoming_receipts has match_score column
    try:
        cursor.execute("DESCRIBE incoming_receipts")
        columns = [row[0] if isinstance(row, tuple) else row.get('Field', '') for row in cursor.fetchall()]
        if 'match_score' not in columns:
            cursor.execute("ALTER TABLE incoming_receipts ADD COLUMN match_score DECIMAL(5,4)")
            conn.commit()
            print("Added match_score column to incoming_receipts")
    except Exception as e:
        print(f"Note: Could not check/add match_score column: {e}")


def get_unmatched_transactions(conn, days_back: int = 90) -> List[Dict]:
    """Get transactions without receipts from the last N days."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT _index, chase_date, chase_description, chase_amount,
               business_type, notes, receipt_file, receipt_url
        FROM transactions
        WHERE (receipt_file IS NULL OR receipt_file = '')
        AND (receipt_url IS NULL OR receipt_url = '')
        AND chase_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        ORDER BY chase_date DESC
    ''', (days_back,))
    return cursor.fetchall()


def get_pending_receipts(conn) -> List[Dict]:
    """Get incoming receipts that haven't been matched yet."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, email_id, gmail_account, subject, from_email,
               merchant, amount, transaction_date, received_date,
               confidence_score, is_subscription, attachments, receipt_files,
               status, match_type, matched_transaction_id
        FROM incoming_receipts
        WHERE status = 'pending'
        AND confidence_score >= 60
        ORDER BY received_date DESC
    ''')
    return cursor.fetchall()


def auto_match_pending_receipts(conn) -> Dict:
    """
    Main function: Auto-match pending incoming receipts to transactions.
    Returns summary of matches made.
    """
    matcher = SmartAutoMatcher(conn)

    # Get data
    transactions = get_unmatched_transactions(conn)
    receipts = get_pending_receipts(conn)

    if not transactions:
        return {'status': 'no_transactions', 'message': 'No unmatched transactions found'}

    if not receipts:
        return {'status': 'no_receipts', 'message': 'No pending receipts found'}

    # Convert receipts to matcher format
    receipt_dicts = []
    for r in receipts:
        receipt_dicts.append({
            'id': r['id'],
            'email_id': r['email_id'],
            'merchant': r['merchant'],
            'amount': r['amount'],
            'date': r['transaction_date'],
            'confidence_score': r['confidence_score'],
            'is_subscription': r['is_subscription'],
            'receipt_files': r['receipt_files']
        })

    # Find matches
    matches = matcher.find_matches_for_receipts(receipt_dicts, transactions)

    # Process results
    auto_matched = 0
    needs_review = 0
    no_match = 0

    cursor = conn.cursor()

    for match in matches:
        if match.get('no_match_found'):
            no_match += 1
            continue

        receipt = match['receipt']
        tx = match['transaction']
        score = match['score']

        if match['auto_match']:
            # High confidence - auto attach
            auto_matched += 1

            # Update incoming_receipts
            cursor.execute('''
                UPDATE incoming_receipts
                SET status = 'auto_matched',
                    matched_transaction_id = %s,
                    match_score = %s
                WHERE id = %s
            ''', (tx['_index'], score, receipt['id']))

            # Get receipt URL from incoming receipt files
            receipt_files = json.loads(receipt.get('receipt_files', '[]')) if isinstance(receipt.get('receipt_files'), str) else receipt.get('receipt_files', [])
            receipt_url = receipt_files[0] if receipt_files else None

            if receipt_url:
                # Attach receipt to transaction
                cursor.execute('''
                    UPDATE transactions
                    SET receipt_url = %s,
                        ai_note = CONCAT(IFNULL(ai_note, ''), ' [Auto-matched: ', %s, '% confidence]')
                    WHERE _index = %s
                ''', (receipt_url, int(score * 100), tx['_index']))

        elif match['needs_review']:
            # Medium confidence - mark for review
            needs_review += 1
            cursor.execute('''
                UPDATE incoming_receipts
                SET match_type = 'needs_review',
                    matched_transaction_id = %s,
                    match_score = %s
                WHERE id = %s
            ''', (tx['_index'], score, receipt['id']))

    conn.commit()

    return {
        'status': 'success',
        'total_receipts': len(receipts),
        'total_transactions': len(transactions),
        'auto_matched': auto_matched,
        'needs_review': needs_review,
        'no_match': no_match,
        'matches': [
            {
                'receipt_merchant': m['receipt'].get('merchant'),
                'tx_merchant': m['transaction'].get('chase_description') if m.get('transaction') else None,
                'score': m['score'],
                'auto_match': m.get('auto_match', False)
            }
            for m in matches if not m.get('no_match_found')
        ][:20]  # Limit to first 20 for response size
    }


# ============================================================================
# CLI & TESTING
# ============================================================================

if __name__ == '__main__':
    import sys

    print("Smart Auto-Matcher Service")
    print("=" * 50)

    # Test duplicate detection
    print("\nTesting duplicate detection...")
    detector = DuplicateDetector()

    # Test with sample data
    test_image = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100  # Fake PNG header
    is_dup, match = detector.is_duplicate(test_image, 'test1.png')
    print(f"First upload: duplicate={is_dup}")

    is_dup, match = detector.is_duplicate(test_image, 'test2.png')
    print(f"Same image again: duplicate={is_dup}, matches={match}")

    # Test matching
    print("\nTesting matching algorithm...")
    matcher = SmartAutoMatcher()

    receipt = {
        'merchant': 'Starbucks',
        'amount': 5.75,
        'date': '2024-11-25'
    }

    transactions = [
        {'_index': 1, 'chase_description': 'SQ *STARBUCKS', 'chase_amount': 5.75, 'chase_date': '2024-11-25'},
        {'_index': 2, 'chase_description': 'AMAZON', 'chase_amount': 25.00, 'chase_date': '2024-11-25'},
        {'_index': 3, 'chase_description': 'STARBUCKS #1234', 'chase_amount': 6.00, 'chase_date': '2024-11-24'},
    ]

    result = matcher.find_best_match(receipt, transactions, exclude_with_receipts=False)
    if result:
        tx, score, details = result
        print(f"Best match: {tx['chase_description']} (score: {score:.2%})")
        print(f"Details: {json.dumps(details, indent=2)}")

    # Connect to database if available
    print("\nAttempting database connection...")
    try:
        conn = get_mysql_connection()
        if conn:
            print("Connected to MySQL!")
            ensure_hash_table(conn)

            if '--run' in sys.argv:
                print("\nRunning auto-match...")
                result = auto_match_pending_receipts(conn)
                print(json.dumps(result, indent=2))

            conn.close()
        else:
            print("No database connection available (set MYSQL_URL)")
    except Exception as e:
        print(f"Database error: {e}")
