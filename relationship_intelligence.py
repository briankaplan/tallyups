#!/usr/bin/env python3
"""
ATLAS - Relationship Intelligence Platform
==========================================

All Touchpoints Logged And Synthesized

This module provides comprehensive relationship intelligence by integrating:
- Contact database (contacts.csv + Apple Contacts + MySQL)
- Email interactions (Gmail)
- iMessage conversations
- Calendar events
- Expense data (for relationship investment tracking)

Features:
- Interaction tracking across all channels
- Commitment extraction and tracking
- Relationship health scoring
- Meeting prep brief generation
- Proactive nudge engine
- Network graph analysis
"""

import os
import re
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict

# Database
from db_mysql import get_db_connection

# AI
try:
    from gemini_utils import generate_content_with_fallback
    GEMINI_AVAILABLE = True
except:
    GEMINI_AVAILABLE = False

# Contact management
try:
    from contact_management import get_contact_manager, search_contacts
    CONTACTS_AVAILABLE = True
except:
    CONTACTS_AVAILABLE = False

# Gmail and Google APIs
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except:
    GOOGLE_API_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent

# Gmail accounts configuration
GMAIL_ACCOUNTS = [
    "kaplan.brian@gmail.com",
    "brian@downhome.com",
    "brian@musiccityrodeo.com",
]

# Token directories to search
GMAIL_TOKEN_DIRS = [
    Path("receipt-system/gmail_tokens"),
    Path("../Task/receipt-system/gmail_tokens"),
    Path("gmail_tokens"),
    Path("."),
]


# =============================================================================
# ENUMS AND DATA CLASSES
# =============================================================================

class InteractionType(Enum):
    EMAIL_SENT = "email_sent"
    EMAIL_RECEIVED = "email_received"
    IMESSAGE_SENT = "imessage_sent"
    IMESSAGE_RECEIVED = "imessage_received"
    MEETING = "meeting"
    CALL = "call"
    EXPENSE = "expense"  # Meals, events together
    VOICE_MEMO = "voice_memo"
    NOTE = "note"


class CommitmentStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class RelationshipTrend(Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    NEW = "new"


@dataclass
class Interaction:
    """Represents any interaction with a contact"""
    id: Optional[int] = None
    contact_id: Optional[int] = None
    contact_name: str = ""
    contact_email: str = ""

    type: InteractionType = InteractionType.NOTE
    occurred_at: datetime = field(default_factory=datetime.now)

    subject: str = ""
    summary: str = ""
    content: str = ""

    # Source tracking
    source: str = ""  # gmail, imessage, calendar, manual
    source_id: str = ""  # Message ID, event ID, etc.

    # Analysis
    sentiment_score: float = 0.0  # -1 to 1
    sentiment_label: str = "neutral"

    # Metadata
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['type'] = self.type.value
        d['occurred_at'] = self.occurred_at.isoformat() if self.occurred_at else None
        return d


@dataclass
class Commitment:
    """A promise or commitment made in a conversation"""
    id: Optional[int] = None
    contact_id: Optional[int] = None
    contact_name: str = ""
    interaction_id: Optional[int] = None

    description: str = ""
    made_by: str = "me"  # "me" or "them"
    due_date: Optional[datetime] = None

    status: CommitmentStatus = CommitmentStatus.PENDING
    completed_at: Optional[datetime] = None

    extracted_at: datetime = field(default_factory=datetime.now)
    confidence: float = 0.8

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['status'] = self.status.value
        d['due_date'] = self.due_date.isoformat() if self.due_date else None
        d['completed_at'] = self.completed_at.isoformat() if self.completed_at else None
        d['extracted_at'] = self.extracted_at.isoformat() if self.extracted_at else None
        return d


@dataclass
class RelationshipHealth:
    """Relationship health assessment"""
    contact_id: int
    contact_name: str

    overall_score: float = 0.5  # 0-1
    trend: RelationshipTrend = RelationshipTrend.STABLE

    # Component scores
    frequency_score: float = 0.5
    recency_score: float = 0.5
    sentiment_score: float = 0.5
    reciprocity_score: float = 0.5
    commitment_score: float = 0.5

    # Stats
    total_interactions: int = 0
    last_interaction: Optional[datetime] = None
    days_since_contact: int = 0

    # Recommendations
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['trend'] = self.trend.value
        d['last_interaction'] = self.last_interaction.isoformat() if self.last_interaction else None
        return d


@dataclass
class MeetingBrief:
    """Pre-meeting preparation brief"""
    event_title: str
    event_time: datetime
    event_location: str = ""

    attendees: List[Dict] = field(default_factory=list)
    talking_points: List[str] = field(default_factory=list)
    open_commitments: List[Dict] = field(default_factory=list)
    recent_interactions: List[Dict] = field(default_factory=list)
    relationship_context: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['event_time'] = self.event_time.isoformat() if self.event_time else None
        return d


@dataclass
class Nudge:
    """Proactive relationship nudge"""
    type: str  # overdue_contact, birthday, commitment, news, reciprocity
    priority: str  # high, medium, low

    contact_id: Optional[int] = None
    contact_name: str = ""

    title: str = ""
    body: str = ""
    action: str = ""

    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['created_at'] = self.created_at.isoformat() if self.created_at else None
        return d


# =============================================================================
# DATABASE SCHEMA CREATION
# =============================================================================

def create_atlas_tables():
    """Create ATLAS tables in MySQL"""
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database")
        return False

    cursor = conn.cursor()

    # Contacts table (enhanced)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS atlas_contacts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            email VARCHAR(255),
            phone VARCHAR(50),
            company VARCHAR(255),
            title VARCHAR(255),

            -- Relationship metadata
            category VARCHAR(100),
            priority VARCHAR(20) DEFAULT 'normal',
            relationship_score FLOAT DEFAULT 0.5,

            -- Contact frequency targets
            target_contact_days INT DEFAULT 30,

            -- Personal notes
            family_notes TEXT,
            interests TEXT,
            important_dates JSON,

            -- Photos
            photo_url VARCHAR(500),
            photo_data LONGBLOB,

            -- Social
            linkedin_url VARCHAR(500),
            twitter_handle VARCHAR(100),

            -- Source tracking
            source VARCHAR(50),
            apple_id VARCHAR(100),
            google_id VARCHAR(100),

            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            last_interaction_at TIMESTAMP,

            INDEX idx_email (email),
            INDEX idx_name (name),
            INDEX idx_company (company)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # Interactions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS atlas_interactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            contact_id INT,
            contact_name VARCHAR(255),
            contact_email VARCHAR(255),

            type VARCHAR(50) NOT NULL,
            occurred_at TIMESTAMP NOT NULL,

            subject VARCHAR(500),
            summary TEXT,
            content LONGTEXT,

            -- Source tracking
            source VARCHAR(50),
            source_id VARCHAR(255),

            -- Analysis
            sentiment_score FLOAT DEFAULT 0,
            sentiment_label VARCHAR(20) DEFAULT 'neutral',

            -- Metadata
            metadata JSON,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            INDEX idx_contact (contact_id),
            INDEX idx_contact_email (contact_email),
            INDEX idx_occurred (occurred_at),
            INDEX idx_type (type),
            INDEX idx_source (source, source_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # Commitments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS atlas_commitments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            contact_id INT,
            contact_name VARCHAR(255),
            interaction_id INT,

            description TEXT NOT NULL,
            made_by VARCHAR(10) DEFAULT 'me',
            due_date DATE,

            status VARCHAR(20) DEFAULT 'pending',
            completed_at TIMESTAMP,

            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confidence FLOAT DEFAULT 0.8,

            INDEX idx_contact (contact_id),
            INDEX idx_status (status),
            INDEX idx_due (due_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # Contact relationships (network graph)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS atlas_contact_relationships (
            id INT AUTO_INCREMENT PRIMARY KEY,
            contact_a_id INT NOT NULL,
            contact_b_id INT NOT NULL,

            relationship_type VARCHAR(50),
            strength FLOAT DEFAULT 0.5,

            evidence JSON,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

            UNIQUE KEY unique_pair (contact_a_id, contact_b_id),
            INDEX idx_contact_a (contact_a_id),
            INDEX idx_contact_b (contact_b_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # Nudges table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS atlas_nudges (
            id INT AUTO_INCREMENT PRIMARY KEY,
            contact_id INT,
            contact_name VARCHAR(255),

            type VARCHAR(50) NOT NULL,
            priority VARCHAR(20) DEFAULT 'medium',

            title VARCHAR(255),
            body TEXT,
            action TEXT,

            is_dismissed BOOLEAN DEFAULT FALSE,
            dismissed_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            INDEX idx_contact (contact_id),
            INDEX idx_type (type),
            INDEX idx_dismissed (is_dismissed)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    conn.commit()
    cursor.close()
    conn.close()

    print("ATLAS tables created successfully")
    return True


# =============================================================================
# iMESSAGE READER
# =============================================================================

class iMessageReader:
    """Read iMessage conversations from chat.db"""

    CHAT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

    def __init__(self):
        self.db_path = self.CHAT_DB_PATH

    def is_available(self) -> bool:
        return self.db_path.exists()

    def get_conversations_with(
        self,
        phone_or_email: str,
        days: int = 90,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent iMessage conversations with a contact"""
        if not self.is_available():
            return []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Calculate date threshold (Apple's timestamp is nanoseconds since 2001-01-01)
            threshold_date = datetime.now() - timedelta(days=days)
            apple_epoch = datetime(2001, 1, 1)
            threshold_ns = int((threshold_date - apple_epoch).total_seconds() * 1e9)

            # Query messages
            cursor.execute("""
                SELECT
                    m.ROWID,
                    m.text,
                    m.is_from_me,
                    datetime(m.date/1000000000 + strftime('%s', '2001-01-01'), 'unixepoch', 'localtime') as message_date,
                    h.id as handle_id
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE (h.id LIKE ? OR h.id LIKE ?)
                AND m.date > ?
                AND m.text IS NOT NULL
                ORDER BY m.date DESC
                LIMIT ?
            """, (f'%{phone_or_email}%', f'+1%{phone_or_email}%', threshold_ns, limit))

            messages = []
            for row in cursor.fetchall():
                messages.append({
                    'id': row['ROWID'],
                    'text': row['text'],
                    'is_from_me': bool(row['is_from_me']),
                    'date': row['message_date'],
                    'handle': row['handle_id'],
                })

            conn.close()
            return messages

        except Exception as e:
            print(f"iMessage read error: {e}")
            return []

    def search_messages(
        self,
        query: str,
        days: int = 90,
        limit: int = 100
    ) -> List[Dict]:
        """Search iMessage for specific text"""
        if not self.is_available():
            return []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            threshold_date = datetime.now() - timedelta(days=days)
            apple_epoch = datetime(2001, 1, 1)
            threshold_ns = int((threshold_date - apple_epoch).total_seconds() * 1e9)

            cursor.execute("""
                SELECT
                    m.ROWID,
                    m.text,
                    m.is_from_me,
                    datetime(m.date/1000000000 + strftime('%s', '2001-01-01'), 'unixepoch', 'localtime') as message_date,
                    h.id as handle_id
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.text LIKE ?
                AND m.date > ?
                ORDER BY m.date DESC
                LIMIT ?
            """, (f'%{query}%', threshold_ns, limit))

            messages = []
            for row in cursor.fetchall():
                messages.append({
                    'id': row['ROWID'],
                    'text': row['text'],
                    'is_from_me': bool(row['is_from_me']),
                    'date': row['message_date'],
                    'handle': row['handle_id'],
                })

            conn.close()
            return messages

        except Exception as e:
            print(f"iMessage search error: {e}")
            return []

    def get_recent_contacts(self, days: int = 30, limit: int = 50) -> List[Dict]:
        """Get contacts with recent iMessage activity"""
        if not self.is_available():
            return []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            threshold_date = datetime.now() - timedelta(days=days)
            apple_epoch = datetime(2001, 1, 1)
            threshold_ns = int((threshold_date - apple_epoch).total_seconds() * 1e9)

            cursor.execute("""
                SELECT
                    h.id as handle_id,
                    COUNT(*) as message_count,
                    MAX(datetime(m.date/1000000000 + strftime('%s', '2001-01-01'), 'unixepoch', 'localtime')) as last_message
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.date > ?
                GROUP BY h.id
                ORDER BY MAX(m.date) DESC
                LIMIT ?
            """, (threshold_ns, limit))

            contacts = []
            for row in cursor.fetchall():
                contacts.append({
                    'handle': row['handle_id'],
                    'message_count': row['message_count'],
                    'last_message': row['last_message'],
                })

            conn.close()
            return contacts

        except Exception as e:
            print(f"iMessage contacts error: {e}")
            return []


# =============================================================================
# GMAIL EMAIL READER (ALL 3 ACCOUNTS)
# =============================================================================

class GmailReader:
    """Read email conversations from Gmail across all 3 accounts"""

    def __init__(self):
        self.services = {}  # account_email -> service
        self._load_all_services()

    def _load_gmail_token(self, account_email: str) -> Optional[Dict]:
        """Load Gmail token from file or environment"""
        token_file = f"tokens_{account_email.replace('@', '_').replace('.', '_')}.json"

        # Try file-based tokens
        for token_dir in GMAIL_TOKEN_DIRS:
            token_path = token_dir / token_file
            if token_path.exists():
                try:
                    with open(token_path, 'r') as f:
                        return json.load(f)
                except:
                    continue

        # Try environment variable (Railway)
        env_key = f"GMAIL_TOKEN_{account_email.replace('@', '_').replace('.', '_').upper()}"
        env_token = os.getenv(env_key)
        if env_token:
            try:
                return json.loads(env_token)
            except:
                pass

        return None

    def _load_all_services(self):
        """Load Gmail services for all configured accounts"""
        if not GOOGLE_API_AVAILABLE:
            return

        for account in GMAIL_ACCOUNTS:
            token_data = self._load_gmail_token(account)
            if token_data:
                try:
                    creds = Credentials.from_authorized_user_info(token_data)
                    service = build('gmail', 'v1', credentials=creds)
                    self.services[account] = service
                except Exception as e:
                    print(f"Failed to load Gmail service for {account}: {e}")

    def is_available(self) -> bool:
        return len(self.services) > 0

    def get_account_status(self) -> Dict[str, bool]:
        """Get status of each Gmail account"""
        return {account: account in self.services for account in GMAIL_ACCOUNTS}

    def get_emails_with_contact(
        self,
        email_address: str,
        days: int = 90,
        limit: int = 50
    ) -> List[Dict]:
        """Get email conversations with a specific contact across all accounts"""
        all_emails = []

        for account, service in self.services.items():
            try:
                # Search for emails to/from this contact
                query = f"(from:{email_address} OR to:{email_address})"
                if days:
                    from datetime import datetime, timedelta
                    after_date = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
                    query += f" after:{after_date}"

                results = service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=limit
                ).execute()

                messages = results.get('messages', [])

                for msg in messages:
                    try:
                        full_msg = service.users().messages().get(
                            userId='me',
                            id=msg['id'],
                            format='metadata',
                            metadataHeaders=['From', 'To', 'Subject', 'Date']
                        ).execute()

                        headers = {h['name']: h['value'] for h in full_msg.get('payload', {}).get('headers', [])}

                        all_emails.append({
                            'id': msg['id'],
                            'account': account,
                            'from': headers.get('From', ''),
                            'to': headers.get('To', ''),
                            'subject': headers.get('Subject', ''),
                            'date': headers.get('Date', ''),
                            'is_from_me': account in headers.get('From', ''),
                            'snippet': full_msg.get('snippet', ''),
                        })
                    except:
                        continue

            except Exception as e:
                print(f"Gmail search error for {account}: {e}")

        # Sort by date descending
        all_emails.sort(key=lambda x: x.get('date', ''), reverse=True)
        return all_emails[:limit]

    def get_recent_email_contacts(self, days: int = 30, limit: int = 50) -> List[Dict]:
        """Get contacts with recent email activity across all accounts"""
        contact_counts = defaultdict(lambda: {'sent': 0, 'received': 0, 'last_email': '', 'accounts': set()})

        for account, service in self.services.items():
            try:
                from datetime import datetime, timedelta
                after_date = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
                query = f"after:{after_date}"

                results = service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=200
                ).execute()

                for msg in results.get('messages', []):
                    try:
                        full_msg = service.users().messages().get(
                            userId='me',
                            id=msg['id'],
                            format='metadata',
                            metadataHeaders=['From', 'To', 'Date']
                        ).execute()

                        headers = {h['name']: h['value'] for h in full_msg.get('payload', {}).get('headers', [])}

                        from_email = headers.get('From', '')
                        to_email = headers.get('To', '')

                        # Extract email address from header
                        import re
                        from_match = re.search(r'[\w\.-]+@[\w\.-]+', from_email)
                        to_match = re.search(r'[\w\.-]+@[\w\.-]+', to_email)

                        if from_match and from_match.group() not in GMAIL_ACCOUNTS:
                            contact = from_match.group().lower()
                            contact_counts[contact]['received'] += 1
                            contact_counts[contact]['last_email'] = headers.get('Date', '')
                            contact_counts[contact]['accounts'].add(account)

                        if to_match and to_match.group() not in GMAIL_ACCOUNTS:
                            contact = to_match.group().lower()
                            contact_counts[contact]['sent'] += 1
                            if not contact_counts[contact]['last_email']:
                                contact_counts[contact]['last_email'] = headers.get('Date', '')
                            contact_counts[contact]['accounts'].add(account)

                    except:
                        continue

            except Exception as e:
                print(f"Gmail contacts error for {account}: {e}")

        # Convert to list and sort
        contacts = [
            {
                'email': email,
                'sent_count': data['sent'],
                'received_count': data['received'],
                'total_count': data['sent'] + data['received'],
                'last_email': data['last_email'],
                'accounts': list(data['accounts']),
            }
            for email, data in contact_counts.items()
        ]
        contacts.sort(key=lambda x: x['total_count'], reverse=True)
        return contacts[:limit]


# =============================================================================
# GOOGLE PEOPLE API (CONTACT ENRICHMENT)
# =============================================================================

class GooglePeopleAPI:
    """Access Google People API for rich contact information"""

    def __init__(self):
        self.services = {}  # account_email -> service
        self._load_all_services()

    def _load_gmail_token(self, account_email: str) -> Optional[Dict]:
        """Load token (reusing Gmail tokens which should have People scope)"""
        token_file = f"tokens_{account_email.replace('@', '_').replace('.', '_')}.json"

        for token_dir in GMAIL_TOKEN_DIRS:
            token_path = token_dir / token_file
            if token_path.exists():
                try:
                    with open(token_path, 'r') as f:
                        return json.load(f)
                except:
                    continue

        env_key = f"GMAIL_TOKEN_{account_email.replace('@', '_').replace('.', '_').upper()}"
        env_token = os.getenv(env_key)
        if env_token:
            try:
                return json.loads(env_token)
            except:
                pass

        return None

    def _load_all_services(self):
        """Load People API services for all configured accounts"""
        if not GOOGLE_API_AVAILABLE:
            return

        for account in GMAIL_ACCOUNTS:
            token_data = self._load_gmail_token(account)
            if token_data:
                try:
                    creds = Credentials.from_authorized_user_info(token_data)
                    service = build('people', 'v1', credentials=creds)
                    self.services[account] = service
                except Exception as e:
                    print(f"Failed to load People API for {account}: {e}")

    def is_available(self) -> bool:
        return len(self.services) > 0

    def get_all_contacts(self, limit: int = 1000) -> List[Dict]:
        """Get all Google contacts with photos and details"""
        all_contacts = []
        seen_emails = set()

        for account, service in self.services.items():
            try:
                results = service.people().connections().list(
                    resourceName='people/me',
                    pageSize=min(limit, 1000),
                    personFields='names,emailAddresses,phoneNumbers,photos,organizations,biographies,birthdays,addresses,urls'
                ).execute()

                connections = results.get('connections', [])

                for person in connections:
                    # Get primary email
                    emails = person.get('emailAddresses', [])
                    primary_email = emails[0].get('value', '').lower() if emails else None

                    if primary_email and primary_email in seen_emails:
                        continue
                    if primary_email:
                        seen_emails.add(primary_email)

                    # Get name
                    names = person.get('names', [])
                    display_name = names[0].get('displayName', '') if names else ''
                    first_name = names[0].get('givenName', '') if names else ''
                    last_name = names[0].get('familyName', '') if names else ''

                    # Get phone
                    phones = person.get('phoneNumbers', [])
                    primary_phone = phones[0].get('value', '') if phones else ''

                    # Get photo
                    photos = person.get('photos', [])
                    photo_url = photos[0].get('url', '') if photos else ''

                    # Get organization
                    orgs = person.get('organizations', [])
                    company = orgs[0].get('name', '') if orgs else ''
                    title = orgs[0].get('title', '') if orgs else ''

                    # Get birthday
                    birthdays = person.get('birthdays', [])
                    birthday = None
                    if birthdays:
                        bd = birthdays[0].get('date', {})
                        if bd.get('month') and bd.get('day'):
                            birthday = f"{bd.get('month'):02d}-{bd.get('day'):02d}"

                    all_contacts.append({
                        'source': f'google:{account}',
                        'resource_name': person.get('resourceName', ''),
                        'display_name': display_name,
                        'first_name': first_name,
                        'last_name': last_name,
                        'email': primary_email,
                        'all_emails': [e.get('value', '') for e in emails],
                        'phone': primary_phone,
                        'all_phones': [p.get('value', '') for p in phones],
                        'photo_url': photo_url,
                        'company': company,
                        'title': title,
                        'birthday': birthday,
                    })

            except Exception as e:
                print(f"People API error for {account}: {e}")

        return all_contacts

    def search_contacts(self, query: str, limit: int = 20) -> List[Dict]:
        """Search Google contacts by name or email"""
        results = []

        for account, service in self.services.items():
            try:
                search_results = service.people().searchContacts(
                    query=query,
                    readMask='names,emailAddresses,phoneNumbers,photos,organizations',
                    pageSize=min(limit, 30)
                ).execute()

                for result in search_results.get('results', []):
                    person = result.get('person', {})

                    names = person.get('names', [])
                    emails = person.get('emailAddresses', [])
                    phones = person.get('phoneNumbers', [])
                    photos = person.get('photos', [])
                    orgs = person.get('organizations', [])

                    results.append({
                        'source': f'google:{account}',
                        'display_name': names[0].get('displayName', '') if names else '',
                        'email': emails[0].get('value', '') if emails else '',
                        'phone': phones[0].get('value', '') if phones else '',
                        'photo_url': photos[0].get('url', '') if photos else '',
                        'company': orgs[0].get('name', '') if orgs else '',
                    })

            except Exception as e:
                print(f"People API search error for {account}: {e}")

        return results[:limit]

    def get_contact_photo(self, email: str) -> Optional[str]:
        """Get photo URL for a contact by email"""
        for account, service in self.services.items():
            try:
                results = service.people().searchContacts(
                    query=email,
                    readMask='photos',
                    pageSize=1
                ).execute()

                for result in results.get('results', []):
                    photos = result.get('person', {}).get('photos', [])
                    if photos:
                        return photos[0].get('url')
            except:
                continue

        return None


# =============================================================================
# INTERACTION TRACKER
# =============================================================================

class InteractionTracker:
    """Track and analyze interactions across all channels"""

    def __init__(self):
        self.imessage = iMessageReader()

    def log_interaction(self, interaction: Interaction) -> Optional[int]:
        """Log an interaction to the database"""
        conn = get_db_connection()
        if not conn:
            return None

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO atlas_interactions (
                contact_id, contact_name, contact_email,
                type, occurred_at, subject, summary, content,
                source, source_id, sentiment_score, sentiment_label,
                metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            interaction.contact_id,
            interaction.contact_name,
            interaction.contact_email,
            interaction.type.value,
            interaction.occurred_at,
            interaction.subject,
            interaction.summary,
            interaction.content,
            interaction.source,
            interaction.source_id,
            interaction.sentiment_score,
            interaction.sentiment_label,
            json.dumps(interaction.metadata),
        ))

        interaction_id = cursor.lastrowid

        # Update contact's last interaction
        if interaction.contact_id:
            cursor.execute("""
                UPDATE atlas_contacts
                SET last_interaction_at = %s
                WHERE id = %s
            """, (interaction.occurred_at, interaction.contact_id))

        conn.commit()
        cursor.close()
        conn.close()

        return interaction_id

    def get_interactions_with(
        self,
        contact_id: Optional[int] = None,
        contact_email: Optional[str] = None,
        days: int = 90,
        limit: int = 50
    ) -> List[Interaction]:
        """Get recent interactions with a contact"""
        conn = get_db_connection()
        if not conn:
            return []

        cursor = conn.cursor()

        threshold = datetime.now() - timedelta(days=days)

        if contact_id:
            cursor.execute("""
                SELECT * FROM atlas_interactions
                WHERE contact_id = %s AND occurred_at > %s
                ORDER BY occurred_at DESC
                LIMIT %s
            """, (contact_id, threshold, limit))
        elif contact_email:
            cursor.execute("""
                SELECT * FROM atlas_interactions
                WHERE contact_email = %s AND occurred_at > %s
                ORDER BY occurred_at DESC
                LIMIT %s
            """, (contact_email, threshold, limit))
        else:
            return []

        interactions = []
        for row in cursor.fetchall():
            interactions.append(Interaction(
                id=row['id'],
                contact_id=row['contact_id'],
                contact_name=row['contact_name'],
                contact_email=row['contact_email'],
                type=InteractionType(row['type']),
                occurred_at=row['occurred_at'],
                subject=row['subject'] or '',
                summary=row['summary'] or '',
                content=row['content'] or '',
                source=row['source'] or '',
                source_id=row['source_id'] or '',
                sentiment_score=row['sentiment_score'] or 0,
                sentiment_label=row['sentiment_label'] or 'neutral',
                metadata=json.loads(row['metadata']) if row['metadata'] else {},
            ))

        cursor.close()
        conn.close()

        return interactions

    def sync_imessage_interactions(
        self,
        contact_email_or_phone: str,
        contact_id: Optional[int] = None,
        contact_name: str = "",
        days: int = 90
    ) -> int:
        """Sync iMessage conversations as interactions"""
        if not self.imessage.is_available():
            return 0

        messages = self.imessage.get_conversations_with(
            contact_email_or_phone,
            days=days,
            limit=100
        )

        synced = 0
        for msg in messages:
            # Check if already synced
            if self._interaction_exists('imessage', str(msg['id'])):
                continue

            interaction = Interaction(
                contact_id=contact_id,
                contact_name=contact_name,
                contact_email=contact_email_or_phone,
                type=InteractionType.IMESSAGE_SENT if msg['is_from_me'] else InteractionType.IMESSAGE_RECEIVED,
                occurred_at=datetime.fromisoformat(msg['date']) if msg['date'] else datetime.now(),
                content=msg['text'] or '',
                summary=msg['text'][:200] if msg['text'] else '',
                source='imessage',
                source_id=str(msg['id']),
            )

            if self.log_interaction(interaction):
                synced += 1

        return synced

    def _interaction_exists(self, source: str, source_id: str) -> bool:
        """Check if interaction already logged"""
        conn = get_db_connection()
        if not conn:
            return False

        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM atlas_interactions
            WHERE source = %s AND source_id = %s
            LIMIT 1
        """, (source, source_id))

        exists = cursor.fetchone() is not None
        cursor.close()
        conn.close()

        return exists


# =============================================================================
# COMMITMENT TRACKER
# =============================================================================

class CommitmentTracker:
    """Extract and track commitments from interactions"""

    def log_commitment(self, commitment: Commitment) -> Optional[int]:
        """Log a commitment to the database"""
        conn = get_db_connection()
        if not conn:
            return None

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO atlas_commitments (
                contact_id, contact_name, interaction_id,
                description, made_by, due_date,
                status, confidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            commitment.contact_id,
            commitment.contact_name,
            commitment.interaction_id,
            commitment.description,
            commitment.made_by,
            commitment.due_date,
            commitment.status.value,
            commitment.confidence,
        ))

        commitment_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()

        return commitment_id

    def get_open_commitments(
        self,
        contact_id: Optional[int] = None,
        made_by: Optional[str] = None
    ) -> List[Commitment]:
        """Get open (pending/overdue) commitments"""
        conn = get_db_connection()
        if not conn:
            return []

        cursor = conn.cursor()

        query = """
            SELECT * FROM atlas_commitments
            WHERE status IN ('pending', 'overdue')
        """
        params = []

        if contact_id:
            query += " AND contact_id = %s"
            params.append(contact_id)

        if made_by:
            query += " AND made_by = %s"
            params.append(made_by)

        query += " ORDER BY due_date ASC, extracted_at DESC"

        cursor.execute(query, params)

        commitments = []
        for row in cursor.fetchall():
            commitments.append(Commitment(
                id=row['id'],
                contact_id=row['contact_id'],
                contact_name=row['contact_name'] or '',
                interaction_id=row['interaction_id'],
                description=row['description'],
                made_by=row['made_by'],
                due_date=row['due_date'],
                status=CommitmentStatus(row['status']),
                completed_at=row['completed_at'],
                confidence=row['confidence'] or 0.8,
            ))

        cursor.close()
        conn.close()

        return commitments

    def complete_commitment(self, commitment_id: int) -> bool:
        """Mark a commitment as completed"""
        conn = get_db_connection()
        if not conn:
            return False

        cursor = conn.cursor()
        cursor.execute("""
            UPDATE atlas_commitments
            SET status = 'completed', completed_at = NOW()
            WHERE id = %s
        """, (commitment_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return True

    def extract_commitments_from_text(self, text: str, contact_name: str = "") -> List[Dict]:
        """Use AI to extract commitments from conversation text"""
        if not GEMINI_AVAILABLE:
            return []

        prompt = f"""Analyze this conversation and extract any commitments/promises made.

Conversation:
{text[:3000]}

For each commitment found, identify:
1. description: What was promised/committed to
2. made_by: Who made the promise - "me" (the speaker/Brian) or "them" (the other party/{contact_name or 'the contact'})
3. due_date: When it's due (YYYY-MM-DD format, or null if not specified)
4. confidence: How confident you are this is a real commitment (0.0-1.0)

Return as JSON array. Only include clear commitments, not vague statements.
Example: [{{"description": "Send quarterly report", "made_by": "me", "due_date": "2024-01-15", "confidence": 0.9}}]

If no commitments found, return: []"""

        result = generate_content_with_fallback(prompt)
        if not result:
            return []

        try:
            # Clean up response
            result = result.strip()
            if result.startswith('```'):
                result = result.split('\n', 1)[1]
            if result.endswith('```'):
                result = result.rsplit('```', 1)[0]
            result = result.strip()

            commitments = json.loads(result)
            return commitments if isinstance(commitments, list) else []
        except:
            return []


# =============================================================================
# RELATIONSHIP HEALTH ANALYZER
# =============================================================================

class RelationshipHealthAnalyzer:
    """Analyze and score relationship health"""

    def __init__(self):
        self.tracker = InteractionTracker()
        self.commitments = CommitmentTracker()

    def calculate_health(
        self,
        contact_id: int,
        contact_name: str = "",
        target_days: int = 30
    ) -> RelationshipHealth:
        """Calculate comprehensive relationship health score"""

        # Get interactions
        interactions = self.tracker.get_interactions_with(
            contact_id=contact_id,
            days=365  # Look at full year
        )

        # Get commitments
        open_commitments = self.commitments.get_open_commitments(contact_id=contact_id)

        health = RelationshipHealth(
            contact_id=contact_id,
            contact_name=contact_name,
            total_interactions=len(interactions),
        )

        if not interactions:
            health.overall_score = 0.3
            health.trend = RelationshipTrend.NEW
            health.recommendations.append(f"No recorded interactions with {contact_name}. Consider reaching out.")
            return health

        # Last interaction
        health.last_interaction = interactions[0].occurred_at
        health.days_since_contact = (datetime.now() - health.last_interaction).days

        # Recency score
        if health.days_since_contact <= target_days:
            health.recency_score = 1.0 - (health.days_since_contact / target_days * 0.3)
        elif health.days_since_contact <= target_days * 2:
            health.recency_score = 0.5
        else:
            health.recency_score = max(0.1, 1.0 - health.days_since_contact / 180)

        # Frequency score (interactions per month)
        recent_90 = [i for i in interactions if (datetime.now() - i.occurred_at).days <= 90]
        monthly_rate = len(recent_90) / 3
        target_monthly = 30 / target_days
        health.frequency_score = min(1.0, monthly_rate / target_monthly)

        # Sentiment score
        sentiments = [i.sentiment_score for i in interactions[:10] if i.sentiment_score]
        if sentiments:
            avg_sentiment = sum(sentiments) / len(sentiments)
            health.sentiment_score = (avg_sentiment + 1) / 2  # Convert -1..1 to 0..1

        # Reciprocity (balance of sent vs received)
        sent = len([i for i in interactions if 'sent' in i.type.value])
        received = len([i for i in interactions if 'received' in i.type.value])
        if sent + received > 0:
            balance = min(sent, received) / max(sent, received) if max(sent, received) > 0 else 0.5
            health.reciprocity_score = balance

        # Commitment score
        completed = len([c for c in open_commitments if c.status == CommitmentStatus.COMPLETED])
        total_commitments = len(open_commitments) + completed
        if total_commitments > 0:
            # Penalize for overdue commitments
            overdue = len([c for c in open_commitments if c.due_date and c.due_date < datetime.now().date()])
            health.commitment_score = (completed / total_commitments) * (1 - overdue * 0.2)

        # Overall score
        health.overall_score = (
            health.recency_score * 0.3 +
            health.frequency_score * 0.25 +
            health.sentiment_score * 0.2 +
            health.reciprocity_score * 0.15 +
            health.commitment_score * 0.1
        )

        # Determine trend
        if len(interactions) >= 5:
            recent_sentiment = sum(i.sentiment_score for i in interactions[:3]) / 3
            older_sentiment = sum(i.sentiment_score for i in interactions[3:6]) / min(3, len(interactions) - 3)
            if recent_sentiment > older_sentiment + 0.2:
                health.trend = RelationshipTrend.IMPROVING
            elif recent_sentiment < older_sentiment - 0.2:
                health.trend = RelationshipTrend.DECLINING
            else:
                health.trend = RelationshipTrend.STABLE

        # Generate recommendations
        if health.days_since_contact > target_days:
            health.recommendations.append(
                f"Haven't connected in {health.days_since_contact} days. Schedule a catch-up."
            )

        if health.reciprocity_score < 0.4:
            if sent > received:
                health.recommendations.append("You've been doing most of the reaching out. Give them space or try a different approach.")
            else:
                health.recommendations.append("They've been reaching out more. Make sure to reciprocate.")

        for c in open_commitments:
            if c.due_date and c.due_date < datetime.now().date():
                if c.made_by == 'me':
                    health.recommendations.append(f"Overdue: You promised to '{c.description}'")
                else:
                    health.recommendations.append(f"Follow up: They promised to '{c.description}'")

        return health


# =============================================================================
# MEETING PREP GENERATOR
# =============================================================================

class MeetingPrepGenerator:
    """Generate pre-meeting preparation briefs"""

    def __init__(self):
        self.tracker = InteractionTracker()
        self.commitments = CommitmentTracker()
        self.health = RelationshipHealthAnalyzer()

    def generate_brief(
        self,
        event_title: str,
        event_time: datetime,
        event_location: str,
        attendee_emails: List[str],
        attendee_names: List[str] = None
    ) -> MeetingBrief:
        """Generate comprehensive meeting prep brief"""

        brief = MeetingBrief(
            event_title=event_title,
            event_time=event_time,
            event_location=event_location,
        )

        # Process each attendee
        for i, email in enumerate(attendee_emails):
            name = attendee_names[i] if attendee_names and i < len(attendee_names) else email.split('@')[0]

            attendee_brief = self._build_attendee_brief(email, name)
            brief.attendees.append(attendee_brief)

            # Collect open commitments
            for c in attendee_brief.get('open_commitments', []):
                brief.open_commitments.append(c)

            # Collect recent interactions
            for i in attendee_brief.get('recent_interactions', []):
                brief.recent_interactions.append(i)

        # Generate talking points with AI
        if GEMINI_AVAILABLE and brief.attendees:
            brief.talking_points = self._generate_talking_points(brief)

        return brief

    def _build_attendee_brief(self, email: str, name: str) -> Dict:
        """Build brief for single attendee"""

        # Get recent interactions
        interactions = self.tracker.get_interactions_with(
            contact_email=email,
            days=90,
            limit=5
        )

        # Get open commitments
        # (Would need contact_id, skipping for now if not available)

        return {
            'email': email,
            'name': name,
            'recent_interactions': [
                {
                    'date': i.occurred_at.isoformat(),
                    'type': i.type.value,
                    'summary': i.summary[:200],
                }
                for i in interactions
            ],
            'last_contact': interactions[0].occurred_at.isoformat() if interactions else None,
            'interaction_count': len(interactions),
            'open_commitments': [],  # Would populate with contact_id
        }

    def _generate_talking_points(self, brief: MeetingBrief) -> List[str]:
        """Generate AI-powered talking points"""

        context = f"""
Meeting: {brief.event_title}
Time: {brief.event_time}
Location: {brief.event_location}

Attendees:
"""
        for a in brief.attendees:
            context += f"\n- {a['name']}"
            if a['recent_interactions']:
                last = a['recent_interactions'][0]
                context += f" (Last contact: {last['date'][:10]}, discussed: {last['summary'][:100]})"

        if brief.open_commitments:
            context += "\n\nOpen commitments:"
            for c in brief.open_commitments[:5]:
                context += f"\n- {c.get('description', '')}"

        prompt = f"""{context}

Generate 3-5 specific talking points for this meeting. Include:
1. Topics to follow up on from previous conversations
2. Open loops to close
3. Relationship-building opportunities (personal topics if known)
4. Strategic asks or offers

Return as a JSON array of strings."""

        result = generate_content_with_fallback(prompt)
        if not result:
            return ["Review recent conversations before meeting"]

        try:
            result = result.strip()
            if result.startswith('```'):
                result = result.split('\n', 1)[1]
            if result.endswith('```'):
                result = result.rsplit('```', 1)[0]

            points = json.loads(result.strip())
            return points if isinstance(points, list) else [str(points)]
        except:
            return ["Review recent conversations before meeting"]


# =============================================================================
# NUDGE ENGINE
# =============================================================================

class NudgeEngine:
    """Generate proactive relationship nudges"""

    def __init__(self):
        self.health = RelationshipHealthAnalyzer()
        self.commitments = CommitmentTracker()

    def generate_daily_nudges(self, limit: int = 10) -> List[Nudge]:
        """Generate today's relationship nudges"""

        nudges = []

        # 1. Overdue contacts
        nudges.extend(self._overdue_contact_nudges())

        # 2. Overdue commitments
        nudges.extend(self._commitment_nudges())

        # 3. Upcoming events (birthdays, etc.)
        # nudges.extend(self._upcoming_event_nudges())

        # Prioritize and limit
        nudges.sort(key=lambda n: {'high': 0, 'medium': 1, 'low': 2}.get(n.priority, 1))

        return nudges[:limit]

    def _overdue_contact_nudges(self) -> List[Nudge]:
        """Generate nudges for overdue contacts"""
        nudges = []

        conn = get_db_connection()
        if not conn:
            return nudges

        cursor = conn.cursor()

        # Find contacts overdue for contact
        cursor.execute("""
            SELECT id, name, email, target_contact_days, last_interaction_at,
                   DATEDIFF(NOW(), last_interaction_at) as days_since
            FROM atlas_contacts
            WHERE last_interaction_at IS NOT NULL
            AND DATEDIFF(NOW(), last_interaction_at) > COALESCE(target_contact_days, 30)
            ORDER BY days_since DESC
            LIMIT 10
        """)

        for row in cursor.fetchall():
            days = row['days_since']
            target = row['target_contact_days'] or 30

            priority = 'high' if days > target * 2 else 'medium'

            nudges.append(Nudge(
                type='overdue_contact',
                priority=priority,
                contact_id=row['id'],
                contact_name=row['name'],
                title=f"Reconnect with {row['name']}",
                body=f"It's been {days} days since you connected (target: {target} days)",
                action="Schedule a call or send a quick message",
            ))

        cursor.close()
        conn.close()

        return nudges

    def _commitment_nudges(self) -> List[Nudge]:
        """Generate nudges for overdue/upcoming commitments"""
        nudges = []

        commitments = self.commitments.get_open_commitments()
        today = datetime.now().date()

        for c in commitments:
            if not c.due_date:
                continue

            days_until = (c.due_date - today).days

            if days_until < 0:
                # Overdue
                nudges.append(Nudge(
                    type='commitment_overdue',
                    priority='high',
                    contact_id=c.contact_id,
                    contact_name=c.contact_name,
                    title=f"Overdue: {c.description[:50]}",
                    body=f"{'You promised' if c.made_by == 'me' else c.contact_name + ' promised'} this {abs(days_until)} days ago",
                    action="Complete or follow up",
                ))
            elif days_until <= 3:
                # Due soon
                nudges.append(Nudge(
                    type='commitment_due_soon',
                    priority='medium',
                    contact_id=c.contact_id,
                    contact_name=c.contact_name,
                    title=f"Due soon: {c.description[:50]}",
                    body=f"Due in {days_until} day{'s' if days_until != 1 else ''}",
                    action="Make progress on this",
                ))

        return nudges

    def save_nudge(self, nudge: Nudge) -> Optional[int]:
        """Save a nudge to the database"""
        conn = get_db_connection()
        if not conn:
            return None

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO atlas_nudges (
                contact_id, contact_name, type, priority,
                title, body, action
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            nudge.contact_id,
            nudge.contact_name,
            nudge.type,
            nudge.priority,
            nudge.title,
            nudge.body,
            nudge.action,
        ))

        nudge_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()

        return nudge_id

    def dismiss_nudge(self, nudge_id: int) -> bool:
        """Dismiss a nudge"""
        conn = get_db_connection()
        if not conn:
            return False

        cursor = conn.cursor()
        cursor.execute("""
            UPDATE atlas_nudges
            SET is_dismissed = TRUE, dismissed_at = NOW()
            WHERE id = %s
        """, (nudge_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return True


# =============================================================================
# SENTIMENT ANALYZER
# =============================================================================

class SentimentAnalyzer:
    """Analyze sentiment of interactions"""

    def analyze(self, text: str) -> Dict:
        """Analyze sentiment of text"""
        if not GEMINI_AVAILABLE or not text:
            return {'score': 0.0, 'label': 'neutral', 'signals': [], 'concerns': []}

        prompt = f"""Analyze the sentiment of this message/interaction:

"{text[:1500]}"

Return JSON with:
- score: float from -1.0 (very negative) to 1.0 (very positive)
- label: "positive", "negative", or "neutral"
- signals: list of positive signals (e.g., "enthusiastic", "agreed to next steps")
- concerns: list of concerns (e.g., "seemed hesitant", "pushed back on timeline")

Only return the JSON, no other text."""

        result = generate_content_with_fallback(prompt)
        if not result:
            return {'score': 0.0, 'label': 'neutral', 'signals': [], 'concerns': []}

        try:
            result = result.strip()
            if result.startswith('```'):
                result = result.split('\n', 1)[1]
            if result.endswith('```'):
                result = result.rsplit('```', 1)[0]

            analysis = json.loads(result.strip())
            return analysis
        except:
            return {'score': 0.0, 'label': 'neutral', 'signals': [], 'concerns': []}


# =============================================================================
# UNIFIED ATLAS SERVICE
# =============================================================================

class AtlasService:
    """Unified service for relationship intelligence"""

    def __init__(self):
        self.interactions = InteractionTracker()
        self.commitments = CommitmentTracker()
        self.health = RelationshipHealthAnalyzer()
        self.meeting_prep = MeetingPrepGenerator()
        self.nudges = NudgeEngine()
        self.sentiment = SentimentAnalyzer()
        self.imessage = iMessageReader()

    def prep_for_person(self, name_or_email: str) -> Dict:
        """Get full context before talking to someone"""

        # Search for contact
        contact_info = None
        if CONTACTS_AVAILABLE:
            results = search_contacts(name_or_email, limit=1)
            if results:
                contact_info = results[0]

        # Get interactions
        interactions = self.interactions.get_interactions_with(
            contact_email=name_or_email,
            days=180,
            limit=10
        )

        # Get iMessage history
        imessage_recent = self.imessage.get_conversations_with(
            name_or_email,
            days=30,
            limit=20
        )

        # Get commitments
        commitments = self.commitments.get_open_commitments()
        relevant_commitments = [
            c.to_dict() for c in commitments
            if name_or_email.lower() in (c.contact_name or '').lower()
            or name_or_email.lower() in (c.contact_email or '').lower()
        ]

        return {
            'contact': contact_info,
            'interactions': [i.to_dict() for i in interactions],
            'imessage_recent': imessage_recent,
            'open_commitments': relevant_commitments,
            'last_contact': interactions[0].occurred_at.isoformat() if interactions else None,
        }

    def log_quick_note(
        self,
        contact_name: str,
        note: str,
        extract_commitments: bool = True
    ) -> Dict:
        """Quick note about an interaction"""

        # Create interaction
        interaction = Interaction(
            contact_name=contact_name,
            type=InteractionType.NOTE,
            occurred_at=datetime.now(),
            summary=note[:500],
            content=note,
            source='manual',
        )

        # Analyze sentiment
        sentiment = self.sentiment.analyze(note)
        interaction.sentiment_score = sentiment.get('score', 0)
        interaction.sentiment_label = sentiment.get('label', 'neutral')

        interaction_id = self.interactions.log_interaction(interaction)

        # Extract commitments
        extracted_commitments = []
        if extract_commitments and interaction_id:
            commitment_data = self.commitments.extract_commitments_from_text(note, contact_name)
            for c in commitment_data:
                commitment = Commitment(
                    contact_name=contact_name,
                    interaction_id=interaction_id,
                    description=c.get('description', ''),
                    made_by=c.get('made_by', 'me'),
                    due_date=datetime.strptime(c['due_date'], '%Y-%m-%d').date() if c.get('due_date') else None,
                    confidence=c.get('confidence', 0.8),
                )
                cid = self.commitments.log_commitment(commitment)
                if cid:
                    extracted_commitments.append(commitment.to_dict())

        return {
            'interaction_id': interaction_id,
            'sentiment': sentiment,
            'commitments_extracted': extracted_commitments,
        }

    def get_daily_brief(self) -> Dict:
        """Get daily relationship brief"""

        # Get nudges
        nudges = self.nudges.generate_daily_nudges(limit=10)

        # Get open commitments due soon
        all_commitments = self.commitments.get_open_commitments()
        due_soon = [
            c.to_dict() for c in all_commitments
            if c.due_date and (c.due_date - datetime.now().date()).days <= 7
        ]

        # Get iMessage active contacts
        imessage_active = self.imessage.get_recent_contacts(days=7, limit=10)

        return {
            'nudges': [n.to_dict() for n in nudges],
            'commitments_due_soon': due_soon,
            'imessage_active': imessage_active,
            'generated_at': datetime.now().isoformat(),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_atlas_service = None

def get_atlas() -> AtlasService:
    """Get singleton AtlasService instance"""
    global _atlas_service
    if _atlas_service is None:
        _atlas_service = AtlasService()
    return _atlas_service


def prep_for_person(name_or_email: str) -> Dict:
    """Quick prep for talking to someone"""
    return get_atlas().prep_for_person(name_or_email)


def log_interaction_note(contact_name: str, note: str) -> Dict:
    """Log a quick note about an interaction"""
    return get_atlas().log_quick_note(contact_name, note)


def get_daily_nudges() -> List[Dict]:
    """Get today's relationship nudges"""
    nudges = get_atlas().nudges.generate_daily_nudges()
    return [n.to_dict() for n in nudges]


def get_relationship_health(contact_name: str) -> Dict:
    """Get relationship health for a contact"""
    # Would need to look up contact_id first
    return get_atlas().health.calculate_health(0, contact_name).to_dict()


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ATLAS Relationship Intelligence')
    parser.add_argument('--init', action='store_true', help='Initialize database tables')
    parser.add_argument('--prep', type=str, help='Prep for talking to someone')
    parser.add_argument('--nudges', action='store_true', help='Get daily nudges')
    parser.add_argument('--note', type=str, help='Log a note (format: "Name: note text")')
    parser.add_argument('--imessage', type=str, help='Get iMessage history with contact')
    args = parser.parse_args()

    if args.init:
        print("Initializing ATLAS database tables...")
        create_atlas_tables()

    elif args.prep:
        print(f"\n=== Prep for: {args.prep} ===\n")
        result = prep_for_person(args.prep)
        print(json.dumps(result, indent=2, default=str))

    elif args.nudges:
        print("\n=== Today's Relationship Nudges ===\n")
        nudges = get_daily_nudges()
        for n in nudges:
            print(f"[{n['priority'].upper()}] {n['title']}")
            print(f"  {n['body']}")
            print(f"  Action: {n['action']}")
            print()

    elif args.note:
        if ':' in args.note:
            name, note_text = args.note.split(':', 1)
            result = log_interaction_note(name.strip(), note_text.strip())
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Format: --note 'Name: note text'")

    elif args.imessage:
        print(f"\n=== iMessage with: {args.imessage} ===\n")
        reader = iMessageReader()
        if reader.is_available():
            messages = reader.get_conversations_with(args.imessage, days=30, limit=20)
            for m in messages:
                direction = "You" if m['is_from_me'] else args.imessage
                print(f"[{m['date']}] {direction}: {m['text'][:100]}")
        else:
            print("iMessage database not accessible")

    else:
        print("ATLAS Relationship Intelligence")
        print("================================")
        print("\nUsage:")
        print("  --init        Initialize database tables")
        print("  --prep NAME   Prep for talking to someone")
        print("  --nudges      Get daily relationship nudges")
        print("  --note 'Name: text'  Log interaction note")
        print("  --imessage CONTACT   Get iMessage history")

        # Show stats
        atlas = get_atlas()
        if atlas.imessage.is_available():
            recent = atlas.imessage.get_recent_contacts(days=7, limit=5)
            if recent:
                print(f"\n📱 Recent iMessage contacts (7 days):")
                for c in recent:
                    print(f"  {c['handle']}: {c['message_count']} messages")
