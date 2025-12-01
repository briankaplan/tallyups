#!/usr/bin/env python3
"""
Auto Contact Sync - Runs automatically via LaunchAgent

Syncs local Mac data to ATLAS:
1. Mac Contacts database (names, phones, emails)
2. iMessage chat.db (phone numbers, emails, message counts)
3. Enriches contacts with names from Mac Contacts
4. Pushes to ATLAS API

This runs automatically every 6 hours via LaunchAgent.
"""

import sqlite3
import os
import re
import glob
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

# Setup logging
LOG_FILE = Path.home() / "Library/Logs/atlas_contact_sync.log"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CHAT_DB_PATH = Path.home() / "Library/Messages/chat.db"
ADDRESSBOOK_BASE = Path.home() / "Library/Application Support/AddressBook"
API_BASE = os.getenv('API_BASE', 'https://web-production-309e.up.railway.app')
ADMIN_KEY = os.getenv('ADMIN_KEY', 'tallyups-admin-2024')
DATA_DIR = Path(__file__).parent.parent / "data"


def normalize_phone(phone: str) -> str:
    """Normalize phone number to E.164 format"""
    if not phone:
        return ""
    digits = re.sub(r'[^\d+]', '', phone)

    if digits.startswith('+1'):
        return digits
    elif digits.startswith('1') and len(digits) == 11:
        return '+' + digits
    elif len(digits) == 10:
        return '+1' + digits
    elif digits.startswith('+'):
        return digits

    return phone


def get_mac_contacts():
    """
    Read all contacts from Mac Contacts database.
    Returns dict mapping phone/email to contact info.
    """
    contacts = {}
    contact_list = []

    source_dbs = glob.glob(str(ADDRESSBOOK_BASE / "Sources/*/AddressBook-v22.abcddb"))

    for db_path in source_dbs:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Get all contacts with their phones and emails
            cursor.execute("""
                SELECT
                    r.Z_PK as record_id,
                    r.ZFIRSTNAME,
                    r.ZLASTNAME,
                    r.ZORGANIZATION,
                    r.ZJOBTITLE,
                    r.ZNOTE
                FROM ZABCDRECORD r
                WHERE r.ZFIRSTNAME IS NOT NULL OR r.ZLASTNAME IS NOT NULL OR r.ZORGANIZATION IS NOT NULL
            """)

            records = {}
            for row in cursor.fetchall():
                record_id, first, last, org, title, note = row
                records[record_id] = {
                    'first_name': first or '',
                    'last_name': last or '',
                    'organization': org or '',
                    'job_title': title or '',
                    'note': note or '',
                    'phones': [],
                    'emails': []
                }

            # Get phone numbers
            cursor.execute("""
                SELECT ZOWNER, ZFULLNUMBER, ZLABEL
                FROM ZABCDPHONENUMBER
                WHERE ZOWNER IS NOT NULL
            """)

            for owner, phone, label in cursor.fetchall():
                if owner in records and phone:
                    normalized = normalize_phone(phone)
                    records[owner]['phones'].append({
                        'number': normalized,
                        'label': label or 'other'
                    })
                    contacts[normalized] = records[owner]

            # Get emails
            cursor.execute("""
                SELECT ZOWNER, ZADDRESS, ZLABEL
                FROM ZABCDEMAILADDRESS
                WHERE ZOWNER IS NOT NULL
            """)

            for owner, email, label in cursor.fetchall():
                if owner in records and email:
                    email_lower = email.lower()
                    records[owner]['emails'].append({
                        'address': email_lower,
                        'label': label or 'other'
                    })
                    contacts[email_lower] = records[owner]

            # Build contact list
            for record_id, info in records.items():
                if info['phones'] or info['emails']:
                    full_name = f"{info['first_name']} {info['last_name']}".strip()
                    if not full_name:
                        full_name = info['organization']

                    contact_list.append({
                        'name': full_name,
                        'first_name': info['first_name'],
                        'last_name': info['last_name'],
                        'organization': info['organization'],
                        'job_title': info['job_title'],
                        'phones': [p['number'] for p in info['phones']],
                        'emails': [e['address'] for e in info['emails']],
                        'primary_phone': info['phones'][0]['number'] if info['phones'] else None,
                        'primary_email': info['emails'][0]['address'] if info['emails'] else None
                    })

            conn.close()
        except Exception as e:
            logger.warning(f"Could not read {db_path}: {e}")

    return contacts, contact_list


def get_imessage_contacts():
    """Read contacts from iMessage chat.db with message stats"""
    if not CHAT_DB_PATH.exists():
        logger.error(f"chat.db not found at {CHAT_DB_PATH}")
        return []

    try:
        conn = sqlite3.connect(str(CHAT_DB_PATH))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                h.id,
                h.service,
                MAX(m.date) as last_message_date,
                COUNT(m.ROWID) as message_count,
                SUM(CASE WHEN m.is_from_me = 1 THEN 1 ELSE 0 END) as sent_count,
                SUM(CASE WHEN m.is_from_me = 0 THEN 1 ELSE 0 END) as received_count
            FROM handle h
            LEFT JOIN message m ON h.ROWID = m.handle_id
            GROUP BY h.id, h.service
            ORDER BY message_count DESC
        """)

        contacts = []
        for row in cursor.fetchall():
            handle_id, service, last_msg, msg_count, sent, received = row

            is_phone = handle_id.startswith('+') or re.match(r'^\d{10,}', handle_id)
            is_email = '@' in handle_id

            if is_phone:
                contacts.append({
                    'type': 'phone',
                    'value': normalize_phone(handle_id),
                    'raw': handle_id,
                    'service': service,
                    'message_count': msg_count or 0,
                    'sent_count': sent or 0,
                    'received_count': received or 0
                })
            elif is_email:
                contacts.append({
                    'type': 'email',
                    'value': handle_id.lower(),
                    'raw': handle_id,
                    'service': service,
                    'message_count': msg_count or 0,
                    'sent_count': sent or 0,
                    'received_count': received or 0
                })

        conn.close()
        return contacts
    except Exception as e:
        logger.error(f"Error reading chat.db: {e}")
        return []


def http_request(url, method='GET', data=None, timeout=30):
    """Make HTTP request using urllib (no external dependencies)"""
    try:
        if data:
            data = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        logger.warning(f"HTTP error: {e}")
        return 0, None


def sync_to_atlas(enriched_contacts):
    """Sync enriched contacts to ATLAS API"""

    # First, get existing ATLAS contacts
    try:
        url = f"{API_BASE}/api/atlas/contacts?admin_key={ADMIN_KEY}&limit=5000"
        status, data = http_request(url, 'GET')
        if status == 200 and data:
            existing = data.get('contacts', [])
            logger.info(f"Found {len(existing)} existing ATLAS contacts")
        else:
            existing = []
            logger.warning(f"Could not fetch ATLAS contacts: {status}")
    except Exception as e:
        logger.error(f"Error fetching ATLAS contacts: {e}")
        existing = []

    # Build lookup of existing contacts
    existing_by_email = {c.get('email', '').lower(): c for c in existing if c.get('email')}
    existing_by_phone = {normalize_phone(c.get('phone', '')): c for c in existing if c.get('phone')}

    created = 0
    updated = 0
    skipped = 0

    for contact in enriched_contacts:
        name = contact.get('name', '')
        phone = contact.get('primary_phone', '')
        email = contact.get('primary_email', '')

        if not name or (not phone and not email):
            skipped += 1
            continue

        # Check if exists
        existing_contact = None
        if email and email.lower() in existing_by_email:
            existing_contact = existing_by_email[email.lower()]
        elif phone and normalize_phone(phone) in existing_by_phone:
            existing_contact = existing_by_phone[normalize_phone(phone)]

        try:
            if existing_contact:
                # Update if we have more info
                updates = {}
                if phone and not existing_contact.get('phone'):
                    updates['phone'] = phone
                if contact.get('organization') and not existing_contact.get('company'):
                    updates['company'] = contact['organization']
                if contact.get('job_title') and not existing_contact.get('title'):
                    updates['title'] = contact['job_title']

                if updates:
                    url = f"{API_BASE}/api/atlas/contacts/{existing_contact['id']}?admin_key={ADMIN_KEY}"
                    status, _ = http_request(url, 'PUT', updates, timeout=60)
                    if status == 200:
                        updated += 1
                else:
                    skipped += 1
            else:
                # Create new contact
                data = {
                    'name': name,
                    'source': 'mac_contacts'
                }
                if phone:
                    data['phone'] = phone
                if email:
                    data['email'] = email
                if contact.get('organization'):
                    data['company'] = contact['organization']
                if contact.get('job_title'):
                    data['title'] = contact['job_title']

                url = f"{API_BASE}/api/atlas/contacts?admin_key={ADMIN_KEY}"
                status, _ = http_request(url, 'POST', data, timeout=60)
                if status in [200, 201]:
                    created += 1
                    # Add to lookup to prevent duplicates
                    if email:
                        existing_by_email[email.lower()] = data
                    if phone:
                        existing_by_phone[normalize_phone(phone)] = data
        except Exception as e:
            logger.warning(f"Error syncing contact {name}: {e}")

    return created, updated, skipped


def run_sync():
    """Main sync function"""
    logger.info("=" * 60)
    logger.info(f"Starting contact sync at {datetime.now()}")
    logger.info("=" * 60)

    # Step 1: Read Mac Contacts
    logger.info("Reading Mac Contacts database...")
    mac_lookup, mac_contacts = get_mac_contacts()
    logger.info(f"  Found {len(mac_contacts)} contacts with {len(mac_lookup)} phone/email mappings")

    # Step 2: Read iMessage contacts
    logger.info("Reading iMessage contacts...")
    imessage_contacts = get_imessage_contacts()
    phones = [c for c in imessage_contacts if c['type'] == 'phone']
    emails = [c for c in imessage_contacts if c['type'] == 'email']
    logger.info(f"  Found {len(phones)} phone numbers, {len(emails)} emails")

    # Step 3: Enrich iMessage contacts with names
    logger.info("Enriching iMessage contacts with names...")
    enriched = []
    matched = 0

    for contact in imessage_contacts:
        lookup_key = contact['value']
        if lookup_key in mac_lookup:
            mac_info = mac_lookup[lookup_key]
            full_name = f"{mac_info['first_name']} {mac_info['last_name']}".strip()
            enriched.append({
                'name': full_name,
                'first_name': mac_info['first_name'],
                'last_name': mac_info['last_name'],
                'organization': mac_info.get('organization', ''),
                'primary_phone': contact['value'] if contact['type'] == 'phone' else None,
                'primary_email': contact['value'] if contact['type'] == 'email' else None,
                'message_count': contact['message_count'],
                'source': 'imessage'
            })
            matched += 1

    logger.info(f"  Matched {matched} iMessage contacts to names")

    # Combine with full Mac contacts list
    all_contacts = mac_contacts + enriched

    # Deduplicate by phone/email
    seen_phones = set()
    seen_emails = set()
    unique_contacts = []

    for c in all_contacts:
        phone = c.get('primary_phone', '')
        email = c.get('primary_email', '')

        if phone and phone in seen_phones:
            continue
        if email and email in seen_emails:
            continue

        if phone:
            seen_phones.add(phone)
        if email:
            seen_emails.add(email)

        unique_contacts.append(c)

    logger.info(f"  Total unique contacts: {len(unique_contacts)}")

    # Step 4: Sync to ATLAS
    logger.info("Syncing to ATLAS...")
    created, updated, skipped = sync_to_atlas(unique_contacts)
    logger.info(f"  Created: {created}, Updated: {updated}, Skipped: {skipped}")

    # Step 5: Save local export
    DATA_DIR.mkdir(exist_ok=True)
    export_path = DATA_DIR / "contacts_export.json"

    with open(export_path, 'w') as f:
        json.dump({
            'exported_at': datetime.now().isoformat(),
            'total_contacts': len(unique_contacts),
            'mac_contacts': len(mac_contacts),
            'imessage_matched': matched,
            'contacts': unique_contacts[:100]  # Save top 100 for reference
        }, f, indent=2)

    logger.info(f"Exported to {export_path}")

    # Summary
    logger.info("=" * 60)
    logger.info("SYNC COMPLETE")
    logger.info(f"  Mac Contacts: {len(mac_contacts)}")
    logger.info(f"  iMessage Matched: {matched}")
    logger.info(f"  ATLAS Created: {created}")
    logger.info(f"  ATLAS Updated: {updated}")
    logger.info("=" * 60)

    return {
        'mac_contacts': len(mac_contacts),
        'imessage_matched': matched,
        'created': created,
        'updated': updated,
        'skipped': skipped
    }


if __name__ == '__main__':
    run_sync()
