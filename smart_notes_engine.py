#!/usr/bin/env python3
"""
Smart Notes Engine - Enhanced AI Note Generation
Combines Calendar, iMessage, and Contacts data for rich expense notes

Features:
- Calendar events lookup (who was Brian meeting with on this date?)
- iMessage conversations (who was he texting about meetings/lunch?)
- Contacts database enrichment (add titles, companies, relationships)
- Merchant intelligence (what is this place known for?)
"""

import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")

# MySQL connection for contacts - use return_db_connection to prevent pool leaks
try:
    from db_mysql import get_db_connection, return_db_connection
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    get_db_connection = None
    return_db_connection = None

# Load OpenAI for note generation
try:
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and api_key.startswith("sk-"):
        OPENAI_AVAILABLE = True
        client = OpenAI(api_key=api_key)
    else:
        OPENAI_AVAILABLE = False
        client = None
except:
    OPENAI_AVAILABLE = False
    client = None

# Load Gemini as fallback
try:
    from gemini_utils import generate_content_with_fallback
    GEMINI_AVAILABLE = True
except:
    GEMINI_AVAILABLE = False
    generate_content_with_fallback = None

# Load calendar service
try:
    from calendar_service import get_events_around_date
    CALENDAR_AVAILABLE = True
except:
    CALENDAR_AVAILABLE = False
    get_events_around_date = None


# =============================================================================
# CONTACTS DATABASE - MySQL atlas_contacts table
# =============================================================================

class ContactsDatabase:
    """Rich contacts database from MySQL atlas_contacts table with search capabilities"""

    def __init__(self):
        self.contacts = []
        self.by_name = {}
        self.by_company = {}
        self._loaded = False
        self._load_contacts()

    def _load_contacts(self):
        """Load contacts from MySQL atlas_contacts table"""
        if not MYSQL_AVAILABLE or not get_db_connection:
            print("Warning: MySQL not available for contacts database")
            return

        conn = None
        try:
            conn = get_db_connection()
            if not conn:
                print("Warning: Could not get database connection for contacts")
                return

            cursor = conn.cursor()

            # Query atlas_contacts table
            cursor.execute("""
                SELECT id, name, first_name, last_name, title, company,
                       category, priority, notes, ai_description
                FROM atlas_contacts
                WHERE name IS NOT NULL AND name != ''
            """)

            rows = cursor.fetchall()

            for row in rows:
                contact = {
                    'id': row.get('id'),
                    'name': row.get('name', '') or '',
                    'first_name': row.get('first_name', '') or '',
                    'last_name': row.get('last_name', '') or '',
                    'title': row.get('title', '') or '',
                    'company': row.get('company', '') or '',
                    'category': row.get('category', '') or '',
                    'priority': row.get('priority', '') or '',
                    'notes': row.get('notes', '') or '',
                    'ai_description': row.get('ai_description', '') or '',
                }
                self.contacts.append(contact)

                # Index by name (lowercase)
                name_lower = contact['name'].lower()
                if name_lower:
                    self.by_name[name_lower] = contact

                # Also index by first name
                first_lower = contact['first_name'].lower() if contact['first_name'] else ''
                if first_lower and first_lower not in self.by_name:
                    self.by_name[first_lower] = contact

                # Index by company
                company = contact['company'].strip()
                if company:
                    company_lower = company.lower()
                    if company_lower not in self.by_company:
                        self.by_company[company_lower] = []
                    self.by_company[company_lower].append(contact)

            cursor.close()
            self._loaded = True
            print(f"Loaded {len(self.contacts)} contacts from MySQL atlas_contacts")

        except Exception as e:
            print(f"Error loading contacts from MySQL: {e}")
        finally:
            # CRITICAL: Always return connection to pool, never call conn.close() directly
            if conn and return_db_connection:
                try:
                    return_db_connection(conn)
                except Exception as e:
                    print(f"Error returning connection to pool: {e}")

    def search_by_name(self, name: str) -> Optional[Dict]:
        """Find contact by full or partial name"""
        if not name:
            return None

        name_lower = name.lower().strip()

        # Exact match
        if name_lower in self.by_name:
            return self.by_name[name_lower]

        # Partial match
        for key, contact in self.by_name.items():
            if name_lower in key or key in name_lower:
                return contact

        return None

    def search_by_company(self, company: str) -> List[Dict]:
        """Find contacts by company"""
        if not company:
            return []

        company_lower = company.lower().strip()

        if company_lower in self.by_company:
            return self.by_company[company_lower]

        # Partial match
        results = []
        for key, contacts in self.by_company.items():
            if company_lower in key or key in company_lower:
                results.extend(contacts)

        return results

    def enrich_name(self, name: str) -> str:
        """Get enriched name with title/company if found"""
        contact = self.search_by_name(name)
        if contact:
            parts = [contact['name']]
            if contact['title']:
                parts.append(f"({contact['title'][:50]})")
            elif contact['company']:
                parts.append(f"({contact['company']})")
            return ' '.join(parts)
        return name


# Global contacts instance
_contacts_db = None

def get_contacts_db() -> ContactsDatabase:
    """Get or create contacts database singleton"""
    global _contacts_db
    if _contacts_db is None:
        _contacts_db = ContactsDatabase()
    return _contacts_db


# =============================================================================
# IMESSAGE CONTEXT LOOKUP
# =============================================================================

def get_imessage_context(date_str: str, merchant: str = "") -> Dict:
    """
    Get iMessage context for a transaction date.
    Looks for:
    - Who was Brian texting on this date?
    - Any mentions of lunch, dinner, meeting, coffee?
    - Any mentions of the merchant name?

    Returns dict with 'people' list and 'relevant_messages' list
    """
    result = {
        'people': [],
        'relevant_messages': [],
        'meeting_hints': []
    }

    if not os.path.exists(IMESSAGE_DB):
        return result

    try:
        # Parse date
        if isinstance(date_str, str):
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y']:
                try:
                    tx_date = datetime.strptime(date_str, fmt)
                    break
                except:
                    continue
            else:
                return result
        else:
            tx_date = date_str

        # Calculate date range (same day only for messages)
        start_date = tx_date.replace(hour=0, minute=0, second=0)
        end_date = tx_date.replace(hour=23, minute=59, second=59)

        # Convert to Mac cocoa time (nanoseconds since 2001-01-01)
        cocoa_epoch = datetime(2001, 1, 1)
        start_cocoa = int((start_date - cocoa_epoch).total_seconds() * 1_000_000_000)
        end_cocoa = int((end_date - cocoa_epoch).total_seconds() * 1_000_000_000)

        # Connect to iMessage database (read-only)
        conn = sqlite3.connect(f'file:{IMESSAGE_DB}?mode=ro', uri=True)
        cursor = conn.cursor()

        # Query for messages on this date
        query = """
            SELECT
                message.text,
                message.is_from_me,
                handle.id as sender,
                message.date
            FROM message
            LEFT JOIN handle ON message.handle_id = handle.ROWID
            WHERE message.text IS NOT NULL
                AND message.date >= ?
                AND message.date <= ?
            ORDER BY message.date
            LIMIT 200
        """

        cursor.execute(query, (start_cocoa, end_cocoa))

        # Keywords that suggest meetings/meals
        meeting_keywords = [
            'lunch', 'dinner', 'breakfast', 'coffee', 'meeting',
            'drinks', 'meet', 'see you', 'joining', 'reservation',
            'table for', 'soho', 'restaurant', 'headed to', 'on my way'
        ]

        merchant_lower = merchant.lower() if merchant else ""
        people_seen = set()

        for row in cursor.fetchall():
            text, is_from_me, sender, msg_date = row

            if not text:
                continue

            text_lower = text.lower()

            # Track unique conversation partners
            if sender and sender not in people_seen:
                people_seen.add(sender)

            # Check for meeting-related keywords
            for kw in meeting_keywords:
                if kw in text_lower:
                    result['relevant_messages'].append({
                        'text': text[:150],
                        'sender': sender or 'Me',
                        'is_from_me': bool(is_from_me),
                        'keyword': kw
                    })
                    result['meeting_hints'].append(kw)
                    break

            # Check for merchant mention
            if merchant_lower and merchant_lower in text_lower:
                result['relevant_messages'].append({
                    'text': text[:150],
                    'sender': sender or 'Me',
                    'is_from_me': bool(is_from_me),
                    'keyword': 'merchant'
                })

        conn.close()

        result['people'] = list(people_seen)

    except Exception as e:
        print(f"Error querying iMessage: {e}")

    return result


# =============================================================================
# CALENDAR CONTEXT LOOKUP
# =============================================================================

# Keywords that indicate personal/non-business events to exclude from expense context
PERSONAL_EVENT_KEYWORDS = [
    'birthday', 'bday', 'b-day', "b'day",
    'anniversary',
    'dentist', 'doctor', 'appointment', 'checkup', 'physical',
    'school', 'pickup', 'drop off', 'dropoff', 'carpool',
    'recital', 'game', 'practice', 'soccer', 'basketball', 'football', 'baseball',
    'vacation', 'holiday', 'pto', 'day off',
    'haircut', 'salon', 'spa',
]


def is_business_relevant_event(event: dict) -> bool:
    """
    Check if a calendar event is business-relevant for expense categorization.
    Filters out birthdays, personal appointments, kids' events, etc.
    """
    title = (event.get('title') or '').lower()
    description = (event.get('description') or '').lower()

    # Check title and description for personal keywords
    combined_text = f"{title} {description}"

    for keyword in PERSONAL_EVENT_KEYWORDS:
        if keyword in combined_text:
            return False

    return True


def get_calendar_context(date_str: str) -> Dict:
    """
    Get calendar events for a transaction date.
    Automatically filters out personal events (birthdays, etc.) that shouldn't
    be used for business expense categorization.

    Returns dict with 'events' list and 'attendees' set
    """
    result = {
        'events': [],
        'attendees': set(),
        'event_titles': []
    }

    if not CALENDAR_AVAILABLE or not get_events_around_date:
        return result

    try:
        events = get_events_around_date(date_str, days_before=0, days_after=0)

        # Filter out personal events (birthdays, etc.) - these should not be used for business expense notes
        events = [e for e in events if is_business_relevant_event(e)]

        for event in events:
            title = event.get('title', '')
            location = event.get('location', '')
            description = event.get('description', '')

            result['events'].append(event)
            result['event_titles'].append(title)

            # Extract attendee names from title/description
            # Handle patterns like:
            # - "Dinner Meeting with Bill Stapleton, Scott Simon, and Kelly Clegg"
            # - "Lunch with John Smith"
            # - "Coffee w/ Jane Doe"
            # - "Brian Kaplan + Mark Johnson"

            text_to_search = f"{title} {description}"

            # First, try to extract names after "with" (most common pattern)
            with_match = re.search(r'(?:with|w/)\s+(.+?)(?:\s*[-@|]|$)', text_to_search, re.IGNORECASE)
            if with_match:
                names_text = with_match.group(1)
                # Split by comma, "and", "&"
                names = re.split(r'\s*,\s*|\s+and\s+|\s*&\s*', names_text)
                for name in names:
                    name = name.strip()
                    # Check if it looks like a name (First Last or First)
                    if name and re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$', name):
                        if name not in ['Meeting', 'Lunch', 'Dinner', 'Call', 'Coffee', 'Breakfast', 'Team']:
                            result['attendees'].add(name)

            # Also check for "Name + Name" pattern (common in calendar)
            plus_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*\+\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', text_to_search)
            if plus_match:
                for name in plus_match.groups():
                    if name and name not in ['Meeting', 'Lunch', 'Dinner']:
                        result['attendees'].add(name.strip())

            # Check for "FirstName LastName - Meeting" pattern
            name_dash_match = re.search(r'^([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-:]', title)
            if name_dash_match:
                name = name_dash_match.group(1).strip()
                if name:
                    result['attendees'].add(name)

        result['attendees'] = list(result['attendees'])

    except Exception as e:
        print(f"Error getting calendar context: {e}")

    return result


# =============================================================================
# MERCHANT INTELLIGENCE
# =============================================================================

MERCHANT_HINTS = {
    # Member clubs & hospitality
    'soho house': 'Soho House Nashville - exclusive members club; business development, entertainment meetings, and industry networking',
    'sh nashville': 'Soho House Nashville - exclusive members club; business development, entertainment meetings, and industry networking',

    # Travel services
    'clear': 'CLEAR - airport security expediting service for frequent business travelers',
    'tsa precheck': 'TSA PreCheck - trusted traveler program for efficient airport security',
    'uber': 'Uber - rideshare for local transportation to meetings/events',
    'lyft': 'Lyft - rideshare for local transportation to meetings/events',

    # AI & Software
    'anthropic': 'Anthropic/Claude - AI assistant for writing, research, coding, and business strategy',
    'openai': 'OpenAI/ChatGPT - AI platform for content creation and analysis',
    'claude': 'Claude AI - AI assistant for business productivity',
    'runway': 'Runway ML - AI video generation for creative content',
    'midjourney': 'Midjourney - AI image generation for creative projects',
    'cursor': 'Cursor - AI-powered code editor for development',

    # Subscriptions
    'apple one': 'Apple One - premium bundle including iCloud, Music, TV+ for business productivity',
    'spotify': 'Spotify - music streaming for work and entertainment industry research',
    'netflix': 'Netflix - streaming for entertainment industry research',
    'imdbpro': 'IMDbPro - entertainment industry database and research tool',

    # Professional services
    'expensify': 'Expensify - expense management software',

    # Parking
    'park happy': 'Park Happy - parking for business meetings in Nashville',
    'pmc': 'PMC Parking - parking garage for meetings',
    'metropolis': 'Metropolis parking - parking for business meetings',
}

def get_merchant_intelligence(merchant: str) -> str:
    """Get intelligence about a merchant"""
    merchant_lower = merchant.lower()

    for key, hint in MERCHANT_HINTS.items():
        if key in merchant_lower:
            return hint

    return ""


# =============================================================================
# SMART NOTE GENERATION
# =============================================================================

def generate_smart_note(
    merchant: str,
    amount: float,
    date: str,
    category: str = "",
    business_type: str = ""
) -> Dict[str, Any]:
    """
    Generate a smart, context-aware note for a transaction.

    Combines:
    1. Calendar events on the date
    2. iMessage conversations on the date
    3. Contact database enrichment
    4. Merchant intelligence
    5. AI synthesis

    Returns:
    {
        'note': str,  # The generated note
        'attendees': List[str],  # Likely attendees
        'calendar_events': List[str],  # Relevant calendar events
        'confidence': str,  # high/medium/low
        'data_sources': List[str]  # What data was used
    }
    """
    result = {
        'note': '',
        'attendees': ['Brian Kaplan'],
        'calendar_events': [],
        'confidence': 'low',
        'data_sources': []
    }

    # 1. Get merchant intelligence
    merchant_hint = get_merchant_intelligence(merchant)
    if merchant_hint:
        result['data_sources'].append('merchant_intelligence')

    # 2. Get calendar context
    calendar_ctx = get_calendar_context(date)
    if calendar_ctx['events']:
        result['data_sources'].append('calendar')
        result['calendar_events'] = calendar_ctx['event_titles']
        for attendee in calendar_ctx['attendees']:
            if attendee not in result['attendees']:
                result['attendees'].append(attendee)

    # 3. Get iMessage context (only runs locally with macOS access)
    imessage_ctx = get_imessage_context(date, merchant)
    if imessage_ctx['relevant_messages']:
        result['data_sources'].append('imessage')

    # 4. Enrich attendee names with contact database
    contacts_db = get_contacts_db()
    enriched_attendees = []
    for attendee in result['attendees']:
        enriched = contacts_db.enrich_name(attendee)
        enriched_attendees.append(enriched)

    # 5. Determine confidence
    if len(result['data_sources']) >= 2:
        result['confidence'] = 'high'
    elif len(result['data_sources']) == 1:
        result['confidence'] = 'medium'
    else:
        result['confidence'] = 'low'

    # 6. Generate note with AI (try OpenAI first, then Gemini)
    prompt = _build_note_prompt(
        merchant=merchant,
        amount=amount,
        date=date,
        category=category,
        business_type=business_type,
        merchant_hint=merchant_hint,
        calendar_events=calendar_ctx['event_titles'],
        attendees=enriched_attendees,
        imessage_hints=imessage_ctx.get('meeting_hints', []),
        relevant_messages=imessage_ctx.get('relevant_messages', [])[:3]
    )

    ai_note_generated = False

    # Try OpenAI first
    if OPENAI_AVAILABLE and client:
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You write concise, professional expense notes. Be specific and factual."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.5,
            )
            result['note'] = resp.choices[0].message.content.strip()
            ai_note_generated = True
        except Exception as e:
            print(f"OpenAI error: {e}")

    # Try Gemini as fallback
    if not ai_note_generated and GEMINI_AVAILABLE and generate_content_with_fallback:
        try:
            gemini_prompt = f"You write concise, professional expense notes. Be specific and factual.\n\n{prompt}"
            gemini_result = generate_content_with_fallback(gemini_prompt)
            if gemini_result:
                # Clean up the response
                note = gemini_result.strip()
                # Remove any markdown formatting
                if note.startswith('Note:'):
                    note = note[5:].strip()
                result['note'] = note
                ai_note_generated = True
        except Exception as e:
            print(f"Gemini error: {e}")

    # Final fallback
    if not ai_note_generated:
        result['note'] = _generate_fallback_note(
            merchant, amount, date, category,
            merchant_hint, enriched_attendees
        )

    result['attendees'] = enriched_attendees

    return result


def _build_note_prompt(
    merchant: str,
    amount: float,
    date: str,
    category: str,
    business_type: str,
    merchant_hint: str,
    calendar_events: List[str],
    attendees: List[str],
    imessage_hints: List[str],
    relevant_messages: List[Dict]
) -> str:
    """Build the prompt for AI note generation"""

    parts = [
        f"Generate a professional expense note for Brian Kaplan.",
        f"",
        f"Transaction:",
        f"- Merchant: {merchant}",
        f"- Amount: ${amount:.2f}",
        f"- Date: {date}",
        f"- Category: {category or 'Not specified'}",
        f"- Business: {business_type or 'Not specified'}",
    ]

    if merchant_hint:
        parts.append(f"\nMerchant Context: {merchant_hint}")

    if calendar_events:
        parts.append(f"\nCalendar events on this date: {', '.join(calendar_events[:3])}")

    if attendees and len(attendees) > 1:
        parts.append(f"\nLikely attendees: {', '.join(attendees)}")

    if imessage_hints:
        parts.append(f"\niMessage context: Messages mention {', '.join(set(imessage_hints))}")

    if relevant_messages:
        parts.append("\nRelevant messages:")
        for msg in relevant_messages[:2]:
            direction = "Brian said" if msg['is_from_me'] else f"{msg['sender']} said"
            parts.append(f"  - {direction}: \"{msg['text'][:80]}...\"")

    parts.extend([
        "",
        "IMPORTANT: Write a SPECIFIC expense note that would satisfy an IRS auditor asking 'What was this for?'",
        "",
        "REQUIREMENTS:",
        "1. Be SPECIFIC - name people, projects, or events when known",
        "2. For meals: specify WHO was there and WHAT was discussed (artist deals, contracts, etc.)",
        "3. For travel: specify WHERE and WHY (event name, meeting purpose)",
        "4. For subscriptions: specify HOW it's used for business",
        "5. Never use generic phrases like 'business expense' or 'client meeting'",
        "",
        "EXCELLENT NOTES:",
        "- 'Artist development dinner at Soho House with Jason Ross discussing Q4 release strategy for Morgan Wade'",
        "- 'Claude AI subscription - contract analysis, press release drafting, and business correspondence'",
        "- 'Delta flight to Los Angeles for Grammy week artist showcases and label meetings'",
        "- 'Parking at BNA airport during Las Vegas trip for NFR (National Finals Rodeo) production meetings'",
        "- 'Team lunch at 12 South Taproom with Joel Bergvall and Kevin Sabbe - quarterly planning review'",
        "",
        "BAD NOTES (too vague - NEVER write these):",
        "- 'Business dinner' or 'Client meeting'",
        "- 'Software subscription'",
        "- 'Travel expense'",
        "- 'Meal with team'",
        "",
        "Write 1-2 sentences. Be factual and specific:",
    ])

    return "\n".join(parts)


def _generate_fallback_note(
    merchant: str,
    amount: float,
    date: str,
    category: str,
    merchant_hint: str,
    attendees: List[str]
) -> str:
    """Generate a basic note without AI"""
    parts = []

    if merchant_hint:
        # Use the merchant hint as the base
        parts.append(merchant_hint.split(' - ')[0])
    else:
        parts.append(f"{merchant}")

    if category and category.lower() not in ['general', 'shopping']:
        parts.append(f"({category})")

    if len(attendees) > 1:
        others = [a for a in attendees if 'Brian' not in a][:2]
        if others:
            parts.append(f"with {', '.join(others)}")

    return ' '.join(parts)


# =============================================================================
# BATCH PROCESSING
# =============================================================================

def generate_notes_for_transactions(transactions: List[Dict]) -> List[Dict]:
    """
    Generate smart notes for a batch of transactions.

    Args:
        transactions: List of dicts with keys like:
            - Chase Description / merchant
            - Chase Amount / amount
            - Chase Date / transaction_date
            - Chase Category / category
            - Business Type / business_type

    Returns:
        List of dicts with note data
    """
    results = []

    for i, tx in enumerate(transactions):
        print(f"\n[{i+1}/{len(transactions)}] Processing {tx.get('Chase Description', tx.get('merchant', 'Unknown'))}")

        merchant = tx.get('Chase Description') or tx.get('merchant') or 'Unknown'
        amount = abs(float(tx.get('Chase Amount') or tx.get('amount') or 0))
        date = tx.get('Chase Date') or tx.get('transaction_date') or ''
        category = tx.get('Chase Category') or tx.get('category') or ''
        business_type = tx.get('Business Type') or tx.get('business_type') or ''

        note_result = generate_smart_note(
            merchant=merchant,
            amount=amount,
            date=date,
            category=category,
            business_type=business_type
        )

        note_result['transaction_id'] = tx.get('_index') or tx.get('id')
        results.append(note_result)

        print(f"   Note: {note_result['note'][:80]}...")
        print(f"   Confidence: {note_result['confidence']}")
        print(f"   Sources: {', '.join(note_result['data_sources']) or 'none'}")

    return results


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate smart expense notes")
    parser.add_argument("--merchant", required=True, help="Merchant name")
    parser.add_argument("--amount", type=float, required=True, help="Transaction amount")
    parser.add_argument("--date", required=True, help="Transaction date (YYYY-MM-DD)")
    parser.add_argument("--category", default="", help="Transaction category")
    parser.add_argument("--business", default="", help="Business type")
    args = parser.parse_args()

    print("=" * 80)
    print("SMART NOTES ENGINE TEST")
    print("=" * 80)

    result = generate_smart_note(
        merchant=args.merchant,
        amount=args.amount,
        date=args.date,
        category=args.category,
        business_type=args.business
    )

    print(f"\nMerchant: {args.merchant}")
    print(f"Amount: ${args.amount:.2f}")
    print(f"Date: {args.date}")
    print(f"\n{'='*40}")
    print(f"Generated Note: {result['note']}")
    print(f"Attendees: {', '.join(result['attendees'])}")
    print(f"Calendar Events: {', '.join(result['calendar_events']) or 'None found'}")
    print(f"Confidence: {result['confidence']}")
    print(f"Data Sources: {', '.join(result['data_sources']) or 'None'}")
    print("=" * 80)
