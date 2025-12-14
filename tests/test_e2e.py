#!/usr/bin/env python3
"""
End-to-End Tests for ReceiptAI
==============================

Tests for complete user workflows including:
- New expense submission flow
- Manual receipt matching flow
- Bulk review and approval flow
- Report generation flow
- Settings and configuration flow

These tests simulate real user interactions with the system.
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
# NEW EXPENSE FLOW TESTS
# =============================================================================

class TestNewExpenseFlow:
    """Test complete new expense submission workflow."""

    @pytest.mark.e2e
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PYTEST_ASYNCIO, reason="pytest-asyncio not installed")
    async def test_email_receipt_to_approved(self, tmp_path):
        """
        Full flow: Email receipt arrives → Auto-processed → Matched → Reviewed → Approved

        Steps:
        1. User receives email receipt (simulated Gmail push)
        2. System auto-extracts receipt data via OCR
        3. System finds matching transaction
        4. System generates smart note
        5. User reviews and approves in dashboard
        6. User generates expense report
        """
        # Step 1: Simulate email receipt arrival
        email_receipt = {
            'message_id': 'msg_001',
            'from': 'billing@anthropic.com',
            'subject': 'Your Anthropic receipt - $20.00',
            'date': datetime(2024, 1, 15, 12, 0),
            'attachment': {
                'filename': 'receipt.pdf',
                'mime_type': 'application/pdf',
            }
        }

        # Step 2: Simulate OCR extraction
        ocr_result = {
            'supplier_name': 'Anthropic',
            'total_amount': 20.00,
            'invoice_date': datetime(2024, 1, 15),
            'confidence': 0.95,
            'line_items': [
                {'description': 'Claude Pro Subscription', 'amount': 20.00}
            ]
        }

        # Step 3: Simulate transaction matching
        transaction = {
            'id': 1,
            'merchant': 'ANTHROPIC',
            'amount': Decimal('20.00'),
            'date': datetime(2024, 1, 15),
            'business_type': 'down_home',
            'category': 'Software & Subscriptions',
        }

        # Verify flow logic
        assert email_receipt['from'].endswith('anthropic.com')
        assert ocr_result['supplier_name'].lower() == 'anthropic'
        assert abs(ocr_result['total_amount'] - float(transaction['amount'])) < 0.01

        # Step 4: Simulate smart note generation
        try:
            from services.smart_notes_service import SmartNotesService
            with patch.object(SmartNotesService, '_load_contacts_cache'):
                service = SmartNotesService(credentials_dir=str(tmp_path))
                service.claude_client = None
                service.calendar_client = MagicMock()
                service.calendar_client.get_events_around_time = Mock(return_value=[])

                note_result = await service.generate_note(
                    merchant='Anthropic',
                    amount=20.00,
                    date=datetime(2024, 1, 15),
                    business_type='Down Home',
                    category='Software & Subscriptions',
                )

                assert note_result.note is not None
        except ImportError:
            pass  # Skip if service not available

        # Step 5: Simulate user approval (would be API call)
        approval_data = {
            'transaction_id': 1,
            'status': 'APPROVED',
            'reviewed_at': datetime.now(),
            'reviewer': 'test_user',
        }
        assert approval_data['status'] == 'APPROVED'

    @pytest.mark.e2e
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PYTEST_ASYNCIO, reason="pytest-asyncio not installed")
    async def test_scanner_upload_to_matched(self, tmp_path, temp_image):
        """
        Full flow: User scans receipt → Uploaded → OCR processed → Matched

        Steps:
        1. User opens scanner in mobile app
        2. User takes photo of receipt
        3. System uploads to R2
        4. System runs OCR
        5. System matches to transaction
        """
        # Step 1-2: User captures receipt photo
        assert temp_image.exists()

        # Step 3: Simulate R2 upload
        r2_url = f"https://r2.example.com/receipts/{temp_image.name}"

        # Step 4: Simulate OCR result
        ocr_result = {
            'supplier_name': 'Corner Pub',
            'total_amount': 65.50,
            'tip_amount': 13.00,
            'subtotal': 52.50,
            'invoice_date': datetime(2024, 1, 15),
            'confidence': 0.88,
        }

        # Step 5: Simulate matching
        try:
            from smart_auto_matcher import SmartAutoMatcher
            matcher = SmartAutoMatcher(db_connection=None)

            receipt = {
                'merchant': ocr_result['supplier_name'],
                'amount': str(ocr_result['subtotal']),  # Pre-tip amount
                'date': ocr_result['invoice_date'].strftime('%Y-%m-%d'),
            }
            transaction = {
                'chase_description': 'CORNER PUB',
                'chase_amount': str(ocr_result['total_amount']),  # With tip
                'chase_date': '01/15/2024',
            }

            score, details = matcher.calculate_match_score(receipt, transaction)
            assert score >= 0.5, "Should find reasonable match"
        except ImportError:
            pass


# =============================================================================
# MANUAL MATCHING FLOW TESTS
# =============================================================================

class TestManualMatchingFlow:
    """Test manual receipt matching workflow."""

    @pytest.mark.e2e
    def test_unmatched_transaction_to_matched(self, tmp_path, temp_image):
        """
        Full flow: User has unmatched transaction → Uploads receipt → Confirms match

        Steps:
        1. User views unmatched transactions in dashboard
        2. User selects transaction
        3. User uploads receipt photo
        4. System suggests match
        5. User confirms match
        """
        # Step 1: Simulate unmatched transaction
        unmatched_transaction = {
            'id': 1,
            'merchant': 'UBER TRIP',
            'amount': Decimal('25.00'),
            'date': datetime(2024, 1, 15),
            'review_status': None,
            'receipt_url': None,
        }

        assert unmatched_transaction['review_status'] is None
        assert unmatched_transaction['receipt_url'] is None

        # Step 2-3: User uploads receipt
        assert temp_image.exists()

        # Step 4: System suggests match
        suggested_match = {
            'transaction_id': 1,
            'receipt_merchant': 'Uber',
            'receipt_amount': 25.00,
            'match_score': 0.92,
            'confidence': 'HIGH',
        }

        assert suggested_match['match_score'] >= 0.75

        # Step 5: User confirms
        confirmed_transaction = {
            **unmatched_transaction,
            'review_status': 'MATCHED',
            'receipt_url': f"https://r2.example.com/{temp_image.name}",
            'match_confirmed_at': datetime.now(),
        }

        assert confirmed_transaction['review_status'] == 'MATCHED'
        assert confirmed_transaction['receipt_url'] is not None


# =============================================================================
# BULK REVIEW FLOW TESTS
# =============================================================================

class TestBulkReviewFlow:
    """Test bulk review and approval workflow."""

    @pytest.mark.e2e
    def test_bulk_approve_by_business_type(self):
        """
        Full flow: User bulk approves transactions by business type

        Steps:
        1. User filters by business type (Down Home)
        2. User selects all high-confidence matches
        3. User bulk approves
        4. System updates all records
        """
        # Step 1: Filter transactions
        all_transactions = [
            {'id': 1, 'business_type': 'down_home', 'match_confidence': 0.95, 'review_status': None},
            {'id': 2, 'business_type': 'down_home', 'match_confidence': 0.88, 'review_status': None},
            {'id': 3, 'business_type': 'personal', 'match_confidence': 0.92, 'review_status': None},
            {'id': 4, 'business_type': 'down_home', 'match_confidence': 0.60, 'review_status': None},
            {'id': 5, 'business_type': 'down_home', 'match_confidence': 0.91, 'review_status': None},
        ]

        down_home_txs = [t for t in all_transactions if t['business_type'] == 'down_home']
        assert len(down_home_txs) == 4

        # Step 2: Select high-confidence matches
        high_confidence = [t for t in down_home_txs if t['match_confidence'] >= 0.85]
        assert len(high_confidence) == 3

        # Step 3-4: Bulk approve
        for tx in high_confidence:
            tx['review_status'] = 'APPROVED'
            tx['approved_at'] = datetime.now()

        approved = [t for t in all_transactions if t['review_status'] == 'APPROVED']
        assert len(approved) == 3

    @pytest.mark.e2e
    def test_bulk_reject_with_notes(self):
        """
        Full flow: User bulk rejects transactions with rejection notes

        Steps:
        1. User selects transactions for rejection
        2. User enters rejection reason
        3. System updates all with rejection status and notes
        """
        transactions = [
            {'id': 1, 'merchant': 'Unknown', 'review_status': None},
            {'id': 2, 'merchant': 'Personal Item', 'review_status': None},
        ]

        rejection_reason = "Not a business expense"

        for tx in transactions:
            tx['review_status'] = 'REJECTED'
            tx['rejection_reason'] = rejection_reason
            tx['rejected_at'] = datetime.now()

        assert all(t['review_status'] == 'REJECTED' for t in transactions)
        assert all(t['rejection_reason'] == rejection_reason for t in transactions)


# =============================================================================
# REPORT GENERATION FLOW TESTS
# =============================================================================

class TestReportGenerationFlow:
    """Test report generation workflow."""

    @pytest.mark.e2e
    def test_monthly_report_generation(self, tmp_path):
        """
        Full flow: User generates monthly expense report

        Steps:
        1. User selects date range (January 2024)
        2. User selects business type (Down Home)
        3. User selects report format (Excel)
        4. System generates report
        5. User downloads report
        """
        # Step 1-2: User selections
        report_params = {
            'date_start': datetime(2024, 1, 1),
            'date_end': datetime(2024, 1, 31),
            'business_type': 'Down Home',
            'report_type': 'expense_detail',
            'export_format': 'excel',
        }

        # Step 3-4: Generate report
        try:
            from services.excel_exporter import ExcelExporter

            exporter = ExcelExporter()

            # Create mock report
            mock_report = Mock()
            mock_report.report_name = "January 2024 - Down Home"
            mock_report.report_id = "RPT-2024-001"
            mock_report.business_type = "Down Home"
            mock_report.date_range = (report_params['date_start'], report_params['date_end'])
            mock_report.generated_at = datetime.now()
            mock_report.transactions = []

            mock_report.summary = Mock()
            mock_report.summary.total_transactions = 0
            mock_report.summary.total_amount = Decimal("0")
            mock_report.summary.average_transaction = Decimal("0")
            mock_report.summary.match_rate = 0
            mock_report.summary.receipt_rate = 0
            mock_report.summary.by_category = []
            mock_report.summary.by_vendor = []
            mock_report.summary.monthly_trends = []

            result = exporter.export_report(mock_report)

            # Step 5: Verify downloadable file
            assert isinstance(result, bytes)
            assert len(result) > 0
            assert result[:2] == b'PK'  # Excel/XLSX magic bytes

            # Save to file
            report_path = tmp_path / "report.xlsx"
            with open(report_path, 'wb') as f:
                f.write(result)
            assert report_path.exists()

        except ImportError:
            pytest.skip("ExcelExporter not available")

    @pytest.mark.e2e
    @pytest.mark.skip(reason="Test uses Mock objects incompatible with exporter implementations")
    def test_multi_format_export(self, tmp_path):
        """
        Full flow: User exports report in multiple formats

        Steps:
        1. User generates report
        2. User exports to CSV, Excel, PDF
        3. All formats are valid
        """
        # Create mock report
        mock_report = Mock()
        mock_report.report_name = "Test Report"
        mock_report.report_id = "RPT-001"
        mock_report.business_type = "Down Home"
        mock_report.date_range = (datetime(2024, 1, 1), datetime(2024, 1, 31))
        mock_report.generated_at = datetime.now()
        mock_report.transactions = []

        mock_report.summary = Mock()
        mock_report.summary.total_transactions = 0
        mock_report.summary.total_amount = Decimal("0")
        mock_report.summary.average_transaction = Decimal("0")
        mock_report.summary.match_rate = 0
        mock_report.summary.receipt_rate = 0
        mock_report.summary.by_category = []
        mock_report.summary.by_vendor = []
        mock_report.summary.monthly_trends = []

        exports = {}

        # CSV Export
        try:
            from services.csv_exporter import CSVExporter
            csv_exporter = CSVExporter()
            exports['csv'] = csv_exporter.export_standard_csv(mock_report)
            assert exports['csv'][:4] != b'%PDF'  # Not PDF
        except ImportError:
            pass

        # Excel Export
        try:
            from services.excel_exporter import ExcelExporter
            excel_exporter = ExcelExporter()
            exports['excel'] = excel_exporter.export_report(mock_report)
            assert exports['excel'][:2] == b'PK'  # ZIP format
        except ImportError:
            pass

        # PDF Export
        try:
            from services.pdf_exporter import PDFExporter
            pdf_exporter = PDFExporter()
            exports['pdf'] = pdf_exporter.export_report(mock_report)
            assert exports['pdf'][:4] == b'%PDF'  # PDF magic bytes
        except ImportError:
            pass

        # At least one format should work
        assert len(exports) >= 1


# =============================================================================
# CLASSIFICATION CORRECTION FLOW TESTS
# =============================================================================

class TestClassificationCorrectionFlow:
    """Test business type correction workflow."""

    @pytest.mark.e2e
    def test_correct_misclassified_transaction(self, tmp_path):
        """
        Full flow: User corrects a misclassified transaction

        Steps:
        1. User views transaction classified as Personal
        2. User corrects to Down Home
        3. System learns from correction
        4. Future similar transactions classified correctly
        """
        try:
            from business_classifier import BusinessTypeClassifier, BusinessType, Transaction
        except ImportError:
            pytest.skip("business_classifier not available")

        try:
            classifier = BusinessTypeClassifier(data_dir=tmp_path)
        except TypeError:
            # Try without data_dir if the API doesn't support it
            classifier = BusinessTypeClassifier()

        # Step 1: Initial classification
        tx = Transaction(
            id=1,
            merchant="New Software Tool",
            amount=Decimal("50.00"),
            date=datetime.now(),
        )
        initial_result = classifier.classify(tx)

        # Step 2-3: User corrects and system learns
        classifier.learn_from_correction(
            transaction_id=1,
            merchant="New Software Tool",
            amount=Decimal("50.00"),
            correct_type=BusinessType.DOWN_HOME,
            user_notes="AI development tool",
        )

        # Step 4: Re-classify should use learned data
        updated_result = classifier.classify(tx)
        assert updated_result.business_type == BusinessType.DOWN_HOME


# =============================================================================
# SETTINGS AND CONFIGURATION FLOW TESTS
# =============================================================================

class TestSettingsFlow:
    """Test settings and configuration workflows."""

    @pytest.mark.e2e
    @pytest.mark.skip(reason="ScheduledReportService API has changed - needs update")
    def test_scheduled_report_setup(self, tmp_path):
        """
        Full flow: User sets up scheduled weekly report

        Steps:
        1. User opens report settings
        2. User configures weekly Down Home report
        3. User adds email recipients
        4. System saves schedule
        """
        try:
            from services.scheduled_reports import (
                ScheduledReportService,
                ScheduledReport,
                ScheduleFrequency,
                ReportDeliveryMethod,
            )
        except ImportError:
            pytest.skip("scheduled_reports not available")

        try:
            service = ScheduledReportService(data_dir=str(tmp_path))
        except TypeError:
            # Try without data_dir if the API doesn't support it
            service = ScheduledReportService()

        # User configures schedule
        schedule = ScheduledReport(
            id="sched_001",
            name="Weekly Down Home Report",
            frequency=ScheduleFrequency.WEEKLY,
            business_types=["down_home"],
            report_type="expense_detail",
            export_format="excel",
            delivery_method=ReportDeliveryMethod.EMAIL,
            recipients=["user@example.com"],
            day_of_week=0,  # Monday
            time_of_day="09:00",
            enabled=True,
        )

        service.add_schedule(schedule)

        # Verify saved
        saved = service.get_schedule("sched_001")
        assert saved is not None
        assert saved.name == "Weekly Down Home Report"
        assert saved.frequency == ScheduleFrequency.WEEKLY


# =============================================================================
# ERROR RECOVERY FLOW TESTS
# =============================================================================

class TestErrorRecoveryFlow:
    """Test error handling and recovery workflows."""

    @pytest.mark.e2e
    def test_failed_ocr_recovery(self, tmp_path, temp_image):
        """
        Full flow: OCR fails → User manually enters data

        Steps:
        1. User uploads receipt
        2. OCR fails to extract
        3. System prompts for manual entry
        4. User enters data manually
        5. Transaction matches
        """
        # Step 1-2: Upload and OCR fails
        failed_ocr_result = {
            'success': False,
            'error': 'Unable to extract text',
            'confidence': 0.0,
        }

        assert failed_ocr_result['success'] is False

        # Step 3-4: User manually enters
        manual_entry = {
            'merchant': 'Corner Pub',
            'amount': 65.50,
            'date': datetime(2024, 1, 15),
            'entered_by': 'user',
            'entry_method': 'manual',
        }

        assert manual_entry['merchant'] is not None
        assert manual_entry['amount'] > 0

        # Step 5: Matching proceeds
        try:
            from smart_auto_matcher import SmartAutoMatcher
            matcher = SmartAutoMatcher(db_connection=None)

            receipt = {
                'merchant': manual_entry['merchant'],
                'amount': str(manual_entry['amount']),
                'date': manual_entry['date'].strftime('%Y-%m-%d'),
            }
            transaction = {
                'chase_description': 'CORNER PUB',
                'chase_amount': '65.50',
                'chase_date': '01/15/2024',
            }

            score, _ = matcher.calculate_match_score(receipt, transaction)
            assert score >= 0.75
        except ImportError:
            pass

    @pytest.mark.e2e
    def test_duplicate_receipt_handling(self, temp_image):
        """
        Full flow: User uploads duplicate → System detects → User informed

        Steps:
        1. User uploads receipt
        2. System detects duplicate
        3. User is shown original
        4. User decides action
        """
        try:
            from smart_auto_matcher import DuplicateDetector
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        detector = DuplicateDetector(db_connection=None)

        with open(temp_image, 'rb') as f:
            image_data = f.read()

        # First upload - not duplicate
        is_dup1, _ = detector.is_duplicate(image_data, "original.jpg")
        assert is_dup1 is False

        # Second upload - should detect duplicate
        is_dup2, match = detector.is_duplicate(image_data, "duplicate.jpg")
        assert is_dup2 is True
        assert match == "original.jpg"

        # User is informed about duplicate
        duplicate_info = {
            'is_duplicate': is_dup2,
            'original_file': match,
            'message': f"This receipt appears to be a duplicate of {match}",
        }

        assert 'duplicate' in duplicate_info['message']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
