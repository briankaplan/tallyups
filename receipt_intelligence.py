#!/usr/bin/env python3
"""
Receipt Intelligence Engine
============================
World-class, merchant-driven receipt detection system.

Philosophy: Don't guess if something is a receipt.
           KNOW it's a receipt because it's from a known merchant.

Architecture:
1. Merchant Email Domains - whitelist of known receipt senders
2. Subscription Awareness - expected receipts at known intervals
3. Smart Capture Pipeline - download/screenshot → convert → R2
4. Learning Loop - auto-learn from accepted receipts
"""

import os
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
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIGURATION - Use centralized db_config (no hardcoded credentials)
# =============================================================================

def _get_mysql_config():
    """Get MySQL config from centralized db_config module."""
    try:
        from db_config import get_db_config
        config = get_db_config()
        if config:
            config['cursorclass'] = pymysql.cursors.DictCursor
            return config
    except ImportError:
        pass

    # Fallback to environment variables only (NO hardcoded defaults)
    host = os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST')
    user = os.getenv('MYSQLUSER') or os.getenv('MYSQL_USER')
    password = os.getenv('MYSQLPASSWORD') or os.getenv('MYSQL_PASSWORD')

    if not all([host, user, password]):
        return None

    return {
        'host': host,
        'port': int(os.getenv('MYSQLPORT', os.getenv('MYSQL_PORT', '3306'))),
        'user': user,
        'password': password,
        'database': os.getenv('MYSQLDATABASE', os.getenv('MYSQL_DATABASE', 'railway')),
        'charset': 'utf8mb4',
        'cursorclass': pymysql.cursors.DictCursor
    }

MYSQL_CONFIG = _get_mysql_config()


# =============================================================================
# DATA MODELS
# =============================================================================

class ReceiptConfidence(Enum):
    """Confidence levels for receipt detection"""
    CERTAIN = 100      # From known merchant domain with amount match
    HIGH = 90          # From known merchant domain
    MEDIUM = 70        # Matches receipt patterns + has amount
    LOW = 50           # Matches some patterns
    NONE = 0           # Not a receipt


@dataclass
class MerchantDomain:
    """A known merchant email domain"""
    id: int
    merchant_id: Optional[int]
    merchant_name: str
    email_domain: str
    email_patterns: List[str]  # e.g., ["receipts@", "billing@", "noreply@"]
    is_subscription: bool
    billing_cycle_days: Optional[int]  # 30 for monthly, 365 for yearly
    expected_amount_min: Optional[Decimal]
    expected_amount_max: Optional[Decimal]
    confidence: int
    receipt_count: int
    last_receipt_date: Optional[datetime]
    category: Optional[str]


@dataclass
class ReceiptCandidate:
    """An email that might be a receipt"""
    email_id: str
    from_email: str
    from_domain: str
    subject: str
    body_snippet: str
    received_date: datetime
    has_attachment: bool
    attachments: List[Dict]

    # Detection results
    confidence: ReceiptConfidence = ReceiptConfidence.NONE
    confidence_score: int = 0
    matched_merchant: Optional[MerchantDomain] = None
    extracted_amount: Optional[Decimal] = None
    extracted_merchant_name: Optional[str] = None
    rejection_reason: Optional[str] = None

    # Matching
    matched_transaction_id: Optional[int] = None
    match_type: str = 'new'  # 'new', 'needs_receipt', 'has_receipt'


# =============================================================================
# MERCHANT EMAIL DOMAIN MAPPING
# =============================================================================

# Comprehensive mapping of merchants to their email domains
# This is the SINGLE SOURCE OF TRUTH for receipt detection

MERCHANT_EMAIL_MAPPING = {
    # =========================================================================
    # AI & DEVELOPMENT TOOLS (High Priority - Subscriptions)
    # =========================================================================
    'Anthropic': {
        'domains': ['anthropic.com'],
        'patterns': ['receipts@', 'billing@', 'noreply@'],
        'is_subscription': True,
        'amount_range': (20.00, 200.00),
        'category': 'Software & Subscriptions',
        'aliases': ['Claude AI', 'CLAUDE.AI SUBSCRIPTION', 'ANTHROPIC']
    },
    'OpenAI': {
        'domains': ['openai.com'],
        'patterns': ['noreply@', 'receipts@'],
        'is_subscription': True,
        'amount_range': (20.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['ChatGPT', 'GPT-4']
    },
    'Midjourney': {
        'domains': ['midjourney.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (10.00, 120.00),
        'category': 'Software & Subscriptions',
        'aliases': ['MIDJOURNEY INC.', 'MIDJOURNEY INC']
    },
    'Cursor': {
        'domains': ['cursor.sh', 'cursor.com'],
        'patterns': ['team@', 'billing@', 'noreply@'],
        'is_subscription': True,
        'amount_range': (1.00, 200.00),
        'category': 'Software & Subscriptions',
        'aliases': ['CURSOR AI POWERED IDE', 'CURSOR USAGE']
    },
    'GitHub': {
        'domains': ['github.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (4.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['GITHUB']
    },
    'Sourcegraph': {
        'domains': ['sourcegraph.com'],
        'patterns': ['billing@', 'noreply@'],
        'is_subscription': True,
        'amount_range': (9.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['SOURCEGRAPH INC']
    },
    'Hugging Face': {
        'domains': ['huggingface.co'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (9.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['HUGGINGFACE']
    },
    'Ada AI': {
        'domains': ['ada.ai', 'im-ada.ai'],
        'patterns': ['noreply@', 'billing@', 'receipts@'],
        'is_subscription': True,
        'amount_range': (40.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['IM-ADA.AI']
    },

    # =========================================================================
    # CLOUD & INFRASTRUCTURE
    # =========================================================================
    'Cloudflare': {
        'domains': ['cloudflare.com'],
        'patterns': ['billing@', 'noreply@'],
        'is_subscription': True,
        'amount_range': (5.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['CLOUDFLARE']
    },
    'Railway': {
        'domains': ['railway.app'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (1.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['RAILWAY']
    },
    'Vercel': {
        'domains': ['vercel.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (20.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['VERCEL']
    },
    'DigitalOcean': {
        'domains': ['digitalocean.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (5.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['DIGITALOCEAN']
    },
    'AWS': {
        'domains': ['amazon.com', 'aws.amazon.com', 'amazonaws.com'],
        'patterns': ['no-reply@', 'billing@', 'aws-receivables-support@'],
        'is_subscription': True,
        'amount_range': (0.01, 10000.00),
        'category': 'Software & Subscriptions',
        'aliases': ['AWS', 'AMAZON WEB SERVICES']
    },
    'Heroku': {
        'domains': ['heroku.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (7.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['HEROKU']
    },
    'Netlify': {
        'domains': ['netlify.com'],
        'patterns': ['team@', 'billing@'],
        'is_subscription': True,
        'amount_range': (19.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['NETLIFY']
    },

    # =========================================================================
    # PRODUCTIVITY & BUSINESS TOOLS
    # =========================================================================
    'Apple': {
        'domains': ['apple.com', 'email.apple.com', 'insideapple.apple.com'],
        'patterns': ['no_reply@', 'noreply@', 'do_not_reply@'],
        'is_subscription': True,
        'amount_range': (0.99, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['APPLE.COM/BILL', 'APPLE.COM', 'APPLE STORE', 'APP STORE']
    },
    'Google': {
        'domains': ['google.com', 'googlemail.com'],
        'patterns': ['noreply@', 'payments-noreply@', 'googleplay-noreply@'],
        'is_subscription': True,
        'amount_range': (0.99, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['GOOGLE', 'GOOGLE PLAY', 'GOOGLE ONE', 'GOOGLE CLOUD']
    },
    'Microsoft': {
        'domains': ['microsoft.com', 'microsoftonline.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (6.99, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['MICROSOFT', 'MICROSOFT 365', 'AZURE']
    },
    'Notion': {
        'domains': ['notion.so', 'notion.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (8.00, 100.00),
        'category': 'Software & Subscriptions',
        'aliases': ['NOTION']
    },
    'Slack': {
        'domains': ['slack.com'],
        'patterns': ['noreply@', 'billing@', 'feedback@'],
        'is_subscription': True,
        'amount_range': (7.25, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['SLACK']
    },
    'Zoom': {
        'domains': ['zoom.us', 'zoom.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (14.99, 200.00),
        'category': 'Software & Subscriptions',
        'aliases': ['ZOOM']
    },
    'Dropbox': {
        'domains': ['dropbox.com'],
        'patterns': ['noreply@', 'no-reply@'],
        'is_subscription': True,
        'amount_range': (11.99, 200.00),
        'category': 'Software & Subscriptions',
        'aliases': ['DROPBOX']
    },
    'Adobe': {
        'domains': ['adobe.com'],
        'patterns': ['noreply@', 'billing@', 'mail@'],
        'is_subscription': True,
        'amount_range': (10.99, 600.00),
        'category': 'Software & Subscriptions',
        'aliases': ['ADOBE', 'ADOBE CREATIVE CLOUD']
    },
    'Figma': {
        'domains': ['figma.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (12.00, 100.00),
        'category': 'Software & Subscriptions',
        'aliases': ['FIGMA']
    },
    'Canva': {
        'domains': ['canva.com'],
        'patterns': ['noreply@', 'support@'],
        'is_subscription': True,
        'amount_range': (12.99, 200.00),
        'category': 'Software & Subscriptions',
        'aliases': ['CANVA']
    },
    'Hive': {
        'domains': ['hive.com'],
        'patterns': ['noreply@', 'billing@', 'team@'],
        'is_subscription': True,
        'amount_range': (12.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['HIVE CO', 'HIVE']
    },
    'Expensify': {
        'domains': ['expensify.com'],
        'patterns': ['receipts@', 'concierge@', 'noreply@'],
        'is_subscription': True,
        'amount_range': (5.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['EXPENSIFY INC.', 'EXPENSIFY']
    },
    'CalendarBridge': {
        'domains': ['calendarbridge.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (10.00, 20.00),
        'category': 'Software & Subscriptions',
        'aliases': ['CALENDARBRIDGE']
    },
    'EasyFAQ': {
        'domains': ['easyfaq.io'],
        'patterns': ['noreply@', 'support@'],
        'is_subscription': True,
        'amount_range': (4.00, 10.00),
        'category': 'Software & Subscriptions',
        'aliases': ['EASYFAQ.IO']
    },
    'Chartmetric': {
        'domains': ['chartmetric.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (100.00, 200.00),
        'category': 'Software & Subscriptions',
        'aliases': ['CHARTMETRIC']
    },
    'IMDbPro': {
        'domains': ['imdb.com', 'imdbpro.com'],
        'patterns': ['noreply@', 'do-not-reply@'],
        'is_subscription': True,
        'amount_range': (19.99, 30.00),
        'category': 'Software & Subscriptions',
        'aliases': ['IMDBPRO']
    },

    # =========================================================================
    # ENTERTAINMENT & MEDIA
    # =========================================================================
    'Spotify': {
        'domains': ['spotify.com'],
        'patterns': ['noreply@', 'no-reply@'],
        'is_subscription': True,
        'amount_range': (10.99, 17.99),
        'category': 'Entertainment',
        'aliases': ['SPOTIFY USA', 'SPOTIFY']
    },
    'Netflix': {
        'domains': ['netflix.com'],
        'patterns': ['info@', 'noreply@'],
        'is_subscription': True,
        'amount_range': (6.99, 22.99),
        'category': 'Entertainment',
        'aliases': ['NETFLIX']
    },
    'Hulu': {
        'domains': ['hulu.com'],
        'patterns': ['noreply@', 'hulumail@'],
        'is_subscription': True,
        'amount_range': (7.99, 75.99),
        'category': 'Entertainment',
        'aliases': ['HULU']
    },
    'Disney+': {
        'domains': ['disney.com', 'disneyplus.com'],
        'patterns': ['noreply@', 'disneyplus@'],
        'is_subscription': True,
        'amount_range': (7.99, 13.99),
        'category': 'Entertainment',
        'aliases': ['DISNEY PLUS', 'DISNEY+']
    },
    'YouTube': {
        'domains': ['youtube.com'],
        'patterns': ['noreply@'],
        'is_subscription': True,
        'amount_range': (11.99, 22.99),
        'category': 'Entertainment',
        'aliases': ['YOUTUBE PREMIUM', 'YOUTUBE TV']
    },
    'Cowboy Channel': {
        'domains': ['cowboychannel.com', 'thecowboychannel.com'],
        'patterns': ['noreply@', 'support@'],
        'is_subscription': True,
        'amount_range': (9.99, 15.00),
        'category': 'Entertainment',
        'aliases': ['COWBOY CHANNEL PLUS']
    },

    # =========================================================================
    # TRAVEL & TRANSPORTATION
    # =========================================================================
    'Uber': {
        'domains': ['uber.com'],
        'patterns': ['receipts@', 'noreply@', 'uber.us@'],
        'is_subscription': False,
        'amount_range': (5.00, 500.00),
        'category': 'Travel',
        'aliases': ['UBER *TRIP', 'UBER', 'UBER EATS']
    },
    'Lyft': {
        'domains': ['lyft.com'],
        'patterns': ['receipts@', 'no-reply@'],
        'is_subscription': False,
        'amount_range': (5.00, 300.00),
        'category': 'Travel',
        'aliases': ['LYFT']
    },
    'Southwest': {
        'domains': ['southwest.com', 'ifly.southwest.com'],
        'patterns': ['noreply@', 'SouthwestAirlines@'],
        'is_subscription': False,
        'amount_range': (50.00, 1000.00),
        'category': 'Travel',
        'aliases': ['SOUTHWEST AIRLINES']
    },
    'Delta': {
        'domains': ['delta.com'],
        'patterns': ['noreply@', 'DeltaAirLines@'],
        'is_subscription': False,
        'amount_range': (50.00, 2000.00),
        'category': 'Travel',
        'aliases': ['DELTA AIRLINES', 'DELTA AIR LINES']
    },
    'American Airlines': {
        'domains': ['aa.com', 'americanairlines.com'],
        'patterns': ['noreply@', 'notify@'],
        'is_subscription': False,
        'amount_range': (50.00, 2000.00),
        'category': 'Travel',
        'aliases': ['AMERICAN AIRLINES', 'AA']
    },
    'United': {
        'domains': ['united.com'],
        'patterns': ['noreply@', 'united-reservations@'],
        'is_subscription': False,
        'amount_range': (50.00, 2000.00),
        'category': 'Travel',
        'aliases': ['UNITED AIRLINES']
    },
    'Airbnb': {
        'domains': ['airbnb.com'],
        'patterns': ['automated@', 'express@', 'noreply@'],
        'is_subscription': False,
        'amount_range': (50.00, 5000.00),
        'category': 'Travel',
        'aliases': ['AIRBNB']
    },
    'Hotels.com': {
        'domains': ['hotels.com'],
        'patterns': ['noreply@', 'reservations@'],
        'is_subscription': False,
        'amount_range': (50.00, 2000.00),
        'category': 'Travel',
        'aliases': ['HOTELS.COM']
    },
    'Marriott': {
        'domains': ['marriott.com'],
        'patterns': ['noreply@', 'marriott@'],
        'is_subscription': False,
        'amount_range': (100.00, 2000.00),
        'category': 'Travel',
        'aliases': ['MARRIOTT']
    },
    'Hilton': {
        'domains': ['hilton.com'],
        'patterns': ['noreply@', 'hilton@'],
        'is_subscription': False,
        'amount_range': (100.00, 2000.00),
        'category': 'Travel',
        'aliases': ['HILTON']
    },
    'HotelTonight': {
        'domains': ['hoteltonight.com'],
        'patterns': ['noreply@', 'reservations@'],
        'is_subscription': False,
        'amount_range': (50.00, 1000.00),
        'category': 'Travel',
        'aliases': ['HOTEL TONIGHT']
    },

    # =========================================================================
    # FOOD & DELIVERY
    # =========================================================================
    'DoorDash': {
        'domains': ['doordash.com'],
        'patterns': ['noreply@', 'no-reply@'],
        'is_subscription': False,
        'amount_range': (10.00, 200.00),
        'category': 'Food & Dining',
        'aliases': ['DOORDASH']
    },
    'Grubhub': {
        'domains': ['grubhub.com'],
        'patterns': ['noreply@', 'orders@'],
        'is_subscription': False,
        'amount_range': (10.00, 200.00),
        'category': 'Food & Dining',
        'aliases': ['GRUBHUB']
    },
    'Instacart': {
        'domains': ['instacart.com'],
        'patterns': ['noreply@', 'receipts@'],
        'is_subscription': False,
        'amount_range': (20.00, 500.00),
        'category': 'Food & Dining',
        'aliases': ['INSTACART']
    },
    'Postmates': {
        'domains': ['postmates.com'],
        'patterns': ['noreply@', 'receipts@'],
        'is_subscription': False,
        'amount_range': (10.00, 200.00),
        'category': 'Food & Dining',
        'aliases': ['POSTMATES']
    },

    # =========================================================================
    # E-COMMERCE & RETAIL
    # =========================================================================
    'Amazon': {
        'domains': ['amazon.com'],
        'patterns': ['auto-confirm@', 'ship-confirm@', 'order-update@', 'digital-no-reply@'],
        'is_subscription': False,
        'amount_range': (1.00, 5000.00),
        'category': 'Shopping',
        'aliases': ['AMAZON', 'AMZN', 'AMAZON MARKETPLACE']
    },
    'Target': {
        'domains': ['target.com'],
        'patterns': ['noreply@', 'orders@'],
        'is_subscription': False,
        'amount_range': (5.00, 1000.00),
        'category': 'Shopping',
        'aliases': ['TARGET']
    },
    'Walmart': {
        'domains': ['walmart.com'],
        'patterns': ['noreply@', 'help@'],
        'is_subscription': False,
        'amount_range': (5.00, 1000.00),
        'category': 'Shopping',
        'aliases': ['WALMART', 'WAL-MART']
    },
    'Best Buy': {
        'domains': ['bestbuy.com'],
        'patterns': ['noreply@', 'orders@'],
        'is_subscription': False,
        'amount_range': (10.00, 5000.00),
        'category': 'Shopping',
        'aliases': ['BEST BUY', 'BESTBUY']
    },

    # =========================================================================
    # PAYMENT PROCESSORS (Always send receipts)
    # =========================================================================
    'Stripe': {
        'domains': ['stripe.com'],
        'patterns': ['receipts@', 'noreply@', 'billing@'],
        'is_subscription': False,
        'amount_range': (0.50, 50000.00),
        'category': 'Payment',
        'aliases': ['STRIPE']
    },
    'PayPal': {
        'domains': ['paypal.com'],
        'patterns': ['service@', 'noreply@'],
        'is_subscription': False,
        'amount_range': (0.01, 50000.00),
        'category': 'Payment',
        'aliases': ['PAYPAL']
    },
    'Square': {
        'domains': ['square.com', 'squareup.com'],
        'patterns': ['receipts@', 'noreply@'],
        'is_subscription': False,
        'amount_range': (1.00, 10000.00),
        'category': 'Payment',
        'aliases': ['SQUARE', 'SQ *']
    },
    'Venmo': {
        'domains': ['venmo.com'],
        'patterns': ['venmo@', 'noreply@'],
        'is_subscription': False,
        'amount_range': (1.00, 5000.00),
        'category': 'Payment',
        'aliases': ['VENMO']
    },

    # =========================================================================
    # UTILITIES & SERVICES
    # =========================================================================
    'SimpleTexting': {
        'domains': ['simpletexting.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (25.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['SIMPLETEXTING']
    },
    'Taskade': {
        'domains': ['taskade.com'],
        'patterns': ['noreply@', 'hello@'],
        'is_subscription': True,
        'amount_range': (5.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['TASKADE']
    },
    'Every Studio': {
        'domains': ['every.to', 'every.studio'],
        'patterns': ['noreply@', 'hello@'],
        'is_subscription': True,
        'amount_range': (3.00, 10.00),
        'category': 'Software & Subscriptions',
        'aliases': ['EVERY STUDIO']
    },
    'Runway': {
        'domains': ['runwayml.com', 'runway.ml'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (12.00, 100.00),
        'category': 'Software & Subscriptions',
        'aliases': ['RUNWAY', 'RUNWAYML']
    },
    'Ideogram': {
        'domains': ['ideogram.ai'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (7.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['IDEOGRAM']
    },
    'Beautiful.ai': {
        'domains': ['beautiful.ai'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (12.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['BEAUTIFUL.AI']
    },

    # =========================================================================
    # ADDITIONAL MERCHANTS (from transaction history)
    # =========================================================================
    'CalendarBridge': {
        'domains': ['calendarbridge.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (5.00, 20.00),
        'category': 'Software & Subscriptions',
        'aliases': ['CALENDARBRIDGE']
    },
    'TDS Telecom': {
        'domains': ['tdstelecom.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (50.00, 200.00),
        'category': 'Utilities',
        'aliases': ['TDS TELECOM', 'TDS']
    },
    'Cima Solutions': {
        'domains': ['cimacares.com'],
        'patterns': ['noreply@', 'billing@', 'receipts@'],
        'is_subscription': True,
        'amount_range': (50.00, 200.00),
        'category': 'Healthcare',
        'aliases': ['CIMA SOLUTIONS', 'CIMA']
    },
    'Performance Lawns': {
        'domains': ['clearent.com', 'serviceautopilot.com'],
        'patterns': ['noreply@', 'receipts@'],
        'is_subscription': True,
        'amount_range': (50.00, 500.00),
        'category': 'Services',
        'aliases': ['PERFORMANCE LAWNS']
    },
    'GoDaddy': {
        'domains': ['godaddy.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (10.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['GODADDY']
    },
    'Paige': {
        'domains': ['paige.com'],
        'patterns': ['noreply@', 'orders@'],
        'is_subscription': False,
        'amount_range': (50.00, 1000.00),
        'category': 'Shopping',
        'aliases': ['PAIGE']
    },
    'Sonic Drive-In': {
        'domains': ['sonicdrivein.com'],
        'patterns': ['noreply@', 'orders@'],
        'is_subscription': False,
        'amount_range': (5.00, 50.00),
        'category': 'Food & Drink',
        'aliases': ['SONIC DRIVE-IN', 'SONIC']
    },
    'Speedpay/Kia Finance': {
        'domains': ['speedpay.com'],
        'patterns': ['noreply@'],
        'is_subscription': True,
        'amount_range': (200.00, 1000.00),
        'category': 'Auto',
        'aliases': ['KIA FINANCE', 'KIA']
    },
    'AdaptHealth': {
        'domains': ['adapthealth.com'],
        'patterns': ['noreply@', 'autopay@'],
        'is_subscription': True,
        'amount_range': (20.00, 200.00),
        'category': 'Healthcare',
        'aliases': ['ADAPTHEALTH', 'OXYGEN & SLEEP']
    },
    'SuitSupply': {
        'domains': ['service.suitsupply.com', 'suitsupply.com'],
        'patterns': ['noreply@', 'service@'],
        'is_subscription': False,
        'amount_range': (100.00, 2000.00),
        'category': 'Shopping',
        'aliases': ['SUITSUPPLY']
    },
    'Adventure Park': {
        'domains': ['myadventurepark.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (10.00, 200.00),
        'category': 'Entertainment',
        'aliases': ['ADVENTURE PARK']
    },
    'ROSTR': {
        'domains': ['rostr.cc'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (30.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['ROSTR']
    },
    'EM.co': {
        'domains': ['em.co'],
        'patterns': ['noreply@', 'invoices@'],
        'is_subscription': False,
        'amount_range': (50.00, 5000.00),
        'category': 'Business Services',
        'aliases': ['EMCO', 'EM.CO']
    },
    'FinsRule': {
        'domains': ['finsrule.com'],
        'patterns': ['noreply@', 'invoices@'],
        'is_subscription': False,
        'amount_range': (100.00, 5000.00),
        'category': 'Business Services',
        'aliases': ['FINSRULE']
    },
    'Nordstrom': {
        'domains': ['eml.nordstrom.com', 'nordstrom.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (50.00, 2000.00),
        'category': 'Shopping',
        'aliases': ['NORDSTROM']
    },
    'Golden Nugget': {
        'domains': ['goldennugget.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (100.00, 2000.00),
        'category': 'Travel',
        'aliases': ['GOLDEN NUGGET']
    },
    'Little Caesars': {
        'domains': ['littlecaesars.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (5.00, 100.00),
        'category': 'Food & Drink',
        'aliases': ['LITTLE CAESARS']
    },
    'DISCO': {
        'domains': ['payments.disco.ac', 'disco.ac'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (50.00, 200.00),
        'category': 'Software & Subscriptions',
        'aliases': ['DISCO']
    },
    'Pika': {
        'domains': ['pika.art'],
        'patterns': ['noreply@'],
        'is_subscription': True,
        'amount_range': (10.00, 100.00),
        'category': 'Software & Subscriptions',
        'aliases': ['PIKA']
    },
    'Render': {
        'domains': ['render.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (0.50, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['RENDER']
    },
    'Chick-fil-A': {
        'domains': ['chick-fil-a.com', 'email.chick-fil-a.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (5.00, 100.00),
        'category': 'Food & Drink',
        'aliases': ['CHICK-FIL-A', 'CHICKFILA']
    },
    'Kit (ConvertKit)': {
        'domains': ['convertkit.com'],
        'patterns': ['billing@'],
        'is_subscription': True,
        'amount_range': (25.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['KIT', 'CONVERTKIT']
    },
    'Pond5': {
        'domains': ['e.pond5.com', 'pond5.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (10.00, 1000.00),
        'category': 'Software & Subscriptions',
        'aliases': ['POND5']
    },
    'Burger King': {
        'domains': ['mail.burgerking.com', 'burgerking.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (5.00, 50.00),
        'category': 'Food & Drink',
        'aliases': ['BURGER KING']
    },
    'Incogni (Paddle)': {
        'domains': ['paddle.com'],
        'patterns': ['noreply@'],
        'is_subscription': True,
        'amount_range': (5.00, 100.00),
        'category': 'Software & Subscriptions',
        'aliases': ['PADDLE', 'INCOGNI']
    },
    'Peppermill Casino': {
        'domains': ['peppermillreno.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (100.00, 2000.00),
        'category': 'Travel',
        'aliases': ['PEPPERMILL']
    },
    'RetroSupply': {
        'domains': ['t.shopifyemail.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (10.00, 200.00),
        'category': 'Shopping',
        'aliases': ['RETROSUPPLY']
    },
    'Zappos': {
        'domains': ['zappos.com'],
        'patterns': ['noreply@', 'cs@'],
        'is_subscription': False,
        'amount_range': (20.00, 500.00),
        'category': 'Shopping',
        'aliases': ['ZAPPOS']
    },
    'Red Robin': {
        'domains': ['ziosk.com', 'redrobin.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (10.00, 100.00),
        'category': 'Food & Drink',
        'aliases': ['RED ROBIN']
    },
    'Have I Been Pwned': {
        'domains': ['haveibeenpwned.com'],
        'patterns': ['noreply@'],
        'is_subscription': True,
        'amount_range': (3.00, 10.00),
        'category': 'Software & Subscriptions',
        'aliases': ['HIBP']
    },
    'Suno': {
        'domains': ['suno.ai', 'suno.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (10.00, 150.00),
        'category': 'Software & Subscriptions',
        'aliases': ['SUNO']
    },
    'Davinci AI': {
        'domains': ['davinci.ai'],
        'patterns': ['noreply@'],
        'is_subscription': True,
        'amount_range': (10.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['DAVINCI']
    },
    'Charles Tyrwhitt': {
        'domains': ['ctshirts.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (50.00, 500.00),
        'category': 'Shopping',
        'aliases': ['CHARLES TYRWHITT']
    },
    'TeamSnap': {
        'domains': ['email.teamsnap.com', 'teamsnap.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (0.00, 500.00),
        'category': 'Sports & Fitness',
        'aliases': ['TEAMSNAP']
    },
    'Noise New Media': {
        'domains': ['noisenewmedia.com'],
        'patterns': ['noreply@', 'invoices@'],
        'is_subscription': False,
        'amount_range': (100.00, 1000.00),
        'category': 'Business Services',
        'aliases': ['NOISE NEW MEDIA']
    },
    'Mercer & Ross': {
        'domains': ['mercerandross.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (500.00, 10000.00),
        'category': 'Business Services',
        'aliases': ['MERCER AND ROSS']
    },
    'Chartmetric': {
        'domains': ['chartmetric.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (100.00, 500.00),
        'category': 'Software & Subscriptions',
        'aliases': ['CHARTMETRIC']
    },
    'Ada AI': {
        'domains': ['ada.ai', 'im-ada.ai'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (25.00, 100.00),
        'category': 'Software & Subscriptions',
        'aliases': ['ADA AI', 'ADA']
    },
    'Shortwave': {
        'domains': ['shortwave.com'],
        'patterns': ['noreply@', 'billing@'],
        'is_subscription': True,
        'amount_range': (5.00, 50.00),
        'category': 'Software & Subscriptions',
        'aliases': ['SHORTWAVE']
    },
    'Hugging Face': {
        'domains': ['huggingface.co'],
        'patterns': ['noreply@'],
        'is_subscription': True,
        'amount_range': (5.00, 100.00),
        'category': 'Software & Subscriptions',
        'aliases': ['HUGGING FACE', 'HUGGINGFACE']
    },
    'Inter-State Studio': {
        'domains': ['inter-state.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (20.00, 200.00),
        'category': 'Photography',
        'aliases': ['INTER-STATE STUDIO']
    },
    'Best Buy': {
        'domains': ['emailinfo.bestbuy.com', 'bestbuy.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (10.00, 5000.00),
        'category': 'Shopping',
        'aliases': ['BEST BUY', 'BESTBUY']
    },
    'HangTag Parking': {
        'domains': ['hangtag.io'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (5.00, 100.00),
        'category': 'Parking',
        'aliases': ['HANGTAG']
    },
    'Popmenu': {
        'domains': ['popmenu.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (5.00, 100.00),
        'category': 'Food & Drink',
        'aliases': ['POPMENU']
    },
    'TheraNest': {
        'domains': ['theranest.com'],
        'patterns': ['noreply@'],
        'is_subscription': False,
        'amount_range': (50.00, 500.00),
        'category': 'Healthcare',
        'aliases': ['THERANEST', 'SESSIONS PSYCHOLOGY']
    },
}

# =============================================================================
# ABSOLUTE BLOCKLIST - Never process emails from these domains
# =============================================================================

BLOCKED_DOMAINS = {
    # Marketing platforms (but NOT convertkit.com - they send billing receipts)
    'mailchimp.com', 'sendgrid.net', 'constantcontact.com', 'mailgun.org',
    'hubspot.com', 'mailerlite.com', 'klaviyo.com', 'brevo.com',
    'mixmax.com', 'intercom.io', 'drip.com',
    'campaign-archive.com', 'list-manage.com', 'createsend.com',

    # Social media
    'linkedin.com', 'facebook.com', 'twitter.com', 'x.com',
    'instagram.com', 'tiktok.com', 'pinterest.com', 'reddit.com',

    # News & content
    'substack.com', 'medium.com', 'ghost.io', 'beehiiv.com',
    'buttondown.email', 'revue.email',

    # Notifications (not receipts)
    'github.com/notifications', 'noreply.github.com',
    'notifications@github.com',  # GitHub notifs, not payments

    # Other noise
    'docusign.com', 'docusign.net',  # Contracts, not receipts
    'calendly.com',  # Scheduling, not receipts
    'typeform.com',  # Forms, not receipts
    'surveymonkey.com',  # Surveys
    'eventbrite.com',  # Events (unless ticket purchase)
}

# =============================================================================
# HIGH-CONFIDENCE RECEIPT PATTERNS
# =============================================================================

# These patterns, when matched, indicate HIGH confidence even from unknown domains
HIGH_CONFIDENCE_PATTERNS = [
    # Explicit receipt language with identifiers
    r'Your receipt from .+ #[A-Z0-9\-]+',
    r'Receipt for .+ #[A-Z0-9\-]+',
    r'Payment receipt #[A-Z0-9\-]+',
    r'Invoice #[A-Z0-9\-]+',
    r'Order #[A-Z0-9\-]+ confirmed',

    # Payment confirmations with amounts
    r'Payment of \$[\d,]+\.\d{2}',
    r'Charged \$[\d,]+\.\d{2}',
    r'You paid \$[\d,]+\.\d{2}',
    r'Amount: \$[\d,]+\.\d{2}',
    r'Total: \$[\d,]+\.\d{2}',

    # Subscription receipts
    r'subscription.*renewed.*\$[\d,]+\.\d{2}',
    r'monthly charge.*\$[\d,]+\.\d{2}',
    r'recurring payment.*\$[\d,]+\.\d{2}',
]

# =============================================================================
# RECEIPT INTELLIGENCE ENGINE
# =============================================================================

class ReceiptIntelligence:
    """
    World-class receipt detection engine.

    Uses merchant knowledge, not keyword guessing.
    """

    def __init__(self):
        self._domain_cache: Dict[str, MerchantDomain] = {}
        self._build_domain_cache()

    def _build_domain_cache(self):
        """Build fast lookup cache from merchant mapping"""
        for merchant_name, config in MERCHANT_EMAIL_MAPPING.items():
            for domain in config['domains']:
                domain_lower = domain.lower()
                amount_range = config.get('amount_range', (0.01, 50000.00))

                self._domain_cache[domain_lower] = MerchantDomain(
                    id=0,  # Will be set from DB
                    merchant_id=None,
                    merchant_name=merchant_name,
                    email_domain=domain_lower,
                    email_patterns=config.get('patterns', []),
                    is_subscription=config.get('is_subscription', False),
                    billing_cycle_days=30 if config.get('is_subscription') else None,
                    expected_amount_min=Decimal(str(amount_range[0])),
                    expected_amount_max=Decimal(str(amount_range[1])),
                    confidence=100,
                    receipt_count=0,
                    last_receipt_date=None,
                    category=config.get('category', 'General')
                )

    def extract_domain(self, email: str) -> str:
        """Extract domain from email address"""
        if not email:
            return ''
        # Handle "Name <email@domain.com>" format
        match = re.search(r'<(.+?)>', email)
        if match:
            email = match.group(1)
        # Extract domain
        if '@' in email:
            return email.split('@')[-1].lower()
        return ''

    def is_blocked_domain(self, domain: str) -> bool:
        """Check if domain is in absolute blocklist"""
        domain_lower = domain.lower()

        # Exact match
        if domain_lower in BLOCKED_DOMAINS:
            return True

        # Check for subdomain matches (e.g., "mail.mailchimp.com")
        for blocked in BLOCKED_DOMAINS:
            if domain_lower.endswith('.' + blocked) or domain_lower == blocked:
                return True

        return False

    def lookup_merchant_by_domain(self, domain: str) -> Optional[MerchantDomain]:
        """Look up merchant by email domain"""
        domain_lower = domain.lower()

        # Direct match
        if domain_lower in self._domain_cache:
            return self._domain_cache[domain_lower]

        # Check for subdomain matches (e.g., "email.apple.com" → "apple.com")
        parts = domain_lower.split('.')
        for i in range(len(parts) - 1):
            parent_domain = '.'.join(parts[i:])
            if parent_domain in self._domain_cache:
                return self._domain_cache[parent_domain]

        return None

    def extract_amount(self, text: str) -> Optional[Decimal]:
        """Extract dollar amount from text"""
        if not text:
            return None

        patterns = [
            r'\$\s*([\d,]+\.?\d{0,2})',  # $123.45 or $123
            r'([\d,]+\.\d{2})\s*(?:USD|usd)',  # 123.45 USD
            r'(?:Total|Amount|Charged|Price|Cost)[:\s]*\$?\s*([\d,]+\.?\d{0,2})',
            r'(?:You paid|Payment of)[:\s]*\$?\s*([\d,]+\.?\d{0,2})',
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

    def matches_high_confidence_pattern(self, subject: str, body: str = '') -> bool:
        """Check if email matches high-confidence receipt patterns"""
        text = f"{subject} {body}"
        for pattern in HIGH_CONFIDENCE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def analyze_email(self, candidate: ReceiptCandidate) -> ReceiptCandidate:
        """
        Analyze an email and determine if it's a receipt.

        Returns the candidate with confidence and match info populated.
        """
        domain = candidate.from_domain or self.extract_domain(candidate.from_email)
        candidate.from_domain = domain

        # Step 0: Check blocklist
        if self.is_blocked_domain(domain):
            candidate.confidence = ReceiptConfidence.NONE
            candidate.confidence_score = 0
            candidate.rejection_reason = f"Blocked domain: {domain}"
            return candidate

        # Step 1: Look up merchant by domain
        merchant = self.lookup_merchant_by_domain(domain)

        if merchant:
            candidate.matched_merchant = merchant
            candidate.extracted_merchant_name = merchant.merchant_name

            # Extract amount from subject/body
            amount = self.extract_amount(candidate.subject)
            if not amount:
                amount = self.extract_amount(candidate.body_snippet)
            candidate.extracted_amount = amount

            # Validate amount if we have expectations
            if amount and merchant.expected_amount_min and merchant.expected_amount_max:
                if merchant.expected_amount_min <= amount <= merchant.expected_amount_max:
                    candidate.confidence = ReceiptConfidence.CERTAIN
                    candidate.confidence_score = 100
                else:
                    # Amount outside expected range - still high confidence but flag it
                    candidate.confidence = ReceiptConfidence.HIGH
                    candidate.confidence_score = 90
            else:
                candidate.confidence = ReceiptConfidence.HIGH
                candidate.confidence_score = 90

            return candidate

        # Step 2: Check high-confidence patterns for unknown domains
        if self.matches_high_confidence_pattern(candidate.subject, candidate.body_snippet):
            amount = self.extract_amount(candidate.subject)
            if not amount:
                amount = self.extract_amount(candidate.body_snippet)

            if amount:
                candidate.confidence = ReceiptConfidence.MEDIUM
                candidate.confidence_score = 70
                candidate.extracted_amount = amount
                return candidate

        # Step 3: Not a receipt
        candidate.confidence = ReceiptConfidence.NONE
        candidate.confidence_score = 0
        candidate.rejection_reason = f"Unknown domain: {domain}"
        return candidate

    def should_capture(self, candidate: ReceiptCandidate) -> Tuple[bool, str]:
        """
        Determine if we should capture this email.

        Returns (should_capture, reason)
        """
        if candidate.confidence == ReceiptConfidence.NONE:
            return False, candidate.rejection_reason or "Not a receipt"

        if candidate.confidence in (ReceiptConfidence.CERTAIN, ReceiptConfidence.HIGH):
            merchant_name = candidate.matched_merchant.merchant_name if candidate.matched_merchant else "Unknown"
            return True, f"Known merchant: {merchant_name}"

        if candidate.confidence == ReceiptConfidence.MEDIUM:
            return True, "Matches receipt pattern"

        return False, "Low confidence"


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def get_db_connection():
    """Get MySQL database connection"""
    return pymysql.connect(**MYSQL_CONFIG)


def init_merchant_email_domains_table():
    """Create the merchant_email_domains table"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS merchant_email_domains (
                id INT AUTO_INCREMENT PRIMARY KEY,
                merchant_id INT,
                merchant_name VARCHAR(255) NOT NULL,
                email_domain VARCHAR(255) NOT NULL,
                email_patterns TEXT,
                is_subscription BOOLEAN DEFAULT FALSE,
                billing_cycle_days INT,
                expected_amount_min DECIMAL(10,2),
                expected_amount_max DECIMAL(10,2),
                confidence INT DEFAULT 100,
                receipt_count INT DEFAULT 0,
                last_receipt_date DATETIME,
                category VARCHAR(100),
                aliases TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_domain (email_domain),
                INDEX idx_merchant_id (merchant_id),
                INDEX idx_subscription (is_subscription),
                INDEX idx_category (category)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        conn.commit()
        print("Created merchant_email_domains table")
        return True
    except Exception as e:
        print(f"Error creating table: {e}")
        return False
    finally:
        conn.close()


def seed_merchant_email_domains():
    """Seed the merchant_email_domains table from MERCHANT_EMAIL_MAPPING"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        inserted = 0
        updated = 0

        for merchant_name, config in MERCHANT_EMAIL_MAPPING.items():
            amount_range = config.get('amount_range', (0.01, 50000.00))

            for domain in config['domains']:
                try:
                    cursor.execute('''
                        INSERT INTO merchant_email_domains
                        (merchant_name, email_domain, email_patterns, is_subscription,
                         billing_cycle_days, expected_amount_min, expected_amount_max,
                         confidence, category, aliases)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            merchant_name = VALUES(merchant_name),
                            email_patterns = VALUES(email_patterns),
                            is_subscription = VALUES(is_subscription),
                            expected_amount_min = VALUES(expected_amount_min),
                            expected_amount_max = VALUES(expected_amount_max),
                            category = VALUES(category),
                            aliases = VALUES(aliases),
                            updated_at = CURRENT_TIMESTAMP
                    ''', (
                        merchant_name,
                        domain.lower(),
                        json.dumps(config.get('patterns', [])),
                        config.get('is_subscription', False),
                        30 if config.get('is_subscription') else None,
                        amount_range[0],
                        amount_range[1],
                        100,
                        config.get('category', 'General'),
                        json.dumps(config.get('aliases', []))
                    ))

                    if cursor.rowcount == 1:
                        inserted += 1
                    else:
                        updated += 1

                except Exception as e:
                    print(f"  Error inserting {domain}: {e}")

        conn.commit()
        print(f"Seeded merchant_email_domains: {inserted} inserted, {updated} updated")
        return inserted + updated

    except Exception as e:
        print(f"Error seeding table: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()


def get_all_whitelisted_domains() -> List[str]:
    """Get all whitelisted email domains"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT email_domain FROM merchant_email_domains')
        return [row['email_domain'] for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error getting domains: {e}")
        return list(MERCHANT_EMAIL_MAPPING.keys())
    finally:
        conn.close()


def add_learned_domain(domain: str, merchant_name: str, amount: Optional[Decimal] = None,
                       is_subscription: bool = False, category: str = 'General') -> bool:
    """Add a newly learned domain from accepted receipt"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO merchant_email_domains
            (merchant_name, email_domain, is_subscription, confidence, category, receipt_count, last_receipt_date)
            VALUES (%s, %s, %s, 80, %s, 1, NOW())
            ON DUPLICATE KEY UPDATE
                receipt_count = receipt_count + 1,
                last_receipt_date = NOW(),
                confidence = LEAST(confidence + 5, 100)
        ''', (merchant_name, domain.lower(), is_subscription, category))

        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding learned domain: {e}")
        return False
    finally:
        conn.close()


def clean_false_positives() -> Dict[str, int]:
    """Clean existing false positives from incoming_receipts"""
    conn = get_db_connection()
    cursor = conn.cursor()

    results = {
        'deleted_rejected': 0,
        'deleted_low_confidence': 0,
        'deleted_blocked_domain': 0,
        'remaining': 0
    }

    try:
        # Delete all rejected
        cursor.execute("DELETE FROM incoming_receipts WHERE status = 'rejected'")
        results['deleted_rejected'] = cursor.rowcount

        # Delete low confidence (< 70)
        cursor.execute("DELETE FROM incoming_receipts WHERE confidence_score < 70 AND status = 'pending'")
        results['deleted_low_confidence'] = cursor.rowcount

        # Delete from blocked domains
        blocked_list = ', '.join([f"'{d}'" for d in BLOCKED_DOMAINS])
        cursor.execute(f"""
            DELETE FROM incoming_receipts
            WHERE from_domain IN ({blocked_list})
            AND status = 'pending'
        """)
        results['deleted_blocked_domain'] = cursor.rowcount

        # Count remaining
        cursor.execute("SELECT COUNT(*) as cnt FROM incoming_receipts WHERE status = 'pending'")
        results['remaining'] = cursor.fetchone()['cnt']

        conn.commit()
        return results

    except Exception as e:
        print(f"Error cleaning: {e}")
        conn.rollback()
        return results
    finally:
        conn.close()


# =============================================================================
# MAIN / CLI
# =============================================================================

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == 'init':
            print("Initializing merchant_email_domains table...")
            init_merchant_email_domains_table()

        elif command == 'seed':
            print("Seeding merchant email domains...")
            init_merchant_email_domains_table()
            count = seed_merchant_email_domains()
            print(f"Seeded {count} domain mappings")

        elif command == 'clean':
            print("Cleaning false positives...")
            results = clean_false_positives()
            print(f"Deleted: {results['deleted_rejected']} rejected, "
                  f"{results['deleted_low_confidence']} low confidence, "
                  f"{results['deleted_blocked_domain']} blocked domains")
            print(f"Remaining pending: {results['remaining']}")

        elif command == 'test':
            # Test the engine
            engine = ReceiptIntelligence()

            test_cases = [
                ('receipts@anthropic.com', 'Your Claude Pro subscription - $20.00'),
                ('noreply@mailchimp.com', 'Check out our latest deals!'),
                ('noreply@apple.com', 'Your receipt from Apple - Order #ABC123'),
                ('unknown@randomcompany.com', 'Invoice #12345 - Total: $99.99'),
                ('newsletter@medium.com', 'Top stories this week'),
            ]

            print("\n=== Receipt Intelligence Test ===\n")
            for from_email, subject in test_cases:
                candidate = ReceiptCandidate(
                    email_id='test',
                    from_email=from_email,
                    from_domain=engine.extract_domain(from_email),
                    subject=subject,
                    body_snippet='',
                    received_date=datetime.now(),
                    has_attachment=False,
                    attachments=[]
                )

                result = engine.analyze_email(candidate)
                should_capture, reason = engine.should_capture(result)

                status = "CAPTURE" if should_capture else "SKIP"
                print(f"[{status}] {from_email}")
                print(f"         Subject: {subject}")
                print(f"         Confidence: {result.confidence.name} ({result.confidence_score}%)")
                print(f"         Reason: {reason}")
                if result.extracted_amount:
                    print(f"         Amount: ${result.extracted_amount}")
                print()

        else:
            print(f"Unknown command: {command}")
            print("Usage: python receipt_intelligence.py [init|seed|clean|test]")
    else:
        print("Receipt Intelligence Engine")
        print("Usage: python receipt_intelligence.py [init|seed|clean|test]")
