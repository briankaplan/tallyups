"""
CRUD Operations for Contact Hub
"""

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func
from typing import Optional, List, Dict, Any
import phonenumbers
from fuzzywuzzy import fuzz
import csv
import io
import vobject
from datetime import datetime
import json

from . import models, schemas


def normalize_phone(number: str, region: str = "US") -> Optional[str]:
    """Normalize phone number to E.164 format"""
    try:
        parsed = phonenumbers.parse(number, region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except:
        pass
    return None


# =============================================================================
# Contact CRUD
# =============================================================================

def create_contact(db: Session, contact: schemas.ContactCreate) -> models.Contact:
    """Create a new contact"""
    
    # Build display name if not provided
    display_name = contact.display_name
    if not display_name:
        parts = [p for p in [contact.first_name, contact.last_name] if p]
        display_name = " ".join(parts) if parts else contact.company
    
    db_contact = models.Contact(
        prefix=contact.prefix,
        first_name=contact.first_name,
        middle_name=contact.middle_name,
        last_name=contact.last_name,
        suffix=contact.suffix,
        nickname=contact.nickname,
        display_name=display_name,
        company=contact.company,
        job_title=contact.job_title,
        department=contact.department,
        birthday=contact.birthday,
        anniversary=contact.anniversary,
        notes=contact.notes,
        photo_url=contact.photo_url,
        linkedin_url=contact.linkedin_url,
        twitter_handle=contact.twitter_handle,
        facebook_url=contact.facebook_url,
        instagram_handle=contact.instagram_handle,
        website=contact.website,
        is_starred=contact.is_starred,
        target_contact_frequency_days=contact.target_contact_frequency_days,
        source=models.SyncSource.LOCAL,
    )
    
    db.add(db_contact)
    db.flush()
    
    # Add emails
    for email_data in contact.emails:
        email = models.Email(
            contact_id=db_contact.id,
            email=email_data.email.lower(),
            type=models.EmailType(email_data.type.value),
            is_primary=email_data.is_primary,
        )
        db.add(email)
    
    # Add phones
    for phone_data in contact.phones:
        phone = models.Phone(
            contact_id=db_contact.id,
            number=phone_data.number,
            normalized=normalize_phone(phone_data.number),
            type=models.PhoneType(phone_data.type.value),
            is_primary=phone_data.is_primary,
        )
        db.add(phone)
    
    # Add addresses
    for addr_data in contact.addresses:
        address = models.Address(
            contact_id=db_contact.id,
            street1=addr_data.street1,
            street2=addr_data.street2,
            city=addr_data.city,
            state=addr_data.state,
            postal_code=addr_data.postal_code,
            country=addr_data.country,
            type=models.AddressType(addr_data.type.value),
            is_primary=addr_data.is_primary,
        )
        db.add(address)
    
    # Add tags
    for tag_id in contact.tag_ids:
        tag = db.query(models.Tag).filter(models.Tag.id == tag_id).first()
        if tag:
            db_contact.tags.append(tag)
    
    db.commit()
    db.refresh(db_contact)
    
    return db_contact


def get_contact(db: Session, contact_id: int) -> Optional[models.Contact]:
    """Get a contact by ID"""
    return db.query(models.Contact).options(
        joinedload(models.Contact.emails),
        joinedload(models.Contact.phones),
        joinedload(models.Contact.addresses),
        joinedload(models.Contact.tags),
    ).filter(models.Contact.id == contact_id).first()


def get_contacts(
    db: Session,
    search: Optional[str] = None,
    tag_id: Optional[int] = None,
    needs_attention: Optional[bool] = None,
    is_starred: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Get contacts with filtering and pagination"""
    
    query = db.query(models.Contact).options(
        joinedload(models.Contact.emails),
        joinedload(models.Contact.phones),
        joinedload(models.Contact.addresses),
        joinedload(models.Contact.tags),
    ).filter(models.Contact.is_archived == False)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Contact.first_name.ilike(search_term),
                models.Contact.last_name.ilike(search_term),
                models.Contact.display_name.ilike(search_term),
                models.Contact.company.ilike(search_term),
                models.Contact.emails.any(models.Email.email.ilike(search_term)),
                models.Contact.phones.any(models.Phone.number.ilike(search_term)),
            )
        )
    
    if tag_id:
        query = query.filter(models.Contact.tags.any(models.Tag.id == tag_id))
    
    if needs_attention is not None:
        query = query.filter(models.Contact.needs_attention == needs_attention)
    
    if is_starred is not None:
        query = query.filter(models.Contact.is_starred == is_starred)
    
    total = query.count()
    
    contacts = query.order_by(
        models.Contact.is_starred.desc(),
        models.Contact.display_name,
    ).offset((page - 1) * page_size).limit(page_size).all()
    
    return {
        "items": contacts,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def search_contacts(db: Session, query: str, limit: int = 20) -> List[models.Contact]:
    """Quick search contacts"""
    search_term = f"%{query}%"
    
    return db.query(models.Contact).options(
        joinedload(models.Contact.emails),
        joinedload(models.Contact.phones),
    ).filter(
        models.Contact.is_archived == False,
        or_(
            models.Contact.first_name.ilike(search_term),
            models.Contact.last_name.ilike(search_term),
            models.Contact.display_name.ilike(search_term),
            models.Contact.company.ilike(search_term),
            models.Contact.emails.any(models.Email.email.ilike(search_term)),
        )
    ).limit(limit).all()


def update_contact(
    db: Session,
    contact_id: int,
    contact: schemas.ContactUpdate,
) -> Optional[models.Contact]:
    """Update a contact"""
    
    db_contact = db.query(models.Contact).filter(
        models.Contact.id == contact_id
    ).first()
    
    if not db_contact:
        return None
    
    update_data = contact.model_dump(exclude_unset=True)
    
    # Handle nested objects separately
    emails_data = update_data.pop('emails', None)
    phones_data = update_data.pop('phones', None)
    addresses_data = update_data.pop('addresses', None)
    tag_ids = update_data.pop('tag_ids', None)
    
    # Update scalar fields
    for key, value in update_data.items():
        setattr(db_contact, key, value)
    
    # Update emails if provided
    if emails_data is not None:
        db.query(models.Email).filter(models.Email.contact_id == contact_id).delete()
        for email_data in emails_data:
            email = models.Email(
                contact_id=contact_id,
                email=email_data.email.lower(),
                type=models.EmailType(email_data.type.value),
                is_primary=email_data.is_primary,
            )
            db.add(email)
    
    # Update phones if provided
    if phones_data is not None:
        db.query(models.Phone).filter(models.Phone.contact_id == contact_id).delete()
        for phone_data in phones_data:
            phone = models.Phone(
                contact_id=contact_id,
                number=phone_data.number,
                normalized=normalize_phone(phone_data.number),
                type=models.PhoneType(phone_data.type.value),
                is_primary=phone_data.is_primary,
            )
            db.add(phone)
    
    # Update addresses if provided
    if addresses_data is not None:
        db.query(models.Address).filter(models.Address.contact_id == contact_id).delete()
        for addr_data in addresses_data:
            address = models.Address(
                contact_id=contact_id,
                street1=addr_data.street1,
                street2=addr_data.street2,
                city=addr_data.city,
                state=addr_data.state,
                postal_code=addr_data.postal_code,
                country=addr_data.country,
                type=models.AddressType(addr_data.type.value),
                is_primary=addr_data.is_primary,
            )
            db.add(address)
    
    # Update tags if provided
    if tag_ids is not None:
        db_contact.tags = []
        for tag_id in tag_ids:
            tag = db.query(models.Tag).filter(models.Tag.id == tag_id).first()
            if tag:
                db_contact.tags.append(tag)
    
    db.commit()
    db.refresh(db_contact)
    
    return db_contact


def delete_contact(db: Session, contact_id: int) -> bool:
    """Delete a contact"""
    contact = db.query(models.Contact).filter(
        models.Contact.id == contact_id
    ).first()
    
    if not contact:
        return False
    
    db.delete(contact)
    db.commit()
    return True


# =============================================================================
# Tags
# =============================================================================

def get_tags(db: Session) -> List[models.Tag]:
    """Get all tags"""
    return db.query(models.Tag).all()


def create_tag(db: Session, tag: schemas.TagCreate) -> models.Tag:
    """Create a new tag"""
    db_tag = models.Tag(
        name=tag.name,
        color=tag.color,
        description=tag.description,
    )
    db.add(db_tag)
    db.commit()
    db.refresh(db_tag)
    return db_tag


def add_tag_to_contact(db: Session, contact_id: int, tag_id: int) -> bool:
    """Add a tag to a contact"""
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    tag = db.query(models.Tag).filter(models.Tag.id == tag_id).first()
    
    if not contact or not tag:
        return False
    
    if tag not in contact.tags:
        contact.tags.append(tag)
        db.commit()
    
    return True


def remove_tag_from_contact(db: Session, contact_id: int, tag_id: int) -> bool:
    """Remove a tag from a contact"""
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    tag = db.query(models.Tag).filter(models.Tag.id == tag_id).first()
    
    if not contact or not tag:
        return False
    
    if tag in contact.tags:
        contact.tags.remove(tag)
        db.commit()
    
    return True


# =============================================================================
# Deduplication
# =============================================================================

def find_duplicates(db: Session) -> List[Dict[str, Any]]:
    """Find potential duplicate contacts"""
    
    contacts = db.query(models.Contact).options(
        joinedload(models.Contact.emails),
        joinedload(models.Contact.phones),
    ).filter(models.Contact.is_archived == False).all()
    
    duplicates = []
    checked_pairs = set()
    
    for i, c1 in enumerate(contacts):
        for c2 in contacts[i+1:]:
            pair_key = (min(c1.id, c2.id), max(c1.id, c2.id))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            
            match_reason = None
            confidence = 0.0
            
            # Check email match
            c1_emails = {e.email.lower() for e in c1.emails}
            c2_emails = {e.email.lower() for e in c2.emails}
            if c1_emails & c2_emails:
                match_reason = "Same email address"
                confidence = 1.0
            
            # Check phone match
            if not match_reason:
                c1_phones = {p.normalized for p in c1.phones if p.normalized}
                c2_phones = {p.normalized for p in c2.phones if p.normalized}
                if c1_phones & c2_phones:
                    match_reason = "Same phone number"
                    confidence = 1.0
            
            # Check fuzzy name match
            if not match_reason and c1.display_name and c2.display_name:
                name_ratio = fuzz.ratio(
                    c1.display_name.lower(),
                    c2.display_name.lower()
                )
                if name_ratio >= 85:
                    match_reason = f"Similar names ({name_ratio}% match)"
                    confidence = name_ratio / 100.0
            
            if match_reason:
                existing_group = None
                for group in duplicates:
                    group_ids = {c.id for c in group['contacts']}
                    if c1.id in group_ids or c2.id in group_ids:
                        existing_group = group
                        break
                
                if existing_group:
                    if c1 not in existing_group['contacts']:
                        existing_group['contacts'].append(c1)
                    if c2 not in existing_group['contacts']:
                        existing_group['contacts'].append(c2)
                else:
                    duplicates.append({
                        'contacts': [c1, c2],
                        'match_reason': match_reason,
                        'confidence': confidence,
                    })
    
    return duplicates


def merge_contacts(
    db: Session,
    contact_ids: List[int],
    primary_contact_id: int,
) -> Optional[models.Contact]:
    """Merge multiple contacts into one"""
    
    if primary_contact_id not in contact_ids:
        return None
    
    contacts = db.query(models.Contact).options(
        joinedload(models.Contact.emails),
        joinedload(models.Contact.phones),
        joinedload(models.Contact.addresses),
        joinedload(models.Contact.tags),
    ).filter(models.Contact.id.in_(contact_ids)).all()
    
    if len(contacts) < 2:
        return None
    
    primary = next((c for c in contacts if c.id == primary_contact_id), None)
    if not primary:
        return None
    
    others = [c for c in contacts if c.id != primary_contact_id]
    
    # Store original data for potential undo
    original_data = {
        'primary': primary_contact_id,
        'merged': [c.id for c in others],
        'contacts': [
            {
                'id': c.id,
                'display_name': c.display_name,
                'emails': [e.email for e in c.emails],
                'phones': [p.number for p in c.phones],
            }
            for c in contacts
        ]
    }
    
    # Merge data from others into primary
    for other in others:
        # Merge emails
        existing_emails = {e.email.lower() for e in primary.emails}
        for email in other.emails:
            if email.email.lower() not in existing_emails:
                new_email = models.Email(
                    contact_id=primary.id,
                    email=email.email,
                    type=email.type,
                    is_primary=False,
                )
                db.add(new_email)
        
        # Merge phones
        existing_phones = {p.normalized for p in primary.phones if p.normalized}
        for phone in other.phones:
            if phone.normalized not in existing_phones:
                new_phone = models.Phone(
                    contact_id=primary.id,
                    number=phone.number,
                    normalized=phone.normalized,
                    type=phone.type,
                    is_primary=False,
                )
                db.add(new_phone)
        
        # Merge addresses
        for addr in other.addresses:
            new_addr = models.Address(
                contact_id=primary.id,
                street1=addr.street1,
                street2=addr.street2,
                city=addr.city,
                state=addr.state,
                postal_code=addr.postal_code,
                country=addr.country,
                type=addr.type,
                is_primary=False,
            )
            db.add(new_addr)
        
        # Merge tags
        for tag in other.tags:
            if tag not in primary.tags:
                primary.tags.append(tag)
        
        # Fill in missing fields
        if not primary.company and other.company:
            primary.company = other.company
        if not primary.job_title and other.job_title:
            primary.job_title = other.job_title
        if not primary.notes and other.notes:
            primary.notes = other.notes
        elif other.notes:
            primary.notes = f"{primary.notes}\n\n---\n\n{other.notes}"
        if not primary.birthday and other.birthday:
            primary.birthday = other.birthday
        if not primary.linkedin_url and other.linkedin_url:
            primary.linkedin_url = other.linkedin_url
        
        # Update interaction count
        primary.interaction_count = (primary.interaction_count or 0) + (other.interaction_count or 0)
        
        # Delete the merged contact
        db.delete(other)
    
    # Record merge history
    merge_record = models.MergeHistory(
        primary_contact_id=primary.id,
        merged_contact_ids=",".join(str(c.id) for c in others),
        original_data=json.dumps(original_data),
    )
    db.add(merge_record)
    
    db.commit()
    db.refresh(primary)
    
    return primary


# =============================================================================
# Import/Export
# =============================================================================

def import_csv(db: Session, content: str) -> Dict[str, int]:
    """Import contacts from CSV"""
    
    result = {"imported": 0, "skipped": 0, "errors": 0, "duplicates": 0, "details": []}
    
    reader = csv.DictReader(io.StringIO(content))
    
    # Map common column names
    field_map = {
        'first name': 'first_name',
        'firstname': 'first_name',
        'first': 'first_name',
        'last name': 'last_name',
        'lastname': 'last_name',
        'last': 'last_name',
        'email': 'email',
        'e-mail': 'email',
        'email address': 'email',
        'phone': 'phone',
        'phone number': 'phone',
        'mobile': 'phone',
        'cell': 'phone',
        'company': 'company',
        'organization': 'company',
        'title': 'job_title',
        'job title': 'job_title',
        'notes': 'notes',
    }
    
    for row in reader:
        try:
            # Normalize column names
            normalized = {}
            for key, value in row.items():
                if key:
                    normalized_key = field_map.get(key.lower().strip(), key.lower().strip())
                    normalized[normalized_key] = value.strip() if value else None
            
            # Check for duplicate by email
            email = normalized.get('email')
            if email:
                existing = db.query(models.Email).filter(
                    models.Email.email == email.lower()
                ).first()
                if existing:
                    result["duplicates"] += 1
                    continue
            
            # Create contact
            contact = models.Contact(
                first_name=normalized.get('first_name'),
                last_name=normalized.get('last_name'),
                display_name=f"{normalized.get('first_name', '')} {normalized.get('last_name', '')}".strip() or normalized.get('company'),
                company=normalized.get('company'),
                job_title=normalized.get('job_title'),
                notes=normalized.get('notes'),
                source=models.SyncSource.IMPORT,
            )
            db.add(contact)
            db.flush()
            
            if email:
                db.add(models.Email(contact_id=contact.id, email=email.lower()))
            
            phone = normalized.get('phone')
            if phone:
                db.add(models.Phone(
                    contact_id=contact.id,
                    number=phone,
                    normalized=normalize_phone(phone),
                ))
            
            result["imported"] += 1
            
        except Exception as e:
            result["errors"] += 1
            result["details"].append(str(e))
    
    db.commit()
    return result


def import_vcard(db: Session, content: str) -> Dict[str, int]:
    """Import contacts from vCard"""
    
    result = {"imported": 0, "skipped": 0, "errors": 0, "duplicates": 0, "details": []}
    
    try:
        for vcard in vobject.readComponents(content):
            try:
                # Parse name
                first_name = None
                last_name = None
                
                if hasattr(vcard, 'n'):
                    first_name = vcard.n.value.given if vcard.n.value.given else None
                    last_name = vcard.n.value.family if vcard.n.value.family else None
                
                display_name = str(vcard.fn.value) if hasattr(vcard, 'fn') else None
                
                # Parse organization
                company = None
                if hasattr(vcard, 'org'):
                    org = vcard.org.value
                    company = org[0] if isinstance(org, list) else str(org)
                
                # Create contact
                contact = models.Contact(
                    first_name=first_name,
                    last_name=last_name,
                    display_name=display_name or f"{first_name or ''} {last_name or ''}".strip(),
                    company=company,
                    source=models.SyncSource.IMPORT,
                )
                db.add(contact)
                db.flush()
                
                # Parse emails
                if hasattr(vcard, 'email_list'):
                    for email in vcard.email_list:
                        db.add(models.Email(
                            contact_id=contact.id,
                            email=str(email.value).lower(),
                        ))
                
                # Parse phones
                if hasattr(vcard, 'tel_list'):
                    for tel in vcard.tel_list:
                        number = str(tel.value)
                        db.add(models.Phone(
                            contact_id=contact.id,
                            number=number,
                            normalized=normalize_phone(number),
                        ))
                
                result["imported"] += 1
                
            except Exception as e:
                result["errors"] += 1
                result["details"].append(str(e))
    
    except Exception as e:
        result["errors"] += 1
        result["details"].append(f"Failed to parse vCard: {str(e)}")
    
    db.commit()
    return result


def export_csv(
    db: Session,
    contact_ids: Optional[List[int]] = None,
    tag_id: Optional[int] = None,
) -> str:
    """Export contacts to CSV"""
    
    query = db.query(models.Contact).options(
        joinedload(models.Contact.emails),
        joinedload(models.Contact.phones),
        joinedload(models.Contact.addresses),
        joinedload(models.Contact.tags),
    )
    
    if contact_ids:
        query = query.filter(models.Contact.id.in_(contact_ids))
    
    if tag_id:
        query = query.filter(models.Contact.tags.any(models.Tag.id == tag_id))
    
    contacts = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = [
        'First Name', 'Last Name', 'Display Name', 'Company', 'Job Title',
        'Email 1', 'Email 2', 'Phone 1', 'Phone 2',
        'Street', 'City', 'State', 'Postal Code', 'Country',
        'Birthday', 'Notes', 'Tags', 'LinkedIn', 'Twitter',
        'Last Interaction', 'Interaction Count'
    ]
    writer.writerow(headers)
    
    for contact in contacts:
        emails = [e.email for e in contact.emails]
        phones = [p.number for p in contact.phones]
        primary_addr = next((a for a in contact.addresses if a.is_primary), 
                           contact.addresses[0] if contact.addresses else None)
        
        row = [
            contact.first_name or '',
            contact.last_name or '',
            contact.display_name or '',
            contact.company or '',
            contact.job_title or '',
            emails[0] if emails else '',
            emails[1] if len(emails) > 1 else '',
            phones[0] if phones else '',
            phones[1] if len(phones) > 1 else '',
            primary_addr.street1 if primary_addr else '',
            primary_addr.city if primary_addr else '',
            primary_addr.state if primary_addr else '',
            primary_addr.postal_code if primary_addr else '',
            primary_addr.country if primary_addr else '',
            contact.birthday.strftime('%Y-%m-%d') if contact.birthday else '',
            contact.notes or '',
            ', '.join(t.name for t in contact.tags),
            contact.linkedin_url or '',
            contact.twitter_handle or '',
            contact.last_interaction_at.isoformat() if contact.last_interaction_at else '',
            contact.interaction_count or 0,
        ]
        writer.writerow(row)
    
    return output.getvalue()


def export_vcard(
    db: Session,
    contact_ids: Optional[List[int]] = None,
    tag_id: Optional[int] = None,
) -> str:
    """Export contacts to vCard format"""
    
    query = db.query(models.Contact).options(
        joinedload(models.Contact.emails),
        joinedload(models.Contact.phones),
        joinedload(models.Contact.addresses),
    )
    
    if contact_ids:
        query = query.filter(models.Contact.id.in_(contact_ids))
    
    if tag_id:
        query = query.filter(models.Contact.tags.any(models.Tag.id == tag_id))
    
    contacts = query.all()
    
    vcards = []
    
    for contact in contacts:
        vcard = vobject.vCard()
        
        # Name
        vcard.add('n')
        vcard.n.value = vobject.vcard.Name(
            family=contact.last_name or '',
            given=contact.first_name or '',
        )
        
        # Full name
        vcard.add('fn')
        vcard.fn.value = contact.display_name or f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        
        # Organization
        if contact.company:
            vcard.add('org')
            vcard.org.value = [contact.company]
        
        # Title
        if contact.job_title:
            vcard.add('title')
            vcard.title.value = contact.job_title
        
        # Emails
        for email in contact.emails:
            e = vcard.add('email')
            e.value = email.email
            e.type_param = email.type.value.upper()
        
        # Phones
        for phone in contact.phones:
            t = vcard.add('tel')
            t.value = phone.number
            t.type_param = phone.type.value.upper()
        
        # Addresses
        for addr in contact.addresses:
            a = vcard.add('adr')
            a.value = vobject.vcard.Address(
                street=addr.street1 or '',
                city=addr.city or '',
                region=addr.state or '',
                code=addr.postal_code or '',
                country=addr.country or '',
            )
            a.type_param = addr.type.value.upper()
        
        # Birthday
        if contact.birthday:
            bday = vcard.add('bday')
            bday.value = contact.birthday.strftime('%Y-%m-%d')
        
        # Note
        if contact.notes:
            note = vcard.add('note')
            note.value = contact.notes
        
        # URL
        if contact.website:
            url = vcard.add('url')
            url.value = contact.website
        
        vcards.append(vcard.serialize())
    
    return '\n'.join(vcards)
