"""
Google Contacts Sync Engine
Two-way sync with Google People API
"""

import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from . import models, schemas, crud


# Google API scopes
SCOPES = ['https://www.googleapis.com/auth/contacts']


def get_google_service(sync_account: models.SyncAccount):
    """Get authenticated Google People API service"""
    
    creds = Credentials(
        token=sync_account.access_token,
        refresh_token=sync_account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    )
    
    # Refresh if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Update stored tokens
        sync_account.access_token = creds.token
        sync_account.token_expiry = creds.expiry
    
    return build('people', 'v1', credentials=creds)


def google_contact_to_local(person: Dict) -> schemas.ContactCreate:
    """Convert Google People API person to local contact schema"""
    
    # Names
    names = person.get('names', [{}])
    name = names[0] if names else {}
    
    # Emails
    emails = []
    for email in person.get('emailAddresses', []):
        email_type = email.get('type', 'other').lower()
        if email_type not in ['personal', 'work', 'other']:
            email_type = 'other'
        emails.append(schemas.EmailCreate(
            email=email.get('value', ''),
            type=schemas.EmailType(email_type),
            is_primary=email.get('metadata', {}).get('primary', False),
        ))
    
    # Phones
    phones = []
    for phone in person.get('phoneNumbers', []):
        phone_type = phone.get('type', 'other').lower()
        if phone_type not in ['mobile', 'home', 'work', 'fax', 'other']:
            phone_type = 'other'
        phones.append(schemas.PhoneCreate(
            number=phone.get('value', ''),
            type=schemas.PhoneType(phone_type),
            is_primary=phone.get('metadata', {}).get('primary', False),
        ))
    
    # Addresses
    addresses = []
    for addr in person.get('addresses', []):
        addr_type = addr.get('type', 'other').lower()
        if addr_type not in ['home', 'work', 'other']:
            addr_type = 'other'
        addresses.append(schemas.AddressCreate(
            street1=addr.get('streetAddress', ''),
            city=addr.get('city', ''),
            state=addr.get('region', ''),
            postal_code=addr.get('postalCode', ''),
            country=addr.get('country', ''),
            type=schemas.AddressType(addr_type),
        ))
    
    # Organization
    orgs = person.get('organizations', [{}])
    org = orgs[0] if orgs else {}
    
    # Birthday
    birthday = None
    birthdays = person.get('birthdays', [])
    if birthdays:
        bday = birthdays[0].get('date', {})
        if bday.get('year') and bday.get('month') and bday.get('day'):
            birthday = datetime(bday['year'], bday['month'], bday['day'])
    
    # URLs
    urls = {url.get('type', '').lower(): url.get('value', '') for url in person.get('urls', [])}
    
    return schemas.ContactCreate(
        first_name=name.get('givenName', ''),
        middle_name=name.get('middleName', ''),
        last_name=name.get('familyName', ''),
        nickname=person.get('nicknames', [{}])[0].get('value', '') if person.get('nicknames') else None,
        company=org.get('name', ''),
        job_title=org.get('title', ''),
        department=org.get('department', ''),
        birthday=birthday,
        notes=person.get('biographies', [{}])[0].get('value', '') if person.get('biographies') else None,
        website=urls.get('homepage', '') or urls.get('blog', ''),
        linkedin_url=urls.get('linkedin', ''),
        emails=emails,
        phones=phones,
        addresses=addresses,
    )


def local_contact_to_google(contact: models.Contact) -> Dict:
    """Convert local contact to Google People API format"""
    
    person = {
        'names': [{
            'givenName': contact.first_name or '',
            'middleName': contact.middle_name or '',
            'familyName': contact.last_name or '',
        }],
        'emailAddresses': [],
        'phoneNumbers': [],
        'addresses': [],
        'organizations': [],
        'urls': [],
    }
    
    # Emails
    for email in contact.emails:
        person['emailAddresses'].append({
            'value': email.email,
            'type': email.type.value if email.type else 'other',
        })
    
    # Phones
    for phone in contact.phones:
        person['phoneNumbers'].append({
            'value': phone.number,
            'type': phone.type.value if phone.type else 'other',
        })
    
    # Addresses
    for addr in contact.addresses:
        person['addresses'].append({
            'streetAddress': addr.street1 or '',
            'city': addr.city or '',
            'region': addr.state or '',
            'postalCode': addr.postal_code or '',
            'country': addr.country or '',
            'type': addr.type.value if addr.type else 'other',
        })
    
    # Organization
    if contact.company or contact.job_title:
        person['organizations'].append({
            'name': contact.company or '',
            'title': contact.job_title or '',
            'department': contact.department or '',
        })
    
    # URLs
    if contact.website:
        person['urls'].append({'value': contact.website, 'type': 'homepage'})
    if contact.linkedin_url:
        person['urls'].append({'value': contact.linkedin_url, 'type': 'linkedin'})
    
    # Notes
    if contact.notes:
        person['biographies'] = [{'value': contact.notes}]
    
    # Birthday
    if contact.birthday:
        person['birthdays'] = [{
            'date': {
                'year': contact.birthday.year,
                'month': contact.birthday.month,
                'day': contact.birthday.day,
            }
        }]
    
    return person


def pull_from_google(
    db: Session,
    sync_account: models.SyncAccount,
    service
) -> Dict[str, int]:
    """Pull contacts from Google to local database"""
    
    result = {"pulled": 0, "updated": 0, "skipped": 0}
    
    # Build request
    request = service.people().connections().list(
        resourceName='people/me',
        pageSize=1000,
        personFields='names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,biographies,urls,nicknames,metadata',
        requestSyncToken=True,
    )
    
    # Use sync token if available for incremental sync
    if sync_account.last_sync_token:
        request = service.people().connections().list(
            resourceName='people/me',
            pageSize=1000,
            personFields='names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,biographies,urls,nicknames,metadata',
            syncToken=sync_account.last_sync_token,
        )
    
    while request:
        response = request.execute()
        
        for person in response.get('connections', []):
            resource_name = person.get('resourceName', '')
            etag = person.get('etag', '')
            
            # Check if contact exists locally
            existing = db.query(models.Contact).filter(
                models.Contact.external_id == resource_name,
                models.Contact.sync_account_id == sync_account.id,
            ).first()
            
            if existing:
                # Check if updated
                if existing.external_etag != etag:
                    # Update local contact
                    contact_data = google_contact_to_local(person)
                    crud.update_contact(db, existing.id, schemas.ContactUpdate(**contact_data.model_dump()))
                    existing.external_etag = etag
                    existing.last_synced_at = datetime.utcnow()
                    result["updated"] += 1
                else:
                    result["skipped"] += 1
            else:
                # Create new local contact
                contact_data = google_contact_to_local(person)
                new_contact = crud.create_contact(db, contact_data)
                new_contact.source = models.SyncSource.GOOGLE
                new_contact.external_id = resource_name
                new_contact.external_etag = etag
                new_contact.sync_account_id = sync_account.id
                new_contact.last_synced_at = datetime.utcnow()
                result["pulled"] += 1
        
        # Handle pagination
        if 'nextPageToken' in response:
            request = service.people().connections().list(
                resourceName='people/me',
                pageSize=1000,
                personFields='names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,biographies,urls,nicknames,metadata',
                pageToken=response['nextPageToken'],
            )
        else:
            request = None
        
        # Save sync token
        if 'nextSyncToken' in response:
            sync_account.last_sync_token = response['nextSyncToken']
    
    db.commit()
    return result


def push_to_google(
    db: Session,
    sync_account: models.SyncAccount,
    service
) -> Dict[str, int]:
    """Push local contacts to Google"""
    
    result = {"pushed": 0, "updated": 0, "errors": 0}
    
    # Find contacts that need syncing
    # Either new (no external_id) or updated since last sync
    contacts_to_push = db.query(models.Contact).filter(
        models.Contact.sync_account_id == sync_account.id,
        models.Contact.source == models.SyncSource.LOCAL,
    ).all()
    
    contacts_to_update = db.query(models.Contact).filter(
        models.Contact.sync_account_id == sync_account.id,
        models.Contact.external_id.isnot(None),
        models.Contact.updated_at > models.Contact.last_synced_at,
    ).all()
    
    # Create new contacts in Google
    for contact in contacts_to_push:
        try:
            person_data = local_contact_to_google(contact)
            
            created = service.people().createContact(
                body=person_data
            ).execute()
            
            contact.external_id = created.get('resourceName')
            contact.external_etag = created.get('etag')
            contact.source = models.SyncSource.GOOGLE
            contact.last_synced_at = datetime.utcnow()
            result["pushed"] += 1
            
        except Exception as e:
            print(f"Error pushing contact {contact.id}: {e}")
            result["errors"] += 1
    
    # Update existing contacts in Google
    for contact in contacts_to_update:
        try:
            person_data = local_contact_to_google(contact)
            person_data['etag'] = contact.external_etag
            
            updated = service.people().updateContact(
                resourceName=contact.external_id,
                updatePersonFields='names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,biographies,urls',
                body=person_data
            ).execute()
            
            contact.external_etag = updated.get('etag')
            contact.last_synced_at = datetime.utcnow()
            result["updated"] += 1
            
        except Exception as e:
            print(f"Error updating contact {contact.id}: {e}")
            result["errors"] += 1
    
    db.commit()
    return result


def sync(db: Session, account_id: Optional[int] = None) -> Dict[str, Any]:
    """Run full sync with Google"""
    
    result = {
        "pulled": 0,
        "pushed": 0,
        "conflicts": 0,
        "errors": [],
    }
    
    # Get sync accounts
    query = db.query(models.SyncAccount).filter(
        models.SyncAccount.source == models.SyncSource.GOOGLE,
        models.SyncAccount.is_enabled == True,
    )
    
    if account_id:
        query = query.filter(models.SyncAccount.id == account_id)
    
    accounts = query.all()
    
    for account in accounts:
        try:
            service = get_google_service(account)
            
            # Pull first
            if account.sync_direction in ['bidirectional', 'pull']:
                pull_result = pull_from_google(db, account, service)
                result["pulled"] += pull_result["pulled"] + pull_result["updated"]
            
            # Then push
            if account.sync_direction in ['bidirectional', 'push']:
                push_result = push_to_google(db, account, service)
                result["pushed"] += push_result["pushed"] + push_result["updated"]
            
            # Update last sync time
            account.last_sync_at = datetime.utcnow()
            
            # Log the sync
            log = models.SyncLog(
                sync_account_id=account.id,
                completed_at=datetime.utcnow(),
                status="success",
                contacts_pulled=pull_result.get("pulled", 0) if account.sync_direction in ['bidirectional', 'pull'] else 0,
                contacts_pushed=push_result.get("pushed", 0) if account.sync_direction in ['bidirectional', 'push'] else 0,
            )
            db.add(log)
            
        except Exception as e:
            result["errors"].append(f"Account {account.id}: {str(e)}")
            
            log = models.SyncLog(
                sync_account_id=account.id,
                completed_at=datetime.utcnow(),
                status="failed",
                error_message=str(e),
            )
            db.add(log)
    
    db.commit()
    return result
