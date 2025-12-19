#!/usr/bin/env python3
"""
Shared iMessage Client
======================

Unified iMessage/chat.db client for all brian-system apps.
Provides access to messages with payment/receipt detection and smart routing.

Features:
- Read messages from macOS Messages.app database
- Detect payment platforms (Square, Toast, Venmo, etc.)
- Extract receipt URLs and amounts
- Integration with Taskade for task creation

Usage:
    from packages.shared import iMessageClient

    client = iMessageClient()
    payments = client.get_recent_payments(days=7)
    receipts = client.find_receipt_urls(days=30)

Note: Requires Full Disk Access permission for Terminal/IDE to read chat.db
"""

import os
import re
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

# Payment platform patterns in messages
PAYMENT_PATTERNS = {
    # POS Systems
    'square': {
        'url_patterns': [r'https?://[^\s<>"]*square[^\s<>"]*'],
        'text_patterns': [r'square\s+receipt', r'sq\s+\*', r'squareup\.com'],
        'type': 'pos'
    },
    'toast': {
        'url_patterns': [r'https?://[^\s<>"]*toast(?:tab)?[^\s<>"]*'],
        'text_patterns': [r'toast\s+receipt', r'tst\s+\*', r'toasttab\.com'],
        'type': 'pos'
    },

    # Parking Services
    'pmc': {
        'url_patterns': [r'https?://[^\s<>"]*(?:pmc|metropolis|mpolis)[^\s<>"]*'],
        'text_patterns': [r'pmc\s+parking', r'metropolis', r'mpolis\.io'],
        'type': 'parking'
    },
    'parkmobile': {
        'url_patterns': [r'https?://[^\s<>"]*parkmobile[^\s<>"]*'],
        'text_patterns': [r'parkmobile', r'park\s+mobile'],
        'type': 'parking'
    },
    'spothero': {
        'url_patterns': [r'https?://[^\s<>"]*spothero[^\s<>"]*'],
        'text_patterns': [r'spothero', r'spot\s+hero'],
        'type': 'parking'
    },

    # Rideshare
    'uber': {
        'url_patterns': [r'https?://[^\s<>"]*uber[^\s<>"]*'],
        'text_patterns': [r'uber\s+(?:trip|ride|receipt)', r'uber\.com'],
        'type': 'rideshare'
    },
    'lyft': {
        'url_patterns': [r'https?://[^\s<>"]*lyft[^\s<>"]*'],
        'text_patterns': [r'lyft\s+(?:trip|ride|receipt)', r'lyft\.com'],
        'type': 'rideshare'
    },

    # P2P Payments
    'venmo': {
        'url_patterns': [r'https?://[^\s<>"]*venmo[^\s<>"]*'],
        'text_patterns': [r'venmo', r'venmo\.com'],
        'type': 'p2p'
    },
    'cashapp': {
        'url_patterns': [r'https?://[^\s<>"]*cash\.app[^\s<>"]*'],
        'text_patterns': [r'cash\s*app', r'\$cashtag'],
        'type': 'p2p'
    },
    'zelle': {
        'url_patterns': [r'https?://[^\s<>"]*zelle[^\s<>"]*'],
        'text_patterns': [r'zelle', r'zelle\.com'],
        'type': 'p2p'
    },
    'paypal': {
        'url_patterns': [r'https?://[^\s<>"]*paypal[^\s<>"]*'],
        'text_patterns': [r'paypal'],
        'type': 'p2p'
    },

    # Food Delivery
    'doordash': {
        'url_patterns': [r'https?://[^\s<>"]*doordash[^\s<>"]*'],
        'text_patterns': [r'doordash', r'door\s*dash'],
        'type': 'food_delivery'
    },
    'ubereats': {
        'url_patterns': [r'https?://[^\s<>"]*uber\s*eats[^\s<>"]*'],
        'text_patterns': [r'uber\s*eats'],
        'type': 'food_delivery'
    },
    'grubhub': {
        'url_patterns': [r'https?://[^\s<>"]*grubhub[^\s<>"]*'],
        'text_patterns': [r'grubhub'],
        'type': 'food_delivery'
    },
}

# Amount extraction patterns
AMOUNT_PATTERNS = [
    r'\$\s*(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)',  # $123.45
    r'(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)\s*(?:dollars?|USD)',  # 123.45 dollars
    r'(?:total|amount|charged|paid)[:\s]*\$?\s*(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)',  # Total: $123.45
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class iMessage:
    """Represents an iMessage"""
    text: str
    date: datetime
    sender: str
    is_from_me: bool
    chat_id: Optional[str] = None
    rowid: Optional[int] = None


@dataclass
class PaymentMessage:
    """Message containing payment/receipt information"""
    message: iMessage
    platform: str
    platform_type: str
    urls: List[str] = field(default_factory=list)
    amount: Optional[float] = None
    raw_amount: Optional[str] = None


@dataclass
class ReceiptURL:
    """Receipt URL found in message"""
    url: str
    message: iMessage
    platform: Optional[str] = None
    amount: Optional[float] = None


# =============================================================================
# IMESSAGE CLIENT
# =============================================================================

class iMessageClient:
    """
    Client for reading and analyzing iMessage/chat.db.

    Provides:
    - Message search and retrieval
    - Payment platform detection
    - Receipt URL extraction
    - Amount parsing
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or CHAT_DB_PATH
        self._verify_access()

    def _verify_access(self) -> bool:
        """Verify we can access chat.db"""
        if not os.path.exists(self.db_path):
            logger.error(f"chat.db not found at {self.db_path}")
            return False

        try:
            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
            conn.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"Cannot access chat.db: {e}")
            logger.error("Ensure Terminal/IDE has Full Disk Access in System Settings")
            return False

    def _connect(self) -> sqlite3.Connection:
        """Get read-only connection to chat.db"""
        return sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)

    def _cocoa_to_datetime(self, cocoa_timestamp: int) -> datetime:
        """Convert macOS Cocoa timestamp to datetime"""
        # Cocoa timestamps are nanoseconds since 2001-01-01
        return datetime(2001, 1, 1) + timedelta(seconds=cocoa_timestamp / 1_000_000_000)

    def _datetime_to_cocoa(self, dt: datetime) -> int:
        """Convert datetime to Cocoa timestamp"""
        return int((dt - datetime(2001, 1, 1)).total_seconds() * 1_000_000_000)

    # =========================================================================
    # MESSAGE RETRIEVAL
    # =========================================================================

    def get_messages(
        self,
        days: int = 30,
        sender: str = None,
        contains: str = None,
        limit: int = 1000
    ) -> List[iMessage]:
        """
        Get messages from chat.db.

        Args:
            days: Look back this many days
            sender: Filter by sender phone/email
            contains: Filter by text content
            limit: Max messages to return
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            start_date = datetime.now() - timedelta(days=days)
            start_cocoa = self._datetime_to_cocoa(start_date)

            query = """
                SELECT
                    message.text,
                    message.date,
                    message.is_from_me,
                    COALESCE(handle.id, 'Me') as sender,
                    message.ROWID
                FROM message
                LEFT JOIN handle ON message.handle_id = handle.ROWID
                WHERE message.text IS NOT NULL
                    AND message.text != ''
                    AND message.date >= ?
            """
            params = [start_cocoa]

            if sender:
                query += " AND handle.id LIKE ?"
                params.append(f"%{sender}%")

            if contains:
                query += " AND message.text LIKE ?"
                params.append(f"%{contains}%")

            query += " ORDER BY message.date DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)

            messages = []
            for row in cursor.fetchall():
                text, date, is_from_me, sender_id, rowid = row
                messages.append(iMessage(
                    text=text,
                    date=self._cocoa_to_datetime(date),
                    sender=sender_id,
                    is_from_me=bool(is_from_me),
                    rowid=rowid
                ))

            conn.close()
            return messages

        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    def search_messages(self, query: str, days: int = 90) -> List[iMessage]:
        """Search messages by text content"""
        return self.get_messages(days=days, contains=query)

    # =========================================================================
    # PAYMENT DETECTION
    # =========================================================================

    def detect_payment_platform(self, text: str) -> Optional[Tuple[str, str]]:
        """
        Detect payment platform in message text.
        Returns (platform_name, platform_type) or None.
        """
        if not text:
            return None

        text_lower = text.lower()

        for platform, config in PAYMENT_PATTERNS.items():
            # Check URL patterns
            for pattern in config.get('url_patterns', []):
                if re.search(pattern, text, re.IGNORECASE):
                    return (platform, config['type'])

            # Check text patterns
            for pattern in config.get('text_patterns', []):
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return (platform, config['type'])

        return None

    def extract_amount(self, text: str) -> Optional[Tuple[float, str]]:
        """
        Extract dollar amount from text.
        Returns (amount, raw_string) or None.
        """
        if not text:
            return None

        for pattern in AMOUNT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw = match.group(1)
                try:
                    amount = float(raw.replace(',', ''))
                    return (amount, raw)
                except ValueError:
                    continue

        return None

    def extract_urls(self, text: str) -> List[str]:
        """Extract all URLs from text"""
        if not text:
            return []

        url_pattern = r'https?://[^\s<>"\']+'
        return re.findall(url_pattern, text)

    # =========================================================================
    # PAYMENT/RECEIPT QUERIES
    # =========================================================================

    def get_recent_payments(self, days: int = 30) -> List[PaymentMessage]:
        """
        Get messages containing payment/receipt information.
        Detects Square, Toast, Venmo, parking receipts, etc.
        """
        messages = self.get_messages(days=days, limit=5000)
        payments = []

        for msg in messages:
            platform_info = self.detect_payment_platform(msg.text)

            if platform_info:
                platform, platform_type = platform_info
                amount_info = self.extract_amount(msg.text)
                urls = self.extract_urls(msg.text)

                payments.append(PaymentMessage(
                    message=msg,
                    platform=platform,
                    platform_type=platform_type,
                    urls=urls,
                    amount=amount_info[0] if amount_info else None,
                    raw_amount=amount_info[1] if amount_info else None
                ))

        return payments

    def get_payments_by_platform(self, platform: str, days: int = 90) -> List[PaymentMessage]:
        """Get payments for a specific platform"""
        all_payments = self.get_recent_payments(days=days)
        return [p for p in all_payments if p.platform.lower() == platform.lower()]

    def get_parking_receipts(self, days: int = 90) -> List[PaymentMessage]:
        """Get all parking-related receipts"""
        all_payments = self.get_recent_payments(days=days)
        return [p for p in all_payments if p.platform_type == 'parking']

    def get_rideshare_receipts(self, days: int = 90) -> List[PaymentMessage]:
        """Get all rideshare receipts (Uber, Lyft)"""
        all_payments = self.get_recent_payments(days=days)
        return [p for p in all_payments if p.platform_type == 'rideshare']

    def get_p2p_payments(self, days: int = 90) -> List[PaymentMessage]:
        """Get P2P payments (Venmo, Zelle, CashApp, PayPal)"""
        all_payments = self.get_recent_payments(days=days)
        return [p for p in all_payments if p.platform_type == 'p2p']

    def find_receipt_urls(self, days: int = 90) -> List[ReceiptURL]:
        """
        Find all receipt URLs in messages.
        Returns URLs with platform detection.
        """
        messages = self.get_messages(days=days, limit=5000)
        receipts = []

        for msg in messages:
            urls = self.extract_urls(msg.text)
            if not urls:
                continue

            # Check each URL for receipt patterns
            for url in urls:
                # Detect platform from URL
                platform = None
                for plat, config in PAYMENT_PATTERNS.items():
                    for pattern in config.get('url_patterns', []):
                        if re.search(pattern, url, re.IGNORECASE):
                            platform = plat
                            break
                    if platform:
                        break

                # Also check for generic receipt keywords
                if not platform:
                    url_lower = url.lower()
                    if any(kw in url_lower for kw in ['receipt', 'invoice', 'order', 'confirmation']):
                        platform = 'unknown'

                if platform:
                    amount_info = self.extract_amount(msg.text)
                    receipts.append(ReceiptURL(
                        url=url,
                        message=msg,
                        platform=platform,
                        amount=amount_info[0] if amount_info else None
                    ))

        return receipts

    # =========================================================================
    # MATCHING / SEARCH
    # =========================================================================

    def search_for_transaction(
        self,
        merchant: str,
        amount: float,
        date: datetime,
        window_days: int = 5
    ) -> List[PaymentMessage]:
        """
        Search for iMessages matching a bank transaction.

        Args:
            merchant: Merchant name from bank
            amount: Transaction amount
            date: Transaction date
            window_days: Days before/after to search
        """
        start = date - timedelta(days=window_days)
        end = date + timedelta(days=window_days)

        # Get messages in date range
        try:
            conn = self._connect()
            cursor = conn.cursor()

            start_cocoa = self._datetime_to_cocoa(start)
            end_cocoa = self._datetime_to_cocoa(end)

            query = """
                SELECT
                    message.text,
                    message.date,
                    message.is_from_me,
                    COALESCE(handle.id, 'Me') as sender,
                    message.ROWID
                FROM message
                LEFT JOIN handle ON message.handle_id = handle.ROWID
                WHERE message.text IS NOT NULL
                    AND message.date >= ?
                    AND message.date <= ?
                    AND (
                        message.text LIKE '%http%'
                        OR message.text LIKE '%$%'
                        OR message.text LIKE '%receipt%'
                    )
                ORDER BY message.date DESC
            """

            cursor.execute(query, (start_cocoa, end_cocoa))

            matches = []
            merchant_lower = merchant.lower()

            for row in cursor.fetchall():
                text, date_val, is_from_me, sender, rowid = row
                msg = iMessage(
                    text=text,
                    date=self._cocoa_to_datetime(date_val),
                    sender=sender,
                    is_from_me=bool(is_from_me),
                    rowid=rowid
                )

                # Score this message
                text_lower = text.lower()
                score = 0

                # Merchant match
                if any(word in text_lower for word in merchant_lower.split() if len(word) > 3):
                    score += 40

                # Amount match
                amount_info = self.extract_amount(text)
                if amount_info:
                    diff = abs(amount_info[0] - amount)
                    if diff < 0.01:
                        score += 50
                    elif diff < 5:
                        score += 30
                    elif diff < 20:
                        score += 15

                # Platform detection
                platform_info = self.detect_payment_platform(text)
                if platform_info:
                    score += 10

                if score >= 30:
                    platform, platform_type = platform_info if platform_info else ('unknown', 'unknown')
                    matches.append(PaymentMessage(
                        message=msg,
                        platform=platform,
                        platform_type=platform_type,
                        urls=self.extract_urls(text),
                        amount=amount_info[0] if amount_info else None
                    ))

            conn.close()
            return sorted(matches, key=lambda x: x.amount if x.amount else 0, reverse=True)[:10]

        except Exception as e:
            logger.error(f"Error searching for transaction: {e}")
            return []

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_payment_stats(self, days: int = 30) -> Dict:
        """Get statistics about payments in messages"""
        payments = self.get_recent_payments(days=days)

        stats = {
            'total_messages': len(payments),
            'by_platform': {},
            'by_type': {},
            'total_amount': 0,
            'with_amount': 0,
        }

        for p in payments:
            # By platform
            if p.platform not in stats['by_platform']:
                stats['by_platform'][p.platform] = {'count': 0, 'total': 0}
            stats['by_platform'][p.platform]['count'] += 1

            # By type
            if p.platform_type not in stats['by_type']:
                stats['by_type'][p.platform_type] = {'count': 0, 'total': 0}
            stats['by_type'][p.platform_type]['count'] += 1

            # Amounts
            if p.amount:
                stats['with_amount'] += 1
                stats['total_amount'] += p.amount
                stats['by_platform'][p.platform]['total'] += p.amount
                stats['by_type'][p.platform_type]['total'] += p.amount

        return stats


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_client: iMessageClient = None

def get_imessage_client() -> iMessageClient:
    """Get singleton iMessage client"""
    global _client
    if _client is None:
        _client = iMessageClient()
    return _client


def get_recent_payments(days: int = 30) -> List[PaymentMessage]:
    """Quick function to get recent payments"""
    return get_imessage_client().get_recent_payments(days)


def find_receipt_urls(days: int = 90) -> List[ReceiptURL]:
    """Quick function to find receipt URLs"""
    return get_imessage_client().find_receipt_urls(days)


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import sys

    client = iMessageClient()

    print("iMessage Payment Scanner")
    print("=" * 60)

    # Get recent payments
    print("\nScanning for payment messages (last 30 days)...")
    payments = client.get_recent_payments(days=30)

    print(f"\nFound {len(payments)} payment-related messages\n")

    # Group by type
    by_type = {}
    for p in payments:
        if p.platform_type not in by_type:
            by_type[p.platform_type] = []
        by_type[p.platform_type].append(p)

    for ptype, items in sorted(by_type.items()):
        print(f"\n{ptype.upper()} ({len(items)} messages):")
        for item in items[:3]:  # Show first 3
            amount_str = f"${item.amount:.2f}" if item.amount else "N/A"
            print(f"  - {item.platform}: {amount_str} ({item.message.date.date()})")
            if item.urls:
                print(f"    URL: {item.urls[0][:50]}...")

    # Stats
    stats = client.get_payment_stats(days=30)
    print(f"\n\nSTATISTICS (30 days)")
    print("-" * 40)
    print(f"Total messages with payments: {stats['total_messages']}")
    print(f"Messages with amounts: {stats['with_amount']}")
    print(f"Total amount detected: ${stats['total_amount']:.2f}")

    print("\nBy Platform:")
    for platform, data in sorted(stats['by_platform'].items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"  {platform}: {data['count']} messages, ${data['total']:.2f}")
