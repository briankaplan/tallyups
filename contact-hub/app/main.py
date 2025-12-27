"""
Contact Hub API - Personal CRM with Relationship Tracking
Extended with interactions, calendar sync, email tracking, and reminders
"""

from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import io
import csv

from .database import engine, get_db, Base
from . import models, schemas, crud
from . import interactions as interaction_service
from . import reminders as reminder_service
from . import sync_google
from . import sync_gmail
from . import sync_calendar

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Contact Hub",
    description="Personal CRM with relationship tracking, email sync, and calendar integration",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health")
def health_check():
    return {"status": "healthy", "version": "2.0.0"}


# =============================================================================
# Contact CRUD
# =============================================================================

@app.post("/contacts", response_model=schemas.ContactResponse)
def create_contact(contact: schemas.ContactCreate, db: Session = Depends(get_db)):
    """Create a new contact"""
    return crud.create_contact(db, contact)


@app.get("/contacts", response_model=schemas.ContactListResponse)
def list_contacts(
    search: Optional[str] = None,
    tag_id: Optional[int] = None,
    needs_attention: Optional[bool] = None,
    is_starred: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """List contacts with filtering and pagination"""
    return crud.get_contacts(
        db,
        search=search,
        tag_id=tag_id,
        needs_attention=needs_attention,
        is_starred=is_starred,
        page=page,
        page_size=page_size,
    )


@app.get("/contacts/{contact_id}", response_model=schemas.ContactResponse)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    """Get a specific contact"""
    contact = crud.get_contact(db, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@app.put("/contacts/{contact_id}", response_model=schemas.ContactResponse)
def update_contact(
    contact_id: int,
    contact: schemas.ContactUpdate,
    db: Session = Depends(get_db),
):
    """Update a contact"""
    result = crud.update_contact(db, contact_id, contact)
    if not result:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@app.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    """Delete a contact"""
    if not crud.delete_contact(db, contact_id):
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "deleted"}


@app.get("/search")
def search_contacts(
    q: str,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Quick search contacts"""
    return crud.search_contacts(db, q, limit)


# =============================================================================
# Tags
# =============================================================================

@app.get("/tags", response_model=List[schemas.TagResponse])
def list_tags(db: Session = Depends(get_db)):
    """List all tags"""
    return crud.get_tags(db)


@app.post("/tags", response_model=schemas.TagResponse)
def create_tag(tag: schemas.TagCreate, db: Session = Depends(get_db)):
    """Create a new tag"""
    return crud.create_tag(db, tag)


@app.post("/contacts/{contact_id}/tags/{tag_id}")
def add_tag_to_contact(contact_id: int, tag_id: int, db: Session = Depends(get_db)):
    """Add a tag to a contact"""
    if not crud.add_tag_to_contact(db, contact_id, tag_id):
        raise HTTPException(status_code=404, detail="Contact or tag not found")
    return {"status": "tagged"}


@app.delete("/contacts/{contact_id}/tags/{tag_id}")
def remove_tag_from_contact(contact_id: int, tag_id: int, db: Session = Depends(get_db)):
    """Remove a tag from a contact"""
    if not crud.remove_tag_from_contact(db, contact_id, tag_id):
        raise HTTPException(status_code=404, detail="Contact or tag not found")
    return {"status": "untagged"}


# =============================================================================
# Interactions
# =============================================================================

@app.post("/interactions", response_model=schemas.InteractionResponse)
def log_interaction(
    interaction: schemas.InteractionCreate,
    db: Session = Depends(get_db),
):
    """Log a manual interaction"""
    return interaction_service.log_interaction(
        db,
        contact_ids=interaction.contact_ids,
        interaction_type=models.InteractionType(interaction.type.value),
        occurred_at=interaction.occurred_at,
        subject=interaction.subject,
        summary=interaction.summary,
        content=interaction.content,
        channel=models.InteractionChannel(interaction.channel.value) if interaction.channel else None,
        duration_minutes=interaction.duration_minutes,
        location=interaction.location,
        is_outgoing=interaction.is_outgoing,
        metadata=interaction.metadata,
    )


@app.post("/interactions/call", response_model=schemas.InteractionResponse)
def log_call(request: schemas.LogCallRequest, db: Session = Depends(get_db)):
    """Log a phone call"""
    return interaction_service.log_call(
        db,
        contact_id=request.contact_id,
        occurred_at=request.occurred_at,
        duration_minutes=request.duration_minutes,
        is_outgoing=request.is_outgoing,
        summary=request.summary,
        was_missed=request.was_missed,
    )


@app.post("/interactions/meeting", response_model=schemas.InteractionResponse)
def log_meeting(request: schemas.LogMeetingRequest, db: Session = Depends(get_db)):
    """Log a meeting"""
    return interaction_service.log_meeting(
        db,
        contact_ids=request.contact_ids,
        occurred_at=request.occurred_at,
        subject=request.subject,
        duration_minutes=request.duration_minutes,
        location=request.location,
        summary=request.summary,
        notes=request.notes,
        is_video=request.is_video,
        video_platform=request.video_platform,
    )


@app.post("/interactions/message", response_model=schemas.InteractionResponse)
def log_message(request: schemas.LogMessageRequest, db: Session = Depends(get_db)):
    """Log a text message"""
    return interaction_service.log_message(
        db,
        contact_id=request.contact_id,
        occurred_at=request.occurred_at,
        content=request.content,
        is_outgoing=request.is_outgoing,
        channel=request.channel,
    )


@app.post("/interactions/note", response_model=schemas.InteractionResponse)
def add_note(request: schemas.AddNoteRequest, db: Session = Depends(get_db)):
    """Add a note about a contact"""
    return interaction_service.add_note(
        db,
        contact_id=request.contact_id,
        content=request.content,
        subject=request.subject,
    )


@app.get("/contacts/{contact_id}/interactions", response_model=List[schemas.InteractionResponse])
def get_contact_interactions(
    contact_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get interactions for a contact"""
    return interaction_service.get_interactions(db, contact_id=contact_id, limit=limit)


@app.get("/contacts/{contact_id}/timeline", response_model=List[schemas.ActivityFeedItem])
def get_contact_timeline(
    contact_id: int,
    limit: int = 50,
    before: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    """Get activity timeline for a contact"""
    return interaction_service.get_activity_timeline(
        db, contact_id=contact_id, limit=limit, before=before
    )


@app.get("/contacts/{contact_id}/stats", response_model=schemas.ContactStatsResponse)
def get_contact_stats(contact_id: int, db: Session = Depends(get_db)):
    """Get interaction statistics for a contact"""
    return interaction_service.get_contact_stats(db, contact_id)


@app.get("/contacts/needing-attention", response_model=List[schemas.ContactResponse])
def get_contacts_needing_attention(limit: int = 20, db: Session = Depends(get_db)):
    """Get contacts that need attention based on frequency goals"""
    return interaction_service.get_contacts_needing_attention(db, limit)


@app.put("/contacts/{contact_id}/frequency")
def set_contact_frequency(
    contact_id: int,
    frequency_days: int,
    db: Session = Depends(get_db),
):
    """Set how often you want to contact someone"""
    contact = interaction_service.set_contact_frequency(db, contact_id, frequency_days)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "updated", "frequency_days": frequency_days}


# =============================================================================
# Reminders
# =============================================================================

@app.post("/reminders", response_model=schemas.ReminderResponse)
def create_reminder(reminder: schemas.ReminderCreate, db: Session = Depends(get_db)):
    """Create a reminder"""
    return reminder_service.create_reminder(
        db,
        contact_id=reminder.contact_id,
        title=reminder.title,
        description=reminder.description,
        due_at=reminder.due_at,
        priority=reminder.priority,
        recurrence_rule=reminder.recurrence_rule,
    )


@app.get("/reminders", response_model=List[schemas.ReminderResponse])
def list_reminders(
    contact_id: Optional[int] = None,
    include_completed: bool = False,
    due_before: Optional[datetime] = None,
    due_after: Optional[datetime] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List reminders"""
    return reminder_service.get_reminders(
        db,
        contact_id=contact_id,
        include_completed=include_completed,
        due_before=due_before,
        due_after=due_after,
        limit=limit,
    )


@app.get("/reminders/due", response_model=List[schemas.ReminderResponse])
def get_due_reminders(db: Session = Depends(get_db)):
    """Get reminders that are due now or overdue"""
    return reminder_service.get_due_reminders(db)


@app.post("/reminders/{reminder_id}/complete")
def complete_reminder(reminder_id: int, db: Session = Depends(get_db)):
    """Mark a reminder as completed"""
    reminder = reminder_service.complete_reminder(db, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"status": "completed"}


@app.post("/reminders/{reminder_id}/snooze")
def snooze_reminder(
    reminder_id: int,
    snooze: schemas.SnoozeRequest,
    db: Session = Depends(get_db),
):
    """Snooze a reminder"""
    reminder = reminder_service.snooze_reminder_duration(
        db, reminder_id, hours=snooze.hours, days=snooze.days
    )
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"status": "snoozed", "until": reminder.snoozed_until}


@app.put("/reminders/{reminder_id}", response_model=schemas.ReminderResponse)
def update_reminder(
    reminder_id: int,
    update: schemas.ReminderUpdate,
    db: Session = Depends(get_db),
):
    """Update a reminder"""
    reminder = reminder_service.update_reminder(
        db, reminder_id, **update.model_dump(exclude_unset=True)
    )
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@app.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, db: Session = Depends(get_db)):
    """Delete a reminder"""
    if not reminder_service.delete_reminder(db, reminder_id):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"status": "deleted"}


@app.post("/reminders/follow-up", response_model=schemas.ReminderResponse)
def create_follow_up(request: schemas.FollowUpRequest, db: Session = Depends(get_db)):
    """Quick way to create a follow-up reminder"""
    reminder = reminder_service.create_follow_up_reminder(
        db,
        contact_id=request.contact_id,
        days_from_now=request.days_from_now,
        title=request.title,
    )
    if not reminder:
        raise HTTPException(status_code=404, detail="Contact not found")
    return reminder


@app.get("/upcoming/birthdays", response_model=List[schemas.UpcomingBirthday])
def get_upcoming_birthdays(days_ahead: int = 30, db: Session = Depends(get_db)):
    """Get contacts with upcoming birthdays"""
    return reminder_service.get_upcoming_birthdays(db, days_ahead)


@app.get("/upcoming/anniversaries", response_model=List[schemas.UpcomingAnniversary])
def get_upcoming_anniversaries(days_ahead: int = 30, db: Session = Depends(get_db)):
    """Get contacts with upcoming anniversaries"""
    return reminder_service.get_upcoming_anniversaries(db, days_ahead)


# =============================================================================
# Calendar
# =============================================================================

@app.get("/calendar/events", response_model=List[schemas.CalendarEventResponse])
def list_calendar_events(
    contact_id: Optional[int] = None,
    days: int = 30,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get upcoming calendar events"""
    return sync_calendar.get_upcoming_events(db, contact_id=contact_id, days=days, limit=limit)


@app.get("/contacts/{contact_id}/meetings", response_model=List[schemas.CalendarEventResponse])
def get_contact_meetings(contact_id: int, limit: int = 20, db: Session = Depends(get_db)):
    """Get past meetings with a contact"""
    return sync_calendar.get_past_meetings(db, contact_id, limit)


@app.post("/sync/calendar")
def sync_google_calendar(
    request: schemas.CalendarSyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Sync calendar from Google"""
    account = db.query(models.SyncAccount).filter(
        models.SyncAccount.id == request.account_id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Sync account not found")
    
    result = sync_calendar.sync_calendar(
        db, account,
        days_back=request.days_back,
        days_forward=request.days_forward,
    )
    
    return result


# =============================================================================
# Email
# =============================================================================

@app.get("/contacts/{contact_id}/emails", response_model=List[schemas.EmailThreadResponse])
def get_contact_emails(contact_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """Get email threads with a contact"""
    return sync_gmail.get_email_history(db, contact_id, limit)


@app.post("/sync/email")
def sync_gmail_emails(
    account_id: int,
    max_results: int = 100,
    db: Session = Depends(get_db),
):
    """Sync emails from Gmail"""
    account = db.query(models.SyncAccount).filter(
        models.SyncAccount.id == account_id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Sync account not found")
    
    return sync_gmail.sync_emails(db, account, max_results)


# =============================================================================
# Full Sync
# =============================================================================

@app.post("/sync/full", response_model=schemas.FullSyncResponse)
def full_sync(request: schemas.FullSyncRequest, db: Session = Depends(get_db)):
    """Run full sync for an account (contacts, calendar, email)"""
    account = db.query(models.SyncAccount).filter(
        models.SyncAccount.id == request.account_id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Sync account not found")
    
    result = {
        "contacts": {"synced": 0, "errors": 0},
        "calendar": {"synced": 0, "interactions": 0, "errors": 0},
        "email": {"synced": 0, "threads": 0, "interactions": 0, "errors": 0},
        "total_interactions": 0,
    }
    
    if request.sync_contacts and account.sync_contacts:
        try:
            contacts_result = sync_google.sync(db, account)
            result["contacts"] = contacts_result
        except Exception as e:
            result["contacts"]["errors"] = 1
            result["contacts"]["error"] = str(e)
    
    if request.sync_calendar and account.sync_calendar:
        try:
            calendar_result = sync_calendar.sync_calendar(db, account)
            result["calendar"] = calendar_result
            result["total_interactions"] += calendar_result.get("interactions", 0)
        except Exception as e:
            result["calendar"]["errors"] = 1
            result["calendar"]["error"] = str(e)
    
    if request.sync_email and account.sync_email:
        try:
            email_result = sync_gmail.sync_emails(db, account)
            result["email"] = email_result
            result["total_interactions"] += email_result.get("interactions", 0)
        except Exception as e:
            result["email"]["errors"] = 1
            result["email"]["error"] = str(e)
    
    return result


# =============================================================================
# Sync Accounts
# =============================================================================

@app.get("/sync/accounts", response_model=List[schemas.SyncAccountResponse])
def list_sync_accounts(db: Session = Depends(get_db)):
    """List all sync accounts"""
    return db.query(models.SyncAccount).all()


@app.get("/sync/status")
def get_sync_status(db: Session = Depends(get_db)):
    """Get overall sync status"""
    accounts = db.query(models.SyncAccount).all()
    
    return {
        "accounts": [
            {
                "id": a.id,
                "name": a.name,
                "source": a.source.value if a.source else None,
                "email": a.account_email,
                "last_sync": a.last_sync_at.isoformat() if a.last_sync_at else None,
                "is_enabled": a.is_enabled,
            }
            for a in accounts
        ],
        "total_contacts": db.query(models.Contact).count(),
        "total_interactions": db.query(models.Interaction).count(),
        "total_events": db.query(models.CalendarEvent).count(),
        "total_email_threads": db.query(models.EmailThread).count(),
    }


# =============================================================================
# Deduplication
# =============================================================================

@app.get("/contacts/duplicates", response_model=List[schemas.DuplicateGroup])
def find_duplicates(db: Session = Depends(get_db)):
    """Find potential duplicate contacts"""
    return crud.find_duplicates(db)


@app.post("/contacts/merge", response_model=schemas.ContactResponse)
def merge_contacts(request: schemas.MergeRequest, db: Session = Depends(get_db)):
    """Merge multiple contacts into one"""
    result = crud.merge_contacts(
        db,
        contact_ids=request.contact_ids,
        primary_contact_id=request.primary_contact_id,
    )
    if not result:
        raise HTTPException(status_code=400, detail="Failed to merge contacts")
    return result


# =============================================================================
# Import/Export
# =============================================================================

@app.post("/contacts/import/csv", response_model=schemas.ImportResult)
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import contacts from CSV"""
    content = await file.read()
    return crud.import_csv(db, content.decode('utf-8'))


@app.post("/contacts/import/vcard", response_model=schemas.ImportResult)
async def import_vcard(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import contacts from vCard"""
    content = await file.read()
    return crud.import_vcard(db, content.decode('utf-8'))


@app.get("/export/csv")
def export_csv(
    contact_ids: Optional[str] = None,
    tag_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Export contacts to CSV"""
    ids = [int(x) for x in contact_ids.split(',')] if contact_ids else None
    csv_content = crud.export_csv(db, contact_ids=ids, tag_id=tag_id)
    
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


@app.get("/export/vcard")
def export_vcard(
    contact_ids: Optional[str] = None,
    tag_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Export contacts to vCard"""
    ids = [int(x) for x in contact_ids.split(',')] if contact_ids else None
    vcard_content = crud.export_vcard(db, contact_ids=ids, tag_id=tag_id)
    
    return StreamingResponse(
        iter([vcard_content]),
        media_type="text/vcard",
        headers={"Content-Disposition": "attachment; filename=contacts.vcf"},
    )


# =============================================================================
# Include OAuth routes
# =============================================================================

from . import auth
app.include_router(auth.router)
