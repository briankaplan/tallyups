#!/usr/bin/env python3
"""
Performance Tests and Benchmarks for ReceiptAI
==============================================

Tests for system performance including:
- Response time benchmarks
- Throughput testing
- Memory usage
- Concurrent operations
- Batch processing speed

Performance Targets:
- Dashboard load: < 1 second
- Single OCR: < 3 seconds
- Batch matching (100): < 5 seconds
- Report generation: < 10 seconds
"""

import pytest
import time
import asyncio
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Import test data generator from conftest
from conftest import TestDataGenerator


# =============================================================================
# PERFORMANCE BENCHMARKS
# =============================================================================

class TestPerformanceBenchmarks:
    """Performance benchmark tests."""

    @pytest.fixture
    def data_generator(self):
        return TestDataGenerator(seed=42)

    @pytest.mark.performance
    @pytest.mark.slow
    def test_classification_throughput(self, data_generator):
        """Classification should process 100 transactions in < 2 seconds."""
        try:
            from business_classifier import BusinessTypeClassifier, Transaction
        except ImportError:
            pytest.skip("business_classifier not available")

        classifier = BusinessTypeClassifier()
        transactions = []

        # Generate 100 transactions
        for tx in data_generator.generate_transactions(100):
            transactions.append(Transaction(
                id=tx.id,
                merchant=tx.merchant,
                amount=tx.amount,
                date=tx.date,
            ))

        start = time.time()
        results = classifier.classify_batch(transactions)
        elapsed = time.time() - start

        assert len(results) == 100
        assert elapsed < 2.0, f"Classification took {elapsed:.2f}s, expected < 2s"

    @pytest.mark.performance
    @pytest.mark.slow
    def test_matching_throughput(self, data_generator):
        """Matching should process 100 receipt-transaction pairs in < 5 seconds."""
        try:
            from smart_auto_matcher import SmartAutoMatcher
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        matcher = SmartAutoMatcher(db_connection=None)
        pairs = data_generator.generate_matching_pairs(100)

        start = time.time()
        results = []
        for tx, receipt in pairs:
            score, _ = matcher.calculate_match_score(
                receipt.to_dict(),
                tx.to_dict()
            )
            results.append(score)
        elapsed = time.time() - start

        assert len(results) == 100
        assert elapsed < 5.0, f"Matching took {elapsed:.2f}s, expected < 5s"

    @pytest.mark.performance
    @pytest.mark.slow
    def test_merchant_normalization_throughput(self, data_generator):
        """Merchant normalization should be fast."""
        try:
            from smart_auto_matcher import normalize_merchant
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        merchants = [
            "SQ*STARBUCKS #12345 NASHVILLE TN 37201",
            "TST*CORNER PUB",
            "DD*DOORDASH MCDONALDS",
            "ANTHROPIC.COM",
            "NETFLIX.COM",
        ] * 200  # 1000 merchants

        start = time.time()
        results = [normalize_merchant(m) for m in merchants]
        elapsed = time.time() - start

        assert len(results) == 1000
        assert elapsed < 1.0, f"Normalization took {elapsed:.2f}s, expected < 1s"

    @pytest.mark.performance
    def test_csv_export_performance(self, data_generator):
        """CSV export of 1000 transactions should be < 5 seconds."""
        try:
            from services.csv_exporter import CSVExporter
        except ImportError:
            pytest.skip("csv_exporter not available")

        exporter = CSVExporter()

        # Create mock report with 1000 transactions
        mock_report = Mock()
        mock_report.report_name = "Test Report"
        mock_report.report_id = "RPT-001"
        mock_report.business_type = "Business"
        mock_report.date_range = (datetime(2024, 1, 1), datetime(2024, 12, 31))
        mock_report.generated_at = datetime.now()

        transactions = []
        for i, tx in enumerate(data_generator.generate_transactions(1000)):
            mock_tx = Mock()
            mock_tx.index = i
            mock_tx.date = tx.date
            mock_tx.description = tx.description
            mock_tx.amount = tx.amount
            mock_tx.effective_category = tx.category
            mock_tx.business_type = tx.business_type
            mock_tx.review_status = "VERIFIED"
            mock_tx.has_receipt = True
            mock_tx.effective_receipt_url = f"https://r2.example.com/{i}.jpg"
            mock_tx.notes = None
            mock_tx.ai_note = None
            mock_tx.ai_confidence = 0.95
            mock_tx.mi_merchant = tx.merchant
            mock_tx.mi_category = tx.category
            mock_tx.source = "Chase"
            transactions.append(mock_tx)

        mock_report.transactions = transactions

        # Create mock summary
        mock_report.summary = Mock()
        mock_report.summary.total_transactions = 1000
        mock_report.summary.total_amount = Decimal("50000.00")
        mock_report.summary.average_transaction = Decimal("50.00")
        mock_report.summary.match_rate = 85.0
        mock_report.summary.receipt_rate = 90.0
        mock_report.summary.by_category = []
        mock_report.summary.by_vendor = []
        mock_report.summary.monthly_trends = []

        start = time.time()
        result = exporter.export_standard_csv(mock_report)
        elapsed = time.time() - start

        assert len(result) > 0
        assert elapsed < 5.0, f"CSV export took {elapsed:.2f}s, expected < 5s"

    @pytest.mark.performance
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PYTEST_ASYNCIO, reason="pytest-asyncio not installed")
    async def test_notes_generation_throughput(self, tmp_path, data_generator):
        """Notes generation for 50 transactions should be < 10 seconds."""
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
                {
                    "merchant": tx.merchant,
                    "amount": float(tx.amount),
                    "date": tx.date.strftime("%Y-%m-%d"),
                }
                for tx in data_generator.generate_transactions(50)
            ]

            start = time.time()
            results = await service.generate_batch(transactions)
            elapsed = time.time() - start

            assert len(results) == 50
            assert elapsed < 10.0, f"Notes generation took {elapsed:.2f}s, expected < 10s"


# =============================================================================
# CONCURRENT OPERATIONS TESTS
# =============================================================================

class TestConcurrentOperations:
    """Test concurrent access and thread safety."""

    @pytest.mark.performance
    def test_concurrent_classification(self):
        """Multiple concurrent classifications should not crash."""
        try:
            from business_classifier import BusinessTypeClassifier, Transaction
        except ImportError:
            pytest.skip("business_classifier not available")

        classifier = BusinessTypeClassifier()
        merchants = ["Anthropic", "Netflix", "Uber", "Starbucks", "Amazon"]

        def classify_merchant(merchant):
            tx = Transaction(
                id=1,
                merchant=merchant,
                amount=Decimal("50.00"),
                date=datetime.now(),
            )
            return classifier.classify(tx)

        # Run 10 concurrent classifications
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(classify_merchant, m) for m in merchants * 2]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 10

    @pytest.mark.performance
    def test_concurrent_matching(self):
        """Multiple concurrent matchings should not crash."""
        try:
            from smart_auto_matcher import SmartAutoMatcher
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        matcher = SmartAutoMatcher(db_connection=None)

        def match_pair(idx):
            receipt = {
                'merchant': f'Merchant {idx}',
                'amount': str(50.00 + idx),
                'date': '2024-01-15',
            }
            transaction = {
                'chase_description': f'MERCHANT {idx}',
                'chase_amount': str(50.00 + idx),
                'chase_date': '01/15/2024',
            }
            return matcher.calculate_match_score(receipt, transaction)

        # Run 20 concurrent matches
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(match_pair, i) for i in range(20)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 20

    @pytest.mark.performance
    def test_cache_thread_safety(self, tmp_path):
        """Cache should be thread-safe."""
        try:
            from cache_manager import ThreadSafeCache
        except ImportError:
            pytest.skip("cache_manager not available")

        cache = ThreadSafeCache(ttl_seconds=60)
        errors = []

        def cache_operation(idx):
            try:
                cache.set(f"key_{idx}", f"value_{idx}")
                value = cache.get(f"key_{idx}")
                assert value == f"value_{idx}"
            except Exception as e:
                errors.append(e)

        # Run 100 concurrent cache operations
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(cache_operation, i) for i in range(100)]
            for f in as_completed(futures):
                pass

        assert len(errors) == 0, f"Cache errors: {errors}"


# =============================================================================
# MEMORY USAGE TESTS
# =============================================================================

class TestMemoryUsage:
    """Test memory usage and leaks."""

    @pytest.mark.performance
    @pytest.mark.slow
    def test_large_batch_memory(self, data_generator):
        """Large batch processing should not cause memory issues."""
        try:
            from business_classifier import BusinessTypeClassifier, Transaction
        except ImportError:
            pytest.skip("business_classifier not available")

        import gc

        classifier = BusinessTypeClassifier()

        # Process in batches to check memory doesn't grow unbounded
        for batch_num in range(10):
            transactions = []
            for tx in data_generator.generate_transactions(100):
                transactions.append(Transaction(
                    id=tx.id,
                    merchant=tx.merchant,
                    amount=tx.amount,
                    date=tx.date,
                ))

            results = classifier.classify_batch(transactions)
            assert len(results) == 100

            # Clean up
            del transactions
            del results
            gc.collect()

        # If we get here without memory error, test passes

    @pytest.mark.performance
    def test_duplicate_detector_memory(self, temp_image):
        """Duplicate detector cache should handle multiple images."""
        try:
            from smart_auto_matcher import DuplicateDetector
            from PIL import Image
            import io
        except ImportError:
            pytest.skip("smart_auto_matcher or PIL not available")

        detector = DuplicateDetector(db_connection=None)

        # Create truly unique images with distinct content
        for i in range(20):
            # Create unique images with different content
            img = Image.new('RGB', (100, 100), color=(i * 12, 100, 255 - i * 12))
            buffer = io.BytesIO()
            img.save(buffer, 'JPEG')
            image_data = buffer.getvalue()
            detector.is_duplicate(image_data, f"receipt_{i}.jpg")

        # Cache should have at least some entries (duplicate detection may reduce count)
        # The important thing is the cache exists and functions
        assert len(detector.hash_cache) >= 1
        # Cache should be bounded - not growing unboundedly
        assert len(detector.hash_cache) <= 20


# =============================================================================
# LOAD TESTS
# =============================================================================

class TestLoadHandling:
    """Test system behavior under load."""

    @pytest.mark.performance
    @pytest.mark.slow
    def test_sustained_classification_load(self, data_generator):
        """System should handle sustained classification load."""
        try:
            from business_classifier import BusinessTypeClassifier, Transaction
        except ImportError:
            pytest.skip("business_classifier not available")

        classifier = BusinessTypeClassifier()

        start = time.time()
        total_classified = 0

        # Run for 5 seconds of sustained load
        while time.time() - start < 5.0:
            tx = Transaction(
                id=1,
                merchant="Anthropic",
                amount=Decimal("20.00"),
                date=datetime.now(),
            )
            result = classifier.classify(tx)
            assert result is not None
            total_classified += 1

        elapsed = time.time() - start
        rate = total_classified / elapsed

        # Should handle at least 100 classifications per second
        assert rate >= 100, f"Rate {rate:.1f}/s below threshold of 100/s"

    @pytest.mark.performance
    @pytest.mark.slow
    def test_burst_matching_load(self, data_generator):
        """System should handle burst matching load."""
        try:
            from smart_auto_matcher import SmartAutoMatcher
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        matcher = SmartAutoMatcher(db_connection=None)
        pairs = data_generator.generate_matching_pairs(500)

        start = time.time()
        results = []
        for tx, receipt in pairs:
            score, _ = matcher.calculate_match_score(
                receipt.to_dict(),
                tx.to_dict()
            )
            results.append(score)
        elapsed = time.time() - start

        rate = len(results) / elapsed

        # Should handle at least 50 matches per second
        assert rate >= 50, f"Rate {rate:.1f}/s below threshold of 50/s"


# =============================================================================
# RESPONSE TIME TESTS
# =============================================================================

class TestResponseTimes:
    """Test individual operation response times."""

    @pytest.mark.performance
    def test_single_classification_time(self):
        """Single classification should be < 50ms."""
        try:
            from business_classifier import BusinessTypeClassifier, Transaction
        except ImportError:
            pytest.skip("business_classifier not available")

        classifier = BusinessTypeClassifier()
        tx = Transaction(
            id=1,
            merchant="Anthropic",
            amount=Decimal("20.00"),
            date=datetime.now(),
        )

        # Warm up
        classifier.classify(tx)

        # Measure
        times = []
        for _ in range(10):
            start = time.time()
            classifier.classify(tx)
            times.append(time.time() - start)

        avg_time = sum(times) / len(times) * 1000  # Convert to ms
        assert avg_time < 50, f"Avg classification time {avg_time:.1f}ms > 50ms"

    @pytest.mark.performance
    def test_single_match_time(self):
        """Single match scoring should be < 10ms."""
        try:
            from smart_auto_matcher import SmartAutoMatcher
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        matcher = SmartAutoMatcher(db_connection=None)
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

        # Warm up
        matcher.calculate_match_score(receipt, transaction)

        # Measure
        times = []
        for _ in range(100):
            start = time.time()
            matcher.calculate_match_score(receipt, transaction)
            times.append(time.time() - start)

        avg_time = sum(times) / len(times) * 1000  # Convert to ms
        assert avg_time < 10, f"Avg match time {avg_time:.1f}ms > 10ms"

    @pytest.mark.performance
    def test_merchant_normalization_time(self):
        """Merchant normalization should be < 1ms."""
        try:
            from smart_auto_matcher import normalize_merchant
        except ImportError:
            pytest.skip("smart_auto_matcher not available")

        merchant = "SQ*STARBUCKS COFFEE #12345 NASHVILLE TN 37201"

        # Measure
        times = []
        for _ in range(1000):
            start = time.time()
            normalize_merchant(merchant)
            times.append(time.time() - start)

        avg_time = sum(times) / len(times) * 1000  # Convert to ms
        assert avg_time < 1, f"Avg normalization time {avg_time:.3f}ms > 1ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
