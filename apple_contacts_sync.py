#!/usr/bin/env python3
"""
Apple Contacts Sync Module
--------------------------
Syncs contacts from macOS native Contacts app (AddressBook) to our contact management system.

Features:
- Reads from all AddressBook source databases (iCloud, Exchange, Local, etc.)
- Extracts: names, organizations, job titles, emails, phone numbers
- Merges/deduplicates with existing contacts.csv data
- Exports to unified contacts.csv format
- Supports incremental sync (only new/updated contacts)
"""

import os
import sqlite3
import csv
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
from collections import defaultdict

# Base paths
BASE_DIR = Path(__file__).resolve().parent
ADDRESSBOOK_BASE = Path.home() / "Library" / "Application Support" / "AddressBook"
CONTACTS_CSV = BASE_DIR / "contacts.csv"
SYNC_LOG = BASE_DIR / "data" / "apple_contacts_sync_log.json"


class AppleContact:
    """Represents a contact from Apple AddressBook"""

    def __init__(self):
        self.apple_id: str = ""
        self.first_name: str = ""
        self.last_name: str = ""
        self.nickname: str = ""
        self.organization: str = ""
        self.job_title: str = ""
        self.department: str = ""
        self.emails: List[Tuple[str, str]] = []  # (label, email)
        self.phones: List[Tuple[str, str]] = []  # (label, phone)
        self.source: str = ""  # Which AddressBook source
        self.created_date: Optional[datetime] = None
        self.modified_date: Optional[datetime] = None

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p).strip()

    @property
    def display_name(self) -> str:
        if self.full_name:
            return self.full_name
        if self.organization:
            return self.organization
        if self.emails:
            return self.emails[0][1].split('@')[0]
        return "Unknown"

    @property
    def primary_email(self) -> str:
        if not self.emails:
            return ""
        # Prefer work email, then first email
        for label, email in self.emails:
            if 'work' in label.lower():
                return email
        return self.emails[0][1]

    @property
    def primary_phone(self) -> str:
        if not self.phones:
            return ""
        # Prefer mobile, then work, then first
        for label, phone in self.phones:
            if 'mobile' in label.lower() or 'cell' in label.lower():
                return phone
        for label, phone in self.phones:
            if 'work' in label.lower():
                return phone
        return self.phones[0][1]

    def to_csv_row(self) -> Dict[str, str]:
        """Convert to contacts.csv format"""
        # Determine category based on organization/title
        category = self._guess_category()
        priority = self._guess_priority()

        return {
            'Name': self.display_name,
            'First Name': self.first_name,
            'Last Name': self.last_name,
            'Company': self.organization,
            'Title': self.job_title,
            'Email': self.primary_email,
            'Phone': self.primary_phone,
            'Category': category,
            'Priority': priority,
            'Source': f"Apple Contacts ({self.source})",
            'Apple ID': self.apple_id,
            'Notes': self._build_notes(),
        }

    def _guess_category(self) -> str:
        """Guess contact category from org/title"""
        org_lower = (self.organization or "").lower()
        title_lower = (self.job_title or "").lower()
        combined = f"{org_lower} {title_lower}"

        # Music industry keywords
        music_keywords = ['record', 'music', 'entertainment', 'label', 'artist', 'producer',
                        'songwriter', 'publishing', 'a&r', 'tour', 'booking', 'management',
                        'sony', 'warner', 'universal', 'bmg', 'nashville', 'country']
        if any(kw in combined for kw in music_keywords):
            return "Music Industry"

        # Tech
        tech_keywords = ['tech', 'software', 'engineer', 'developer', 'google', 'apple',
                        'microsoft', 'amazon', 'meta', 'startup', 'ai', 'saas']
        if any(kw in combined for kw in tech_keywords):
            return "Technology"

        # Executive
        exec_keywords = ['ceo', 'cfo', 'coo', 'president', 'founder', 'director', 'vp ',
                        'vice president', 'chief', 'partner', 'owner']
        if any(kw in combined for kw in exec_keywords):
            return "Executive/Leadership"

        # Media
        media_keywords = ['media', 'journalist', 'editor', 'writer', 'reporter', 'press',
                        'news', 'podcast', 'radio', 'tv', 'film', 'video']
        if any(kw in combined for kw in media_keywords):
            return "Media"

        # Legal/Finance
        legal_keywords = ['attorney', 'lawyer', 'legal', 'law firm', 'accountant', 'cpa',
                        'financial', 'investment', 'bank']
        if any(kw in combined for kw in legal_keywords):
            return "Legal/Finance"

        return "General"

    def _guess_priority(self) -> str:
        """Guess priority based on title/position"""
        title_lower = (self.job_title or "").lower()

        high_keywords = ['ceo', 'president', 'founder', 'owner', 'partner', 'chief',
                        'vp', 'vice president', 'director', 'head of', 'executive']
        if any(kw in title_lower for kw in high_keywords):
            return "High"

        medium_keywords = ['manager', 'senior', 'lead', 'principal', 'coordinator']
        if any(kw in title_lower for kw in medium_keywords):
            return "Medium"

        return "Normal"

    def _build_notes(self) -> str:
        """Build notes string with extra info"""
        notes = []
        if self.department:
            notes.append(f"Dept: {self.department}")
        if self.nickname:
            notes.append(f"Nickname: {self.nickname}")
        if len(self.emails) > 1:
            other_emails = [e for _, e in self.emails[1:]]
            notes.append(f"Also: {', '.join(other_emails)}")
        return " | ".join(notes)


class AppleContactsSync:
    """Main sync engine for Apple Contacts"""

    def __init__(self):
        self.contacts: List[AppleContact] = []
        self.sources: Dict[str, str] = {}  # source_id -> source_name
        self.existing_contacts: Dict[str, Dict] = {}  # email -> contact row
        self.stats = {
            'sources_found': 0,
            'contacts_read': 0,
            'contacts_new': 0,
            'contacts_updated': 0,
            'contacts_skipped': 0,
        }

    def find_addressbook_sources(self) -> List[Path]:
        """Find all AddressBook source databases"""
        sources = []
        sources_dir = ADDRESSBOOK_BASE / "Sources"

        if not sources_dir.exists():
            print(f"   AddressBook Sources directory not found: {sources_dir}")
            return sources

        for source_dir in sources_dir.iterdir():
            if source_dir.is_dir():
                db_path = source_dir / "AddressBook-v22.abcddb"
                if db_path.exists():
                    sources.append(db_path)
                    self.sources[source_dir.name] = source_dir.name[:8]  # Short ID

        self.stats['sources_found'] = len(sources)
        print(f"   Found {len(sources)} AddressBook sources")
        return sources

    def read_contacts_from_db(self, db_path: Path) -> List[AppleContact]:
        """Read contacts from a single AddressBook database"""
        contacts = []
        source_id = db_path.parent.name

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Read main contact records
            cursor.execute("""
                SELECT
                    Z_PK, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZNICKNAME,
                    ZORGANIZATION, ZJOBTITLE, ZDEPARTMENT,
                    ZCREATIONDATE, ZMODIFICATIONDATE
                FROM ZABCDRECORD
                WHERE ZFIRSTNAME IS NOT NULL
                   OR ZLASTNAME IS NOT NULL
                   OR ZORGANIZATION IS NOT NULL
            """)

            records = {row['Z_PK']: dict(row) for row in cursor.fetchall()}

            # Read emails
            cursor.execute("""
                SELECT ZOWNER, ZLABEL, ZADDRESS
                FROM ZABCDEMAILADDRESS
                WHERE ZADDRESS IS NOT NULL
            """)
            emails_by_owner = defaultdict(list)
            for row in cursor.fetchall():
                if row['ZOWNER'] and row['ZADDRESS']:
                    label = row['ZLABEL'] or 'other'
                    # Clean up Apple's label format
                    label = label.replace('_$!<', '').replace('>!$_', '').lower()
                    emails_by_owner[row['ZOWNER']].append((label, row['ZADDRESS']))

            # Read phone numbers
            cursor.execute("""
                SELECT ZOWNER, ZLABEL, ZFULLNUMBER
                FROM ZABCDPHONENUMBER
                WHERE ZFULLNUMBER IS NOT NULL
            """)
            phones_by_owner = defaultdict(list)
            for row in cursor.fetchall():
                if row['ZOWNER'] and row['ZFULLNUMBER']:
                    label = row['ZLABEL'] or 'other'
                    label = label.replace('_$!<', '').replace('>!$_', '').lower()
                    phones_by_owner[row['ZOWNER']].append((label, row['ZFULLNUMBER']))

            # Build contact objects
            for pk, rec in records.items():
                contact = AppleContact()
                contact.apple_id = rec.get('ZUNIQUEID') or str(pk)
                contact.first_name = rec.get('ZFIRSTNAME') or ""
                contact.last_name = rec.get('ZLASTNAME') or ""
                contact.nickname = rec.get('ZNICKNAME') or ""
                contact.organization = rec.get('ZORGANIZATION') or ""
                contact.job_title = rec.get('ZJOBTITLE') or ""
                contact.department = rec.get('ZDEPARTMENT') or ""
                contact.emails = emails_by_owner.get(pk, [])
                contact.phones = phones_by_owner.get(pk, [])
                contact.source = source_id[:8]

                # Parse timestamps (Apple's Core Data format)
                if rec.get('ZCREATIONDATE'):
                    try:
                        # Core Data timestamps are seconds since 2001-01-01
                        contact.created_date = datetime(2001, 1, 1) + \
                            __import__('datetime').timedelta(seconds=rec['ZCREATIONDATE'])
                    except:
                        pass

                contacts.append(contact)

            conn.close()

        except Exception as e:
            print(f"   Error reading {db_path}: {e}")

        return contacts

    def load_existing_contacts(self) -> None:
        """Load existing contacts.csv for merge/dedup"""
        if not CONTACTS_CSV.exists():
            print("   No existing contacts.csv found")
            return

        try:
            with open(CONTACTS_CSV, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = (row.get('Email') or "").lower().strip()
                    name = (row.get('Name') or "").lower().strip()

                    # Index by email and name for dedup
                    if email:
                        self.existing_contacts[email] = row
                    if name:
                        self.existing_contacts[f"name:{name}"] = row

            print(f"   Loaded {len(self.existing_contacts)} existing contacts for merge")
        except Exception as e:
            print(f"   Error loading existing contacts: {e}")

    def sync_all(self) -> Dict:
        """
        Main sync process:
        1. Find all AddressBook sources
        2. Read contacts from each
        3. Deduplicate across sources
        4. Merge with existing contacts.csv
        5. Export unified contacts.csv
        """
        print("\n=== Apple Contacts Sync ===\n")

        # Find sources
        sources = self.find_addressbook_sources()
        if not sources:
            return {'error': 'No AddressBook sources found', 'stats': self.stats}

        # Load existing for merge
        self.load_existing_contacts()

        # Read from all sources
        all_contacts = []
        for source_path in sources:
            contacts = self.read_contacts_from_db(source_path)
            all_contacts.extend(contacts)
            print(f"   Read {len(contacts)} contacts from {source_path.parent.name[:8]}...")

        self.stats['contacts_read'] = len(all_contacts)
        print(f"\n   Total contacts read: {len(all_contacts)}")

        # Deduplicate (by email, then by name)
        unique_contacts = self._deduplicate(all_contacts)
        print(f"   After deduplication: {len(unique_contacts)}")

        # Merge with existing
        merged = self._merge_with_existing(unique_contacts)
        print(f"   After merge: {len(merged)}")

        # Export
        self._export_contacts(merged)

        return {
            'status': 'success',
            'stats': self.stats,
            'total_contacts': len(merged),
        }

    def _deduplicate(self, contacts: List[AppleContact]) -> List[AppleContact]:
        """Deduplicate contacts across sources"""
        seen_emails: Set[str] = set()
        seen_names: Set[str] = set()
        unique = []

        for contact in contacts:
            # Check email first
            email = contact.primary_email.lower()
            if email and email in seen_emails:
                continue

            # Check name (for contacts without email)
            name_key = f"{contact.first_name}|{contact.last_name}|{contact.organization}".lower()
            if not email and name_key in seen_names:
                continue

            # Keep this contact
            if email:
                seen_emails.add(email)
            seen_names.add(name_key)
            unique.append(contact)

        return unique

    def _merge_with_existing(self, contacts: List[AppleContact]) -> List[Dict]:
        """Merge Apple contacts with existing contacts.csv"""
        merged = []
        apple_emails = set()

        for contact in contacts:
            row = contact.to_csv_row()
            email = row['Email'].lower()
            name = row['Name'].lower()

            # Check if exists
            existing = None
            if email:
                existing = self.existing_contacts.get(email)
                apple_emails.add(email)
            if not existing and name:
                existing = self.existing_contacts.get(f"name:{name}")

            if existing:
                # Merge: prefer existing data where available, fill gaps from Apple
                for key in row:
                    if not existing.get(key) and row.get(key):
                        existing[key] = row[key]
                merged.append(existing)
                self.stats['contacts_updated'] += 1
            else:
                merged.append(row)
                self.stats['contacts_new'] += 1

        # Add existing contacts not in Apple
        for key, existing in self.existing_contacts.items():
            if key.startswith('name:'):
                continue  # Skip name keys
            if key.lower() not in apple_emails:
                merged.append(existing)
                self.stats['contacts_skipped'] += 1

        return merged

    def _export_contacts(self, contacts: List[Dict]) -> None:
        """Export merged contacts to contacts.csv"""
        if not contacts:
            return

        # Ensure consistent columns
        all_columns = set()
        for c in contacts:
            all_columns.update(c.keys())

        # Preferred column order
        preferred_order = ['Name', 'First Name', 'Last Name', 'Company', 'Title',
                         'Email', 'Phone', 'Category', 'Priority', 'Source', 'Notes']
        columns = [c for c in preferred_order if c in all_columns]
        columns.extend(sorted(c for c in all_columns if c not in columns))

        # Backup existing
        if CONTACTS_CSV.exists():
            backup_path = CONTACTS_CSV.with_suffix(f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
            CONTACTS_CSV.rename(backup_path)
            print(f"   Backed up existing to {backup_path.name}")

        # Write new
        with open(CONTACTS_CSV, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(contacts)

        print(f"   Exported {len(contacts)} contacts to {CONTACTS_CSV.name}")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def sync_apple_contacts() -> Dict:
    """One-liner to sync Apple contacts"""
    syncer = AppleContactsSync()
    return syncer.sync_all()


def get_apple_contacts_stats() -> Dict:
    """Get stats about Apple AddressBook without syncing"""
    sources_dir = ADDRESSBOOK_BASE / "Sources"
    stats = {
        'available': sources_dir.exists(),
        'sources': [],
        'total_contacts': 0,
    }

    if not sources_dir.exists():
        return stats

    for source_dir in sources_dir.iterdir():
        if source_dir.is_dir():
            db_path = source_dir / "AddressBook-v22.abcddb"
            if db_path.exists():
                try:
                    conn = sqlite3.connect(str(db_path))
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(*) FROM ZABCDRECORD
                        WHERE ZFIRSTNAME IS NOT NULL
                           OR ZLASTNAME IS NOT NULL
                           OR ZORGANIZATION IS NOT NULL
                    """)
                    count = cursor.fetchone()[0]
                    conn.close()

                    stats['sources'].append({
                        'id': source_dir.name[:8],
                        'contacts': count
                    })
                    stats['total_contacts'] += count
                except:
                    pass

    return stats


def search_apple_contacts(query: str, limit: int = 20) -> List[Dict]:
    """
    Search Apple contacts directly without full sync.
    Useful for quick lookups.
    """
    results = []
    query_lower = query.lower()
    sources_dir = ADDRESSBOOK_BASE / "Sources"

    if not sources_dir.exists():
        return results

    for source_dir in sources_dir.iterdir():
        if not source_dir.is_dir():
            continue

        db_path = source_dir / "AddressBook-v22.abcddb"
        if not db_path.exists():
            continue

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Search by name or organization
            cursor.execute("""
                SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION, ZJOBTITLE
                FROM ZABCDRECORD
                WHERE LOWER(ZFIRSTNAME || ' ' || COALESCE(ZLASTNAME, '')) LIKE ?
                   OR LOWER(COALESCE(ZORGANIZATION, '')) LIKE ?
                LIMIT ?
            """, (f'%{query_lower}%', f'%{query_lower}%', limit))

            for row in cursor.fetchall():
                pk = row['Z_PK']

                # Get primary email
                cursor.execute("""
                    SELECT ZADDRESS FROM ZABCDEMAILADDRESS
                    WHERE ZOWNER = ? LIMIT 1
                """, (pk,))
                email_row = cursor.fetchone()
                email = email_row['ZADDRESS'] if email_row else ""

                # Get primary phone
                cursor.execute("""
                    SELECT ZFULLNUMBER FROM ZABCDPHONENUMBER
                    WHERE ZOWNER = ? LIMIT 1
                """, (pk,))
                phone_row = cursor.fetchone()
                phone = phone_row['ZFULLNUMBER'] if phone_row else ""

                first = row['ZFIRSTNAME'] or ""
                last = row['ZLASTNAME'] or ""
                name = f"{first} {last}".strip() or row['ZORGANIZATION'] or "Unknown"

                results.append({
                    'name': name,
                    'company': row['ZORGANIZATION'] or "",
                    'title': row['ZJOBTITLE'] or "",
                    'email': email,
                    'phone': phone,
                    'source': 'Apple Contacts',
                })

                if len(results) >= limit:
                    break

            conn.close()

        except Exception as e:
            continue

        if len(results) >= limit:
            break

    return results


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse
    import json

    parser = argparse.ArgumentParser(description='Apple Contacts Sync')
    parser.add_argument('--sync', action='store_true', help='Sync Apple contacts to contacts.csv')
    parser.add_argument('--stats', action='store_true', help='Show AddressBook stats')
    parser.add_argument('--search', type=str, help='Search for a contact')
    args = parser.parse_args()

    if args.sync:
        result = sync_apple_contacts()
        print(json.dumps(result, indent=2, default=str))

    elif args.stats:
        stats = get_apple_contacts_stats()
        print(json.dumps(stats, indent=2))

    elif args.search:
        results = search_apple_contacts(args.search)
        print(f"\nFound {len(results)} results for '{args.search}':\n")
        for r in results:
            print(f"  {r['name']}")
            if r['company']:
                print(f"    {r['company']}")
            if r['email']:
                print(f"    {r['email']}")
            print()

    else:
        # Default: show stats
        stats = get_apple_contacts_stats()
        print("\n=== Apple AddressBook Stats ===\n")
        print(f"Available: {stats['available']}")
        print(f"Total contacts: {stats['total_contacts']}")
        print(f"\nSources:")
        for src in stats['sources']:
            print(f"  {src['id']}: {src['contacts']} contacts")
        print("\nUse --sync to sync to contacts.csv")
        print("Use --search 'name' to search contacts")
