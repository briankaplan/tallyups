#!/usr/bin/env python3
"""
Universal Contact Sync Engine
Keeps ALL contact databases in sync with ATLAS as the source of truth

Supported Sources:
- Google Contacts (multiple accounts)
- Apple/iCloud Contacts
- LinkedIn (import + enrichment)
- CardDAV servers
- Local imports (CSV, vCard)

Architecture:
- ATLAS is the master database
- Changes flow bidirectionally where supported
- Conflict resolution: most recent wins (with merge for additive data)
"""

import os
import asyncio
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import httpx

# Import structured logging if available
try:
    from logging_config import get_logger, SyncLogger
    logger = get_logger(__name__)
    sync_logger = SyncLogger()
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    sync_logger = None


class SyncDirection(Enum):
    PULL = "pull"  # Source → ATLAS
    PUSH = "push"  # ATLAS → Source
    BIDIRECTIONAL = "bidirectional"


class ConflictResolution(Enum):
    ATLAS_WINS = "atlas_wins"
    SOURCE_WINS = "source_wins"
    NEWEST_WINS = "newest_wins"
    MERGE = "merge"
    MANUAL = "manual"  # Requires user intervention


@dataclass
class SyncConflict:
    """Represents a sync conflict between local and remote data"""
    contact_id: Optional[int]  # ATLAS contact ID if exists
    source: str
    source_id: str
    local_data: Dict[str, Any]
    remote_data: Dict[str, Any]
    conflicting_fields: List[str]
    local_modified: Optional[datetime] = None
    remote_modified: Optional[datetime] = None
    resolution: Optional[ConflictResolution] = None
    resolved_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "contact_id": self.contact_id,
            "source": self.source,
            "source_id": self.source_id,
            "conflicting_fields": self.conflicting_fields,
            "local_modified": self.local_modified.isoformat() if self.local_modified else None,
            "remote_modified": self.remote_modified.isoformat() if self.remote_modified else None,
            "resolution": self.resolution.value if self.resolution else None,
        }


@dataclass
class SyncResult:
    """Result of a sync operation"""
    source: str
    direction: SyncDirection
    started_at: datetime
    completed_at: Optional[datetime] = None

    pulled: int = 0
    pushed: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    conflicts: int = 0
    errors: int = 0

    error_details: List[str] = field(default_factory=list)


@dataclass
class ContactData:
    """Normalized contact data for sync"""
    # Identifiers
    source: str
    source_id: str
    atlas_id: Optional[int] = None

    # Name
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: Optional[str] = None
    nickname: Optional[str] = None

    # Contact info
    emails: List[Dict[str, Any]] = field(default_factory=list)  # [{email, type, is_primary}]
    phones: List[Dict[str, Any]] = field(default_factory=list)  # [{number, type, is_primary}]
    addresses: List[Dict[str, Any]] = field(default_factory=list)

    # Professional
    company: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None

    # Personal
    birthday: Optional[datetime] = None
    anniversary: Optional[datetime] = None
    notes: Optional[str] = None

    # Social
    linkedin_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    website: Optional[str] = None

    # Photo
    photo_url: Optional[str] = None
    photo_data: Optional[bytes] = None

    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    etag: Optional[str] = None

    def get_fingerprint(self) -> str:
        """Generate fingerprint for change detection"""
        data = {
            "name": f"{self.first_name}|{self.last_name}|{self.display_name}",
            "emails": sorted([e.get("email", "").lower() for e in self.emails]),
            "phones": sorted([p.get("number", "") for p in self.phones]),
            "company": self.company,
            "title": self.job_title,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


class ContactSyncAdapter(ABC):
    """Base class for contact source adapters"""

    source_name: str
    supports_push: bool = False
    supports_incremental: bool = False

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the source"""
        pass

    @abstractmethod
    async def pull_contacts(self, since: Optional[datetime] = None) -> List[ContactData]:
        """Pull contacts from source"""
        pass

    async def push_contact(self, contact: ContactData) -> bool:
        """Push contact to source (if supported)"""
        raise NotImplementedError("Push not supported for this source")

    async def delete_contact(self, source_id: str) -> bool:
        """Delete contact from source (if supported)"""
        raise NotImplementedError("Delete not supported for this source")

    def normalize_contact(self, raw_data: Any) -> ContactData:
        """Convert source-specific data to normalized ContactData"""
        raise NotImplementedError()


# =============================================================================
# Google Contacts Adapter
# =============================================================================

class GoogleContactsAdapter(ContactSyncAdapter):
    """Adapter for Google Contacts (People API)"""

    source_name = "google"
    supports_push = True
    supports_incremental = True

    def __init__(self, account_id: int, credentials: Dict[str, str]):
        self.account_id = account_id
        self.credentials = credentials
        self.service = None

    async def connect(self) -> bool:
        """Connect to Google People API"""
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=self.credentials.get("access_token"),
            refresh_token=self.credentials.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        )

        self.service = build('people', 'v1', credentials=creds)
        return True

    async def pull_contacts(self, since: Optional[datetime] = None) -> List[ContactData]:
        """Pull contacts from Google"""
        contacts = []
        page_token = None

        while True:
            results = self.service.people().connections().list(
                resourceName='people/me',
                pageSize=1000,
                personFields='names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,urls,photos,metadata',
                pageToken=page_token,
            ).execute()

            for person in results.get('connections', []):
                contact = self._normalize_google_contact(person)

                # Check if modified since
                if since and contact.updated_at and contact.updated_at < since:
                    continue

                contacts.append(contact)

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        return contacts

    async def push_contact(self, contact: ContactData) -> bool:
        """Push contact to Google"""
        person_data = self._contact_to_google(contact)

        if contact.source_id:
            # Update existing
            self.service.people().updateContact(
                resourceName=contact.source_id,
                updatePersonFields='names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,urls',
                body=person_data
            ).execute()
        else:
            # Create new
            result = self.service.people().createContact(body=person_data).execute()
            contact.source_id = result.get('resourceName')

        return True

    def _normalize_google_contact(self, person: Dict) -> ContactData:
        """Convert Google person to ContactData"""
        names = person.get('names', [{}])
        name = names[0] if names else {}

        emails = [
            {
                "email": e.get('value', '').lower(),
                "type": e.get('type', 'other'),
                "is_primary": i == 0
            }
            for i, e in enumerate(person.get('emailAddresses', []))
        ]

        phones = [
            {
                "number": p.get('value', ''),
                "type": p.get('type', 'other'),
                "is_primary": i == 0
            }
            for i, p in enumerate(person.get('phoneNumbers', []))
        ]

        orgs = person.get('organizations', [{}])
        org = orgs[0] if orgs else {}

        photos = person.get('photos', [])
        photo_url = photos[0].get('url') if photos else None

        metadata = person.get('metadata', {})
        sources = metadata.get('sources', [{}])
        source = sources[0] if sources else {}

        updated_at = None
        if source.get('updateTime'):
            try:
                updated_at = datetime.fromisoformat(source['updateTime'].replace('Z', '+00:00'))
            except:
                pass

        return ContactData(
            source="google",
            source_id=person.get('resourceName', ''),
            first_name=name.get('givenName'),
            last_name=name.get('familyName'),
            display_name=name.get('displayName'),
            emails=emails,
            phones=phones,
            company=org.get('name'),
            job_title=org.get('title'),
            department=org.get('department'),
            photo_url=photo_url,
            updated_at=updated_at,
            etag=person.get('etag'),
        )

    def _contact_to_google(self, contact: ContactData) -> Dict:
        """Convert ContactData to Google person format"""
        person = {
            "names": [{
                "givenName": contact.first_name,
                "familyName": contact.last_name,
            }],
            "emailAddresses": [
                {"value": e["email"], "type": e.get("type", "other")}
                for e in contact.emails
            ],
            "phoneNumbers": [
                {"value": p["number"], "type": p.get("type", "other")}
                for p in contact.phones
            ],
        }

        if contact.company or contact.job_title:
            person["organizations"] = [{
                "name": contact.company,
                "title": contact.job_title,
                "department": contact.department,
            }]

        return person


# =============================================================================
# Apple/iCloud Contacts Adapter
# =============================================================================

class AppleContactsAdapter(ContactSyncAdapter):
    """Adapter for Apple Contacts via contacts framework or CardDAV"""

    source_name = "apple"
    supports_push = True
    supports_incremental = False

    def __init__(self):
        self.contacts_db_path = None

    async def connect(self) -> bool:
        """Connect to Apple Contacts"""
        # Check for Contacts.app database
        from pathlib import Path

        sources_path = Path.home() / "Library/Application Support/AddressBook/Sources"
        if sources_path.exists():
            # Find the main AddressBook database
            for source_dir in sources_path.iterdir():
                db_path = source_dir / "AddressBook-v22.abcddb"
                if db_path.exists():
                    self.contacts_db_path = db_path
                    return True

        # Fallback to older location
        legacy_path = Path.home() / "Library/Application Support/AddressBook/AddressBook-v22.abcddb"
        if legacy_path.exists():
            self.contacts_db_path = legacy_path
            return True

        logger.warning("Could not find Apple Contacts database")
        return False

    async def pull_contacts(self, since: Optional[datetime] = None) -> List[ContactData]:
        """Pull contacts from Apple Contacts database"""
        import sqlite3

        if not self.contacts_db_path:
            return []

        conn = sqlite3.connect(str(self.contacts_db_path))
        conn.row_factory = sqlite3.Row

        contacts = []

        # Query main records
        query = """
            SELECT
                ZUNIQUEID as id,
                ZFIRSTNAME as first_name,
                ZLASTNAME as last_name,
                ZNICKNAME as nickname,
                ZORGANIZATION as company,
                ZJOBTITLE as job_title,
                ZDEPARTMENT as department,
                ZNOTE as notes,
                ZMODIFICATIONDATE as updated_at
            FROM ZABCDRECORD
            WHERE ZFIRSTNAME IS NOT NULL OR ZLASTNAME IS NOT NULL OR ZORGANIZATION IS NOT NULL
        """

        for row in conn.execute(query):
            record_id = row['id']

            # Get emails
            emails = []
            for email_row in conn.execute(
                "SELECT ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS WHERE ZOWNER = ?",
                (record_id,)
            ):
                if email_row['ZADDRESS']:
                    emails.append({
                        "email": email_row['ZADDRESS'].lower(),
                        "type": self._parse_apple_label(email_row['ZLABEL']),
                        "is_primary": len(emails) == 0
                    })

            # Get phones
            phones = []
            for phone_row in conn.execute(
                "SELECT ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER WHERE ZOWNER = ?",
                (record_id,)
            ):
                if phone_row['ZFULLNUMBER']:
                    phones.append({
                        "number": phone_row['ZFULLNUMBER'],
                        "type": self._parse_apple_label(phone_row['ZLABEL']),
                        "is_primary": len(phones) == 0
                    })

            # Convert Apple timestamp (Core Data: seconds since 2001-01-01)
            updated_at = None
            if row['updated_at']:
                apple_epoch = datetime(2001, 1, 1)
                updated_at = apple_epoch + timedelta(seconds=row['updated_at'])

            contact = ContactData(
                source="apple",
                source_id=record_id,
                first_name=row['first_name'],
                last_name=row['last_name'],
                display_name=f"{row['first_name'] or ''} {row['last_name'] or ''}".strip() or row['company'],
                nickname=row['nickname'],
                emails=emails,
                phones=phones,
                company=row['company'],
                job_title=row['job_title'],
                department=row['department'],
                notes=row['notes'],
                updated_at=updated_at,
            )

            contacts.append(contact)

        conn.close()
        return contacts

    def _parse_apple_label(self, label: Optional[str]) -> str:
        """Parse Apple label format"""
        if not label:
            return "other"

        # Labels are like "_$!<Home>!$_" or "_$!<Work>!$_"
        import re
        match = re.search(r'<(.+)>', label)
        if match:
            return match.group(1).lower()
        return "other"


# =============================================================================
# LinkedIn Adapter (Import + Enrichment)
# =============================================================================

class LinkedInAdapter(ContactSyncAdapter):
    """Adapter for LinkedIn - import only + enrichment"""

    source_name = "linkedin"
    supports_push = False
    supports_incremental = False

    def __init__(self, csv_path: Optional[str] = None, proxycurl_api_key: Optional[str] = None):
        self.csv_path = csv_path
        self.proxycurl_api_key = proxycurl_api_key or os.getenv("PROXYCURL_API_KEY")

    async def connect(self) -> bool:
        return True

    async def pull_contacts(self, since: Optional[datetime] = None) -> List[ContactData]:
        """Pull contacts from LinkedIn export CSV"""
        import csv

        if not self.csv_path:
            return []

        contacts = []

        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                contact = ContactData(
                    source="linkedin",
                    source_id=row.get('Profile URL', ''),
                    first_name=row.get('First Name'),
                    last_name=row.get('Last Name'),
                    display_name=f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
                    company=row.get('Company'),
                    job_title=row.get('Position'),
                    linkedin_url=row.get('Profile URL'),
                    emails=[{"email": row.get('Email Address', '').lower(), "type": "work"}] if row.get('Email Address') else [],
                )

                if contact.first_name or contact.last_name:
                    contacts.append(contact)

        return contacts

    async def enrich_contact(self, linkedin_url: str) -> Dict[str, Any]:
        """Enrich contact using Proxycurl API"""
        if not self.proxycurl_api_key:
            return {}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://nubela.co/proxycurl/api/v2/linkedin",
                params={"url": linkedin_url},
                headers={"Authorization": f"Bearer {self.proxycurl_api_key}"}
            )

            if response.status_code == 200:
                return response.json()

        return {}


# =============================================================================
# Universal Sync Engine
# =============================================================================

class UniversalSyncEngine:
    """Orchestrates sync across all contact sources"""

    def __init__(self, atlas_api_url: str):
        self.api_url = atlas_api_url
        self.adapters: Dict[str, ContactSyncAdapter] = {}
        self.conflict_resolution = ConflictResolution.NEWEST_WINS
        self.pending_conflicts: List[SyncConflict] = []
        self.conflict_callback = None  # Optional callback for conflict notification

    # Fields that can have conflicts (not additive like emails/phones)
    CONFLICT_FIELDS = [
        'first_name', 'last_name', 'display_name', 'company',
        'job_title', 'department', 'birthday', 'notes'
    ]

    def register_adapter(self, adapter: ContactSyncAdapter):
        """Register a contact source adapter"""
        self.adapters[adapter.source_name] = adapter
        logger.info(f"Registered adapter: {adapter.source_name}")

    def set_conflict_resolution(self, strategy: ConflictResolution):
        """Set the conflict resolution strategy"""
        self.conflict_resolution = strategy
        logger.info(f"Conflict resolution set to: {strategy.value}")

    def set_conflict_callback(self, callback):
        """Set callback for manual conflict resolution notifications"""
        self.conflict_callback = callback

    def get_pending_conflicts(self) -> List[SyncConflict]:
        """Get all pending conflicts awaiting manual resolution"""
        return [c for c in self.pending_conflicts if c.resolution is None]

    def detect_conflicts(
        self,
        local_data: Dict[str, Any],
        remote_data: ContactData
    ) -> List[str]:
        """
        Detect conflicting fields between local and remote data.

        Returns list of field names that have different non-null values.
        """
        conflicts = []

        remote_dict = {
            'first_name': remote_data.first_name,
            'last_name': remote_data.last_name,
            'display_name': remote_data.display_name,
            'company': remote_data.company,
            'job_title': remote_data.job_title,
            'department': remote_data.department,
            'birthday': remote_data.birthday.isoformat() if remote_data.birthday else None,
            'notes': remote_data.notes,
        }

        for field in self.CONFLICT_FIELDS:
            local_val = local_data.get(field)
            remote_val = remote_dict.get(field)

            # Skip if either value is null/empty
            if not local_val or not remote_val:
                continue

            # Normalize for comparison
            local_norm = str(local_val).strip().lower()
            remote_norm = str(remote_val).strip().lower()

            if local_norm != remote_norm:
                conflicts.append(field)

        return conflicts

    def resolve_conflict(
        self,
        conflict: SyncConflict,
        strategy: Optional[ConflictResolution] = None
    ) -> Dict[str, Any]:
        """
        Resolve a sync conflict using the specified strategy.

        Args:
            conflict: The conflict to resolve
            strategy: Resolution strategy (uses engine default if not specified)

        Returns:
            Resolved data dictionary
        """
        strategy = strategy or self.conflict_resolution

        if strategy == ConflictResolution.ATLAS_WINS:
            # Keep all local values
            conflict.resolution = ConflictResolution.ATLAS_WINS
            conflict.resolved_data = conflict.local_data.copy()
            return conflict.resolved_data

        elif strategy == ConflictResolution.SOURCE_WINS:
            # Use all remote values
            conflict.resolution = ConflictResolution.SOURCE_WINS
            conflict.resolved_data = conflict.remote_data.copy()
            return conflict.resolved_data

        elif strategy == ConflictResolution.NEWEST_WINS:
            # Compare timestamps, use newest
            local_time = conflict.local_modified or datetime.min
            remote_time = conflict.remote_modified or datetime.min

            if local_time >= remote_time:
                conflict.resolution = ConflictResolution.NEWEST_WINS
                conflict.resolved_data = conflict.local_data.copy()
            else:
                conflict.resolution = ConflictResolution.NEWEST_WINS
                conflict.resolved_data = conflict.remote_data.copy()
            return conflict.resolved_data

        elif strategy == ConflictResolution.MERGE:
            # Intelligent merge: prefer non-null remote values, keep local where remote is null
            merged = conflict.local_data.copy()

            for field in conflict.conflicting_fields:
                remote_val = conflict.remote_data.get(field)
                # Remote wins for conflicting fields in merge mode
                if remote_val:
                    merged[field] = remote_val

            # Always merge additive data (emails, phones, addresses)
            for additive_field in ['emails', 'phones', 'addresses']:
                local_items = conflict.local_data.get(additive_field, [])
                remote_items = conflict.remote_data.get(additive_field, [])

                if additive_field == 'emails':
                    # Merge emails by email address
                    seen = {e['email'].lower() for e in local_items if e.get('email')}
                    merged_items = local_items.copy()
                    for item in remote_items:
                        if item.get('email') and item['email'].lower() not in seen:
                            merged_items.append(item)
                    merged[additive_field] = merged_items

                elif additive_field == 'phones':
                    # Merge phones by normalized number
                    seen = {p.get('normalized', p['number']) for p in local_items if p.get('number')}
                    merged_items = local_items.copy()
                    for item in remote_items:
                        key = item.get('normalized', item.get('number', ''))
                        if key and key not in seen:
                            merged_items.append(item)
                    merged[additive_field] = merged_items

                elif additive_field == 'addresses':
                    # Merge addresses by formatted address
                    seen = {a.get('formatted', '').lower() for a in local_items if a.get('formatted')}
                    merged_items = local_items.copy()
                    for item in remote_items:
                        if item.get('formatted') and item['formatted'].lower() not in seen:
                            merged_items.append(item)
                    merged[additive_field] = merged_items

            conflict.resolution = ConflictResolution.MERGE
            conflict.resolved_data = merged
            return conflict.resolved_data

        elif strategy == ConflictResolution.MANUAL:
            # Add to pending conflicts for manual resolution
            if conflict not in self.pending_conflicts:
                self.pending_conflicts.append(conflict)

            # Notify via callback if set
            if self.conflict_callback:
                try:
                    self.conflict_callback(conflict)
                except Exception as e:
                    logger.error(f"Conflict callback error: {e}")

            # Return local data as temporary resolution
            return conflict.local_data

        # Default: return local data
        return conflict.local_data

    def resolve_manual_conflict(
        self,
        conflict_source_id: str,
        resolution: ConflictResolution,
        custom_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Manually resolve a pending conflict.

        Args:
            conflict_source_id: The source_id of the conflicted contact
            resolution: How to resolve (ATLAS_WINS, SOURCE_WINS, MERGE)
            custom_data: Custom merged data (for MERGE resolution)

        Returns:
            True if conflict was found and resolved
        """
        for conflict in self.pending_conflicts:
            if conflict.source_id == conflict_source_id and conflict.resolution is None:
                if custom_data:
                    conflict.resolution = ConflictResolution.MERGE
                    conflict.resolved_data = custom_data
                else:
                    self.resolve_conflict(conflict, resolution)

                logger.info(f"Manually resolved conflict for {conflict_source_id}: {resolution.value}")
                return True

        return False

    async def sync_all(self, direction: SyncDirection = SyncDirection.BIDIRECTIONAL) -> List[SyncResult]:
        """Sync all registered sources"""
        results = []

        for name, adapter in self.adapters.items():
            try:
                result = await self.sync_source(adapter, direction)
                results.append(result)
            except Exception as e:
                logger.error(f"Error syncing {name}: {e}")
                results.append(SyncResult(
                    source=name,
                    direction=direction,
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    errors=1,
                    error_details=[str(e)]
                ))

        return results

    async def sync_source(
        self,
        adapter: ContactSyncAdapter,
        direction: SyncDirection = SyncDirection.BIDIRECTIONAL
    ) -> SyncResult:
        """Sync a single source"""

        result = SyncResult(
            source=adapter.source_name,
            direction=direction,
            started_at=datetime.utcnow()
        )

        # Connect to source
        if not await adapter.connect():
            result.errors = 1
            result.error_details.append("Failed to connect to source")
            result.completed_at = datetime.utcnow()
            return result

        # Pull from source
        if direction in (SyncDirection.PULL, SyncDirection.BIDIRECTIONAL):
            try:
                source_contacts = await adapter.pull_contacts()
                result.pulled = len(source_contacts)

                for contact in source_contacts:
                    try:
                        await self._sync_to_atlas(contact, result)
                    except Exception as e:
                        result.errors += 1
                        result.error_details.append(f"Error syncing {contact.display_name}: {e}")

            except Exception as e:
                result.errors += 1
                result.error_details.append(f"Pull failed: {e}")

        # Push to source (if supported)
        if direction in (SyncDirection.PUSH, SyncDirection.BIDIRECTIONAL) and adapter.supports_push:
            try:
                atlas_contacts = await self._get_atlas_contacts_for_source(adapter.source_name)

                for contact in atlas_contacts:
                    try:
                        if await adapter.push_contact(contact):
                            result.pushed += 1
                    except Exception as e:
                        result.errors += 1
                        result.error_details.append(f"Push failed for {contact.display_name}: {e}")

            except Exception as e:
                result.errors += 1
                result.error_details.append(f"Push failed: {e}")

        result.completed_at = datetime.utcnow()
        return result

    async def _sync_to_atlas(self, contact: ContactData, result: SyncResult):
        """Sync a single contact to ATLAS"""

        async with httpx.AsyncClient() as client:
            # Check if contact exists by source_id
            existing = await self._find_existing_contact(contact)

            if existing:
                # Update existing
                response = await client.put(
                    f"{self.api_url}/contacts/{existing['id']}",
                    json=self._contact_to_api(contact)
                )
                if response.status_code == 200:
                    result.updated += 1
                else:
                    result.errors += 1
            else:
                # Check for duplicate by email/phone
                duplicate = await self._find_duplicate(contact)

                if duplicate:
                    # Merge with existing
                    await self._merge_with_existing(contact, duplicate)
                    result.updated += 1
                else:
                    # Create new
                    response = await client.post(
                        f"{self.api_url}/contacts",
                        json=self._contact_to_api(contact)
                    )
                    if response.status_code in (200, 201):
                        result.created += 1
                    else:
                        result.errors += 1

    async def _find_existing_contact(self, contact: ContactData) -> Optional[Dict]:
        """Find existing contact by source ID"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_url}/contacts",
                params={
                    "source": contact.source,
                    "source_id": contact.source_id
                }
            )

            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                if items:
                    return items[0]

        return None

    async def _find_duplicate(self, contact: ContactData) -> Optional[Dict]:
        """Find duplicate by email or phone"""
        async with httpx.AsyncClient() as client:
            # Search by primary email
            for email in contact.emails:
                response = await client.get(
                    f"{self.api_url}/search",
                    params={"q": email["email"], "limit": 1}
                )

                if response.status_code == 200:
                    results = response.json()
                    if results:
                        return results[0]

            # Search by primary phone
            for phone in contact.phones:
                response = await client.get(
                    f"{self.api_url}/search",
                    params={"q": phone["number"], "limit": 1}
                )

                if response.status_code == 200:
                    results = response.json()
                    if results:
                        return results[0]

        return None

    async def _merge_with_existing(self, new_contact: ContactData, existing: Dict):
        """Merge new contact data with existing contact"""
        # Additive merge: add emails/phones that don't exist
        existing_emails = {e["email"].lower() for e in existing.get("emails", [])}
        existing_phones = {p.get("normalized") or p["number"] for p in existing.get("phones", [])}

        new_emails = [e for e in new_contact.emails if e["email"].lower() not in existing_emails]
        new_phones = [p for p in new_contact.phones if p["number"] not in existing_phones]

        update_data = {}

        if new_emails:
            update_data["emails"] = existing.get("emails", []) + new_emails

        if new_phones:
            update_data["phones"] = existing.get("phones", []) + new_phones

        # Fill in missing fields
        if not existing.get("company") and new_contact.company:
            update_data["company"] = new_contact.company

        if not existing.get("job_title") and new_contact.job_title:
            update_data["job_title"] = new_contact.job_title

        if not existing.get("linkedin_url") and new_contact.linkedin_url:
            update_data["linkedin_url"] = new_contact.linkedin_url

        if update_data:
            async with httpx.AsyncClient() as client:
                await client.put(
                    f"{self.api_url}/contacts/{existing['id']}",
                    json=update_data
                )

    async def _get_atlas_contacts_for_source(self, source: str) -> List[ContactData]:
        """Get ATLAS contacts that should be pushed to a source"""
        # TODO: Implement getting contacts that need to be pushed
        return []

    def _contact_to_api(self, contact: ContactData) -> Dict:
        """Convert ContactData to API format"""
        return {
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "display_name": contact.display_name,
            "nickname": contact.nickname,
            "company": contact.company,
            "job_title": contact.job_title,
            "department": contact.department,
            "birthday": contact.birthday.isoformat() if contact.birthday else None,
            "anniversary": contact.anniversary.isoformat() if contact.anniversary else None,
            "notes": contact.notes,
            "linkedin_url": contact.linkedin_url,
            "twitter_handle": contact.twitter_handle,
            "website": contact.website,
            "photo_url": contact.photo_url,
            "emails": contact.emails,
            "phones": contact.phones,
            "addresses": contact.addresses,
            "source": contact.source,
            "external_id": contact.source_id,
        }


# =============================================================================
# CLI
# =============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="ATLAS Universal Contact Sync")
    parser.add_argument("command", choices=["sync", "sync-google", "sync-apple", "sync-linkedin"])
    parser.add_argument("--api-url", default=os.getenv("ATLAS_API_URL", "http://localhost:8000"))
    parser.add_argument("--account-id", type=int, help="Google account ID for sync")
    parser.add_argument("--linkedin-csv", help="Path to LinkedIn export CSV")
    parser.add_argument("--direction", choices=["pull", "push", "bidirectional"], default="bidirectional")

    args = parser.parse_args()

    engine = UniversalSyncEngine(args.api_url)

    direction = SyncDirection(args.direction)

    if args.command == "sync":
        # Register all available adapters
        engine.register_adapter(AppleContactsAdapter())
        # Would add Google adapters here based on configured accounts

        results = await engine.sync_all(direction)

        for result in results:
            print(f"\n{result.source}:")
            print(f"  Pulled: {result.pulled}")
            print(f"  Created: {result.created}")
            print(f"  Updated: {result.updated}")
            print(f"  Errors: {result.errors}")

    elif args.command == "sync-apple":
        adapter = AppleContactsAdapter()
        engine.register_adapter(adapter)
        result = await engine.sync_source(adapter, direction)
        print(f"Apple Contacts: {result.pulled} pulled, {result.created} created, {result.updated} updated")

    elif args.command == "sync-linkedin":
        if not args.linkedin_csv:
            print("Error: --linkedin-csv required")
            return

        adapter = LinkedInAdapter(csv_path=args.linkedin_csv)
        engine.register_adapter(adapter)
        result = await engine.sync_source(adapter, SyncDirection.PULL)
        print(f"LinkedIn: {result.pulled} pulled, {result.created} created, {result.updated} updated")


if __name__ == "__main__":
    asyncio.run(main())
