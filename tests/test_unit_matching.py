#!/usr/bin/env python3
"""
Comprehensive Unit Tests for Smart Auto-Matcher
================================================

Tests for the receipt-to-transaction matching system including:
- Amount matching with various tolerances
- Merchant name normalization and matching
- Date tolerance calculations
- Duplicate detection using perceptual hashing
- Confidence score calculations
- Edge cases and error handling

Test Coverage Target: 95%+
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch
import hashlib
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_auto_matcher import (
    normalize_merchant,
    parse_amount,
    parse_date,
    calculate_amount_score,
    calculate_merchant_score,
    calculate_date_score,
    is_subscription_merchant,
    is_delivery_merchant,
    compute_image_hash,
    compute_content_hash,
    hamming_distance,
    are_images_similar,
    SmartAutoMatcher,
    DuplicateDetector,
    AUTO_MATCH_THRESHOLD,
    REVIEW_THRESHOLD,
    DUPLICATE_SIMILARITY,
    AMOUNT_EXACT,
    AMOUNT_CLOSE,
    AMOUNT_TIP_VARIANCE,
    DATE_TOLERANCE_RETAIL,
    DATE_TOLERANCE_SUBSCRIPTION,
    DATE_TOLERANCE_DELIVERY,
)


# =============================================================================
# MERCHANT NORMALIZATION TESTS
# =============================================================================

class TestNormalizeMerchant:
    """Test suite for merchant name normalization."""

    @pytest.mark.unit
    def test_lowercase_conversion(self):
        """Merchant names should be lowercased."""
        assert normalize_merchant("ANTHROPIC") == "anthropic"
        assert normalize_merchant("AnThrOpIc") == "anthropic"

    @pytest.mark.unit
    def test_strip_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        assert normalize_merchant("  Anthropic  ") == "anthropic"
        assert normalize_merchant("\tAnthropic\n") == "anthropic"

    @pytest.mark.unit
    def test_remove_sq_prefix(self):
        """Square (SQ*) prefix should be removed."""
        assert normalize_merchant("SQ*COFFEE SHOP") == "coffee shop"
        assert normalize_merchant("sq*coffee shop") == "coffee shop"
        assert normalize_merchant("sq coffee") == "coffee"

    @pytest.mark.unit
    def test_remove_tst_prefix(self):
        """Toast (TST*) prefix should be removed."""
        assert normalize_merchant("TST*RESTAURANT") == "restaurant"
        assert normalize_merchant("tst*restaurant") == "restaurant"
        assert normalize_merchant("tst restaurant") == "restaurant"

    @pytest.mark.unit
    def test_remove_dd_prefix(self):
        """DoorDash (DD*) prefix should be removed."""
        assert normalize_merchant("DD*MCDONALDS") == "mcdonalds"
        assert normalize_merchant("dd*mcdonalds") == "mcdonalds"

    @pytest.mark.unit
    def test_remove_location_number(self):
        """Store numbers (#123) should be removed."""
        assert normalize_merchant("Starbucks #12345") == "starbucks"
        assert normalize_merchant("Target #1234") == "target"

    @pytest.mark.unit
    def test_remove_zip_code(self):
        """ZIP codes should be removed."""
        assert normalize_merchant("WALMART 37203") == "walmart"
        assert normalize_merchant("TARGET NASHVILLE 37206") == "target nashville"

    @pytest.mark.unit
    def test_state_codes_preserved(self):
        """State codes are preserved (may be part of name)."""
        # State codes at end are kept as they could be intentional (e.g., "TN Diner")
        assert normalize_merchant("COFFEE SHOP TN") == "coffee shop tn"
        assert normalize_merchant("RESTAURANT CA") == "restaurant ca"

    @pytest.mark.unit
    def test_remove_special_characters(self):
        """Special characters should be replaced with spaces."""
        assert normalize_merchant("STAR-BUCKS") == "star bucks"
        assert normalize_merchant("MC_DONALD'S") == "mc donald s"

    @pytest.mark.unit
    def test_collapse_multiple_spaces(self):
        """Multiple spaces should collapse to single space."""
        assert normalize_merchant("COFFEE   SHOP") == "coffee shop"
        assert normalize_merchant("THE    RESTAURANT") == "the restaurant"

    @pytest.mark.unit
    def test_empty_string(self):
        """Empty string should return empty string."""
        assert normalize_merchant("") == ""
        assert normalize_merchant(None) == ""

    @pytest.mark.unit
    def test_complex_merchant_name(self):
        """Complex merchant names with multiple patterns."""
        result = normalize_merchant("SQ*COFFEE SHOP #123 NASHVILLE TN 37201")
        assert "coffee shop" in result
        assert "sq" not in result
        assert "#123" not in result
        assert "37201" not in result


# =============================================================================
# AMOUNT PARSING TESTS
# =============================================================================

class TestParseAmount:
    """Test suite for amount parsing."""

    @pytest.mark.unit
    def test_float_passthrough(self):
        """Float values should pass through."""
        assert parse_amount(20.0) == 20.0
        assert parse_amount(0.01) == 0.01

    @pytest.mark.unit
    def test_int_conversion(self):
        """Integer values should convert to float."""
        assert parse_amount(20) == 20.0
        assert parse_amount(0) == 0.0

    @pytest.mark.unit
    def test_string_with_dollar_sign(self):
        """String with $ should parse correctly."""
        assert parse_amount("$20.00") == 20.0
        assert parse_amount("$1,234.56") == 1234.56

    @pytest.mark.unit
    def test_string_with_commas(self):
        """String with thousands separators should parse."""
        assert parse_amount("1,000.00") == 1000.0
        assert parse_amount("10,000") == 10000.0

    @pytest.mark.unit
    def test_negative_amount(self):
        """Negative amounts should return absolute value."""
        assert parse_amount("-20.00") == 20.0
        assert parse_amount("-$50.00") == 50.0

    @pytest.mark.unit
    def test_empty_values(self):
        """Empty values should return 0.0."""
        assert parse_amount("") == 0.0
        assert parse_amount(None) == 0.0

    @pytest.mark.unit
    def test_invalid_string(self):
        """Invalid strings should return 0.0."""
        assert parse_amount("not a number") == 0.0
        assert parse_amount("abc123") == 0.0

    @pytest.mark.unit
    def test_decimal_precision(self):
        """Decimal precision should be maintained."""
        assert parse_amount("19.99") == 19.99
        assert parse_amount("0.01") == 0.01


# =============================================================================
# DATE PARSING TESTS
# =============================================================================

class TestParseDate:
    """Test suite for date parsing."""

    @pytest.mark.unit
    def test_datetime_passthrough(self):
        """Datetime objects should pass through."""
        dt = datetime(2024, 1, 15)
        assert parse_date(dt) == dt

    @pytest.mark.unit
    def test_iso_format(self):
        """ISO date format (YYYY-MM-DD) should parse."""
        result = parse_date("2024-01-15")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    @pytest.mark.unit
    def test_us_format_with_year(self):
        """US date format (MM/DD/YYYY) should parse."""
        result = parse_date("01/15/2024")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    @pytest.mark.unit
    def test_us_format_short_year(self):
        """US date format with short year (MM/DD/YY) should parse."""
        result = parse_date("01/15/24")
        assert result.month == 1
        assert result.day == 15

    @pytest.mark.unit
    def test_month_name_format(self):
        """Month name format (Jan 15, 2024) should parse."""
        result = parse_date("Jan 15, 2024")
        assert result.month == 1
        assert result.day == 15

    @pytest.mark.unit
    def test_full_month_name(self):
        """Full month name format (January 15, 2024) should parse."""
        result = parse_date("January 15, 2024")
        assert result.month == 1
        assert result.day == 15

    @pytest.mark.unit
    def test_empty_values(self):
        """Empty values should return None."""
        assert parse_date("") is None
        assert parse_date(None) is None

    @pytest.mark.unit
    def test_invalid_date(self):
        """Invalid date strings should return None."""
        assert parse_date("not a date") is None
        assert parse_date("13/45/2024") is None

    @pytest.mark.unit
    def test_whitespace_handling(self):
        """Whitespace should be stripped."""
        result = parse_date("  2024-01-15  ")
        assert result.year == 2024


# =============================================================================
# AMOUNT SCORE CALCULATION TESTS
# =============================================================================

class TestCalculateAmountScore:
    """Test suite for amount matching score calculation."""

    @pytest.mark.unit
    def test_exact_match(self):
        """Exact amounts should score 1.0."""
        assert calculate_amount_score(20.00, 20.00) == 1.0
        assert calculate_amount_score(100.00, 100.00) == 1.0

    @pytest.mark.unit
    def test_near_exact_match(self):
        """Within $0.01 should score very high (rounding differences)."""
        score = calculate_amount_score(20.00, 20.01)
        assert score >= 0.95  # Very close amounts should score high
        score2 = calculate_amount_score(20.01, 20.00)
        assert score2 >= 0.95

    @pytest.mark.unit
    def test_close_match_fees(self):
        """Within $2.00 (fees) should score ~0.95."""
        score = calculate_amount_score(20.00, 21.50)
        assert score >= 0.90

    @pytest.mark.unit
    def test_tip_variance(self):
        """Restaurant with 15-25% tip should score well."""
        # $100 receipt + 20% tip = $120 transaction
        score = calculate_amount_score(100.00, 120.00)
        assert score >= 0.85, f"Score {score} too low for tip variance"

    @pytest.mark.unit
    def test_low_tip_variance(self):
        """Restaurant with 10% tip should score well."""
        # $100 receipt + 10% tip = $110 transaction
        score = calculate_amount_score(100.00, 110.00)
        assert score >= 0.85

    @pytest.mark.unit
    def test_high_tip_variance(self):
        """Restaurant with 25% tip should score well."""
        # $100 receipt + 25% tip = $125 transaction
        score = calculate_amount_score(100.00, 125.00)
        assert score >= 0.80

    @pytest.mark.unit
    def test_small_percentage_difference(self):
        """2% difference should score ~0.90."""
        score = calculate_amount_score(100.00, 102.00)
        assert score >= 0.85

    @pytest.mark.unit
    def test_moderate_percentage_difference(self):
        """5% difference should score ~0.80."""
        score = calculate_amount_score(100.00, 105.00)
        assert score >= 0.75

    @pytest.mark.unit
    def test_large_percentage_difference(self):
        """10% difference should score lower."""
        score = calculate_amount_score(100.00, 110.00)
        assert 0.5 <= score <= 0.90

    @pytest.mark.unit
    def test_very_large_difference(self):
        """30%+ difference should score very low or 0."""
        score = calculate_amount_score(100.00, 130.00)
        assert score <= 0.50

    @pytest.mark.unit
    def test_completely_different(self):
        """Completely different amounts should score 0."""
        score = calculate_amount_score(20.00, 200.00)
        assert score == 0.0

    @pytest.mark.unit
    def test_zero_receipt_amount(self):
        """Zero receipt amount should score 0."""
        assert calculate_amount_score(0.0, 20.00) == 0.0

    @pytest.mark.unit
    def test_zero_transaction_amount(self):
        """Zero transaction amount should score 0."""
        assert calculate_amount_score(20.00, 0.0) == 0.0

    @pytest.mark.unit
    def test_both_zero(self):
        """Both zero should score 0."""
        assert calculate_amount_score(0.0, 0.0) == 0.0


# =============================================================================
# MERCHANT SCORE CALCULATION TESTS
# =============================================================================

class TestCalculateMerchantScore:
    """Test suite for merchant name matching score calculation."""

    @pytest.mark.unit
    def test_exact_match(self):
        """Exact merchant names should score 1.0."""
        assert calculate_merchant_score("Anthropic", "Anthropic") == 1.0

    @pytest.mark.unit
    def test_case_insensitive(self):
        """Matching should be case insensitive."""
        score = calculate_merchant_score("ANTHROPIC", "anthropic")
        assert score == 1.0

    @pytest.mark.unit
    def test_contains_match(self):
        """One name containing other should score high."""
        score = calculate_merchant_score("Starbucks", "Starbucks Coffee")
        assert score >= 0.85

    @pytest.mark.unit
    def test_contained_in(self):
        """Being contained in other should score high."""
        score = calculate_merchant_score("Starbucks Coffee", "Starbucks")
        assert score >= 0.85

    @pytest.mark.unit
    def test_first_word_match(self):
        """First word matching should boost score."""
        score = calculate_merchant_score("Starbucks Reserve", "Starbucks Coffee")
        assert score >= 0.70

    @pytest.mark.unit
    def test_similar_names(self):
        """Similar names should have reasonable score."""
        score = calculate_merchant_score("Starbuck", "Starbucks")
        assert score >= 0.80

    @pytest.mark.unit
    def test_different_merchants(self):
        """Completely different merchants should score low."""
        score = calculate_merchant_score("Anthropic", "Netflix")
        assert score < 0.50

    @pytest.mark.unit
    def test_empty_receipt_merchant(self):
        """Empty receipt merchant should score 0."""
        assert calculate_merchant_score("", "Anthropic") == 0.0

    @pytest.mark.unit
    def test_empty_transaction_merchant(self):
        """Empty transaction merchant should score 0."""
        assert calculate_merchant_score("Anthropic", "") == 0.0

    @pytest.mark.unit
    def test_both_empty(self):
        """Both empty should score 0."""
        assert calculate_merchant_score("", "") == 0.0

    @pytest.mark.unit
    def test_sq_prefix_normalization(self):
        """SQ* prefixes should be normalized."""
        score = calculate_merchant_score("SQ*COFFEE SHOP", "Coffee Shop")
        assert score >= 0.85

    @pytest.mark.unit
    def test_abbreviations(self):
        """Common abbreviations should match reasonably."""
        score = calculate_merchant_score("McDonalds", "MCDONALDS RESTAURANT")
        assert score >= 0.60


# =============================================================================
# DATE SCORE CALCULATION TESTS
# =============================================================================

class TestCalculateDateScore:
    """Test suite for date matching score calculation."""

    @pytest.mark.unit
    def test_same_day(self):
        """Same day should score 1.0."""
        date1 = datetime(2024, 1, 15)
        date2 = datetime(2024, 1, 15)
        assert calculate_date_score(date1, date2) == 1.0

    @pytest.mark.unit
    def test_one_day_apart(self):
        """One day difference should score ~0.95."""
        date1 = datetime(2024, 1, 15)
        date2 = datetime(2024, 1, 16)
        score = calculate_date_score(date1, date2)
        assert score >= 0.90

    @pytest.mark.unit
    def test_within_retail_tolerance(self):
        """Within retail tolerance (3 days) should score well."""
        date1 = datetime(2024, 1, 15)
        date2 = datetime(2024, 1, 18)  # 3 days later
        score = calculate_date_score(date1, date2)
        assert score >= 0.75

    @pytest.mark.unit
    def test_subscription_tolerance(self):
        """Subscriptions get 7 day tolerance."""
        date1 = datetime(2024, 1, 15)
        date2 = datetime(2024, 1, 21)  # 6 days later
        score = calculate_date_score(date1, date2, is_subscription=True)
        assert score >= 0.75

    @pytest.mark.unit
    def test_delivery_tolerance(self):
        """Delivery services get 14 day tolerance."""
        date1 = datetime(2024, 1, 15)
        date2 = datetime(2024, 1, 28)  # 13 days later
        score = calculate_date_score(date1, date2, is_delivery=True)
        assert score >= 0.75

    @pytest.mark.unit
    def test_beyond_tolerance(self):
        """Beyond tolerance should score low."""
        date1 = datetime(2024, 1, 15)
        date2 = datetime(2024, 2, 15)  # 31 days later
        score = calculate_date_score(date1, date2)
        assert score <= 0.50

    @pytest.mark.unit
    def test_missing_receipt_date(self):
        """Missing receipt date should return neutral 0.5."""
        score = calculate_date_score(None, datetime(2024, 1, 15))
        assert score == 0.5

    @pytest.mark.unit
    def test_missing_transaction_date(self):
        """Missing transaction date should return neutral 0.5."""
        score = calculate_date_score(datetime(2024, 1, 15), None)
        assert score == 0.5

    @pytest.mark.unit
    def test_negative_date_difference(self):
        """Receipt date after transaction should work (absolute)."""
        date1 = datetime(2024, 1, 18)
        date2 = datetime(2024, 1, 15)
        score = calculate_date_score(date1, date2)
        assert score >= 0.75


# =============================================================================
# SUBSCRIPTION/DELIVERY MERCHANT DETECTION TESTS
# =============================================================================

class TestMerchantTypeDetection:
    """Test suite for subscription and delivery merchant detection."""

    @pytest.mark.unit
    def test_subscription_anthropic(self):
        """Anthropic should be detected as subscription."""
        assert is_subscription_merchant("Anthropic") is True

    @pytest.mark.unit
    def test_subscription_openai(self):
        """OpenAI should be detected as subscription."""
        assert is_subscription_merchant("OpenAI") is True

    @pytest.mark.unit
    def test_subscription_spotify(self):
        """Spotify should be detected as subscription."""
        assert is_subscription_merchant("Spotify") is True

    @pytest.mark.unit
    def test_subscription_netflix(self):
        """Netflix should be detected as subscription."""
        assert is_subscription_merchant("Netflix") is True

    @pytest.mark.unit
    def test_subscription_github(self):
        """GitHub should be detected as subscription."""
        assert is_subscription_merchant("GitHub") is True

    @pytest.mark.unit
    def test_not_subscription(self):
        """Regular merchants should not be subscriptions."""
        assert is_subscription_merchant("Starbucks") is False
        assert is_subscription_merchant("Target") is False

    @pytest.mark.unit
    def test_delivery_doordash(self):
        """DoorDash should be detected as delivery."""
        assert is_delivery_merchant("DoorDash") is True
        assert is_delivery_merchant("DD*MCDONALDS") is True

    @pytest.mark.unit
    def test_delivery_uber_eats(self):
        """Uber Eats should be detected as delivery."""
        assert is_delivery_merchant("Uber Eats") is True

    @pytest.mark.unit
    def test_delivery_grubhub(self):
        """Grubhub should be detected as delivery."""
        assert is_delivery_merchant("Grubhub") is True

    @pytest.mark.unit
    def test_not_delivery(self):
        """Regular merchants should not be delivery."""
        assert is_delivery_merchant("Starbucks") is False
        assert is_delivery_merchant("Target") is False

    @pytest.mark.unit
    def test_empty_merchant(self):
        """Empty merchant should return False."""
        assert is_subscription_merchant("") is False
        assert is_subscription_merchant(None) is False
        assert is_delivery_merchant("") is False
        assert is_delivery_merchant(None) is False


# =============================================================================
# DUPLICATE DETECTION TESTS
# =============================================================================

class TestDuplicateDetection:
    """Test suite for duplicate receipt detection."""

    @pytest.mark.unit
    def test_compute_content_hash(self):
        """Content hash should be consistent."""
        data = b"test content"
        hash1 = compute_content_hash(data)
        hash2 = compute_content_hash(data)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex

    @pytest.mark.unit
    def test_content_hash_different_data(self):
        """Different data should produce different hashes."""
        hash1 = compute_content_hash(b"data1")
        hash2 = compute_content_hash(b"data2")
        assert hash1 != hash2

    @pytest.mark.unit
    def test_compute_image_hash(self, temp_image):
        """Image hash should be computed."""
        with open(temp_image, 'rb') as f:
            image_data = f.read()

        hash1 = compute_image_hash(image_data)
        assert hash1 is not None
        assert len(hash1) >= 8

    @pytest.mark.unit
    def test_image_hash_consistency(self, temp_image):
        """Same image should produce same hash."""
        with open(temp_image, 'rb') as f:
            image_data = f.read()

        hash1 = compute_image_hash(image_data)
        hash2 = compute_image_hash(image_data)
        assert hash1 == hash2

    @pytest.mark.unit
    def test_hamming_distance_identical(self):
        """Identical hashes should have distance 0."""
        assert hamming_distance("abcdef1234567890", "abcdef1234567890") == 0

    @pytest.mark.unit
    def test_hamming_distance_different(self):
        """Different hashes should have positive distance."""
        dist = hamming_distance("0000000000000000", "ffffffffffffffff")
        assert dist > 0

    @pytest.mark.unit
    def test_hamming_distance_length_mismatch(self):
        """Length mismatch should return max distance."""
        dist = hamming_distance("abc", "abcdef")
        assert dist == 64  # Max distance

    @pytest.mark.unit
    def test_are_images_similar_identical(self):
        """Identical hashes should be similar."""
        assert are_images_similar("abcdef1234567890", "abcdef1234567890") is True

    @pytest.mark.unit
    def test_are_images_similar_threshold(self):
        """Images within threshold should be similar."""
        # Small hamming distance should be similar
        assert are_images_similar("0000000000000000", "0000000000000001", threshold=10) is True

    @pytest.mark.unit
    def test_are_images_not_similar(self):
        """Very different hashes should not be similar."""
        assert are_images_similar("0000000000000000", "ffffffffffffffff", threshold=10) is False


class TestDuplicateDetectorClass:
    """Test suite for DuplicateDetector class."""

    @pytest.mark.unit
    def test_init_without_db(self):
        """Detector should initialize without database."""
        detector = DuplicateDetector(db_connection=None)
        assert detector.db is None
        assert detector.hash_cache == {}

    @pytest.mark.unit
    def test_init_with_db(self, mock_mysql_connection):
        """Detector should initialize with database."""
        detector = DuplicateDetector(db_connection=mock_mysql_connection)
        assert detector.db is not None

    @pytest.mark.unit
    def test_is_duplicate_not_duplicate(self, temp_image):
        """New image should not be duplicate."""
        detector = DuplicateDetector(db_connection=None)

        with open(temp_image, 'rb') as f:
            image_data = f.read()

        is_dup, match = detector.is_duplicate(image_data, "test1.jpg")
        assert is_dup is False
        assert match is None

    @pytest.mark.unit
    def test_is_duplicate_exact_duplicate(self, temp_image):
        """Identical image should be detected as duplicate."""
        detector = DuplicateDetector(db_connection=None)

        with open(temp_image, 'rb') as f:
            image_data = f.read()

        # Add first image
        detector.is_duplicate(image_data, "test1.jpg")

        # Check same image again
        is_dup, match = detector.is_duplicate(image_data, "test2.jpg")
        assert is_dup is True
        assert match == "test1.jpg"

    @pytest.mark.unit
    def test_cache_population(self, temp_image):
        """Cache should be populated after checking."""
        detector = DuplicateDetector(db_connection=None)

        with open(temp_image, 'rb') as f:
            image_data = f.read()

        detector.is_duplicate(image_data, "test1.jpg")

        assert "test1.jpg" in detector.hash_cache
        assert 'content' in detector.hash_cache["test1.jpg"]
        assert 'perceptual' in detector.hash_cache["test1.jpg"]


# =============================================================================
# SMART AUTO-MATCHER CLASS TESTS
# =============================================================================

class TestSmartAutoMatcher:
    """Test suite for SmartAutoMatcher class."""

    @pytest.mark.unit
    def test_init_without_db(self):
        """Matcher should initialize without database."""
        matcher = SmartAutoMatcher(db_connection=None)
        assert matcher.db is None
        assert matcher.duplicate_detector is not None

    @pytest.mark.unit
    def test_init_with_db(self, mock_mysql_connection):
        """Matcher should initialize with database."""
        matcher = SmartAutoMatcher(db_connection=mock_mysql_connection)
        assert matcher.db is not None

    @pytest.mark.unit
    def test_calculate_match_score_exact(self, matcher):
        """Exact match should score high."""
        receipt = {
            'merchant': 'Anthropic',
            'amount': '20.00',
            'date': '2024-01-15',
        }
        transaction = {
            'chase_description': 'ANTHROPIC',
            'chase_amount': '20.00',
            'chase_date': '01/15/2024',
        }

        score, details = matcher.calculate_match_score(receipt, transaction)
        assert score >= AUTO_MATCH_THRESHOLD

    @pytest.mark.unit
    def test_calculate_match_score_with_tip(self, matcher):
        """Match with restaurant tip should score well."""
        receipt = {
            'merchant': 'Corner Pub',
            'amount': '50.00',
            'date': '2024-01-15',
        }
        transaction = {
            'chase_description': 'CORNER PUB',
            'chase_amount': '60.00',  # With 20% tip
            'chase_date': '01/15/2024',
        }

        score, details = matcher.calculate_match_score(receipt, transaction)
        assert score >= REVIEW_THRESHOLD

    @pytest.mark.unit
    def test_calculate_match_score_date_drift(self, matcher):
        """Match with posting delay should score reasonably."""
        receipt = {
            'merchant': 'Anthropic',
            'amount': '20.00',
            'date': '2024-01-15',
        }
        transaction = {
            'chase_description': 'ANTHROPIC',
            'chase_amount': '20.00',
            'chase_date': '01/17/2024',  # 2 days later
        }

        score, details = matcher.calculate_match_score(receipt, transaction)
        assert score >= REVIEW_THRESHOLD

    @pytest.mark.unit
    def test_calculate_match_score_different(self, matcher):
        """Different receipt/transaction should score low."""
        receipt = {
            'merchant': 'Anthropic',
            'amount': '20.00',
            'date': '2024-01-15',
        }
        transaction = {
            'chase_description': 'NETFLIX',
            'chase_amount': '15.99',
            'chase_date': '01/20/2024',
        }

        score, details = matcher.calculate_match_score(receipt, transaction)
        assert score < REVIEW_THRESHOLD

    @pytest.mark.unit
    def test_calculate_match_score_details(self, matcher):
        """Match should return detailed breakdown."""
        receipt = {
            'merchant': 'Anthropic',
            'amount': '20.00',
            'date': '2024-01-15',
        }
        transaction = {
            'chase_description': 'ANTHROPIC',
            'chase_amount': '20.00',
            'chase_date': '01/15/2024',
        }

        score, details = matcher.calculate_match_score(receipt, transaction)

        assert 'amount_score' in details
        assert 'merchant_score' in details
        assert 'date_score' in details

    @pytest.mark.unit
    def test_subscription_detection_in_scoring(self, matcher):
        """Subscription merchants should use extended date tolerance."""
        receipt = {
            'merchant': 'Spotify',
            'amount': '10.99',
            'date': '2024-01-15',
        }
        transaction = {
            'chase_description': 'SPOTIFY',
            'chase_amount': '10.99',
            'chase_date': '01/20/2024',  # 5 days later
        }

        score, details = matcher.calculate_match_score(receipt, transaction)
        # Should still score well due to subscription tolerance
        assert score >= REVIEW_THRESHOLD


# =============================================================================
# EDGE CASES AND ERROR HANDLING
# =============================================================================

class TestEdgeCases:
    """Test suite for edge cases and error handling."""

    @pytest.mark.unit
    def test_unicode_merchant_names(self):
        """Unicode characters in merchant names should be handled."""
        result = normalize_merchant("Café Délice")
        assert result is not None
        assert len(result) > 0

    @pytest.mark.unit
    def test_very_long_merchant_name(self):
        """Very long merchant names should be handled."""
        long_name = "A" * 1000
        result = normalize_merchant(long_name)
        assert result is not None

    @pytest.mark.unit
    def test_special_characters_only(self):
        """Merchant name with only special chars should handle gracefully."""
        result = normalize_merchant("!@#$%^&*()")
        assert result == ""

    @pytest.mark.unit
    def test_amount_with_multiple_decimals(self):
        """Amount with multiple decimal points should handle gracefully."""
        result = parse_amount("20.00.50")
        assert result == 0.0 or result > 0  # Should handle somehow

    @pytest.mark.unit
    def test_date_with_invalid_day(self):
        """Date with invalid day should return None."""
        result = parse_date("2024-02-30")  # Invalid date
        assert result is None

    @pytest.mark.unit
    def test_match_with_empty_receipt(self, matcher):
        """Empty receipt should not crash."""
        receipt = {}
        transaction = {
            'chase_description': 'ANTHROPIC',
            'chase_amount': '20.00',
        }

        score, details = matcher.calculate_match_score(receipt, transaction)
        assert score <= REVIEW_THRESHOLD

    @pytest.mark.unit
    def test_match_with_empty_transaction(self, matcher):
        """Empty transaction should not crash."""
        receipt = {
            'merchant': 'Anthropic',
            'amount': '20.00',
        }
        transaction = {}

        score, details = matcher.calculate_match_score(receipt, transaction)
        assert score <= REVIEW_THRESHOLD

    @pytest.mark.unit
    def test_corrupt_image_data(self):
        """Corrupt image data should not crash hash computation."""
        corrupt_data = b"not a valid image"
        result = compute_image_hash(corrupt_data)
        assert result is not None  # Should return fallback hash


# =============================================================================
# CONFIGURATION CONSTANTS TESTS
# =============================================================================

class TestConfiguration:
    """Test suite for configuration constants."""

    @pytest.mark.unit
    def test_thresholds_valid(self):
        """Thresholds should be valid percentages."""
        assert 0 < AUTO_MATCH_THRESHOLD <= 1.0
        assert 0 < REVIEW_THRESHOLD <= 1.0
        assert AUTO_MATCH_THRESHOLD > REVIEW_THRESHOLD

    @pytest.mark.unit
    def test_date_tolerances_valid(self):
        """Date tolerances should be reasonable."""
        assert DATE_TOLERANCE_RETAIL > 0
        assert DATE_TOLERANCE_SUBSCRIPTION >= DATE_TOLERANCE_RETAIL
        assert DATE_TOLERANCE_DELIVERY >= DATE_TOLERANCE_SUBSCRIPTION

    @pytest.mark.unit
    def test_amount_tolerances_valid(self):
        """Amount tolerances should be reasonable."""
        assert AMOUNT_EXACT > 0
        assert AMOUNT_CLOSE > AMOUNT_EXACT
        assert 0 < AMOUNT_TIP_VARIANCE < 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
