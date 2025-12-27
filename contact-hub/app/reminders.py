"""
Reminder System
Create and manage follow-up reminders for contacts
"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dateutil.rrule import rrulestr

from . import models


def create_reminder(
    db: Session,
    contact_id: int,
    title: str,
    due_at: datetime,
    description: Optional[str] = None,
    priority: int = 0,
    recurrence_rule: Optional[str] = None,
) -> models.Reminder:
    """Create a reminder for a contact"""
    
    reminder = models.Reminder(
        contact_id=contact_id,
        title=title,
        description=description,
        due_at=due_at,
        priority=priority,
        is_recurring=bool(recurrence_rule),
        recurrence_rule=recurrence_rule,
    )
    
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    
    return reminder


def get_reminders(
    db: Session,
    contact_id: Optional[int] = None,
    include_completed: bool = False,
    due_before: Optional[datetime] = None,
    due_after: Optional[datetime] = None,
    limit: int = 50,
) -> List[models.Reminder]:
    """Get reminders with optional filters"""
    
    query = db.query(models.Reminder)
    
    if contact_id:
        query = query.filter(models.Reminder.contact_id == contact_id)
    
    if not include_completed:
        query = query.filter(models.Reminder.is_completed == False)
    
    if due_before:
        query = query.filter(models.Reminder.due_at <= due_before)
    
    if due_after:
        query = query.filter(models.Reminder.due_at >= due_after)
    
    # Exclude snoozed reminders that haven't reached snooze time
    query = query.filter(
        or_(
            models.Reminder.is_snoozed == False,
            models.Reminder.snoozed_until <= datetime.utcnow()
        )
    )
    
    return query.order_by(models.Reminder.due_at).limit(limit).all()


def get_due_reminders(db: Session) -> List[models.Reminder]:
    """Get reminders that are due now or overdue"""
    
    return db.query(models.Reminder).filter(
        models.Reminder.is_completed == False,
        models.Reminder.due_at <= datetime.utcnow(),
        or_(
            models.Reminder.is_snoozed == False,
            models.Reminder.snoozed_until <= datetime.utcnow()
        )
    ).order_by(models.Reminder.priority.desc(), models.Reminder.due_at).all()


def complete_reminder(
    db: Session,
    reminder_id: int,
    create_next_if_recurring: bool = True,
) -> models.Reminder:
    """Mark a reminder as completed"""
    
    reminder = db.query(models.Reminder).filter(
        models.Reminder.id == reminder_id
    ).first()
    
    if not reminder:
        return None
    
    reminder.is_completed = True
    reminder.completed_at = datetime.utcnow()
    reminder.is_snoozed = False
    reminder.snoozed_until = None
    
    # If recurring, create the next occurrence
    if create_next_if_recurring and reminder.is_recurring and reminder.recurrence_rule:
        try:
            rule = rrulestr(reminder.recurrence_rule, dtstart=reminder.due_at)
            next_occurrence = rule.after(datetime.utcnow())
            
            if next_occurrence:
                create_reminder(
                    db=db,
                    contact_id=reminder.contact_id,
                    title=reminder.title,
                    description=reminder.description,
                    due_at=next_occurrence,
                    priority=reminder.priority,
                    recurrence_rule=reminder.recurrence_rule,
                )
        except Exception as e:
            print(f"Error creating recurring reminder: {e}")
    
    db.commit()
    return reminder


def snooze_reminder(
    db: Session,
    reminder_id: int,
    snooze_until: datetime,
) -> models.Reminder:
    """Snooze a reminder until a later time"""
    
    reminder = db.query(models.Reminder).filter(
        models.Reminder.id == reminder_id
    ).first()
    
    if not reminder:
        return None
    
    reminder.is_snoozed = True
    reminder.snoozed_until = snooze_until
    
    db.commit()
    return reminder


def snooze_reminder_duration(
    db: Session,
    reminder_id: int,
    hours: int = 0,
    days: int = 0,
) -> models.Reminder:
    """Snooze a reminder for a duration"""
    
    snooze_until = datetime.utcnow() + timedelta(hours=hours, days=days)
    return snooze_reminder(db, reminder_id, snooze_until)


def delete_reminder(db: Session, reminder_id: int) -> bool:
    """Delete a reminder"""
    
    reminder = db.query(models.Reminder).filter(
        models.Reminder.id == reminder_id
    ).first()
    
    if not reminder:
        return False
    
    db.delete(reminder)
    db.commit()
    return True


def update_reminder(
    db: Session,
    reminder_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    due_at: Optional[datetime] = None,
    priority: Optional[int] = None,
) -> models.Reminder:
    """Update a reminder"""
    
    reminder = db.query(models.Reminder).filter(
        models.Reminder.id == reminder_id
    ).first()
    
    if not reminder:
        return None
    
    if title is not None:
        reminder.title = title
    if description is not None:
        reminder.description = description
    if due_at is not None:
        reminder.due_at = due_at
    if priority is not None:
        reminder.priority = priority
    
    db.commit()
    return reminder


def create_follow_up_reminder(
    db: Session,
    contact_id: int,
    days_from_now: int = 7,
    title: Optional[str] = None,
) -> models.Reminder:
    """Quick way to create a follow-up reminder"""
    
    contact = db.query(models.Contact).filter(
        models.Contact.id == contact_id
    ).first()
    
    if not contact:
        return None
    
    due_at = datetime.utcnow() + timedelta(days=days_from_now)
    
    if not title:
        title = f"Follow up with {contact.display_name or contact.first_name}"
    
    return create_reminder(
        db=db,
        contact_id=contact_id,
        title=title,
        due_at=due_at,
    )


def get_upcoming_birthdays(
    db: Session,
    days_ahead: int = 30,
) -> List[Dict[str, Any]]:
    """Get contacts with upcoming birthdays"""
    
    today = datetime.utcnow().date()
    
    contacts = db.query(models.Contact).filter(
        models.Contact.birthday.isnot(None),
        models.Contact.is_archived == False,
    ).all()
    
    upcoming = []
    
    for contact in contacts:
        birthday = contact.birthday.date() if isinstance(contact.birthday, datetime) else contact.birthday
        
        # Calculate this year's birthday
        this_year_birthday = birthday.replace(year=today.year)
        
        # If birthday has passed this year, use next year
        if this_year_birthday < today:
            this_year_birthday = birthday.replace(year=today.year + 1)
        
        days_until = (this_year_birthday - today).days
        
        if 0 <= days_until <= days_ahead:
            upcoming.append({
                "contact_id": contact.id,
                "contact_name": contact.display_name or f"{contact.first_name} {contact.last_name}",
                "birthday": birthday.isoformat(),
                "this_year": this_year_birthday.isoformat(),
                "days_until": days_until,
                "turning_age": today.year - birthday.year + (1 if days_until > 0 else 0),
            })
    
    return sorted(upcoming, key=lambda x: x["days_until"])


def get_upcoming_anniversaries(
    db: Session,
    days_ahead: int = 30,
) -> List[Dict[str, Any]]:
    """Get contacts with upcoming anniversaries"""
    
    today = datetime.utcnow().date()
    
    contacts = db.query(models.Contact).filter(
        models.Contact.anniversary.isnot(None),
        models.Contact.is_archived == False,
    ).all()
    
    upcoming = []
    
    for contact in contacts:
        anniversary = contact.anniversary.date() if isinstance(contact.anniversary, datetime) else contact.anniversary
        
        # Calculate this year's anniversary
        this_year_anniversary = anniversary.replace(year=today.year)
        
        if this_year_anniversary < today:
            this_year_anniversary = anniversary.replace(year=today.year + 1)
        
        days_until = (this_year_anniversary - today).days
        
        if 0 <= days_until <= days_ahead:
            upcoming.append({
                "contact_id": contact.id,
                "contact_name": contact.display_name or f"{contact.first_name} {contact.last_name}",
                "anniversary": anniversary.isoformat(),
                "this_year": this_year_anniversary.isoformat(),
                "days_until": days_until,
                "years": today.year - anniversary.year + (1 if days_until > 0 else 0),
            })
    
    return sorted(upcoming, key=lambda x: x["days_until"])
