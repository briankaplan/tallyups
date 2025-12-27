#!/usr/bin/env python3
"""
Smart Notes Service
===================

Generates contextual, human-quality expense descriptions by combining:
- Transaction data
- Receipt data (OCR)
- Calendar events (Google Calendar)
- Contact information (Google Contacts)
- Historical patterns

Features:
- Fast context gathering (< 2 seconds with caching)
- Audit/tax compliant notes
- Learning from user corrections
- Batch processing support

Example Good Notes:
- "Business dinner with Patrick Humes (MCR co-founder) discussing Q1 2026 MCR marketing budget and Miranda Lambert confirmation. Also present: Tim McGraw. 3 attendees."
- "Uber from downtown Nashville to BNA airport for flight to LA for Business investor meeting with Skydance."
"""

import os
import json
import hashlib
import logging
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from functools import lru_cache
import pickle
import re

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# =============================================================================
# Try to import dependencies
# =============================================================================

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    Anthropic = None

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Contact:
    """Contact information for attendee enrichment."""
    id: Optional[int] = None
    name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    relationship: Optional[str] = None  # client, partner, investor, team, vendor
    business_type: Optional[str] = None  # Business, MCR, Personal
    tags: List[str] = field(default_factory=list)

    def get_display_name(self) -> str:
        """Get formatted display name with title/company."""
        parts = [self.name or f"{self.first_name} {self.last_name}".strip()]

        if self.job_title and self.company:
            parts.append(f"({self.job_title}, {self.company})")
        elif self.job_title:
            parts.append(f"({self.job_title})")
        elif self.company:
            parts.append(f"({self.company})")
        elif self.relationship:
            parts.append(f"({self.relationship})")

        return " ".join(parts)


@dataclass
class CalendarEvent:
    """Calendar event for context."""
    id: str = ""
    title: str = ""
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    attendees: List[str] = field(default_factory=list)
    organizer: Optional[str] = None
    is_business: bool = True
    event_type: Optional[str] = None  # meeting, lunch, travel, etc.

    def matches_time(self, transaction_time: datetime, hours_window: int = 2) -> bool:
        """Check if event is within time window of transaction."""
        if not self.start_time:
            return False
        delta = abs((transaction_time - self.start_time).total_seconds()) / 3600
        return delta <= hours_window


@dataclass
class ReceiptData:
    """OCR extracted receipt data."""
    merchant: str = ""
    amount: Optional[Decimal] = None
    date: Optional[datetime] = None
    items: List[Dict[str, Any]] = field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    tip: Optional[Decimal] = None
    total: Optional[Decimal] = None
    server_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    raw_text: Optional[str] = None


@dataclass
class TransactionContext:
    """Complete context for note generation."""
    # Core transaction data
    merchant: str = ""
    amount: Decimal = Decimal("0")
    date: Optional[datetime] = None
    description: Optional[str] = None
    category: Optional[str] = None
    business_type: Optional[str] = None  # Business, MCR, Personal
    card_used: Optional[str] = None

    # Receipt data
    receipt: Optional[ReceiptData] = None

    # Calendar context
    calendar_events: List[CalendarEvent] = field(default_factory=list)
    closest_event: Optional[CalendarEvent] = None

    # Contact context
    attendees: List[Contact] = field(default_factory=list)

    # Historical patterns
    previous_notes: List[str] = field(default_factory=list)
    typical_purpose: Optional[str] = None
    recurring_pattern: Optional[str] = None

    # Merchant intelligence
    merchant_hint: Optional[str] = None


@dataclass
class NoteResult:
    """Result of note generation."""
    note: str = ""
    attendees: List[Contact] = field(default_factory=list)
    attendee_count: int = 0
    calendar_event: Optional[CalendarEvent] = None
    business_purpose: str = ""
    tax_category: str = ""
    confidence: float = 0.0
    data_sources: List[str] = field(default_factory=list)
    needs_review: bool = False
    generated_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "note": self.note,
            "attendees": [asdict(a) for a in self.attendees],
            "attendee_count": self.attendee_count,
            "calendar_event": asdict(self.calendar_event) if self.calendar_event else None,
            "business_purpose": self.business_purpose,
            "tax_category": self.tax_category,
            "confidence": round(self.confidence, 2),
            "data_sources": self.data_sources,
            "needs_review": self.needs_review,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


# =============================================================================
# Caching Layer
# =============================================================================

class ContextCache:
    """
    In-memory cache for calendar events and contacts.
    Reduces API calls and improves response time.
    """

    def __init__(self, cache_dir: Optional[Path] = None, ttl_seconds: int = 3600):
        self.cache_dir = cache_dir or Path(__file__).parent.parent / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

        # In-memory caches
        self._calendar_cache: Dict[str, Tuple[datetime, List[CalendarEvent]]] = {}
        self._contacts_cache: Dict[str, Tuple[datetime, Contact]] = {}
        self._contacts_loaded = False
        self._all_contacts: List[Contact] = []

    def _is_expired(self, cached_at: datetime) -> bool:
        """Check if cache entry is expired."""
        return (datetime.now() - cached_at).total_seconds() > self.ttl_seconds

    def get_calendar_events(self, date: datetime, account: str) -> Optional[List[CalendarEvent]]:
        """Get cached calendar events for a date."""
        cache_key = f"{account}:{date.strftime('%Y-%m-%d')}"

        if cache_key in self._calendar_cache:
            cached_at, events = self._calendar_cache[cache_key]
            if not self._is_expired(cached_at):
                return events
        return None

    def set_calendar_events(self, date: datetime, account: str, events: List[CalendarEvent]):
        """Cache calendar events for a date."""
        cache_key = f"{account}:{date.strftime('%Y-%m-%d')}"
        self._calendar_cache[cache_key] = (datetime.now(), events)

    def get_contact(self, identifier: str) -> Optional[Contact]:
        """Get cached contact by name or email."""
        identifier_lower = identifier.lower()

        if identifier_lower in self._contacts_cache:
            cached_at, contact = self._contacts_cache[identifier_lower]
            if not self._is_expired(cached_at):
                return contact
        return None

    def set_contact(self, identifier: str, contact: Contact):
        """Cache a contact."""
        self._contacts_cache[identifier.lower()] = (datetime.now(), contact)

    def load_all_contacts(self, contacts: List[Contact]):
        """Bulk load contacts into cache."""
        self._all_contacts = contacts
        self._contacts_loaded = True

        # Index by name and email
        for contact in contacts:
            if contact.name:
                self._contacts_cache[contact.name.lower()] = (datetime.now(), contact)
            if contact.first_name:
                self._contacts_cache[contact.first_name.lower()] = (datetime.now(), contact)
            if contact.email:
                self._contacts_cache[contact.email.lower()] = (datetime.now(), contact)

    def search_contacts(self, query: str) -> List[Contact]:
        """Search contacts by name (fuzzy match)."""
        if not self._contacts_loaded:
            return []

        query_lower = query.lower()
        results = []

        for contact in self._all_contacts:
            name_lower = contact.name.lower() if contact.name else ""
            first_lower = contact.first_name.lower() if contact.first_name else ""
            last_lower = contact.last_name.lower() if contact.last_name else ""

            if (query_lower in name_lower or
                query_lower in first_lower or
                query_lower in last_lower or
                name_lower in query_lower):
                results.append(contact)

        return results

    def clear(self):
        """Clear all caches."""
        self._calendar_cache.clear()
        self._contacts_cache.clear()
        self._contacts_loaded = False
        self._all_contacts.clear()

    def save_to_disk(self):
        """Persist cache to disk."""
        cache_file = self.cache_dir / "context_cache.pkl"
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump({
                    'calendar': self._calendar_cache,
                    'contacts': self._contacts_cache,
                    'all_contacts': self._all_contacts,
                    'contacts_loaded': self._contacts_loaded,
                }, f)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def load_from_disk(self):
        """Load cache from disk."""
        cache_file = self.cache_dir / "context_cache.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    data = pickle.load(f)
                    self._calendar_cache = data.get('calendar', {})
                    self._contacts_cache = data.get('contacts', {})
                    self._all_contacts = data.get('all_contacts', [])
                    self._contacts_loaded = data.get('contacts_loaded', False)
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")


# =============================================================================
# Google Calendar Integration
# =============================================================================

class GoogleCalendarClient:
    """
    Google Calendar integration for fetching events around transaction times.
    """

    # Personal events to exclude from business context
    PERSONAL_KEYWORDS = [
        'birthday', 'bday', "b'day", 'anniversary',
        'dentist', 'doctor', 'appointment', 'checkup', 'physical',
        'school', 'pickup', 'drop off', 'dropoff', 'carpool',
        'recital', 'game', 'practice', 'soccer', 'basketball', 'football',
        'vacation', 'holiday', 'pto', 'day off',
        'haircut', 'salon', 'spa',
    ]

    # Business meeting keywords
    BUSINESS_KEYWORDS = [
        'meeting', 'call', 'lunch', 'dinner', 'coffee', 'drinks',
        'interview', 'sync', 'review', 'planning', 'strategy',
        'presentation', 'demo', 'pitch', 'investor', 'client',
    ]

    def __init__(self, credentials_dir: str = 'credentials'):
        self.credentials_dir = Path(credentials_dir)
        self._services: Dict[str, Any] = {}

        # Default accounts
        self.accounts = [
            'brian@business.com',
            'kaplan.brian@gmail.com',
            'brian@secondary.com',
        ]

    def _get_service(self, account_email: str):
        """Get authenticated Calendar API service."""
        if not GOOGLE_AVAILABLE:
            return None

        if account_email in self._services:
            return self._services[account_email]

        # Try JSON token first, then pickle
        token_json = self.credentials_dir / f'tokens_{account_email.replace("@", "_").replace(".", "_")}.json'
        token_pickle = self.credentials_dir / f'token_{account_email}.pickle'

        token_path = None
        if token_json.exists():
            token_path = token_json
        elif token_pickle.exists():
            token_path = token_pickle

        if not token_path:
            logger.warning(f"No token found for {account_email}")
            return None

        try:
            if str(token_path).endswith('.json'):
                creds = Credentials.from_authorized_user_file(str(token_path))
            else:
                with open(token_path, 'rb') as f:
                    creds = pickle.load(f)

            # Refresh if expired
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                if str(token_path).endswith('.json'):
                    with open(token_path, 'w') as f:
                        f.write(creds.to_json())
                else:
                    with open(token_path, 'wb') as f:
                        pickle.dump(creds, f)

            service = build('calendar', 'v3', credentials=creds)
            self._services[account_email] = service
            return service

        except Exception as e:
            logger.error(f"Calendar auth failed for {account_email}: {e}")
            return None

    def _is_business_event(self, title: str, description: str = "") -> bool:
        """Check if event is business-related."""
        combined = f"{title} {description}".lower()

        for keyword in self.PERSONAL_KEYWORDS:
            if keyword in combined:
                return False

        return True

    def _extract_attendee_names(self, title: str, description: str = "", attendees_list: List[Dict] = None) -> List[str]:
        """Extract attendee names from event."""
        names = set()
        text = f"{title} {description}"

        # Extract from "with X, Y, and Z" pattern
        with_match = re.search(r'(?:with|w/)\s+(.+?)(?:\s*[-@|]|$)', text, re.IGNORECASE)
        if with_match:
            names_text = with_match.group(1)
            for name in re.split(r'\s*,\s*|\s+and\s+|\s*&\s*', names_text):
                name = name.strip()
                if name and re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$', name):
                    if name not in ['Meeting', 'Lunch', 'Dinner', 'Call', 'Coffee']:
                        names.add(name)

        # Extract from "X + Y" pattern
        plus_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*\+\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', text)
        if plus_match:
            for name in plus_match.groups():
                if name:
                    names.add(name.strip())

        # Extract from "FirstName LastName - Meeting" pattern
        name_dash = re.search(r'^([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-:]', title)
        if name_dash:
            names.add(name_dash.group(1).strip())

        # Extract from attendees list (Google Calendar API)
        if attendees_list:
            for attendee in attendees_list:
                if email := attendee.get('email'):
                    # Try to extract name from email
                    display_name = attendee.get('displayName', '')
                    if display_name and not display_name.endswith('.com'):
                        names.add(display_name)

        return list(names)

    def get_events_around_time(
        self,
        transaction_time: datetime,
        hours_before: int = 2,
        hours_after: int = 2,
        accounts: List[str] = None
    ) -> List[CalendarEvent]:
        """
        Fetch calendar events within a time window around the transaction.

        Args:
            transaction_time: The transaction datetime
            hours_before: Hours to look before transaction
            hours_after: Hours to look after transaction
            accounts: List of Google accounts to check (defaults to all)

        Returns:
            List of CalendarEvent objects
        """
        if not GOOGLE_AVAILABLE:
            return []

        accounts = accounts or self.accounts
        events = []

        time_min = transaction_time - timedelta(hours=hours_before)
        time_max = transaction_time + timedelta(hours=hours_after)

        for account in accounts:
            service = self._get_service(account)
            if not service:
                continue

            try:
                result = service.events().list(
                    calendarId='primary',
                    timeMin=time_min.isoformat() + 'Z',
                    timeMax=time_max.isoformat() + 'Z',
                    singleEvents=True,
                    orderBy='startTime',
                    maxResults=20,
                ).execute()

                for item in result.get('items', []):
                    title = item.get('summary', '')
                    description = item.get('description', '')

                    # Skip personal events
                    if not self._is_business_event(title, description):
                        continue

                    # Parse start/end times
                    start_str = item.get('start', {}).get('dateTime') or item.get('start', {}).get('date')
                    end_str = item.get('end', {}).get('dateTime') or item.get('end', {}).get('date')

                    start_time = None
                    end_time = None
                    if start_str:
                        try:
                            start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        except:
                            pass
                    if end_str:
                        try:
                            end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                        except:
                            pass

                    # Extract attendees
                    attendee_names = self._extract_attendee_names(
                        title, description, item.get('attendees', [])
                    )

                    event = CalendarEvent(
                        id=item.get('id', ''),
                        title=title,
                        description=description,
                        start_time=start_time,
                        end_time=end_time,
                        location=item.get('location'),
                        attendees=attendee_names,
                        organizer=item.get('organizer', {}).get('email'),
                        is_business=True,
                    )
                    events.append(event)

            except Exception as e:
                logger.error(f"Calendar API error for {account}: {e}")

        # Sort by proximity to transaction time
        events.sort(key=lambda e: abs((e.start_time - transaction_time).total_seconds()) if e.start_time else float('inf'))

        return events


# =============================================================================
# Google Contacts Integration
# =============================================================================

class GoogleContactsClient:
    """
    Google Contacts integration for attendee enrichment.
    """

    def __init__(self, credentials_dir: str = 'credentials'):
        self.credentials_dir = Path(credentials_dir)
        self._services: Dict[str, Any] = {}

        self.accounts = [
            'brian@business.com',
            'kaplan.brian@gmail.com',
            'brian@secondary.com',
        ]

    def _get_service(self, account_email: str):
        """Get authenticated People API service."""
        if not GOOGLE_AVAILABLE:
            return None

        if account_email in self._services:
            return self._services[account_email]

        token_json = self.credentials_dir / f'tokens_{account_email.replace("@", "_").replace(".", "_")}.json'
        token_pickle = self.credentials_dir / f'token_{account_email}.pickle'

        token_path = None
        if token_json.exists():
            token_path = token_json
        elif token_pickle.exists():
            token_path = token_pickle

        if not token_path:
            return None

        try:
            if str(token_path).endswith('.json'):
                creds = Credentials.from_authorized_user_file(str(token_path))
            else:
                with open(token_path, 'rb') as f:
                    creds = pickle.load(f)

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())

            service = build('people', 'v1', credentials=creds)
            self._services[account_email] = service
            return service

        except Exception as e:
            logger.error(f"Contacts auth failed for {account_email}: {e}")
            return None

    def get_all_contacts(self, accounts: List[str] = None) -> List[Contact]:
        """
        Fetch all contacts from Google Contacts.

        Returns:
            List of Contact objects
        """
        if not GOOGLE_AVAILABLE:
            return []

        accounts = accounts or self.accounts
        contacts = []
        seen_emails = set()

        for account in accounts:
            service = self._get_service(account)
            if not service:
                continue

            try:
                page_token = None
                while True:
                    result = service.people().connections().list(
                        resourceName='people/me',
                        pageSize=1000,
                        personFields='names,emailAddresses,phoneNumbers,organizations,biographies',
                        pageToken=page_token,
                    ).execute()

                    for person in result.get('connections', []):
                        # Extract name
                        names = person.get('names', [])
                        name_data = names[0] if names else {}

                        display_name = name_data.get('displayName', '')
                        first_name = name_data.get('givenName', '')
                        last_name = name_data.get('familyName', '')

                        # Extract email
                        emails = person.get('emailAddresses', [])
                        email = emails[0].get('value') if emails else None

                        # Skip duplicates by email
                        if email and email.lower() in seen_emails:
                            continue
                        if email:
                            seen_emails.add(email.lower())

                        # Extract phone
                        phones = person.get('phoneNumbers', [])
                        phone = phones[0].get('value') if phones else None

                        # Extract organization
                        orgs = person.get('organizations', [])
                        org_data = orgs[0] if orgs else {}
                        company = org_data.get('name', '')
                        job_title = org_data.get('title', '')

                        contact = Contact(
                            name=display_name,
                            first_name=first_name,
                            last_name=last_name,
                            email=email,
                            phone=phone,
                            company=company,
                            job_title=job_title,
                        )
                        contacts.append(contact)

                    page_token = result.get('nextPageToken')
                    if not page_token:
                        break

            except Exception as e:
                logger.error(f"Contacts API error for {account}: {e}")

        return contacts

    def search_contact(self, query: str, accounts: List[str] = None) -> Optional[Contact]:
        """Search for a contact by name or email."""
        if not GOOGLE_AVAILABLE:
            return None

        accounts = accounts or self.accounts

        for account in accounts:
            service = self._get_service(account)
            if not service:
                continue

            try:
                result = service.people().searchContacts(
                    query=query,
                    readMask='names,emailAddresses,phoneNumbers,organizations',
                    pageSize=5,
                ).execute()

                for person in result.get('results', []):
                    person_data = person.get('person', {})
                    names = person_data.get('names', [])
                    if names:
                        name_data = names[0]
                        orgs = person_data.get('organizations', [])
                        org_data = orgs[0] if orgs else {}
                        emails = person_data.get('emailAddresses', [])

                        return Contact(
                            name=name_data.get('displayName', ''),
                            first_name=name_data.get('givenName', ''),
                            last_name=name_data.get('familyName', ''),
                            email=emails[0].get('value') if emails else None,
                            company=org_data.get('name', ''),
                            job_title=org_data.get('title', ''),
                        )

            except Exception as e:
                logger.debug(f"Contact search error for {account}: {e}")

        return None


# =============================================================================
# Merchant Intelligence
# =============================================================================

MERCHANT_INTELLIGENCE = {
    # Member clubs & hospitality
    'soho house': {
        'description': 'Soho House Nashville - exclusive members club',
        'typical_use': 'business development, entertainment meetings, industry networking',
        'tax_category': 'Meals & Entertainment',
    },
    'sh nashville': {
        'description': 'Soho House Nashville - exclusive members club',
        'typical_use': 'business development, entertainment meetings, industry networking',
        'tax_category': 'Meals & Entertainment',
    },

    # AI & Software
    'anthropic': {
        'description': 'Anthropic/Claude AI subscription',
        'typical_use': 'AI assistant for writing, research, coding, business strategy',
        'tax_category': 'Software & Subscriptions',
    },
    'claude': {
        'description': 'Claude AI subscription',
        'typical_use': 'AI assistant for business productivity',
        'tax_category': 'Software & Subscriptions',
    },
    'openai': {
        'description': 'OpenAI/ChatGPT subscription',
        'typical_use': 'AI platform for content creation and analysis',
        'tax_category': 'Software & Subscriptions',
    },
    'midjourney': {
        'description': 'Midjourney AI image generation',
        'typical_use': 'creative visual content for projects',
        'tax_category': 'Software & Subscriptions',
    },
    'cursor': {
        'description': 'Cursor AI code editor',
        'typical_use': 'software development for business applications',
        'tax_category': 'Software & Subscriptions',
    },

    # Travel
    'uber': {
        'description': 'Uber rideshare',
        'typical_use': 'local transportation to meetings/events',
        'tax_category': 'Travel - Local Transportation',
    },
    'lyft': {
        'description': 'Lyft rideshare',
        'typical_use': 'local transportation to meetings/events',
        'tax_category': 'Travel - Local Transportation',
    },
    'southwest': {
        'description': 'Southwest Airlines',
        'typical_use': 'business travel for meetings/events',
        'tax_category': 'Travel - Airfare',
    },
    'delta': {
        'description': 'Delta Airlines',
        'typical_use': 'business travel for meetings/events',
        'tax_category': 'Travel - Airfare',
    },
    'clear': {
        'description': 'CLEAR airport security',
        'typical_use': 'expedited airport security for frequent business travel',
        'tax_category': 'Travel - Transportation',
    },

    # Parking
    'metropolis': {
        'description': 'Metropolis parking',
        'typical_use': 'parking for business meetings',
        'tax_category': 'Travel - Parking',
    },
    'pmc': {
        'description': 'PMC parking',
        'typical_use': 'parking for business meetings',
        'tax_category': 'Travel - Parking',
    },
    'park happy': {
        'description': 'Park Happy parking',
        'typical_use': 'parking for business meetings in Nashville',
        'tax_category': 'Travel - Parking',
    },

    # Streaming/Entertainment Research
    'spotify': {
        'description': 'Spotify music streaming',
        'typical_use': 'music streaming for industry research and work',
        'tax_category': 'Software & Subscriptions',
    },
    'imdbpro': {
        'description': 'IMDbPro entertainment database',
        'typical_use': 'entertainment industry research',
        'tax_category': 'Software & Subscriptions',
    },

    # Productivity
    'expensify': {
        'description': 'Expensify expense management',
        'typical_use': 'expense tracking and reporting',
        'tax_category': 'Software & Subscriptions',
    },
    'notion': {
        'description': 'Notion workspace',
        'typical_use': 'project management and documentation',
        'tax_category': 'Software & Subscriptions',
    },
}


def get_merchant_intelligence(merchant: str) -> Dict[str, str]:
    """Get intelligence about a merchant."""
    merchant_lower = merchant.lower()

    for key, info in MERCHANT_INTELLIGENCE.items():
        if key in merchant_lower:
            return info

    return {}


# =============================================================================
# LLM Prompt Templates
# =============================================================================

SYSTEM_PROMPT = """You are an expense report assistant specializing in creating detailed, audit-ready expense descriptions.

Your role is to generate professional expense notes that:
1. Clearly state the business purpose
2. Name attendees with their roles/companies when known
3. Reference specific projects, events, or initiatives when applicable
4. Are suitable for IRS documentation and expense audits
5. Are factual - only include information that can be verified from the provided data

You work for Brian Kaplan, who runs:
- Business: A production company in partnership with Tim McGraw
- Secondary (MCR): A PRCA rodeo event in Nashville

IMPORTANT GUIDELINES:
- Be SPECIFIC - generic phrases like "business meeting" or "client dinner" are NOT acceptable
- For meals: Always specify WHO was there and WHAT was discussed if known
- For travel: Specify WHERE and WHY
- For subscriptions: Explain HOW they're used for business
- Keep notes to 1-2 sentences maximum
- Never make up information not provided in the context"""


NOTE_GENERATION_PROMPT = """Generate a professional expense description for the following transaction:

## Transaction Details
- Merchant: {merchant}
- Amount: ${amount:.2f}
- Date: {date}
- Business Type: {business_type}
- Category: {category}

## Receipt Data
{receipt_details}

## Calendar Context
{calendar_context}

## Known Attendees
{attendees}

## Merchant Intelligence
{merchant_intel}

## Previous Similar Notes
{previous_notes}

---

Generate the expense note following this exact format:

DESCRIPTION: [1-2 sentence description that would satisfy an auditor asking "What was this for?"]
ATTENDEES: [List of people with roles, or "N/A" if none]
BUSINESS_PURPOSE: [Brief purpose - e.g., "Client development", "Industry research", "Travel"]
TAX_CATEGORY: [Meals & Entertainment / Travel / Software & Subscriptions / etc.]

Remember: Be specific and factual. Do NOT use vague phrases like "business expense" or "client meeting"."""


# =============================================================================
# Learning System
# =============================================================================

class NoteLearningSystem:
    """
    Learns from user corrections to improve future note generation.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(__file__).parent.parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.corrections_file = self.data_dir / "note_corrections.json"
        self.patterns_file = self.data_dir / "note_patterns.json"

        self.corrections: List[Dict] = []
        self.patterns: Dict[str, List[str]] = {}

        self._load()

    def _load(self):
        """Load learned data from disk."""
        if self.corrections_file.exists():
            try:
                with open(self.corrections_file, 'r') as f:
                    self.corrections = json.load(f)
            except:
                self.corrections = []

        if self.patterns_file.exists():
            try:
                with open(self.patterns_file, 'r') as f:
                    self.patterns = json.load(f)
            except:
                self.patterns = {}

    def _save(self):
        """Save learned data to disk."""
        with open(self.corrections_file, 'w') as f:
            json.dump(self.corrections, f, indent=2)

        with open(self.patterns_file, 'w') as f:
            json.dump(self.patterns, f, indent=2)

    def learn_correction(
        self,
        merchant: str,
        original_note: str,
        corrected_note: str,
        context: Dict = None
    ):
        """Learn from a user correction."""
        correction = {
            'merchant': merchant.lower(),
            'original': original_note,
            'corrected': corrected_note,
            'context': context or {},
            'timestamp': datetime.now().isoformat(),
        }
        self.corrections.append(correction)

        # Update patterns for this merchant
        merchant_key = merchant.lower()
        if merchant_key not in self.patterns:
            self.patterns[merchant_key] = []
        self.patterns[merchant_key].append(corrected_note)

        # Keep only last 10 patterns per merchant
        self.patterns[merchant_key] = self.patterns[merchant_key][-10:]

        self._save()

    def get_previous_notes(self, merchant: str, limit: int = 3) -> List[str]:
        """Get previous notes for a merchant."""
        merchant_key = merchant.lower()

        for key in self.patterns:
            if key in merchant_key or merchant_key in key:
                return self.patterns[key][-limit:]

        return []

    def get_typical_purpose(self, merchant: str) -> Optional[str]:
        """Infer typical purpose from previous notes."""
        notes = self.get_previous_notes(merchant)
        if not notes:
            return None

        # Simple: return most recent pattern
        return notes[-1]


# =============================================================================
# Smart Notes Service
# =============================================================================

class SmartNotesService:
    """
    Main service for generating intelligent expense notes.

    Combines:
    - Transaction data
    - Receipt OCR data
    - Calendar events (±2 hours of transaction)
    - Contact information
    - Historical patterns
    - AI synthesis (Claude)
    """

    def __init__(
        self,
        credentials_dir: str = 'credentials',
        cache_ttl: int = 3600,
    ):
        # Initialize components
        self.calendar_client = GoogleCalendarClient(credentials_dir)
        self.contacts_client = GoogleContactsClient(credentials_dir)
        self.cache = ContextCache(ttl_seconds=cache_ttl)
        self.learning = NoteLearningSystem()

        # Claude client
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        self.claude_client = Anthropic(api_key=self.anthropic_key) if ANTHROPIC_AVAILABLE and self.anthropic_key else None
        self.model = "claude-sonnet-4-20250514"

        # Load contacts cache
        self._load_contacts_cache()

    def _load_contacts_cache(self):
        """Load all contacts into cache."""
        try:
            self.cache.load_from_disk()

            if not self.cache._contacts_loaded:
                contacts = self.contacts_client.get_all_contacts()
                self.cache.load_all_contacts(contacts)
                self.cache.save_to_disk()
                logger.info(f"Loaded {len(contacts)} contacts into cache")

        except Exception as e:
            logger.warning(f"Failed to load contacts cache: {e}")

    async def gather_context(
        self,
        merchant: str,
        amount: Decimal,
        date: datetime,
        receipt: Optional[ReceiptData] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        business_type: Optional[str] = None,
    ) -> TransactionContext:
        """
        Gather all available context for note generation.
        Target: < 2 seconds total.
        """
        context = TransactionContext(
            merchant=merchant,
            amount=amount,
            date=date,
            receipt=receipt,
            description=description,
            category=category,
            business_type=business_type,
        )

        # Get merchant intelligence
        intel = get_merchant_intelligence(merchant)
        if intel:
            context.merchant_hint = intel.get('typical_use', '')

        # Get calendar events (check cache first)
        cached_events = self.cache.get_calendar_events(date, 'all')
        if cached_events is not None:
            context.calendar_events = cached_events
        else:
            events = self.calendar_client.get_events_around_time(date, hours_before=2, hours_after=2)
            context.calendar_events = events
            self.cache.set_calendar_events(date, 'all', events)

        # Find closest event
        if context.calendar_events:
            context.closest_event = context.calendar_events[0]  # Already sorted by proximity

        # Enrich attendees from calendar events
        attendee_names = set()
        for event in context.calendar_events:
            attendee_names.update(event.attendees)

        # Look up contacts
        for name in attendee_names:
            # Check cache first
            contact = self.cache.get_contact(name)
            if not contact:
                # Search in contacts
                matches = self.cache.search_contacts(name)
                if matches:
                    contact = matches[0]
                else:
                    # Try Google search
                    contact = self.contacts_client.search_contact(name)

                if contact:
                    self.cache.set_contact(name, contact)

            if contact:
                context.attendees.append(contact)
            else:
                # Create basic contact
                context.attendees.append(Contact(name=name))

        # Get historical patterns
        context.previous_notes = self.learning.get_previous_notes(merchant)
        context.typical_purpose = self.learning.get_typical_purpose(merchant)

        return context

    def _build_prompt_context(self, context: TransactionContext) -> Dict[str, str]:
        """Build prompt variables from context."""
        # Receipt details
        receipt_details = "No receipt data available."
        if context.receipt:
            parts = []
            if context.receipt.items:
                parts.append(f"Items: {', '.join(str(i) for i in context.receipt.items[:5])}")
            if context.receipt.subtotal:
                parts.append(f"Subtotal: ${context.receipt.subtotal}")
            if context.receipt.tax:
                parts.append(f"Tax: ${context.receipt.tax}")
            if context.receipt.tip:
                parts.append(f"Tip: ${context.receipt.tip}")
            if context.receipt.server_name:
                parts.append(f"Server: {context.receipt.server_name}")
            if context.receipt.address:
                parts.append(f"Location: {context.receipt.address}")
            if parts:
                receipt_details = "\n".join(parts)

        # Calendar context
        calendar_context = "No calendar events found near this time."
        if context.calendar_events:
            event_strs = []
            for e in context.calendar_events[:3]:
                time_str = e.start_time.strftime('%I:%M %p') if e.start_time else 'Unknown time'
                attendees_str = f" with {', '.join(e.attendees)}" if e.attendees else ""
                event_strs.append(f"- {time_str}: {e.title}{attendees_str}")
            calendar_context = "\n".join(event_strs)

        # Attendees
        attendees_str = "No known attendees."
        if context.attendees:
            attendee_strs = [a.get_display_name() for a in context.attendees]
            attendees_str = "\n".join(f"- {a}" for a in attendee_strs)

        # Merchant intelligence
        merchant_intel = "No merchant intelligence available."
        if context.merchant_hint:
            intel = get_merchant_intelligence(context.merchant)
            if intel:
                merchant_intel = f"Description: {intel.get('description', '')}\nTypical use: {intel.get('typical_use', '')}"

        # Previous notes
        previous_notes = "No previous notes for this merchant."
        if context.previous_notes:
            previous_notes = "\n".join(f"- {n}" for n in context.previous_notes[-3:])

        return {
            'merchant': context.merchant,
            'amount': float(context.amount),
            'date': context.date.strftime('%Y-%m-%d') if context.date else 'Unknown',
            'business_type': context.business_type or 'Not specified',
            'category': context.category or 'Not specified',
            'receipt_details': receipt_details,
            'calendar_context': calendar_context,
            'attendees': attendees_str,
            'merchant_intel': merchant_intel,
            'previous_notes': previous_notes,
        }

    async def generate_note(
        self,
        merchant: str,
        amount: float,
        date: datetime,
        receipt: Optional[ReceiptData] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        business_type: Optional[str] = None,
    ) -> NoteResult:
        """
        Generate a smart note for a transaction.

        Args:
            merchant: Merchant name
            amount: Transaction amount
            date: Transaction date/time
            receipt: Optional OCR receipt data
            description: Optional bank description
            category: Optional category
            business_type: Business, MCR, Personal, etc.

        Returns:
            NoteResult with generated note and metadata
        """
        result = NoteResult(generated_at=datetime.now())

        # Gather context
        context = await self.gather_context(
            merchant=merchant,
            amount=Decimal(str(amount)),
            date=date,
            receipt=receipt,
            description=description,
            category=category,
            business_type=business_type,
        )

        # Track data sources
        if context.calendar_events:
            result.data_sources.append('calendar')
        if context.attendees:
            result.data_sources.append('contacts')
        if context.receipt:
            result.data_sources.append('receipt')
        if context.merchant_hint:
            result.data_sources.append('merchant_intelligence')
        if context.previous_notes:
            result.data_sources.append('historical_patterns')

        # Calculate confidence
        result.confidence = min(0.95, 0.5 + (len(result.data_sources) * 0.15))

        # Generate note with Claude
        if self.claude_client:
            try:
                prompt_vars = self._build_prompt_context(context)
                user_prompt = NOTE_GENERATION_PROMPT.format(**prompt_vars)

                response = self.claude_client.messages.create(
                    model=self.model,
                    max_tokens=500,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}]
                )

                response_text = response.content[0].text

                # Parse response
                parsed = self._parse_llm_response(response_text)
                result.note = parsed.get('description', '')
                result.business_purpose = parsed.get('business_purpose', '')
                result.tax_category = parsed.get('tax_category', '')

                # Parse attendees from response
                attendees_str = parsed.get('attendees', 'N/A')
                if attendees_str and attendees_str != 'N/A':
                    result.attendee_count = len([a.strip() for a in attendees_str.split(',') if a.strip()])

            except Exception as e:
                logger.error(f"Claude API error: {e}")
                result.note = self._generate_fallback_note(context)
        else:
            result.note = self._generate_fallback_note(context)

        # Set attendees
        result.attendees = context.attendees
        result.attendee_count = max(result.attendee_count, len(context.attendees))
        result.calendar_event = context.closest_event

        # Determine if needs review
        result.needs_review = result.confidence < 0.7 or not result.note

        return result

    def _parse_llm_response(self, response: str) -> Dict[str, str]:
        """Parse the structured LLM response."""
        result = {}

        # Extract DESCRIPTION
        desc_match = re.search(r'DESCRIPTION:\s*(.+?)(?=\n[A-Z]+:|$)', response, re.DOTALL)
        if desc_match:
            result['description'] = desc_match.group(1).strip()

        # Extract ATTENDEES
        att_match = re.search(r'ATTENDEES:\s*(.+?)(?=\n[A-Z]+:|$)', response, re.DOTALL)
        if att_match:
            result['attendees'] = att_match.group(1).strip()

        # Extract BUSINESS_PURPOSE
        purpose_match = re.search(r'BUSINESS_PURPOSE:\s*(.+?)(?=\n[A-Z]+:|$)', response, re.DOTALL)
        if purpose_match:
            result['business_purpose'] = purpose_match.group(1).strip()

        # Extract TAX_CATEGORY
        tax_match = re.search(r'TAX_CATEGORY:\s*(.+?)(?=\n|$)', response, re.DOTALL)
        if tax_match:
            result['tax_category'] = tax_match.group(1).strip()

        return result

    def _generate_fallback_note(self, context: TransactionContext) -> str:
        """Generate a basic note without AI."""
        parts = []

        # Start with merchant and business type
        if context.merchant_hint:
            parts.append(context.merchant_hint)
        else:
            parts.append(context.merchant)

        # Add attendees if known
        if context.attendees:
            others = [a.get_display_name() for a in context.attendees[:3]]
            if others:
                parts.append(f"with {', '.join(others)}")

        # Add event context
        if context.closest_event:
            parts.append(f"for {context.closest_event.title}")

        return ' '.join(parts)

    async def generate_batch(
        self,
        transactions: List[Dict[str, Any]],
        progress_callback=None,
    ) -> List[NoteResult]:
        """
        Generate notes for multiple transactions.

        Args:
            transactions: List of transaction dicts with keys:
                - merchant / Chase Description
                - amount / Chase Amount
                - date / Chase Date / transaction_date
                - category / Chase Category
                - business_type / Business Type
            progress_callback: Optional callback(current, total, result)

        Returns:
            List of NoteResult objects
        """
        results = []
        total = len(transactions)

        for i, tx in enumerate(transactions):
            merchant = tx.get('merchant') or tx.get('Chase Description') or 'Unknown'
            amount = abs(float(tx.get('amount') or tx.get('Chase Amount') or 0))

            date_str = tx.get('date') or tx.get('Chase Date') or tx.get('transaction_date')
            if isinstance(date_str, str):
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y']:
                    try:
                        date = datetime.strptime(date_str, fmt)
                        break
                    except:
                        continue
                else:
                    date = datetime.now()
            else:
                date = date_str or datetime.now()

            category = tx.get('category') or tx.get('Chase Category')
            business_type = tx.get('business_type') or tx.get('Business Type')

            result = await self.generate_note(
                merchant=merchant,
                amount=amount,
                date=date,
                category=category,
                business_type=business_type,
            )
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total, result)

        return results

    def learn_from_edit(
        self,
        merchant: str,
        original_note: str,
        edited_note: str,
        context: Dict = None,
    ):
        """
        Learn from a user's edit to improve future notes.

        Args:
            merchant: Merchant name
            original_note: The AI-generated note
            edited_note: The user's corrected note
            context: Optional additional context
        """
        self.learning.learn_correction(
            merchant=merchant,
            original_note=original_note,
            corrected_note=edited_note,
            context=context,
        )

    async def regenerate_note(
        self,
        merchant: str,
        amount: float,
        date: datetime,
        additional_context: str = "",
        **kwargs,
    ) -> NoteResult:
        """
        Regenerate a note with additional user-provided context.

        Args:
            merchant: Merchant name
            amount: Transaction amount
            date: Transaction date
            additional_context: User-provided context to include
            **kwargs: Additional transaction fields

        Returns:
            New NoteResult
        """
        # Generate with updated context
        result = await self.generate_note(
            merchant=merchant,
            amount=amount,
            date=date,
            **kwargs,
        )

        # If additional context provided, regenerate with it
        if additional_context and self.claude_client:
            try:
                prompt = f"""Based on this expense and additional context, generate a better note:

Merchant: {merchant}
Amount: ${amount:.2f}
Date: {date.strftime('%Y-%m-%d')}

Current Note: {result.note}

Additional Context from User: {additional_context}

Generate an improved DESCRIPTION that incorporates this context. Be specific and factual."""

                response = self.claude_client.messages.create(
                    model=self.model,
                    max_tokens=200,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}]
                )

                result.note = response.content[0].text.strip()
                result.data_sources.append('user_context')
                result.confidence = min(0.95, result.confidence + 0.1)

            except Exception as e:
                logger.error(f"Regeneration error: {e}")

        return result


# =============================================================================
# Convenience Functions
# =============================================================================

# Global service instance
_service: Optional[SmartNotesService] = None


def get_smart_notes_service() -> SmartNotesService:
    """Get or create the SmartNotesService singleton."""
    global _service
    if _service is None:
        _service = SmartNotesService()
    return _service


async def generate_note(
    merchant: str,
    amount: float,
    date: datetime,
    **kwargs,
) -> NoteResult:
    """Convenience function to generate a note."""
    service = get_smart_notes_service()
    return await service.generate_note(merchant, amount, date, **kwargs)


def generate_note_sync(
    merchant: str,
    amount: float,
    date: datetime,
    **kwargs,
) -> NoteResult:
    """Synchronous version of generate_note."""
    return asyncio.run(generate_note(merchant, amount, date, **kwargs))


# =============================================================================
# CLI Test
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Smart Notes Service Test")
    parser.add_argument("--merchant", required=True, help="Merchant name")
    parser.add_argument("--amount", type=float, required=True, help="Amount")
    parser.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    parser.add_argument("--business", default="", help="Business type")
    parser.add_argument("--category", default="", help="Category")
    args = parser.parse_args()

    # Parse date
    try:
        date = datetime.strptime(args.date, '%Y-%m-%d')
    except:
        date = datetime.now()

    print("=" * 80)
    print("SMART NOTES SERVICE TEST")
    print("=" * 80)

    result = generate_note_sync(
        merchant=args.merchant,
        amount=args.amount,
        date=date,
        business_type=args.business,
        category=args.category,
    )

    print(f"\nMerchant: {args.merchant}")
    print(f"Amount: ${args.amount:.2f}")
    print(f"Date: {args.date}")
    print(f"\n{'='*40}")
    print(f"Generated Note: {result.note}")
    print(f"Business Purpose: {result.business_purpose}")
    print(f"Tax Category: {result.tax_category}")
    print(f"Attendees: {', '.join(a.get_display_name() for a in result.attendees) or 'None'}")
    print(f"Attendee Count: {result.attendee_count}")
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Data Sources: {', '.join(result.data_sources) or 'None'}")
    print(f"Needs Review: {result.needs_review}")
    print("=" * 80)
