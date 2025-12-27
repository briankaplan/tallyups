#!/usr/bin/env python3
"""
Gmail Receipt Extraction Service

Multi-account Gmail receipt extraction service
- Connect to 3 Gmail accounts (brian@business.com, kaplan.brian@gmail.com, brian@secondary.com)
- Search for receipt emails
- Extract merchant, amount, date, order number
- Save to SQLite database + R2 storage
- Return structured receipt data

Requirements: google-auth, google-auth-oauthlib, google-auth-httplib2, google-api-python-client
"""

import os
import sqlite3
import re
import json
import base64
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Google API imports - graceful degradation if not available
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False
    print("⚠️  Google API libraries not available - Gmail integration disabled")


# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Gmail accounts to monitor
GMAIL_ACCOUNTS = {
    'brian@business.com': {
        'credentials_path': os.getenv('GMAIL_CREDENTIALS_BUSINESS', 'receipt-system/config/credentials.json'),
        'token_path': os.getenv('GMAIL_TOKEN_BUSINESS', 'receipt-system/gmail_tokens/tokens_brian_business_com.json'),
        'business_type': 'Business'
    },
    'kaplan.brian@gmail.com': {
        'credentials_path': os.getenv('GMAIL_CREDENTIALS_PERSONAL', 'receipt-system/config/credentials.json'),
        'token_path': os.getenv('GMAIL_TOKEN_PERSONAL', 'receipt-system/gmail_tokens/tokens_kaplan_brian_gmail_com.json'),
        'business_type': 'Personal'
    },
    'brian@secondary.com': {
        'credentials_path': os.getenv('GMAIL_CREDENTIALS_MCR', 'receipt-system/config/credentials.json'),
        'token_path': os.getenv('GMAIL_TOKEN_MCR', 'receipt-system/gmail_tokens/tokens_brian_secondary_com.json'),
        'business_type': 'Secondary'
    }
}

# Receipt email patterns (common receipt senders)
RECEIPT_PATTERNS = [
    'receipt',
    'invoice',
    'order confirmation',
    'payment confirmation',
    'your purchase',
    'billing',
    'subscription',
    'payment received',
    'thank you for your order',
    'order summary',
    'your apple receipt',
    'booking confirmation',
    'flight confirmation',
    'hotel confirmation',
    'reservation confirmed'
]

# Known receipt sender domains - search by from: address
RECEIPT_SENDERS = [
    'email.apple.com',           # Apple App Store/iTunes receipts
    'apple.com',                 # Apple
    'hoteltonight.com',          # HotelTonight
    'southwest.com',             # Southwest Airlines
    'ifly.southwest.com',        # Southwest flight confirmations
    'hotels.com',                # Hotels.com
    'booking.com',               # Booking.com
    'expedia.com',               # Expedia
    'marriott.com',              # Marriott hotels
    'hilton.com',                # Hilton hotels
    'ihg.com',                   # IHG hotels
    'hyatt.com',                 # Hyatt hotels
    'airbnb.com',                # Airbnb
    'uber.com',                  # Uber
    'lyft.com',                  # Lyft
    'doordash.com',              # DoorDash
    'grubhub.com',               # Grubhub
    'amazon.com',                # Amazon
    'paypal.com',                # PayPal
    'venmo.com',                 # Venmo
    'square.com',                # Square
    'stripe.com',                # Stripe receipts
]

# Merchant extraction patterns
MERCHANT_PATTERNS = [
    r'from ([A-Z][A-Za-z\s]+)',  # "from Merchant Name"
    r'at ([A-Z][A-Za-z\s]+)',    # "at Merchant Name"
    r'Your receipt from ([A-Za-z\s]+)',  # "Your receipt from Merchant"
    r'Order from ([A-Za-z\s]+)',  # "Order from Merchant"
]

# Amount extraction patterns
AMOUNT_PATTERNS = [
    r'\$\s?(\d+[\.,]\d{2})',  # $123.45 or $123,45
    r'(\d+[\.,]\d{2})\s?USD',  # 123.45 USD
    r'Total[:\s]+\$?\s?(\d+[\.,]\d{2})',  # Total: $123.45
    r'Amount[:\s]+\$?\s?(\d+[\.,]\d{2})',  # Amount: $123.45
]

# Date extraction patterns
DATE_PATTERNS = [
    r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',  # MM/DD/YYYY or DD-MM-YYYY
    r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',    # YYYY-MM-DD
    r'([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})', # January 1, 2025
]

# Order number patterns
ORDER_PATTERNS = [
    r'Order\s+#?\s?([A-Z0-9\-]+)',
    r'Order\s+Number[:\s]+([A-Z0-9\-]+)',
    r'Transaction\s+ID[:\s]+([A-Z0-9\-]+)',
    r'Reference[:\s]+([A-Z0-9\-]+)',
]

# =============================================================================
# HYBRID RECEIPT FILTER - High-precision patterns to filter garbage at scan time
# Based on analysis of 306 emails: 89% were garbage, only 11% real receipts
# =============================================================================

# GARBAGE PATTERNS - Emails matching these are NOT receipts (reject immediately)
GARBAGE_SUBJECT_PATTERNS = [
    # Marketing with emojis
    r'^[🎶🎄📢👻✨🏆🎧🎁🔥💰🚀🎉🌟⭐️💥🏅🎸🎵🛒📦💳]',
    r'🎶|🎄|📢|👻|✨|🏆|🎧|🎁|🔥|💰|🚀|🎉|🌟|⭐️|💥',

    # News/articles
    r'^Breaking:',
    r'Federal Court',
    r'Supreme Court',
    r'Trump announces',
    r'criminals arrested',
    r'BREAKING NEWS',

    # Marketing disguised as receipts
    r'Black Friday',
    r'Cyber Monday',
    r'Save up to \d+%',
    r'Earn \d+ points',
    r'claim your deal',
    r'limited time',
    r'act now',
    r'don\'t miss',
    r'exclusive offer',
    r'flash sale',
    r'today only',
    r'last chance',

    # Internal business threads (not receipts)
    r'Scoring Stage Investment',
    r'rodeo proposal',
    r'Management Equity',
    r'Engagement Letter',
    r'staffing \w+ rodeo',
    r'talent search',
    r'tour routing',
    r'booking inquiry',

    # Blog posts / newsletters
    r'^How My Company',
    r'^How Tools Shape',
    r'^How I Built',
    r'^What I Learned',
    r'^The Secret to',
    r'^Why You Should',
    r'ChatGPT Has Entered',
    r'AI is changing',
    r'New Music Friday',
    r'Movie Guide',
    r'Weekend Picks',

    # App notifications (not receipts)
    r'Firebase.*downgraded',
    r'Safety settings',
    r'Receipt Upload Problem',
    r'updated.*Apple Account',
    r'Account Summary',
    r'membership expires',
    r'Developer Program.*expire',
    r'Your.*has been terminated',
    r'Billing Update.*Tax',

    # Giveaways/scams
    r'gold bar giveaway',
    r'you\'ve won',
    r'winner selected',
    r'claim your prize',
    r'lottery',
    r'sweepstakes',

    # General marketing
    r'Keep up with Alexa',
    r'Tomorrow Night.*Full',
    r'See what\'s new',
    r'Check out the new',
    r'Explore.*new',
    r'Discover.*new',
    r'Weekly digest',
    r'Daily digest',
    r'Newsletter',
]

# HIGH CONFIDENCE RECEIPT PATTERNS - Emails matching these ARE receipts
HIGH_CONFIDENCE_RECEIPT_PATTERNS = [
    # Standard receipt format with order numbers
    r'Your receipt from .+ #\d+',
    r'Your receipt from .+ #[A-Z0-9\-]+',

    # Invoice patterns
    r'Invoice #\d+',
    r'Invoice from .+',
    r'Invoice \d+ from',

    # Refund patterns
    r'Your refund from .+ #',
    r'Refund confirmation',
    r'Refund processed',

    # Payment confirmations with amounts
    r'Payment.*\$\d+',
    r'Recurring Payment Confirm',
    r'Payment received.*\$',
    r'Payment confirmation',

    # Amazon orders (with items)
    r'^Shipped: "',
    r'^Ordered: "',
    r'Your Amazon\.com order',
    r'has shipped',

    # Subscription receipts
    r'subscription.*renew.*\$',
    r'Your subscription.*\$\d+',

    # Parking/transport receipts
    r'Parking Payment',
    r'Ride receipt',
    r'Trip receipt',
]

# KNOWN RECEIPT SENDERS - High trust domains (whitelist)
TRUSTED_RECEIPT_SENDERS = [
    'anthropic.com',           # Anthropic (Claude)
    'midjourney.com',          # Midjourney
    'stripe.com',              # Stripe payments
    'railway.app',             # Railway hosting
    'huggingface.co',          # Hugging Face
    'openai.com',              # OpenAI
    'cloudflare.com',          # Cloudflare
    'github.com',              # GitHub
    'digitalocean.com',        # DigitalOcean
    'aws.amazon.com',          # AWS
    'simpletexting.com',       # SimpleTexting
    'taskade.com',             # Taskade
]

# KNOWN GARBAGE SENDERS - Block these domains
GARBAGE_SENDERS = [
    'substack.com',            # Newsletters
    'medium.com',              # Blog posts
    'linkedin.com',            # Social
    'facebook.com',            # Social
    'twitter.com',             # Social
    'x.com',                   # Social
    'instagram.com',           # Social
    'tiktok.com',              # Social
    'youtube.com',             # Social
    'spotify.com',             # Music (unless receipt)
    'mailchimp.com',           # Marketing
    'constantcontact.com',     # Marketing
    'hubspot.com',             # Marketing
    'sendgrid.net',            # Marketing
]


class GmailReceiptService:
    """
    Gmail Receipt Extraction Service

    Handles Gmail authentication and receipt extraction across multiple accounts.
    Supports both legacy global accounts and per-user credentials for multi-tenant mode.
    """

    def __init__(self, db_path: str = 'receipts.db', credentials_dir: str = 'credentials', user_id: str = None):
        """
        Initialize Gmail receipt service

        Args:
            db_path: Path to SQLite database
            credentials_dir: Directory containing Gmail credentials and tokens
            user_id: Optional user ID for per-user credential storage (multi-tenant mode)
        """
        self.db_path = db_path
        self.credentials_dir = Path(credentials_dir)
        self.gmail_services = {}  # Account email -> Gmail service
        self.user_id = user_id  # For multi-tenant mode
        self._user_credentials_service = None  # Lazy-loaded

        # Ensure credentials directory exists
        self.credentials_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

        # Check if Gmail API is available
        if not GMAIL_API_AVAILABLE:
            print("⚠️  Gmail API not available - service running in limited mode")

    def _get_user_credentials_service(self):
        """Lazy-load user credentials service for multi-tenant mode."""
        if self._user_credentials_service is None:
            try:
                from services.user_credentials_service import get_user_credentials_service
                self._user_credentials_service = get_user_credentials_service()
            except ImportError:
                pass
        return self._user_credentials_service

    def authenticate_with_user_credentials(self, user_id: str, account_email: str) -> Optional[object]:
        """
        Authenticate Gmail using per-user credentials from database.

        Args:
            user_id: User's UUID
            account_email: Gmail account email

        Returns:
            Gmail service object or None if failed
        """
        if not GMAIL_API_AVAILABLE:
            print("❌ Gmail API not available")
            return None

        creds_service = self._get_user_credentials_service()
        if not creds_service:
            print("❌ User credentials service not available")
            return None

        # Get stored credentials for this user's Gmail account
        stored_creds = creds_service.get_credential(user_id, 'gmail', account_email)
        if not stored_creds:
            print(f"❌ No stored credentials for {account_email}")
            return None

        try:
            # Build credentials from stored tokens
            creds = Credentials(
                token=stored_creds.get('access_token'),
                refresh_token=stored_creds.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=os.getenv('GOOGLE_CLIENT_ID'),
                client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                scopes=stored_creds.get('scopes', SCOPES)
            )

            # Refresh if expired
            if creds.expired and creds.refresh_token:
                print(f"🔄 Refreshing credentials for {account_email}...")
                creds.refresh(Request())

                # Update stored credentials with new access token
                creds_service.store_credential(
                    user_id=user_id,
                    service_type='gmail',
                    account_email=account_email,
                    access_token=creds.token,
                    refresh_token=creds.refresh_token,
                    token_expires_at=creds.expiry,
                    scopes=list(creds.scopes) if creds.scopes else SCOPES
                )

            # Build Gmail service
            service = build('gmail', 'v1', credentials=creds)
            cache_key = f"{user_id}:{account_email}"
            self.gmail_services[cache_key] = service
            print(f"✅ Authenticated (user mode): {account_email}")
            return service

        except Exception as e:
            print(f"❌ Failed to authenticate with user credentials: {e}")
            return None

    def get_user_gmail_accounts(self, user_id: str) -> List[Dict]:
        """
        Get list of Gmail accounts connected by a user.

        Args:
            user_id: User's UUID

        Returns:
            List of connected Gmail accounts with metadata
        """
        creds_service = self._get_user_credentials_service()
        if not creds_service:
            return []

        return creds_service.list_credentials(user_id, 'gmail')

    def search_receipts_for_user(
        self,
        user_id: str,
        account_email: str = None,
        days_back: int = 30,
        max_results: int = 100
    ) -> List[Dict]:
        """
        Search for receipts in user's Gmail accounts.

        Args:
            user_id: User's UUID
            account_email: Specific account to search (None = all user's accounts)
            days_back: Number of days to look back
            max_results: Maximum number of results

        Returns:
            List of receipt email dicts
        """
        if account_email:
            accounts = [{'account_email': account_email}]
        else:
            accounts = self.get_user_gmail_accounts(user_id)

        all_receipts = []
        for account in accounts:
            email = account.get('account_email')
            if not email:
                continue

            # Authenticate with user credentials
            service = self.authenticate_with_user_credentials(user_id, email)
            if not service:
                continue

            # Search this account
            receipts = self._search_receipts_with_service(service, email, days_back, max_results)
            all_receipts.extend(receipts)

        return all_receipts

    def _search_receipts_with_service(
        self,
        service,
        account_email: str,
        days_back: int,
        max_results: int
    ) -> List[Dict]:
        """
        Search for receipts using a Gmail service object.

        Args:
            service: Authenticated Gmail service
            account_email: Account email for context
            days_back: Number of days to look back
            max_results: Maximum number of results

        Returns:
            List of receipt dicts
        """
        # Build search query
        date_cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
        query_parts = [f'after:{date_cutoff}']

        # Add receipt keyword search
        receipt_keywords = ' OR '.join([f'"{pattern}"' for pattern in RECEIPT_PATTERNS])
        sender_queries = ' OR '.join([f'from:{domain}' for domain in RECEIPT_SENDERS])
        query_parts.append(f'(({receipt_keywords}) OR ({sender_queries}))')

        query = ' '.join(query_parts)

        print(f"🔍 Searching {account_email} for receipts (last {days_back} days)...")

        try:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            messages = results.get('messages', [])

            if not messages:
                print(f"   No receipts found")
                return []

            print(f"   Found {len(messages)} potential receipts")

            receipts = []
            for msg in messages:
                try:
                    message = service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='full'
                    ).execute()

                    receipt = self._extract_receipt_data(message, account_email)
                    if receipt:
                        receipts.append(receipt)
                except Exception as e:
                    print(f"   ⚠️  Error processing message {msg['id']}: {e}")
                    continue

            print(f"   Extracted {len(receipts)} receipts")
            return receipts

        except HttpError as e:
            print(f"❌ Gmail API error: {e}")
            return []
        except Exception as e:
            print(f"❌ Search error: {e}")
            return []

    def _init_database(self):
        """
        Initialize SQLite database for receipts
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Create receipts table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_account TEXT NOT NULL,
                gmail_message_id TEXT UNIQUE,
                email_subject TEXT,
                email_date TEXT,
                source TEXT DEFAULT 'gmail',
                merchant TEXT,
                amount REAL,
                transaction_date TEXT,
                order_number TEXT,
                business_type TEXT,
                r2_url TEXT,
                r2_key TEXT,
                file_hash TEXT,
                file_size INTEGER,
                total_pages INTEGER DEFAULT 1,
                processing_status TEXT DEFAULT 'pending',
                confidence_score REAL,
                extraction_metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT,
                UNIQUE(gmail_account, gmail_message_id)
            )
        """)

        # Create index for faster lookups
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_receipts_merchant
            ON receipts(merchant)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_receipts_date
            ON receipts(transaction_date)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_receipts_gmail
            ON receipts(gmail_account, gmail_message_id)
        """)

        conn.commit()
        conn.close()

        print(f"✅ Database initialized: {self.db_path}")

    def authenticate_account(self, account_email: str) -> Optional[object]:
        """
        Authenticate Gmail account using OAuth2

        Args:
            account_email: Gmail account email

        Returns:
            Gmail service object or None if failed
        """
        if not GMAIL_API_AVAILABLE:
            print("❌ Gmail API not available")
            return None

        if account_email not in GMAIL_ACCOUNTS:
            print(f"❌ Unknown account: {account_email}")
            return None

        config = GMAIL_ACCOUNTS[account_email]
        credentials_path = config['credentials_path']
        token_path = config['token_path']

        # Ensure credentials directory exists
        Path(credentials_path).parent.mkdir(parents=True, exist_ok=True)

        creds = None

        # Load existing token if available
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception as e:
                print(f"⚠️  Error loading token: {e}")

        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    print(f"🔄 Refreshing credentials for {account_email}...")
                    creds.refresh(Request())
                except Exception as e:
                    print(f"⚠️  Error refreshing token: {e}")
                    creds = None

            if not creds:
                if not os.path.exists(credentials_path):
                    print(f"❌ Credentials file not found: {credentials_path}")
                    print(f"   Please download OAuth2 credentials from Google Cloud Console")
                    return None

                try:
                    print(f"🔐 Starting OAuth flow for {account_email}...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    print(f"❌ OAuth flow failed: {e}")
                    return None

            # Save credentials
            try:
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
                print(f"✅ Credentials saved: {token_path}")
            except Exception as e:
                print(f"⚠️  Error saving token: {e}")

        # Build Gmail service
        try:
            service = build('gmail', 'v1', credentials=creds)
            self.gmail_services[account_email] = service
            print(f"✅ Authenticated: {account_email}")
            return service
        except Exception as e:
            print(f"❌ Failed to build Gmail service: {e}")
            return None

    def search_receipts(
        self,
        account_email: str,
        days_back: int = 30,
        max_results: int = 100
    ) -> List[Dict]:
        """
        Search for receipt emails in Gmail account

        Args:
            account_email: Gmail account to search
            days_back: Number of days to look back
            max_results: Maximum number of results

        Returns:
            List of receipt email dicts
        """
        if not GMAIL_API_AVAILABLE:
            return []

        # Authenticate if not already
        if account_email not in self.gmail_services:
            service = self.authenticate_account(account_email)
            if not service:
                return []
        else:
            service = self.gmail_services[account_email]

        # Build search query
        date_cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
        query_parts = [f'after:{date_cutoff}']

        # Add receipt keyword search
        receipt_keywords = ' OR '.join([f'"{pattern}"' for pattern in RECEIPT_PATTERNS])

        # Add known receipt sender domains
        sender_queries = ' OR '.join([f'from:{domain}' for domain in RECEIPT_SENDERS])

        # Combine: (keywords OR senders) - match either receipt keywords or known senders
        query_parts.append(f'(({receipt_keywords}) OR ({sender_queries}))')

        query = ' '.join(query_parts)

        print(f"🔍 Searching {account_email} for receipts (last {days_back} days)...")

        try:
            # Search for messages
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            messages = results.get('messages', [])

            if not messages:
                print(f"   No receipts found")
                return []

            print(f"   Found {len(messages)} potential receipts")

            # Fetch full message details
            receipts = []

            for msg in messages:
                try:
                    # Get full message
                    message = service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='full'
                    ).execute()

                    # Extract receipt data
                    receipt = self._extract_receipt_data(message, account_email)

                    if receipt:
                        receipts.append(receipt)

                except Exception as e:
                    print(f"   ⚠️  Error processing message {msg['id']}: {e}")
                    continue

            print(f"   Extracted {len(receipts)} receipts")

            return receipts

        except HttpError as e:
            print(f"❌ Gmail API error: {e}")
            return []
        except Exception as e:
            print(f"❌ Search error: {e}")
            return []

    def _extract_receipt_data(self, message: Dict, account_email: str) -> Optional[Dict]:
        """
        Extract receipt data from Gmail message with HYBRID FILTERING.

        Uses rule-based pre-filter to reject garbage emails at scan time,
        then extracts data from emails classified as receipts.

        Args:
            message: Gmail message object
            account_email: Gmail account email

        Returns:
            Dict with extracted receipt data or None if garbage
        """
        try:
            # Get headers
            headers = {h['name']: h['value'] for h in message['payload']['headers']}

            subject = headers.get('Subject', '')
            from_email = headers.get('From', '')
            date_str = headers.get('Date', '')
            message_id = message['id']

            # Get email body for classification
            body = self._get_message_body(message)

            # =================================================================
            # HYBRID FILTER: Classify email BEFORE extracting data
            # =================================================================
            classification = self._classify_email(subject, from_email, body)

            if classification['classification'] == 'garbage':
                # Skip garbage emails - don't even extract data
                return None

            # =================================================================
            # Extract receipt data for non-garbage emails
            # =================================================================

            # Parse email date
            email_date = self._parse_email_date(date_str)

            # Extract merchant (use app name extraction for Apple receipts)
            if 'apple' in from_email.lower() or 'apple' in subject.lower():
                merchant = self._extract_apple_app_name(body, subject)
            else:
                merchant = self._extract_merchant(subject, body)

            # Extract amount (pass from_email for vendor-specific parsing like Apple)
            amount = self._extract_amount(subject, body, from_email)

            # Extract transaction date
            transaction_date = self._extract_date(subject, body) or email_date

            # Extract order number
            order_number = self._extract_order_number(subject, body)

            # Get business type
            business_type = GMAIL_ACCOUNTS[account_email]['business_type']

            # Check for attachments
            has_attachments = self._has_attachments(message)

            # Use classification confidence, boosted by data extraction quality
            data_confidence = self._calculate_confidence(merchant, amount, transaction_date)
            combined_confidence = (classification['confidence'] + data_confidence) / 2

            receipt = {
                'gmail_account': account_email,
                'gmail_message_id': message_id,
                'email_subject': subject,
                'email_date': email_date,
                'merchant': merchant,
                'amount': amount,
                'transaction_date': transaction_date,
                'order_number': order_number,
                'business_type': business_type,
                'has_attachments': has_attachments,
                'confidence_score': round(combined_confidence, 2),
                'classification': classification['classification'],
                'classification_reason': classification['reason'],
                'extraction_metadata': json.dumps({
                    'subject': subject,
                    'from': from_email,
                    'date': date_str,
                    'has_attachments': has_attachments,
                    'classification': classification['classification'],
                    'classification_confidence': classification['confidence'],
                    'classification_reason': classification['reason']
                })
            }

            return receipt

        except Exception as e:
            print(f"   Error extracting receipt data: {e}")
            return None

    def _get_message_body(self, message: Dict) -> str:
        """
        Extract message body text from Gmail message

        Args:
            message: Gmail message object

        Returns:
            str: Message body text (prefers plain text, falls back to HTML for Apple receipts)
        """
        try:
            payload = message['payload']
            plain_text = ''
            html_text = ''

            # Try to get body from payload directly (single part message)
            if 'body' in payload and 'data' in payload['body']:
                body_data = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
                if payload.get('mimeType') == 'text/html':
                    html_text = body_data
                else:
                    plain_text = body_data

            # Check parts for multipart messages
            if 'parts' in payload:
                for part in payload['parts']:
                    mime_type = part.get('mimeType', '')
                    body = part.get('body', {})

                    if 'data' in body:
                        decoded = base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')
                        if mime_type == 'text/plain' and not plain_text:
                            plain_text = decoded
                        elif mime_type == 'text/html' and not html_text:
                            html_text = decoded

                    # Check nested parts (for multipart/alternative inside multipart/mixed)
                    if 'parts' in part:
                        for subpart in part['parts']:
                            sub_mime = subpart.get('mimeType', '')
                            sub_body = subpart.get('body', {})

                            if 'data' in sub_body:
                                decoded = base64.urlsafe_b64decode(sub_body['data']).decode('utf-8', errors='ignore')
                                if sub_mime == 'text/plain' and not plain_text:
                                    plain_text = decoded
                                elif sub_mime == 'text/html' and not html_text:
                                    html_text = decoded

            # Return plain text if available, otherwise HTML (needed for Apple receipts)
            return plain_text if plain_text else html_text

        except Exception as e:
            return ''

    def _parse_email_date(self, date_str: str) -> str:
        """
        Parse email date string to YYYY-MM-DD format

        Args:
            date_str: Email date string

        Returns:
            str: Date in YYYY-MM-DD format
        """
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.strftime('%Y-%m-%d')
        except:
            return datetime.now().strftime('%Y-%m-%d')

    def _extract_merchant(self, subject: str, body: str) -> Optional[str]:
        """Extract merchant name from subject/body"""
        text = f"{subject} {body[:500]}"  # Use first 500 chars of body

        for pattern in MERCHANT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                merchant = match.group(1).strip()
                # Clean up merchant name
                merchant = re.sub(r'\s+', ' ', merchant)
                return merchant[:100]  # Limit length

        return None

    def _extract_apple_receipt_amount(self, html_body: str) -> Optional[float]:
        """
        Extract amount from Apple receipt HTML.

        Apple receipts have the total deep in the HTML body with patterns like:
        - TOTAL $XX.XX
        - Total: $XX.XX
        - Grand Total $XX.XX
        - Order Total $XX.XX
        - "TOTAL" row in HTML table
        """
        # Apple-specific amount patterns (search full body)
        apple_patterns = [
            # HTML patterns - Apple uses uppercase TOTAL in their receipts
            r'TOTAL\s*[\$€£]\s*([\d,]+\.?\d*)',
            r'>TOTAL<.*?>\s*[\$€£]?\s*([\d,]+\.?\d*)<',
            # Order total patterns
            r'Order\s+Total[:\s]*[\$€£]?\s*([\d,]+\.?\d*)',
            r'Grand\s+Total[:\s]*[\$€£]?\s*([\d,]+\.?\d*)',
            # Generic total patterns
            r'Total[:\s]+[\$€£]\s*([\d,]+\.?\d*)',
            r'Total.*?[\$€£]\s*([\d,]+\.?\d*)',
            # In-app purchase patterns
            r'Price[:\s]+[\$€£]\s*([\d,]+\.?\d*)',
            # Table cell patterns (Apple uses these)
            r'<td[^>]*>\s*[\$€£]\s*([\d,]+\.?\d*)\s*</td>',
            # Subscription renewal
            r'renew.*?[\$€£]\s*([\d,]+\.?\d*)',
            # Billed amounts
            r'billed[:\s]+[\$€£]\s*([\d,]+\.?\d*)',
        ]

        amounts_found = []

        for pattern in apple_patterns:
            matches = re.findall(pattern, html_body, re.IGNORECASE | re.DOTALL)
            for match in matches:
                try:
                    # Clean up the amount string
                    amount_str = match.replace(',', '').strip()
                    if amount_str and float(amount_str) > 0:
                        amounts_found.append(float(amount_str))
                except (ValueError, AttributeError):
                    continue

        if amounts_found:
            # Return the largest amount found (usually the total)
            # Filter out unreasonably large amounts (>$10000 likely parsing error)
            valid_amounts = [a for a in amounts_found if 0 < a < 10000]
            if valid_amounts:
                return max(valid_amounts)

        return None

    def _extract_apple_app_name(self, html_body: str, subject: str = '') -> str:
        """
        Extract the app/service name from Apple receipt HTML.

        Returns merchant name like "Apple - Roblox" or "Apple - Calendly"
        """
        # Common patterns for app names in Apple receipts
        app_patterns = [
            # App name in product/item rows
            r'<td[^>]*class="[^"]*item[^"]*"[^>]*>([^<]+)</td>',
            r'<td[^>]*>([A-Z][a-zA-Z0-9\s\-\+\.]+(?:Premium|Pro|Plus|Subscription)?)</td>',
            # Item name patterns
            r'Item:\s*([A-Za-z0-9\s\-\+\.]+)',
            r'Product:\s*([A-Za-z0-9\s\-\+\.]+)',
            # Subscription patterns
            r'(\w+(?:\s+\w+)?)\s+(?:Premium|Pro|Plus|Subscription|Monthly|Annual)',
            # In-App Purchase patterns
            r'In-App Purchase[:\s]*([A-Za-z0-9\s\-\+\.]+)',
            # Game currencies/items
            r'(\d+\s+(?:Robux|Gems|Coins|Credits|V-Bucks))',
        ]

        # Known app names to look for
        known_apps = [
            'Roblox', 'Calendly', 'Spotify', 'Netflix', 'YouTube',
            'Disney+', 'HBO Max', 'Hulu', 'Apple Music', 'iCloud',
            'Apple TV', 'Apple Arcade', 'Apple News', 'Apple Fitness',
            'Fortnite', 'Minecraft', 'Candy Crush', 'Clash of Clans',
            'WhatsApp', 'Telegram', 'Signal', 'Slack', 'Zoom',
            'Microsoft 365', 'Adobe', 'Canva', 'Notion', 'Evernote',
            'Duolingo', 'Headspace', 'Calm', 'Strava', 'MyFitnessPal'
        ]

        # First check for known app names in body
        body_lower = html_body.lower()
        for app in known_apps:
            if app.lower() in body_lower:
                return f"Apple - {app}"

        # Check subject line for app names
        if subject:
            for app in known_apps:
                if app.lower() in subject.lower():
                    return f"Apple - {app}"

        # Try regex patterns
        for pattern in app_patterns:
            matches = re.findall(pattern, html_body, re.IGNORECASE)
            for match in matches:
                name = match.strip()
                # Filter out generic terms
                if name and len(name) > 2 and name.lower() not in ['total', 'price', 'item', 'product', 'tax', 'apple']:
                    # Clean up the name
                    name = re.sub(r'\s+', ' ', name).strip()
                    if len(name) < 50:  # Reasonable length
                        return f"Apple - {name}"

        # Check for subscription renewal
        if 'renew' in body_lower or 'subscription' in body_lower:
            return "Apple - Subscription"

        # Check for iCloud storage
        if 'icloud' in body_lower or 'storage' in body_lower:
            return "Apple - iCloud Storage"

        # Default fallback
        return "Apple"

    def _extract_apple_apps_and_amounts(self, html_body: str, subject: str = '') -> List[Tuple[str, float]]:
        """
        Extract ALL apps and their amounts from an Apple receipt.

        This handles multi-app receipts where one email contains multiple purchases.

        Returns:
            List of (app_name, amount) tuples, e.g.:
            [('Roblox', 4.99), ('Spotify', 9.99)]

        If only one app is found, returns list with single item.
        """
        results = []

        # Known app names to look for
        known_apps = [
            'Roblox', 'Calendly', 'Spotify', 'Netflix', 'YouTube',
            'Disney+', 'HBO Max', 'Hulu', 'Apple Music', 'iCloud',
            'Apple TV', 'Apple Arcade', 'Apple News', 'Apple Fitness',
            'Fortnite', 'Minecraft', 'Candy Crush', 'Clash of Clans',
            'WhatsApp', 'Telegram', 'Signal', 'Slack', 'Zoom',
            'Microsoft 365', 'Adobe', 'Canva', 'Notion', 'Evernote',
            'Duolingo', 'Headspace', 'Calm', 'Strava', 'MyFitnessPal'
        ]

        # Try to find table rows with items and prices
        # Apple receipts typically have HTML tables with product names and amounts
        table_row_pattern = r'<tr[^>]*>(.*?)</tr>'
        table_rows = re.findall(table_row_pattern, html_body, re.IGNORECASE | re.DOTALL)

        for row in table_rows:
            # Look for app name in this row
            app_found = None
            for app in known_apps:
                if app.lower() in row.lower():
                    app_found = app
                    break

            if not app_found:
                # Try to extract app name from table cell
                td_pattern = r'<td[^>]*>([^<]+)</td>'
                cells = re.findall(td_pattern, row, re.IGNORECASE)
                for cell in cells:
                    cell_clean = cell.strip()
                    # Look for capitalized words that might be app names
                    if cell_clean and len(cell_clean) > 2 and cell_clean[0].isupper():
                        if cell_clean.lower() not in ['total', 'price', 'item', 'product', 'tax', 'apple', 'quantity', 'description']:
                            app_found = cell_clean
                            break

            # Look for amount in this row
            amount_found = None
            if app_found:
                # Find amounts in this row
                amount_patterns = [
                    r'[\$€£]\s*([\d,]+\.?\d*)',
                    r'([\d,]+\.?\d*)\s*[\$€£]'
                ]
                for pattern in amount_patterns:
                    matches = re.findall(pattern, row, re.IGNORECASE)
                    for match in matches:
                        try:
                            amount_str = match.replace(',', '').strip()
                            amount_val = float(amount_str)
                            if 0 < amount_val < 10000:  # Reasonable range
                                amount_found = amount_val
                                break
                        except (ValueError, AttributeError):
                            continue
                    if amount_found:
                        break

            # Add to results if we found both
            if app_found and amount_found:
                # Check if this app is already in results (avoid duplicates)
                if not any(app_found.lower() in existing[0].lower() for existing in results):
                    results.append((app_found, amount_found))

        # If we couldn't find apps in table rows, fall back to single app detection
        if not results:
            app_name = self._extract_apple_app_name(html_body, subject)
            # Remove "Apple - " prefix if present
            if app_name.startswith("Apple - "):
                app_name = app_name[8:]
            elif app_name == "Apple":
                app_name = "App Store Purchase"

            amount = self._extract_apple_receipt_amount(html_body)
            if amount and amount > 0:
                results.append((app_name, amount))

        return results

    def _extract_amount(self, subject: str, body: str, from_email: str = '') -> Optional[float]:
        """Extract amount from subject/body with vendor-specific parsing"""

        # Check if this is an Apple receipt - search the FULL body
        is_apple = (
            'apple' in from_email.lower() or
            'apple' in subject.lower() or
            'itunes' in from_email.lower() or
            'App Store' in subject
        )

        if is_apple:
            # Use Apple-specific parser that searches full body
            apple_amount = self._extract_apple_receipt_amount(body)
            if apple_amount:
                return apple_amount

        # Standard extraction for other vendors (first 1000 chars)
        text = f"{subject} {body[:1000]}"

        for pattern in AMOUNT_PATTERNS:
            match = re.search(pattern, text)
            if match:
                amount_str = match.group(1).replace(',', '.')
                try:
                    return float(amount_str)
                except:
                    continue

        # If no amount found yet, try searching more of the body
        if len(body) > 1000:
            extended_text = body[:5000]
            for pattern in AMOUNT_PATTERNS:
                match = re.search(pattern, extended_text)
                if match:
                    amount_str = match.group(1).replace(',', '.')
                    try:
                        return float(amount_str)
                    except:
                        continue

        return None

    def _extract_date(self, subject: str, body: str) -> Optional[str]:
        """Extract transaction date from subject/body"""
        text = f"{subject} {body[:500]}"

        for pattern in DATE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                # Try to parse to standard format
                try:
                    # Handle various date formats
                    for fmt in ['%m/%d/%Y', '%d-%m-%Y', '%Y-%m-%d', '%B %d, %Y']:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            return dt.strftime('%Y-%m-%d')
                        except:
                            continue
                except:
                    continue

        return None

    def _extract_order_number(self, subject: str, body: str) -> Optional[str]:
        """Extract order number from subject/body"""
        text = f"{subject} {body[:500]}"

        for pattern in ORDER_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)[:50]  # Limit length

        return None

    def _has_attachments(self, message: Dict) -> bool:
        """Check if message has attachments"""
        try:
            payload = message['payload']

            if 'parts' in payload:
                for part in payload['parts']:
                    if 'filename' in part and part['filename']:
                        return True

                    # Check nested parts
                    if 'parts' in part:
                        for subpart in part['parts']:
                            if 'filename' in subpart and subpart['filename']:
                                return True

            return False

        except:
            return False

    def _calculate_confidence(self, merchant: Optional[str], amount: Optional[float], date: Optional[str]) -> float:
        """
        Calculate confidence score for extracted data

        Args:
            merchant: Extracted merchant
            amount: Extracted amount
            date: Extracted date

        Returns:
            float: Confidence score (0-1)
        """
        score = 0.0

        if merchant:
            score += 0.4
        if amount and amount > 0:
            score += 0.4
        if date:
            score += 0.2

        return round(score, 2)

    def _is_garbage(self, subject: str, from_email: str = '') -> Tuple[bool, str]:
        """
        Check if email is garbage (NOT a receipt) using hybrid filter patterns.

        This implements the rule-based pre-filter from the hybrid approach:
        - Marketing emails with emojis
        - News articles
        - Internal business threads
        - Blog posts / newsletters
        - Known garbage sender domains

        Args:
            subject: Email subject line
            from_email: Sender email address

        Returns:
            Tuple of (is_garbage: bool, reason: str)
        """
        # Check subject against garbage patterns
        for pattern in GARBAGE_SUBJECT_PATTERNS:
            if re.search(pattern, subject, re.IGNORECASE):
                return True, f"matches garbage pattern: {pattern[:30]}"

        # Check sender domain against garbage list
        if from_email:
            from_domain = from_email.split('@')[-1].lower() if '@' in from_email else ''
            for garbage_domain in GARBAGE_SENDERS:
                if garbage_domain in from_domain:
                    return True, f"from garbage sender: {garbage_domain}"

        # Check for forwarded duplicates (Fwd: or Re: with no amount context)
        if subject.lower().startswith(('fwd:', 'fw:', 're: re:', 're: fwd:')):
            # Allow if it looks like a real forwarded receipt
            if not any(re.search(p, subject, re.IGNORECASE) for p in HIGH_CONFIDENCE_RECEIPT_PATTERNS):
                # Check if it has receipt keywords
                receipt_keywords = ['receipt', 'invoice', 'payment', 'order', 'refund']
                has_keyword = any(kw in subject.lower() for kw in receipt_keywords)
                if not has_keyword:
                    return True, "forwarded email without receipt keywords"

        return False, ""

    def _is_high_confidence_receipt(self, subject: str, from_email: str = '', body: str = '') -> Tuple[bool, str]:
        """
        Check if email is a HIGH CONFIDENCE receipt using hybrid filter patterns.

        This implements the rule-based detection for obvious receipts:
        - Standard receipt format with order numbers
        - Invoice patterns
        - Known receipt sender domains
        - Payment confirmations with amounts

        Args:
            subject: Email subject line
            from_email: Sender email address
            body: First 500 chars of email body

        Returns:
            Tuple of (is_receipt: bool, reason: str)
        """
        # Check subject against high-confidence receipt patterns
        for pattern in HIGH_CONFIDENCE_RECEIPT_PATTERNS:
            if re.search(pattern, subject, re.IGNORECASE):
                return True, f"matches receipt pattern: {pattern[:40]}"

        # Check sender domain against trusted receipt senders
        if from_email:
            from_domain = from_email.split('@')[-1].lower() if '@' in from_email else ''
            for trusted_domain in TRUSTED_RECEIPT_SENDERS:
                if trusted_domain in from_domain:
                    return True, f"from trusted sender: {trusted_domain}"

        # Check for monetary amounts + receipt keywords in subject
        has_amount = bool(re.search(r'\$\d+[\.,]?\d*', subject))
        has_receipt_word = any(kw in subject.lower() for kw in ['receipt', 'invoice', 'payment', 'order', 'refund', 'charge'])
        if has_amount and has_receipt_word:
            return True, "has amount and receipt keyword"

        return False, ""

    def _classify_email(self, subject: str, from_email: str = '', body: str = '') -> Dict:
        """
        Classify email using hybrid approach (rules + confidence scoring).

        Returns classification result with:
        - classification: 'receipt', 'garbage', or 'uncertain'
        - confidence: 0.0 to 1.0
        - reason: explanation for classification

        Args:
            subject: Email subject
            from_email: Sender email
            body: Email body text

        Returns:
            Dict with classification, confidence, reason
        """
        # Step 1: Check if it's garbage (high-precision rejection)
        is_garbage, garbage_reason = self._is_garbage(subject, from_email)
        if is_garbage:
            return {
                'classification': 'garbage',
                'confidence': 0.95,
                'reason': garbage_reason,
                'should_save': False
            }

        # Step 2: Check if it's a high-confidence receipt
        is_receipt, receipt_reason = self._is_high_confidence_receipt(subject, from_email, body)
        if is_receipt:
            return {
                'classification': 'receipt',
                'confidence': 0.95,
                'reason': receipt_reason,
                'should_save': True
            }

        # Step 3: Uncertain - use heuristics to decide
        # Check for any receipt-like keywords
        receipt_keywords = ['receipt', 'invoice', 'order', 'payment', 'transaction',
                          'confirmation', 'booking', 'subscription', 'charge', 'billing']
        keyword_matches = sum(1 for kw in receipt_keywords if kw in subject.lower())

        # Check for amounts in subject or body
        has_amount_subject = bool(re.search(r'\$\d+[\.,]?\d*', subject))
        has_amount_body = bool(re.search(r'\$\d+[\.,]?\d*', body[:500])) if body else False

        # Calculate confidence for uncertain emails
        confidence = 0.3  # Base confidence
        if keyword_matches > 0:
            confidence += 0.2 * min(keyword_matches, 2)  # Up to +0.4
        if has_amount_subject:
            confidence += 0.2
        if has_amount_body:
            confidence += 0.1

        # If confidence > 0.5, treat as possible receipt
        if confidence > 0.5:
            return {
                'classification': 'receipt',
                'confidence': confidence,
                'reason': f"{keyword_matches} keywords, amount in {'subject' if has_amount_subject else 'body' if has_amount_body else 'neither'}",
                'should_save': True
            }

        return {
            'classification': 'uncertain',
            'confidence': confidence,
            'reason': 'no strong receipt signals',
            'should_save': True  # Save for manual review
        }

    def save_receipt(self, receipt: Dict) -> Optional[int]:
        """
        Save receipt to database

        Args:
            receipt: Receipt dict

        Returns:
            int: Receipt ID or None if error
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO receipts (
                    gmail_account,
                    gmail_message_id,
                    email_subject,
                    email_date,
                    source,
                    merchant,
                    amount,
                    transaction_date,
                    order_number,
                    business_type,
                    confidence_score,
                    extraction_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                receipt['gmail_account'],
                receipt['gmail_message_id'],
                receipt['email_subject'],
                receipt['email_date'],
                'gmail',
                receipt.get('merchant'),
                receipt.get('amount'),
                receipt.get('transaction_date'),
                receipt.get('order_number'),
                receipt['business_type'],
                receipt.get('confidence_score', 0.0),
                receipt.get('extraction_metadata', '{}')
            ))

            receipt_id = cur.lastrowid
            conn.commit()

            return receipt_id

        except sqlite3.IntegrityError:
            # Receipt already exists
            return None
        except Exception as e:
            print(f"❌ Error saving receipt: {e}")
            return None
        finally:
            conn.close()

    def download_attachment(
        self,
        account: str,
        message_id: str,
        attachment_id: str,
        filename: str
    ) -> Optional[bytes]:
        """
        Download attachment from Gmail

        Args:
            account: Gmail account email
            message_id: Gmail message ID
            attachment_id: Attachment ID
            filename: Attachment filename

        Returns:
            bytes: Attachment data or None if error
        """
        if not GMAIL_API_AVAILABLE:
            return None

        if account not in self.gmail_services:
            service = self.authenticate_account(account)
            if not service:
                return None
        else:
            service = self.gmail_services[account]

        try:
            attachment = service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=attachment_id
            ).execute()

            data = base64.urlsafe_b64decode(attachment['data'])
            return data

        except Exception as e:
            print(f"❌ Error downloading attachment: {e}")
            return None

    def search_and_save_receipts(
        self,
        account_email: str = None,
        days_back: int = 30,
        max_results: int = 100
    ) -> Dict:
        """
        Search for receipts and save to database

        Args:
            account_email: Specific account to search (None = all accounts)
            days_back: Number of days to look back
            max_results: Maximum results per account

        Returns:
            Dict with statistics
        """
        accounts = [account_email] if account_email else list(GMAIL_ACCOUNTS.keys())

        stats = {
            'total_found': 0,
            'total_saved': 0,
            'total_duplicates': 0,
            'by_account': {}
        }

        for account in accounts:
            print(f"\n🔍 Processing {account}...")

            receipts = self.search_receipts(account, days_back, max_results)

            account_stats = {
                'found': len(receipts),
                'saved': 0,
                'duplicates': 0
            }

            for receipt in receipts:
                receipt_id = self.save_receipt(receipt)

                if receipt_id:
                    account_stats['saved'] += 1
                else:
                    account_stats['duplicates'] += 1

            stats['total_found'] += account_stats['found']
            stats['total_saved'] += account_stats['saved']
            stats['total_duplicates'] += account_stats['duplicates']
            stats['by_account'][account] = account_stats

            print(f"   ✅ Saved {account_stats['saved']} new receipts ({account_stats['duplicates']} duplicates)")

        return stats


# Singleton instance
_gmail_receipt_service = None

def get_gmail_receipt_service(db_path: str = 'receipts.db') -> GmailReceiptService:
    """
    Get or create the Gmail receipt service singleton

    Args:
        db_path: Path to SQLite database

    Returns:
        GmailReceiptService: Singleton instance
    """
    global _gmail_receipt_service
    if _gmail_receipt_service is None:
        _gmail_receipt_service = GmailReceiptService(db_path)
    return _gmail_receipt_service


if __name__ == '__main__':
    """
    Test Gmail receipt service
    """
    import sys

    print("=" * 80)
    print("GMAIL RECEIPT EXTRACTION SERVICE")
    print("=" * 80)

    db_path = sys.argv[1] if len(sys.argv) > 1 else 'receipts.db'

    # Initialize service
    service = GmailReceiptService(db_path)

    print("\n" + "=" * 80)
    print("Available accounts:")
    for i, account in enumerate(GMAIL_ACCOUNTS.keys(), 1):
        print(f"{i}. {account}")
    print(f"{len(GMAIL_ACCOUNTS) + 1}. All accounts")
    print("=" * 80)

    choice = input("\nSelect account (1-4): ").strip()

    if choice == str(len(GMAIL_ACCOUNTS) + 1):
        account = None
        print("\n🔍 Searching all accounts...")
    else:
        try:
            account = list(GMAIL_ACCOUNTS.keys())[int(choice) - 1]
            print(f"\n🔍 Searching {account}...")
        except:
            print("❌ Invalid choice")
            sys.exit(1)

    days = input("Days to look back (default 30): ").strip()
    days = int(days) if days else 30

    # Search and save receipts
    stats = service.search_and_save_receipts(
        account_email=account,
        days_back=days,
        max_results=100
    )

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total found: {stats['total_found']}")
    print(f"Total saved: {stats['total_saved']}")
    print(f"Total duplicates: {stats['total_duplicates']}")

    for account, account_stats in stats['by_account'].items():
        print(f"\n{account}:")
        print(f"  Found: {account_stats['found']}")
        print(f"  Saved: {account_stats['saved']}")
        print(f"  Duplicates: {account_stats['duplicates']}")

    print("\n" + "=" * 80)
