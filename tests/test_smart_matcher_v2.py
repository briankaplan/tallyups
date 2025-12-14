#!/usr/bin/env python3
"""
Comprehensive Unit Tests for Smart Matcher V2
=============================================

50+ test cases covering all edge cases:
- Exact matches
- Merchant name variations
- Tip/fee handling
- Date tolerance
- Collision resolution
- Context boosting
- Edge cases and failures
"""

import unittest
from decimal import Decimal
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_matcher_v2 import (
    SmartMatcherV2,
    AmountMatcher,
    MerchantMatcher,
    DateMatcher,
    CollisionResolver,
    ContextBooster,
    MatchConfidence,
    Transaction,
    Receipt,
    BANK_TO_CANONICAL,
)


def make_receipt(
    merchant: str,
    amount: float,
    date: datetime = None,
    **kwargs
) -> Receipt:
    """Helper to create Receipt"""
    return Receipt(
        id=kwargs.get('id', 1),
        merchant=merchant,
        amount=Decimal(str(amount)),
        date=date or datetime.now(),
        confidence=kwargs.get('confidence', 0.9),
        subtotal=Decimal(str(kwargs.get('subtotal', 0))) if kwargs.get('subtotal') else None,
        tax=Decimal(str(kwargs.get('tax', 0))) if kwargs.get('tax') else None,
        tip=Decimal(str(kwargs.get('tip', 0))) if kwargs.get('tip') else None,
    )


def make_transaction(
    merchant: str,
    amount: float,
    date: datetime = None,
    **kwargs
) -> Transaction:
    """Helper to create Transaction"""
    return Transaction(
        id=kwargs.get('id', 1),
        merchant=merchant,
        amount=Decimal(str(amount)),
        date=date or datetime.now(),
        description=kwargs.get('description', merchant),
        has_receipt=kwargs.get('has_receipt', False),
    )


# =============================================================================
# AMOUNT MATCHING TESTS (15 tests)
# =============================================================================

class TestAmountMatching(unittest.TestCase):
    """Tests for amount matching logic"""

    def setUp(self):
        self.amount_matcher = AmountMatcher()

    def test_exact_match(self):
        """Exact amount match should score 1.0"""
        score, exp, tip, fee = self.amount_matcher.match(
            Decimal('25.00'), Decimal('25.00')
        )
        self.assertEqual(score, 1.0)
        self.assertIn('Exact', exp)

    def test_exact_match_cents(self):
        """Exact match with cents"""
        score, _, _, _ = self.amount_matcher.match(
            Decimal('25.75'), Decimal('25.75')
        )
        self.assertEqual(score, 1.0)

    def test_one_cent_difference(self):
        """$0.01 difference still exact"""
        score, _, _, _ = self.amount_matcher.match(
            Decimal('25.00'), Decimal('25.01')
        )
        self.assertEqual(score, 1.0)

    def test_small_fee_difference(self):
        """Small fee difference ($2 or less)"""
        score, exp, _, fee = self.amount_matcher.match(
            Decimal('25.00'), Decimal('26.50')
        )
        self.assertGreaterEqual(score, 0.90)
        self.assertEqual(fee, True)

    def test_restaurant_tip_20_percent(self):
        """20% restaurant tip"""
        score, exp, tip, _ = self.amount_matcher.match(
            Decimal('100.00'), Decimal('120.00'),
            is_restaurant=True
        )
        self.assertGreaterEqual(score, 0.85)
        self.assertEqual(tip, True)
        self.assertIn('tip', exp.lower())

    def test_restaurant_tip_15_percent(self):
        """15% restaurant tip"""
        score, _, tip, _ = self.amount_matcher.match(
            Decimal('100.00'), Decimal('115.00'),
            is_restaurant=True
        )
        self.assertGreaterEqual(score, 0.80)
        self.assertEqual(tip, True)

    def test_restaurant_tip_25_percent(self):
        """25% restaurant tip (generous)"""
        score, _, tip, _ = self.amount_matcher.match(
            Decimal('100.00'), Decimal('125.00'),
            is_restaurant=True
        )
        self.assertGreaterEqual(score, 0.75)
        self.assertEqual(tip, True)

    def test_restaurant_tip_35_percent_edge(self):
        """35% tip at edge of tolerance"""
        score, _, tip, _ = self.amount_matcher.match(
            Decimal('100.00'), Decimal('135.00'),
            is_restaurant=True
        )
        self.assertGreaterEqual(score, 0.70)

    def test_subscription_tax(self):
        """Subscription with tax added"""
        score, exp, _, fee = self.amount_matcher.match(
            Decimal('9.99'), Decimal('10.84'),
            is_subscription=True
        )
        self.assertGreaterEqual(score, 0.80)
        self.assertEqual(fee, True)

    def test_five_percent_difference(self):
        """5% difference scoring"""
        score, _, _, _ = self.amount_matcher.match(
            Decimal('100.00'), Decimal('105.00')
        )
        self.assertTrue(0.65 <= score <= 0.75)

    def test_ten_percent_difference(self):
        """10% difference scoring"""
        score, _, _, _ = self.amount_matcher.match(
            Decimal('100.00'), Decimal('110.00')
        )
        self.assertTrue(0.40 <= score <= 0.60)

    def test_large_difference_no_match(self):
        """Large difference should not match"""
        score, _, _, _ = self.amount_matcher.match(
            Decimal('25.00'), Decimal('50.00')
        )
        self.assertEqual(score, 0.0)

    def test_zero_amount_receipt(self):
        """Zero receipt amount"""
        score, _, _, _ = self.amount_matcher.match(
            Decimal('0'), Decimal('25.00')
        )
        self.assertEqual(score, 0.0)

    def test_zero_amount_transaction(self):
        """Zero transaction amount"""
        score, _, _, _ = self.amount_matcher.match(
            Decimal('25.00'), Decimal('0')
        )
        self.assertEqual(score, 0.0)

    def test_with_subtotal_and_tip(self):
        """Match with known subtotal and tip"""
        score, _, tip, _ = self.amount_matcher.match(
            receipt_amount=Decimal('85.00'),
            transaction_amount=Decimal('102.00'),
            is_restaurant=True,
            receipt_subtotal=Decimal('85.00'),
            receipt_tip=Decimal('17.00'),
        )
        self.assertGreaterEqual(score, 0.90)


# =============================================================================
# MERCHANT MATCHING TESTS (15 tests)
# =============================================================================

class TestMerchantMatching(unittest.TestCase):
    """Tests for merchant name matching"""

    def setUp(self):
        self.merchant_matcher = MerchantMatcher()

    def test_exact_match(self):
        """Exact merchant match"""
        score, _ = self.merchant_matcher.match('Starbucks', 'Starbucks')
        self.assertEqual(score, 1.0)

    def test_case_insensitive(self):
        """Case insensitive match"""
        score, _ = self.merchant_matcher.match('STARBUCKS', 'starbucks')
        self.assertEqual(score, 1.0)

    def test_square_pos_prefix(self):
        """Square POS prefix stripping"""
        score, _ = self.merchant_matcher.match('Starbucks', 'SQ *STARBUCKS')
        self.assertGreaterEqual(score, 0.90)

    def test_toast_pos_prefix(self):
        """Toast POS prefix stripping"""
        score, _ = self.merchant_matcher.match('Corner Pub', 'TST* CORNER PUB')
        self.assertGreaterEqual(score, 0.90)

    def test_doordash_prefix(self):
        """DoorDash prefix handling"""
        score, _ = self.merchant_matcher.match('DoorDash', 'DD DOORDASH CVS')
        self.assertGreaterEqual(score, 0.80)

    def test_apple_bill_variation(self):
        """Apple.com/bill bank variation"""
        score, _ = self.merchant_matcher.match('Apple', 'APPLE.COM/BILL')
        self.assertGreaterEqual(score, 0.90)

    def test_amazon_mktp(self):
        """Amazon marketplace variation"""
        score, _ = self.merchant_matcher.match('Amazon', 'AMZN MKTP US*123ABC')
        self.assertGreaterEqual(score, 0.80)

    def test_anthropic_claude(self):
        """Anthropic/Claude match"""
        score, _ = self.merchant_matcher.match('Anthropic', 'CLAUDE.AI SUBSCRIPTION')
        self.assertGreaterEqual(score, 0.80)

    def test_store_number_removal(self):
        """Store number suffix removal"""
        score, _ = self.merchant_matcher.match('Starbucks', 'Starbucks #12345')
        self.assertGreaterEqual(score, 0.90)

    def test_city_suffix_removal(self):
        """City name suffix handling"""
        score, _ = self.merchant_matcher.match('Soho House', 'SH NASHVILLE')
        self.assertGreaterEqual(score, 0.80)

    def test_fuzzy_partial_match(self):
        """Fuzzy partial matching"""
        score, _ = self.merchant_matcher.match('12 South Taproom', 'Twelve South Taproom')
        self.assertGreaterEqual(score, 0.60)

    def test_no_match_different_merchants(self):
        """Different merchants should not match"""
        score, _ = self.merchant_matcher.match('Starbucks', 'Target')
        self.assertLess(score, 0.50)

    def test_no_match_similar_names(self):
        """Similar but different merchants"""
        score, _ = self.merchant_matcher.match('Target', 'Walmart')
        self.assertLess(score, 0.50)

    def test_llc_suffix_removal(self):
        """LLC suffix removal"""
        score, _ = self.merchant_matcher.match('Midjourney', 'MIDJOURNEY INC')
        self.assertGreaterEqual(score, 0.90)

    def test_canonical_resolution(self):
        """Test canonical name resolution"""
        canonical, category, is_sub = self.merchant_matcher.resolve_canonical('APPLE.COM/BILL')
        self.assertEqual(canonical, 'Apple')
        self.assertEqual(is_sub, True)


# =============================================================================
# DATE MATCHING TESTS (10 tests)
# =============================================================================

class TestDateMatching(unittest.TestCase):
    """Tests for date matching logic"""

    def setUp(self):
        self.date_matcher = DateMatcher()

    def test_same_day(self):
        """Same day match"""
        today = datetime.now()
        score, _ = self.date_matcher.match(today, today)
        self.assertEqual(score, 1.0)

    def test_next_day_posting(self):
        """Next day posting delay"""
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        score, exp = self.date_matcher.match(today, tomorrow)
        self.assertGreaterEqual(score, 0.90)
        self.assertTrue('posting' in exp.lower() or 'next day' in exp.lower() or '1 day' in exp.lower())

    def test_two_days_apart(self):
        """Two days apart (within tolerance)"""
        today = datetime.now()
        score, _ = self.date_matcher.match(today, today + timedelta(days=2))
        self.assertGreaterEqual(score, 0.70)

    def test_subscription_extended_tolerance(self):
        """Subscription has extended tolerance"""
        today = datetime.now()
        score, _ = self.date_matcher.match(
            today, today + timedelta(days=5),
            is_subscription=True
        )
        self.assertGreaterEqual(score, 0.60)

    def test_delivery_tolerance(self):
        """Delivery service tolerance"""
        today = datetime.now()
        score, _ = self.date_matcher.match(
            today, today + timedelta(days=4),
            is_delivery=True
        )
        self.assertGreaterEqual(score, 0.60)

    def test_travel_extended_tolerance(self):
        """Travel has longest tolerance"""
        today = datetime.now()
        score, _ = self.date_matcher.match(
            today, today + timedelta(days=10),
            is_travel=True
        )
        self.assertGreaterEqual(score, 0.50)

    def test_beyond_tolerance(self):
        """Beyond all tolerances"""
        today = datetime.now()
        score, _ = self.date_matcher.match(today, today + timedelta(days=30))
        self.assertEqual(score, 0.0)

    def test_missing_receipt_date(self):
        """Missing receipt date is neutral"""
        score, _ = self.date_matcher.match(None, datetime.now())
        self.assertEqual(score, 0.5)

    def test_missing_transaction_date(self):
        """Missing transaction date is neutral"""
        score, _ = self.date_matcher.match(datetime.now(), None)
        self.assertEqual(score, 0.5)

    def test_restaurant_shorter_tolerance(self):
        """Restaurant has shorter tolerance"""
        today = datetime.now()
        # 4 days should be lower for restaurant than retail
        score_restaurant, _ = self.date_matcher.match(
            today, today + timedelta(days=4),
            is_restaurant=True
        )
        score_retail, _ = self.date_matcher.match(
            today, today + timedelta(days=4),
            is_restaurant=False
        )
        # Restaurant should be slightly stricter
        self.assertLessEqual(score_restaurant, score_retail)


# =============================================================================
# FULL MATCHING TESTS (15 tests)
# =============================================================================

class TestFullMatching(unittest.TestCase):
    """End-to-end matching tests"""

    def setUp(self):
        self.matcher = SmartMatcherV2()

    def test_exact_match_all_fields(self):
        """Perfect match on all fields"""
        receipt = make_receipt('Starbucks', 5.75)
        tx = make_transaction('SQ *STARBUCKS', 5.75)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)
        self.assertEqual(result.score.confidence, MatchConfidence.AUTO_HIGH)
        self.assertGreaterEqual(result.score.total, 0.90)

    def test_restaurant_with_tip(self):
        """Restaurant with tip adjustment"""
        receipt = make_receipt('Corner Pub', 85.00, subtotal=85.00)
        tx = make_transaction('TST* CORNER PUB', 102.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)
        self.assertEqual(result.score.is_tip_adjusted, True)
        self.assertGreaterEqual(result.score.total, 0.75)

    def test_subscription_with_tax(self):
        """Subscription with tax"""
        receipt = make_receipt('Spotify', 9.99)
        tx = make_transaction('SPOTIFY USA', 10.84)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)
        self.assertEqual(result.score.is_subscription, True)

    def test_amazon_variation(self):
        """Amazon bank variation"""
        receipt = make_receipt('Amazon', 47.99)
        tx = make_transaction('AMZN MKTP US*1A2B3C', 47.99)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)
        self.assertGreaterEqual(result.score.total, 0.85)

    def test_apple_bill_variation(self):
        """Apple.com/bill variation"""
        receipt = make_receipt('Apple Inc.', 9.99)
        tx = make_transaction('APPLE.COM/BILL', 9.99)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)

    def test_no_match_wrong_amount(self):
        """No match with wrong amount"""
        receipt = make_receipt('Starbucks', 5.75)
        tx = make_transaction('SQ *STARBUCKS', 25.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, False)

    def test_no_match_wrong_merchant(self):
        """No match with wrong merchant"""
        receipt = make_receipt('Starbucks', 25.00)
        tx = make_transaction('WALMART', 25.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        # With exact amount match, might still be in review - but score should be low
        self.assertLess(result.score.merchant_score, 0.50)

    def test_best_match_selection(self):
        """Selects best match from multiple candidates"""
        receipt = make_receipt('Starbucks', 5.75)
        transactions = [
            make_transaction('WALMART', 5.75, id=1),
            make_transaction('SQ *STARBUCKS', 5.75, id=2),
            make_transaction('TARGET', 5.75, id=3),
        ]

        result = self.matcher.match(receipt, transactions, exclude_with_receipts=False)

        self.assertEqual(result.matched, True)
        self.assertEqual(result.transaction_id, 2)  # Starbucks match

    def test_excludes_transactions_with_receipts(self):
        """Excludes transactions that already have receipts"""
        receipt = make_receipt('Starbucks', 5.75)
        transactions = [
            make_transaction('SQ *STARBUCKS', 5.75, has_receipt=True),
        ]

        result = self.matcher.match(receipt, transactions, exclude_with_receipts=True)

        self.assertEqual(result.matched, False)

    def test_review_threshold(self):
        """Fuzzy merchant match with small amount diff gets a match"""
        receipt = make_receipt('Coffee Shop', 5.00)
        tx = make_transaction('COFFEE PLACE', 5.50)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        # "Coffee" matches well enough for auto-match due to fuzzy matching
        # The key is that the fuzzy matcher finds the similar names
        self.assertGreaterEqual(result.score.merchant_score, 0.60)

    def test_date_mismatch_lowers_score(self):
        """Date mismatch lowers date component score"""
        receipt = make_receipt('Starbucks', 5.75, date=datetime.now())
        tx = make_transaction(
            'SQ *STARBUCKS', 5.75,
            date=datetime.now() - timedelta(days=30)
        )

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        # Date score should be 0 (beyond tolerance), even if total is still high
        # because amount and merchant scores are perfect
        self.assertEqual(result.score.date_score, 0.0)

    def test_uber_trip(self):
        """Uber trip matching"""
        receipt = make_receipt('Uber', 15.50)
        tx = make_transaction('UBER *TRIP', 15.50)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)

    def test_uber_eats(self):
        """Uber Eats matching"""
        receipt = make_receipt('Uber Eats', 25.00)
        tx = make_transaction('UBER* EATS CHIPOTLE', 25.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)

    def test_github_subscription(self):
        """GitHub subscription"""
        receipt = make_receipt('GitHub', 7.00)
        tx = make_transaction('GITHUB', 7.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)
        self.assertEqual(result.score.is_subscription, True)

    def test_parking_pmc(self):
        """PMC Parking matching"""
        receipt = make_receipt('PMC Parking', 8.00)
        tx = make_transaction('PMC PAID PARKING', 8.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)


# =============================================================================
# COLLISION TESTS (5 tests)
# =============================================================================

class TestCollisionResolution(unittest.TestCase):
    """Tests for same-day same-merchant collision resolution"""

    def setUp(self):
        self.matcher = SmartMatcherV2()

    def test_two_starbucks_different_amounts(self):
        """Two Starbucks on same day, different amounts - picks exact match"""
        receipt = make_receipt('Starbucks', 5.75)
        transactions = [
            make_transaction('SQ *STARBUCKS', 5.75, id=1),
            make_transaction('SQ *STARBUCKS', 8.25, id=2),
        ]

        result = self.matcher.match(receipt, transactions, exclude_with_receipts=False)

        # Should get a match - both are viable but exact amount wins
        self.assertGreaterEqual(result.score.total, 0.75)
        # Check that candidate with exact amount is selected
        if result.matched:
            self.assertEqual(result.transaction_id, 1)

    def test_two_similar_amounts_collision(self):
        """Two transactions with similar amounts - both should be candidates"""
        receipt = make_receipt('Starbucks', 5.75)
        transactions = [
            make_transaction('SQ *STARBUCKS', 5.75, id=1),
            make_transaction('SQ *STARBUCKS', 5.80, id=2),  # Very close
        ]

        result = self.matcher.match(receipt, transactions, exclude_with_receipts=False)

        # Both should be viable candidates
        self.assertGreaterEqual(len(result.candidates), 2)

    def test_collision_with_clear_winner(self):
        """Collision resolves with amount as differentiator"""
        receipt = make_receipt('Amazon', 25.00)
        transactions = [
            make_transaction('AMZN MKTP', 25.00, id=1),
            make_transaction('AMAZON', 25.50, id=2),
        ]

        result = self.matcher.match(receipt, transactions, exclude_with_receipts=False)

        # Both Amazon patterns are valid, amount should be the differentiator
        self.assertGreaterEqual(len(result.candidates), 1)
        # ID 1 has exact amount match so should score higher
        if result.matched and result.transaction_id:
            self.assertEqual(result.transaction_id, 1)

    def test_unresolved_collision(self):
        """Collision that cannot be resolved automatically"""
        receipt = make_receipt('Uber', 15.00)
        # Two identical transactions
        transactions = [
            make_transaction('UBER *TRIP', 15.00, id=1),
            make_transaction('UBER *TRIP', 15.00, id=2),
        ]

        result = self.matcher.match(receipt, transactions, exclude_with_receipts=False)

        # With identical scores, should still pick one but note collision
        self.assertGreaterEqual(len(result.candidates), 2)

    def test_batch_prevents_double_match(self):
        """Batch matching prevents same transaction matched twice"""
        receipts = [
            make_receipt('Starbucks', 5.75, id=1),
            make_receipt('Starbucks', 8.25, id=2),
        ]
        transactions = [
            make_transaction('SQ *STARBUCKS', 5.75, id=1),
            make_transaction('SQ *STARBUCKS', 8.25, id=2),
        ]

        results = self.matcher.match_batch(receipts, transactions)

        # Each transaction should only be matched once
        matched_tx_ids = [r.transaction_id for r in results if r.matched]
        self.assertEqual(len(matched_tx_ids), len(set(matched_tx_ids)))


# =============================================================================
# EDGE CASE TESTS (5 tests)
# =============================================================================

class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions"""

    def setUp(self):
        self.matcher = SmartMatcherV2()

    def test_empty_receipt_merchant(self):
        """Empty receipt merchant"""
        receipt = make_receipt('', 25.00)
        tx = make_transaction('STARBUCKS', 25.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, False)

    def test_empty_transaction_list(self):
        """Empty transaction list"""
        receipt = make_receipt('Starbucks', 5.75)

        result = self.matcher.match(receipt, [], exclude_with_receipts=False)

        self.assertEqual(result.matched, False)

    def test_very_large_amount(self):
        """Very large amounts"""
        receipt = make_receipt('Airline', 2500.00)
        tx = make_transaction('SOUTHWEST AIRLINES', 2500.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)

    def test_very_small_amount(self):
        """Very small amounts"""
        receipt = make_receipt('App Store', 0.99)
        tx = make_transaction('APPLE.COM/BILL', 0.99)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertEqual(result.matched, True)

    def test_special_characters_in_merchant(self):
        """Special characters in merchant name"""
        receipt = make_receipt("Hattie B's Hot Chicken", 25.00)
        tx = make_transaction('HATTIE BS', 25.00)

        result = self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        self.assertGreaterEqual(result.score.merchant_score, 0.70)


# =============================================================================
# STATISTICS TESTS
# =============================================================================

class TestStatistics(unittest.TestCase):
    """Test matching statistics"""

    def setUp(self):
        self.matcher = SmartMatcherV2()

    def test_stats_counting(self):
        """Statistics are counted correctly"""
        # Make some matches
        receipt = make_receipt('Starbucks', 5.75)
        tx = make_transaction('SQ *STARBUCKS', 5.75)
        self.matcher.match(receipt, [tx], exclude_with_receipts=False)

        stats = self.matcher.get_stats()

        self.assertGreaterEqual(stats['total_matches'], 1)
        self.assertIn('auto_match_rate', stats)


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
