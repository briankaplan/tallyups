#!/usr/bin/env python3
"""
Gmail Label-Based Receipt Integration for ReceiptAI
====================================================

This module replaces keyword-based Gmail searching with label-based scanning.

HOW IT WORKS:
1. Gmail filters (set up separately) auto-label receipts with "Receipts" label
2. This module polls the "Receipts" label for new emails
3. New receipts are extracted, OCR'd, and fed into ReceiptAI
4. Processed emails are marked (optional: move to "Receipts/Processed")

ADVANTAGES:
- Gmail filters are faster and run on Google's servers 24/7
- No need to maintain receipt patterns in two places
- Cleaner inbox (receipts skip inbox entirely)
- Lower API usage (only fetch emails that are definitely receipts)

INTEGRATION:
- Drop this file into your ReceiptAI-MASTER-LIBRARY directory
- Update viewer_server.py to use `scan_receipt_label()` instead of keyword search
- Run `setup_gmail_receipt_filters.py` to create the filters

Author: Built for Brian Kaplan's ReceiptAI system
Date: December 2024
"""

import os
import json
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Google API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False
    print("⚠️  Google API libraries not available")

# Import existing ReceiptAI services
try:
    from services.gmail_receipt_service import GmailReceiptService, GMAIL_ACCOUNTS
    from receipt_ocr_service import process_receipt_image
    from r2_service import upload_to_r2
    RECEIPTAI_AVAILABLE = True
except ImportError:
    RECEIPTAI_AVAILABLE = False
    print("⚠️  ReceiptAI services not available - running standalone")


# =============================================================================
# CONFIGURATION
# =============================================================================

# Gmail API scopes (need modify to manage labels)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels'
]

# Label names
RECEIPT_LABEL_NAME = "Receipts"
PROCESSED_LABEL_NAME = "Receipts/Processed"  # Optional: move processed receipts here

# Token paths (matching existing ReceiptAI structure)
TOKEN_DIR = Path(__file__).parent / "gmail_tokens"

# Accounts to monitor (same as existing ReceiptAI)
ACCOUNTS = {
    'kaplan.brian@gmail.com': {
        'token_file': 'tokens_kaplan_brian_gmail_com.json',
        'business_type': 'Personal'
    },
    'brian@business.com': {
        'token_file': 'tokens_brian_business_com.json',
        'business_type': 'Business'
    },
    'brian@musiccityrodeo.com': {
        'token_file': 'tokens_brian_musiccityrodeo_com.json',
        'business_type': 'Music City Rodeo'
    }
}


class GmailLabelScanner:
    """
    Scans Gmail "Receipts" label for new receipt emails.
    
    This is a cleaner approach than keyword searching:
    - Gmail filters automatically label receipts
    - We just fetch emails with that label
    - Much faster and more reliable
    """
    
    def __init__(self, db_path: str = 'receipts.db'):
        self.db_path = db_path
        self.services = {}  # account -> gmail service
        self.label_ids = {}  # account -> label_id for "Receipts"
        
    def _get_service(self, account: str) -> Optional[object]:
        """Get Gmail service for account (cached)."""
        if account in self.services:
            return self.services[account]
            
        if account not in ACCOUNTS:
            print(f"❌ Unknown account: {account}")
            return None
            
        config = ACCOUNTS[account]
        token_path = TOKEN_DIR / config['token_file']
        
        if not token_path.exists():
            print(f"❌ Token not found: {token_path}")
            print(f"   Run OAuth flow to create token for {account}")
            return None
            
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                with open(token_path, 'w') as f:
                    f.write(creds.to_json())
                    
            service = build('gmail', 'v1', credentials=creds)
            self.services[account] = service
            return service
            
        except Exception as e:
            print(f"❌ Failed to authenticate {account}: {e}")
            return None
            
    def _get_or_create_label(self, service, label_name: str) -> Optional[str]:
        """Get label ID, creating the label if it doesn't exist."""
        try:
            # List all labels
            results = service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            # Find existing label
            for label in labels:
                if label['name'] == label_name:
                    return label['id']
                    
            # Create label if not found
            label_body = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            created = service.users().labels().create(userId='me', body=label_body).execute()
            print(f"✅ Created label: {label_name}")
            return created['id']
            
        except Exception as e:
            print(f"❌ Error with label {label_name}: {e}")
            return None
            
    def _get_label_id(self, account: str) -> Optional[str]:
        """Get the "Receipts" label ID for an account."""
        if account in self.label_ids:
            return self.label_ids[account]
            
        service = self._get_service(account)
        if not service:
            return None
            
        label_id = self._get_or_create_label(service, RECEIPT_LABEL_NAME)
        if label_id:
            self.label_ids[account] = label_id
        return label_id
        
    def scan_receipt_label(
        self, 
        account: str, 
        max_results: int = 50,
        since_hours: int = 24
    ) -> List[Dict]:
        """
        Scan the "Receipts" label for new emails.
        
        This is the main entry point - call this instead of keyword search.
        
        Args:
            account: Gmail account to scan
            max_results: Maximum emails to fetch
            since_hours: Only fetch emails from last N hours
            
        Returns:
            List of receipt dicts ready for ReceiptAI processing
        """
        service = self._get_service(account)
        if not service:
            return []
            
        label_id = self._get_label_id(account)
        if not label_id:
            return []
            
        # Build query for recent emails in Receipts label
        since_date = (datetime.now() - timedelta(hours=since_hours)).strftime('%Y/%m/%d')
        query = f"after:{since_date}"
        
        try:
            # Fetch messages with Receipts label
            results = service.users().messages().list(
                userId='me',
                labelIds=[label_id],
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                print(f"📭 No new receipts in {account}")
                return []
                
            print(f"📬 Found {len(messages)} receipts in {account}")
            
            receipts = []
            for msg in messages:
                receipt = self._process_message(service, msg['id'], account)
                if receipt:
                    receipts.append(receipt)
                    
            return receipts
            
        except HttpError as e:
            print(f"❌ Gmail API error: {e}")
            return []
            
    def _process_message(self, service, message_id: str, account: str) -> Optional[Dict]:
        """Process a single Gmail message into a receipt dict."""
        try:
            # Fetch full message
            message = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Extract headers
            headers = {h['name']: h['value'] for h in message['payload']['headers']}
            
            subject = headers.get('Subject', '')
            from_email = headers.get('From', '')
            date_str = headers.get('Date', '')
            
            # Get body
            body = self._get_message_body(message)
            
            # Extract receipt data
            receipt = {
                'gmail_account': account,
                'gmail_message_id': message_id,
                'email_subject': subject,
                'email_from': from_email,
                'email_date': self._parse_date(date_str),
                'business_type': ACCOUNTS[account]['business_type'],
                'source': 'gmail_label',
                'body_preview': body[:500] if body else '',
                'has_attachments': self._has_attachments(message),
                'attachments': self._get_attachments(service, message_id, message)
            }
            
            # Basic extraction (your existing OCR pipeline will enhance this)
            receipt['amount'] = self._extract_amount(subject, body)
            receipt['merchant'] = self._extract_merchant(subject, from_email)
            
            return receipt
            
        except Exception as e:
            print(f"   ⚠️ Error processing message {message_id}: {e}")
            return None
            
    def _get_message_body(self, message: Dict) -> str:
        """Extract body text from Gmail message."""
        try:
            payload = message['payload']
            
            # Try direct body
            if 'body' in payload and 'data' in payload['body']:
                return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
                
            # Check parts
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        if 'data' in part.get('body', {}):
                            return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                    # Check nested parts
                    if 'parts' in part:
                        for subpart in part['parts']:
                            if subpart.get('mimeType') == 'text/plain':
                                if 'data' in subpart.get('body', {}):
                                    return base64.urlsafe_b64decode(subpart['body']['data']).decode('utf-8', errors='ignore')
            return ''
        except:
            return ''
            
    def _parse_date(self, date_str: str) -> str:
        """Parse email date to YYYY-MM-DD."""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.strftime('%Y-%m-%d')
        except:
            return datetime.now().strftime('%Y-%m-%d')
            
    def _has_attachments(self, message: Dict) -> bool:
        """Check if message has attachments."""
        try:
            payload = message['payload']
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('filename'):
                        return True
                    if 'parts' in part:
                        for subpart in part['parts']:
                            if subpart.get('filename'):
                                return True
            return False
        except:
            return False
            
    def _get_attachments(self, service, message_id: str, message: Dict) -> List[Dict]:
        """Get attachment metadata and data."""
        attachments = []
        
        try:
            payload = message['payload']
            
            def process_parts(parts):
                for part in parts:
                    filename = part.get('filename', '')
                    if filename:
                        # Get attachment data
                        att_id = part['body'].get('attachmentId')
                        if att_id:
                            try:
                                att = service.users().messages().attachments().get(
                                    userId='me',
                                    messageId=message_id,
                                    id=att_id
                                ).execute()
                                
                                data = base64.urlsafe_b64decode(att['data'])
                                
                                attachments.append({
                                    'filename': filename,
                                    'mime_type': part.get('mimeType', ''),
                                    'size': len(data),
                                    'data': data  # Raw bytes
                                })
                            except:
                                pass
                                
                    # Recurse into nested parts
                    if 'parts' in part:
                        process_parts(part['parts'])
                        
            if 'parts' in payload:
                process_parts(payload['parts'])
                
        except Exception as e:
            print(f"   ⚠️ Error getting attachments: {e}")
            
        return attachments
        
    def _extract_amount(self, subject: str, body: str) -> Optional[float]:
        """Quick amount extraction (OCR pipeline will refine this)."""
        import re
        
        text = f"{subject} {body[:1000]}"
        patterns = [
            r'\$\s?([\d,]+\.?\d*)',
            r'Total[:\s]+\$?\s?([\d,]+\.?\d*)',
            r'Amount[:\s]+\$?\s?([\d,]+\.?\d*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except:
                    continue
        return None
        
    def _extract_merchant(self, subject: str, from_email: str) -> str:
        """Quick merchant extraction."""
        import re
        
        # Try to get from email domain
        domain_match = re.search(r'@([a-zA-Z0-9.-]+)', from_email)
        if domain_match:
            domain = domain_match.group(1).lower()
            # Clean up common patterns
            domain = domain.replace('.com', '').replace('.net', '').replace('.org', '')
            domain = domain.replace('mail.', '').replace('email.', '').replace('e.', '')
            return domain.title()
            
        return "Unknown"
        
    def mark_as_processed(self, account: str, message_id: str) -> bool:
        """
        Mark a receipt as processed (optional - move to Receipts/Processed).
        
        This prevents re-processing the same receipt.
        """
        service = self._get_service(account)
        if not service:
            return False
            
        try:
            # Get or create "Receipts/Processed" label
            processed_label_id = self._get_or_create_label(service, PROCESSED_LABEL_NAME)
            if not processed_label_id:
                return False
                
            # Get current "Receipts" label
            receipt_label_id = self._get_label_id(account)
            
            # Modify labels: remove "Receipts", add "Receipts/Processed"
            service.users().messages().modify(
                userId='me',
                id=message_id,
                body={
                    'removeLabelIds': [receipt_label_id] if receipt_label_id else [],
                    'addLabelIds': [processed_label_id]
                }
            ).execute()
            
            return True
            
        except Exception as e:
            print(f"   ⚠️ Error marking as processed: {e}")
            return False
            
    def scan_all_accounts(self, max_per_account: int = 50, since_hours: int = 24) -> Dict:
        """
        Scan all accounts for new receipts.
        
        Returns:
            Dict with receipts by account and stats
        """
        results = {
            'receipts': [],
            'stats': {
                'total': 0,
                'by_account': {}
            }
        }
        
        for account in ACCOUNTS:
            print(f"\n📬 Scanning {account}...")
            receipts = self.scan_receipt_label(account, max_per_account, since_hours)
            
            results['receipts'].extend(receipts)
            results['stats']['total'] += len(receipts)
            results['stats']['by_account'][account] = len(receipts)
            
        return results


# =============================================================================
# INTEGRATION HELPERS
# =============================================================================

def integrate_with_receiptai(receipt: Dict, scanner: GmailLabelScanner) -> bool:
    """
    Process a receipt through the full ReceiptAI pipeline.
    
    This is a helper that:
    1. Uploads attachments to R2
    2. Runs OCR extraction
    3. Saves to database
    4. Marks email as processed
    
    Args:
        receipt: Receipt dict from scan_receipt_label()
        scanner: GmailLabelScanner instance
        
    Returns:
        bool: Success status
    """
    if not RECEIPTAI_AVAILABLE:
        print("⚠️  ReceiptAI services not available")
        return False
        
    try:
        # Process attachments
        for attachment in receipt.get('attachments', []):
            filename = attachment['filename']
            data = attachment['data']
            
            # Check if it's an image or PDF
            mime = attachment.get('mime_type', '').lower()
            if not any(t in mime for t in ['image', 'pdf']):
                continue
                
            # Upload to R2
            r2_key = f"gmail/{receipt['gmail_account']}/{receipt['gmail_message_id']}/{filename}"
            r2_url = upload_to_r2(data, r2_key, mime)
            
            if r2_url:
                # Run OCR
                ocr_result = process_receipt_image(data, filename)
                
                # Merge OCR results into receipt
                if ocr_result:
                    receipt['ocr_merchant'] = ocr_result.get('merchant')
                    receipt['ocr_amount'] = ocr_result.get('total')
                    receipt['ocr_date'] = ocr_result.get('date')
                    receipt['r2_url'] = r2_url
                    
        # Save to database
        service = GmailReceiptService()
        receipt_id = service.save_receipt(receipt)
        
        if receipt_id:
            # Mark as processed
            scanner.mark_as_processed(
                receipt['gmail_account'],
                receipt['gmail_message_id']
            )
            return True
            
    except Exception as e:
        print(f"❌ Error integrating receipt: {e}")
        
    return False


# =============================================================================
# STANDALONE USAGE
# =============================================================================

if __name__ == '__main__':
    """
    Test the Gmail label scanner.
    
    Usage:
        python gmail_label_integration.py [account] [hours_back]
        
    Examples:
        python gmail_label_integration.py                    # Scan all accounts, last 24h
        python gmail_label_integration.py kaplan.brian@gmail.com 48  # Specific account, 48h
    """
    import sys
    
    print("=" * 70)
    print("GMAIL LABEL-BASED RECEIPT SCANNER")
    print("=" * 70)
    
    scanner = GmailLabelScanner()
    
    # Parse args
    account = sys.argv[1] if len(sys.argv) > 1 else None
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    
    if account:
        print(f"\n📬 Scanning {account} (last {hours} hours)...")
        receipts = scanner.scan_receipt_label(account, max_results=50, since_hours=hours)
    else:
        print(f"\n📬 Scanning all accounts (last {hours} hours)...")
        result = scanner.scan_all_accounts(max_per_account=50, since_hours=hours)
        receipts = result['receipts']
        print(f"\n📊 Stats: {result['stats']}")
        
    print(f"\n📋 Found {len(receipts)} receipts:\n")
    
    for i, r in enumerate(receipts, 1):
        print(f"{i}. {r.get('merchant', 'Unknown')} - ${r.get('amount', '?')}")
        print(f"   Subject: {r['email_subject'][:60]}...")
        print(f"   Date: {r['email_date']}")
        print(f"   Attachments: {len(r.get('attachments', []))}")
        print()
        
    print("=" * 70)
