"""
Merchant-First Receipt Matcher
==============================

WRONG (old approach):
  Score = 0.55 * amount_score + 0.35 * merchant_score + 0.10 * date_score
  → High amount match can override zero merchant match
  → $14.99 Anthropic API matches $14.99 parking ticket

RIGHT (this approach):
  IF merchant_match >= threshold:
      Score = amount_score * date_score * merchant_bonus
  ELSE:
      Score = 0  # No match possible without merchant foundation

Merchant-first receipt to transaction matching engine.
Amount verifies merchant matches; it never discovers them.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from difflib import SequenceMatcher
from collections import defaultdict
from datetime import datetime, date


class MatchTier(Enum):
    AUTO_MATCH = "auto_match"           # ≥85: proceed without review
    HIGH_CONFIDENCE = "high_confidence"  # 70-84: match with note
    REVIEW = "review"                    # 50-69: human review
    LOW_CONFIDENCE = "low_confidence"    # 30-49: possible only
    NO_MATCH = "no_match"               # <30: don't suggest


@dataclass
class MatchResult:
    receipt_id: str
    transaction_id: str
    confidence: float
    tier: MatchTier
    merchant_score: float
    amount_score: float
    date_score: float
    reasoning: str
    flags: List[str]


# ============================================================
# MERCHANT MATCHING — THE GATEKEEPER
# ============================================================

# Known merchant aliases (bank descriptor → canonical name)
MERCHANT_ALIASES = {
    # Tech / Software
    "anthropic": ["anthropic", "claude"],
    "openai": ["openai", "chatgpt"],
    "github": ["github", "gh "],
    "microsoft": ["microsoft", "msft", "azure", "ms "],
    "apple": ["apple.com", "apple ", "itunes", "app store", "applecash", "applecare"],
    "google": ["google", "goog ", "youtube", "google cloud", "gsuite"],
    "amazon": ["amzn", "amazon", "aws ", "prime video", "audible"],
    "stripe": ["stripe"],
    "notion": ["notion"],
    "midjourney": ["midjourney"],
    "cursor": ["cursor"],
    "railway": ["railway"],
    "vercel": ["vercel"],
    "cloudflare": ["cloudflare"],
    "huggingface": ["huggingface", "hugging face"],
    "suno": ["suno"],
    "ideogram": ["ideogram"],
    "ada": ["im-ada", "ada.ai", "ada ai"],
    "kit": ["kit.com", "kit "],
    "taskade": ["taskade"],
    "mongodb": ["mongodb", "mongo"],
    "imdb": ["imdb", "imdbpro"],

    # Food & Dining
    "doordash": ["doordash", "dd *", "dd*"],
    "uber eats": ["uber eats", "ubereats", "uber *eats"],
    "grubhub": ["grubhub"],
    "starbucks": ["starbucks", "sbux"],
    "chipotle": ["chipotle"],
    "chick-fil-a": ["chick-fil-a", "chick fil a", "cfa "],
    "corner pub": ["corner pub"],
    "soho house": ["soho house", "sh nashville"],

    # Travel & Transport
    "uber": ["uber trip", "uber *trip", "uber*"],
    "lyft": ["lyft"],
    "delta": ["delta air", "delta.com"],
    "american airlines": ["american air", "aa.com"],
    "united": ["united air", "united.com"],
    "southwest": ["southwest", "southwes", "swa "],
    "marriott": ["marriott", "bonvoy"],
    "hilton": ["hilton", "hhonors"],
    "airbnb": ["airbnb"],
    "virgin hotels": ["virgin hotel", "vhlv"],
    "resorts world": ["resorts world", "rwlv"],
    "holiday inn": ["holiday inn", "hoteltonight"],

    # Retail
    "walmart": ["walmart", "wal-mart", "wm supercenter"],
    "target": ["target"],
    "costco": ["costco"],
    "home depot": ["home depot", "homedepot"],
    "lowes": ["lowes", "lowe's"],
    "best buy": ["best buy", "bestbuy"],
    "nordstrom": ["nordstrom"],
    "suitsupply": ["suitsupply", "suit supply"],
    "paige": ["paige"],

    # Parking & Transit (the culprits!)
    "metropolis": ["metropolis", "metro park"],
    "spothero": ["spothero", "spot hero"],
    "parkwhiz": ["parkwhiz"],
    "parkme": ["parkme"],
    "laz parking": ["laz parking"],
    "pmc parking": ["pmc ", "pmc-"],

    # Subscriptions
    "netflix": ["netflix"],
    "spotify": ["spotify"],
    "hulu": ["hulu"],
    "disney": ["disney+", "disney plus", "disneyplus"],
    "adobe": ["adobe"],
    "dropbox": ["dropbox"],
    "slack": ["slack"],
    "zoom": ["zoom.us", "zoom video"],
    "verizon": ["verizon", "vzwrlss"],
    "clear": ["clear ", "clearme"],

    # Square / Toast merchants (need special handling)
    "square": ["sq *", "sq*", "gosq.com"],
    "toast": ["tst*", "tst *"],
}

# Patterns to strip from merchant names before comparison
STRIP_PATTERNS = [
    r'\*+',                    # Asterisks
    r'#\d+',                   # Store numbers
    r'\d{5,}',                 # Long number sequences
    r'\b(inc|llc|ltd|corp|pbc)\b', # Business suffixes
    r'\s+',                    # Collapse whitespace
]

# Words to ignore when matching (too common)
IGNORE_WORDS = {
    'inc', 'llc', 'ltd', 'corp', 'pbc', 'co', 'company',
    'the', 'and', 'of', 'at', 'in', 'for', 'a', 'an',
    'store', 'shop', 'cafe', 'bar', 'restaurant', 'grill', 'hotel',
    'services', 'service', 'payments', 'payment', 'subscription',
    'purchase', 'order', 'transaction',
    # Location words
    'nashville', 'las', 'vegas', 'downtown', 'airport', 'north', 'south', 'east', 'west',
    'park', 'center', 'centre', 'plaza', 'mall', 'ave', 'street', 'road', 'blvd'
}


def normalize_merchant(name: str) -> str:
    """Normalize merchant name for comparison."""
    if not name:
        return ""

    text = name.lower().strip()

    for pattern in STRIP_PATTERNS:
        text = re.sub(pattern, ' ', text, flags=re.IGNORECASE)

    return ' '.join(text.split())  # Collapse whitespace


def get_canonical_merchant(name: str) -> Tuple[str, str]:
    """
    Return (canonical_name, matched_alias) for a merchant.
    Returns (normalized_name, '') if no alias found.
    """
    normalized = normalize_merchant(name)

    for canonical, aliases in MERCHANT_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                return canonical, alias

    return normalized, ''


def merchant_similarity(name1: str, name2: str) -> float:
    """
    Calculate merchant name similarity.
    Returns 0.0 to 1.0
    """
    if not name1 or not name2:
        return 0.0

    # First, check canonical names
    canon1, _ = get_canonical_merchant(name1)
    canon2, _ = get_canonical_merchant(name2)

    if canon1 and canon2 and canon1 == canon2:
        return 1.0

    # Fuzzy match on normalized names
    norm1 = normalize_merchant(name1)
    norm2 = normalize_merchant(name2)

    if not norm1 or not norm2:
        return 0.0

    # Check if one contains the other
    if norm1 in norm2 or norm2 in norm1:
        return 0.9

    # Check word overlap (excluding common words)
    words1 = set(w for w in norm1.split() if w not in IGNORE_WORDS and len(w) > 2)
    words2 = set(w for w in norm2.split() if w not in IGNORE_WORDS and len(w) > 2)

    if words1 and words2:
        overlap = len(words1 & words2)
        if overlap > 0:
            total = len(words1 | words2)
            word_similarity = overlap / total if total > 0 else 0
            return 0.7 + (word_similarity * 0.3)

    # Check partial word matches (first 4+ chars)
    for w1 in words1:
        for w2 in words2:
            if len(w1) >= 4 and len(w2) >= 4:
                if w1[:4] == w2[:4]:
                    return 0.65

    # Fall back to sequence matching
    ratio = SequenceMatcher(None, norm1, norm2).ratio()
    return ratio if ratio > 0.6 else 0.0  # Only count if reasonably similar


# ============================================================
# AMOUNT MATCHING — THE VERIFIER
# ============================================================

def amount_similarity(
    receipt_amount: float,
    transaction_amount: float,
    allow_tip: bool = True,
    allow_tax: bool = True
) -> Tuple[float, str]:
    """
    Calculate amount match score.
    Returns (score 0.0-1.0, reason string)
    """
    if receipt_amount <= 0 or transaction_amount <= 0:
        return 0.0, "invalid amounts"

    # Exact match
    if abs(receipt_amount - transaction_amount) < 0.01:
        return 1.0, "exact match"

    # Within rounding (1 cent)
    if abs(receipt_amount - transaction_amount) <= 0.02:
        return 0.98, "rounding difference"

    diff = transaction_amount - receipt_amount
    pct_diff = diff / receipt_amount if receipt_amount > 0 else float('inf')

    # Transaction higher — could be tip or tax
    if diff > 0:
        # Tip range: 15-30% higher
        if allow_tip and 0.14 <= pct_diff <= 0.35:
            return 0.85, f"likely tip ({pct_diff:.0%} higher)"

        # Tax range: up to 12% higher
        if allow_tax and 0.01 <= pct_diff <= 0.12:
            return 0.90, f"likely tax ({pct_diff:.0%} higher)"

        # Small variance (under 5%)
        if pct_diff <= 0.05:
            return 0.80, f"small variance ({pct_diff:.1%} higher)"

    # Transaction lower — partial refund or discount?
    if diff < 0 and abs(pct_diff) <= 0.15:
        return 0.70, f"transaction lower ({abs(pct_diff):.1%})"

    # Within 20% — weak signal
    if abs(pct_diff) <= 0.20:
        return 0.40, f"within 20% ({pct_diff:+.1%})"

    return 0.0, f"amount mismatch ({pct_diff:+.1%})"


# ============================================================
# DATE MATCHING — THE TIE-BREAKER
# ============================================================

def date_similarity(
    receipt_date,  # datetime or date
    transaction_date,  # datetime or date
    max_days: int = 7
) -> Tuple[float, str]:
    """
    Calculate date proximity score.
    Returns (score 0.0-1.0, reason string)
    """
    # Normalize to date objects
    if isinstance(receipt_date, datetime):
        receipt_date = receipt_date.date()
    if isinstance(transaction_date, datetime):
        transaction_date = transaction_date.date()

    if not receipt_date or not transaction_date:
        return 0.5, "date missing"  # Neutral, don't penalize

    try:
        if isinstance(receipt_date, str):
            receipt_date = datetime.strptime(receipt_date, '%Y-%m-%d').date()
        if isinstance(transaction_date, str):
            transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
    except:
        return 0.5, "date parse error"

    days_diff = abs((transaction_date - receipt_date).days)

    if days_diff == 0:
        return 1.0, "same day"
    elif days_diff == 1:
        return 0.95, "1 day apart"
    elif days_diff <= 3:
        return 0.85, f"{days_diff} days apart (normal posting)"
    elif days_diff <= 5:
        return 0.70, f"{days_diff} days apart"
    elif days_diff <= max_days:
        return 0.50, f"{days_diff} days apart (edge of range)"
    else:
        return 0.0, f"{days_diff} days apart (too far)"


# ============================================================
# THE MATCHER — MERCHANT-FIRST ARCHITECTURE
# ============================================================

@dataclass
class Receipt:
    id: str
    merchant_name: str
    amount: float
    date: Any  # datetime or date
    email_from: str = ""
    raw_text: str = ""
    image_url: str = ""


@dataclass
class Transaction:
    id: str
    index: int  # _index in database
    merchant_name: str
    amount: float
    date: Any  # datetime or date
    category: str = ""
    already_matched: bool = False


class MerchantFirstMatcher:
    """
    Receipt-to-transaction matcher that requires merchant match
    before considering amount.
    """

    # Thresholds
    MERCHANT_THRESHOLD = 0.50      # Minimum merchant similarity to consider
    AUTO_MATCH_THRESHOLD = 0.85    # Auto-match without review
    HIGH_CONFIDENCE_THRESHOLD = 0.70
    REVIEW_THRESHOLD = 0.50
    LOW_CONFIDENCE_THRESHOLD = 0.30

    def __init__(self):
        self.learned_aliases: Dict[str, set] = defaultdict(set)
        self.match_history: List[MatchResult] = []

    def match_receipt(
        self,
        receipt: Receipt,
        transactions: List[Transaction],
        require_merchant: bool = True
    ) -> List[MatchResult]:
        """
        Find matching transactions for a receipt.

        Args:
            receipt: The receipt to match
            transactions: Available transactions to match against
            require_merchant: If True (default), merchant must match above threshold

        Returns:
            List of potential matches, sorted by confidence descending
        """
        candidates = []

        for txn in transactions:
            if txn.already_matched:
                continue

            result = self._score_match(receipt, txn, require_merchant)

            if result.tier != MatchTier.NO_MATCH:
                candidates.append(result)

        # Sort by confidence descending
        candidates.sort(key=lambda x: x.confidence, reverse=True)

        return candidates

    def _score_match(
        self,
        receipt: Receipt,
        txn: Transaction,
        require_merchant: bool
    ) -> MatchResult:
        """Score a single receipt-transaction pair."""

        flags = []

        # ============================================
        # GATE 1: Merchant matching (REQUIRED)
        # ============================================
        merchant_score = merchant_similarity(
            receipt.merchant_name or receipt.email_from,
            txn.merchant_name
        )

        # Check learned aliases
        receipt_canon, _ = get_canonical_merchant(receipt.merchant_name or receipt.email_from)
        txn_canon, _ = get_canonical_merchant(txn.merchant_name)

        if receipt_canon in self.learned_aliases:
            if txn_canon in self.learned_aliases[receipt_canon]:
                merchant_score = max(merchant_score, 0.85)
                flags.append("learned_alias")

        # CRITICAL: If merchant doesn't match, stop here
        if require_merchant and merchant_score < self.MERCHANT_THRESHOLD:
            return MatchResult(
                receipt_id=receipt.id,
                transaction_id=txn.id,
                confidence=0.0,
                tier=MatchTier.NO_MATCH,
                merchant_score=merchant_score,
                amount_score=0.0,
                date_score=0.0,
                reasoning=f"Merchant mismatch: '{receipt.merchant_name}' vs '{txn.merchant_name}' ({merchant_score:.0%})",
                flags=["merchant_gate_failed"]
            )

        # ============================================
        # GATE 2: Amount verification
        # ============================================
        is_restaurant = "restaurant" in txn.category.lower() if txn.category else False
        amount_score, amount_reason = amount_similarity(
            receipt.amount,
            txn.amount,
            allow_tip=is_restaurant
        )

        if amount_score < 0.30:
            flags.append("weak_amount_match")

        # ============================================
        # SIGNAL 3: Date proximity
        # ============================================
        date_score, date_reason = date_similarity(receipt.date, txn.date)

        if date_score < 0.50:
            flags.append("date_gap")

        # ============================================
        # CALCULATE FINAL CONFIDENCE
        # ============================================
        # Merchant-first weighting:
        # - Strong merchant required (gated above)
        # - Amount is primary verification
        # - Date is tie-breaker

        if merchant_score >= 0.90:
            # Very strong merchant match — amount verifies
            confidence = (
                0.35 * merchant_score +
                0.50 * amount_score +
                0.15 * date_score
            )
        elif merchant_score >= 0.70:
            # Good merchant match — need stronger amount
            confidence = (
                0.40 * merchant_score +
                0.45 * amount_score +
                0.15 * date_score
            )
        else:
            # Marginal merchant match — need excellent amount
            if amount_score >= 0.95:
                confidence = (
                    0.45 * merchant_score +
                    0.40 * amount_score +
                    0.15 * date_score
                )
            else:
                confidence = 0.25  # Too risky

        # ============================================
        # DATE GAP PENALTY
        # ============================================
        # If date is way off (score=0), cap confidence
        # A receipt from months/years ago is likely wrong
        if date_score == 0.0:
            # Cap at REVIEW tier max - even perfect merchant/amount
            # shouldn't AUTO_MATCH with 30+ day date gap
            confidence = min(confidence, 0.65)
            flags.append("date_penalty")

        # ============================================
        # DETERMINE TIER
        # ============================================
        if confidence >= self.AUTO_MATCH_THRESHOLD:
            tier = MatchTier.AUTO_MATCH
        elif confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            tier = MatchTier.HIGH_CONFIDENCE
        elif confidence >= self.REVIEW_THRESHOLD:
            tier = MatchTier.REVIEW
        elif confidence >= self.LOW_CONFIDENCE_THRESHOLD:
            tier = MatchTier.LOW_CONFIDENCE
        else:
            tier = MatchTier.NO_MATCH

        # ============================================
        # BUILD REASONING
        # ============================================
        reasoning = (
            f"Merchant: {merchant_score:.0%} | "
            f"Amount: {amount_score:.0%} ({amount_reason}) | "
            f"Date: {date_score:.0%} ({date_reason})"
        )

        return MatchResult(
            receipt_id=receipt.id,
            transaction_id=txn.id,
            confidence=confidence,
            tier=tier,
            merchant_score=merchant_score,
            amount_score=amount_score,
            date_score=date_score,
            reasoning=reasoning,
            flags=flags
        )

    def learn_alias(self, merchant1: str, merchant2: str):
        """Record that two merchant names refer to the same entity."""
        canon1, _ = get_canonical_merchant(merchant1)
        canon2, _ = get_canonical_merchant(merchant2)

        if canon1 and canon2:
            self.learned_aliases[canon1].add(canon2)
            self.learned_aliases[canon2].add(canon1)

    def match_all(
        self,
        receipts: List[Receipt],
        transactions: List[Transaction]
    ) -> Dict:
        """
        Match all receipts to transactions.
        Returns summary with matches and unmatched items.
        """
        results = {
            "auto_matched": [],
            "high_confidence": [],
            "needs_review": [],
            "low_confidence": [],
            "unmatched_receipts": [],
            "stats": {
                "total_receipts": len(receipts),
                "total_transactions": len(transactions),
            }
        }

        # Track which transactions are used
        used_txn_ids = set()

        for receipt in receipts:
            # Filter to available transactions
            available_txns = [t for t in transactions if t.id not in used_txn_ids]

            matches = self.match_receipt(receipt, available_txns)

            if not matches:
                results["unmatched_receipts"].append({
                    "receipt_id": receipt.id,
                    "merchant": receipt.merchant_name,
                    "amount": receipt.amount,
                    "reason": "no merchant matches found"
                })
                continue

            best_match = matches[0]

            if best_match.tier == MatchTier.AUTO_MATCH:
                results["auto_matched"].append(best_match)
                used_txn_ids.add(best_match.transaction_id)
            elif best_match.tier == MatchTier.HIGH_CONFIDENCE:
                results["high_confidence"].append(best_match)
                used_txn_ids.add(best_match.transaction_id)
            elif best_match.tier == MatchTier.REVIEW:
                results["needs_review"].append({
                    "best_match": best_match,
                    "alternatives": matches[1:3]  # Show runner-ups
                })
            elif best_match.tier == MatchTier.LOW_CONFIDENCE:
                results["low_confidence"].append({
                    "best_match": best_match,
                    "alternatives": matches[1:3]
                })
            else:
                results["unmatched_receipts"].append({
                    "receipt_id": receipt.id,
                    "merchant": receipt.merchant_name,
                    "amount": receipt.amount,
                    "reason": best_match.reasoning
                })

        # Calculate stats
        results["stats"]["auto_matched"] = len(results["auto_matched"])
        results["stats"]["high_confidence"] = len(results["high_confidence"])
        results["stats"]["needs_review"] = len(results["needs_review"])
        results["stats"]["unmatched"] = len(results["unmatched_receipts"])
        results["stats"]["match_rate"] = (
            (results["stats"]["auto_matched"] + results["stats"]["high_confidence"])
            / results["stats"]["total_receipts"]
        ) if results["stats"]["total_receipts"] > 0 else 0

        return results


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def quick_match(
    receipt_merchant: str,
    receipt_amount: float,
    receipt_date,
    txn_merchant: str,
    txn_amount: float,
    txn_date
) -> Dict:
    """Quick single-pair matching for testing."""

    receipt = Receipt(
        id="test_receipt",
        merchant_name=receipt_merchant,
        amount=receipt_amount,
        date=receipt_date
    )

    txn = Transaction(
        id="test_txn",
        index=0,
        merchant_name=txn_merchant,
        amount=txn_amount,
        date=txn_date
    )

    matcher = MerchantFirstMatcher()
    results = matcher.match_receipt(receipt, [txn])

    if results:
        r = results[0]
        return {
            "match": r.tier != MatchTier.NO_MATCH,
            "confidence": f"{r.confidence:.0%}",
            "tier": r.tier.value,
            "reasoning": r.reasoning
        }

    return {"match": False, "confidence": "0%", "tier": "no_match", "reasoning": "No candidates"}


# ============================================================
# EXAMPLE USAGE
# ============================================================

if __name__ == "__main__":
    from datetime import date

    # Your problem cases
    print("=== Testing Problem Cases ===\n")

    # Case 1: Anthropic → Metropolis (should NOT match)
    result = quick_match(
        receipt_merchant="Anthropic",
        receipt_amount=14.99,
        receipt_date=date(2024, 12, 1),
        txn_merchant="METROPOLIS PARKING",
        txn_amount=14.99,
        txn_date=date(2024, 12, 1)
    )
    print(f"Anthropic → Metropolis: {result}")
    assert not result["match"], "Should NOT match!"

    # Case 2: AppleCare → Catalina Bar (should NOT match)
    result = quick_match(
        receipt_merchant="Apple",
        receipt_amount=9.99,
        receipt_date=date(2024, 12, 1),
        txn_merchant="CATALINA BAR",
        txn_amount=9.99,
        txn_date=date(2024, 12, 1)
    )
    print(f"Apple → Catalina Bar: {result}")
    assert not result["match"], "Should NOT match!"

    # Case 3: Amazon → AMZN (SHOULD match)
    result = quick_match(
        receipt_merchant="Amazon.com",
        receipt_amount=47.82,
        receipt_date=date(2024, 12, 1),
        txn_merchant="AMZN MKTP US*1234",
        txn_amount=47.82,
        txn_date=date(2024, 12, 2)
    )
    print(f"Amazon → AMZN: {result}")
    assert result["match"], "Should match!"

    # Case 4: Starbucks with tip (SHOULD match)
    result = quick_match(
        receipt_merchant="Starbucks",
        receipt_amount=6.45,
        receipt_date=date(2024, 12, 1),
        txn_merchant="STARBUCKS #12345 NASHVILLE",
        txn_amount=7.45,  # $1 tip
        txn_date=date(2024, 12, 1)
    )
    print(f"Starbucks with tip: {result}")

    # Case 5: Claude → Anthropic (SHOULD match via alias)
    result = quick_match(
        receipt_merchant="Anthropic, PBC",
        receipt_amount=21.95,
        receipt_date=date(2024, 12, 1),
        txn_merchant="CLAUDE.AI SUBSCRIPTION",
        txn_amount=21.95,
        txn_date=date(2024, 12, 1)
    )
    print(f"Anthropic → Claude: {result}")
    assert result["match"], "Should match via alias!"

    # Case 6: Midjourney (SHOULD match)
    result = quick_match(
        receipt_merchant="Midjourney Inc",
        receipt_amount=21.95,
        receipt_date=date(2024, 12, 1),
        txn_merchant="MIDJOURNEY",
        txn_amount=21.95,
        txn_date=date(2024, 12, 1)
    )
    print(f"Midjourney: {result}")
    assert result["match"], "Should match!"

    print("\n=== All tests passed! ===")
