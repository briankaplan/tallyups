#!/usr/bin/env python3
"""
Smart Matcher V2 - Production-Grade Receipt-to-Transaction Matching Engine
===========================================================================

Target: 95%+ accuracy for auto-matching with comprehensive edge case handling.

Features:
- Multi-signal matching with weighted scoring
- Comprehensive merchant alias database (bank name -> canonical)
- Fuzzy string matching with configurable thresholds
- Tip/fee/tax tolerance with percentage-based handling
- Same-day same-merchant collision resolution
- Calendar event context boosting
- Contact context boosting
- Learning from manual matches
- Detailed confidence explanations
- Full audit logging

Match Score Components:
- Amount matching (40-60% weight depending on confidence)
- Merchant matching (30-40% weight)
- Date matching (10-20% weight)
- Context bonuses (+5-15 points)
- Collision penalties (-5-20 points)

Thresholds:
- 85%+ -> Auto-match (high confidence)
- 70-85% -> Auto-match with note (good confidence)
- 50-70% -> Manual review required
- <50% -> No match
"""

import hashlib
import json
import os
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Tuple, Set, Any
from pathlib import Path
from enum import Enum
import threading


# =============================================================================
# CONFIGURATION
# =============================================================================

class MatchConfidence(Enum):
    """Match confidence levels"""
    AUTO_HIGH = "auto_high"        # 85%+ - Auto-match with high confidence
    AUTO_GOOD = "auto_good"        # 70-85% - Auto-match with good confidence
    REVIEW = "review"              # 50-70% - Needs manual review
    NO_MATCH = "no_match"          # <50% - No match found
    COLLISION = "collision"        # Multiple candidates, needs resolution


# Thresholds (can be overridden via environment)
AUTO_HIGH_THRESHOLD = float(os.getenv('MATCH_AUTO_HIGH', '0.85'))
AUTO_GOOD_THRESHOLD = float(os.getenv('MATCH_AUTO_GOOD', '0.70'))
REVIEW_THRESHOLD = float(os.getenv('MATCH_REVIEW', '0.50'))

# Logging
logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class MatchScore:
    """Detailed match score with explanation"""
    total: float
    confidence: MatchConfidence

    # Component scores (0.0 - 1.0)
    amount_score: float = 0.0
    merchant_score: float = 0.0
    date_score: float = 0.0

    # Bonuses and penalties
    context_bonus: float = 0.0
    collision_penalty: float = 0.0

    # Explanations
    amount_explanation: str = ""
    merchant_explanation: str = ""
    date_explanation: str = ""
    context_explanation: str = ""

    # Metadata
    is_tip_adjusted: bool = False
    is_fee_adjusted: bool = False
    is_subscription: bool = False
    is_restaurant: bool = False

    def to_dict(self) -> Dict:
        return {
            'total': round(self.total, 4),
            'confidence': self.confidence.value,
            'components': {
                'amount': round(self.amount_score, 4),
                'merchant': round(self.merchant_score, 4),
                'date': round(self.date_score, 4),
            },
            'bonuses': {
                'context': round(self.context_bonus, 4),
                'collision_penalty': round(self.collision_penalty, 4),
            },
            'explanations': {
                'amount': self.amount_explanation,
                'merchant': self.merchant_explanation,
                'date': self.date_explanation,
                'context': self.context_explanation,
            },
            'flags': {
                'tip_adjusted': self.is_tip_adjusted,
                'fee_adjusted': self.is_fee_adjusted,
                'subscription': self.is_subscription,
                'restaurant': self.is_restaurant,
            }
        }


@dataclass
class MatchResult:
    """Complete match result for a receipt"""
    receipt_id: Any
    transaction_id: Any = None
    score: Optional[MatchScore] = None
    matched: bool = False

    # For collision scenarios
    candidates: List[Tuple[Any, 'MatchScore']] = field(default_factory=list)
    collision_resolved: bool = False
    resolution_reason: str = ""


@dataclass
class Transaction:
    """Standardized transaction representation"""
    id: Any
    merchant: str
    amount: Decimal
    date: datetime
    category: str = ""
    description: str = ""
    has_receipt: bool = False
    receipt_url: str = ""

    # Additional context
    business_type: str = ""
    notes: str = ""


@dataclass
class Receipt:
    """Standardized receipt representation"""
    id: Any
    merchant: str
    amount: Decimal
    date: Optional[datetime]

    # OCR confidence
    confidence: float = 0.0

    # Additional data
    line_items: List[Dict] = field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    tip: Optional[Decimal] = None

    # Source
    source: str = ""  # 'email', 'mobile', 'scan'
    file_path: str = ""


# =============================================================================
# MERCHANT ALIAS DATABASE
# =============================================================================

# Comprehensive bank name -> canonical merchant mapping
# Format: 'bank_pattern': ('canonical_name', 'category', is_subscription)
BANK_TO_CANONICAL = {
    # Apple ecosystem
    'apple.com/bill': ('Apple', 'subscriptions', True),
    'apple com bill': ('Apple', 'subscriptions', True),
    'applecombill': ('Apple', 'subscriptions', True),
    'apple store': ('Apple Store', 'retail', False),
    'app store': ('Apple', 'subscriptions', True),
    'itunes': ('Apple', 'subscriptions', True),
    'icloud': ('Apple', 'subscriptions', True),

    # Amazon variations
    'amzn mktp': ('Amazon', 'retail', False),
    'amazon mktp': ('Amazon', 'retail', False),
    'amzn.com': ('Amazon', 'retail', False),
    'amazon.com': ('Amazon', 'retail', False),
    'amzn digital': ('Amazon Digital', 'subscriptions', True),
    'amazon prime': ('Amazon Prime', 'subscriptions', True),
    'prime video': ('Amazon Prime Video', 'subscriptions', True),
    'whole foods': ('Whole Foods', 'groceries', False),
    'amzn fresh': ('Amazon Fresh', 'groceries', False),

    # Starbucks variations
    'sq *starbucks': ('Starbucks', 'food_beverage', False),
    'tst* starbucks': ('Starbucks', 'food_beverage', False),
    'starbucks': ('Starbucks', 'food_beverage', False),

    # Square/Toast POS systems
    'sq *': ('Square Payment', 'retail', False),  # Will be refined with merchant name
    'tst*': ('Toast Payment', 'restaurant', False),
    'tst *': ('Toast Payment', 'restaurant', False),

    # Uber ecosystem
    'uber trip': ('Uber', 'transportation', False),
    'uber *trip': ('Uber', 'transportation', False),
    'uber eats': ('Uber Eats', 'delivery', False),
    'uber* eats': ('Uber Eats', 'delivery', False),
    'ubereats': ('Uber Eats', 'delivery', False),

    # DoorDash
    'doordash': ('DoorDash', 'delivery', False),
    'dd doordash': ('DoorDash', 'delivery', False),
    'dd *': ('DoorDash', 'delivery', False),

    # AI/Tech subscriptions
    'anthropic': ('Anthropic', 'subscriptions', True),
    'claude ai': ('Anthropic', 'subscriptions', True),
    'claude.ai': ('Anthropic', 'subscriptions', True),
    'openai': ('OpenAI', 'subscriptions', True),
    'chatgpt': ('OpenAI', 'subscriptions', True),
    'midjourney': ('Midjourney', 'subscriptions', True),
    'cursor': ('Cursor', 'subscriptions', True),
    'cursor ai': ('Cursor', 'subscriptions', True),
    'github': ('GitHub', 'subscriptions', True),
    'huggingface': ('Hugging Face', 'subscriptions', True),
    'hugging face': ('Hugging Face', 'subscriptions', True),

    # Cloud services
    'cloudflare': ('Cloudflare', 'subscriptions', True),
    'railway': ('Railway', 'subscriptions', True),
    'vercel': ('Vercel', 'subscriptions', True),
    'digitalocean': ('DigitalOcean', 'subscriptions', True),
    'aws': ('AWS', 'subscriptions', True),
    'amazon web services': ('AWS', 'subscriptions', True),
    'heroku': ('Heroku', 'subscriptions', True),
    'netlify': ('Netlify', 'subscriptions', True),

    # Streaming/Media
    'spotify': ('Spotify', 'subscriptions', True),
    'netflix': ('Netflix', 'subscriptions', True),
    'hulu': ('Hulu', 'subscriptions', True),
    'disney+': ('Disney+', 'subscriptions', True),
    'disney plus': ('Disney+', 'subscriptions', True),
    'hbo max': ('HBO Max', 'subscriptions', True),
    'youtube': ('YouTube', 'subscriptions', True),
    'youtube premium': ('YouTube Premium', 'subscriptions', True),

    # Google
    'google': ('Google', 'subscriptions', True),
    'google *': ('Google', 'subscriptions', True),
    'google play': ('Google Play', 'subscriptions', True),
    'google one': ('Google One', 'subscriptions', True),
    'google cloud': ('Google Cloud', 'subscriptions', True),

    # Microsoft
    'microsoft': ('Microsoft', 'subscriptions', True),
    'msft *': ('Microsoft', 'subscriptions', True),
    'microsoft 365': ('Microsoft 365', 'subscriptions', True),
    'xbox': ('Xbox', 'subscriptions', True),

    # PayPal prefixed
    'paypal *': ('PayPal', 'payment', False),
    'pp*': ('PayPal', 'payment', False),

    # Parking
    'pmc parking': ('PMC Parking', 'parking', False),
    'pmc paid parking': ('PMC Parking', 'parking', False),
    'metropolis': ('Metropolis Parking', 'parking', False),
    'spothero': ('SpotHero', 'parking', False),

    # Airlines
    'southwest': ('Southwest Airlines', 'travel', False),
    'southwest air': ('Southwest Airlines', 'travel', False),
    'american air': ('American Airlines', 'travel', False),
    'delta air': ('Delta Airlines', 'travel', False),
    'united air': ('United Airlines', 'travel', False),

    # Hotels
    'marriott': ('Marriott', 'travel', False),
    'hilton': ('Hilton', 'travel', False),
    'hyatt': ('Hyatt', 'travel', False),
    'airbnb': ('Airbnb', 'travel', False),
    'vrbo': ('VRBO', 'travel', False),

    # Telecom
    'verizon': ('Verizon', 'subscriptions', True),
    'vzwrlss': ('Verizon', 'subscriptions', True),
    'att': ('AT&T', 'subscriptions', True),
    't-mobile': ('T-Mobile', 'subscriptions', True),

    # Nashville specific (from user's data)
    'soho house': ('Soho House', 'restaurant', False),
    'sh nashville': ('Soho House', 'restaurant', False),
    '12 south taproom': ('12 South Taproom', 'restaurant', False),
    'corner pub': ('Corner Pub', 'restaurant', False),
    'optimist': ('The Optimist', 'restaurant', False),
    'the optimist': ('The Optimist', 'restaurant', False),
    'britannia pub': ('Britannia Pub', 'restaurant', False),
    'hattie b': ('Hattie B\'s', 'restaurant', False),
    'panchos': ('Panchos', 'restaurant', False),
    'first watch': ('First Watch', 'restaurant', False),
    'white rhino': ('White Rhino Coffee', 'food_beverage', False),
    'in n out': ('In-N-Out', 'restaurant', False),
    'in-n-out': ('In-N-Out', 'restaurant', False),
}

# Restaurant categories that typically have tips
RESTAURANT_CATEGORIES = {
    'restaurant', 'bar', 'food_beverage', 'dining', 'cafe', 'pub', 'grill',
    'tavern', 'kitchen', 'eatery', 'bistro', 'brasserie'
}

# Categories with potential delivery fees
DELIVERY_CATEGORIES = {'delivery', 'food_delivery', 'groceries'}

# Subscription categories with potential tax variations
SUBSCRIPTION_CATEGORIES = {'subscriptions', 'software', 'saas', 'digital'}


# =============================================================================
# AMOUNT MATCHING
# =============================================================================

class AmountMatcher:
    """
    Sophisticated amount matching with tip/fee/tax handling.

    Handles:
    - Exact matches (within $0.01)
    - Small fee variations (international fees, processing fees)
    - Restaurant tips (10-30% range)
    - Tax variations on subscriptions
    - Partial amounts (split bills)
    """

    # Tolerance configurations
    EXACT_TOLERANCE = Decimal('0.01')
    FEE_TOLERANCE = Decimal('2.50')  # Processing/forex fees

    # Tip ranges (as percentage of receipt subtotal)
    TIP_MIN_PCT = Decimal('0.10')  # 10% minimum tip
    TIP_MAX_PCT = Decimal('0.35')  # 35% maximum tip (generous)
    TIP_TYPICAL_PCT = Decimal('0.20')  # 20% typical tip

    # Tax variations
    TAX_MAX_PCT = Decimal('0.12')  # 12% max tax rate

    # International forex fee
    FOREX_FEE_PCT = Decimal('0.03')  # 3% typical forex fee

    def __init__(self):
        self.two_places = Decimal('0.01')

    def match(
        self,
        receipt_amount: Decimal,
        transaction_amount: Decimal,
        is_restaurant: bool = False,
        is_subscription: bool = False,
        is_international: bool = False,
        receipt_subtotal: Optional[Decimal] = None,
        receipt_tax: Optional[Decimal] = None,
        receipt_tip: Optional[Decimal] = None,
    ) -> Tuple[float, str, bool, bool]:
        """
        Match receipt amount to transaction amount.

        Returns:
            (score, explanation, is_tip_adjusted, is_fee_adjusted)
        """
        if receipt_amount <= 0 or transaction_amount <= 0:
            return 0.0, "Invalid amount", False, False

        # Ensure Decimal types
        r_amt = Decimal(str(receipt_amount)).quantize(self.two_places)
        t_amt = Decimal(str(transaction_amount)).quantize(self.two_places)

        diff = abs(t_amt - r_amt)
        pct_diff = diff / max(r_amt, t_amt)

        # === EXACT MATCH ===
        if diff <= self.EXACT_TOLERANCE:
            return 1.0, f"Exact match: ${t_amt}", False, False

        # === SMALL DIFFERENCE (fees/rounding) ===
        if diff <= self.FEE_TOLERANCE:
            score = 0.95 - (float(diff) * 0.02)  # Small penalty for each dollar diff
            return max(0.90, score), f"Close match (${diff} difference, likely fee)", False, True

        # === RESTAURANT TIP ADJUSTMENT ===
        if is_restaurant and t_amt > r_amt:
            # Calculate what tip percentage this would be
            base_amount = receipt_subtotal if receipt_subtotal else r_amt
            implied_tip = t_amt - r_amt
            implied_tip_pct = implied_tip / base_amount

            # If we have the actual tip from receipt, compare
            if receipt_tip:
                # Transaction should be subtotal + tax + tip
                expected_total = base_amount + (receipt_tax or Decimal('0')) + receipt_tip
                if abs(t_amt - expected_total) <= self.EXACT_TOLERANCE:
                    return 0.98, f"Exact match with ${receipt_tip} tip", True, False

            # Check if implied tip is in reasonable range
            if self.TIP_MIN_PCT <= implied_tip_pct <= self.TIP_MAX_PCT:
                # Higher score for tips closer to typical 20%
                tip_deviation = abs(implied_tip_pct - self.TIP_TYPICAL_PCT)
                score = 0.92 - float(tip_deviation) * 0.5
                return max(0.80, score), f"Tip adjusted: ${implied_tip:.2f} ({implied_tip_pct:.0%} tip)", True, False

        # === SUBSCRIPTION TAX VARIATION ===
        if is_subscription and t_amt > r_amt:
            implied_tax = t_amt - r_amt
            implied_tax_pct = implied_tax / r_amt

            if implied_tax_pct <= self.TAX_MAX_PCT:
                score = 0.90 - float(implied_tax_pct) * 2
                return max(0.80, score), f"Tax adjusted: ${implied_tax:.2f} ({implied_tax_pct:.1%} tax)", False, True

        # === INTERNATIONAL FOREX FEE ===
        if is_international and t_amt > r_amt:
            implied_fee_pct = (t_amt - r_amt) / r_amt
            if implied_fee_pct <= self.FOREX_FEE_PCT:
                return 0.88, f"Forex fee adjusted: {implied_fee_pct:.1%} fee", False, True

        # === PERCENTAGE-BASED SCORING ===
        if pct_diff <= Decimal('0.02'):  # 2%
            return 0.85, f"Within 2% (${diff} difference)", False, False
        elif pct_diff <= Decimal('0.05'):  # 5%
            return 0.70, f"Within 5% (${diff} difference)", False, False
        elif pct_diff <= Decimal('0.10'):  # 10%
            return 0.50, f"Within 10% (${diff} difference)", False, False
        elif pct_diff <= Decimal('0.20'):  # 20%
            return 0.30, f"Within 20% (${diff} difference)", False, False
        else:
            return 0.0, f"Amount mismatch: ${r_amt} vs ${t_amt}", False, False


# =============================================================================
# MERCHANT MATCHING
# =============================================================================

class MerchantMatcher:
    """
    Advanced merchant name matching with alias resolution.

    Handles:
    - Bank description -> canonical name resolution
    - POS prefix stripping (SQ*, TST*, DD*)
    - Fuzzy string matching
    - Chain/franchise variations
    - Location suffix removal
    """

    # Common POS/payment prefixes to strip
    POS_PREFIXES = [
        'sq *', 'sq*', 'tst *', 'tst*', 'dd *', 'dd*',
        'pp *', 'pp*', 'ppl*', 'zzz*', 'chk*',
        'pos ', 'pos*', 'dbt ', 'ach ',
    ]

    # Suffixes to remove
    LOCATION_PATTERNS = [
        r'\s*#\d+.*$',           # Store numbers: #1234
        r'\s+\d{5}(-\d{4})?$',   # ZIP codes: 12345 or 12345-6789
        r'\s+[A-Z]{2}\s*$',      # State codes: TN, CA
        r'\s+\d{3,4}$',          # Short numbers
        r'\s*-\s*\d+$',          # Dash numbers
        r'\s+\(\d+\)$',          # Parenthetical numbers
    ]

    # Words to remove
    NOISE_WORDS = {
        'inc', 'llc', 'corp', 'ltd', 'co', 'company',
        'the', 'and', '&', 'of', 'at', 'in',
    }

    def __init__(self, aliases: Dict[str, Tuple[str, str, bool]] = None):
        self.aliases = aliases or BANK_TO_CANONICAL
        self._build_alias_lookup()

    def _build_alias_lookup(self):
        """Build optimized alias lookup structures"""
        self.exact_lookup = {}
        self.prefix_lookup = []

        for pattern, (canonical, category, is_sub) in self.aliases.items():
            pattern_lower = pattern.lower()
            if pattern_lower.endswith('*'):
                # Prefix pattern
                self.prefix_lookup.append((
                    pattern_lower[:-1],
                    canonical,
                    category,
                    is_sub
                ))
            else:
                self.exact_lookup[pattern_lower] = (canonical, category, is_sub)

        # Sort prefix patterns by length (longest first) for best matching
        self.prefix_lookup.sort(key=lambda x: len(x[0]), reverse=True)

    def normalize(self, merchant: str) -> str:
        """Normalize merchant name for matching"""
        if not merchant:
            return ""

        m = merchant.lower().strip()

        # Remove POS prefixes
        for prefix in self.POS_PREFIXES:
            if m.startswith(prefix):
                m = m[len(prefix):].strip()
                break

        # Remove location patterns
        for pattern in self.LOCATION_PATTERNS:
            m = re.sub(pattern, '', m, flags=re.IGNORECASE)

        # Remove special characters except spaces
        m = re.sub(r'[^a-z0-9\s]', ' ', m)

        # Remove noise words
        words = m.split()
        words = [w for w in words if w not in self.NOISE_WORDS]

        # Collapse whitespace
        return ' '.join(words).strip()

    def resolve_canonical(self, merchant: str) -> Tuple[str, str, bool]:
        """
        Resolve bank merchant name to canonical form.

        Returns:
            (canonical_name, category, is_subscription)
        """
        m = merchant.lower().strip()

        # Check exact matches first
        for pattern, info in self.exact_lookup.items():
            if pattern in m:
                return info

        # Check prefix patterns
        for prefix, canonical, category, is_sub in self.prefix_lookup:
            if m.startswith(prefix):
                # Try to extract the actual merchant after prefix
                remainder = m[len(prefix):].strip()
                if remainder:
                    # For generic prefixes like "sq *", use the remainder
                    if canonical in ('Square Payment', 'Toast Payment', 'DoorDash', 'PayPal'):
                        return (remainder.title(), category, is_sub)
                return (canonical, category, is_sub)

        # No alias found, return normalized original
        normalized = self.normalize(merchant)
        return (normalized.title() if normalized else merchant, '', False)

    def match(
        self,
        receipt_merchant: str,
        transaction_merchant: str,
    ) -> Tuple[float, str]:
        """
        Match receipt merchant to transaction merchant.

        Returns:
            (score, explanation)
        """
        if not receipt_merchant or not transaction_merchant:
            return 0.0, "Missing merchant name"

        # Resolve to canonical forms
        r_canonical, r_cat, r_sub = self.resolve_canonical(receipt_merchant)
        t_canonical, t_cat, t_sub = self.resolve_canonical(transaction_merchant)

        # Normalize for comparison
        r_norm = self.normalize(r_canonical)
        t_norm = self.normalize(t_canonical)

        # === EXACT MATCH ===
        if r_norm == t_norm:
            return 1.0, f"Exact match: {t_canonical}"

        # === CANONICAL MATCH ===
        # Both resolved to same canonical name
        if r_canonical.lower() == t_canonical.lower():
            return 0.98, f"Canonical match: {t_canonical}"

        # === SUBSTRING MATCH ===
        if r_norm in t_norm or t_norm in r_norm:
            return 0.90, f"Substring match: {r_canonical} ~ {t_canonical}"

        # === WORD OVERLAP ===
        r_words = set(r_norm.split())
        t_words = set(t_norm.split())

        if r_words and t_words:
            overlap = r_words & t_words
            if overlap:
                # First word match is most important (usually brand)
                r_first = r_norm.split()[0] if r_norm else ''
                t_first = t_norm.split()[0] if t_norm else ''

                if r_first == t_first:
                    score = 0.80 + (len(overlap) / max(len(r_words), len(t_words))) * 0.15
                    return min(0.92, score), f"Brand match: {r_first}"
                else:
                    score = 0.60 + (len(overlap) / max(len(r_words), len(t_words))) * 0.20
                    return min(0.80, score), f"Word overlap: {overlap}"

        # === FUZZY MATCHING ===
        ratio = SequenceMatcher(None, r_norm, t_norm).ratio()

        if ratio >= 0.85:
            return ratio * 0.95, f"Fuzzy match ({ratio:.0%}): {r_canonical} ~ {t_canonical}"
        elif ratio >= 0.70:
            return ratio * 0.85, f"Partial match ({ratio:.0%})"
        elif ratio >= 0.50:
            return ratio * 0.70, f"Weak match ({ratio:.0%})"
        else:
            return 0.0, f"No match: {r_canonical} vs {t_canonical}"


# =============================================================================
# DATE MATCHING
# =============================================================================

class DateMatcher:
    """
    Date matching with category-aware tolerances.

    Handles:
    - Same-day matches (highest confidence)
    - Next-day posting delays
    - Weekend/holiday processing delays
    - Subscription billing date variations
    - Delivery service delays
    """

    # Default tolerances (in days)
    TOLERANCE_RETAIL = 3
    TOLERANCE_RESTAURANT = 2
    TOLERANCE_SUBSCRIPTION = 7
    TOLERANCE_DELIVERY = 5
    TOLERANCE_TRAVEL = 14

    def match(
        self,
        receipt_date: Optional[datetime],
        transaction_date: Optional[datetime],
        is_subscription: bool = False,
        is_delivery: bool = False,
        is_travel: bool = False,
        is_restaurant: bool = False,
    ) -> Tuple[float, str]:
        """
        Match receipt date to transaction date.

        Returns:
            (score, explanation)
        """
        # Handle missing dates
        if not receipt_date:
            return 0.5, "No receipt date (neutral)"
        if not transaction_date:
            return 0.5, "No transaction date (neutral)"

        # Normalize to date only (ignore time)
        r_date = receipt_date.date() if hasattr(receipt_date, 'date') else receipt_date
        t_date = transaction_date.date() if hasattr(transaction_date, 'date') else transaction_date

        days_diff = abs((t_date - r_date).days)

        # Determine tolerance based on category
        if is_travel:
            tolerance = self.TOLERANCE_TRAVEL
        elif is_subscription:
            tolerance = self.TOLERANCE_SUBSCRIPTION
        elif is_delivery:
            tolerance = self.TOLERANCE_DELIVERY
        elif is_restaurant:
            tolerance = self.TOLERANCE_RESTAURANT
        else:
            tolerance = self.TOLERANCE_RETAIL

        # === EXACT MATCH ===
        if days_diff == 0:
            return 1.0, "Same day"

        # === NEXT DAY (common posting delay) ===
        if days_diff == 1:
            return 0.95, "Next day posting"

        # === WITHIN TOLERANCE ===
        if days_diff <= tolerance:
            # Linear decay within tolerance
            score = 0.90 - (days_diff / tolerance) * 0.30
            return max(0.60, score), f"{days_diff} days apart (within {tolerance}-day tolerance)"

        # === EXTENDED TOLERANCE ===
        if days_diff <= tolerance * 2:
            score = 0.50 - ((days_diff - tolerance) / tolerance) * 0.30
            return max(0.20, score), f"{days_diff} days apart (extended tolerance)"

        # === TOO FAR APART ===
        return 0.0, f"{days_diff} days apart (beyond tolerance)"


# =============================================================================
# COLLISION RESOLUTION
# =============================================================================

class CollisionResolver:
    """
    Resolves same-day same-merchant collisions.

    Strategies:
    1. Amount differentiation (most reliable)
    2. Time-of-day hints from receipt
    3. Line item count/content
    4. Receipt source differentiation
    """

    def resolve(
        self,
        receipt: Receipt,
        candidates: List[Tuple[Transaction, MatchScore]],
    ) -> Tuple[Optional[Transaction], str]:
        """
        Resolve collision among multiple candidate transactions.

        Returns:
            (best_transaction, resolution_reason) or (None, reason) if unresolved
        """
        if not candidates:
            return None, "No candidates"

        if len(candidates) == 1:
            return candidates[0][0], "Single candidate"

        # Sort by score
        sorted_candidates = sorted(candidates, key=lambda x: x[1].total, reverse=True)

        best = sorted_candidates[0]
        second = sorted_candidates[1] if len(sorted_candidates) > 1 else None

        # === CLEAR WINNER BY SCORE ===
        if second and best[1].total - second[1].total >= 0.15:
            return best[0], f"Clear score difference: {best[1].total:.2%} vs {second[1].total:.2%}"

        # === AMOUNT DIFFERENTIATION ===
        # If amounts differ, prefer exact/closer match
        amount_scores = [(c[0], c[1].amount_score, c[1]) for c in sorted_candidates]
        best_amount = max(amount_scores, key=lambda x: x[1])

        if best_amount[1] >= 0.95 and all(
            a[1] < 0.90 for a in amount_scores if a[0].id != best_amount[0].id
        ):
            return best_amount[0], f"Amount differentiation: exact match"

        # === TIME-OF-DAY HINTS ===
        # If receipt has time info and we have morning/afternoon transactions
        # (This would require additional data not always available)

        # === UNRESOLVED - NEEDS MANUAL REVIEW ===
        tx_descriptions = [f"{c[0].merchant} ${c[0].amount}" for c in sorted_candidates[:3]]
        return None, f"Collision unresolved: {', '.join(tx_descriptions)}"


# =============================================================================
# CONTEXT BOOSTING
# =============================================================================

class ContextBooster:
    """
    Applies context-aware bonuses to match scores.

    Boosts:
    - Calendar event at same location (+10 points)
    - Contact name on receipt (+5 points)
    - Historical match pattern (+5 points)
    - Same business type (+3 points)
    """

    CALENDAR_BONUS = 0.10
    CONTACT_BONUS = 0.05
    HISTORICAL_BONUS = 0.05
    BUSINESS_TYPE_BONUS = 0.03

    def __init__(self, db_connection=None):
        self.db = db_connection
        self.historical_matches: Dict[str, str] = {}  # merchant -> typical_bank_desc

    def load_historical_matches(self):
        """Load historical match patterns from database"""
        if not self.db:
            return

        try:
            cursor = self.db.cursor()
            cursor.execute('''
                SELECT DISTINCT
                    ir.merchant as receipt_merchant,
                    t.chase_description as bank_description
                FROM incoming_receipts ir
                JOIN transactions t ON ir.matched_transaction_id = t._index
                WHERE ir.status = 'accepted'
                AND ir.match_score >= 0.80
            ''')
            for row in cursor.fetchall():
                r_merchant = row.get('receipt_merchant', '').lower()
                b_desc = row.get('bank_description', '')
                if r_merchant and b_desc:
                    self.historical_matches[r_merchant] = b_desc
        except Exception as e:
            logger.warning(f"Could not load historical matches: {e}")

    def calculate_bonus(
        self,
        receipt: Receipt,
        transaction: Transaction,
        calendar_events: List[Dict] = None,
        contacts: List[Dict] = None,
    ) -> Tuple[float, str]:
        """
        Calculate context bonus for a match.

        Returns:
            (bonus_score, explanation)
        """
        total_bonus = 0.0
        explanations = []

        # === CALENDAR EVENT MATCH ===
        if calendar_events:
            for event in calendar_events:
                event_date = event.get('date')
                event_location = event.get('location', '').lower()

                # Check if event is on same day
                if event_date and receipt.date:
                    if abs((event_date - receipt.date).days) <= 1:
                        # Check location match
                        merchant_norm = receipt.merchant.lower()
                        if merchant_norm in event_location or event_location in merchant_norm:
                            total_bonus += self.CALENDAR_BONUS
                            explanations.append(f"Calendar event at {event.get('location')}")
                            break

        # === CONTACT ON RECEIPT ===
        if contacts and receipt.line_items:
            contact_names = {c.get('name', '').lower() for c in contacts if c.get('name')}

            for item in receipt.line_items:
                item_text = str(item).lower()
                for name in contact_names:
                    if name and len(name) > 2 and name in item_text:
                        total_bonus += self.CONTACT_BONUS
                        explanations.append(f"Contact '{name}' found on receipt")
                        break

        # === HISTORICAL MATCH PATTERN ===
        receipt_merchant_lower = receipt.merchant.lower()
        if receipt_merchant_lower in self.historical_matches:
            historical_bank = self.historical_matches[receipt_merchant_lower]
            if historical_bank.lower() in transaction.description.lower():
                total_bonus += self.HISTORICAL_BONUS
                explanations.append("Historical match pattern")

        # === BUSINESS TYPE MATCH ===
        if receipt.source and transaction.business_type:
            if receipt.source.lower() == transaction.business_type.lower():
                total_bonus += self.BUSINESS_TYPE_BONUS
                explanations.append(f"Business type match: {transaction.business_type}")

        explanation = "; ".join(explanations) if explanations else "No context bonus"
        return total_bonus, explanation


# =============================================================================
# LEARNING ENGINE
# =============================================================================

class MatchLearner:
    """
    Learns from manual matches and rejections to improve future matching.

    Features:
    - Records successful manual matches
    - Records rejections with reasons
    - Builds merchant alias suggestions
    - Adjusts confidence thresholds
    """

    def __init__(self, db_connection=None):
        self.db = db_connection
        self.learned_aliases: Dict[str, str] = {}  # bank_desc -> canonical
        self.rejection_patterns: List[Dict] = []
        self._lock = threading.Lock()

    def record_match(
        self,
        receipt: Receipt,
        transaction: Transaction,
        was_manual: bool,
        score: float,
    ):
        """Record a successful match for learning"""
        if not self.db:
            return

        try:
            cursor = self.db.cursor()
            cursor.execute('''
                INSERT INTO match_learning (
                    receipt_merchant, bank_description,
                    receipt_amount, transaction_amount,
                    was_manual, match_score, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ''', (
                receipt.merchant,
                transaction.description,
                float(receipt.amount),
                float(transaction.amount),
                was_manual,
                score,
            ))
            self.db.commit()

            # Update in-memory aliases
            if was_manual and score < 0.70:
                with self._lock:
                    bank_norm = transaction.description.lower()
                    self.learned_aliases[bank_norm] = receipt.merchant

        except Exception as e:
            logger.warning(f"Could not record match: {e}")

    def record_rejection(
        self,
        receipt: Receipt,
        transaction: Transaction,
        reason: str,
    ):
        """Record a rejected match for learning"""
        if not self.db:
            return

        try:
            cursor = self.db.cursor()
            cursor.execute('''
                INSERT INTO match_rejections (
                    receipt_merchant, bank_description,
                    receipt_amount, transaction_amount,
                    rejection_reason, created_at
                ) VALUES (%s, %s, %s, %s, %s, NOW())
            ''', (
                receipt.merchant,
                transaction.description,
                float(receipt.amount),
                float(transaction.amount),
                reason,
            ))
            self.db.commit()

        except Exception as e:
            logger.warning(f"Could not record rejection: {e}")

    def get_learned_alias(self, bank_description: str) -> Optional[str]:
        """Get learned canonical name for bank description"""
        with self._lock:
            return self.learned_aliases.get(bank_description.lower())


# =============================================================================
# MAIN MATCHER CLASS
# =============================================================================

class SmartMatcherV2:
    """
    Production-grade receipt-to-transaction matching engine.

    Usage:
        matcher = SmartMatcherV2(db_connection)

        # Match single receipt
        result = matcher.match(receipt, transactions)

        # Batch match
        results = matcher.match_batch(receipts, transactions)
    """

    def __init__(self, db_connection=None):
        self.db = db_connection

        # Initialize components
        self.amount_matcher = AmountMatcher()
        self.merchant_matcher = MerchantMatcher()
        self.date_matcher = DateMatcher()
        self.collision_resolver = CollisionResolver()
        self.context_booster = ContextBooster(db_connection)
        self.learner = MatchLearner(db_connection)

        # Load historical data
        self.context_booster.load_historical_matches()

        # Weights (can be adjusted based on learning)
        self.default_weights = {
            'amount': 0.45,
            'merchant': 0.40,
            'date': 0.15,
        }

        # Statistics
        self.stats = {
            'total_matches': 0,
            'auto_high': 0,
            'auto_good': 0,
            'review': 0,
            'no_match': 0,
            'collisions': 0,
        }

    def _determine_weights(
        self,
        amount_score: float,
        merchant_score: float,
        is_subscription: bool,
    ) -> Dict[str, float]:
        """Dynamically adjust weights based on signal quality"""

        # High amount confidence -> trust amount more
        if amount_score >= 0.95:
            return {'amount': 0.55, 'merchant': 0.35, 'date': 0.10}

        # High merchant confidence -> trust merchant more
        if merchant_score >= 0.95:
            return {'amount': 0.40, 'merchant': 0.50, 'date': 0.10}

        # Subscription -> date is less reliable (billing cycles vary)
        if is_subscription:
            return {'amount': 0.50, 'merchant': 0.40, 'date': 0.10}

        return self.default_weights

    def _calculate_score(
        self,
        receipt: Receipt,
        transaction: Transaction,
        calendar_events: List[Dict] = None,
        contacts: List[Dict] = None,
    ) -> MatchScore:
        """Calculate comprehensive match score"""

        # Determine transaction characteristics
        _, t_category, is_subscription = self.merchant_matcher.resolve_canonical(
            transaction.description
        )
        is_restaurant = t_category in RESTAURANT_CATEGORIES
        is_delivery = t_category in DELIVERY_CATEGORIES
        is_travel = t_category == 'travel'

        # === AMOUNT MATCHING ===
        amount_score, amount_exp, is_tip, is_fee = self.amount_matcher.match(
            receipt.amount,
            transaction.amount,
            is_restaurant=is_restaurant,
            is_subscription=is_subscription,
            receipt_subtotal=receipt.subtotal,
            receipt_tax=receipt.tax,
            receipt_tip=receipt.tip,
        )

        # === MERCHANT MATCHING ===
        merchant_score, merchant_exp = self.merchant_matcher.match(
            receipt.merchant,
            transaction.description,
        )

        # === DATE MATCHING ===
        date_score, date_exp = self.date_matcher.match(
            receipt.date,
            transaction.date,
            is_subscription=is_subscription,
            is_delivery=is_delivery,
            is_travel=is_travel,
            is_restaurant=is_restaurant,
        )

        # === DETERMINE WEIGHTS ===
        weights = self._determine_weights(amount_score, merchant_score, is_subscription)

        # === CALCULATE WEIGHTED TOTAL ===
        weighted_total = (
            amount_score * weights['amount'] +
            merchant_score * weights['merchant'] +
            date_score * weights['date']
        )

        # === CONTEXT BONUS ===
        context_bonus, context_exp = self.context_booster.calculate_bonus(
            receipt, transaction, calendar_events, contacts
        )

        # === FINAL SCORE ===
        final_score = min(1.0, weighted_total + context_bonus)

        # === DETERMINE CONFIDENCE LEVEL ===
        if final_score >= AUTO_HIGH_THRESHOLD:
            confidence = MatchConfidence.AUTO_HIGH
        elif final_score >= AUTO_GOOD_THRESHOLD:
            confidence = MatchConfidence.AUTO_GOOD
        elif final_score >= REVIEW_THRESHOLD:
            confidence = MatchConfidence.REVIEW
        else:
            confidence = MatchConfidence.NO_MATCH

        return MatchScore(
            total=final_score,
            confidence=confidence,
            amount_score=amount_score,
            merchant_score=merchant_score,
            date_score=date_score,
            context_bonus=context_bonus,
            amount_explanation=amount_exp,
            merchant_explanation=merchant_exp,
            date_explanation=date_exp,
            context_explanation=context_exp,
            is_tip_adjusted=is_tip,
            is_fee_adjusted=is_fee,
            is_subscription=is_subscription,
            is_restaurant=is_restaurant,
        )

    def match(
        self,
        receipt: Receipt,
        transactions: List[Transaction],
        calendar_events: List[Dict] = None,
        contacts: List[Dict] = None,
        exclude_with_receipts: bool = True,
    ) -> MatchResult:
        """
        Find the best matching transaction for a receipt.

        Args:
            receipt: Receipt to match
            transactions: List of candidate transactions
            calendar_events: Optional calendar events for context
            contacts: Optional contacts for context
            exclude_with_receipts: Skip transactions that already have receipts

        Returns:
            MatchResult with best match or collision details
        """
        self.stats['total_matches'] += 1

        # Filter available transactions
        available = transactions
        if exclude_with_receipts:
            available = [t for t in transactions if not t.has_receipt]

        if not available:
            return MatchResult(receipt_id=receipt.id, matched=False)

        # Score all candidates
        candidates: List[Tuple[Transaction, MatchScore]] = []

        for tx in available:
            score = self._calculate_score(receipt, tx, calendar_events, contacts)

            if score.confidence != MatchConfidence.NO_MATCH:
                candidates.append((tx, score))

        if not candidates:
            self.stats['no_match'] += 1
            return MatchResult(receipt_id=receipt.id, matched=False)

        # Sort by score
        candidates.sort(key=lambda x: x[1].total, reverse=True)

        best_tx, best_score = candidates[0]

        # Check for collision (multiple high-scoring candidates)
        high_scoring = [c for c in candidates if c[1].total >= REVIEW_THRESHOLD]

        if len(high_scoring) > 1:
            # Check if scores are too close
            score_diff = high_scoring[0][1].total - high_scoring[1][1].total

            if score_diff < 0.10:  # Less than 10% difference
                self.stats['collisions'] += 1

                # Try to resolve collision
                resolved_tx, reason = self.collision_resolver.resolve(receipt, high_scoring)

                if resolved_tx:
                    # Find the score for resolved transaction
                    resolved_score = next(
                        s for t, s in candidates if t.id == resolved_tx.id
                    )
                    resolved_score.collision_penalty = -0.05  # Small penalty for collision
                    resolved_score.total = max(0, resolved_score.total - 0.05)

                    self._update_stats(resolved_score.confidence)

                    return MatchResult(
                        receipt_id=receipt.id,
                        transaction_id=resolved_tx.id,
                        score=resolved_score,
                        matched=True,
                        candidates=high_scoring,
                        collision_resolved=True,
                        resolution_reason=reason,
                    )
                else:
                    # Unresolved collision
                    return MatchResult(
                        receipt_id=receipt.id,
                        score=best_score,
                        matched=False,
                        candidates=high_scoring,
                        collision_resolved=False,
                        resolution_reason=reason,
                    )

        # Single clear winner
        self._update_stats(best_score.confidence)

        return MatchResult(
            receipt_id=receipt.id,
            transaction_id=best_tx.id,
            score=best_score,
            matched=best_score.confidence in (
                MatchConfidence.AUTO_HIGH,
                MatchConfidence.AUTO_GOOD,
            ),
        )

    def _update_stats(self, confidence: MatchConfidence):
        """Update match statistics"""
        if confidence == MatchConfidence.AUTO_HIGH:
            self.stats['auto_high'] += 1
        elif confidence == MatchConfidence.AUTO_GOOD:
            self.stats['auto_good'] += 1
        elif confidence == MatchConfidence.REVIEW:
            self.stats['review'] += 1
        else:
            self.stats['no_match'] += 1

    def match_batch(
        self,
        receipts: List[Receipt],
        transactions: List[Transaction],
        calendar_events: List[Dict] = None,
        contacts: List[Dict] = None,
    ) -> List[MatchResult]:
        """
        Match multiple receipts to transactions.
        Handles conflicts where multiple receipts could match same transaction.
        """
        results = []
        matched_tx_ids: Set[Any] = set()

        # Sort receipts by confidence (higher first)
        sorted_receipts = sorted(
            receipts,
            key=lambda r: r.confidence,
            reverse=True,
        )

        for receipt in sorted_receipts:
            # Filter out already-matched transactions
            available = [t for t in transactions if t.id not in matched_tx_ids]

            result = self.match(
                receipt, available, calendar_events, contacts,
                exclude_with_receipts=True,
            )

            results.append(result)

            if result.matched and result.transaction_id:
                matched_tx_ids.add(result.transaction_id)

        return results

    def get_stats(self) -> Dict:
        """Get matching statistics"""
        total = self.stats['total_matches']
        if total == 0:
            return self.stats

        return {
            **self.stats,
            'auto_match_rate': (
                self.stats['auto_high'] + self.stats['auto_good']
            ) / total,
            'review_rate': self.stats['review'] / total,
            'no_match_rate': self.stats['no_match'] / total,
            'collision_rate': self.stats['collisions'] / total,
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def parse_decimal(value: Any) -> Decimal:
    """Parse various formats to Decimal"""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if not value:
        return Decimal('0')

    # Remove currency symbols and commas
    cleaned = re.sub(r'[$,]', '', str(value))
    try:
        return Decimal(cleaned).quantize(Decimal('0.01'))
    except:
        return Decimal('0')


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse various date formats to datetime"""
    if isinstance(value, datetime):
        return value
    if not value:
        return None

    formats = [
        '%Y-%m-%d',
        '%Y-%m-%d %H:%M:%S',
        '%m/%d/%Y',
        '%m/%d/%y',
        '%d/%m/%Y',
        '%Y/%m/%d',
        '%b %d, %Y',
        '%B %d, %Y',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(str(value).strip()[:19], fmt)
        except ValueError:
            continue

    return None


def dict_to_transaction(row: Dict) -> Transaction:
    """Convert database row to Transaction"""
    return Transaction(
        id=row.get('_index') or row.get('id'),
        merchant=row.get('chase_description') or row.get('merchant', ''),
        amount=parse_decimal(row.get('chase_amount') or row.get('amount')),
        date=parse_datetime(row.get('chase_date') or row.get('date')),
        category=row.get('chase_category') or row.get('category', ''),
        description=row.get('chase_description') or row.get('description', ''),
        has_receipt=bool(row.get('receipt_file') or row.get('receipt_url')),
        receipt_url=row.get('receipt_url', ''),
        business_type=row.get('business_type', ''),
        notes=row.get('notes', ''),
    )


def dict_to_receipt(row: Dict) -> Receipt:
    """Convert database row to Receipt"""
    return Receipt(
        id=row.get('id'),
        merchant=row.get('merchant') or row.get('ocr_merchant', ''),
        amount=parse_decimal(row.get('amount') or row.get('ocr_amount')),
        date=parse_datetime(
            row.get('transaction_date') or row.get('receipt_date') or row.get('ocr_date')
        ),
        confidence=float(row.get('confidence_score') or row.get('ocr_confidence') or 0),
        subtotal=parse_decimal(row.get('ocr_subtotal')),
        tax=parse_decimal(row.get('ocr_tax')),
        tip=parse_decimal(row.get('ocr_tip')),
        source=row.get('source', ''),
        file_path=row.get('receipt_file', ''),
    )


# =============================================================================
# CLI & TESTING
# =============================================================================

if __name__ == '__main__':
    import sys

    print("Smart Matcher V2 - Production Test")
    print("=" * 60)

    # Initialize matcher
    matcher = SmartMatcherV2()

    # Test cases covering all edge cases
    test_cases = [
        # (receipt_merchant, receipt_amount, tx_merchant, tx_amount, expected_match)

        # Exact matches
        ("Starbucks", 5.75, "SQ *STARBUCKS", 5.75, True),
        ("Amazon", 25.00, "AMZN MKTP US*123ABC", 25.00, True),

        # Bank name variations
        ("Apple Inc.", 9.99, "APPLE.COM/BILL", 9.99, True),
        ("Anthropic", 20.00, "CLAUDE.AI SUBSCRIPTION", 20.00, True),
        ("Uber", 15.50, "UBER *TRIP", 15.50, True),

        # Tip scenarios
        ("Corner Pub", 85.00, "TST* CORNER PUB", 102.00, True),  # 20% tip
        ("Soho House", 150.00, "SH NASHVILLE", 180.00, True),  # 20% tip

        # Fee variations
        ("Spotify", 9.99, "SPOTIFY USA", 10.84, True),  # Tax
        ("Netflix", 15.49, "NETFLIX.COM", 15.99, True),  # Small fee

        # Should NOT match
        ("Target", 50.00, "WALMART", 50.00, False),
        ("Starbucks", 5.75, "AMAZON", 5.75, False),
    ]

    print("\nRunning test cases...")
    passed = 0
    failed = 0

    for r_merchant, r_amount, t_merchant, t_amount, expected in test_cases:
        receipt = Receipt(
            id=1,
            merchant=r_merchant,
            amount=Decimal(str(r_amount)),
            date=datetime.now(),
        )

        transaction = Transaction(
            id=1,
            merchant=t_merchant,
            amount=Decimal(str(t_amount)),
            date=datetime.now(),
            description=t_merchant,
        )

        result = matcher.match(receipt, [transaction], exclude_with_receipts=False)

        matched = result.matched
        score = result.score.total if result.score else 0

        status = "PASS" if matched == expected else "FAIL"
        if matched == expected:
            passed += 1
        else:
            failed += 1

        print(f"\n{status}: {r_merchant} ${r_amount} -> {t_merchant} ${t_amount}")
        print(f"  Score: {score:.2%}, Expected match: {expected}, Got: {matched}")
        if result.score:
            print(f"  Amount: {result.score.amount_explanation}")
            print(f"  Merchant: {result.score.merchant_explanation}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print(f"Stats: {matcher.get_stats()}")
