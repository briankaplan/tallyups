"""
OAuth Authentication Routes
Google OAuth for Contacts, Calendar, and Gmail
"""

import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta

from .database import get_db
from . import models

router = APIRouter(prefix="/auth", tags=["auth"])

# OAuth scopes for full access
SCOPES = [
    "https://www.googleapis.com/auth/contacts",           # Contacts read/write
    "https://www.googleapis.com/auth/calendar.readonly",  # Calendar read
    "https://www.googleapis.com/auth/gmail.readonly",     # Gmail read
    "https://www.googleapis.com/auth/userinfo.email",     # Get user email
    "https://www.googleapis.com/auth/userinfo.profile",   # Get user profile
]


def get_oauth_flow(redirect_uri: str) -> Flow:
    """Create OAuth flow"""
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


@router.get("/google")
def google_auth(request: Request):
    """Initiate Google OAuth flow"""
    
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/auth/google/callback"
    
    flow = get_oauth_flow(redirect_uri)
    
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    
    return {"auth_url": auth_url, "state": state}


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str,
    state: str = None,
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback"""
    
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/auth/google/callback"
    
    flow = get_oauth_flow(redirect_uri)
    
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch token: {str(e)}")
    
    credentials = flow.credentials
    
    # Get user info
    try:
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        email = user_info.get('email')
        name = user_info.get('name', email)
    except Exception as e:
        email = None
        name = "Google Account"
    
    # Check if account already exists
    existing = db.query(models.SyncAccount).filter(
        models.SyncAccount.account_email == email,
        models.SyncAccount.source == models.SyncSource.GOOGLE,
    ).first()
    
    if existing:
        # Update tokens
        existing.access_token = credentials.token
        existing.refresh_token = credentials.refresh_token or existing.refresh_token
        existing.token_expiry = credentials.expiry
        existing.updated_at = datetime.utcnow()
        sync_account = existing
    else:
        # Create new account
        sync_account = models.SyncAccount(
            name=name,
            source=models.SyncSource.GOOGLE,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            token_expiry=credentials.expiry,
            account_email=email,
            account_id=user_info.get('id') if email else None,
            sync_contacts=True,
            sync_calendar=True,
            sync_email=True,
            is_enabled=True,
            sync_direction="bidirectional",
        )
        db.add(sync_account)
    
    db.commit()
    db.refresh(sync_account)
    
    return {
        "status": "connected",
        "account_id": sync_account.id,
        "email": email,
        "name": name,
        "sync_contacts": sync_account.sync_contacts,
        "sync_calendar": sync_account.sync_calendar,
        "sync_email": sync_account.sync_email,
    }


@router.delete("/google/{account_id}")
def disconnect_google(account_id: int, db: Session = Depends(get_db)):
    """Disconnect a Google account"""
    
    account = db.query(models.SyncAccount).filter(
        models.SyncAccount.id == account_id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    # Optionally revoke the token
    if account.access_token:
        try:
            import requests
            requests.post(
                'https://oauth2.googleapis.com/revoke',
                params={'token': account.access_token},
                headers={'content-type': 'application/x-www-form-urlencoded'}
            )
        except:
            pass
    
    db.delete(account)
    db.commit()
    
    return {"status": "disconnected"}


@router.put("/google/{account_id}/settings")
def update_sync_settings(
    account_id: int,
    sync_contacts: bool = None,
    sync_calendar: bool = None,
    sync_email: bool = None,
    is_enabled: bool = None,
    db: Session = Depends(get_db),
):
    """Update sync settings for an account"""
    
    account = db.query(models.SyncAccount).filter(
        models.SyncAccount.id == account_id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    if sync_contacts is not None:
        account.sync_contacts = sync_contacts
    if sync_calendar is not None:
        account.sync_calendar = sync_calendar
    if sync_email is not None:
        account.sync_email = sync_email
    if is_enabled is not None:
        account.is_enabled = is_enabled
    
    db.commit()
    
    return {
        "account_id": account.id,
        "sync_contacts": account.sync_contacts,
        "sync_calendar": account.sync_calendar,
        "sync_email": account.sync_email,
        "is_enabled": account.is_enabled,
    }


@router.get("/google/{account_id}/test")
def test_connection(account_id: int, db: Session = Depends(get_db)):
    """Test if a Google connection is still valid"""
    
    account = db.query(models.SyncAccount).filter(
        models.SyncAccount.id == account_id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    try:
        credentials = Credentials(
            token=account.access_token,
            refresh_token=account.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        )
        
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        
        return {
            "status": "valid",
            "email": user_info.get('email'),
            "token_expiry": account.token_expiry.isoformat() if account.token_expiry else None,
        }
    except Exception as e:
        return {
            "status": "invalid",
            "error": str(e),
        }
