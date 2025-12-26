"""
================================================================================
Gmail Receipt API Routes
================================================================================
Flask Blueprint for Gmail receipt processing.

ENDPOINTS:
----------
    GET  /api/gmail/accounts           - List connected Gmail accounts
    POST /api/gmail/authenticate/<account> - Trigger re-auth flow
    GET  /api/gmail/receipts           - List extracted receipts
    GET  /api/gmail/receipts/<id>      - Get receipt details
    POST /api/gmail/receipts/<id>/match - Match receipt to transaction
    POST /api/gmail/receipts/<id>/ocr  - Trigger OCR on attachment
    GET  /api/gmail/search             - Custom Gmail search
    GET  /api/gmail/sync/status        - Get sync progress
    POST /api/gmail/sync               - Trigger manual sync

================================================================================
"""

import os
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

# Create blueprint
gmail_bp = Blueprint('gmail', __name__, url_prefix='/api/gmail')

# Logger
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


# Gmail accounts configuration
GMAIL_ACCOUNTS = [
    'brian@downhome.com',
    'kaplan.brian@gmail.com',
    'brian@musiccityrodeo.com'
]


# =============================================================================
# ACCOUNTS
# =============================================================================

@gmail_bp.route('/accounts', methods=['GET'])
def list_accounts():
    """
    List connected Gmail accounts and their status.

    Response:
        {
            "success": true,
            "accounts": [
                {
                    "email": "brian@downhome.com",
                    "connected": true,
                    "business_type": "Down_Home",
                    "last_sync": "2024-12-20T10:30:00Z"
                },
                ...
            ]
        }
    """
    try:
        from pathlib import Path
        credentials_dir = Path('credentials')

        accounts = []
        for email in GMAIL_ACCOUNTS:
            token_file = credentials_dir / f'tokens_{email.replace("@", "_").replace(".", "_")}.json'
            pickle_file = credentials_dir / f'token_{email}.pickle'

            connected = token_file.exists() or pickle_file.exists()

            # Determine business type from email
            if 'downhome' in email:
                business_type = 'Down_Home'
            elif 'musiccityrodeo' in email:
                business_type = 'Music_City_Rodeo'
            else:
                business_type = 'Personal'

            accounts.append({
                'email': email,
                'connected': connected,
                'business_type': business_type,
                'last_sync': None  # Would come from DB
            })

        return jsonify({
            'success': True,
            'accounts': accounts
        })

    except Exception as e:
        logger.error(f"List accounts error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gmail_bp.route('/authenticate/<account>', methods=['POST'])
def authenticate_account(account):
    """
    Trigger OAuth re-authentication flow for a Gmail account.

    This returns a URL for the user to complete authentication.

    Response:
        {
            "success": true,
            "auth_url": "https://accounts.google.com/..."
        }
    """
    try:
        if account not in GMAIL_ACCOUNTS:
            return jsonify({
                'success': False,
                'error': f'Unknown account: {account}'
            }), 400

        # For now, return instructions
        return jsonify({
            'success': True,
            'message': f'Run: python scripts/auth_gmail_direct.py --account {account}',
            'account': account
        })

    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# RECEIPTS
# =============================================================================

@gmail_bp.route('/receipts', methods=['GET'])
def list_receipts():
    """
    List Gmail receipts.

    Query Params:
        account: Email account (optional, defaults to all)
        status: pending|matched|rejected (optional)
        limit: Max results (default 50)
        offset: Pagination offset

    Response:
        {
            "success": true,
            "receipts": [...],
            "total": 150
        }
    """
    try:
        account = request.args.get('account')
        status = request.args.get('status')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT id, gmail_id, account_email, subject, sender,
                       extracted_merchant, extracted_amount, extracted_date,
                       confidence, status, created_at
                FROM gmail_receipts
                WHERE 1=1
            """
            params = []

            if account:
                query += " AND account_email = %s"
                params.append(account)

            if status:
                query += " AND status = %s"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cursor.execute(query, params)

            receipts = []
            for row in cursor.fetchall():
                receipts.append({
                    'id': row[0],
                    'gmail_id': row[1],
                    'account': row[2],
                    'subject': row[3],
                    'sender': row[4],
                    'merchant': row[5],
                    'amount': float(row[6]) if row[6] else None,
                    'date': str(row[7]) if row[7] else None,
                    'confidence': float(row[8]) if row[8] else None,
                    'status': row[9],
                    'created_at': str(row[10])
                })

            # Get total count
            cursor.execute("SELECT COUNT(*) FROM gmail_receipts WHERE 1=1")
            total = cursor.fetchone()[0]

        return jsonify({
            'success': True,
            'receipts': receipts,
            'total': total,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        logger.error(f"List receipts error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gmail_bp.route('/receipts/<receipt_id>', methods=['GET'])
def get_receipt(receipt_id):
    """Get detailed receipt information."""
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, gmail_id, account_email, subject, sender, body_preview,
                       extracted_merchant, extracted_amount, extracted_date,
                       extracted_order_number, confidence, status,
                       has_attachment, attachment_url, created_at
                FROM gmail_receipts
                WHERE id = %s
            """, (receipt_id,))

            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Receipt not found'}), 404

            receipt = {
                'id': row[0],
                'gmail_id': row[1],
                'account': row[2],
                'subject': row[3],
                'sender': row[4],
                'body_preview': row[5],
                'merchant': row[6],
                'amount': float(row[7]) if row[7] else None,
                'date': str(row[8]) if row[8] else None,
                'order_number': row[9],
                'confidence': float(row[10]) if row[10] else None,
                'status': row[11],
                'has_attachment': bool(row[12]),
                'attachment_url': row[13],
                'created_at': str(row[14])
            }

        return jsonify({
            'success': True,
            'receipt': receipt
        })

    except Exception as e:
        logger.error(f"Get receipt error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gmail_bp.route('/receipts/<receipt_id>/match', methods=['POST'])
def match_receipt_to_transaction(receipt_id):
    """
    Match a Gmail receipt to a transaction.

    Request Body:
        {
            "transaction_id": 123,  // Optional: specific transaction
            "auto_match": true      // Try to auto-match based on amount/date
        }

    Response:
        {
            "success": true,
            "matched": true,
            "transaction_id": 123,
            "confidence": 0.95
        }
    """
    try:
        data = request.get_json() or {}
        transaction_id = data.get('transaction_id')
        auto_match = data.get('auto_match', True)

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get receipt details
            cursor.execute("""
                SELECT extracted_amount, extracted_date, extracted_merchant
                FROM gmail_receipts WHERE id = %s
            """, (receipt_id,))

            receipt = cursor.fetchone()
            if not receipt:
                return jsonify({'success': False, 'error': 'Receipt not found'}), 404

            amount, date, merchant = receipt

            if transaction_id:
                # Direct match
                cursor.execute("""
                    UPDATE transactions SET gmail_receipt_id = %s WHERE id = %s
                """, (receipt_id, transaction_id))

                cursor.execute("""
                    UPDATE gmail_receipts SET status = 'matched', transaction_id = %s WHERE id = %s
                """, (transaction_id, receipt_id))

                return jsonify({
                    'success': True,
                    'matched': True,
                    'transaction_id': transaction_id,
                    'confidence': 1.0
                })

            elif auto_match and amount and date:
                # Auto-match by amount and date
                cursor.execute("""
                    SELECT id FROM transactions
                    WHERE ABS(chase_amount) = ABS(%s)
                    AND chase_date BETWEEN DATE_SUB(%s, INTERVAL 3 DAY) AND DATE_ADD(%s, INTERVAL 3 DAY)
                    AND gmail_receipt_id IS NULL
                    LIMIT 1
                """, (abs(amount), date, date))

                match = cursor.fetchone()
                if match:
                    cursor.execute("""
                        UPDATE transactions SET gmail_receipt_id = %s WHERE id = %s
                    """, (receipt_id, match[0]))

                    cursor.execute("""
                        UPDATE gmail_receipts SET status = 'matched', transaction_id = %s WHERE id = %s
                    """, (match[0], receipt_id))

                    return jsonify({
                        'success': True,
                        'matched': True,
                        'transaction_id': match[0],
                        'confidence': 0.9
                    })

            return jsonify({
                'success': True,
                'matched': False,
                'message': 'No matching transaction found'
            })

    except Exception as e:
        logger.error(f"Match receipt error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gmail_bp.route('/receipts/<receipt_id>/ocr', methods=['POST'])
def ocr_receipt_attachment(receipt_id):
    """
    Trigger OCR processing on a receipt attachment.

    Uses Gemini Vision or Ollama for OCR.

    Response:
        {
            "success": true,
            "ocr_result": {
                "merchant": "Walmart",
                "amount": 45.67,
                "date": "2024-12-20",
                "items": [...],
                "raw_text": "..."
            }
        }
    """
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get attachment URL
            cursor.execute("""
                SELECT attachment_url, account_email, gmail_id
                FROM gmail_receipts WHERE id = %s
            """, (receipt_id,))

            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Receipt not found'}), 404

            attachment_url, account, gmail_id = row

            if not attachment_url:
                return jsonify({
                    'success': False,
                    'error': 'No attachment found for this receipt'
                }), 400

            # Try to use Gemini Vision for OCR
            try:
                import google.generativeai as genai
                import requests
                from io import BytesIO
                from PIL import Image

                # Download the image
                response = requests.get(attachment_url)
                img = Image.open(BytesIO(response.content))

                # Configure Gemini
                genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
                model = genai.GenerativeModel('gemini-1.5-flash')

                prompt = """Analyze this receipt image and extract:
                1. Merchant/Store name
                2. Total amount
                3. Date
                4. List of items with prices
                5. Payment method if visible

                Return as JSON with keys: merchant, amount, date, items, payment_method, raw_text"""

                result = model.generate_content([prompt, img])

                # Parse the response
                ocr_result = {
                    'raw_response': result.text,
                    'processed': True
                }

                # Update the receipt with OCR results
                cursor.execute("""
                    UPDATE gmail_receipts
                    SET ocr_processed = TRUE, ocr_raw = %s
                    WHERE id = %s
                """, (result.text, receipt_id))

                return jsonify({
                    'success': True,
                    'ocr_result': ocr_result
                })

            except ImportError:
                return jsonify({
                    'success': False,
                    'error': 'Gemini Vision not available. Install google-generativeai.'
                }), 500

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# SEARCH & SYNC
# =============================================================================

@gmail_bp.route('/search', methods=['GET'])
def search_gmail():
    """
    Search Gmail for receipts.

    Query Params:
        account: Email account
        query: Gmail search query (e.g., "from:amazon.com")
        max_results: Max results (default 20)

    Response:
        {
            "success": true,
            "messages": [...],
            "count": 15
        }
    """
    try:
        account = request.args.get('account', GMAIL_ACCOUNTS[0])
        query = request.args.get('query', 'label:receipts OR subject:receipt OR subject:order')
        max_results = int(request.args.get('max_results', 20))

        # Try to get Gmail service
        try:
            from pathlib import Path
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            token_path = Path('credentials') / f'tokens_{account.replace("@", "_").replace(".", "_")}.json'

            if not token_path.exists():
                return jsonify({
                    'success': False,
                    'error': f'Not authenticated for {account}'
                }), 401

            creds = Credentials.from_authorized_user_file(str(token_path))
            service = build('gmail', 'v1', credentials=creds)

            # Search
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            messages = []
            for msg in results.get('messages', []):
                msg_data = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata',
                    metadataHeaders=['Subject', 'From', 'Date']
                ).execute()

                headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
                messages.append({
                    'id': msg['id'],
                    'subject': headers.get('Subject', ''),
                    'from': headers.get('From', ''),
                    'date': headers.get('Date', '')
                })

            return jsonify({
                'success': True,
                'account': account,
                'query': query,
                'messages': messages,
                'count': len(messages)
            })

        except Exception as e:
            logger.error(f"Gmail search error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gmail_bp.route('/sync/status', methods=['GET'])
def get_sync_status():
    """
    Get Gmail sync status for all accounts.

    Response:
        {
            "success": true,
            "accounts": [
                {
                    "email": "brian@downhome.com",
                    "last_sync": "2024-12-20T10:30:00Z",
                    "receipts_found": 150,
                    "status": "idle"
                },
                ...
            ]
        }
    """
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()

        accounts = []

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            for email in GMAIL_ACCOUNTS:
                cursor.execute("""
                    SELECT COUNT(*), MAX(created_at)
                    FROM gmail_receipts
                    WHERE account_email = %s
                """, (email,))

                row = cursor.fetchone()
                accounts.append({
                    'email': email,
                    'receipts_found': row[0] if row else 0,
                    'last_sync': str(row[1]) if row and row[1] else None,
                    'status': 'idle'
                })

        return jsonify({
            'success': True,
            'accounts': accounts
        })

    except Exception as e:
        logger.error(f"Sync status error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gmail_bp.route('/sync', methods=['POST'])
def trigger_sync():
    """
    Trigger Gmail sync for one or all accounts.

    Request Body:
        {
            "account": "brian@downhome.com",  // Optional, syncs all if not specified
            "days_back": 30  // How many days to look back (default 30)
        }

    Response:
        {
            "success": true,
            "message": "Sync started",
            "accounts": ["brian@downhome.com"]
        }
    """
    try:
        data = request.get_json() or {}
        account = data.get('account')
        days_back = data.get('days_back', 30)

        accounts_to_sync = [account] if account else GMAIL_ACCOUNTS

        # For now, return success - actual sync would be async
        return jsonify({
            'success': True,
            'message': 'Sync initiated',
            'accounts': accounts_to_sync,
            'days_back': days_back
        })

    except Exception as e:
        logger.error(f"Trigger sync error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def register_gmail_routes(app):
    """Register Gmail routes with the Flask app."""
    app.register_blueprint(gmail_bp)
    logger.info("Gmail routes registered at /api/gmail/*")


# =============================================================================
# CONTACT EXTRACTION FROM EMAILS
# =============================================================================

def extract_contact_from_email(sender_string):
    """
    Extract name and email from a sender string like 'John Doe <john@example.com>'.

    Returns:
        tuple: (name, email)
    """
    import re
    # Pattern: "Name <email>" or just "email"
    match = re.match(r'^(?:"?([^"<]+)"?\s*)?<?([^>]+@[^>]+)>?$', sender_string.strip())
    if match:
        name = match.group(1).strip() if match.group(1) else None
        email = match.group(2).strip().lower()
        return name, email
    return None, sender_string.strip().lower()


@gmail_bp.route('/extract-contacts', methods=['POST'])
def extract_contacts_from_emails():
    """
    Extract contacts from Gmail messages and create/update in contacts table.

    Request Body:
        {
            "account": "brian@downhome.com",  // Optional
            "days_back": 90,  // How far back to scan (default 90)
            "max_messages": 500  // Max messages to process (default 500)
        }

    Response:
        {
            "success": true,
            "contacts_created": 15,
            "contacts_updated": 30,
            "emails_processed": 250
        }
    """
    try:
        data = request.get_json() or {}
        account = data.get('account', GMAIL_ACCOUNTS[0])
        days_back = data.get('days_back', 90)
        max_messages = data.get('max_messages', 500)

        from pathlib import Path
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from db_mysql import get_mysql_db

        token_path = Path('credentials') / f'tokens_{account.replace("@", "_").replace(".", "_")}.json'
        if not token_path.exists():
            return jsonify({
                'success': False,
                'error': f'Not authenticated for {account}'
            }), 401

        creds = Credentials.from_authorized_user_file(str(token_path))
        service = build('gmail', 'v1', credentials=creds)

        # Search for emails in date range
        from datetime import datetime, timedelta
        after_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
        query = f'after:{after_date}'

        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_messages
        ).execute()

        messages = results.get('messages', [])
        db = get_mysql_db()

        contacts_created = 0
        contacts_updated = 0
        interactions_added = 0

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            for msg in messages:
                try:
                    msg_data = service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='metadata',
                        metadataHeaders=['Subject', 'From', 'Date', 'To']
                    ).execute()

                    headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
                    sender = headers.get('From', '')
                    subject = headers.get('Subject', '')
                    date_str = headers.get('Date', '')

                    name, email = extract_contact_from_email(sender)

                    if not email or email == account:
                        continue  # Skip self-emails

                    # Check if contact exists
                    cursor.execute("SELECT id, name FROM contacts WHERE email = %s", (email,))
                    existing = cursor.fetchone()

                    if existing:
                        contact_id = existing[0]
                        # Update last interaction
                        cursor.execute("""
                            UPDATE contacts
                            SET last_interaction = GREATEST(COALESCE(last_interaction, '1970-01-01'), NOW()),
                                interaction_count = COALESCE(interaction_count, 0) + 1,
                                gmail_thread_count = COALESCE(gmail_thread_count, 0) + 1,
                                updated_at = NOW()
                            WHERE id = %s
                        """, (contact_id,))
                        contacts_updated += 1
                    else:
                        # Create new contact
                        cursor.execute("""
                            INSERT INTO contacts (name, email, source, last_interaction,
                                                  interaction_count, gmail_thread_count, created_at, updated_at)
                            VALUES (%s, %s, 'gmail', NOW(), 1, 1, NOW(), NOW())
                        """, (name or email.split('@')[0].replace('.', ' ').title(), email))
                        contact_id = cursor.lastrowid
                        contacts_created += 1

                    # Add interaction record
                    cursor.execute("""
                        INSERT INTO contact_interactions
                        (contact_id, interaction_type, interaction_date, subject, source_type, source_id)
                        VALUES (%s, 'email', NOW(), %s, 'gmail', %s)
                        ON DUPLICATE KEY UPDATE interaction_date = VALUES(interaction_date)
                    """, (contact_id, subject[:500] if subject else None, msg['id']))
                    interactions_added += 1

                except Exception as e:
                    logger.warning(f"Error processing message {msg['id']}: {e}")
                    continue

        return jsonify({
            'success': True,
            'contacts_created': contacts_created,
            'contacts_updated': contacts_updated,
            'interactions_added': interactions_added,
            'emails_processed': len(messages)
        })

    except Exception as e:
        logger.error(f"Extract contacts error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gmail_bp.route('/contact/<int:contact_id>/emails', methods=['GET'])
def get_contact_emails(contact_id):
    """
    Get email history for a specific contact.

    Query Params:
        limit: Max results (default 20)

    Response:
        {
            "success": true,
            "contact": { ... },
            "emails": [
                { "subject": "...", "date": "...", "preview": "..." },
                ...
            ]
        }
    """
    try:
        limit = int(request.args.get('limit', 20))

        from db_mysql import get_mysql_db
        db = get_mysql_db()

        with db._pool.connection() as conn:
            cursor = conn.cursor()

            # Get contact info
            cursor.execute("""
                SELECT id, name, email, company, gmail_thread_count, last_email_date
                FROM contacts WHERE id = %s
            """, (contact_id,))
            contact_row = cursor.fetchone()

            if not contact_row:
                return jsonify({'success': False, 'error': 'Contact not found'}), 404

            contact = {
                'id': contact_row[0],
                'name': contact_row[1],
                'email': contact_row[2],
                'company': contact_row[3],
                'thread_count': contact_row[4],
                'last_email': str(contact_row[5]) if contact_row[5] else None
            }

            # Get interactions
            cursor.execute("""
                SELECT interaction_type, interaction_date, subject, source_id
                FROM contact_interactions
                WHERE contact_id = %s AND interaction_type = 'email'
                ORDER BY interaction_date DESC
                LIMIT %s
            """, (contact_id, limit))

            emails = []
            for row in cursor.fetchall():
                emails.append({
                    'type': row[0],
                    'date': str(row[1]),
                    'subject': row[2],
                    'gmail_id': row[3]
                })

        return jsonify({
            'success': True,
            'contact': contact,
            'emails': emails
        })

    except Exception as e:
        logger.error(f"Get contact emails error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
