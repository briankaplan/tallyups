#!/usr/bin/env python3
"""
contact_management.py - Contacts+ Style Contact Management System
-----------------------------------------------------------------

A comprehensive contact management system that:
1. Loads and indexes contacts from CSV for fast lookup
2. Provides fuzzy search across names, companies, and titles
3. Integrates with expense notes to identify meeting attendees
4. Tracks interaction history with contacts
5. Prepares for Google People API sync

Used by:
- smart_notes_engine.py - to identify meeting attendees
- viewer_server.py - API endpoints for contact management
- contacts_engine.py - enhanced attendee guessing
"""

from __future__ import annotations

import os
import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from difflib import SequenceMatcher
from collections import defaultdict

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Contact:
    """Represents a contact with all their information."""
    id: int
    name: str
    first_name: str
    last_name: str
    title: str = ""
    company: str = ""
    category: str = ""
    priority: str = "Low"  # High, Medium, Low
    notes: str = ""
    relationship: str = ""  # e.g., "Professional Contact", "High-Level Executive"
    status: str = "Not Contacted"
    strategic_notes: str = ""
    connected_on: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    tags: List[str] = field(default_factory=list)
    last_interaction: str = ""
    interaction_count: int = 0
    google_people_id: str = ""  # For Google People API sync

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        return d

    @classmethod
    def from_csv_row(cls, row: Dict[str, str]) -> 'Contact':
        """Create Contact from CSV row."""
        return cls(
            id=int(row.get('id', 0)),
            name=row.get('name', ''),
            first_name=row.get('first_name', ''),
            last_name=row.get('last_name', ''),
            title=row.get('title', ''),
            company=row.get('company', ''),
            category=row.get('category', ''),
            priority=row.get('priority', 'Low'),
            notes=row.get('notes', ''),
            relationship=row.get('relationship', ''),
            status=row.get('status', 'Not Contacted'),
            strategic_notes=row.get('strategic_notes', ''),
            connected_on=row.get('connected_on', ''),
            email=row.get('email', ''),
            phone=row.get('phone', ''),
            linkedin_url=row.get('linkedin_url', ''),
            tags=row.get('tags', '').split(',') if row.get('tags') else [],
        )


@dataclass
class ContactInteraction:
    """Tracks an interaction with a contact."""
    contact_id: int
    contact_name: str
    date: str
    interaction_type: str  # "meeting", "email", "call", "expense"
    description: str
    expense_id: Optional[int] = None
    expense_amount: Optional[float] = None
    location: str = ""


# =============================================================================
# CONTACT MANAGER CLASS
# =============================================================================

class ContactManager:
    """
    Main class for managing contacts with fast lookup and fuzzy search.
    """

    def __init__(self, csv_path: str = None):
        self.contacts: Dict[int, Contact] = {}
        self.name_index: Dict[str, List[int]] = defaultdict(list)  # token -> contact_ids
        self.company_index: Dict[str, List[int]] = defaultdict(list)
        self.category_index: Dict[str, List[int]] = defaultdict(list)
        self.interactions: List[ContactInteraction] = []

        # Default path
        if csv_path is None:
            base_dir = Path(__file__).resolve().parent
            csv_path = base_dir / "contacts.csv"

        self.csv_path = Path(csv_path)
        self._load_contacts()

    def _load_contacts(self):
        """Load contacts from CSV and build indexes."""
        if not self.csv_path.exists():
            print(f"Contacts file not found: {self.csv_path}")
            return

        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    contact = Contact.from_csv_row(row)
                    self.contacts[contact.id] = contact
                    self._index_contact(contact)
                except Exception as e:
                    print(f"Error loading contact: {e}")

        print(f"Loaded {len(self.contacts)} contacts")

    def _index_contact(self, contact: Contact):
        """Build search indexes for a contact."""
        # Name tokens
        name_tokens = self._tokenize(contact.name)
        for token in name_tokens:
            self.name_index[token].append(contact.id)

        # First and last name separately
        if contact.first_name:
            for token in self._tokenize(contact.first_name):
                self.name_index[token].append(contact.id)
        if contact.last_name:
            for token in self._tokenize(contact.last_name):
                self.name_index[token].append(contact.id)

        # Company
        if contact.company:
            company_lower = contact.company.lower().strip()
            self.company_index[company_lower].append(contact.id)
            for token in self._tokenize(contact.company):
                self.company_index[token].append(contact.id)

        # Category
        if contact.category:
            cat_lower = contact.category.lower().strip()
            self.category_index[cat_lower].append(contact.id)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text for indexing."""
        text = text.lower()
        # Remove special characters except spaces
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()
        return [t for t in tokens if len(t) >= 2]

    # -------------------------------------------------------------------------
    # SEARCH METHODS
    # -------------------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> List[Contact]:
        """
        Fuzzy search contacts by name, company, or title.
        Returns contacts sorted by relevance score.
        """
        query = query.lower().strip()
        if not query:
            return []

        scores: Dict[int, float] = defaultdict(float)
        query_tokens = self._tokenize(query)

        # Exact name match (highest priority)
        for contact in self.contacts.values():
            name_lower = contact.name.lower()
            if query == name_lower:
                scores[contact.id] = 1.0
            elif query in name_lower:
                scores[contact.id] = max(scores[contact.id], 0.9)

        # Token matching
        for token in query_tokens:
            # Name index
            if token in self.name_index:
                for cid in self.name_index[token]:
                    scores[cid] = max(scores[cid], 0.7)

            # Company index
            if token in self.company_index:
                for cid in self.company_index[token]:
                    scores[cid] = max(scores[cid], 0.5)

            # Fuzzy matching for longer tokens
            if len(token) >= 3:
                for indexed_token in self.name_index.keys():
                    ratio = SequenceMatcher(None, token, indexed_token).ratio()
                    if ratio > 0.8:
                        for cid in self.name_index[indexed_token]:
                            scores[cid] = max(scores[cid], ratio * 0.6)

        # Sort by score and return top results
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [self.contacts[cid] for cid in sorted_ids[:limit]]

    def search_by_name(self, name: str, limit: int = 5) -> List[Contact]:
        """Search contacts specifically by name with fuzzy matching."""
        name = name.lower().strip()
        results = []

        for contact in self.contacts.values():
            # Check full name
            full_name = contact.name.lower()
            if name == full_name:
                results.append((contact, 1.0))
            elif name in full_name:
                results.append((contact, 0.9))
            else:
                # Fuzzy match
                ratio = SequenceMatcher(None, name, full_name).ratio()
                if ratio > 0.6:
                    results.append((contact, ratio))
                else:
                    # Check first/last name individually
                    first_ratio = SequenceMatcher(None, name, contact.first_name.lower()).ratio()
                    last_ratio = SequenceMatcher(None, name, contact.last_name.lower()).ratio()
                    best = max(first_ratio, last_ratio)
                    if best > 0.7:
                        results.append((contact, best * 0.8))

        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results[:limit]]

    def search_by_company(self, company: str, limit: int = 20) -> List[Contact]:
        """Find all contacts at a company."""
        company = company.lower().strip()
        contact_ids = set()

        # Exact match
        if company in self.company_index:
            contact_ids.update(self.company_index[company])

        # Token match
        for token in self._tokenize(company):
            if token in self.company_index:
                contact_ids.update(self.company_index[token])

        # Also check contact.company directly for fuzzy match
        for contact in self.contacts.values():
            if contact.company and company in contact.company.lower():
                contact_ids.add(contact.id)

        contacts = [self.contacts[cid] for cid in contact_ids if cid in self.contacts]
        return contacts[:limit]

    def search_by_category(self, category: str, limit: int = 50) -> List[Contact]:
        """Find contacts by category."""
        category = category.lower().strip()
        contact_ids = set()

        if category in self.category_index:
            contact_ids.update(self.category_index[category])

        # Partial match
        for cat_key in self.category_index.keys():
            if category in cat_key or cat_key in category:
                contact_ids.update(self.category_index[cat_key])

        contacts = [self.contacts[cid] for cid in contact_ids if cid in self.contacts]

        # Sort by priority
        priority_order = {'High': 0, 'Medium': 1, 'Low': 2}
        contacts.sort(key=lambda c: priority_order.get(c.priority, 3))

        return contacts[:limit]

    def get_high_priority_contacts(self, limit: int = 50) -> List[Contact]:
        """Get all high-priority contacts."""
        high_priority = [c for c in self.contacts.values() if c.priority == 'High']
        return high_priority[:limit]

    def get_contact_by_id(self, contact_id: int) -> Optional[Contact]:
        """Get a specific contact by ID."""
        return self.contacts.get(contact_id)

    # -------------------------------------------------------------------------
    # MEETING ATTENDEE IDENTIFICATION
    # -------------------------------------------------------------------------

    def find_likely_attendees(
        self,
        merchant: str,
        date: str = "",
        business_type: str = "",
        amount: float = 0,
        calendar_attendees: List[str] = None,
        imessage_context: List[str] = None
    ) -> List[Tuple[Contact, float]]:
        """
        Find likely attendees for a meeting/meal expense.

        Returns list of (Contact, confidence_score) tuples.
        """
        candidates: Dict[int, float] = defaultdict(float)

        # 1. Calendar attendees (highest confidence)
        if calendar_attendees:
            for attendee_name in calendar_attendees:
                matches = self.search_by_name(attendee_name, limit=3)
                for contact in matches:
                    candidates[contact.id] = max(candidates[contact.id], 0.95)

        # 2. iMessage mentions
        if imessage_context:
            for msg in imessage_context:
                # Look for names in message text
                for contact in self.contacts.values():
                    if contact.first_name.lower() in msg.lower():
                        candidates[contact.id] = max(candidates[contact.id], 0.7)
                    if contact.last_name.lower() in msg.lower():
                        candidates[contact.id] = max(candidates[contact.id], 0.75)

        # 3. Business type affinity
        if business_type:
            biz_lower = business_type.lower()

            if 'secondary' in biz_lower or 'sec' in biz_lower:
                # Music/rodeo industry contacts
                music_contacts = self.search_by_category('Music Industry', limit=30)
                for contact in music_contacts:
                    candidates[contact.id] = max(candidates[contact.id], 0.4)

            elif 'business' in biz_lower:
                # Tech/streaming/business contacts
                exec_contacts = self.search_by_category('Executive / Leadership', limit=20)
                for contact in exec_contacts:
                    candidates[contact.id] = max(candidates[contact.id], 0.4)

                tech_contacts = self.search_by_category('Tech / Streaming', limit=20)
                for contact in tech_contacts:
                    candidates[contact.id] = max(candidates[contact.id], 0.35)

        # 4. Location/merchant hints
        merchant_lower = merchant.lower()

        if 'soho house' in merchant_lower or 'sh nashville' in merchant_lower:
            # Private club - likely exec meetings
            exec_contacts = self.get_high_priority_contacts(limit=30)
            for contact in exec_contacts:
                candidates[contact.id] = max(candidates[contact.id], 0.5)

        # Convert to list with Contact objects
        results = []
        for cid, score in candidates.items():
            if cid in self.contacts:
                results.append((self.contacts[cid], score))

        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:10]  # Top 10 candidates

    def format_attendees_for_note(
        self,
        attendees: List[Tuple[Contact, float]],
        min_confidence: float = 0.5
    ) -> str:
        """Format attendees for expense note."""
        high_conf = [a for a in attendees if a[1] >= min_confidence]

        if not high_conf:
            return "Brian Kaplan"

        names = ["Brian Kaplan"]  # Always include Brian
        for contact, score in high_conf:
            if contact.name not in names:
                names.append(contact.name)

        return ", ".join(names)

    # -------------------------------------------------------------------------
    # INTERACTION TRACKING
    # -------------------------------------------------------------------------

    def record_interaction(
        self,
        contact_id: int,
        interaction_type: str,
        description: str,
        date: str = None,
        expense_id: int = None,
        expense_amount: float = None,
        location: str = ""
    ):
        """Record an interaction with a contact."""
        contact = self.contacts.get(contact_id)
        if not contact:
            return

        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        interaction = ContactInteraction(
            contact_id=contact_id,
            contact_name=contact.name,
            date=date,
            interaction_type=interaction_type,
            description=description,
            expense_id=expense_id,
            expense_amount=expense_amount,
            location=location
        )

        self.interactions.append(interaction)

        # Update contact
        contact.last_interaction = date
        contact.interaction_count += 1

    def get_contact_interactions(
        self,
        contact_id: int,
        limit: int = 20
    ) -> List[ContactInteraction]:
        """Get recent interactions with a contact."""
        contact_interactions = [
            i for i in self.interactions if i.contact_id == contact_id
        ]
        # Sort by date descending
        contact_interactions.sort(key=lambda x: x.date, reverse=True)
        return contact_interactions[:limit]

    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get contact statistics."""
        categories = defaultdict(int)
        priorities = defaultdict(int)
        relationships = defaultdict(int)

        for contact in self.contacts.values():
            if contact.category:
                categories[contact.category] += 1
            priorities[contact.priority] += 1
            if contact.relationship:
                relationships[contact.relationship] += 1

        return {
            "total_contacts": len(self.contacts),
            "by_priority": dict(priorities),
            "by_category": dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)[:10]),
            "by_relationship": dict(sorted(relationships.items(), key=lambda x: x[1], reverse=True)[:10]),
            "total_interactions": len(self.interactions),
        }

    # -------------------------------------------------------------------------
    # CRUD OPERATIONS
    # -------------------------------------------------------------------------

    def add_contact(self, contact: Contact) -> Contact:
        """Add a new contact."""
        # Generate new ID
        if self.contacts:
            new_id = max(self.contacts.keys()) + 1
        else:
            new_id = 1

        contact.id = new_id
        self.contacts[new_id] = contact
        self._index_contact(contact)

        return contact

    def update_contact(self, contact_id: int, updates: Dict[str, Any]) -> Optional[Contact]:
        """Update a contact's information."""
        contact = self.contacts.get(contact_id)
        if not contact:
            return None

        for key, value in updates.items():
            if hasattr(contact, key):
                setattr(contact, key, value)

        # Re-index if name/company changed
        if 'name' in updates or 'company' in updates or 'category' in updates:
            self._reindex_contact(contact)

        return contact

    def _reindex_contact(self, contact: Contact):
        """Remove old index entries and re-index a contact."""
        # Remove from indexes
        for token_list in self.name_index.values():
            if contact.id in token_list:
                token_list.remove(contact.id)
        for token_list in self.company_index.values():
            if contact.id in token_list:
                token_list.remove(contact.id)
        for token_list in self.category_index.values():
            if contact.id in token_list:
                token_list.remove(contact.id)

        # Re-index
        self._index_contact(contact)

    def save_to_csv(self, path: str = None):
        """Save contacts back to CSV."""
        if path is None:
            path = self.csv_path

        fieldnames = [
            'id', 'name', 'first_name', 'last_name', 'title', 'company',
            'category', 'priority', 'notes', 'relationship', 'status',
            'strategic_notes', 'connected_on', 'email', 'phone', 'linkedin_url',
            'tags', 'last_interaction', 'interaction_count', 'google_people_id'
        ]

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for contact in sorted(self.contacts.values(), key=lambda c: c.id):
                row = contact.to_dict()
                row['tags'] = ','.join(row['tags']) if row['tags'] else ''
                writer.writerow(row)


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_contact_manager: Optional[ContactManager] = None

def get_contact_manager() -> ContactManager:
    """Get or create the singleton ContactManager instance."""
    global _contact_manager
    if _contact_manager is None:
        _contact_manager = ContactManager()
    return _contact_manager


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def search_contacts(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search contacts and return as list of dicts."""
    manager = get_contact_manager()
    contacts = manager.search(query, limit=limit)
    return [c.to_dict() for c in contacts]


def find_attendees_for_expense(
    merchant: str,
    date: str = "",
    business_type: str = "",
    amount: float = 0,
    calendar_attendees: List[str] = None,
    imessage_context: List[str] = None
) -> List[Dict[str, Any]]:
    """
    Find likely attendees for an expense and return formatted results.
    """
    manager = get_contact_manager()
    attendees = manager.find_likely_attendees(
        merchant=merchant,
        date=date,
        business_type=business_type,
        amount=amount,
        calendar_attendees=calendar_attendees,
        imessage_context=imessage_context
    )

    return [
        {
            "name": contact.name,
            "title": contact.title,
            "company": contact.company,
            "confidence": score,
            "contact_id": contact.id
        }
        for contact, score in attendees
    ]


def get_contact_stats() -> Dict[str, Any]:
    """Get contact database statistics."""
    manager = get_contact_manager()
    return manager.get_stats()


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Contact Management System")
    parser.add_argument("--search", help="Search for contacts")
    parser.add_argument("--company", help="Search by company")
    parser.add_argument("--category", help="Search by category")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--attendees", help="Find attendees for merchant")
    args = parser.parse_args()

    manager = get_contact_manager()

    if args.stats:
        print("\n=== Contact Statistics ===")
        stats = manager.get_stats()
        print(json.dumps(stats, indent=2))

    elif args.search:
        print(f"\n=== Searching for: {args.search} ===")
        results = manager.search(args.search, limit=10)
        for contact in results:
            print(f"  {contact.name} - {contact.title} @ {contact.company}")

    elif args.company:
        print(f"\n=== Contacts at: {args.company} ===")
        results = manager.search_by_company(args.company)
        for contact in results:
            print(f"  {contact.name} - {contact.title}")

    elif args.category:
        print(f"\n=== Category: {args.category} ===")
        results = manager.search_by_category(args.category)
        for contact in results[:20]:
            print(f"  [{contact.priority}] {contact.name} - {contact.title}")

    elif args.attendees:
        print(f"\n=== Likely Attendees for: {args.attendees} ===")
        attendees = manager.find_likely_attendees(
            merchant=args.attendees,
            business_type="Business"
        )
        for contact, score in attendees:
            print(f"  {contact.name} ({score:.0%}) - {contact.title}")

    else:
        # Default: show stats
        stats = manager.get_stats()
        print(f"\nContact Manager: {stats['total_contacts']} contacts loaded")
        print("\nPriority breakdown:")
        for priority, count in stats['by_priority'].items():
            print(f"  {priority}: {count}")

        print("\nTop categories:")
        for cat, count in list(stats['by_category'].items())[:5]:
            print(f"  {cat}: {count}")
