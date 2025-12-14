#!/usr/bin/env python3
"""
Unit tests for SmartNotesService

Tests the intelligent note generation system that combines:
- Transaction data
- Receipt OCR data
- Calendar events (Google Calendar)
- Contact information (Google Contacts)
- Historical patterns
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from pathlib import Path
import json
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check dependencies
try:
    import numpy
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import pytest_asyncio
    HAS_PYTEST_ASYNCIO = True
except ImportError:
    HAS_PYTEST_ASYNCIO = False

# Skip entire module if dependencies not available
if not HAS_NUMPY or not HAS_PYTEST_ASYNCIO:
    pytest.skip("Required dependencies not installed", allow_module_level=True)

from services.smart_notes_service import (
    Contact,
    CalendarEvent,
    ReceiptData,
    TransactionContext,
    NoteResult,
    ContextCache,
    GoogleCalendarClient,
    GoogleContactsClient,
    NoteLearningSystem,
    SmartNotesService,
    get_merchant_intelligence,
    MERCHANT_INTELLIGENCE,
)


# =============================================================================
# Contact Tests
# =============================================================================

class TestContact:
    """Tests for the Contact dataclass."""

    def test_contact_creation(self):
        """Test basic contact creation."""
        contact = Contact(
            name="Patrick Humes",
            first_name="Patrick",
            last_name="Humes",
            email="patrick@mcr.com",
            company="Music City Rodeo",
            job_title="Co-founder",
            relationship="partner",
        )
        assert contact.name == "Patrick Humes"
        assert contact.company == "Music City Rodeo"
        assert contact.relationship == "partner"

    def test_contact_display_name_with_title_and_company(self):
        """Test display name with job title and company."""
        contact = Contact(
            name="Patrick Humes",
            job_title="Co-founder",
            company="Music City Rodeo",
        )
        display = contact.get_display_name()
        assert "Patrick Humes" in display
        assert "Co-founder" in display
        assert "Music City Rodeo" in display

    def test_contact_display_name_with_company_only(self):
        """Test display name with company only."""
        contact = Contact(
            name="Tim McGraw",
            company="Down Home",
        )
        display = contact.get_display_name()
        assert "Tim McGraw" in display
        assert "Down Home" in display

    def test_contact_display_name_with_relationship(self):
        """Test display name with relationship only."""
        contact = Contact(
            name="John Smith",
            relationship="investor",
        )
        display = contact.get_display_name()
        assert "John Smith" in display
        assert "investor" in display

    def test_contact_display_name_minimal(self):
        """Test display name with minimal info."""
        contact = Contact(first_name="Jane", last_name="Doe")
        display = contact.get_display_name()
        assert "Jane Doe" in display


# =============================================================================
# CalendarEvent Tests
# =============================================================================

class TestCalendarEvent:
    """Tests for the CalendarEvent dataclass."""

    def test_event_creation(self):
        """Test basic event creation."""
        event = CalendarEvent(
            id="event123",
            title="Lunch with Patrick",
            start_time=datetime(2024, 1, 15, 12, 0),
            end_time=datetime(2024, 1, 15, 13, 0),
            attendees=["Patrick Humes", "Tim McGraw"],
        )
        assert event.title == "Lunch with Patrick"
        assert len(event.attendees) == 2

    def test_event_matches_time_within_window(self):
        """Test that event matches when within time window."""
        event = CalendarEvent(
            start_time=datetime(2024, 1, 15, 12, 0),
        )
        transaction_time = datetime(2024, 1, 15, 13, 0)  # 1 hour later
        assert event.matches_time(transaction_time, hours_window=2)

    def test_event_matches_time_outside_window(self):
        """Test that event doesn't match when outside window."""
        event = CalendarEvent(
            start_time=datetime(2024, 1, 15, 12, 0),
        )
        transaction_time = datetime(2024, 1, 15, 18, 0)  # 6 hours later
        assert not event.matches_time(transaction_time, hours_window=2)

    def test_event_matches_time_no_start(self):
        """Test that event without start_time doesn't match."""
        event = CalendarEvent(title="No time event")
        assert not event.matches_time(datetime.now())


# =============================================================================
# NoteResult Tests
# =============================================================================

class TestNoteResult:
    """Tests for the NoteResult dataclass."""

    def test_note_result_creation(self):
        """Test basic note result creation."""
        result = NoteResult(
            note="Business dinner with Patrick Humes",
            confidence=0.85,
            business_purpose="Client development",
            tax_category="Meals & Entertainment",
        )
        assert result.note == "Business dinner with Patrick Humes"
        assert result.confidence == 0.85
        assert not result.needs_review

    def test_note_result_to_dict(self):
        """Test conversion to dictionary."""
        result = NoteResult(
            note="Test note",
            confidence=0.8,
            data_sources=["calendar", "contacts"],
            generated_at=datetime(2024, 1, 15, 12, 0),
        )
        d = result.to_dict()
        assert d["note"] == "Test note"
        assert d["confidence"] == 0.8
        assert "calendar" in d["data_sources"]


# =============================================================================
# ContextCache Tests
# =============================================================================

class TestContextCache:
    """Tests for the ContextCache class."""

    def test_cache_creation(self, tmp_path):
        """Test cache creation."""
        cache = ContextCache(cache_dir=tmp_path, ttl_seconds=3600)
        assert cache.ttl_seconds == 3600

    def test_calendar_cache_set_get(self, tmp_path):
        """Test setting and getting calendar events."""
        cache = ContextCache(cache_dir=tmp_path)

        events = [
            CalendarEvent(id="1", title="Meeting 1"),
            CalendarEvent(id="2", title="Meeting 2"),
        ]

        date = datetime(2024, 1, 15)
        cache.set_calendar_events(date, "test@example.com", events)

        retrieved = cache.get_calendar_events(date, "test@example.com")
        assert len(retrieved) == 2
        assert retrieved[0].title == "Meeting 1"

    def test_calendar_cache_expired(self, tmp_path):
        """Test that expired cache returns None."""
        cache = ContextCache(cache_dir=tmp_path, ttl_seconds=0)  # Immediate expiry

        events = [CalendarEvent(id="1", title="Meeting")]
        date = datetime(2024, 1, 15)
        cache.set_calendar_events(date, "test@example.com", events)

        # Wait a tiny bit for expiry
        import time
        time.sleep(0.01)

        retrieved = cache.get_calendar_events(date, "test@example.com")
        assert retrieved is None

    def test_contact_cache_set_get(self, tmp_path):
        """Test setting and getting contacts."""
        cache = ContextCache(cache_dir=tmp_path)

        contact = Contact(name="Patrick Humes", email="patrick@mcr.com")
        cache.set_contact("Patrick Humes", contact)

        retrieved = cache.get_contact("patrick humes")  # Case insensitive
        assert retrieved.name == "Patrick Humes"

    def test_bulk_load_contacts(self, tmp_path):
        """Test bulk loading contacts."""
        cache = ContextCache(cache_dir=tmp_path)

        contacts = [
            Contact(name="Patrick Humes", first_name="Patrick", email="patrick@mcr.com"),
            Contact(name="Tim McGraw", first_name="Tim", email="tim@downhome.com"),
            Contact(name="Jane Smith", first_name="Jane"),
        ]

        cache.load_all_contacts(contacts)

        assert cache._contacts_loaded
        assert len(cache._all_contacts) == 3

        # Should be able to find by name
        found = cache.get_contact("Patrick Humes")
        assert found is not None

        # Should be able to find by email
        found = cache.get_contact("tim@downhome.com")
        assert found is not None

    def test_search_contacts(self, tmp_path):
        """Test searching contacts."""
        cache = ContextCache(cache_dir=tmp_path)

        contacts = [
            Contact(name="Patrick Humes"),
            Contact(name="Patrick Smith"),
            Contact(name="Tim McGraw"),
        ]
        cache.load_all_contacts(contacts)

        results = cache.search_contacts("Patrick")
        assert len(results) == 2

    def test_cache_clear(self, tmp_path):
        """Test clearing the cache."""
        cache = ContextCache(cache_dir=tmp_path)

        contacts = [Contact(name="Test")]
        cache.load_all_contacts(contacts)
        cache.set_calendar_events(datetime.now(), "test@example.com", [])

        cache.clear()

        assert not cache._contacts_loaded
        assert len(cache._all_contacts) == 0
        assert len(cache._calendar_cache) == 0


# =============================================================================
# Merchant Intelligence Tests
# =============================================================================

class TestMerchantIntelligence:
    """Tests for merchant intelligence lookup."""

    def test_known_merchant(self):
        """Test lookup of known merchant."""
        intel = get_merchant_intelligence("Soho House Nashville")
        assert "description" in intel
        assert "tax_category" in intel
        assert intel["tax_category"] == "Meals & Entertainment"

    def test_partial_match(self):
        """Test partial merchant name match."""
        intel = get_merchant_intelligence("UBER *RIDES")
        assert intel.get("tax_category") == "Travel - Local Transportation"

    def test_unknown_merchant(self):
        """Test lookup of unknown merchant."""
        intel = get_merchant_intelligence("Unknown Restaurant XYZ")
        assert intel == {}

    def test_case_insensitive(self):
        """Test case insensitive matching."""
        intel = get_merchant_intelligence("ANTHROPIC")
        assert "AI" in intel.get("description", "")


# =============================================================================
# NoteLearningSystem Tests
# =============================================================================

class TestNoteLearningSystem:
    """Tests for the learning system."""

    def test_learning_creation(self, tmp_path):
        """Test learning system creation."""
        learning = NoteLearningSystem(data_dir=tmp_path)
        assert learning.corrections == []
        assert learning.patterns == {}

    def test_learn_correction(self, tmp_path):
        """Test learning from a correction."""
        learning = NoteLearningSystem(data_dir=tmp_path)

        learning.learn_correction(
            merchant="Soho House",
            original_note="Business expense",
            corrected_note="Business dinner with investors discussing funding",
            context={"amount": 250.00},
        )

        assert len(learning.corrections) == 1
        assert "soho house" in learning.patterns

        # Check persistence
        learning2 = NoteLearningSystem(data_dir=tmp_path)
        assert len(learning2.corrections) == 1

    def test_get_previous_notes(self, tmp_path):
        """Test getting previous notes for a merchant."""
        learning = NoteLearningSystem(data_dir=tmp_path)

        learning.learn_correction("Soho House", "bad", "good note 1")
        learning.learn_correction("Soho House", "bad", "good note 2")
        learning.learn_correction("Soho House", "bad", "good note 3")

        notes = learning.get_previous_notes("soho house", limit=2)
        assert len(notes) == 2
        assert notes[-1] == "good note 3"

    def test_get_typical_purpose(self, tmp_path):
        """Test getting typical purpose."""
        learning = NoteLearningSystem(data_dir=tmp_path)

        learning.learn_correction("Uber", "trip", "Uber to meeting at Soho House")

        purpose = learning.get_typical_purpose("UBER *TRIPS")
        assert purpose is not None
        assert "Soho House" in purpose


# =============================================================================
# GoogleCalendarClient Tests
# =============================================================================

class TestGoogleCalendarClient:
    """Tests for the Google Calendar client."""

    def test_is_business_event_true(self):
        """Test business event detection."""
        client = GoogleCalendarClient()
        assert client._is_business_event("Lunch with investors")
        assert client._is_business_event("Q4 Planning Meeting")

    def test_is_business_event_false(self):
        """Test personal event detection."""
        client = GoogleCalendarClient()
        assert not client._is_business_event("John's Birthday Party")
        assert not client._is_business_event("Dentist appointment")
        assert not client._is_business_event("Kid's soccer practice")

    def test_extract_attendee_names_with_pattern(self):
        """Test extracting names from 'with' pattern."""
        client = GoogleCalendarClient()

        names = client._extract_attendee_names("Lunch with Patrick Humes")
        assert "Patrick Humes" in names

    def test_extract_attendee_names_multiple(self):
        """Test extracting multiple names."""
        client = GoogleCalendarClient()

        names = client._extract_attendee_names("Meeting with John Smith and Jane Doe")
        assert len(names) >= 2

    def test_extract_attendee_names_plus_pattern(self):
        """Test extracting names from plus pattern."""
        client = GoogleCalendarClient()

        names = client._extract_attendee_names("Patrick + Tim - Strategy Session")
        assert "Patrick" in names or len(names) >= 1


# =============================================================================
# SmartNotesService Tests
# =============================================================================

class TestSmartNotesService:
    """Tests for the main SmartNotesService."""

    @pytest.fixture
    def mock_service(self, tmp_path):
        """Create a service with mocked dependencies."""
        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))

            # Mock the Claude client
            service.claude_client = None  # Test fallback behavior

            # Mock calendar client
            service.calendar_client.get_events_around_time = Mock(return_value=[])

            # Mock contacts client
            service.contacts_client.get_all_contacts = Mock(return_value=[])

            return service

    @pytest.mark.asyncio
    async def test_generate_note_basic(self, mock_service):
        """Test basic note generation without external data."""
        result = await mock_service.generate_note(
            merchant="Test Restaurant",
            amount=50.00,
            date=datetime(2024, 1, 15, 12, 0),
        )

        assert isinstance(result, NoteResult)
        assert result.generated_at is not None
        assert result.note  # Should have fallback note

    @pytest.mark.asyncio
    async def test_generate_note_with_calendar_context(self, mock_service):
        """Test note generation with calendar events."""
        # Add a calendar event
        event = CalendarEvent(
            id="test123",
            title="Lunch with Patrick",
            start_time=datetime(2024, 1, 15, 12, 0),
            attendees=["Patrick Humes"],
        )
        mock_service.calendar_client.get_events_around_time = Mock(return_value=[event])

        result = await mock_service.generate_note(
            merchant="Test Restaurant",
            amount=75.00,
            date=datetime(2024, 1, 15, 12, 30),
        )

        assert "calendar" in result.data_sources
        assert result.calendar_event is not None
        assert result.calendar_event.title == "Lunch with Patrick"

    @pytest.mark.asyncio
    async def test_generate_note_with_merchant_intelligence(self, mock_service):
        """Test note generation with merchant intelligence."""
        result = await mock_service.generate_note(
            merchant="Soho House Nashville",
            amount=150.00,
            date=datetime(2024, 1, 15, 19, 0),
        )

        assert "merchant_intelligence" in result.data_sources

    @pytest.mark.asyncio
    async def test_generate_note_confidence_scoring(self, mock_service):
        """Test that confidence increases with more data sources."""
        # No data sources
        result1 = await mock_service.generate_note(
            merchant="Unknown Place",
            amount=20.00,
            date=datetime(2024, 1, 15),
        )

        # With merchant intelligence
        result2 = await mock_service.generate_note(
            merchant="Uber Trip",
            amount=25.00,
            date=datetime(2024, 1, 15),
        )

        assert result2.confidence > result1.confidence

    @pytest.mark.asyncio
    async def test_gather_context(self, mock_service):
        """Test context gathering."""
        event = CalendarEvent(
            title="Meeting",
            start_time=datetime(2024, 1, 15, 12, 0),
            attendees=["Test Person"],
        )
        mock_service.calendar_client.get_events_around_time = Mock(return_value=[event])

        context = await mock_service.gather_context(
            merchant="Test Restaurant",
            amount=Decimal("100.00"),
            date=datetime(2024, 1, 15, 12, 30),
            category="Meals",
            business_type="Down Home",
        )

        assert context.merchant == "Test Restaurant"
        assert context.amount == Decimal("100.00")
        assert len(context.calendar_events) == 1
        assert context.closest_event is not None

    def test_parse_llm_response(self, mock_service):
        """Test parsing LLM response."""
        response = """DESCRIPTION: Business dinner with Patrick Humes discussing MCR marketing.
ATTENDEES: Patrick Humes (MCR co-founder)
BUSINESS_PURPOSE: Client development
TAX_CATEGORY: Meals & Entertainment"""

        parsed = mock_service._parse_llm_response(response)

        assert "Patrick Humes" in parsed["description"]
        assert "Client development" in parsed["business_purpose"]
        assert "Meals & Entertainment" in parsed["tax_category"]

    def test_generate_fallback_note(self, mock_service):
        """Test fallback note generation."""
        context = TransactionContext(
            merchant="Soho House",
            amount=Decimal("150.00"),
            date=datetime.now(),
            merchant_hint="exclusive members club for networking",
        )

        note = mock_service._generate_fallback_note(context)
        assert "members club" in note or "Soho House" in note

    def test_generate_fallback_note_with_attendees(self, mock_service):
        """Test fallback note with attendees."""
        context = TransactionContext(
            merchant="Test Restaurant",
            amount=Decimal("100.00"),
            attendees=[
                Contact(name="Patrick Humes", company="MCR"),
                Contact(name="Tim McGraw"),
            ],
        )

        note = mock_service._generate_fallback_note(context)
        assert "with" in note.lower()

    def test_learn_from_edit(self, mock_service, tmp_path):
        """Test learning from user edits."""
        # Create a fresh learning system with isolated data dir
        mock_service.learning = NoteLearningSystem(data_dir=tmp_path / "learning_test")

        mock_service.learn_from_edit(
            merchant="Test Restaurant Unique",
            original_note="Business expense",
            edited_note="Dinner with investors from Skydance",
            context={"amount": 200.00},
        )

        # Should be able to retrieve learned pattern
        notes = mock_service.learning.get_previous_notes("Test Restaurant Unique")
        assert len(notes) >= 1
        assert "Skydance" in notes[-1]

    @pytest.mark.asyncio
    async def test_generate_batch(self, mock_service):
        """Test batch note generation."""
        transactions = [
            {"merchant": "Restaurant A", "amount": 50.00, "date": "2024-01-15"},
            {"merchant": "Restaurant B", "amount": 75.00, "date": "2024-01-16"},
        ]

        results = await mock_service.generate_batch(transactions)

        assert len(results) == 2
        assert all(isinstance(r, NoteResult) for r in results)


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the complete flow."""

    @pytest.mark.asyncio
    async def test_full_note_generation_flow(self, tmp_path):
        """Test the complete note generation flow."""
        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))
            service.claude_client = None

            # Add learned pattern
            service.learning.learn_correction(
                merchant="Soho House",
                original_note="expense",
                corrected_note="Networking dinner at Soho House with industry contacts",
            )

            # Generate note
            result = await service.generate_note(
                merchant="SH Nashville",
                amount=200.00,
                date=datetime(2024, 1, 15, 19, 0),
                business_type="Down Home",
                category="Meals & Entertainment",
            )

            assert result.note
            assert result.confidence > 0
            assert "merchant_intelligence" in result.data_sources

    @pytest.mark.asyncio
    async def test_date_parsing_in_batch(self, tmp_path):
        """Test various date formats in batch processing."""
        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))
            service.claude_client = None

            transactions = [
                {"merchant": "Test 1", "amount": 10, "date": "2024-01-15"},
                {"merchant": "Test 2", "amount": 20, "date": "01/15/2024"},
                {"merchant": "Test 3", "amount": 30, "Chase Date": "01-15-2024"},
            ]

            results = await service.generate_batch(transactions)

            assert len(results) == 3
            assert all(r.note for r in results)


# =============================================================================
# API Response Format Tests
# =============================================================================

class TestAPIResponseFormat:
    """Tests for API response formatting."""

    def test_note_result_json_serialization(self):
        """Test that NoteResult can be serialized to JSON."""
        result = NoteResult(
            note="Test note",
            attendees=[Contact(name="Test Person", company="Test Co")],
            attendee_count=1,
            calendar_event=CalendarEvent(title="Meeting", start_time=datetime.now()),
            confidence=0.85,
            data_sources=["calendar", "contacts"],
            generated_at=datetime.now(),
        )

        d = result.to_dict()

        # Should be JSON serializable
        json_str = json.dumps(d, default=str)
        assert "Test note" in json_str
        assert "Test Person" in json_str


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_merchant(self, tmp_path):
        """Test handling of empty merchant."""
        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))
            service.claude_client = None

            result = await service.generate_note(
                merchant="",
                amount=50.00,
                date=datetime.now(),
            )

            assert isinstance(result, NoteResult)

    @pytest.mark.asyncio
    async def test_negative_amount(self, tmp_path):
        """Test handling of negative amount (refund)."""
        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))
            service.claude_client = None

            result = await service.generate_note(
                merchant="Test Store",
                amount=-50.00,
                date=datetime.now(),
            )

            assert isinstance(result, NoteResult)

    @pytest.mark.asyncio
    async def test_future_date(self, tmp_path):
        """Test handling of future date."""
        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))
            service.claude_client = None

            future_date = datetime.now() + timedelta(days=30)
            result = await service.generate_note(
                merchant="Test",
                amount=100.00,
                date=future_date,
            )

            assert isinstance(result, NoteResult)

    def test_malformed_llm_response(self, tmp_path):
        """Test handling of malformed LLM response."""
        with patch.object(SmartNotesService, '_load_contacts_cache'):
            service = SmartNotesService(credentials_dir=str(tmp_path))

            # Test with completely malformed response
            parsed = service._parse_llm_response("This is not a structured response at all.")
            assert parsed == {}

            # Test with partial response
            parsed = service._parse_llm_response("DESCRIPTION: Only has description")
            assert "description" in parsed
            assert parsed["description"] == "Only has description"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
