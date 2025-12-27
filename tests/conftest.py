#!/usr/bin/env python3
"""
ReceiptAI Test Configuration and Fixtures
==========================================

Provides shared fixtures, mock objects, and test utilities for the entire test suite.
"""

import os
import sys
import json
import pytest
import asyncio
import tempfile
import shutil
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from dataclasses import dataclass, field
import hashlib

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import application modules
try:
    from business_classifier import (
        BusinessType, BusinessTypeClassifier, Transaction as ClassifierTransaction,
        Receipt as ClassifierReceipt, ClassificationResult, ClassificationSignal,
        CalendarEvent as ClassifierCalendarEvent, Contact as ClassifierContact,
    )
except ImportError:
    BusinessType = None
    BusinessTypeClassifier = None

try:
    from smart_auto_matcher import (
        SmartAutoMatcher, DuplicateDetector,
        normalize_merchant, parse_amount, parse_date,
        calculate_amount_score, calculate_merchant_score, calculate_date_score,
        compute_image_hash, compute_content_hash, hamming_distance, are_images_similar,
    )
except ImportError:
    SmartAutoMatcher = None

try:
    from services.smart_notes_service import (
        SmartNotesService, Contact, CalendarEvent, ReceiptData,
        TransactionContext, NoteResult, ContextCache, NoteLearningSystem,
    )
except ImportError:
    SmartNotesService = None

try:
    from services.report_generator import (
        ExpenseReportGenerator, Report, Transaction, ReportSummary,
    )
except ImportError:
    ExpenseReportGenerator = None

try:
    from services.csv_exporter import CSVExporter, get_csv_exporter
except ImportError:
    CSVExporter = None

try:
    from services.excel_exporter import ExcelExporter, get_excel_exporter
except ImportError:
    ExcelExporter = None

try:
    from services.pdf_exporter import PDFExporter, get_pdf_exporter
except ImportError:
    PDFExporter = None


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Register custom markers
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "data_quality: Data quality tests")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "requires_db: Requires database")
    config.addinivalue_line("markers", "requires_api: Requires external API")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on location."""
    for item in items:
        # Auto-mark based on file location
        if "test_unit_" in item.nodeid or "/unit/" in item.nodeid:
            item.add_marker(pytest.mark.unit)
        elif "test_integration_" in item.nodeid or "/integration/" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        elif "test_e2e_" in item.nodeid or "/e2e/" in item.nodeid:
            item.add_marker(pytest.mark.e2e)
        elif "test_performance_" in item.nodeid or "/performance/" in item.nodeid:
            item.add_marker(pytest.mark.performance)


# =============================================================================
# TEST DATA GENERATORS
# =============================================================================

@dataclass
class TestTransaction:
    """Test transaction data structure."""
    id: int
    merchant: str
    amount: Decimal
    date: datetime
    description: Optional[str] = None
    category: Optional[str] = None
    business_type: Optional[str] = None
    chase_description: Optional[str] = None
    chase_amount: Optional[str] = None
    chase_date: Optional[str] = None
    receipt_url: Optional[str] = None
    review_status: Optional[str] = None
    ai_confidence: Optional[float] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'merchant': self.merchant,
            'amount': float(self.amount),
            'date': self.date.strftime('%Y-%m-%d') if self.date else None,
            'description': self.description or self.merchant,
            'category': self.category,
            'business_type': self.business_type,
            'chase_description': self.chase_description or self.merchant,
            'chase_amount': self.chase_amount or str(self.amount),
            'chase_date': self.chase_date or (self.date.strftime('%m/%d/%Y') if self.date else None),
            'receipt_url': self.receipt_url,
            'review_status': self.review_status,
            'ai_confidence': self.ai_confidence,
        }


@dataclass
class TestReceipt:
    """Test receipt data structure."""
    id: int
    merchant: str
    amount: Decimal
    date: Optional[datetime] = None
    filename: Optional[str] = None
    r2_url: Optional[str] = None
    email_from: Optional[str] = None
    email_subject: Optional[str] = None
    raw_text: Optional[str] = None
    items: Optional[List[Dict]] = None
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    tip: Optional[Decimal] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'merchant': self.merchant,
            'amount': float(self.amount),
            'date': self.date.strftime('%Y-%m-%d') if self.date else None,
            'transaction_date': self.date.strftime('%Y-%m-%d') if self.date else None,
            'filename': self.filename,
            'r2_url': self.r2_url,
            'email_from': self.email_from,
            'email_subject': self.email_subject,
            'raw_text': self.raw_text,
            'items': self.items,
            'subtotal': float(self.subtotal) if self.subtotal else None,
            'tax': float(self.tax) if self.tax else None,
            'tip': float(self.tip) if self.tip else None,
        }


class TestDataGenerator:
    """Generate realistic test data for ReceiptAI tests."""

    # Known merchants by business type
    MERCHANTS = {
        'business': [
            ('Anthropic', 20.00),
            ('OpenAI', 20.00),
            ('Midjourney', 30.00),
            ('Cursor', 20.00),
            ('Railway', 20.00),
            ('Cloudflare', 25.00),
            ('GitHub', 7.00),
            ('Figma', 15.00),
            ('Soho House Nashville', 150.00),
            ('Corner Pub', 45.00),
            ('12 South Taproom', 65.00),
        ],
        'secondary': [
            ('Bridgestone Arena', 500.00),
            ('Cambria Hotel Nashville', 189.00),
            ('Hattie Bs', 35.00),
            ('Hive', 25.00),
            ('EasyFAQ', 50.00),
        ],
        'personal': [
            ('Apple', 1299.00),
            ('Amazon', 45.00),
            ('Netflix', 15.99),
            ('Spotify', 10.99),
            ('Nordstrom', 250.00),
            ('Southwest Airlines', 350.00),
            ('Suitsupply', 500.00),
        ],
        'em_co': [
            ('Getty Images', 30.00),
            ('Shutterstock', 50.00),
            ('Adobe Stock', 80.00),
        ],
    }

    CATEGORIES = [
        'Travel - Airfare',
        'Travel - Hotel',
        'Travel - Ground Transport',
        'Travel - Meals',
        'Business Development - Meals',
        'Software & Subscriptions',
        'Office Supplies',
        'Marketing & Advertising',
        'Company Meetings',
    ]

    def __init__(self, seed: int = 42):
        """Initialize generator with seed for reproducibility."""
        import random
        self.rng = random.Random(seed)
        self._tx_counter = 0
        self._receipt_counter = 0

    def generate_transaction(
        self,
        merchant: Optional[str] = None,
        amount: Optional[float] = None,
        business_type: Optional[str] = None,
        date: Optional[datetime] = None,
        **kwargs
    ) -> TestTransaction:
        """Generate a single transaction."""
        self._tx_counter += 1

        # Select business type
        if business_type is None:
            business_type = self.rng.choice(list(self.MERCHANTS.keys()))

        # Select merchant
        if merchant is None:
            merchant_data = self.rng.choice(self.MERCHANTS.get(business_type, self.MERCHANTS['business']))
            merchant = merchant_data[0]
            if amount is None:
                amount = merchant_data[1]

        if amount is None:
            amount = self.rng.uniform(10.0, 500.0)

        if date is None:
            days_ago = self.rng.randint(0, 90)
            date = datetime.now() - timedelta(days=days_ago)

        return TestTransaction(
            id=self._tx_counter,
            merchant=merchant,
            amount=Decimal(str(round(amount, 2))),
            date=date,
            description=kwargs.get('description', merchant),
            category=kwargs.get('category', self.rng.choice(self.CATEGORIES)),
            business_type=business_type,
            chase_description=kwargs.get('chase_description', merchant.upper()),
            chase_amount=kwargs.get('chase_amount'),
            chase_date=kwargs.get('chase_date'),
            receipt_url=kwargs.get('receipt_url'),
            review_status=kwargs.get('review_status'),
            ai_confidence=kwargs.get('ai_confidence'),
        )

    def generate_transactions(self, count: int, **kwargs) -> List[TestTransaction]:
        """Generate multiple transactions."""
        return [self.generate_transaction(**kwargs) for _ in range(count)]

    def generate_receipt(
        self,
        merchant: Optional[str] = None,
        amount: Optional[float] = None,
        date: Optional[datetime] = None,
        **kwargs
    ) -> TestReceipt:
        """Generate a single receipt."""
        self._receipt_counter += 1

        if merchant is None:
            all_merchants = []
            for merchants in self.MERCHANTS.values():
                all_merchants.extend(merchants)
            merchant_data = self.rng.choice(all_merchants)
            merchant = merchant_data[0]
            if amount is None:
                amount = merchant_data[1]

        if amount is None:
            amount = self.rng.uniform(10.0, 500.0)

        if date is None:
            days_ago = self.rng.randint(0, 90)
            date = datetime.now() - timedelta(days=days_ago)

        # Generate subtotals
        subtotal = round(amount * 0.92, 2)
        tax = round(amount * 0.08, 2)

        return TestReceipt(
            id=self._receipt_counter,
            merchant=merchant,
            amount=Decimal(str(round(amount, 2))),
            date=date,
            filename=kwargs.get('filename', f"receipt_{self._receipt_counter}.jpg"),
            r2_url=kwargs.get('r2_url', f"https://r2.example.com/receipts/receipt_{self._receipt_counter}.jpg"),
            email_from=kwargs.get('email_from'),
            email_subject=kwargs.get('email_subject', f"Your receipt from {merchant}"),
            raw_text=kwargs.get('raw_text', f"{merchant}\nTotal: ${amount:.2f}"),
            items=kwargs.get('items'),
            subtotal=Decimal(str(subtotal)),
            tax=Decimal(str(tax)),
            tip=kwargs.get('tip'),
        )

    def generate_receipts(self, count: int, **kwargs) -> List[TestReceipt]:
        """Generate multiple receipts."""
        return [self.generate_receipt(**kwargs) for _ in range(count)]

    def generate_matching_pair(
        self,
        merchant: Optional[str] = None,
        amount: Optional[float] = None,
        date: Optional[datetime] = None,
        date_drift_days: int = 0,
        tip_percentage: float = 0.0,
    ) -> tuple:
        """Generate a transaction-receipt pair that should match."""
        if date is None:
            date = datetime.now() - timedelta(days=self.rng.randint(1, 30))

        receipt = self.generate_receipt(
            merchant=merchant,
            amount=amount,
            date=date,
        )

        # Calculate transaction amount (receipt + tip)
        tx_amount = float(receipt.amount)
        if tip_percentage > 0:
            tx_amount = tx_amount * (1 + tip_percentage)

        # Transaction date may drift (posting delay)
        tx_date = date + timedelta(days=date_drift_days)

        tx = self.generate_transaction(
            merchant=merchant or receipt.merchant,
            amount=tx_amount,
            date=tx_date,
        )

        return tx, receipt

    def generate_matching_pairs(
        self,
        count: int,
        include_variations: bool = True,
    ) -> List[tuple]:
        """Generate multiple matching transaction-receipt pairs with variations."""
        pairs = []

        for i in range(count):
            if include_variations:
                # Vary the matching conditions
                variation = i % 5
                if variation == 0:
                    # Exact match
                    pairs.append(self.generate_matching_pair())
                elif variation == 1:
                    # With tip
                    pairs.append(self.generate_matching_pair(tip_percentage=0.20))
                elif variation == 2:
                    # With date drift
                    pairs.append(self.generate_matching_pair(date_drift_days=2))
                elif variation == 3:
                    # With tip and date drift
                    pairs.append(self.generate_matching_pair(tip_percentage=0.15, date_drift_days=1))
                else:
                    # Random variation
                    pairs.append(self.generate_matching_pair(
                        tip_percentage=self.rng.uniform(0, 0.25),
                        date_drift_days=self.rng.randint(0, 3),
                    ))
            else:
                pairs.append(self.generate_matching_pair())

        return pairs


# =============================================================================
# FIXTURES - Database
# =============================================================================

@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary SQLite database path."""
    return str(tmp_path / "test_receipts.db")


@pytest.fixture
def mock_mysql_connection():
    """Create a mock MySQL connection."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.lastrowid = 1
    cursor.rowcount = 1
    return conn


@pytest.fixture
def mock_db_pool():
    """Create a mock database connection pool."""
    pool = MagicMock()
    conn = MagicMock()
    pool.get_connection.return_value = conn
    return pool


# =============================================================================
# FIXTURES - Test Data
# =============================================================================

@pytest.fixture
def data_generator():
    """Create a test data generator."""
    return TestDataGenerator(seed=42)


@pytest.fixture
def sample_transactions(data_generator):
    """Generate sample transactions."""
    return data_generator.generate_transactions(20)


@pytest.fixture
def sample_receipts(data_generator):
    """Generate sample receipts."""
    return data_generator.generate_receipts(20)


@pytest.fixture
def matching_pairs(data_generator):
    """Generate matching transaction-receipt pairs."""
    return data_generator.generate_matching_pairs(10)


@pytest.fixture
def sample_transaction():
    """Single sample transaction."""
    return TestTransaction(
        id=1,
        merchant="Anthropic",
        amount=Decimal("20.00"),
        date=datetime(2024, 1, 15, 12, 0),
        description="Anthropic subscription",
        category="Software & Subscriptions",
        business_type="business",
    )


@pytest.fixture
def sample_receipt():
    """Single sample receipt."""
    return TestReceipt(
        id=1,
        merchant="Anthropic",
        amount=Decimal("20.00"),
        date=datetime(2024, 1, 15),
        filename="anthropic_receipt.jpg",
        r2_url="https://r2.example.com/receipts/anthropic_receipt.jpg",
        email_from="billing@anthropic.com",
        email_subject="Your Anthropic receipt",
        raw_text="Anthropic\nClaude Pro\nTotal: $20.00",
    )


# =============================================================================
# FIXTURES - Business Classifier
# =============================================================================

@pytest.fixture
def classifier():
    """Create a business classifier instance."""
    if BusinessTypeClassifier is None:
        pytest.skip("BusinessTypeClassifier not available")
    return BusinessTypeClassifier()


@pytest.fixture
def classifier_transaction():
    """Create a classifier Transaction instance."""
    if ClassifierTransaction is None:
        pytest.skip("Classifier Transaction not available")
    return ClassifierTransaction(
        id=1,
        merchant="Anthropic",
        amount=Decimal("20.00"),
        date=datetime.now(),
    )


# =============================================================================
# FIXTURES - Smart Matcher
# =============================================================================

@pytest.fixture
def matcher(mock_mysql_connection):
    """Create a smart matcher instance."""
    if SmartAutoMatcher is None:
        pytest.skip("SmartAutoMatcher not available")
    return SmartAutoMatcher(db_connection=mock_mysql_connection)


@pytest.fixture
def duplicate_detector(mock_mysql_connection):
    """Create a duplicate detector instance."""
    if DuplicateDetector is None:
        pytest.skip("DuplicateDetector not available")
    return DuplicateDetector(db_connection=mock_mysql_connection)


# =============================================================================
# FIXTURES - Smart Notes Service
# =============================================================================

@pytest.fixture
def notes_service(tmp_path):
    """Create a smart notes service instance with mocked dependencies."""
    if SmartNotesService is None:
        pytest.skip("SmartNotesService not available")

    with patch.object(SmartNotesService, '_load_contacts_cache'):
        service = SmartNotesService(credentials_dir=str(tmp_path))
        service.claude_client = None  # Test fallback behavior
        service.calendar_client = MagicMock()
        service.calendar_client.get_events_around_time = Mock(return_value=[])
        service.contacts_client = MagicMock()
        service.contacts_client.get_all_contacts = Mock(return_value=[])
        return service


@pytest.fixture
def context_cache(tmp_path):
    """Create a context cache instance."""
    if ContextCache is None:
        pytest.skip("ContextCache not available")
    return ContextCache(cache_dir=tmp_path, ttl_seconds=3600)


# =============================================================================
# FIXTURES - Report Generation
# =============================================================================

@pytest.fixture
def report_generator(sample_transactions):
    """Create a report generator instance."""
    if ExpenseReportGenerator is None:
        pytest.skip("ExpenseReportGenerator not available")
    # Convert test transactions to the format expected by generator
    return ExpenseReportGenerator()


@pytest.fixture
def csv_exporter():
    """Create a CSV exporter instance."""
    if CSVExporter is None:
        pytest.skip("CSVExporter not available")
    return CSVExporter()


@pytest.fixture
def excel_exporter():
    """Create an Excel exporter instance."""
    if ExcelExporter is None:
        pytest.skip("ExcelExporter not available")
    return ExcelExporter()


@pytest.fixture
def pdf_exporter():
    """Create a PDF exporter instance."""
    if PDFExporter is None:
        pytest.skip("PDFExporter not available")
    return PDFExporter()


# =============================================================================
# FIXTURES - External Services (Mocked)
# =============================================================================

@pytest.fixture
def mock_gmail_service():
    """Create a mock Gmail service."""
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        'messages': []
    }
    return service


@pytest.fixture
def mock_calendar_service():
    """Create a mock Google Calendar service."""
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        'items': []
    }
    return service


@pytest.fixture
def mock_r2_client():
    """Create a mock R2/S3 client."""
    client = MagicMock()
    client.upload_file.return_value = True
    client.get_presigned_url.return_value = "https://r2.example.com/test.jpg"
    return client


@pytest.fixture
def mock_openai_client():
    """Create a mock OpenAI client."""
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Test response"
    client.chat.completions.create.return_value = response
    return client


@pytest.fixture
def mock_gemini_client():
    """Create a mock Gemini client."""
    client = MagicMock()
    response = MagicMock()
    response.text = "Test response"
    client.generate_content.return_value = response
    return client


# =============================================================================
# FIXTURES - Flask Test Client
# =============================================================================

@pytest.fixture
def app():
    """Create Flask test application."""
    try:
        # Import and configure the Flask app for testing
        from viewer_server import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['WTF_CSRF_ENABLED'] = False
        return flask_app
    except (ImportError, RuntimeError):
        # RuntimeError raised when MySQL not available in CI
        pytest.skip("Flask app not available (MySQL required)")


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create Flask CLI test runner."""
    return app.test_cli_runner()


# =============================================================================
# FIXTURES - Temporary Files
# =============================================================================

@pytest.fixture
def temp_image(tmp_path):
    """Create a temporary test image."""
    from PIL import Image
    import io

    # Create a simple test image
    img = Image.new('RGB', (100, 100), color='white')
    img_path = tmp_path / "test_receipt.jpg"
    img.save(img_path)

    return img_path


@pytest.fixture
def temp_pdf(tmp_path):
    """Create a temporary test PDF."""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter

        pdf_path = tmp_path / "test_receipt.pdf"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.drawString(100, 750, "Test Receipt")
        c.drawString(100, 700, "Anthropic")
        c.drawString(100, 650, "Total: $20.00")
        c.save()

        return pdf_path
    except ImportError:
        pytest.skip("reportlab not available")


@pytest.fixture
def temp_csv(tmp_path):
    """Create a temporary test CSV file."""
    import csv

    csv_path = tmp_path / "test_transactions.csv"
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Date', 'Merchant', 'Amount', 'Category'])
        writer.writerow(['2024-01-15', 'Anthropic', '20.00', 'Software'])
        writer.writerow(['2024-01-16', 'Uber', '25.00', 'Travel'])

    return csv_path


# =============================================================================
# FIXTURES - Performance Testing
# =============================================================================

@pytest.fixture
def large_transaction_set(data_generator):
    """Generate a large set of transactions for performance testing."""
    return data_generator.generate_transactions(1000)


@pytest.fixture
def large_receipt_set(data_generator):
    """Generate a large set of receipts for performance testing."""
    return data_generator.generate_receipts(1000)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def assert_classification_result(result, expected_type: str, min_confidence: float = 0.8):
    """Assert classification result matches expectations."""
    assert result is not None
    assert result.business_type.value == expected_type or result.business_type.name.lower() == expected_type.lower()
    assert result.confidence >= min_confidence, f"Confidence {result.confidence} below threshold {min_confidence}"


def assert_match_score(score: float, min_score: float = 0.75):
    """Assert match score meets threshold."""
    assert score >= min_score, f"Match score {score} below threshold {min_score}"


def create_test_image_bytes(width: int = 100, height: int = 100, color: str = 'white') -> bytes:
    """Create test image bytes."""
    from PIL import Image
    import io

    img = Image.new('RGB', (width, height), color=color)
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    return buffer.getvalue()


def create_similar_test_images() -> tuple:
    """Create two similar test images for duplicate detection testing."""
    from PIL import Image
    import io

    # Create base image
    img1 = Image.new('RGB', (100, 100), color='white')

    # Create slightly modified image (should be detected as similar)
    img2 = Image.new('RGB', (100, 100), color='white')
    # Add slight variation
    pixels = img2.load()
    for i in range(10):
        pixels[i, i] = (250, 250, 250)  # Slight variation

    buffer1 = io.BytesIO()
    buffer2 = io.BytesIO()
    img1.save(buffer1, format='JPEG')
    img2.save(buffer2, format='JPEG')

    return buffer1.getvalue(), buffer2.getvalue()


# =============================================================================
# ASYNC FIXTURES
# =============================================================================

@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# CLEANUP FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def cleanup_temp_files(tmp_path):
    """Clean up temporary files after each test."""
    yield
    # Cleanup handled automatically by tmp_path
