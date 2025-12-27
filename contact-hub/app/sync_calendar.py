"""
Google Calendar Sync Engine
Pull calendar events and link to contacts
"""

import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from . import models


def get_calendar_service(sync_account: models.SyncAccount):
    """Get authenticated Google Calendar API service"""
    
    creds = Credentials(
        token=sync_account.access_token,
        refresh_token=sync_account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    )
    
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        sync_account.access_token = creds.token
        sync_account.token_expiry = creds.expiry
    
    return build('calendar', 'v3', credentials=creds)


def find_contacts_by_email(db: Session, email_addresses: List[str]) -> List[models.Contact]:
    """Find contacts by their email addresses"""
    contacts = []
    for email_addr in email_addresses:
        email_record = db.query(models.Email).filter(
            models.Email.email == email_addr.lower()
        ).first()
        if email_record and email_record.contact not in contacts:
            contacts.append(email_record.contact)
    return contacts


def parse_datetime(dt_dict: Dict) -> Optional[datetime]:
    """Parse Google Calendar datetime object"""
    if not dt_dict:
        return None
    
    if 'dateTime' in dt_dict:
        # Full datetime
        dt_str = dt_dict['dateTime']
        # Handle timezone offset
        if '+' in dt_str or dt_str.endswith('Z'):
            try:
                return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            except:
                pass
        return datetime.fromisoformat(dt_str)
    elif 'date' in dt_dict:
        # All-day event
        return datetime.strptime(dt_dict['date'], '%Y-%m-%d')
    
    return None


def sync_calendar(
    db: Session,
    sync_account: models.SyncAccount,
    days_back: int = 30,
    days_forward: int = 90
) -> Dict[str, int]:
    """Sync calendar events from Google Calendar"""
    
    result = {"synced": 0, "updated": 0, "interactions": 0, "errors": 0}
    
    service = get_calendar_service(sync_account)
    
    # Calculate time range
    time_min = (datetime.utcnow() - timedelta(days=days_back)).isoformat() + 'Z'
    time_max = (datetime.utcnow() + timedelta(days=days_forward)).isoformat() + 'Z'
    
    # Get calendar ID (default to primary)
    calendar_id = sync_account.calendar_id or 'primary'
    
    # Use sync token if available
    sync_token = sync_account.calendar_sync_token
    
    try:
        if sync_token:
            # Incremental sync
            events_result = service.events().list(
                calendarId=calendar_id,
                syncToken=sync_token,
                maxResults=250,
                singleEvents=True,
            ).execute()
        else:
            # Full sync
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=250,
                singleEvents=True,
                orderBy='startTime',
            ).execute()
    except Exception as e:
        # Sync token might be expired, do full sync
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=250,
            singleEvents=True,
            orderBy='startTime',
        ).execute()
    
    # Process events
    for event in events_result.get('items', []):
        try:
            event_id = event.get('id')
            
            # Check if event already exists
            existing = db.query(models.CalendarEvent).filter(
                models.CalendarEvent.external_id == event_id,
                models.CalendarEvent.source == models.SyncSource.GOOGLE
            ).first()
            
            # Parse times
            start = parse_datetime(event.get('start', {}))
            end = parse_datetime(event.get('end', {}))
            is_all_day = 'date' in event.get('start', {})
            
            if not start:
                continue
            
            # Get attendees' emails
            attendee_emails = []
            for attendee in event.get('attendees', []):
                email = attendee.get('email', '').lower()
                if email and email != sync_account.account_email.lower():
                    attendee_emails.append(email)
            
            # Find matching contacts
            contacts = find_contacts_by_email(db, attendee_emails)
            
            # Determine event type
            event_type = models.EventType.MEETING
            
            # Check for video conference
            video_url = None
            video_type = None
            
            conference_data = event.get('conferenceData', {})
            for entry_point in conference_data.get('entryPoints', []):
                if entry_point.get('entryPointType') == 'video':
                    video_url = entry_point.get('uri')
                    video_type = conference_data.get('conferenceSolution', {}).get('name', 'video')
                    break
            
            # Check for Zoom link in location or description
            location = event.get('location', '')
            description = event.get('description', '')
            
            if not video_url:
                for text in [location, description]:
                    if 'zoom.us' in text.lower():
                        import re
                        zoom_match = re.search(r'https://[^\s]*zoom\.us/[^\s]*', text)
                        if zoom_match:
                            video_url = zoom_match.group()
                            video_type = 'zoom'
                            break
                    elif 'meet.google.com' in text.lower():
                        import re
                        meet_match = re.search(r'https://meet\.google\.com/[^\s]*', text)
                        if meet_match:
                            video_url = meet_match.group()
                            video_type = 'google_meet'
                            break
            
            # Get organizer
            organizer = event.get('organizer', {})
            organizer_email = organizer.get('email', '')
            organizer_name = organizer.get('displayName', '')
            is_organizer = organizer_email.lower() == sync_account.account_email.lower()
            
            # My response status
            my_response = None
            for attendee in event.get('attendees', []):
                if attendee.get('self'):
                    my_response = attendee.get('responseStatus')
                    break
            
            # Map status
            status_map = {
                'confirmed': models.EventStatus.CONFIRMED,
                'tentative': models.EventStatus.TENTATIVE,
                'cancelled': models.EventStatus.CANCELLED,
            }
            status = status_map.get(event.get('status', 'confirmed'), models.EventStatus.CONFIRMED)
            
            if existing:
                # Update existing event
                existing.title = event.get('summary', '(No title)')
                existing.description = description
                existing.start_time = start
                existing.end_time = end
                existing.is_all_day = is_all_day
                existing.location = location
                existing.video_conference_url = video_url
                existing.video_conference_type = video_type
                existing.status = status
                existing.organizer_email = organizer_email
                existing.organizer_name = organizer_name
                existing.is_organizer = is_organizer
                existing.my_response = my_response
                existing.etag = event.get('etag')
                existing.last_synced_at = datetime.utcnow()
                existing.contacts = contacts
                
                result["updated"] += 1
            else:
                # Create new event
                cal_event = models.CalendarEvent(
                    title=event.get('summary', '(No title)'),
                    description=description,
                    start_time=start,
                    end_time=end,
                    is_all_day=is_all_day,
                    timezone=event.get('start', {}).get('timeZone'),
                    location=location,
                    video_conference_url=video_url,
                    video_conference_type=video_type,
                    status=status,
                    event_type=event_type,
                    is_recurring=bool(event.get('recurringEventId')),
                    recurring_event_id=event.get('recurringEventId'),
                    organizer_email=organizer_email,
                    organizer_name=organizer_name,
                    is_organizer=is_organizer,
                    my_response=my_response,
                    external_id=event_id,
                    external_url=event.get('htmlLink'),
                    source=models.SyncSource.GOOGLE,
                    sync_account_id=sync_account.id,
                    etag=event.get('etag'),
                    last_synced_at=datetime.utcnow(),
                )
                cal_event.contacts = contacts
                db.add(cal_event)
                
                result["synced"] += 1
            
            # Create interaction for past events with contacts
            if contacts and start < datetime.utcnow():
                for contact in contacts:
                    # Check if interaction already exists
                    existing_interaction = db.query(models.Interaction).filter(
                        models.Interaction.external_id == f"cal_{event_id}",
                        models.Interaction.source == models.SyncSource.GOOGLE
                    ).first()
                    
                    if not existing_interaction:
                        # Determine interaction type
                        if video_url:
                            interaction_type = models.InteractionType.VIDEO_CALL
                            channel = models.InteractionChannel.ZOOM if 'zoom' in (video_type or '').lower() else models.InteractionChannel.GOOGLE_MEET
                        else:
                            interaction_type = models.InteractionType.MEETING
                            channel = models.InteractionChannel.IN_PERSON
                        
                        # Calculate duration
                        duration = None
                        if start and end:
                            duration = int((end - start).total_seconds() / 60)
                        
                        interaction = models.Interaction(
                            type=interaction_type,
                            channel=channel,
                            occurred_at=start,
                            duration_minutes=duration,
                            subject=event.get('summary', '(No title)'),
                            summary=description[:500] if description else None,
                            location=location,
                            external_id=f"cal_{event_id}",
                            external_url=event.get('htmlLink'),
                            source=models.SyncSource.GOOGLE,
                            is_outgoing=is_organizer,
                        )
                        db.add(interaction)
                        db.flush()
                        
                        interaction.contacts.append(contact)
                        
                        # Update contact's last interaction
                        if not contact.last_interaction_at or start > contact.last_interaction_at:
                            contact.last_interaction_at = start
                            contact.last_interaction_type = interaction_type
                        contact.interaction_count = (contact.interaction_count or 0) + 1
                        
                        result["interactions"] += 1
            
        except Exception as e:
            print(f"Error processing event: {e}")
            result["errors"] += 1
    
    # Save sync token for incremental sync
    if 'nextSyncToken' in events_result:
        sync_account.calendar_sync_token = events_result['nextSyncToken']
    
    sync_account.last_sync_at = datetime.utcnow()
    db.commit()
    
    return result


def get_upcoming_events(
    db: Session,
    contact_id: Optional[int] = None,
    days: int = 30,
    limit: int = 50
) -> List[models.CalendarEvent]:
    """Get upcoming calendar events, optionally for a specific contact"""
    
    query = db.query(models.CalendarEvent).filter(
        models.CalendarEvent.start_time >= datetime.utcnow(),
        models.CalendarEvent.start_time <= datetime.utcnow() + timedelta(days=days),
        models.CalendarEvent.status != models.EventStatus.CANCELLED,
    )
    
    if contact_id:
        query = query.filter(
            models.CalendarEvent.contacts.any(models.Contact.id == contact_id)
        )
    
    return query.order_by(models.CalendarEvent.start_time).limit(limit).all()


def get_past_meetings(
    db: Session,
    contact_id: int,
    limit: int = 20
) -> List[models.CalendarEvent]:
    """Get past meetings with a specific contact"""
    
    return db.query(models.CalendarEvent).filter(
        models.CalendarEvent.contacts.any(models.Contact.id == contact_id),
        models.CalendarEvent.start_time < datetime.utcnow(),
    ).order_by(models.CalendarEvent.start_time.desc()).limit(limit).all()
