#!/usr/bin/env python3
"""
test_system.py — Quick validation that everything is wired up correctly
"""

import sys
import pytest
from pathlib import Path


class TestModuleImports:
    """Test that core modules can be imported."""

    def test_helpers_import(self):
        """Test helpers.py imports."""
        from helpers import parse_amount_str, normalize_merchant_name, parse_date_fuzzy
        assert callable(parse_amount_str)
        assert callable(normalize_merchant_name)
        assert callable(parse_date_fuzzy)

    def test_contacts_engine_import(self):
        """Test contacts_engine.py imports."""
        from contacts_engine import merchant_hint_for_row, guess_attendees_for_row
        assert callable(merchant_hint_for_row)
        assert callable(guess_attendees_for_row)

    def test_orchestrator_import(self):
        """Test orchestrator.py imports."""
        from orchestrator import (
            find_best_receipt_for_transaction,
            ai_generate_note,
            ai_generate_report_block,
        )
        assert callable(find_best_receipt_for_transaction)
        assert callable(ai_generate_note)
        assert callable(ai_generate_report_block)

    @pytest.mark.skip(reason="Optional module")
    def test_ai_receipt_locator_import(self):
        """Test ai_receipt_locator.py imports (optional)."""
        from ai_receipt_locator import find_best_receipt
        assert callable(find_best_receipt)

    @pytest.mark.skip(reason="Optional module - requires Gmail setup")
    def test_gmail_search_import(self):
        """Test gmail_search.py imports (optional)."""
        from gmail_search import find_best_gmail_receipt_for_row
        assert callable(find_best_gmail_receipt_for_row)


class TestHelperFunctions:
    """Test helper functions work correctly."""

    def test_parse_amount_str(self):
        """Test amount parsing."""
        from helpers import parse_amount_str
        amt = parse_amount_str("$123.45")
        assert amt == 123.45, f"Expected 123.45, got {amt}"

    def test_normalize_merchant_name(self):
        """Test merchant name normalization."""
        from helpers import normalize_merchant_name
        merchant = normalize_merchant_name("SH Nashville")
        assert merchant == "Soho House Nashville", f"Expected 'Soho House Nashville', got '{merchant}'"

    def test_parse_date_fuzzy(self):
        """Test date parsing."""
        from helpers import parse_date_fuzzy
        date = parse_date_fuzzy("2024-07-17")
        assert date.year == 2024 and date.month == 7 and date.day == 17


class TestContactsEngine:
    """Test contacts engine functions."""

    def test_merchant_hint(self):
        """Test merchant hint generation."""
        from contacts_engine import merchant_hint_for_row
        test_row = {
            "Chase Description": "SH NASHVILLE",
            "Chase Amount": "-125.00"
        }
        hint = merchant_hint_for_row(test_row)
        # Just check it returns something without crashing
        assert isinstance(hint, (str, type(None)))

    def test_guess_attendees(self):
        """Test attendee guessing."""
        from contacts_engine import guess_attendees_for_row
        test_row = {
            "Chase Description": "SH NASHVILLE",
            "Chase Amount": "-125.00"
        }
        attendees = guess_attendees_for_row(test_row)
        # Just check it returns a list without crashing
        assert isinstance(attendees, list)


if __name__ == "__main__":
    """Run standalone for debugging."""
    print("=" * 80)
    print("ReceiptAI System Test".center(80))
    print("=" * 80)
    print()

    # Run with pytest
    pytest.main([__file__, "-v"])
