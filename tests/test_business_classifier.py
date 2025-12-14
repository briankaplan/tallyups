#!/usr/bin/env python3
"""
Comprehensive Unit Tests for Business Type Classifier
======================================================

Tests based on ACTUAL DATABASE classifications.
The business types are already set correctly in the database.

Business Types:
- Down Home: Production company (Tim McGraw partnership)
- Music City Rodeo: Event (PRCA rodeo in Nashville)
- Em.co: Additional business entity
- Personal: Personal/family expenses

NOTE: Some merchants (HotelTonight, Southwest, Uber) can legitimately
appear under different business types depending on the specific transaction.
"""

import unittest
from decimal import Decimal
from datetime import datetime, timedelta
import sys
from pathlib import Path
import tempfile
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from business_classifier import (
    BusinessTypeClassifier,
    BusinessType,
    ClassificationResult,
    ClassificationSignal,
    Transaction,
    Receipt,
    CalendarEvent,
    Contact,
    classify_transaction,
)


def make_transaction(merchant: str, amount: float, **kwargs) -> Transaction:
    """Helper to create Transaction."""
    return Transaction(
        id=kwargs.get('id', 1),
        merchant=merchant,
        amount=Decimal(str(amount)),
        date=kwargs.get('date', datetime.now()),
        description=kwargs.get('description'),
        category=kwargs.get('category'),
    )


def make_receipt(merchant: str, amount: float, **kwargs) -> Receipt:
    """Helper to create Receipt."""
    return Receipt(
        id=kwargs.get('id', 1),
        merchant=merchant,
        amount=Decimal(str(amount)),
        date=kwargs.get('date'),
        email_from=kwargs.get('email_from'),
        email_domain=kwargs.get('email_domain'),
        items=kwargs.get('items'),
        attendees=kwargs.get('attendees'),
        location=kwargs.get('location'),
        raw_text=kwargs.get('raw_text'),
    )


# =============================================================================
# DOWN HOME CLASSIFICATION TESTS - AI & SOFTWARE
# Tests for merchants that are definitively Down Home in the database
# =============================================================================

class TestDownHomeAIAndSoftware(unittest.TestCase):
    """Tests for Down Home AI & Software classification."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_anthropic(self):
        """Anthropic is Down Home."""
        tx = make_transaction("Anthropic", 20.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_claude_ai(self):
        """Claude AI is Down Home."""
        tx = make_transaction("Claude AI", 20.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_midjourney(self):
        """Midjourney is Down Home."""
        tx = make_transaction("Midjourney", 30.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_cursor(self):
        """Cursor is Down Home."""
        tx = make_transaction("Cursor", 20.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_hugging_face(self):
        """Hugging Face is Down Home."""
        tx = make_transaction("Hugging Face", 10.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_ada_ai(self):
        """Ada AI is Down Home."""
        tx = make_transaction("Ada AI", 50.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_cloudflare(self):
        """Cloudflare is Down Home."""
        tx = make_transaction("Cloudflare", 25.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_expensify(self):
        """Expensify is Down Home."""
        tx = make_transaction("Expensify", 5.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_sourcegraph(self):
        """Sourcegraph is Down Home."""
        tx = make_transaction("Sourcegraph", 25.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_calendarbridge(self):
        """CalendarBridge is Down Home."""
        tx = make_transaction("CalendarBridge", 10.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_chartmetric(self):
        """Chartmetric is Down Home."""
        tx = make_transaction("Chartmetric", 50.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_imdbpro(self):
        """IMDbPro is Down Home."""
        tx = make_transaction("IMDbPro", 15.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)


# =============================================================================
# DOWN HOME CLASSIFICATION TESTS - DINING & PARKING
# Tests for Nashville venues that are Down Home in the database
# =============================================================================

class TestDownHomeDiningAndParking(unittest.TestCase):
    """Tests for Down Home dining and parking classification."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_soho_house_nashville(self):
        """Soho House Nashville is Down Home."""
        tx = make_transaction("Soho House Nashville", 150.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_corner_pub(self):
        """Corner Pub is Down Home."""
        tx = make_transaction("Corner Pub", 50.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_12_south_taproom(self):
        """12 South Taproom is Down Home."""
        tx = make_transaction("12 South Taproom", 60.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_metropolis_parking(self):
        """Metropolis Parking is Down Home."""
        tx = make_transaction("Metropolis Parking", 15.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_pmc_parking(self):
        """PMC Parking is Down Home."""
        tx = make_transaction("PMC Parking", 10.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_uber(self):
        """Uber is Down Home (per actual data)."""
        tx = make_transaction("Uber", 25.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_doordash(self):
        """DoorDash is Down Home (per actual data)."""
        tx = make_transaction("DoorDash", 30.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_spotify(self):
        """Spotify is Down Home (per actual data)."""
        tx = make_transaction("Spotify", 9.99)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)


# =============================================================================
# MUSIC CITY RODEO CLASSIFICATION TESTS
# Tests for merchants that are definitively MCR in the database
# =============================================================================

class TestMusicCityRodeoClassification(unittest.TestCase):
    """Tests for Music City Rodeo classification."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_hive(self):
        """Hive is Music City Rodeo."""
        tx = make_transaction("Hive", 50.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)

    def test_easyfaq(self):
        """EasyFAQ is Music City Rodeo."""
        tx = make_transaction("EasyFAQ", 30.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)

    def test_google_gsuite_musicci(self):
        """Google GSuite MusicCi is Music City Rodeo."""
        tx = make_transaction("Google *GSuite_MusicCi", 12.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)

    def test_hattiebs(self):
        """Hattie B's is Music City Rodeo."""
        tx = make_transaction("HattieBs", 40.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)

    def test_zoom_mcr(self):
        """Zoom for MCR is Music City Rodeo."""
        tx = make_transaction("Zoom.com 888-799-9666", 15.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)

    def test_cambria_hotel_nashville(self):
        """Cambria Hotel Nashville is Music City Rodeo."""
        tx = make_transaction("Cambria Hotel Nashville D", 200.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)

    # NOTE: HotelTonight and some other merchants can be multiple business types
    # depending on the specific transaction context. Tests only cover definitively
    # single-type merchants.

    def test_zoomcom_mcr(self):
        """Zoomcom (MCR specific) is Music City Rodeo."""
        tx = make_transaction("Zoomcom", 15.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)


# =============================================================================
# PERSONAL CLASSIFICATION TESTS
# Tests for merchants that are definitively Personal in the database
# =============================================================================

class TestPersonalClassification(unittest.TestCase):
    """Tests for Personal classification."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_apple(self):
        """Apple is Personal (per actual data)."""
        tx = make_transaction("Apple", 99.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_apple_store(self):
        """Apple Store is Personal (per actual data)."""
        tx = make_transaction("Apple Store", 500.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_amazon(self):
        """Amazon is Personal (per actual data)."""
        tx = make_transaction("Amazon", 50.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_nordstrom(self):
        """Nordstrom is Personal."""
        tx = make_transaction("Nordstrom", 200.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_suitsupply(self):
        """Suitsupply is Personal."""
        tx = make_transaction("Suitsupply", 400.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_buck_mason(self):
        """Buck Mason is Personal."""
        tx = make_transaction("Buck Mason", 100.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_chase_payment(self):
        """Chase Payment is Personal."""
        tx = make_transaction("Chase Payment", 500.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_chase_interest(self):
        """Chase Interest Charge is Personal."""
        tx = make_transaction("Chase Interest Charge", 50.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_southwest(self):
        """Southwest is Personal (per actual data)."""
        tx = make_transaction("Southwest", 400.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_cowboy_channel_plus(self):
        """Cowboy Channel Plus is Personal."""
        tx = make_transaction("Cowboy Channel Plus", 6.99)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)

    def test_paige_llc(self):
        """Paige LLC is Personal."""
        tx = make_transaction("Paige LLC", 200.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.PERSONAL)


# =============================================================================
# EMAIL DOMAIN MATCHING TESTS
# =============================================================================

class TestEmailDomainMatching(unittest.TestCase):
    """Tests for email domain classification."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_anthropic_email(self):
        """Anthropic email domain."""
        tx = make_transaction("Unknown Charge", 20.00)
        receipt = make_receipt("Unknown", 20.00, email_domain="anthropic.com")
        result = self.classifier.classify(tx, receipt)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_figma_email(self):
        """Figma email is Down Home."""
        tx = make_transaction("Unknown", 15.00)
        receipt = make_receipt("Unknown", 15.00, email_domain="figma.com")
        result = self.classifier.classify(tx, receipt)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_uber_email(self):
        """Uber email is Down Home (per actual data)."""
        tx = make_transaction("Unknown", 25.00)
        receipt = make_receipt("Unknown", 25.00, email_domain="uber.com")
        result = self.classifier.classify(tx, receipt)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)


# =============================================================================
# LEARNING SYSTEM TESTS
# =============================================================================

class TestLearningSystem(unittest.TestCase):
    """Tests for learning from corrections."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.classifier = BusinessTypeClassifier(data_dir=Path(self.temp_dir))

    def test_learn_from_correction(self):
        """Learning system saves correction."""
        self.classifier.learn_from_correction(
            transaction_id=1,
            merchant="New Vendor",
            amount=Decimal("100.00"),
            correct_type=BusinessType.MUSIC_CITY_RODEO,
            user_notes="This is for MCR"
        )
        self.assertTrue(len(self.classifier.learned_corrections) > 0)

    def test_learned_correction_applied(self):
        """Learned correction is applied on next classification."""
        self.classifier.learn_from_correction(
            transaction_id=1,
            merchant="Special Vendor XYZ",
            amount=Decimal("100.00"),
            correct_type=BusinessType.MUSIC_CITY_RODEO,
        )
        tx = make_transaction("Special Vendor XYZ", 100.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.MUSIC_CITY_RODEO)


# =============================================================================
# EDGE CASES TESTS
# =============================================================================

class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and special handling."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_empty_merchant(self):
        """Empty merchant handled gracefully."""
        tx = make_transaction("", 50.00)
        result = self.classifier.classify(tx)
        self.assertIsNotNone(result.business_type)

    def test_very_long_merchant(self):
        """Very long merchant name handled."""
        long_name = "A" * 500
        tx = make_transaction(long_name, 50.00)
        result = self.classifier.classify(tx)
        self.assertIsNotNone(result.business_type)

    def test_special_characters(self):
        """Special characters in merchant handled."""
        tx = make_transaction("Café & Bistro™ #123", 25.00)
        result = self.classifier.classify(tx)
        self.assertIsNotNone(result.business_type)

    def test_case_insensitive(self):
        """Case insensitive matching."""
        tx = make_transaction("ANTHROPIC", 20.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_pos_prefix_handling(self):
        """POS prefix stripped correctly."""
        tx = make_transaction("SQ *ANTHROPIC", 20.00)
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_fuzzy_match(self):
        """Fuzzy matching works."""
        tx = make_transaction("Antropic", 20.00)  # Typo
        result = self.classifier.classify(tx)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_alternative_types(self):
        """Alternative types populated."""
        tx = make_transaction("Unknown Coffee Shop", 5.00)
        result = self.classifier.classify(tx)
        self.assertIsInstance(result.alternative_types, dict)


# =============================================================================
# STATISTICS TESTS
# =============================================================================

class TestStatistics(unittest.TestCase):
    """Tests for statistics tracking."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_stats_initialized(self):
        """Statistics initialized."""
        self.assertIn('total_classifications', self.classifier.stats)
        self.assertIn('by_confidence', self.classifier.stats)
        self.assertIn('by_type', self.classifier.stats)

    def test_stats_increment(self):
        """Statistics increment on classification."""
        initial = self.classifier.stats['total_classifications']
        tx = make_transaction("Anthropic", 20.00)
        self.classifier.classify(tx)
        self.assertEqual(self.classifier.stats['total_classifications'], initial + 1)

    def test_get_stats(self):
        """Get stats method works."""
        stats = self.classifier.get_stats()
        self.assertIsInstance(stats, dict)


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestConvenienceFunctions(unittest.TestCase):
    """Tests for convenience functions."""

    def test_classify_transaction_function(self):
        """classify_transaction convenience function."""
        result = classify_transaction("Anthropic", 20.00)
        self.assertEqual(result.business_type, BusinessType.DOWN_HOME)

    def test_result_to_dict(self):
        """Result converts to dict."""
        tx = make_transaction("Anthropic", 20.00)
        classifier = BusinessTypeClassifier()
        result = classifier.classify(tx)
        d = result.to_dict()
        self.assertIn('business_type', d)
        self.assertIn('confidence', d)
        self.assertIn('reasoning', d)

    def test_business_type_from_string(self):
        """BusinessType.from_string works."""
        self.assertEqual(BusinessType.from_string('down_home'), BusinessType.DOWN_HOME)
        self.assertEqual(BusinessType.from_string('Down Home'), BusinessType.DOWN_HOME)
        self.assertEqual(BusinessType.from_string('music_city_rodeo'), BusinessType.MUSIC_CITY_RODEO)
        self.assertEqual(BusinessType.from_string('MCR'), BusinessType.MUSIC_CITY_RODEO)
        self.assertEqual(BusinessType.from_string('personal'), BusinessType.PERSONAL)
        self.assertEqual(BusinessType.from_string('em_co'), BusinessType.EM_CO)


# =============================================================================
# BATCH CLASSIFICATION TESTS
# =============================================================================

class TestBatchClassification(unittest.TestCase):
    """Tests for batch classification."""

    def setUp(self):
        self.classifier = BusinessTypeClassifier()

    def test_classify_batch(self):
        """Batch classification works."""
        transactions = [
            make_transaction("Anthropic", 20.00, id=1),
            make_transaction("Apple", 99.00, id=2),
            make_transaction("Hive", 50.00, id=3),
        ]
        results = self.classifier.classify_batch(transactions)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].business_type, BusinessType.DOWN_HOME)
        self.assertEqual(results[1].business_type, BusinessType.PERSONAL)
        self.assertEqual(results[2].business_type, BusinessType.MUSIC_CITY_RODEO)

    def test_empty_batch(self):
        """Empty batch returns empty list."""
        results = self.classifier.classify_batch([])
        self.assertEqual(len(results), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
