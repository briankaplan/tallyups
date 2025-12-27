"""
Pydantic Schemas for Contact Hub API
Extended with interactions, calendar, and reminders
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# =============================================================================
# Enums for API
# =============================================================================

class PhoneTypeEnum(str, Enum):
    MOBILE = "mobile"
    HOME = "home"
    WORK = "work"
    FAX = "fax"
    OTHER = "other"


class EmailTypeEnum(str, Enum):
    PERSONAL = "personal"
    WORK = "work"
    OTHER = "other"


class AddressTypeEnum(str, Enum):
    HOME = "home"
    WORK = "work"
    OTHER = "other"


class InteractionTypeEnum(str, Enum):
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


class InteractionChannelEnum(str, Enum):
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


# =============================================================================
# Base Schemas
# =============================================================================

class EmailCreate(BaseModel):
    email: EmailStr
    type: EmailTypeEnum = EmailTypeEnum.OTHER
    is_primary: bool = False


class EmailResponse(BaseModel):
    id: int
    email: str
    type: str
    is_primary: bool

    class Config:
        from_attributes = True


class PhoneCreate(BaseModel):
    number: str
    type: PhoneTypeEnum = PhoneTypeEnum.OTHER
    is_primary: bool = False


class PhoneResponse(BaseModel):
    id: int
    number: str
    normalized: Optional[str]
    type: str
    is_primary: bool

    class Config:
        from_attributes = True


class AddressCreate(BaseModel):
    street1: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    type: AddressTypeEnum = AddressTypeEnum.OTHER
    is_primary: bool = False


class AddressResponse(BaseModel):
    id: int
    street1: Optional[str]
    street2: Optional[str]
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    type: str
    is_primary: bool

    class Config:
        from_attributes = True


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None
    description: Optional[str] = None


class TagResponse(BaseModel):
    id: int
    name: str
    color: Optional[str]
    description: Optional[str]

    class Config:
        from_attributes = True


# =============================================================================
# Contact Schemas
# =============================================================================

class ContactCreate(BaseModel):
    prefix: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    suffix: Optional[str] = None
    nickname: Optional[str] = None
    display_name: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    birthday: Optional[datetime] = None
    anniversary: Optional[datetime] = None
    notes: Optional[str] = None
    photo_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    facebook_url: Optional[str] = None
    instagram_handle: Optional[str] = None
    website: Optional[str] = None
    is_starred: bool = False
    target_contact_frequency_days: Optional[int] = None
    
    emails: List[EmailCreate] = []
    phones: List[PhoneCreate] = []
    addresses: List[AddressCreate] = []
    tag_ids: List[int] = []


class ContactUpdate(BaseModel):
    prefix: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    suffix: Optional[str] = None
    nickname: Optional[str] = None
    display_name: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    birthday: Optional[datetime] = None
    anniversary: Optional[datetime] = None
    notes: Optional[str] = None
    photo_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    facebook_url: Optional[str] = None
    instagram_handle: Optional[str] = None
    website: Optional[str] = None
    is_starred: Optional[bool] = None
    is_archived: Optional[bool] = None
    target_contact_frequency_days: Optional[int] = None
    
    emails: Optional[List[EmailCreate]] = None
    phones: Optional[List[PhoneCreate]] = None
    addresses: Optional[List[AddressCreate]] = None
    tag_ids: Optional[List[int]] = None


class ContactResponse(BaseModel):
    id: int
    prefix: Optional[str]
    first_name: Optional[str]
    middle_name: Optional[str]
    last_name: Optional[str]
    suffix: Optional[str]
    nickname: Optional[str]
    display_name: Optional[str]
    company: Optional[str]
    job_title: Optional[str]
    department: Optional[str]
    birthday: Optional[datetime]
    anniversary: Optional[datetime]
    notes: Optional[str]
    photo_url: Optional[str]
    linkedin_url: Optional[str]
    twitter_handle: Optional[str]
    facebook_url: Optional[str]
    instagram_handle: Optional[str]
    website: Optional[str]
    is_starred: bool
    is_archived: bool
    
    last_interaction_at: Optional[datetime]
    last_interaction_type: Optional[str]
    interaction_count: int
    days_since_contact: Optional[int]
    needs_attention: bool
    target_contact_frequency_days: Optional[int]
    
    created_at: datetime
    updated_at: datetime
    
    emails: List[EmailResponse] = []
    phones: List[PhoneResponse] = []
    addresses: List[AddressResponse] = []
    tags: List[TagResponse] = []

    class Config:
        from_attributes = True


class ContactListResponse(BaseModel):
    items: List[ContactResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ContactBrief(BaseModel):
    id: int
    display_name: Optional[str]
    company: Optional[str]
    primary_email: Optional[str]
    primary_phone: Optional[str]
    last_interaction_at: Optional[datetime]
    needs_attention: bool

    class Config:
        from_attributes = True


# =============================================================================
# Interaction Schemas
# =============================================================================

class InteractionCreate(BaseModel):
    contact_ids: List[int]
    type: InteractionTypeEnum
    channel: Optional[InteractionChannelEnum] = None
    occurred_at: datetime
    duration_minutes: Optional[int] = None
    subject: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    location: Optional[str] = None
    is_outgoing: bool = True
    metadata: Optional[Dict[str, Any]] = None


class InteractionResponse(BaseModel):
    id: int
    type: str
    channel: Optional[str]
    occurred_at: datetime
    duration_minutes: Optional[int]
    subject: Optional[str]
    summary: Optional[str]
    content: Optional[str]
    location: Optional[str]
    is_outgoing: Optional[bool]
    created_at: datetime
    contacts: List[ContactBrief] = []

    class Config:
        from_attributes = True


class LogCallRequest(BaseModel):
    contact_id: int
    occurred_at: datetime
    duration_minutes: Optional[int] = None
    is_outgoing: bool = True
    summary: Optional[str] = None
    was_missed: bool = False


class LogMeetingRequest(BaseModel):
    contact_ids: List[int]
    occurred_at: datetime
    subject: str
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    is_video: bool = False
    video_platform: Optional[str] = None


class LogMessageRequest(BaseModel):
    contact_id: int
    occurred_at: datetime
    content: str
    is_outgoing: bool = True
    channel: str = "sms"


class AddNoteRequest(BaseModel):
    contact_id: int
    content: str
    subject: Optional[str] = None


# =============================================================================
# Calendar Schemas
# =============================================================================

class CalendarEventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    is_all_day: bool
    location: Optional[str]
    video_conference_url: Optional[str]
    video_conference_type: Optional[str]
    status: str
    event_type: str
    is_organizer: bool
    my_response: Optional[str]
    external_url: Optional[str]
    meeting_notes: Optional[str]
    contacts: List[ContactBrief] = []

    class Config:
        from_attributes = True


class CalendarSyncRequest(BaseModel):
    account_id: int
    days_back: int = 30
    days_forward: int = 90


# =============================================================================
# Email Thread Schemas
# =============================================================================

class EmailMessageResponse(BaseModel):
    id: int
    from_email: str
    from_name: Optional[str]
    subject: Optional[str]
    snippet: Optional[str]
    sent_at: Optional[datetime]
    is_sent: bool
    is_read: bool

    class Config:
        from_attributes = True


class EmailThreadResponse(BaseModel):
    id: int
    thread_id: str
    subject: Optional[str]
    message_count: int
    last_message_at: Optional[datetime]
    is_unread: bool
    snippet: Optional[str]
    messages: List[EmailMessageResponse] = []

    class Config:
        from_attributes = True


# =============================================================================
# Reminder Schemas
# =============================================================================

class ReminderCreate(BaseModel):
    contact_id: int
    title: str
    description: Optional[str] = None
    due_at: datetime
    priority: int = 0
    recurrence_rule: Optional[str] = None


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    priority: Optional[int] = None


class ReminderResponse(BaseModel):
    id: int
    contact_id: Optional[int]
    title: str
    description: Optional[str]
    due_at: datetime
    priority: int
    is_completed: bool
    completed_at: Optional[datetime]
    is_snoozed: bool
    snoozed_until: Optional[datetime]
    is_recurring: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SnoozeRequest(BaseModel):
    hours: int = 0
    days: int = 0


class FollowUpRequest(BaseModel):
    contact_id: int
    days_from_now: int = 7
    title: Optional[str] = None


# =============================================================================
# Activity Timeline Schemas
# =============================================================================

class ActivityFeedItem(BaseModel):
    id: int
    type: str
    title: str
    summary: Optional[str]
    icon: Optional[str]
    color: Optional[str]
    occurred_at: datetime
    is_outgoing: Optional[bool]
    metadata: Optional[Dict[str, Any]]


class ContactStatsResponse(BaseModel):
    total_interactions: int
    last_interaction_at: Optional[str]
    last_interaction_type: Optional[str]
    days_since_contact: Optional[int]
    needs_attention: bool
    by_type: Dict[str, int]
    by_channel: Dict[str, int]
    first_interaction_at: Optional[str]
    monthly_activity: Dict[str, int]


# =============================================================================
# Sync Schemas
# =============================================================================

class SyncAccountCreate(BaseModel):
    name: str
    source: str
    sync_contacts: bool = True
    sync_calendar: bool = True
    sync_email: bool = True


class SyncAccountResponse(BaseModel):
    id: int
    name: str
    source: str
    account_email: Optional[str]
    is_enabled: bool
    sync_contacts: bool
    sync_calendar: bool
    sync_email: bool
    last_sync_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class SyncStatusResponse(BaseModel):
    account_id: int
    account_name: str
    contacts_synced: int
    events_synced: int
    emails_synced: int
    interactions_created: int
    errors: int
    last_sync: Optional[datetime]


class FullSyncRequest(BaseModel):
    account_id: int
    sync_contacts: bool = True
    sync_calendar: bool = True
    sync_email: bool = True


class FullSyncResponse(BaseModel):
    contacts: Dict[str, int]
    calendar: Dict[str, int]
    email: Dict[str, int]
    total_interactions: int


# =============================================================================
# Upcoming Events Schemas
# =============================================================================

class UpcomingBirthday(BaseModel):
    contact_id: int
    contact_name: str
    birthday: str
    this_year: str
    days_until: int
    turning_age: int


class UpcomingAnniversary(BaseModel):
    contact_id: int
    contact_name: str
    anniversary: str
    this_year: str
    days_until: int
    years: int


# =============================================================================
# Deduplication Schemas
# =============================================================================

class DuplicateGroup(BaseModel):
    contacts: List[ContactResponse]
    match_reason: str
    confidence: float


class MergeRequest(BaseModel):
    contact_ids: List[int]
    primary_contact_id: int


# =============================================================================
# Import/Export Schemas
# =============================================================================

class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: int
    duplicates: int
    details: List[str] = []


class ExportRequest(BaseModel):
    format: str = "csv"
    contact_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None
