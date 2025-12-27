"""
Gmail Sync Engine
Pull emails and create interaction records
"""

import os
import base64
import email
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from . import models, crud


def get_gmail_service(sync_account: models.SyncAccount):
    """Get authenticated Gmail API service"""
    
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
    
    return build('gmail', 'v1', credentials=creds)


def extract_email_address(header_value: str) -> tuple:
    """Extract email and name from header like 'John Doe <john@example.com>'"""
    if '<' in header_value:
        name = header_value.split('<')[0].strip().strip('"')
        email_addr = header_value.split('<')[1].split('>')[0].strip()
    else:
        name = ''
        email_addr = header_value.strip()
    return email_addr.lower(), name


def find_contact_by_email(db: Session, email_addr: str) -> Optional[models.Contact]:
    """Find a contact by email address"""
    email_record = db.query(models.Email).filter(
        models.Email.email == email_addr.lower()
    ).first()
    
    if email_record:
        return email_record.contact
    return None


def sync_emails(db: Session, sync_account: models.SyncAccount, max_results: int = 100) -> Dict[str, int]:
    """Sync emails from Gmail and create interaction records"""
    
    result = {"synced": 0, "threads": 0, "interactions": 0, "errors": 0}
    
    service = get_gmail_service(sync_account)
    
    # Get list of messages
    query = "in:inbox OR in:sent"
    
    # Use history ID for incremental sync if available
    if sync_account.email_history_id:
        try:
            history = service.users().history().list(
                userId='me',
                startHistoryId=sync_account.email_history_id,
                historyTypes=['messageAdded']
            ).execute()
            
            message_ids = []
            for record in history.get('history', []):
                for msg in record.get('messagesAdded', []):
                    message_ids.append(msg['message']['id'])
            
            # Update history ID
            sync_account.email_history_id = history.get('historyId')
            
        except Exception as e:
            # History expired, do full sync
            message_ids = None
    else:
        message_ids = None
    
    # If no history, get recent messages
    if message_ids is None:
        # Get messages from the last 30 days if first sync
        if sync_account.email_sync_from:
            after_date = sync_account.email_sync_from.strftime('%Y/%m/%d')
            query += f" after:{after_date}"
        else:
            # Default to last 30 days
            after_date = (datetime.utcnow() - timedelta(days=30)).strftime('%Y/%m/%d')
            query += f" after:{after_date}"
        
        messages_response = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()
        
        message_ids = [m['id'] for m in messages_response.get('messages', [])]
        
        # Store history ID for incremental sync
        profile = service.users().getProfile(userId='me').execute()
        sync_account.email_history_id = profile.get('historyId')
    
    # Process each message
    processed_threads = set()
    
    for msg_id in message_ids:
        try:
            # Get full message
            message = service.users().messages().get(
                userId='me',
                id=msg_id,
                format='full'
            ).execute()
            
            thread_id = message.get('threadId')
            
            # Parse headers
            headers = {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}
            
            from_email, from_name = extract_email_address(headers.get('from', ''))
            to_list = [extract_email_address(t.strip()) for t in headers.get('to', '').split(',') if t.strip()]
            
            subject = headers.get('subject', '(no subject)')
            date_str = headers.get('date', '')
            
            # Parse date
            try:
                # Gmail dates are usually RFC 2822 format
                sent_at = email.utils.parsedate_to_datetime(date_str)
            except:
                sent_at = datetime.utcnow()
            
            # Determine if sent or received
            user_email = sync_account.account_email.lower()
            is_sent = from_email == user_email
            
            # Find the contact (the other party)
            if is_sent:
                # We sent it - find recipient contact
                contact_email = to_list[0][0] if to_list else None
            else:
                # We received it - find sender contact
                contact_email = from_email
            
            contact = find_contact_by_email(db, contact_email) if contact_email else None
            
            # Get message body
            body_text = ''
            body_html = ''
            
            def extract_body(payload):
                nonlocal body_text, body_html
                
                if payload.get('mimeType') == 'text/plain':
                    data = payload.get('body', {}).get('data', '')
                    if data:
                        body_text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                elif payload.get('mimeType') == 'text/html':
                    data = payload.get('body', {}).get('data', '')
                    if data:
                        body_html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                
                for part in payload.get('parts', []):
                    extract_body(part)
            
            extract_body(message.get('payload', {}))
            
            # Check if message already exists
            existing = db.query(models.EmailMessage).filter(
                models.EmailMessage.message_id == msg_id
            ).first()
            
            if existing:
                continue
            
            # Create or get thread
            if thread_id not in processed_threads:
                thread = db.query(models.EmailThread).filter(
                    models.EmailThread.thread_id == thread_id
                ).first()
                
                if not thread:
                    thread = models.EmailThread(
                        contact_id=contact.id if contact else None,
                        thread_id=thread_id,
                        subject=subject,
                        participants=[{"email": e, "name": n} for e, n in ([extract_email_address(headers.get('from', ''))] + to_list)],
                        source=models.SyncSource.GOOGLE,
                        sync_account_id=sync_account.id,
                    )
                    db.add(thread)
                    db.flush()
                    result["threads"] += 1
                
                processed_threads.add(thread_id)
            else:
                thread = db.query(models.EmailThread).filter(
                    models.EmailThread.thread_id == thread_id
                ).first()
            
            # Create email message
            email_msg = models.EmailMessage(
                thread_id=thread.id,
                message_id=msg_id,
                from_email=from_email,
                from_name=from_name,
                to_emails=[{"email": e, "name": n} for e, n in to_list],
                subject=subject,
                body_text=body_text[:50000] if body_text else None,  # Limit size
                body_html=body_html[:100000] if body_html else None,
                snippet=message.get('snippet', '')[:500],
                sent_at=sent_at,
                is_read='UNREAD' not in message.get('labelIds', []),
                is_starred='STARRED' in message.get('labelIds', []),
                is_sent='SENT' in message.get('labelIds', []),
                labels=message.get('labelIds', []),
            )
            db.add(email_msg)
            
            # Update thread stats
            thread.message_count = (thread.message_count or 0) + 1
            thread.last_message_at = sent_at
            thread.last_message_from = from_email
            thread.snippet = message.get('snippet', '')[:500]
            thread.is_unread = 'UNREAD' in message.get('labelIds', [])
            
            # Create interaction record if we have a contact
            if contact:
                interaction_type = models.InteractionType.EMAIL_SENT if is_sent else models.InteractionType.EMAIL_RECEIVED
                
                # Check if interaction already exists
                existing_interaction = db.query(models.Interaction).filter(
                    models.Interaction.external_id == msg_id,
                    models.Interaction.source == models.SyncSource.GOOGLE
                ).first()
                
                if not existing_interaction:
                    interaction = models.Interaction(
                        type=interaction_type,
                        channel=models.InteractionChannel.EMAIL,
                        occurred_at=sent_at,
                        subject=subject,
                        summary=message.get('snippet', '')[:500],
                        external_id=msg_id,
                        source=models.SyncSource.GOOGLE,
                        is_outgoing=is_sent,
                    )
                    db.add(interaction)
                    db.flush()
                    
                    # Link to contact
                    interaction.contacts.append(contact)
                    
                    # Update contact's last interaction
                    if not contact.last_interaction_at or sent_at > contact.last_interaction_at:
                        contact.last_interaction_at = sent_at
                        contact.last_interaction_type = interaction_type
                    contact.interaction_count = (contact.interaction_count or 0) + 1
                    
                    result["interactions"] += 1
            
            result["synced"] += 1
            
        except Exception as e:
            print(f"Error processing message {msg_id}: {e}")
            result["errors"] += 1
    
    db.commit()
    return result


def get_email_history(
    db: Session,
    contact_id: int,
    limit: int = 50
) -> List[Dict]:
    """Get email history for a contact"""
    
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not contact:
        return []
    
    # Get threads for this contact
    threads = db.query(models.EmailThread).filter(
        models.EmailThread.contact_id == contact_id
    ).order_by(models.EmailThread.last_message_at.desc()).limit(limit).all()
    
    result = []
    for thread in threads:
        messages = db.query(models.EmailMessage).filter(
            models.EmailMessage.thread_id == thread.id
        ).order_by(models.EmailMessage.sent_at.desc()).all()
        
        result.append({
            "thread_id": thread.thread_id,
            "subject": thread.subject,
            "message_count": thread.message_count,
            "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
            "is_unread": thread.is_unread,
            "messages": [
                {
                    "id": m.id,
                    "from": m.from_email,
                    "from_name": m.from_name,
                    "subject": m.subject,
                    "snippet": m.snippet,
                    "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                    "is_sent": m.is_sent,
                }
                for m in messages[:10]  # Limit messages per thread
            ]
        })
    
    return result
