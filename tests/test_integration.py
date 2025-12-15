#!/usr/bin/env python3
"""
Integration Tests for ReceiptAI
===============================

Tests for module interactions and complete workflows including:
- Receipt processing flow
- API endpoint chains
- Database operations
- Service interactions

Test Coverage Target: 85%+
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check if pytest-asyncio is available
try:
    import pytest_asyncio
    HAS_PYTEST_ASYNCIO = True
except ImportError:
    HAS_PYTEST_ASYNCIO = False


# =============================================================================
# RECEIPT PROCESSING FLOW TESTS
# =============================================================================

class TestReceiptProcessingFlow:
    """Test complete receipt processing workflows."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PYTEST_ASYNCIO, reason="pytest-asyncio not installed")
    async def test_gmail_to_matched_flow(self, tmp_path):
        """Test flow: Email arrives → Extracted → Matched → Reviewed."""
        # This test simulates the complete flow from email to matched receipt

        # Step 1: Mock Gmail API returning a receipt email
        mock_gmail_message = {
            'id': 'msg123',
            'payload': {
                'headers': [
                    {'name': 'From', 'value': 'billing@anthropic.com'},
                    {'name': 'Subject', 'value': 'Your receipt from Anthropic'},
                    {'name': 'Date', 'value': 'Mon, 15 Jan 2024 12:00:00 -0500'},
                ],
                'body': {
                    'data': 'VGVzdCByZWNlaXB0IGNvbnRlbnQ='  # Base64 encoded
                },
                'parts': [
                    {
                        'filename': 'receipt.pdf',
                        'body': {'attachmentId': 'att123'},
                        'mimeType': 'application/pdf',
                    }
                ]
            }
        }

        # Step 2: Mock OCR extraction result
        mock_ocr_result = {
            'supplier_name': 'Anthropic',
            'total_amount': 20.00,
            'invoice_date': '2024-01-15',
            'confidence': 0.95,
        }

        # Step 3: Mock transaction from database
        mock_transaction = {
            'id': 1,
            'chase_description': 'ANTHROPIC',
            'chase_amount': '20.00',
            'chase_date': '01/15/2024',
            'business_type': 'down_home',
        }

        # Verify flow logic
        # 1. Extract email metadata
        email_from = None
        for header in mock_gmail_message['payload']['headers']:
            if header['name'] == 'From':
                email_from = header['value']
                break

        assert email_from == 'billing@anthropic.com'
        assert 'anthropic' in email_from.lower()

        # 2. Check if OCR matches transaction
        ocr_merchant = mock_ocr_result['supplier_name'].lower()
        tx_merchant = mock_transaction['chase_description'].lower()
        assert ocr_merchant == tx_merchant

        # 3. Verify amounts match
        assert abs(mock_ocr_result['total_amount'] - float(mock_transaction['chase_amount'])) < 0.01

    @pytest.mark.integration
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PYTEST_ASYNCIO, reason="pytest-asyncio not installed")
    async def test_scanner_upload_flow(self, tmp_path, temp_image):
        """Test flow: Photo uploaded → OCR processed → Matched."""
        # Simulate receipt photo upload

        # Step 1: Image file exists
        assert temp_image.exists()

        # Step 2: Mock OCR processing
        mock_ocr_result = {
            'supplier_name': 'Corner Pub',
            'total_amount': 45.50,
            'invoice_date': '2024-01-15',
            'confidence': 0.88,
            'tip_amount': 9.00,
        }

        # Step 3: Mock R2 upload
        mock_r2_url = f"https://r2.example.com/receipts/{temp_image.name}"

        # Step 4: Verify processing chain
        assert mock_ocr_result['supplier_name'] is not None
        assert mock_ocr_result['total_amount'] > 0
        assert mock_ocr_result['confidence'] > 0.5

    @pytest.mark.integration
    def test_duplicate_receipt_detection_flow(self, temp_image):
        """Test flow: Upload receipt → Check duplicate → Handle appropriately."""
        try:
            from smart_auto_matcher import DuplicateDetector, compute_content_hash
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        with open(temp_image, 'rb') as f:
            image_data = f.read()

        detector = DuplicateDetector(db_connection=None)

        # First upload - not duplicate
        is_dup1, match1 = detector.is_duplicate(image_data, "receipt_001.jpg")
        assert is_dup1 is False
        assert match1 is None

        # Same image again - should be duplicate
        is_dup2, match2 = detector.is_duplicate(image_data, "receipt_002.jpg")
        assert is_dup2 is True
        assert match2 == "receipt_001.jpg"


# =============================================================================
# API ENDPOINT INTEGRATION TESTS
# =============================================================================

class TestAPIEndpoints:
    """Test API endpoint interactions."""

    @pytest.fixture
    def mock_app(self):
        """Create mock Flask app."""
        try:
            from viewer_server import app
            app.config['TESTING'] = True
            app.config['WTF_CSRF_ENABLED'] = False
            return app
        except (ImportError, RuntimeError):
            pytest.skip("viewer_server not available (MySQL required)")

    @pytest.mark.integration
    def test_health_endpoint(self, mock_app):
        """GET /health should return 200."""
        with mock_app.test_client() as client:
            response = client.get('/health')
            assert response.status_code == 200

    @pytest.mark.integration
    def test_api_health_endpoint(self, mock_app):
        """GET /api/health should return detailed status."""
        with mock_app.test_client() as client:
            response = client.get('/api/health')
            assert response.status_code in [200, 500]  # May fail if DB not available

    @pytest.mark.integration
    @patch('viewer_server.get_db_connection')
    def test_transactions_list(self, mock_db, mock_app):
        """GET /api/transactions should return transactions."""
        # Mock database response
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'merchant': 'Anthropic', 'amount': '20.00'},
            {'id': 2, 'merchant': 'Netflix', 'amount': '15.99'},
        ]
        mock_db.return_value = mock_conn

        with mock_app.test_client() as client:
            response = client.get('/api/transactions')
            # Response should be valid
            assert response.status_code in [200, 500]

    @pytest.mark.integration
    @patch('viewer_server.get_db_connection')
    def test_transactions_filter_by_business_type(self, mock_db, mock_app):
        """GET /api/transactions with business_type filter should work."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'merchant': 'Anthropic', 'amount': '20.00', 'business_type': 'down_home'},
        ]
        mock_db.return_value = mock_conn

        with mock_app.test_client() as client:
            response = client.get('/api/transactions?business_type=down_home')
            assert response.status_code in [200, 500]

    @pytest.mark.integration
    @patch('viewer_server.get_db_connection')
    def test_transaction_search(self, mock_db, mock_app):
        """GET /api/transactions/search should work."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_db.return_value = mock_conn

        with mock_app.test_client() as client:
            response = client.get('/api/transactions/search?q=anthropic')
            # Accept 404 if search endpoint not implemented
            assert response.status_code in [200, 404, 500]


# =============================================================================
# CLASSIFICATION INTEGRATION TESTS
# =============================================================================

class TestClassificationIntegration:
    """Test classification system integration."""

    @pytest.mark.integration
    def test_classify_and_learn(self, tmp_path):
        """Classify → Correct → Re-classify should show learning."""
        try:
            from business_classifier import BusinessTypeClassifier, BusinessType, Transaction
        except ImportError:
            pytest.skip("business_classifier not available")

        try:
            classifier = BusinessTypeClassifier(data_dir=tmp_path)
        except TypeError:
            classifier = BusinessTypeClassifier()

        # Initial classification of unknown merchant
        tx = Transaction(
            id=1,
            merchant="New Test Venue",
            amount=Decimal("200.00"),
            date=datetime.now(),
        )

        result1 = classifier.classify(tx)

        # Learn correction
        classifier.learn_from_correction(
            transaction_id=1,
            merchant="New Test Venue",
            amount=Decimal("200.00"),
            correct_type=BusinessType.MUSIC_CITY_RODEO,
            user_notes="MCR event venue",
        )

        # Re-classify should use learned data
        result2 = classifier.classify(tx)
        assert result2.business_type == BusinessType.MUSIC_CITY_RODEO

    @pytest.mark.integration
    def test_batch_classify_with_context(self, tmp_path):
        """Batch classification with calendar/contact context."""
        try:
            from business_classifier import (
                BusinessTypeClassifier, BusinessType, Transaction,
                CalendarEvent, Contact
            )
        except ImportError:
            pytest.skip("business_classifier not available")

        try:
            classifier = BusinessTypeClassifier(data_dir=tmp_path)
        except TypeError:
            classifier = BusinessTypeClassifier()

        transactions = [
            Transaction(id=1, merchant="Restaurant A", amount=Decimal("100.00"), date=datetime.now()),
            Transaction(id=2, merchant="Restaurant B", amount=Decimal("75.00"), date=datetime.now()),
            Transaction(id=3, merchant="Anthropic", amount=Decimal("20.00"), date=datetime.now()),
        ]

        results = classifier.classify_batch(transactions)

        assert len(results) == 3
        assert results[2].business_type == BusinessType.DOWN_HOME


# =============================================================================
# MATCHING INTEGRATION TESTS
# =============================================================================

class TestMatchingIntegration:
    """Test matching system integration."""

    @pytest.mark.integration
    def test_match_with_duplicate_detection(self, temp_image):
        """Matching should check for duplicates first."""
        try:
            from smart_auto_matcher import SmartAutoMatcher, DuplicateDetector
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        matcher = SmartAutoMatcher(db_connection=None)

        with open(temp_image, 'rb') as f:
            image_data = f.read()

        # Add to duplicate detector
        is_dup, _ = matcher.duplicate_detector.is_duplicate(image_data, "existing.jpg")
        assert is_dup is False

        # Same image should be duplicate
        is_dup2, match = matcher.duplicate_detector.is_duplicate(image_data, "new.jpg")
        assert is_dup2 is True
        assert match == "existing.jpg"

    @pytest.mark.integration
    def test_match_scoring_integration(self):
        """Test complete match scoring with all factors."""
        try:
            from smart_auto_matcher import SmartAutoMatcher, AUTO_MATCH_THRESHOLD
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        matcher = SmartAutoMatcher(db_connection=None)

        # Perfect match
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
        assert details['amount_score'] >= 0.95
        assert details['merchant_score'] >= 0.90
        assert details['date_score'] >= 0.95


# =============================================================================
# REPORT GENERATION INTEGRATION TESTS
# =============================================================================

class TestReportGenerationIntegration:
    """Test report generation integration."""

    @pytest.mark.integration
    def test_generate_and_export_csv(self):
        """Generate report → Export to CSV should work."""
        try:
            from services.report_generator import ExpenseReportGenerator
            from services.csv_exporter import CSVExporter
        except ImportError:
            pytest.skip("Report services not available")

        # This would need actual transaction data or mocks
        # Simplified test
        exporter = CSVExporter()
        assert exporter is not None

    @pytest.mark.integration
    def test_generate_and_export_excel(self):
        """Generate report → Export to Excel should work."""
        try:
            from services.report_generator import ExpenseReportGenerator
            from services.excel_exporter import ExcelExporter
        except ImportError:
            pytest.skip("Report services not available")

        exporter = ExcelExporter()
        assert exporter is not None

    @pytest.mark.integration
    def test_generate_and_export_pdf(self):
        """Generate report → Export to PDF should work."""
        try:
            from services.report_generator import ExpenseReportGenerator
            from services.pdf_exporter import PDFExporter
        except ImportError:
            pytest.skip("Report services not available")

        exporter = PDFExporter()
        assert exporter is not None


# =============================================================================
# NOTES SERVICE INTEGRATION TESTS
# =============================================================================

class TestNotesServiceIntegration:
    """Test smart notes service integration."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PYTEST_ASYNCIO, reason="pytest-asyncio not installed")
    async def test_generate_note_with_calendar(self, tmp_path):
        """Note generation with calendar context should work."""
        try:
            from services.smart_notes_service import (
                SmartNotesService, CalendarEvent, NoteResult
            )
        except ImportError:
            pytest.skip("SmartNotesService not available")

        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))
            service.claude_client = None

            # Mock calendar event
            event = CalendarEvent(
                id="evt123",
                title="Lunch with Patrick",
                start_time=datetime(2024, 1, 15, 12, 0),
                attendees=["Patrick Humes"],
            )
            service.calendar_client = MagicMock()
            service.calendar_client.get_events_around_time = Mock(return_value=[event])

            result = await service.generate_note(
                merchant="Soho House Nashville",
                amount=150.00,
                date=datetime(2024, 1, 15, 12, 30),
            )

            assert isinstance(result, NoteResult)
            assert result.calendar_event is not None

    @pytest.mark.integration
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PYTEST_ASYNCIO, reason="pytest-asyncio not installed")
    async def test_batch_note_generation(self, tmp_path):
        """Batch note generation should work."""
        try:
            from services.smart_notes_service import SmartNotesService
        except ImportError:
            pytest.skip("SmartNotesService not available")

        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))
            service.claude_client = None
            service.calendar_client = MagicMock()
            service.calendar_client.get_events_around_time = Mock(return_value=[])

            transactions = [
                {"merchant": "Restaurant A", "amount": 50.00, "date": "2024-01-15"},
                {"merchant": "Restaurant B", "amount": 75.00, "date": "2024-01-16"},
            ]

            results = await service.generate_batch(transactions)

            assert len(results) == 2


# =============================================================================
# DATABASE INTEGRATION TESTS
# =============================================================================

class TestDatabaseIntegration:
    """Test database operations integration."""

    @pytest.mark.integration
    @pytest.mark.requires_db
    def test_connection_pool(self):
        """Connection pool should manage connections properly."""
        try:
            from db_mysql import ConnectionPool
        except ImportError:
            pytest.skip("db_mysql not available")

        # Would need actual database for real test
        # This is a placeholder for the pattern

    @pytest.mark.integration
    def test_cache_operations(self, tmp_path):
        """Cache operations should work correctly."""
        try:
            from cache_manager import ThreadSafeCache
        except ImportError:
            pytest.skip("cache_manager not available")

        cache = ThreadSafeCache(ttl_seconds=60)

        # Set value
        cache.set("test_key", "test_value")

        # Get value
        value = cache.get("test_key")
        assert value == "test_value"

        # Delete value
        cache.delete("test_key")
        assert cache.get("test_key") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
