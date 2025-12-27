"""
Interaction Tracking Module
Log calls, meetings, in-person interactions, and get activity timeline
"""

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func, desc
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from . import models, schemas


def log_interaction(
    db: Session,
    contact_ids: List[int],
    interaction_type: models.InteractionType,
    occurred_at: datetime,
    subject: Optional[str] = None,
    summary: Optional[str] = None,
    content: Optional[str] = None,
    channel: Optional[models.InteractionChannel] = None,
    duration_minutes: Optional[int] = None,
    location: Optional[str] = None,
    is_outgoing: bool = True,
    metadata: Optional[Dict] = None,
) -> models.Interaction:
    """Log a manual interaction with one or more contacts"""
    
    interaction = models.Interaction(
        type=interaction_type,
        channel=channel,
        occurred_at=occurred_at,
        duration_minutes=duration_minutes,
        subject=subject,
        summary=summary,
        content=content,
        location=location,
        is_outgoing=is_outgoing,
        source=models.SyncSource.LOCAL,
        metadata=metadata,
    )
    
    db.add(interaction)
    db.flush()
    
    # Link to contacts and update their stats
    for contact_id in contact_ids:
        contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
        if contact:
            interaction.contacts.append(contact)
            
            # Update contact stats
            if not contact.last_interaction_at or occurred_at > contact.last_interaction_at:
                contact.last_interaction_at = occurred_at
                contact.last_interaction_type = interaction_type
            
            contact.interaction_count = (contact.interaction_count or 0) + 1
            
            # Update days since contact
            contact.days_since_contact = (datetime.utcnow() - occurred_at).days
            
            # Check if needs attention
            if contact.target_contact_frequency_days:
                contact.needs_attention = contact.days_since_contact > contact.target_contact_frequency_days
            
            # Add to activity feed
            add_to_activity_feed(
                db,
                contact_id=contact.id,
                activity_type='interaction',
                reference_type='interactions',
                reference_id=interaction.id,
                title=subject or f"{interaction_type.value} with {contact.display_name}",
                summary=summary,
                occurred_at=occurred_at,
                is_outgoing=is_outgoing,
            )
    
    db.commit()
    return interaction


def log_call(
    db: Session,
    contact_id: int,
    occurred_at: datetime,
    duration_minutes: Optional[int] = None,
    is_outgoing: bool = True,
    summary: Optional[str] = None,
    was_missed: bool = False,
) -> models.Interaction:
    """Log a phone call"""
    
    if was_missed:
        interaction_type = models.InteractionType.CALL_MISSED
    elif is_outgoing:
        interaction_type = models.InteractionType.CALL_OUTGOING
    else:
        interaction_type = models.InteractionType.CALL_INCOMING
    
    return log_interaction(
        db=db,
        contact_ids=[contact_id],
        interaction_type=interaction_type,
        occurred_at=occurred_at,
        channel=models.InteractionChannel.PHONE,
        duration_minutes=duration_minutes,
        is_outgoing=is_outgoing,
        summary=summary,
    )


def log_meeting(
    db: Session,
    contact_ids: List[int],
    occurred_at: datetime,
    subject: str,
    duration_minutes: Optional[int] = None,
    location: Optional[str] = None,
    summary: Optional[str] = None,
    notes: Optional[str] = None,
    is_video: bool = False,
    video_platform: Optional[str] = None,
) -> models.Interaction:
    """Log a meeting (in-person or video)"""
    
    if is_video:
        interaction_type = models.InteractionType.VIDEO_CALL
        channel_map = {
            'zoom': models.InteractionChannel.ZOOM,
            'meet': models.InteractionChannel.GOOGLE_MEET,
            'teams': models.InteractionChannel.TEAMS,
        }
        channel = channel_map.get((video_platform or '').lower(), models.InteractionChannel.OTHER)
    else:
        interaction_type = models.InteractionType.IN_PERSON
        channel = models.InteractionChannel.IN_PERSON
    
    return log_interaction(
        db=db,
        contact_ids=contact_ids,
        interaction_type=interaction_type,
        occurred_at=occurred_at,
        channel=channel,
        subject=subject,
        summary=summary,
        content=notes,
        duration_minutes=duration_minutes,
        location=location,
        is_outgoing=True,
    )


def log_message(
    db: Session,
    contact_id: int,
    occurred_at: datetime,
    content: str,
    is_outgoing: bool = True,
    channel: str = "sms",
) -> models.Interaction:
    """Log a text message (SMS, iMessage, WhatsApp, etc.)"""
    
    channel_map = {
        'sms': (models.InteractionType.SMS_SENT if is_outgoing else models.InteractionType.SMS_RECEIVED, models.InteractionChannel.SMS),
        'imessage': (models.InteractionType.IMESSAGE_SENT if is_outgoing else models.InteractionType.IMESSAGE_RECEIVED, models.InteractionChannel.IMESSAGE),
        'whatsapp': (models.InteractionType.SMS_SENT if is_outgoing else models.InteractionType.SMS_RECEIVED, models.InteractionChannel.WHATSAPP),
    }
    
    interaction_type, interaction_channel = channel_map.get(
        channel.lower(),
        (models.InteractionType.OTHER, models.InteractionChannel.OTHER)
    )
    
    return log_interaction(
        db=db,
        contact_ids=[contact_id],
        interaction_type=interaction_type,
        occurred_at=occurred_at,
        channel=interaction_channel,
        content=content,
        summary=content[:200] if len(content) > 200 else content,
        is_outgoing=is_outgoing,
    )


def add_note(
    db: Session,
    contact_id: int,
    content: str,
    subject: Optional[str] = None,
) -> models.Interaction:
    """Add a note about a contact"""
    
    return log_interaction(
        db=db,
        contact_ids=[contact_id],
        interaction_type=models.InteractionType.NOTE,
        occurred_at=datetime.utcnow(),
        subject=subject or "Note",
        content=content,
        summary=content[:200] if len(content) > 200 else content,
        is_outgoing=True,
    )


def add_to_activity_feed(
    db: Session,
    contact_id: int,
    activity_type: str,
    reference_type: str,
    reference_id: int,
    title: str,
    summary: Optional[str],
    occurred_at: datetime,
    is_outgoing: Optional[bool] = None,
    icon: Optional[str] = None,
    color: Optional[str] = None,
    metadata: Optional[Dict] = None,
):
    """Add an entry to the activity feed"""
    
    # Icon mapping
    icon_map = {
        'interaction': '💬',
        'email': '📧',
        'call': '📞',
        'meeting': '📅',
        'note': '📝',
    }
    
    feed_entry = models.ActivityFeed(
        contact_id=contact_id,
        activity_type=activity_type,
        reference_type=reference_type,
        reference_id=reference_id,
        title=title,
        summary=summary,
        icon=icon or icon_map.get(activity_type, '📌'),
        color=color,
        occurred_at=occurred_at,
        is_outgoing=is_outgoing,
        metadata=metadata,
    )
    
    db.add(feed_entry)


def get_activity_timeline(
    db: Session,
    contact_id: int,
    limit: int = 50,
    before: Optional[datetime] = None,
    interaction_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Get activity timeline for a contact"""
    
    query = db.query(models.ActivityFeed).filter(
        models.ActivityFeed.contact_id == contact_id
    )
    
    if before:
        query = query.filter(models.ActivityFeed.occurred_at < before)
    
    if interaction_types:
        query = query.filter(models.ActivityFeed.activity_type.in_(interaction_types))
    
    entries = query.order_by(desc(models.ActivityFeed.occurred_at)).limit(limit).all()
    
    return [
        {
            "id": e.id,
            "type": e.activity_type,
            "title": e.title,
            "summary": e.summary,
            "icon": e.icon,
            "color": e.color,
            "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            "is_outgoing": e.is_outgoing,
            "metadata": e.metadata,
        }
        for e in entries
    ]


def get_interactions(
    db: Session,
    contact_id: Optional[int] = None,
    interaction_type: Optional[models.InteractionType] = None,
    channel: Optional[models.InteractionChannel] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = 50,
) -> List[models.Interaction]:
    """Get interactions with optional filters"""
    
    query = db.query(models.Interaction).options(
        joinedload(models.Interaction.contacts)
    )
    
    if contact_id:
        query = query.filter(
            models.Interaction.contacts.any(models.Contact.id == contact_id)
        )
    
    if interaction_type:
        query = query.filter(models.Interaction.type == interaction_type)
    
    if channel:
        query = query.filter(models.Interaction.channel == channel)
    
    if from_date:
        query = query.filter(models.Interaction.occurred_at >= from_date)
    
    if to_date:
        query = query.filter(models.Interaction.occurred_at <= to_date)
    
    return query.order_by(desc(models.Interaction.occurred_at)).limit(limit).all()


def get_contact_stats(db: Session, contact_id: int) -> Dict[str, Any]:
    """Get interaction statistics for a contact"""
    
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not contact:
        return {}
    
    # Count by type
    type_counts = db.query(
        models.Interaction.type,
        func.count(models.Interaction.id)
    ).filter(
        models.Interaction.contacts.any(models.Contact.id == contact_id)
    ).group_by(models.Interaction.type).all()
    
    # Count by channel
    channel_counts = db.query(
        models.Interaction.channel,
        func.count(models.Interaction.id)
    ).filter(
        models.Interaction.contacts.any(models.Contact.id == contact_id)
    ).group_by(models.Interaction.channel).all()
    
    # First and last interaction
    first_interaction = db.query(models.Interaction).filter(
        models.Interaction.contacts.any(models.Contact.id == contact_id)
    ).order_by(models.Interaction.occurred_at).first()
    
    last_interaction = db.query(models.Interaction).filter(
        models.Interaction.contacts.any(models.Contact.id == contact_id)
    ).order_by(desc(models.Interaction.occurred_at)).first()
    
    # Interactions per month (last 12 months)
    twelve_months_ago = datetime.utcnow() - timedelta(days=365)
    monthly_counts = db.query(
        func.date_format(models.Interaction.occurred_at, '%Y-%m').label('month'),
        func.count(models.Interaction.id)
    ).filter(
        models.Interaction.contacts.any(models.Contact.id == contact_id),
        models.Interaction.occurred_at >= twelve_months_ago
    ).group_by('month').all()
    
    return {
        "total_interactions": contact.interaction_count or 0,
        "last_interaction_at": contact.last_interaction_at.isoformat() if contact.last_interaction_at else None,
        "last_interaction_type": contact.last_interaction_type.value if contact.last_interaction_type else None,
        "days_since_contact": contact.days_since_contact,
        "needs_attention": contact.needs_attention,
        "by_type": {t.value: c for t, c in type_counts},
        "by_channel": {c.value if c else 'unknown': cnt for c, cnt in channel_counts},
        "first_interaction_at": first_interaction.occurred_at.isoformat() if first_interaction else None,
        "monthly_activity": {m: c for m, c in monthly_counts},
    }


def get_contacts_needing_attention(db: Session, limit: int = 20) -> List[models.Contact]:
    """Get contacts that need attention based on contact frequency goals"""
    
    # Update days_since_contact for all contacts
    db.execute("""
        UPDATE contacts 
        SET days_since_contact = DATEDIFF(NOW(), last_interaction_at)
        WHERE last_interaction_at IS NOT NULL
    """)
    
    # Update needs_attention flag
    db.execute("""
        UPDATE contacts 
        SET needs_attention = (days_since_contact > target_contact_frequency_days)
        WHERE target_contact_frequency_days IS NOT NULL
    """)
    
    db.commit()
    
    return db.query(models.Contact).filter(
        models.Contact.needs_attention == True,
        models.Contact.is_archived == False,
    ).order_by(
        desc(models.Contact.days_since_contact)
    ).limit(limit).all()


def set_contact_frequency(
    db: Session,
    contact_id: int,
    frequency_days: int
) -> models.Contact:
    """Set how often you want to contact someone"""
    
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not contact:
        return None
    
    contact.target_contact_frequency_days = frequency_days
    
    # Update needs_attention
    if contact.days_since_contact:
        contact.needs_attention = contact.days_since_contact > frequency_days
    
    db.commit()
    return contact
