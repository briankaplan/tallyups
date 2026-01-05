#!/usr/bin/env python3
"""
Receipt Classifier Service
===========================
Production-grade email classification for receipt detection.

Combines rule-based patterns with ML-style scoring to achieve
high accuracy receipt identification across 3 email accounts.

Philosophy:
- WHITELIST known receipt senders (highest confidence)
- BLACKLIST known spam/marketing domains
- Score ambiguous emails using multiple signals
- Learn from user feedback (accept/reject patterns)
"""

import re
import json
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import pymysql
import pymysql.cursors
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

MYSQL_CONFIG = {
    # Use MYSQLHOST (Railway's private hostname) to avoid egress fees
    'host': os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST', ''),
    'port': int(os.getenv('MYSQLPORT') or os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQLUSER') or os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQLPASSWORD') or os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQLDATABASE') or os.getenv('MYSQL_DATABASE', 'railway'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


# =============================================================================
# DATA MODELS
# =============================================================================

class ReceiptType(Enum):
    """Types of receipt emails"""
    ORDER_CONFIRMATION = "order_confirmation"
    PAYMENT_RECEIPT = "payment_receipt"
    SUBSCRIPTION_RENEWAL = "subscription_renewal"
    REFUND_CONFIRMATION = "refund_confirmation"
    INVOICE = "invoice"
    TRIP_RECEIPT = "trip_receipt"
    FOOD_ORDER = "food_order"
    DIGITAL_PURCHASE = "digital_purchase"
    UNKNOWN = "unknown"


class EmailCategory(Enum):
    """Email classification categories"""
    RECEIPT = "receipt"
    MARKETING = "marketing"
    NEWSLETTER = "newsletter"
    NOTIFICATION = "notification"
    SHIPPING = "shipping"
    ACCOUNT_ALERT = "account_alert"
    SURVEY = "survey"
    INVOICE_DUE = "invoice_due"  # Not a receipt - payment request
    SPAM = "spam"
    PERSONAL = "personal"
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    """Result of email classification"""
    is_receipt: bool
    confidence: int  # 0-100
    category: EmailCategory
    receipt_type: Optional[ReceiptType]

    # Extracted data
    merchant_name: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: str = "USD"

    # Metadata
    signals: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    matched_domain_pattern: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'is_receipt': self.is_receipt,
            'confidence': self.confidence,
            'category': self.category.value,
            'receipt_type': self.receipt_type.value if self.receipt_type else None,
            'merchant_name': self.merchant_name,
            'amount': float(self.amount) if self.amount else None,
            'currency': self.currency,
            'signals': self.signals,
            'rejection_reasons': self.rejection_reasons,
        }


# =============================================================================
# KNOWN RECEIPT SENDER DOMAINS (WHITELIST)
# =============================================================================

# These domains are KNOWN to send legitimate receipts
# Format: domain -> {patterns, receipt_type, typical_amounts, is_subscription}

RECEIPT_SENDER_WHITELIST = {
    # === AI & DEVELOPMENT ===
    'anthropic.com': {
        'name': 'Anthropic',
        'patterns': ['receipts@', 'billing@', 'noreply@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (20, 500),
    },
    'openai.com': {
        'name': 'OpenAI',
        'patterns': ['noreply@', 'receipts@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (20, 500),
    },
    'midjourney.com': {
        'name': 'Midjourney',
        'patterns': ['noreply@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (10, 120),
    },
    'cursor.sh': {
        'name': 'Cursor',
        'patterns': ['team@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (20, 200),
    },
    'github.com': {
        'name': 'GitHub',
        'patterns': ['noreply@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (4, 50),
    },

    # === CLOUD & INFRASTRUCTURE ===
    'cloudflare.com': {
        'name': 'Cloudflare',
        'patterns': ['billing@', 'noreply@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (5, 500),
    },
    'railway.app': {
        'name': 'Railway',
        'patterns': ['noreply@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (1, 500),
    },
    'vercel.com': {
        'name': 'Vercel',
        'patterns': ['noreply@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (20, 500),
    },
    'digitalocean.com': {
        'name': 'DigitalOcean',
        'patterns': ['noreply@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (5, 500),
    },

    # === PRODUCTIVITY ===
    'apple.com': {
        'name': 'Apple',
        'patterns': ['no_reply@', 'noreply@', 'do_not_reply@'],
        'receipt_type': ReceiptType.DIGITAL_PURCHASE,
        'is_subscription': True,
        'amount_range': (0.99, 500),
        'subdomains': ['email.apple.com', 'insideapple.apple.com'],
    },
    'google.com': {
        'name': 'Google',
        'patterns': ['noreply@', 'payments-noreply@', 'googleplay-noreply@'],
        'receipt_type': ReceiptType.DIGITAL_PURCHASE,
        'is_subscription': True,
        'amount_range': (0.99, 500),
    },
    'notion.so': {
        'name': 'Notion',
        'patterns': ['noreply@', 'billing@', 'team@makenotion.com'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (8, 100),
    },
    'slack.com': {
        'name': 'Slack',
        'patterns': ['noreply@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (7, 500),
    },
    'zoom.us': {
        'name': 'Zoom',
        'patterns': ['noreply@', 'billing@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (14, 200),
    },
    'dropbox.com': {
        'name': 'Dropbox',
        'patterns': ['noreply@', 'no-reply@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (11, 200),
    },
    'adobe.com': {
        'name': 'Adobe',
        'patterns': ['noreply@', 'billing@', 'mail@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (10, 600),
    },

    # === ENTERTAINMENT ===
    'spotify.com': {
        'name': 'Spotify',
        'patterns': ['noreply@', 'no-reply@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (10, 18),
    },
    'netflix.com': {
        'name': 'Netflix',
        'patterns': ['info@', 'noreply@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (6, 23),
    },
    'hulu.com': {
        'name': 'Hulu',
        'patterns': ['noreply@', 'hulumail@'],
        'receipt_type': ReceiptType.SUBSCRIPTION_RENEWAL,
        'is_subscription': True,
        'amount_range': (7, 76),
    },

    # === RIDESHARE & DELIVERY ===
    'uber.com': {
        'name': 'Uber',
        'patterns': ['receipts@', 'noreply@', 'uber.us@'],
        'receipt_type': ReceiptType.TRIP_RECEIPT,
        'is_subscription': False,
        'amount_range': (5, 500),
    },
    'lyft.com': {
        'name': 'Lyft',
        'patterns': ['receipts@', 'no-reply@'],
        'receipt_type': ReceiptType.TRIP_RECEIPT,
        'is_subscription': False,
        'amount_range': (5, 300),
    },
    'doordash.com': {
        'name': 'DoorDash',
        'patterns': ['no-reply@', 'noreply@'],
        'receipt_type': ReceiptType.FOOD_ORDER,
        'is_subscription': False,
        'amount_range': (10, 200),
    },
    'grubhub.com': {
        'name': 'Grubhub',
        'patterns': ['orders@eat.grubhub.com', 'noreply@'],
        'receipt_type': ReceiptType.FOOD_ORDER,
        'is_subscription': False,
        'amount_range': (10, 200),
    },
    'instacart.com': {
        'name': 'Instacart',
        'patterns': ['noreply@', 'receipts@'],
        'receipt_type': ReceiptType.ORDER_CONFIRMATION,
        'is_subscription': False,
        'amount_range': (20, 500),
    },

    # === E-COMMERCE ===
    'amazon.com': {
        'name': 'Amazon',
        'patterns': ['auto-confirm@', 'ship-confirm@', 'digital-no-reply@'],
        'receipt_type': ReceiptType.ORDER_CONFIRMATION,
        'is_subscription': False,
        'amount_range': (1, 5000),
        # NOTE: marketing@amazon.com is BLOCKED separately
    },
    'target.com': {
        'name': 'Target',
        'patterns': ['noreply@', 'receipts@'],
        'receipt_type': ReceiptType.ORDER_CONFIRMATION,
        'is_subscription': False,
        'amount_range': (5, 1000),
    },
    'walmart.com': {
        'name': 'Walmart',
        'patterns': ['help@', 'noreply@'],
        'receipt_type': ReceiptType.ORDER_CONFIRMATION,
        'is_subscription': False,
        'amount_range': (5, 1000),
    },
    'costco.com': {
        'name': 'Costco',
        'patterns': ['customerservice@', 'noreply@'],
        'receipt_type': ReceiptType.ORDER_CONFIRMATION,
        'is_subscription': False,
        'amount_range': (20, 2000),
    },
    'bestbuy.com': {
        'name': 'Best Buy',
        'patterns': ['noreply@', 'orders@'],
        'receipt_type': ReceiptType.ORDER_CONFIRMATION,
        'is_subscription': False,
        'amount_range': (10, 3000),
    },

    # === TRAVEL ===
    'southwest.com': {
        'name': 'Southwest Airlines',
        'patterns': ['noreply@', 'SouthwestAirlines@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (50, 2000),
    },
    'delta.com': {
        'name': 'Delta',
        'patterns': ['noreply@', 'DeltaAirLines@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (50, 3000),
    },
    'airbnb.com': {
        'name': 'Airbnb',
        'patterns': ['automated@', 'express@', 'noreply@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (50, 5000),
    },
    'hotels.com': {
        'name': 'Hotels.com',
        'patterns': ['noreply@', 'reservations@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (50, 2000),
    },

    # === PAYMENT PROCESSORS (receipt forwarding) ===
    'stripe.com': {
        'name': 'Stripe',
        'patterns': ['receipts@', 'noreply@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (1, 10000),
        'subdomains': ['e.stripe.com'],
    },
    'square.com': {
        'name': 'Square',
        'patterns': ['receipts@', 'noreply@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (1, 5000),
    },
    'paypal.com': {
        'name': 'PayPal',
        'patterns': ['service@', 'noreply@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (1, 10000),
    },
    'venmo.com': {
        'name': 'Venmo',
        'patterns': ['noreply@', 'venmo@'],
        'receipt_type': ReceiptType.PAYMENT_RECEIPT,
        'is_subscription': False,
        'amount_range': (1, 5000),
    },
}


# =============================================================================
# BLOCKED DOMAINS (BLACKLIST)
# =============================================================================

BLOCKED_DOMAINS = {
    # Email marketing platforms
    'mailchimp.com', 'sendgrid.net', 'constantcontact.com', 'mailgun.org',
    'hubspot.com', 'mailerlite.com', 'klaviyo.com', 'brevo.com',
    'mixmax.com', 'intercom.io', 'drip.com', 'convertkit.com',
    'campaign-archive.com', 'list-manage.com',

    # Newsletter platforms
    'substack.com', 'beehiiv.com', 'ghost.io', 'revue.co',

    # Promotional Amazon subdomains
    'advertising.amazon.com', 'marketing.amazon.com',

    # Expense reports (not receipts)
    'expensify.com', 'expensifymail.com',

    # Political/news spam
    'conservativeinstitute.org', 'forbesbreak.com', 'dailywire.com',

    # School/community
    'wilsonk12tn.us', 'k12.com', 'schoolmessenger.com',

    # Surveys
    'surveymonkey.com', 'typeform.com', 'qualtrics.com',
}


# =============================================================================
# SUBJECT PATTERNS
# =============================================================================

# High-confidence receipt patterns (subject line)
RECEIPT_SUBJECT_PATTERNS = [
    r'your\s+receipt\s+from',
    r'order\s+confirm(?:ation|ed)',
    r'payment\s+confirm(?:ation|ed)',
    r'payment\s+received',
    r'your\s+(?:\w+\s+)?order\s+(?:has\s+been\s+)?(?:placed|confirmed)',
    r'your\s+purchase\s+(?:from|at)',
    r'receipt\s+for\s+(?:your\s+)?(?:order|purchase|payment)',
    r'order\s+#?\d+',
    r'invoice\s+#?\d+',
    r'you\s+(?:paid|charged)\s+\$',
    r'subscription\s+(?:renewed|activated|started)',
    r'monthly\s+(?:charge|payment|billing)',
    r'your\s+\$[\d,.]+\s+(?:order|purchase)',
    r'refund\s+(?:processed|issued|confirmed)',
    r'trip\s+(?:with|receipt)',
]

# Patterns that indicate NOT a receipt
NOT_RECEIPT_SUBJECT_PATTERNS = [
    r'^re:', r'^fwd:', r'^fw:',
    r'payment\s+(?:due|reminder|failed|declined)',
    r'(?:trial|subscription)\s+(?:ending|expiring)',
    r'upcoming\s+(?:charge|payment)',
    r'action\s+required',
    r'verify\s+your',
    r'confirm\s+your\s+(?:email|account)',
    r'welcome\s+to',
    r'getting\s+started',
    r'introducing',
    r'new\s+feature',
    r'weekly\s+digest',
    r'monthly\s+newsletter',
    r'save\s+\d+%',
    r'limited\s+time',
    r'flash\s+sale',
    r'don\'t\s+miss',
    r'last\s+chance',
    r'exclusive\s+(?:offer|deal)',
    r'shipped:',
    r'arriving:',
    r'out\s+for\s+delivery',
    r'tracking\s+(?:number|update)',
]


# =============================================================================
# RECEIPT CLASSIFIER
# =============================================================================

class ReceiptClassifier:
    """
    Production-grade receipt classifier.

    Uses a combination of:
    1. Domain whitelist/blacklist
    2. Subject pattern matching
    3. Body content analysis
    4. Amount extraction
    5. Learned patterns from user feedback
    """

    def __init__(self):
        self._domain_cache = {}
        self._learned_patterns = {}
        self._load_domain_cache()
        self._load_learned_patterns()

    def _load_domain_cache(self):
        """Build domain lookup cache from whitelist"""
        for domain, config in RECEIPT_SENDER_WHITELIST.items():
            self._domain_cache[domain.lower()] = config
            # Also add subdomains if specified
            for subdomain in config.get('subdomains', []):
                self._domain_cache[subdomain.lower()] = config

    def _load_learned_patterns(self):
        """Load patterns learned from user accept/reject actions"""
        try:
            conn = pymysql.connect(**MYSQL_CONFIG)
            cursor = conn.cursor()

            # Load rejection patterns
            cursor.execute('''
                SELECT pattern_type, pattern_value, rejection_count
                FROM incoming_rejection_patterns
                WHERE rejection_count >= 2
            ''')

            for row in cursor.fetchall():
                ptype = row['pattern_type']
                if ptype not in self._learned_patterns:
                    self._learned_patterns[ptype] = set()
                self._learned_patterns[ptype].add(row['pattern_value'].lower())

            conn.close()
        except Exception as e:
            print(f"Warning: Could not load learned patterns: {e}")

    def extract_domain(self, email: str) -> str:
        """Extract domain from email address"""
        if '@' in email:
            return email.split('@')[-1].lower()
        return email.lower()

    def is_whitelisted_domain(self, domain: str) -> Tuple[bool, Optional[Dict]]:
        """Check if domain is in whitelist"""
        domain_lower = domain.lower()

        # Direct match
        if domain_lower in self._domain_cache:
            return True, self._domain_cache[domain_lower]

        # Check parent domain (e.g., email.apple.com → apple.com)
        parts = domain_lower.split('.')
        for i in range(len(parts) - 1):
            parent = '.'.join(parts[i:])
            if parent in self._domain_cache:
                return True, self._domain_cache[parent]

        return False, None

    def is_blocked_domain(self, domain: str) -> bool:
        """Check if domain is blocked"""
        domain_lower = domain.lower()

        # Direct match
        if domain_lower in BLOCKED_DOMAINS:
            return True

        # Check if it's a subdomain of a blocked domain
        for blocked in BLOCKED_DOMAINS:
            if domain_lower.endswith('.' + blocked):
                return True

        # Check learned rejections
        if 'domain' in self._learned_patterns:
            if domain_lower in self._learned_patterns['domain']:
                return True

        return False

    def extract_amount(self, text: str) -> Optional[Decimal]:
        """Extract dollar amount from text"""
        if not text:
            return None

        patterns = [
            r'\$\s*([\d,]+\.?\d{0,2})',
            r'([\d,]+\.\d{2})\s*(?:USD|usd)',
            r'(?:Total|Amount|Charged|Price|Cost)[:\s]*\$?\s*([\d,]+\.?\d{0,2})',
            r'(?:You paid|Payment of|Charge of)[:\s]*\$?\s*([\d,]+\.?\d{0,2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    return Decimal(amount_str)
                except:
                    continue

        return None

    def matches_receipt_pattern(self, subject: str) -> Tuple[bool, Optional[str]]:
        """Check if subject matches receipt patterns"""
        subject_lower = subject.lower() if subject else ''

        for pattern in RECEIPT_SUBJECT_PATTERNS:
            if re.search(pattern, subject_lower, re.IGNORECASE):
                return True, pattern

        return False, None

    def matches_not_receipt_pattern(self, subject: str) -> Tuple[bool, Optional[str]]:
        """Check if subject matches non-receipt patterns"""
        subject_lower = subject.lower() if subject else ''

        for pattern in NOT_RECEIPT_SUBJECT_PATTERNS:
            if re.search(pattern, subject_lower, re.IGNORECASE):
                return True, pattern

        return False, None

    def classify(
        self,
        from_email: str,
        subject: str,
        body_snippet: str = '',
        has_attachment: bool = False
    ) -> ClassificationResult:
        """
        Classify an email as receipt or not.

        Returns ClassificationResult with confidence score and details.
        """
        signals = []
        rejection_reasons = []
        confidence = 50  # Start neutral

        domain = self.extract_domain(from_email)
        subject_lower = subject.lower() if subject else ''
        body_lower = body_snippet.lower() if body_snippet else ''

        # === STEP 1: BLACKLIST CHECK ===
        if self.is_blocked_domain(domain):
            return ClassificationResult(
                is_receipt=False,
                confidence=0,
                category=EmailCategory.MARKETING,
                receipt_type=None,
                rejection_reasons=[f"Blocked domain: {domain}"]
            )

        # === STEP 2: NEGATIVE SUBJECT PATTERNS ===
        is_not_receipt, matched_pattern = self.matches_not_receipt_pattern(subject)
        if is_not_receipt:
            rejection_reasons.append(f"Matches non-receipt pattern: {matched_pattern}")
            confidence -= 40

        # Forwards/replies are almost never receipts
        if subject_lower.startswith(('re:', 'fwd:', 'fw:')):
            return ClassificationResult(
                is_receipt=False,
                confidence=0,
                category=EmailCategory.PERSONAL,
                receipt_type=None,
                rejection_reasons=["Forward/reply - not a receipt"]
            )

        # === STEP 3: WHITELIST CHECK (HIGH CONFIDENCE) ===
        is_whitelisted, domain_config = self.is_whitelisted_domain(domain)

        if is_whitelisted:
            signals.append(f"Whitelisted domain: {domain_config['name']}")
            confidence += 40

            # Check if sender pattern matches expected
            for pattern in domain_config.get('patterns', []):
                if pattern in from_email.lower():
                    signals.append(f"Matches sender pattern: {pattern}")
                    confidence += 10
                    break

            # Extract and validate amount
            amount = self.extract_amount(subject + ' ' + body_snippet)
            amount_range = domain_config.get('amount_range', (0.01, 50000))

            if amount:
                signals.append(f"Found amount: ${amount}")
                if amount_range[0] <= float(amount) <= amount_range[1]:
                    signals.append("Amount in expected range")
                    confidence += 10
                else:
                    signals.append("Amount outside expected range")

            # Determine receipt type
            receipt_type = domain_config.get('receipt_type', ReceiptType.UNKNOWN)

            return ClassificationResult(
                is_receipt=True,
                confidence=min(100, max(0, confidence)),
                category=EmailCategory.RECEIPT,
                receipt_type=receipt_type,
                merchant_name=domain_config['name'],
                amount=amount,
                signals=signals,
                matched_domain_pattern=domain
            )

        # === STEP 4: SUBJECT PATTERN MATCHING ===
        is_receipt_subject, matched_pattern = self.matches_receipt_pattern(subject)

        if is_receipt_subject:
            signals.append(f"Matches receipt subject pattern: {matched_pattern}")
            confidence += 25

        # === STEP 5: CONTENT ANALYSIS ===
        # Receipt keywords
        receipt_keywords = [
            'receipt', 'invoice', 'order confirmation', 'payment confirmation',
            'purchase', 'charged', 'paid', 'total:', 'amount:', 'subtotal'
        ]

        keyword_matches = sum(1 for kw in receipt_keywords if kw in subject_lower or kw in body_lower)
        if keyword_matches > 0:
            signals.append(f"Found {keyword_matches} receipt keywords")
            confidence += keyword_matches * 5

        # Marketing keywords (negative)
        marketing_keywords = [
            'unsubscribe', 'view in browser', 'shop now', 'sale',
            'discount', 'promo', 'offer', 'deal', 'coupon'
        ]

        marketing_matches = sum(1 for kw in marketing_keywords if kw in subject_lower or kw in body_lower)
        if marketing_matches > 0:
            rejection_reasons.append(f"Found {marketing_matches} marketing keywords")
            confidence -= marketing_matches * 10

        # Has amount in subject (good sign)
        if '$' in subject or 'usd' in subject_lower:
            signals.append("Amount in subject line")
            confidence += 10

        # Has attachment (often receipts have PDF/image)
        if has_attachment:
            signals.append("Has attachment")
            confidence += 10

        # === STEP 6: EXTRACT DATA ===
        amount = self.extract_amount(subject + ' ' + body_snippet)

        # === STEP 7: FINAL DECISION ===
        confidence = min(100, max(0, confidence))

        # Determine category
        if confidence >= 70:
            category = EmailCategory.RECEIPT
            is_receipt = True
            receipt_type = ReceiptType.UNKNOWN
        elif marketing_matches >= 3:
            category = EmailCategory.MARKETING
            is_receipt = False
            receipt_type = None
        elif confidence < 40:
            category = EmailCategory.UNKNOWN
            is_receipt = False
            receipt_type = None
        else:
            # Borderline - lean towards receipt if we found an amount
            if amount:
                category = EmailCategory.RECEIPT
                is_receipt = True
                receipt_type = ReceiptType.UNKNOWN
            else:
                category = EmailCategory.UNKNOWN
                is_receipt = False
                receipt_type = None

        return ClassificationResult(
            is_receipt=is_receipt,
            confidence=confidence,
            category=category,
            receipt_type=receipt_type,
            amount=amount,
            signals=signals,
            rejection_reasons=rejection_reasons
        )

    def learn_from_rejection(self, from_email: str, subject: str, reason: str = None):
        """Learn from user rejection to improve future classification"""
        try:
            conn = pymysql.connect(**MYSQL_CONFIG)
            cursor = conn.cursor()

            domain = self.extract_domain(from_email)

            # Record domain rejection
            cursor.execute('''
                INSERT INTO incoming_rejection_patterns (pattern_type, pattern_value, rejection_count, last_rejected_at)
                VALUES ('domain', %s, 1, NOW())
                ON DUPLICATE KEY UPDATE rejection_count = rejection_count + 1, last_rejected_at = NOW()
            ''', (domain,))

            # Record sender rejection
            cursor.execute('''
                INSERT INTO incoming_rejection_patterns (pattern_type, pattern_value, rejection_count, last_rejected_at)
                VALUES ('sender', %s, 1, NOW())
                ON DUPLICATE KEY UPDATE rejection_count = rejection_count + 1, last_rejected_at = NOW()
            ''', (from_email.lower(),))

            conn.commit()
            conn.close()

            # Update local cache
            if 'domain' not in self._learned_patterns:
                self._learned_patterns['domain'] = set()
            self._learned_patterns['domain'].add(domain)

        except Exception as e:
            print(f"Error learning from rejection: {e}")

    def learn_from_acceptance(self, from_email: str, merchant: str, amount: float):
        """Learn from user acceptance to improve future classification"""
        try:
            domain = self.extract_domain(from_email)

            # If domain is not whitelisted, consider adding it
            is_whitelisted, _ = self.is_whitelisted_domain(domain)
            if not is_whitelisted:
                # Could add to a "candidate whitelist" table for review
                # For now, just reduce rejection count if any
                conn = pymysql.connect(**MYSQL_CONFIG)
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE incoming_rejection_patterns
                    SET rejection_count = GREATEST(0, rejection_count - 1)
                    WHERE pattern_type = 'domain' AND pattern_value = %s
                ''', (domain,))

                conn.commit()
                conn.close()

        except Exception as e:
            print(f"Error learning from acceptance: {e}")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_classifier() -> ReceiptClassifier:
    """Get singleton classifier instance"""
    if not hasattr(get_classifier, '_instance'):
        get_classifier._instance = ReceiptClassifier()
    return get_classifier._instance


def classify_email(from_email: str, subject: str, body: str = '', has_attachment: bool = False) -> Dict:
    """Convenience function to classify an email"""
    classifier = get_classifier()
    result = classifier.classify(from_email, subject, body, has_attachment)
    return result.to_dict()


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import sys

    classifier = ReceiptClassifier()

    # Test some emails
    test_cases = [
        ('auto-confirm@amazon.com', 'Your Amazon.com order of Widget...', True),
        ('receipts@anthropic.com', 'Your receipt from Anthropic - $20.00', True),
        ('noreply@spotify.com', 'Your Spotify Premium subscription renewed', True),
        ('marketing@amazon.com', "Today's big deals just for you!", False),
        ('newsletter@substack.com', 'Weekly digest from Tech News', False),
        ('receipts@uber.com', 'Your trip with Uber - $24.56', True),
        ('noreply@random-company.com', 'Welcome to our service!', False),
    ]

    print("Receipt Classifier Test\n" + "="*60)

    for from_email, subject, expected in test_cases:
        result = classifier.classify(from_email, subject)
        status = "✓" if result.is_receipt == expected else "✗"
        print(f"\n{status} {from_email}")
        print(f"  Subject: {subject}")
        print(f"  Is Receipt: {result.is_receipt} (expected: {expected})")
        print(f"  Confidence: {result.confidence}")
        print(f"  Category: {result.category.value}")
        if result.signals:
            print(f"  Signals: {', '.join(result.signals[:3])}")
        if result.rejection_reasons:
            print(f"  Rejections: {', '.join(result.rejection_reasons[:3])}")
