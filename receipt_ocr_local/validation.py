#!/usr/bin/env python3
"""
Post-Extraction Validation Layer for Receipt OCR
=================================================
Validates extracted receipt data for consistency, accuracy, and quality.
Runs after all OCR engines have processed the receipt.
"""

import re
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from difflib import SequenceMatcher

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database path for learning
DB_PATH = Path(__file__).parent.parent / "receipts.db"
LEARNING_DB_PATH = Path(__file__).parent.parent / "metadata" / "validation_learning.db"


# =============================================================================
# MERCHANT DATABASE - Loads from DB and learns
# =============================================================================

class MerchantDatabase:
    """Merchant intelligence database with learning capabilities"""

    _instance = None
    _merchants = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._merchants is None:
            self._merchants = {}
            self._load_from_db()
            self._load_hardcoded()
            logger.info(f"Loaded {len(self._merchants)} merchants into validation database")

    def _load_from_db(self):
        """Load merchant knowledge from database"""
        if not DB_PATH.exists():
            return

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT raw_description, normalized_name, category,
                       is_subscription, avg_amount, primary_business_type
                FROM merchants
            """)

            for row in cursor.fetchall():
                key = row['raw_description'].upper().strip()
                self._merchants[key] = {
                    'normalized': row['normalized_name'],
                    'category': row['category'],
                    'is_subscription': bool(row['is_subscription']),
                    'avg_amount': float(row['avg_amount'] or 0),
                    'business_type': row['primary_business_type'] or 'default',
                    'source': 'database'
                }

            conn.close()
            logger.info(f"Loaded {len(self._merchants)} merchants from database")

        except Exception as e:
            logger.warning(f"Could not load merchants from DB: {e}")

    def _load_hardcoded(self):
        """Load hardcoded merchant patterns as fallback"""
        hardcoded = {
            # Fast Food
            "WENDY'S": {'normalized': "wendy's", 'category': 'Food & Drink', 'business_type': 'fast_food', 'avg_amount': 15.0},
            "MCDONALD'S": {'normalized': "mcdonald's", 'category': 'Food & Drink', 'business_type': 'fast_food', 'avg_amount': 12.0},
            "STARBUCKS": {'normalized': 'starbucks', 'category': 'Food & Drink', 'business_type': 'fast_food', 'avg_amount': 8.0},
            "CHICK-FIL-A": {'normalized': 'chick-fil-a', 'category': 'Food & Drink', 'business_type': 'fast_food', 'avg_amount': 12.0},
            "CHIPOTLE": {'normalized': 'chipotle', 'category': 'Food & Drink', 'business_type': 'fast_food', 'avg_amount': 15.0},

            # Restaurants/Bars
            "SOHO HOUSE": {'normalized': 'soho house', 'category': 'Food & Drink', 'business_type': 'bar', 'avg_amount': 150.0},
            "SOHO HOUSE NASHVILLE": {'normalized': 'soho house', 'category': 'Food & Drink', 'business_type': 'bar', 'avg_amount': 150.0},

            # Retail
            "WALMART": {'normalized': 'walmart', 'category': 'Shopping', 'business_type': 'retail', 'avg_amount': 75.0},
            "TARGET": {'normalized': 'target', 'category': 'Shopping', 'business_type': 'retail', 'avg_amount': 60.0},
            "COSTCO": {'normalized': 'costco', 'category': 'Shopping', 'business_type': 'retail', 'avg_amount': 200.0},
            "AMAZON": {'normalized': 'amazon', 'category': 'Shopping', 'business_type': 'retail', 'avg_amount': 50.0},
            "NORDSTROM": {'normalized': 'nordstrom', 'category': 'Shopping', 'business_type': 'retail', 'avg_amount': 150.0},

            # Groceries
            "KROGER": {'normalized': 'kroger', 'category': 'Groceries', 'business_type': 'grocery', 'avg_amount': 80.0},
            "WHOLE FOODS": {'normalized': 'whole foods', 'category': 'Groceries', 'business_type': 'grocery', 'avg_amount': 100.0},
            "TRADER JOE'S": {'normalized': "trader joe's", 'category': 'Groceries', 'business_type': 'grocery', 'avg_amount': 60.0},

            # Services
            "UBER": {'normalized': 'uber', 'category': 'Transportation', 'business_type': 'service', 'avg_amount': 25.0},
            "LYFT": {'normalized': 'lyft', 'category': 'Transportation', 'business_type': 'service', 'avg_amount': 22.0},

            # Subscriptions
            "SPOTIFY": {'normalized': 'spotify', 'category': 'Subscriptions', 'business_type': 'subscription', 'avg_amount': 15.0, 'is_subscription': True},
            "NETFLIX": {'normalized': 'netflix', 'category': 'Subscriptions', 'business_type': 'subscription', 'avg_amount': 20.0, 'is_subscription': True},
            "APPLE": {'normalized': 'apple', 'category': 'Subscriptions', 'business_type': 'subscription', 'avg_amount': 15.0},
            "ANTHROPIC": {'normalized': 'anthropic', 'category': 'Subscriptions', 'business_type': 'subscription', 'avg_amount': 20.0, 'is_subscription': True},
            "MIDJOURNEY": {'normalized': 'midjourney', 'category': 'Subscriptions', 'business_type': 'subscription', 'avg_amount': 30.0, 'is_subscription': True},

            # Parking
            "PMC PARKING": {'normalized': 'pmc parking', 'category': 'Transportation', 'business_type': 'parking', 'avg_amount': 15.0},
            "PMC PAID PARKING": {'normalized': 'pmc parking', 'category': 'Transportation', 'business_type': 'parking', 'avg_amount': 15.0},
        }

        for key, data in hardcoded.items():
            if key not in self._merchants:
                data['source'] = 'hardcoded'
                data.setdefault('is_subscription', False)
                self._merchants[key] = data

    def lookup(self, merchant: str) -> Optional[Dict]:
        """Look up merchant by name (exact or fuzzy match)"""
        if not merchant:
            return None

        merchant_upper = merchant.upper().strip()

        # Exact match
        if merchant_upper in self._merchants:
            return self._merchants[merchant_upper]

        # Fuzzy match
        best_match = None
        best_score = 0.0

        for key, data in self._merchants.items():
            # Check if merchant contains key or vice versa
            if key in merchant_upper or merchant_upper in key:
                score = len(key) / max(len(merchant_upper), len(key))
                if score > best_score:
                    best_score = score
                    best_match = data

            # Sequence matcher for fuzzy
            score = SequenceMatcher(None, merchant_upper, key).ratio()
            if score > best_score and score > 0.7:
                best_score = score
                best_match = data

        return best_match

    def get_business_type(self, merchant: str) -> str:
        """Get business type for merchant"""
        data = self.lookup(merchant)
        return data.get('business_type', 'default') if data else 'default'

    def get_avg_amount(self, merchant: str) -> float:
        """Get average transaction amount for merchant"""
        data = self.lookup(merchant)
        return data.get('avg_amount', 50.0) if data else 50.0

    def get_category(self, merchant: str) -> str:
        """Get category for merchant"""
        data = self.lookup(merchant)
        return data.get('category', 'Other') if data else 'Other'

    def is_known_merchant(self, merchant: str) -> bool:
        """Check if merchant is in database"""
        return self.lookup(merchant) is not None


# =============================================================================
# VALIDATION LEARNER - Learns from corrections
# =============================================================================

class ValidationLearner:
    """Learns from validation results and user corrections"""

    def __init__(self):
        self._init_db()

    def _init_db(self):
        """Initialize learning database"""
        LEARNING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(LEARNING_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_file TEXT,
                merchant TEXT,
                date TEXT,
                total REAL,
                validation_passed INTEGER,
                errors TEXT,
                warnings TEXT,
                original_confidence REAL,
                adjusted_confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_file TEXT,
                field_name TEXT,
                original_value TEXT,
                corrected_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT UNIQUE,
                normalized TEXT,
                business_type TEXT,
                avg_amount REAL,
                confidence REAL DEFAULT 1.0,
                usage_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def record_validation(self, extraction_result: Dict, validation_result: 'ValidationResult'):
        """Record validation result for learning"""
        try:
            conn = sqlite3.connect(LEARNING_DB_PATH)
            conn.execute("""
                INSERT INTO validation_history
                (receipt_file, merchant, date, total, validation_passed,
                 errors, warnings, original_confidence, adjusted_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                extraction_result.get('receipt_file', ''),
                extraction_result.get('Receipt Merchant', ''),
                extraction_result.get('Receipt Date', ''),
                extraction_result.get('Receipt Total', 0),
                1 if validation_result.is_valid else 0,
                json.dumps(validation_result.errors),
                json.dumps(validation_result.warnings),
                extraction_result.get('confidence_score', 0),
                validation_result.adjusted_confidence
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to record validation: {e}")

    def record_correction(self, receipt_file: str, field_name: str, original: str, corrected: str):
        """Record user correction for learning"""
        try:
            conn = sqlite3.connect(LEARNING_DB_PATH)
            conn.execute("""
                INSERT INTO corrections (receipt_file, field_name, original_value, corrected_value)
                VALUES (?, ?, ?, ?)
            """, (receipt_file, field_name, original, corrected))
            conn.commit()
            conn.close()
            logger.info(f"Recorded correction: {field_name} '{original}' -> '{corrected}'")
        except Exception as e:
            logger.warning(f"Failed to record correction: {e}")

    def learn_merchant_pattern(self, raw_merchant: str, normalized: str, business_type: str = None, amount: float = None):
        """Learn new merchant pattern from correction"""
        if not raw_merchant or not normalized:
            return

        try:
            conn = sqlite3.connect(LEARNING_DB_PATH)
            cursor = conn.cursor()

            # Check if pattern exists
            cursor.execute("SELECT id, usage_count, avg_amount FROM merchant_patterns WHERE pattern = ?",
                          (raw_merchant.upper(),))
            existing = cursor.fetchone()

            if existing:
                # Update existing pattern
                new_count = existing[1] + 1
                new_avg = existing[2]
                if amount:
                    new_avg = (existing[2] * existing[1] + amount) / new_count

                cursor.execute("""
                    UPDATE merchant_patterns
                    SET normalized = ?, usage_count = ?, avg_amount = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (normalized, new_count, new_avg, existing[0]))
            else:
                # Insert new pattern
                cursor.execute("""
                    INSERT INTO merchant_patterns (pattern, normalized, business_type, avg_amount)
                    VALUES (?, ?, ?, ?)
                """, (raw_merchant.upper(), normalized, business_type or 'default', amount or 0))

            conn.commit()
            conn.close()
            logger.info(f"Learned merchant pattern: {raw_merchant} -> {normalized}")
        except Exception as e:
            logger.warning(f"Failed to learn merchant pattern: {e}")

    def get_learned_merchants(self) -> Dict:
        """Get all learned merchant patterns"""
        merchants = {}
        try:
            conn = sqlite3.connect(LEARNING_DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT pattern, normalized, business_type, avg_amount, confidence
                FROM merchant_patterns
                WHERE confidence >= 0.5
                ORDER BY usage_count DESC
            """)

            for row in cursor:
                merchants[row['pattern']] = {
                    'normalized': row['normalized'],
                    'business_type': row['business_type'],
                    'avg_amount': row['avg_amount'],
                    'confidence': row['confidence']
                }

            conn.close()
        except Exception as e:
            logger.warning(f"Failed to load learned merchants: {e}")

        return merchants

    def get_validation_stats(self) -> Dict:
        """Get validation statistics for analysis"""
        stats = {
            'total_validations': 0,
            'pass_rate': 0.0,
            'common_errors': {},
            'avg_confidence_improvement': 0.0
        }

        try:
            conn = sqlite3.connect(LEARNING_DB_PATH)
            cursor = conn.cursor()

            # Total and pass rate
            cursor.execute("SELECT COUNT(*), SUM(validation_passed) FROM validation_history")
            row = cursor.fetchone()
            if row[0] > 0:
                stats['total_validations'] = row[0]
                stats['pass_rate'] = row[1] / row[0]

            # Average confidence improvement
            cursor.execute("""
                SELECT AVG(adjusted_confidence - original_confidence)
                FROM validation_history
            """)
            row = cursor.fetchone()
            stats['avg_confidence_improvement'] = row[0] or 0

            conn.close()
        except Exception as e:
            logger.warning(f"Failed to get validation stats: {e}")

        return stats


# Global instances
_merchant_db = None
_learner = None

def get_merchant_db() -> MerchantDatabase:
    """Get singleton merchant database"""
    global _merchant_db
    if _merchant_db is None:
        _merchant_db = MerchantDatabase()
    return _merchant_db

def get_learner() -> ValidationLearner:
    """Get singleton validation learner"""
    global _learner
    if _learner is None:
        _learner = ValidationLearner()
    return _learner


# Validation Constants
class ValidationConfig:
    """Configuration for validation thresholds and rules"""

    # Amount bounds
    MIN_RECEIPT_TOTAL = 0.01
    MAX_RECEIPT_TOTAL = 10000.0
    MAX_TIP_PERCENTAGE = 0.50  # 50% max tip
    MIN_TIP_PERCENTAGE = 0.0
    MAX_TIP_ABSOLUTE = 500.0

    # Date bounds
    MAX_RECEIPT_AGE_DAYS = 730  # 2 years
    MAX_FUTURE_DAYS = 1  # Allow 1 day for timezone issues

    # Merchant validation
    MIN_MERCHANT_LENGTH = 2
    MAX_MERCHANT_LENGTH = 100

    # Invalid merchant patterns (generic OCR noise)
    INVALID_MERCHANT_PATTERNS = [
        r'^[\d\s\.\-\$\,]+$',  # Only numbers/symbols
        r'^[A-Z]{1,2}$',  # Single letters
        r'^(RECEIPT|ORDER|INVOICE|TRANSACTION|SALE|TICKET)$',
        r'^(THANK\s*YOU|THANKS|WELCOME)$',
        r'^(CREDIT|DEBIT|CASH|CHANGE|BALANCE)$',
        r'^(TOTAL|SUBTOTAL|TAX|TIP|AMOUNT)$',
        r'^(DATE|TIME|PHONE|ADDRESS|FAX)$',
        r'^[\W]+$',  # Only special characters
    ]

    # Merchant type expected total ranges
    MERCHANT_TOTAL_RANGES = {
        'fast_food': (1.0, 50.0),
        'restaurant': (5.0, 500.0),
        'bar': (5.0, 300.0),
        'grocery': (5.0, 500.0),
        'retail': (1.0, 2000.0),
        'gas_station': (10.0, 200.0),
        'subscription': (1.0, 200.0),
        'parking': (1.0, 100.0),
        'hotel': (50.0, 5000.0),
        'default': (0.01, 5000.0),
    }

    # Confidence thresholds
    HIGH_CONFIDENCE = 0.8
    MEDIUM_CONFIDENCE = 0.5
    LOW_CONFIDENCE = 0.3


class ValidationResult:
    """Container for validation results"""

    def __init__(self):
        self.is_valid = True
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.suggestions: List[str] = []
        self.adjusted_confidence: float = 0.0
        self.validation_scores: Dict[str, float] = {}
        self.field_validations: Dict[str, bool] = {}

    def add_error(self, message: str):
        """Add critical error - marks result as invalid"""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str):
        """Add warning - doesn't invalidate but needs attention"""
        self.warnings.append(message)

    def add_suggestion(self, message: str):
        """Add suggestion for improvement"""
        self.suggestions.append(message)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'is_valid': self.is_valid,
            'errors': self.errors,
            'warnings': self.warnings,
            'suggestions': self.suggestions,
            'adjusted_confidence': round(self.adjusted_confidence, 3),
            'validation_scores': {k: round(v, 3) for k, v in self.validation_scores.items()},
            'field_validations': self.field_validations,
            'error_count': len(self.errors),
            'warning_count': len(self.warnings),
        }


class ReceiptValidator:
    """Comprehensive validator for extracted receipt data"""

    def __init__(self, config: ValidationConfig = None, learn: bool = True):
        self.config = config or ValidationConfig()
        self.merchant_db = get_merchant_db()
        self.learner = get_learner() if learn else None

    def validate(self, extraction_result: Dict) -> ValidationResult:
        """
        Run all validations on extraction result.

        Args:
            extraction_result: Output from OCR extraction

        Returns:
            ValidationResult with detailed validation info
        """
        result = ValidationResult()

        # Extract fields
        merchant = extraction_result.get('Receipt Merchant', '') or extraction_result.get('ai_receipt_merchant', '')
        date_str = extraction_result.get('Receipt Date', '') or extraction_result.get('ai_receipt_date', '')
        total = float(extraction_result.get('Receipt Total', 0) or extraction_result.get('ai_receipt_total', 0) or 0)
        subtotal = float(extraction_result.get('subtotal_amount', 0) or 0)
        tip = float(extraction_result.get('tip_amount', 0) or 0)
        confidence = float(extraction_result.get('confidence_score', 0) or 0)

        # Run all validations
        merchant_score = self._validate_merchant(merchant, result)
        date_score = self._validate_date(date_str, result)
        total_score = self._validate_total(total, merchant, result)
        tip_score = self._validate_tip(tip, subtotal, total, result)
        arithmetic_score = self._validate_arithmetic(subtotal, tip, total, result)
        completeness_score = self._validate_completeness(extraction_result, result)

        # Store individual scores
        result.validation_scores = {
            'merchant': merchant_score,
            'date': date_score,
            'total': total_score,
            'tip': tip_score,
            'arithmetic': arithmetic_score,
            'completeness': completeness_score,
        }

        # Calculate adjusted confidence
        base_confidence = confidence

        # Weight the scores
        weighted_score = (
            merchant_score * 0.25 +
            date_score * 0.15 +
            total_score * 0.30 +
            tip_score * 0.10 +
            arithmetic_score * 0.10 +
            completeness_score * 0.10
        )

        # Blend original confidence with validation score
        result.adjusted_confidence = (base_confidence * 0.6) + (weighted_score * 0.4)

        # Penalize for errors
        result.adjusted_confidence -= len(result.errors) * 0.1
        result.adjusted_confidence -= len(result.warnings) * 0.02

        # Clamp to valid range
        result.adjusted_confidence = max(0.0, min(1.0, result.adjusted_confidence))

        # Add overall suggestions
        if result.adjusted_confidence < self.config.LOW_CONFIDENCE:
            result.add_suggestion("Consider manual review - very low confidence")
        elif result.adjusted_confidence < self.config.MEDIUM_CONFIDENCE:
            result.add_suggestion("Recommend verification of extracted values")

        # Bonus for known merchants
        if self.merchant_db.is_known_merchant(merchant):
            result.adjusted_confidence = min(1.0, result.adjusted_confidence + 0.05)
            result.validation_scores['merchant_known'] = 1.0
        else:
            result.validation_scores['merchant_known'] = 0.0

        # Record for learning
        if self.learner:
            self.learner.record_validation(extraction_result, result)

        return result

    def _validate_merchant(self, merchant: str, result: ValidationResult) -> float:
        """Validate merchant name using merchant database"""
        score = 1.0

        # Check presence
        if not merchant:
            result.add_error("Merchant name is missing")
            result.field_validations['merchant'] = False
            return 0.0

        # Check length
        if len(merchant) < self.config.MIN_MERCHANT_LENGTH:
            result.add_warning(f"Merchant name too short: '{merchant}'")
            score -= 0.3
        elif len(merchant) > self.config.MAX_MERCHANT_LENGTH:
            result.add_warning(f"Merchant name too long ({len(merchant)} chars)")
            score -= 0.2

        # Check if merchant is in database (bonus for known merchants)
        merchant_data = self.merchant_db.lookup(merchant)
        if merchant_data:
            score += 0.1  # Bonus for known merchant
            result.field_validations['merchant_in_db'] = True
        else:
            result.field_validations['merchant_in_db'] = False

        # Check for invalid patterns
        for pattern in self.config.INVALID_MERCHANT_PATTERNS:
            if re.match(pattern, merchant.strip(), re.IGNORECASE):
                result.add_error(f"Invalid merchant name pattern: '{merchant}'")
                result.field_validations['merchant'] = False
                return 0.1

        # Check for excessive repetition (OCR artifact)
        if re.search(r'(.)\1{4,}', merchant):
            result.add_warning(f"Merchant name may contain OCR artifacts: '{merchant}'")
            score -= 0.3

        # Check for good capitalization (title case or ALL CAPS is expected)
        if merchant.islower():
            result.add_suggestion("Merchant name is all lowercase - may need normalization")
            score -= 0.1

        result.field_validations['merchant'] = score > 0.5
        return max(0.0, score)

    def _validate_date(self, date_str: str, result: ValidationResult) -> float:
        """Validate date value"""
        score = 1.0

        # Check presence
        if not date_str:
            result.add_warning("Date is missing")
            result.field_validations['date'] = False
            return 0.3  # Date is less critical

        # Try to parse date
        parsed_date = None
        formats = ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y']

        for fmt in formats:
            try:
                parsed_date = datetime.strptime(date_str.strip(), fmt)
                break
            except ValueError:
                continue

        if not parsed_date:
            result.add_warning(f"Cannot parse date format: '{date_str}'")
            result.field_validations['date'] = False
            return 0.4

        # Check date bounds
        now = datetime.now()
        max_age = now - timedelta(days=self.config.MAX_RECEIPT_AGE_DAYS)
        max_future = now + timedelta(days=self.config.MAX_FUTURE_DAYS)

        if parsed_date > max_future:
            result.add_error(f"Date is in the future: {date_str}")
            score -= 0.5
        elif parsed_date < max_age:
            result.add_warning(f"Date is very old ({(now - parsed_date).days} days ago)")
            score -= 0.3

        # Check for reasonable year
        if parsed_date.year < 2000:
            result.add_warning(f"Date year seems incorrect: {parsed_date.year}")
            score -= 0.3
        elif parsed_date.year > now.year + 1:
            result.add_error(f"Date year is too far in future: {parsed_date.year}")
            score -= 0.5

        result.field_validations['date'] = score > 0.5
        return max(0.0, score)

    def _validate_total(self, total: float, merchant: str, result: ValidationResult) -> float:
        """Validate total amount"""
        score = 1.0

        # Check presence
        if total == 0:
            result.add_error("Total amount is zero")
            result.field_validations['total'] = False
            return 0.0

        # Check bounds
        if total < self.config.MIN_RECEIPT_TOTAL:
            result.add_error(f"Total ${total:.2f} is below minimum ${self.config.MIN_RECEIPT_TOTAL}")
            result.field_validations['total'] = False
            return 0.0

        if total > self.config.MAX_RECEIPT_TOTAL:
            result.add_error(f"Total ${total:.2f} exceeds maximum ${self.config.MAX_RECEIPT_TOTAL}")
            score -= 0.5

        # Check for unreasonable values
        if total < 1.0:
            result.add_suggestion(f"Very small total (${total:.2f}) - verify accuracy")

        # Merchant-specific validation
        merchant_type = self._guess_merchant_type(merchant)
        min_expected, max_expected = self.config.MERCHANT_TOTAL_RANGES.get(
            merchant_type, self.config.MERCHANT_TOTAL_RANGES['default']
        )

        if total < min_expected:
            result.add_suggestion(f"Total ${total:.2f} seems low for {merchant_type} ({merchant})")
            score -= 0.1
        elif total > max_expected:
            result.add_warning(f"Total ${total:.2f} seems high for {merchant_type} ({merchant})")
            score -= 0.2

        # Check for suspiciously round numbers
        if total == int(total) and total > 10:
            result.add_suggestion(f"Total ${total:.2f} is a round number - verify no cents were missed")

        result.field_validations['total'] = score > 0.5
        return max(0.0, score)

    def _validate_tip(self, tip: float, subtotal: float, total: float, result: ValidationResult) -> float:
        """Validate tip amount"""
        score = 1.0

        # Tip is optional, so missing is OK
        if tip == 0:
            result.field_validations['tip'] = True
            return 1.0

        # Check for negative
        if tip < 0:
            result.add_error(f"Tip cannot be negative: ${tip:.2f}")
            result.field_validations['tip'] = False
            return 0.0

        # Check absolute bounds
        if tip > self.config.MAX_TIP_ABSOLUTE:
            result.add_warning(f"Tip ${tip:.2f} is unusually high")
            score -= 0.3

        # Check relative to subtotal/total
        base = subtotal if subtotal > 0 else total
        if base > 0:
            tip_pct = tip / base
            if tip_pct > self.config.MAX_TIP_PERCENTAGE:
                result.add_warning(f"Tip is {tip_pct*100:.0f}% of base - unusually high")
                score -= 0.3

        # Check that tip < total
        if tip >= total:
            result.add_error(f"Tip ${tip:.2f} cannot be >= total ${total:.2f}")
            result.field_validations['tip'] = False
            return 0.1

        result.field_validations['tip'] = score > 0.5
        return max(0.0, score)

    def _validate_arithmetic(self, subtotal: float, tip: float, total: float, result: ValidationResult) -> float:
        """Validate arithmetic consistency between fields"""
        score = 1.0

        # If no subtotal, can't validate arithmetic
        if subtotal == 0:
            result.field_validations['arithmetic'] = True
            return 1.0

        # Calculate expected total (subtotal + tip)
        # Note: we're not accounting for tax which may cause discrepancy
        expected_min = subtotal + tip
        expected_max = subtotal * 1.15 + tip  # Allow up to 15% tax

        if total < expected_min:
            difference = expected_min - total
            if difference > 0.50:  # Allow small rounding
                result.add_warning(f"Total ${total:.2f} < subtotal ${subtotal:.2f} + tip ${tip:.2f}")
                score -= 0.3

        elif total > expected_max:
            excess = total - expected_max
            if excess > 1.00:  # Allow small discrepancy
                result.add_suggestion(f"Total includes ${excess:.2f} beyond subtotal+tip+15% tax")
                score -= 0.1

        # Check subtotal < total
        if subtotal > total:
            result.add_error(f"Subtotal ${subtotal:.2f} cannot exceed total ${total:.2f}")
            result.field_validations['arithmetic'] = False
            return 0.1

        result.field_validations['arithmetic'] = score > 0.5
        return max(0.0, score)

    def _validate_completeness(self, extraction_result: Dict, result: ValidationResult) -> float:
        """Validate overall extraction completeness"""
        score = 1.0

        required_fields = ['Receipt Merchant', 'Receipt Date', 'Receipt Total']
        optional_fields = ['subtotal_amount', 'tip_amount', 'merchant_normalized']

        # Check required fields
        missing_required = []
        for field in required_fields:
            alt_field = 'ai_' + field.lower().replace(' ', '_')
            value = extraction_result.get(field) or extraction_result.get(alt_field)
            if not value:
                missing_required.append(field)
                score -= 0.25

        if missing_required:
            result.add_warning(f"Missing required fields: {', '.join(missing_required)}")

        # Bonus for optional fields
        present_optional = 0
        for field in optional_fields:
            if extraction_result.get(field):
                present_optional += 1

        if present_optional > 0:
            score += present_optional * 0.05

        # Check for extraction issues
        issues = extraction_result.get('extraction_issues', [])
        if issues:
            result.add_suggestion(f"Extraction flagged issues: {', '.join(issues)}")
            score -= len(issues) * 0.05

        # Check confidence score
        confidence = extraction_result.get('confidence_score', 0)
        if confidence < self.config.LOW_CONFIDENCE:
            result.add_warning(f"OCR confidence is very low: {confidence:.2f}")
            score -= 0.2
        elif confidence < self.config.MEDIUM_CONFIDENCE:
            result.add_suggestion(f"OCR confidence is below average: {confidence:.2f}")
            score -= 0.1

        result.field_validations['completeness'] = score > 0.5
        return max(0.0, min(1.0, score))

    def _guess_merchant_type(self, merchant: str) -> str:
        """Get merchant type from database or guess from name"""
        if not merchant:
            return 'default'

        # First try to look up in database
        business_type = self.merchant_db.get_business_type(merchant)
        if business_type != 'default':
            return business_type

        # Fallback to pattern matching
        merchant_lower = merchant.lower()

        # Fast food
        fast_food = ['wendy', 'mcdonald', 'burger', 'taco', 'pizza', 'subway',
                    'chick-fil-a', 'chipotle', 'kfc', "popeye"]
        if any(ff in merchant_lower for ff in fast_food):
            return 'fast_food'

        # Coffee
        coffee = ['starbucks', 'coffee', 'dunkin', 'peet']
        if any(c in merchant_lower for c in coffee):
            return 'fast_food'

        # Restaurant/Bar
        restaurant = ['restaurant', 'cafe', 'bistro', 'grill', 'kitchen', 'diner']
        if any(r in merchant_lower for r in restaurant):
            return 'restaurant'

        bar = ['bar', 'pub', 'tavern', 'lounge', 'house']
        if any(b in merchant_lower for b in bar):
            return 'bar'

        # Grocery
        grocery = ['grocery', 'market', 'foods', 'kroger', 'publix', 'trader']
        if any(g in merchant_lower for g in grocery):
            return 'grocery'

        # Retail
        retail = ['walmart', 'target', 'costco', 'amazon', 'store', 'shop', 'nordstrom']
        if any(r in merchant_lower for r in retail):
            return 'retail'

        # Gas
        gas = ['shell', 'exxon', 'chevron', 'mobil', 'gas', 'fuel', 'bp']
        if any(g in merchant_lower for g in gas):
            return 'gas_station'

        # Subscription
        subscription = ['spotify', 'netflix', 'apple', 'google', 'adobe', 'microsoft', 'anthropic']
        if any(s in merchant_lower for s in subscription):
            return 'subscription'

        # Parking
        parking = ['parking', 'park', 'garage', 'pmc']
        if any(p in merchant_lower for p in parking):
            return 'parking'

        # Hotel
        hotel = ['hotel', 'inn', 'suites', 'resort', 'marriott', 'hilton']
        if any(h in merchant_lower for h in hotel):
            return 'hotel'

        return 'default'


def validate_extraction(extraction_result: Dict, config: ValidationConfig = None) -> Dict:
    """
    Convenience function to validate extraction result.

    Args:
        extraction_result: Output from OCR extraction
        config: Optional custom configuration

    Returns:
        Dictionary with validation results and adjusted extraction
    """
    validator = ReceiptValidator(config)
    validation = validator.validate(extraction_result)

    # Merge validation into result
    result = extraction_result.copy()
    result['validation'] = validation.to_dict()
    result['validated_confidence'] = validation.adjusted_confidence
    result['validation_passed'] = validation.is_valid

    return result


def batch_validate(extraction_results: List[Dict], config: ValidationConfig = None) -> Tuple[List[Dict], Dict]:
    """
    Validate a batch of extraction results.

    Args:
        extraction_results: List of extraction results
        config: Optional custom configuration

    Returns:
        Tuple of (validated_results, summary_stats)
    """
    validator = ReceiptValidator(config)
    validated = []

    stats = {
        'total': len(extraction_results),
        'passed': 0,
        'failed': 0,
        'warnings': 0,
        'avg_confidence': 0.0,
        'avg_adjusted_confidence': 0.0,
        'common_errors': {},
        'common_warnings': {},
    }

    total_conf = 0.0
    total_adj_conf = 0.0

    for result in extraction_results:
        validation = validator.validate(result)

        # Update result
        validated_result = result.copy()
        validated_result['validation'] = validation.to_dict()
        validated_result['validated_confidence'] = validation.adjusted_confidence
        validated_result['validation_passed'] = validation.is_valid
        validated.append(validated_result)

        # Update stats
        if validation.is_valid:
            stats['passed'] += 1
        else:
            stats['failed'] += 1

        if validation.warnings:
            stats['warnings'] += 1

        total_conf += result.get('confidence_score', 0)
        total_adj_conf += validation.adjusted_confidence

        # Track common issues
        for error in validation.errors:
            error_type = error.split(':')[0] if ':' in error else error[:50]
            stats['common_errors'][error_type] = stats['common_errors'].get(error_type, 0) + 1

        for warning in validation.warnings:
            warning_type = warning.split(':')[0] if ':' in warning else warning[:50]
            stats['common_warnings'][warning_type] = stats['common_warnings'].get(warning_type, 0) + 1

    # Calculate averages
    if stats['total'] > 0:
        stats['avg_confidence'] = round(total_conf / stats['total'], 3)
        stats['avg_adjusted_confidence'] = round(total_adj_conf / stats['total'], 3)
        stats['pass_rate'] = round(stats['passed'] / stats['total'], 3)

    # Sort common issues by frequency
    stats['common_errors'] = dict(sorted(
        stats['common_errors'].items(), key=lambda x: x[1], reverse=True
    )[:10])
    stats['common_warnings'] = dict(sorted(
        stats['common_warnings'].items(), key=lambda x: x[1], reverse=True
    )[:10])

    return validated, stats


# Test
if __name__ == "__main__":
    # Test with sample extraction
    sample = {
        "receipt_file": "test_receipt.jpg",
        "Receipt Merchant": "Starbucks",
        "Receipt Date": "2024-01-15",
        "Receipt Total": 15.50,
        "subtotal_amount": 12.00,
        "tip_amount": 2.50,
        "confidence_score": 0.85,
    }

    result = validate_extraction(sample)

    print("Validation Result:")
    print(f"  Passed: {result['validation_passed']}")
    print(f"  Adjusted Confidence: {result['validated_confidence']:.3f}")
    print(f"  Errors: {result['validation']['errors']}")
    print(f"  Warnings: {result['validation']['warnings']}")
    print(f"  Suggestions: {result['validation']['suggestions']}")

    # Test with problematic extraction
    problematic = {
        "receipt_file": "bad_receipt.jpg",
        "Receipt Merchant": "123",  # Invalid
        "Receipt Date": "2030-01-01",  # Future
        "Receipt Total": 0,  # Zero
        "confidence_score": 0.2,  # Low
    }

    print("\nProblematic Extraction:")
    result = validate_extraction(problematic)
    print(f"  Passed: {result['validation_passed']}")
    print(f"  Adjusted Confidence: {result['validated_confidence']:.3f}")
    print(f"  Errors: {result['validation']['errors']}")
    print(f"  Warnings: {result['validation']['warnings']}")
