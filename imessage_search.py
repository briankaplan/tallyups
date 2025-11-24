#!/usr/bin/env python3
"""
iMessage Receipt Search - Find receipts from text messages with links
Searches iMessage chat.db for messages containing receipt URLs
"""

import sqlite3
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import hashlib
from urllib.parse import urlparse

# Try to import vision extraction (optional)
try:
    from ai_receipt_locator import vision_extract
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False
    vision_extract = None

# Try to import Playwright for screenshots
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None

# iMessage database location
IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")
RECEIPTS_DIR = Path(__file__).parent / "receipts"

# Common receipt URL patterns
RECEIPT_URL_PATTERNS = [
    r'https?://[^\s<>"]+(?:receipt|invoice|order|confirmation)',  # Generic receipt URLs
    r'https?://[^\s<>"]*uber[^\s<>"]*',  # Uber
    r'https?://[^\s<>"]*lyft[^\s<>"]*',  # Lyft
    r'https?://[^\s<>"]*square[^\s<>"]*',  # Square
    r'https?://[^\s<>"]*toast[^\s<>"]*',  # Toast (TST)
    r'https?://[^\s<>"]*toasttab[^\s<>"]*',  # Toast Tab
    r'https?://[^\s<>"]*stripe[^\s<>"]*',  # Stripe
    r'https?://[^\s<>"]*paypal[^\s<>"]*',  # PayPal
    r'https?://[^\s<>"]*venmo[^\s<>"]*',  # Venmo
    r'https?://[^\s<>"]*apple[^\s<>"]*(?:invoice|receipt)',  # Apple
    r'https?://[^\s<>"]*amazon[^\s<>"]*(?:invoice|receipt)',  # Amazon
    r'https?://[^\s<>"]*expensify[^\s<>"]*',  # Expensify
    r'https?://[^\s<>"]*(?:pmc|metropolis|mpolis|greenhills)[^\s<>"]*',  # PMC, Metropolis, mpolis.io, Green Hills
]

# Amount patterns in text
AMOUNT_PATTERNS = [
    r'\$\s*(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)',  # $123.45
    r'(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)\s*(?:dollars?|USD)',  # 123.45 dollars
]

class iMessageReceiptSearch:
    def __init__(self):
        self.db_path = IMESSAGE_DB
        self.receipts_dir = RECEIPTS_DIR
        self.receipts_dir.mkdir(exist_ok=True)

    def search_for_transaction(self, transaction: Dict, date_window_days: int = 5) -> List[Dict]:
        """
        Search iMessage for receipt links matching a transaction

        Args:
            transaction: Dict with 'Chase Description', 'Chase Amount', 'Chase Date'
            date_window_days: Days before/after transaction to search

        Returns:
            List of candidate receipts with scores
        """
        merchant = transaction.get('Chase Description', '')
        amount = abs(float(transaction.get('Chase Amount', 0)))
        tx_date_str = transaction.get('Chase Date', '')

        if not tx_date_str or not merchant:
            return []

        # Parse transaction date
        try:
            if isinstance(tx_date_str, str):
                tx_date = datetime.strptime(tx_date_str, '%Y-%m-%d')
            else:
                tx_date = tx_date_str
        except:
            return []

        # Calculate date range
        start_date = tx_date - timedelta(days=date_window_days)
        end_date = tx_date + timedelta(days=date_window_days)

        print(f"💬 Searching iMessage for {merchant} ${amount:.2f} around {tx_date.date()}")

        # Search messages
        messages = self._search_messages_with_urls(start_date, end_date)
        print(f"   Found {len(messages)} messages with URLs in date range")

        # Score candidates
        candidates = []
        for msg in messages:
            score_result = self._score_message(msg, merchant, amount, tx_date)
            if score_result and score_result['score'] >= 0.5:  # 50% threshold
                candidates.append(score_result)

        # Sort by score
        candidates.sort(key=lambda x: x['score'], reverse=True)

        return candidates[:10]  # Top 10 candidates

    def _search_messages_with_urls(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Search iMessage database for messages with receipt URLs"""
        try:
            # Connect to iMessage database (read-only)
            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
            cursor = conn.cursor()

            # Convert datetime to Mac's cocoa time format (seconds since 2001-01-01)
            start_cocoa = int((start_date - datetime(2001, 1, 1)).total_seconds())
            end_cocoa = int((end_date - datetime(2001, 1, 1)).total_seconds())

            # Query for messages with text containing URLs
            query = """
                SELECT
                    message.text,
                    message.date,
                    message.is_from_me,
                    handle.id as sender
                FROM message
                LEFT JOIN handle ON message.handle_id = handle.ROWID
                WHERE message.text IS NOT NULL
                    AND message.date >= ?
                    AND message.date <= ?
                    AND (
                        message.text LIKE '%http%'
                        OR message.text LIKE '%www.%'
                    )
                ORDER BY message.date DESC
            """

            cursor.execute(query, (start_cocoa, end_cocoa))
            results = []

            for row in cursor.fetchall():
                text, cocoa_date, is_from_me, sender = row

                # Convert cocoa time back to datetime
                msg_date = datetime(2001, 1, 1) + timedelta(seconds=cocoa_date / 1000000000)

                # Extract URLs from text
                urls = self._extract_receipt_urls(text)

                if urls:
                    results.append({
                        'text': text,
                        'date': msg_date,
                        'urls': urls,
                        'sender': sender or 'Me' if is_from_me else 'Unknown',
                        'is_from_me': bool(is_from_me)
                    })

            conn.close()
            return results

        except Exception as e:
            print(f"   ⚠️  Error searching iMessage: {e}")
            return []

    def _extract_receipt_urls(self, text: str) -> List[str]:
        """Extract receipt-related URLs from message text"""
        if not text:
            return []

        urls = []
        for pattern in RECEIPT_URL_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            urls.extend(matches)

        # Also extract any URLs if they're the only thing in the message
        if not urls and len(text) < 500:  # Short message might be just a URL
            url_match = re.findall(r'https?://[^\s<>"]+', text)
            urls.extend(url_match)

        return list(set(urls))  # Remove duplicates

    def _score_message(self, message: Dict, merchant: str, amount: float, tx_date: datetime) -> Optional[Dict]:
        """Score a message against transaction"""
        text = message['text']
        msg_date = message['date']
        urls = message['urls']

        if not urls:
            return None

        # Extract merchant/amount mentions from text
        merchant_score = self._score_merchant(text, merchant)
        amount_score = self._score_amount(text, amount)
        date_score = self._score_date(msg_date, tx_date)

        # URL quality score
        url_score = self._score_urls(urls)

        # Calculate weighted score
        # 40% merchant + 30% amount + 20% date + 10% URL quality
        total_score = (
            merchant_score * 0.4 +
            amount_score * 0.3 +
            date_score * 0.2 +
            url_score * 0.1
        )

        if total_score < 0.5:
            return None

        return {
            'score': total_score,
            'message': text[:200],  # First 200 chars
            'date': msg_date,
            'urls': urls,
            'sender': message['sender'],
            'merchant_score': merchant_score,
            'amount_score': amount_score,
            'date_score': date_score,
            'url_score': url_score
        }

    def _score_merchant(self, text: str, merchant: str) -> float:
        """Score merchant name match in message text"""
        if not text or not merchant:
            return 0.0

        text_lower = text.lower()
        merchant_lower = merchant.lower()

        # Direct substring match
        if merchant_lower in text_lower or text_lower in merchant_lower:
            return 1.0

        # Check for word matches
        merchant_words = set(w for w in merchant_lower.split() if len(w) > 3)
        text_words = set(w for w in text_lower.split() if len(w) > 3)

        if merchant_words and text_words:
            overlap = merchant_words & text_words
            if overlap:
                return min(1.0, len(overlap) / len(merchant_words) * 1.5)

        return 0.0

    def _score_amount(self, text: str, amount: float) -> float:
        """Score amount match in message text"""
        if not text or amount == 0:
            return 0.0

        # Extract amounts from text
        for pattern in AMOUNT_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    text_amount = float(match.replace(',', ''))
                    diff = abs(text_amount - amount)

                    # Perfect match
                    if diff < 0.01:
                        return 1.0

                    # Within 1%
                    if diff < (amount * 0.01):
                        return 0.95

                    # Within $5
                    if diff < 5.0:
                        return 0.8

                    # Within $20
                    if diff < 20.0:
                        return 0.6
                except:
                    continue

        return 0.0

    def _score_date(self, msg_date: datetime, tx_date: datetime) -> float:
        """Score date proximity"""
        day_diff = abs((msg_date - tx_date).days)

        if day_diff == 0:
            return 1.0
        elif day_diff <= 1:
            return 0.9
        elif day_diff <= 3:
            return 0.7
        elif day_diff <= 5:
            return 0.5
        else:
            return 0.0

    def _score_urls(self, urls: List[str]) -> float:
        """Score URL quality"""
        if not urls:
            return 0.0

        score = 0.5  # Base score for having a URL

        for url in urls:
            url_lower = url.lower()

            # Known receipt services get higher scores
            if any(service in url_lower for service in ['uber', 'lyft', 'square', 'toast', 'toasttab', 'stripe', 'expensify', 'pmc', 'metropolis', 'greenhills']):
                score = max(score, 1.0)
            elif any(word in url_lower for word in ['receipt', 'invoice', 'order', 'confirmation']):
                score = max(score, 0.9)
            elif url_lower.endswith(('.pdf', '.png', '.jpg', '.jpeg')):
                score = max(score, 0.8)

        return min(1.0, score)

    def screenshot_receipt_from_url(self, url: str, transaction: Dict) -> Optional[str]:
        """Open URL in browser and screenshot the receipt page"""

        if not PLAYWRIGHT_AVAILABLE:
            print("   ⚠️  Playwright not available - cannot screenshot URL")
            return None

        try:
            print(f"   📸 Screenshotting receipt from: {url[:60]}...")

            # Generate filename
            merchant = transaction.get('Chase Description', 'Unknown').replace(' ', '_')
            date_str = transaction.get('Chase Date', 'NoDate')
            amount = abs(float(transaction.get('Chase Amount', 0)))
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

            filename = f"imessage_{merchant}_{date_str}_{amount:.0f}_{url_hash}.png"
            filepath = self.receipts_dir / filename

            # Use Playwright to screenshot the URL
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={'width': 800, 'height': 2400},  # Tall viewport for receipts
                    device_scale_factor=2  # Retina quality
                )
                page = context.new_page()

                # Navigate to URL
                print(f"   🌐 Loading URL...")
                page.goto(url, wait_until='networkidle', timeout=30000)

                # Wait a bit for any dynamic content
                page.wait_for_timeout(2000)

                # Take full-page screenshot
                page.screenshot(path=str(filepath), full_page=True)

                browser.close()

            print(f"   ✅ Saved: {filename}")

            # Extract metadata with vision AI (optional)
            if VISION_AVAILABLE and vision_extract:
                try:
                    metadata = vision_extract(filepath)
                    print(f"   👁️  Vision extraction complete")
                except Exception as e:
                    print(f"   ⚠️  Vision extraction failed: {e}")

            return filename

        except Exception as e:
            print(f"   ❌ Screenshot failed: {e}")
            return None

# Module-level function for easy import
def search_imessage(transaction: Dict) -> List[Dict]:
    """Search iMessage for receipts matching transaction"""
    searcher = iMessageReceiptSearch()
    return searcher.search_for_transaction(transaction)

def download_imessage_receipt(url: str, transaction: Dict) -> Optional[str]:
    """Screenshot receipt from iMessage URL (open in browser and capture)"""
    searcher = iMessageReceiptSearch()
    return searcher.screenshot_receipt_from_url(url, transaction)

if __name__ == "__main__":
    # Test search
    test_tx = {
        'Chase Description': 'UBER TRIP',
        'Chase Amount': -28.75,
        'Chase Date': '2024-06-30'
    }

    print("🧪 Testing iMessage Receipt Search")
    print("=" * 80)
    results = search_imessage(test_tx)

    if results:
        print(f"\n✅ Found {len(results)} candidates:")
        for i, result in enumerate(results, 1):
            print(f"\n#{i}: Score {result['score']*100:.1f}%")
            print(f"   Message: {result['message']}")
            print(f"   Date: {result['date']}")
            print(f"   URLs: {', '.join(result['urls'][:2])}")
    else:
        print("\n❌ No matches found")
