#!/usr/bin/env python3
"""
Test suite for the Receipt Library functionality.
Tests the backend services: receipt_library_service, duplicate_detector, receipt_search.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check if numpy is available (required by pandas)
try:
    import numpy
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Skip entire module if numpy not available
if not HAS_NUMPY:
    pytest.skip("numpy not installed", allow_module_level=True)


# ============================================
# Receipt Library Service Tests
# ============================================

class TestReceiptLibraryService:
    """Tests for receipt_library_service.py"""

    def test_receipt_source_enum_values(self):
        """Test that ReceiptSource enum has all expected values."""
        from services.receipt_library_service import ReceiptSource

        expected = ['gmail_personal', 'gmail_mcr', 'gmail_down_home',
                   'scanner_mobile', 'scanner_web', 'manual_upload',
                   'forwarded_email', 'bank_statement_pdf', 'import']

        for source in expected:
            assert hasattr(ReceiptSource, source.upper()), f"Missing source: {source}"

    def test_receipt_status_enum_values(self):
        """Test that ReceiptStatus enum has all expected values."""
        from services.receipt_library_service import ReceiptStatus

        expected = ['processing', 'ready', 'matched', 'duplicate', 'rejected', 'archived']

        for status in expected:
            assert hasattr(ReceiptStatus, status.upper()), f"Missing status: {status}"

    def test_business_type_enum_values(self):
        """Test that BusinessType enum has all expected values."""
        from services.receipt_library_service import BusinessType

        expected = ['down_home', 'mcr', 'personal', 'ceo', 'em_co', 'unknown']

        for bt in expected:
            assert hasattr(BusinessType, bt.upper()), f"Missing business type: {bt}"

    def test_receipt_library_item_creation(self):
        """Test creating a ReceiptLibraryItem dataclass."""
        from services.receipt_library_service import ReceiptLibraryItem

        item = ReceiptLibraryItem(
            uuid='test-uuid-123',
            storage_key='receipts/2024/test.jpg',
            merchant_name='Test Merchant',
            amount=Decimal('25.99'),
            receipt_date=date.today(),
            status='ready',
            business_type='personal'
        )

        assert item.uuid == 'test-uuid-123'
        assert item.storage_key == 'receipts/2024/test.jpg'
        assert item.merchant_name == 'Test Merchant'
        assert item.amount == Decimal('25.99')
        assert item.status == 'ready'
        assert item.business_type == 'personal'

    def test_library_search_query_defaults(self):
        """Test LibrarySearchQuery with default values."""
        from services.receipt_library_service import LibrarySearchQuery

        query = LibrarySearchQuery()

        assert query.text is None
        assert query.page == 1
        assert query.per_page == 50
        assert query.sort_by == 'created_at'
        assert query.sort_order == 'desc'

    def test_library_search_query_with_filters(self):
        """Test LibrarySearchQuery with various filters."""
        from services.receipt_library_service import LibrarySearchQuery

        query = LibrarySearchQuery(
            text='coffee',
            merchant='Starbucks',
            status=['matched'],
            business_type=['down_home'],
            amount_min=Decimal('10.00'),
            amount_max=Decimal('50.00'),
            date_from=date(2024, 1, 1),
            date_to=date(2024, 12, 31),
            page=2,
            per_page=100
        )

        assert query.text == 'coffee'
        assert query.merchant == 'Starbucks'
        assert query.status == ['matched']
        assert query.business_type == ['down_home']
        assert query.amount_min == Decimal('10.00')
        assert query.amount_max == Decimal('50.00')
        assert query.date_from == date(2024, 1, 1)
        assert query.date_to == date(2024, 12, 31)
        assert query.page == 2
        assert query.per_page == 100


# ============================================
# Duplicate Detector Tests
# ============================================

class TestDuplicateDetector:
    """Tests for duplicate_detector.py"""

    def test_duplicate_match_dataclass(self):
        """Test DuplicateMatch dataclass creation."""
        from services.duplicate_detector import DuplicateMatch

        match = DuplicateMatch(
            receipt_id=1,
            duplicate_of_id=2,
            confidence=0.95,
            reason='Identical content hash',
            detection_method='content_hash'
        )

        assert match.receipt_id == 1
        assert match.duplicate_of_id == 2
        assert match.confidence == 0.95
        assert match.reason == 'Identical content hash'
        assert match.detection_method == 'content_hash'

    def test_fingerprint_result_dataclass(self):
        """Test FingerprintResult dataclass creation."""
        from services.duplicate_detector import FingerprintResult

        result = FingerprintResult(
            content_hash='abc123',
            perceptual_hash='def456',
            file_size=12345
        )

        assert result.content_hash == 'abc123'
        assert result.perceptual_hash == 'def456'
        assert result.file_size == 12345

    def test_detector_constants(self):
        """Test DuplicateDetector class constants."""
        from services.duplicate_detector import DuplicateDetector

        assert DuplicateDetector.PHASH_THRESHOLD == 8
        assert DuplicateDetector.TEXT_SIMILARITY_THRESHOLD == 0.85
        assert DuplicateDetector.DATE_TOLERANCE_DAYS == 3
        assert DuplicateDetector.AMOUNT_TOLERANCE_PERCENT == 0.01


# ============================================
# Receipt Search Tests
# ============================================

class TestReceiptSearch:
    """Tests for receipt_search.py"""

    def test_parsed_query_defaults(self):
        """Test ParsedQuery with default values."""
        from services.receipt_search import ParsedQuery

        query = ParsedQuery(raw_query='test')

        assert query.raw_query == 'test'
        assert query.text_terms == []
        assert query.merchant is None
        assert query.amount_min is None
        assert query.amount_max is None
        assert query.date_from is None
        assert query.date_to is None
        assert query.status is None
        assert query.business_type is None
        assert query.source is None
        assert query.tags == []

    def test_search_result_dataclass(self):
        """Test SearchResult dataclass creation."""
        from services.receipt_search import SearchResult

        result = SearchResult(
            id=1,
            uuid='test-uuid',
            merchant_name='Test Merchant',
            merchant_normalized='test merchant',
            amount=25.99,
            receipt_date=date.today(),
            status='ready',
            business_type='personal',
            thumbnail_key='thumb/test.webp',
            storage_key='receipts/test.jpg',
            source='scanner_mobile',
            match_confidence=0.95,
            is_favorite=False,
            needs_review=False,
            relevance_score=0.95
        )

        assert result.uuid == 'test-uuid'
        assert result.merchant_name == 'Test Merchant'
        assert result.amount == 25.99
        assert result.relevance_score == 0.95

    def test_query_parser_simple_text(self):
        """Test parsing simple text query."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('coffee')

        assert parsed.raw_query == 'coffee'
        assert 'coffee' in parsed.text_terms

    def test_query_parser_merchant_filter(self):
        """Test parsing merchant: operator."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('merchant:starbucks')

        assert parsed.merchant == 'starbucks'

    def test_query_parser_amount_greater_than(self):
        """Test parsing amount greater than operator."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('amount:>50')

        assert parsed.amount_min == Decimal('50')

    def test_query_parser_amount_less_than(self):
        """Test parsing amount less than operator."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('amount:<100')

        assert parsed.amount_max == Decimal('100')

    def test_query_parser_date_shortcuts(self):
        """Test parsing date shortcuts."""
        from services.receipt_search import QueryParser

        parser = QueryParser()

        # Test today
        parsed = parser.parse('date:today')
        assert parsed.date_from == date.today()
        assert parsed.date_to == date.today()

        # Test this-week
        parsed = parser.parse('date:this-week')
        assert parsed.date_from is not None
        assert parsed.date_to is not None

    def test_query_parser_status_filter(self):
        """Test parsing status: operator."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('status:ready')

        assert parsed.status == 'ready'

    def test_query_parser_business_filter(self):
        """Test parsing type: operator for business type."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('type:down_home')

        assert parsed.business_type == 'down_home'

    def test_query_parser_hashtag(self):
        """Test parsing #hashtag."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('#lunch')

        assert 'lunch' in parsed.tags

    def test_query_parser_is_favorite(self):
        """Test parsing is:favorite flag."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('is:favorite')

        assert parsed.is_favorite is True

    def test_query_parser_complex_query(self):
        """Test parsing complex query with multiple operators."""
        from services.receipt_search import QueryParser

        parser = QueryParser()
        parsed = parser.parse('coffee merchant:starbucks amount:>10 date:this-month #business')

        assert 'coffee' in parsed.text_terms
        assert parsed.merchant == 'starbucks'
        assert parsed.amount_min == Decimal('10')
        assert 'business' in parsed.tags


# ============================================
# Thumbnail Generator Tests
# ============================================

class TestThumbnailGenerator:
    """Tests for thumbnail_generator.py"""

    def test_thumbnail_size_enum(self):
        """Test ThumbnailSize enum values."""
        from services.thumbnail_generator import ThumbnailSize

        assert ThumbnailSize.SMALL.value == (150, 150)
        assert ThumbnailSize.MEDIUM.value == (300, 300)
        assert ThumbnailSize.LARGE.value == (600, 600)
        assert ThumbnailSize.XLARGE.value == (1200, 1200)

    def test_thumbnail_result_dataclass(self):
        """Test ThumbnailResult dataclass creation."""
        from services.thumbnail_generator import ThumbnailResult, ThumbnailSize

        result = ThumbnailResult(
            success=True,
            size=ThumbnailSize.MEDIUM,
            width=300,
            height=200,
            format='webp',
            file_size=15000
        )

        assert result.success is True
        assert result.size == ThumbnailSize.MEDIUM
        assert result.width == 300
        assert result.height == 200
        assert result.format == 'webp'
        assert result.file_size == 15000

    def test_thumbnail_result_failure(self):
        """Test ThumbnailResult for failed generation."""
        from services.thumbnail_generator import ThumbnailResult, ThumbnailSize

        result = ThumbnailResult(
            success=False,
            size=ThumbnailSize.MEDIUM,
            width=0,
            height=0,
            format='webp',
            file_size=0,
            error='Invalid image data'
        )

        assert result.success is False
        assert result.error == 'Invalid image data'

    def test_thumbnail_set_dataclass(self):
        """Test ThumbnailSet dataclass creation."""
        from services.thumbnail_generator import ThumbnailSet, ThumbnailResult, ThumbnailSize

        small = ThumbnailResult(
            success=True, size=ThumbnailSize.SMALL,
            width=150, height=100, format='webp', file_size=5000
        )
        medium = ThumbnailResult(
            success=True, size=ThumbnailSize.MEDIUM,
            width=300, height=200, format='webp', file_size=15000
        )

        thumb_set = ThumbnailSet(
            receipt_uuid='test-uuid',
            small=small,
            medium=medium
        )

        assert thumb_set.receipt_uuid == 'test-uuid'
        assert thumb_set.small.width == 150
        assert thumb_set.medium.width == 300

    @pytest.mark.skipif(
        not pytest.importorskip('PIL', reason='PIL not installed'),
        reason='PIL not available'
    )
    def test_thumbnail_generator_initialization(self):
        """Test ThumbnailGenerator can be initialized."""
        from services.thumbnail_generator import ThumbnailGenerator

        generator = ThumbnailGenerator()

        assert generator is not None
        assert generator.cache_dir.exists()

    @pytest.mark.skipif(
        not pytest.importorskip('PIL', reason='PIL not installed'),
        reason='PIL not available'
    )
    def test_generate_placeholder(self):
        """Test placeholder thumbnail generation."""
        from services.thumbnail_generator import ThumbnailGenerator, ThumbnailSize

        generator = ThumbnailGenerator()
        result = generator.generate_placeholder(ThumbnailSize.MEDIUM)

        assert result.success is True
        assert result.width == 300
        assert result.height == 300
        assert result.format == 'webp'
        assert result.data is not None
        assert len(result.data) > 0

    @pytest.mark.skipif(
        not pytest.importorskip('PIL', reason='PIL not installed'),
        reason='PIL not available'
    )
    def test_cache_stats(self):
        """Test getting cache statistics."""
        from services.thumbnail_generator import ThumbnailGenerator

        generator = ThumbnailGenerator()
        stats = generator.get_cache_stats()

        assert 'cache_dir' in stats
        assert 'receipts_cached' in stats
        assert 'total_files' in stats
        assert 'total_size_bytes' in stats
        assert 'total_size_mb' in stats


# ============================================
# Integration Tests (require database)
# ============================================

@pytest.mark.skip(reason="Requires MySQL database connection")
class TestLibraryIntegration:
    """Integration tests that require database."""

    def test_full_receipt_lifecycle(self):
        """Test creating, searching, and deleting a receipt."""
        # This would test the full flow with actual database
        pass

    def test_duplicate_detection_on_insert(self):
        """Test that duplicates are detected when inserting."""
        pass

    def test_search_performance(self):
        """Test that search completes within acceptable time."""
        pass


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def sample_receipt_data():
    """Sample receipt data for testing."""
    return {
        'uuid': 'test-uuid-123',
        'merchant_name': 'Test Coffee Shop',
        'amount': Decimal('15.99'),
        'receipt_date': date.today(),
        'business_type': 'personal',
        'source': 'manual_upload',
        'storage_key': 'receipts/test/receipt.jpg'
    }


@pytest.fixture
def sample_image_bytes():
    """Generate a simple test image."""
    try:
        from PIL import Image
        import io

        img = Image.new('RGB', (400, 600), color='white')
        buffer = io.BytesIO()
        img.save(buffer, 'JPEG')
        return buffer.getvalue()
    except ImportError:
        return b'fake-image-data'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
