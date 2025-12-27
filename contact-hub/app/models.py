"""
Extended Database Models for Contact Hub
Includes interactions, calendar events, email/message tracking
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, 
    Table, Index, UniqueConstraint, Enum as SQLEnum, Float, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

from .database import Base


# =============================================================================
# Enums
# =============================================================================

class PhoneType(enum.Enum):
    MOBILE = "mobile"
    HOME = "home"
    WORK = "work"
    FAX = "fax"
    OTHER = "other"


class EmailType(enum.Enum):
    PERSONAL = "personal"
    WORK = "work"
    OTHER = "other"


class AddressType(enum.Enum):
    HOME = "home"
    WORK = "work"
    OTHER = "other"


class SyncSource(enum.Enum):
    LOCAL = "local"
    GOOGLE = "google"
    ICLOUD = "icloud"
    CARDDAV = "carddav"
    LINKEDIN = "linkedin"
    IMPORT = "import"


class InteractionType(enum.Enum):
    EMAIL_SENT = "email_sent"
    EMAIL_RECEIVED = "email_received"
    CALL_OUTGOING = "call_outgoing"
    CALL_INCOMING = "call_incoming"
    CALL_MISSED = "call_missed"
    SMS_SENT = "sms_sent"
    SMS_RECEIVED = "sms_received"
    IMESSAGE_SENT = "imessage_sent"
    IMESSAGE_RECEIVED = "imessage_received"
    MEETING = "meeting"
    IN_PERSON = "in_person"
    VIDEO_CALL = "video_call"
    SOCIAL_MEDIA = "social_media"
    NOTE = "note"
    TASK = "task"
    OTHER = "other"


class InteractionChannel(enum.Enum):
    EMAIL = "email"
    PHONE = "phone"
    SMS = "sms"
    IMESSAGE = "imessage"
    WHATSAPP = "whatsapp"
    SLACK = "slack"
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"
    TEAMS = "teams"
    IN_PERSON = "in_person"
    OTHER = "other"


class EventType(enum.Enum):
    MEETING = "meeting"
    CALL = "call"
    REMINDER = "reminder"
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    FOLLOW_UP = "follow_up"
    TASK = "task"
    OTHER = "other"


class EventStatus(enum.Enum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


# =============================================================================
# Association Tables
# =============================================================================

contact_tags = Table(
    'contact_tags',
    Base.metadata,
    Column('contact_id', Integer, ForeignKey('contacts.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)
)

event_contacts = Table(
    'event_contacts',
    Base.metadata,
    Column('event_id', Integer, ForeignKey('calendar_events.id', ondelete='CASCADE'), primary_key=True),
    Column('contact_id', Integer, ForeignKey('contacts.id', ondelete='CASCADE'), primary_key=True)
)

interaction_contacts = Table(
    'interaction_contacts',
    Base.metadata,
    Column('interaction_id', Integer, ForeignKey('interactions.id', ondelete='CASCADE'), primary_key=True),
    Column('contact_id', Integer, ForeignKey('contacts.id', ondelete='CASCADE'), primary_key=True)
)


# =============================================================================
# Main Contact Model
# =============================================================================

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    
    # Name fields
    prefix = Column(String(20))
    first_name = Column(String(100), index=True)
    middle_name = Column(String(100))
    last_name = Column(String(100), index=True)
    suffix = Column(String(20))
    nickname = Column(String(100))
    display_name = Column(String(255), index=True)
    
    # Company info
    company = Column(String(255), index=True)
    job_title = Column(String(255))
    department = Column(String(255))
    
    # Personal info
    birthday = Column(DateTime)
    anniversary = Column(DateTime)
    
    # Notes
    notes = Column(Text)
    
    # Photo
    photo_url = Column(String(500))
    photo_data = Column(Text)
    
    # Social profiles
    linkedin_url = Column(String(500))
    twitter_handle = Column(String(100))
    facebook_url = Column(String(500))
    instagram_handle = Column(String(100))
    website = Column(String(500))
    
    # Relationship tracking
    relationship_score = Column(Float, default=0.0)
    last_interaction_at = Column(DateTime)
    last_interaction_type = Column(SQLEnum(InteractionType))
    interaction_count = Column(Integer, default=0)
    
    # Contact frequency goals
    target_contact_frequency_days = Column(Integer)
    days_since_contact = Column(Integer)
    needs_attention = Column(Boolean, default=False)
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    is_starred = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    
    # Sync tracking
    source = Column(SQLEnum(SyncSource), default=SyncSource.LOCAL)
    external_id = Column(String(255))
    external_etag = Column(String(255))
    last_synced_at = Column(DateTime)
    sync_account_id = Column(Integer, ForeignKey('sync_accounts.id'))
    
    # Relationships
    emails = relationship("Email", back_populates="contact", cascade="all, delete-orphan")
    phones = relationship("Phone", back_populates="contact", cascade="all, delete-orphan")
    addresses = relationship("Address", back_populates="contact", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary=contact_tags, back_populates="contacts")
    sync_account = relationship("SyncAccount", back_populates="contacts")
    interactions = relationship("Interaction", secondary=interaction_contacts, back_populates="contacts")
    calendar_events = relationship("CalendarEvent", secondary=event_contacts, back_populates="contacts")
    email_threads = relationship("EmailThread", back_populates="contact")
    reminders = relationship("Reminder", back_populates="contact")
    
    __table_args__ = (
        Index('idx_contact_name', 'first_name', 'last_name'),
        Index('idx_contact_company', 'company'),
        Index('idx_contact_external', 'source', 'external_id'),
        Index('idx_contact_last_interaction', 'last_interaction_at'),
        Index('idx_contact_needs_attention', 'needs_attention'),
    )


class Email(Base):
    __tablename__ = "emails"
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    type = Column(SQLEnum(EmailType), default=EmailType.OTHER)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    contact = relationship("Contact", back_populates="emails")


class Phone(Base):
    __tablename__ = "phones"
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    number = Column(String(50), nullable=False)
    normalized = Column(String(20), index=True)
    type = Column(SQLEnum(PhoneType), default=PhoneType.OTHER)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    contact = relationship("Contact", back_populates="phones")


class Address(Base):
    __tablename__ = "addresses"
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    street1 = Column(String(255))
    street2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100))
    type = Column(SQLEnum(AddressType), default=AddressType.OTHER)
    is_primary = Column(Boolean, default=False)
    latitude = Column(Float)
    longitude = Column(Float)
    created_at = Column(DateTime, default=func.now())
    contact = relationship("Contact", back_populates="addresses")


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    color = Column(String(7))
    description = Column(String(255))
    parent_id = Column(Integer, ForeignKey('tags.id'))
    created_at = Column(DateTime, default=func.now())
    contacts = relationship("Contact", secondary=contact_tags, back_populates="tags")
    children = relationship("Tag", backref="parent", remote_side=[id])


# =============================================================================
# Interaction Model - Core of relationship tracking
# =============================================================================

class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    
    type = Column(SQLEnum(InteractionType), nullable=False, index=True)
    channel = Column(SQLEnum(InteractionChannel), index=True)
    
    occurred_at = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer)
    
    subject = Column(String(500))
    summary = Column(Text)
    content = Column(Text)
    
    sentiment_score = Column(Float)
    sentiment_label = Column(String(20))
    
    location = Column(String(500))
    latitude = Column(Float)
    longitude = Column(Float)
    
    external_id = Column(String(255))
    external_url = Column(String(500))
    source = Column(SQLEnum(SyncSource))
    
    is_outgoing = Column(Boolean)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    is_private = Column(Boolean, default=False)
    
    attachments = Column(JSON)
    metadata = Column(JSON)
    
    contacts = relationship("Contact", secondary=interaction_contacts, back_populates="interactions")
    
    __table_args__ = (
        Index('idx_interaction_date', 'occurred_at'),
        Index('idx_interaction_type', 'type'),
        Index('idx_interaction_external', 'source', 'external_id'),
    )


# =============================================================================
# Email Thread Model
# =============================================================================

class EmailThread(Base):
    __tablename__ = "email_threads"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey('contacts.id', ondelete='CASCADE'))
    
    thread_id = Column(String(255), index=True)
    subject = Column(String(500))
    participants = Column(JSON)
    
    message_count = Column(Integer, default=0)
    last_message_at = Column(DateTime)
    last_message_from = Column(String(255))
    is_unread = Column(Boolean, default=False)
    snippet = Column(Text)
    labels = Column(JSON)
    
    source = Column(SQLEnum(SyncSource))
    sync_account_id = Column(Integer, ForeignKey('sync_accounts.id'))
    last_synced_at = Column(DateTime)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    contact = relationship("Contact", back_populates="email_threads")
    messages = relationship("EmailMessage", back_populates="thread", cascade="all, delete-orphan")


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey('email_threads.id', ondelete='CASCADE'))
    
    message_id = Column(String(255), unique=True, index=True)
    
    from_email = Column(String(255))
    from_name = Column(String(255))
    to_emails = Column(JSON)
    cc_emails = Column(JSON)
    bcc_emails = Column(JSON)
    
    subject = Column(String(500))
    body_text = Column(Text)
    body_html = Column(Text)
    snippet = Column(Text)
    
    sent_at = Column(DateTime, index=True)
    received_at = Column(DateTime)
    
    is_read = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)
    is_draft = Column(Boolean, default=False)
    is_sent = Column(Boolean, default=False)
    
    attachments = Column(JSON)
    labels = Column(JSON)
    
    created_at = Column(DateTime, default=func.now())
    
    thread = relationship("EmailThread", back_populates="messages")


# =============================================================================
# Calendar Event Model
# =============================================================================

class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    
    title = Column(String(500), nullable=False)
    description = Column(Text)
    
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime)
    is_all_day = Column(Boolean, default=False)
    timezone = Column(String(50))
    
    location = Column(String(500))
    latitude = Column(Float)
    longitude = Column(Float)
    
    video_conference_url = Column(String(500))
    video_conference_type = Column(String(50))
    
    status = Column(SQLEnum(EventStatus), default=EventStatus.CONFIRMED)
    event_type = Column(SQLEnum(EventType), default=EventType.MEETING)
    
    is_recurring = Column(Boolean, default=False)
    recurrence_rule = Column(String(255))
    recurring_event_id = Column(String(255))
    
    reminders = Column(JSON)
    
    organizer_email = Column(String(255))
    organizer_name = Column(String(255))
    is_organizer = Column(Boolean, default=False)
    my_response = Column(String(20))
    
    external_id = Column(String(255), index=True)
    external_url = Column(String(500))
    source = Column(SQLEnum(SyncSource))
    sync_account_id = Column(Integer, ForeignKey('sync_accounts.id'))
    etag = Column(String(255))
    last_synced_at = Column(DateTime)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    meeting_notes = Column(Text)
    action_items = Column(JSON)
    
    contacts = relationship("Contact", secondary=event_contacts, back_populates="calendar_events")
    
    __table_args__ = (
        Index('idx_event_start', 'start_time'),
        Index('idx_event_external', 'source', 'external_id'),
    )


# =============================================================================
# Reminder Model
# =============================================================================

class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey('contacts.id', ondelete='CASCADE'))
    
    title = Column(String(500), nullable=False)
    description = Column(Text)
    
    due_at = Column(DateTime, nullable=False, index=True)
    
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime)
    is_snoozed = Column(Boolean, default=False)
    snoozed_until = Column(DateTime)
    
    is_recurring = Column(Boolean, default=False)
    recurrence_rule = Column(String(255))
    
    priority = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    contact = relationship("Contact", back_populates="reminders")


# =============================================================================
# Sync Account Model
# =============================================================================

class SyncAccount(Base):
    __tablename__ = "sync_accounts"

    id = Column(Integer, primary_key=True, index=True)
    
    name = Column(String(255), nullable=False)
    source = Column(SQLEnum(SyncSource), nullable=False)
    
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expiry = Column(DateTime)
    
    account_email = Column(String(255))
    account_id = Column(String(255))
    
    sync_contacts = Column(Boolean, default=True)
    sync_calendar = Column(Boolean, default=True)
    sync_email = Column(Boolean, default=True)
    
    is_enabled = Column(Boolean, default=True)
    sync_direction = Column(String(20), default="bidirectional")
    last_sync_at = Column(DateTime)
    last_sync_token = Column(String(255))
    
    calendar_id = Column(String(255))
    calendar_sync_token = Column(String(255))
    
    email_sync_from = Column(DateTime)
    email_history_id = Column(String(255))
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    contacts = relationship("Contact", back_populates="sync_account")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    sync_account_id = Column(Integer, ForeignKey('sync_accounts.id'))
    sync_type = Column(String(50))
    started_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime)
    status = Column(String(20))
    contacts_pulled = Column(Integer, default=0)
    contacts_pushed = Column(Integer, default=0)
    events_synced = Column(Integer, default=0)
    emails_synced = Column(Integer, default=0)
    interactions_created = Column(Integer, default=0)
    conflicts = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    error_message = Column(Text)
    details = Column(Text)


class MergeHistory(Base):
    __tablename__ = "merge_history"

    id = Column(Integer, primary_key=True, index=True)
    primary_contact_id = Column(Integer, ForeignKey('contacts.id'))
    merged_contact_ids = Column(Text)
    merged_at = Column(DateTime, default=func.now())
    merged_by = Column(String(100))
    original_data = Column(Text)


class ActivityFeed(Base):
    __tablename__ = "activity_feed"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey('contacts.id', ondelete='CASCADE'), index=True)
    activity_type = Column(String(50), index=True)
    reference_type = Column(String(50))
    reference_id = Column(Integer)
    title = Column(String(500))
    summary = Column(Text)
    icon = Column(String(50))
    color = Column(String(20))
    occurred_at = Column(DateTime, index=True)
    is_outgoing = Column(Boolean)
    metadata = Column(JSON)
    created_at = Column(DateTime, default=func.now())
    
    __table_args__ = (
        Index('idx_activity_contact_date', 'contact_id', 'occurred_at'),
    )
