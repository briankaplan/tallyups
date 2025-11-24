"""
Inbox Zero Automation Service

Features:
- Auto-unsubscribe from promotional emails
- VIP sender protection (partners never auto-processed)
- Receipt extraction from emails
- Smart triage by urgency
- Daily automation for complete inbox zero

Integrated with:
- Gmail API (3 accounts)
- Anthropic AI (classification & urgency)
- R2 (receipt storage)
- Taskade (task routing)
"""

import os
import re
import json
import base64
from datetime import datetime, timedelta
from pathlib import Path
from email import message_from_bytes
import anthropic

# VIP Senders - Never auto-process or unsubscribe
VIP_SENDERS = [
    # Partners & Key Contacts
    'tim@',
    'patrick@',
    'reba@',
    # Family
    'miranda@',
    'luna@',
    # Business Critical
    'stripe.com',
    'square.com',
    'quickbooks',
    'bank',
    'chase.com',
    'paypal.com',
    # Add more VIPs as needed
]

# Unsubscribe keywords
UNSUBSCRIBE_KEYWORDS = [
    'unsubscribe',
    'opt out',
    'manage preferences',
    'email preferences',
    'stop receiving'
]

# Receipt indicators
RECEIPT_KEYWORDS = [
    'receipt',
    'invoice',
    'order confirmation',
    'payment confirmation',
    'your purchase',
    'transaction',
    'billing',
    'statement'
]

# Urgency indicators
URGENT_KEYWORDS = [
    'urgent',
    'asap',
    'immediate',
    'deadline',
    'important',
    'action required',
    'expires',
    'due date',
    'overdue',
    'final notice'
]


class InboxZeroService:
    """Automated inbox management service"""

    def __init__(self, gmail_service, anthropic_client, receipt_service, taskade_service):
        self.gmail = gmail_service
        self.ai = anthropic_client
        self.receipts = receipt_service
        self.taskade = taskade_service

    def is_vip_sender(self, email_from):
        """Check if sender is on VIP list"""
        email_lower = email_from.lower()
        return any(vip in email_lower for vip in VIP_SENDERS)

    def detect_unsubscribe_link(self, email_body):
        """Extract unsubscribe link from email"""
        # Look for unsubscribe links
        patterns = [
            r'https?://[^\s<>"]+unsubscribe[^\s<>"]*',
            r'https?://[^\s<>"]+opt-out[^\s<>"]*',
            r'https?://[^\s<>"]+preferences[^\s<>"]*'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, email_body, re.IGNORECASE)
            if matches:
                return matches[0]

        return None

    def is_promotional(self, subject, body, sender):
        """Detect if email is promotional"""
        # Skip VIPs
        if self.is_vip_sender(sender):
            return False

        # Check for promotional indicators
        promo_indicators = [
            'sale', 'discount', 'offer', 'deal', 'promo',
            '% off', 'save now', 'limited time', 'shop now',
            'free shipping', 'buy now', 'order now',
            'newsletter', 'update', 'this week'
        ]

        text = f"{subject} {body}".lower()
        promo_count = sum(1 for indicator in promo_indicators if indicator in text)

        # If 3+ promotional indicators, likely promotional
        return promo_count >= 3

    def has_receipt(self, subject, body):
        """Detect if email contains a receipt"""
        text = f"{subject} {body}".lower()
        return any(keyword in text for keyword in RECEIPT_KEYWORDS)

    def calculate_urgency(self, subject, body):
        """
        Calculate urgency score using AI

        Returns: 'urgent', 'normal', or 'low'
        """
        if not self.ai:
            # Fallback: keyword-based urgency
            text = f"{subject} {body}".lower()
            if any(keyword in text for keyword in URGENT_KEYWORDS):
                return 'urgent'
            return 'normal'

        try:
            prompt = f"""Analyze this email and determine urgency level.

Subject: {subject}
Body: {body[:500]}

Return ONLY one word: urgent, normal, or low

Criteria:
- urgent: Requires immediate action, has deadline, time-sensitive
- normal: Standard email, can be handled today
- low: FYI, no action needed, can wait

Return ONLY: urgent, normal, or low"""

            response = self.ai.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=10,
                messages=[{'role': 'user', 'content': prompt}]
            )

            urgency = response.content[0].text.strip().lower()
            return urgency if urgency in ['urgent', 'normal', 'low'] else 'normal'

        except Exception as e:
            print(f"Urgency calculation error: {e}")
            return 'normal'

    def extract_action_items(self, subject, body):
        """Extract action items from email using AI"""
        if not self.ai:
            return None

        try:
            prompt = f"""Extract action items from this email.

Subject: {subject}
Body: {body[:1000]}

Return a JSON array of action items, each with:
- task: Brief task description
- deadline: Extracted deadline if any (YYYY-MM-DD format)
- priority: urgent/normal/low

If no action items, return empty array: []

Return ONLY valid JSON array."""

            response = self.ai.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=500,
                messages=[{'role': 'user', 'content': prompt}]
            )

            actions = json.loads(response.content[0].text)
            return actions if isinstance(actions, list) else []

        except Exception as e:
            print(f"Action extraction error: {e}")
            return []

    def process_email(self, message_id, account_email):
        """
        Process a single email for inbox zero

        Returns:
            dict with processing results and actions taken
        """
        try:
            # Get full message
            message = self.gmail.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()

            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')

            # Get body
            body = self._extract_body(message)

            # Processing results
            result = {
                'message_id': message_id,
                'subject': subject,
                'sender': sender,
                'account': account_email,
                'actions_taken': [],
                'urgency': 'normal',
                'is_vip': False,
                'has_receipt': False,
                'unsubscribe_available': False
            }

            # 1. Check if VIP
            if self.is_vip_sender(sender):
                result['is_vip'] = True
                result['actions_taken'].append('VIP_PROTECTED')
                return result  # Don't auto-process VIPs

            # 2. Check for receipts
            if self.has_receipt(subject, body):
                result['has_receipt'] = True
                # Extract receipt (handled by receipt service)
                if self.receipts:
                    receipt_result = self._extract_and_upload_receipt(message, account_email)
                    if receipt_result:
                        result['actions_taken'].append(f"RECEIPT_EXTRACTED: {receipt_result['r2_url']}")

            # 3. Calculate urgency
            urgency = self.calculate_urgency(subject, body)
            result['urgency'] = urgency

            # 4. Check for unsubscribe
            if self.is_promotional(subject, body, sender):
                unsubscribe_link = self.detect_unsubscribe_link(body)
                if unsubscribe_link:
                    result['unsubscribe_available'] = True
                    result['unsubscribe_link'] = unsubscribe_link
                    result['actions_taken'].append('UNSUBSCRIBE_DETECTED')

            # 5. Extract action items
            actions = self.extract_action_items(subject, body)
            if actions:
                result['action_items'] = actions
                result['actions_taken'].append(f"ACTIONS_EXTRACTED: {len(actions)}")

                # Create Taskade tasks for urgent actions
                if urgency == 'urgent' and self.taskade:
                    for action in actions:
                        self._create_urgent_task(action, subject, sender)
                    result['actions_taken'].append('TASKADE_CREATED')

            # 6. Archive if processed
            if result['actions_taken']:
                self._archive_message(message_id)
                result['actions_taken'].append('ARCHIVED')

            return result

        except Exception as e:
            print(f"Error processing email {message_id}: {e}")
            return {'error': str(e), 'message_id': message_id}

    def _extract_body(self, message):
        """Extract email body text"""
        try:
            if 'parts' in message['payload']:
                for part in message['payload']['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data', '')
                        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            else:
                data = message['payload']['body'].get('data', '')
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        except:
            return ""

    def _extract_and_upload_receipt(self, message, account_email):
        """Extract receipt attachment and upload to R2"""
        # Check for attachments
        if 'parts' not in message['payload']:
            return None

        for part in message['payload']['parts']:
            filename = part.get('filename', '')
            if filename and any(ext in filename.lower() for ext in ['.pdf', '.png', '.jpg', '.html']):
                # Download attachment
                attachment_id = part['body'].get('attachmentId')
                if attachment_id:
                    attachment = self.gmail.users().messages().attachments().get(
                        userId='me',
                        messageId=message['id'],
                        id=attachment_id
                    ).execute()

                    # Upload to R2
                    if self.receipts:
                        data = base64.urlsafe_b64decode(attachment['data'])
                        result = self.receipts.upload_gmail_receipt(
                            data,
                            merchant='Email Receipt',
                            amount='',
                            date=datetime.now().strftime('%Y-%m-%d')
                        )
                        return result

        return None

    def _archive_message(self, message_id):
        """Archive (remove from inbox) a message"""
        try:
            self.gmail.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['INBOX']}
            ).execute()
            return True
        except:
            return False

    def _create_urgent_task(self, action, email_subject, sender):
        """Create Taskade task for urgent action"""
        task_content = f"""🚨 URGENT: {action['task']}

From: {sender}
Email: {email_subject}
Deadline: {action.get('deadline', 'ASAP')}
Priority: {action.get('priority', 'urgent')}"""

        # Create in appropriate project based on content
        # Default to TODAY project for urgent items
        if self.taskade:
            self.taskade.create_task('today', task_content)

    def run_daily_cleanup(self, account_email, max_emails=50):
        """
        Run daily inbox zero automation

        Args:
            account_email: Gmail account to process
            max_emails: Maximum emails to process in one run

        Returns:
            Summary of processing results
        """
        try:
            # Get unread messages
            results = self.gmail.users().messages().list(
                userId='me',
                q='is:unread',
                maxResults=max_emails
            ).execute()

            messages = results.get('messages', [])

            summary = {
                'total_processed': 0,
                'vip_protected': 0,
                'receipts_extracted': 0,
                'urgent_items': 0,
                'archived': 0,
                'unsubscribe_available': 0,
                'errors': 0
            }

            for msg in messages:
                result = self.process_email(msg['id'], account_email)

                if 'error' in result:
                    summary['errors'] += 1
                    continue

                summary['total_processed'] += 1

                if result['is_vip']:
                    summary['vip_protected'] += 1
                if result['has_receipt']:
                    summary['receipts_extracted'] += 1
                if result['urgency'] == 'urgent':
                    summary['urgent_items'] += 1
                if 'ARCHIVED' in result['actions_taken']:
                    summary['archived'] += 1
                if result.get('unsubscribe_available'):
                    summary['unsubscribe_available'] += 1

            # Calculate inbox zero achievement
            remaining = len(messages) - summary['archived']
            summary['inbox_zero_achieved'] = remaining == 0
            summary['remaining_emails'] = remaining

            return summary

        except Exception as e:
            return {'error': str(e)}


# Factory function
def create_inbox_zero_service(gmail_service, anthropic_client=None, receipt_service=None, taskade_service=None):
    """Create configured Inbox Zero service"""
    return InboxZeroService(gmail_service, anthropic_client, receipt_service, taskade_service)
