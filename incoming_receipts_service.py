#!/usr/bin/env python3
"""
Incoming Receipts Service
Monitors Gmail for new receipts and intelligently filters out marketing emails
"""
import sqlite3
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import hashlib
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

# Lazy imports for optional dependencies (require system packages)
convert_from_bytes = None
imgkit = None

def _lazy_import_pdf2image():
    global convert_from_bytes
    if convert_from_bytes is None:
        try:
            from pdf2image import convert_from_bytes as _convert
            convert_from_bytes = _convert
        except ImportError:
            print("⚠️  pdf2image not available - PDF conversion disabled")
            convert_from_bytes = lambda *args, **kwargs: []
    return convert_from_bytes

def _lazy_import_imgkit():
    global imgkit
    if imgkit is None:
        try:
            import imgkit as _imgkit
            imgkit = _imgkit
        except ImportError:
            print("⚠️  imgkit not available - HTML screenshot disabled")
            imgkit = None
    return imgkit

load_dotenv()

# Import Gemini utility with automatic key fallback
from gemini_utils import generate_content_with_fallback, analyze_email_content, get_model as get_gemini_model

DB_PATH = "receipts.db"
RECEIPTS_DIR = "receipts/incoming"
GMAIL_TOKENS_DIR = "../Task/receipt-system/gmail_tokens"

# Smart filtering patterns
RECEIPT_INDICATORS = [
    'receipt', 'invoice', 'order confirmation', 'payment confirmation',
    'purchase confirmation', 'order receipt', 'transaction receipt',
    'order complete', 'payment received', 'charge receipt',
    'your order', 'order summary', 'payment summary'
]

MARKETING_PATTERNS = [
    'unsubscribe', 'view in browser', 'shop now', 'buy now',
    'limited time', 'sale', 'discount', 'promo', 'offer expires',
    'save now', 'deal', 'coupon', 'get % off', 'exclusive offer',
    'newsletter', 'follow us', 'join us'
]

# Personal subscription & service receipts (INCLUDE these)
PERSONAL_SERVICE_DOMAINS = [
    # AI/Creative Tools
    'anthropic.com', 'openai.com', 'midjourney.com', 'runway.ml', 'runwayml.com',
    'ideogram.ai', 'beautiful.ai', 'figma.com', 'canva.com',
    # Tech Services
    'apple.com', 'icloud.com', 'google.com', 'microsoft.com', 'adobe.com',
    'spotify.com', 'netflix.com', 'hulu.com', 'disney.com',
    # Business Tools
    'hive.com', 'notion.so', 'slack.com', 'zoom.us', 'dropbox.com',
    'github.com', 'vercel.com', 'railway.app', 'netlify.com', 'heroku.com',
    # Cloud/Hosting
    'cloudflare.com', 'aws.amazon.com', 'digitalocean.com',
    # Payment Processors (when they send receipts)
    'stripe.com', 'square.com', 'paypal.com'
]

# B2B/Vendor invoice patterns (EXCLUDE these)
VENDOR_INVOICE_PATTERNS = [
    'invoice', 'statement', 'bill due', 'payment due', 'overdue',
    'quote', 'estimate', 'proposal', 'net 30', 'net 60',
    'terms and conditions', 'purchase order', 'PO #',
    'account balance', 'outstanding balance', 'aging report'
]

# Notification patterns (EXCLUDE unless has amount/receipt)
NOTIFICATION_PATTERNS = [
    'payment failed', 'payment declined', 'card declined',
    'subscription will renew', 'subscription expiring', 'trial ending',
    'upcoming charge', 'upcoming payment', 'reminder:',
    'action required', 'verify your', 'confirm your',
    'activate your', 'welcome to', 'getting started',
    'introducing', 'new feature', 'update available'
]

# Co-worker/internal communication patterns (EXCLUDE these)
COWORKER_PATTERNS = [
    'scott siman', 'siman',  # Specific people
    'netsuite', 'quickbooks', 'internal app', 'app update',  # Business apps
    'meeting', 'call scheduled', 'zoom meeting', 'calendar invite',  # Meetings
    'please review', 'fyi', 'heads up', 're:', 'fwd:',  # Internal comms
]

# Artist/contract patterns (EXCLUDE these)
CONTRACT_PATTERNS = [
    'artist agreement', 'talent agreement', 'artist contract',
    'performance agreement', 'booking agreement', 'rider',
    'settlement sheet', 'tour', 'show date', 'venue',
    'contract', 'agreement', 'terms', 'signature required'
]

def init_incoming_receipts_table():
    """Initialize database table for incoming receipts"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incoming_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id TEXT UNIQUE NOT NULL,
            gmail_account TEXT NOT NULL,
            subject TEXT,
            from_email TEXT,
            from_domain TEXT,
            received_date TEXT,
            body_snippet TEXT,
            has_attachment BOOLEAN,
            attachment_count INTEGER DEFAULT 0,
            attachments TEXT,  -- JSON array of attachment metadata from Gmail
            receipt_files TEXT,  -- JSON array of downloaded file paths

            -- OCR extracted data
            merchant TEXT,
            amount REAL,
            transaction_date TEXT,
            ocr_confidence INTEGER,

            -- Gemini AI extracted data
            description TEXT,
            is_subscription BOOLEAN DEFAULT 0,
            matched_transaction_id INTEGER,
            match_type TEXT DEFAULT 'new',  -- 'new', 'needs_receipt', 'has_receipt'

            -- Classification
            is_receipt BOOLEAN DEFAULT 1,
            is_marketing BOOLEAN DEFAULT 0,
            confidence_score INTEGER,  -- 0-100

            -- Status
            status TEXT DEFAULT 'pending',  -- 'pending', 'accepted', 'rejected', 'processed'
            reviewed_at TEXT,
            accepted_as_transaction_id INTEGER,
            rejection_reason TEXT,

            -- Metadata
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT,

            FOREIGN KEY (accepted_as_transaction_id) REFERENCES transactions(_index)
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_incoming_status ON incoming_receipts(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_incoming_date ON incoming_receipts(received_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_incoming_account ON incoming_receipts(gmail_account)')

    # Create rejection learning table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incoming_rejection_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL,  -- 'domain', 'subject', 'sender'
            pattern_value TEXT NOT NULL,
            rejection_count INTEGER DEFAULT 1,
            last_rejected_at TEXT,
            UNIQUE(pattern_type, pattern_value)
        )
    ''')

    conn.commit()
    conn.close()

    print("✅ Incoming receipts table initialized")

def calculate_receipt_confidence(subject, from_email, body_snippet, has_attachment):
    """
    Calculate confidence that an email is a real PERSONAL receipt (0-100)

    Focus: Personal subscriptions (Anthropic, Midjourney, Apple, etc.)
    Exclude: B2B invoices, notifications, marketing
    """
    score = 50  # Start neutral

    subject_lower = subject.lower() if subject else ''
    body_lower = body_snippet.lower() if body_snippet else ''
    from_lower = from_email.lower() if from_email else ''

    # Extract domain
    domain = from_email.split('@')[-1] if '@' in from_email else ''

    # === STRONG NEGATIVE FILTERS (Auto-reject = 0) ===

    # 1. Forwards and replies
    if subject_lower.startswith('re:') or subject_lower.startswith('fwd:'):
        return 0

    # 2. Internal emails from yourself
    if any(x in from_email for x in ['kaplan.brian@gmail.com', 'brian@downhome.com', 'brian@musiccityrodeo.com']):
        return 0

    # 3. Generic vague subjects
    if subject_lower in ['account payment', 'payment', 'notification', 'update', 'message', 'alert']:
        return 0

    # 4. B2B Vendor invoices (net terms, statements, quotes)
    for pattern in VENDOR_INVOICE_PATTERNS:
        if pattern in subject_lower or pattern in body_lower:
            return 0

    # 5. Notifications/warnings (unless they have receipt keywords)
    has_receipt_keyword = any(kw in subject_lower for kw in ['receipt', 'order confirmation', 'payment confirmation'])
    if not has_receipt_keyword:
        for pattern in NOTIFICATION_PATTERNS:
            if pattern in subject_lower:
                return 0

    # 6. Co-worker/internal communications (Scott Siman, NetSuite, etc.)
    for pattern in COWORKER_PATTERNS:
        if pattern in subject_lower or pattern in body_lower or pattern in from_lower:
            print(f"      ✗ Rejected: Co-worker/internal pattern '{pattern}'")
            return 0

    # 7. Artist contracts and agreements
    for pattern in CONTRACT_PATTERNS:
        if pattern in subject_lower or pattern in body_lower:
            print(f"      ✗ Rejected: Contract pattern '{pattern}'")
            return 0

    # 8. DocuSign, proposals
    if 'docusign' in from_email.lower():
        print(f"      ✗ Rejected: DocuSign email")
        return 0

    # 9. Marketing emails
    marketing_count = sum(1 for p in MARKETING_PATTERNS if p in subject_lower or p in body_lower)
    if marketing_count >= 3:  # Strong marketing signal
        print(f"      ✗ Rejected: Marketing email ({marketing_count} patterns)")
        return 0

    # === POSITIVE SIGNALS ===

    # Personal service domains get HIGH priority
    if any(svc in domain for svc in PERSONAL_SERVICE_DOMAINS):
        score += 30  # Big boost for known services
        print(f"      ✓ Personal service domain: {domain}")

    # Receipt keywords
    for indicator in RECEIPT_INDICATORS:
        if indicator in subject_lower:
            score += 10
        if indicator in body_lower:
            score += 3

    # Has attachment (good sign for receipts)
    if has_attachment:
        score += 15

    # Has dollar amount in subject
    if '$' in subject or 'usd' in subject_lower:
        score += 10

    # === NEGATIVE SIGNALS ===

    # Marketing patterns (but not auto-reject)
    score -= marketing_count * 5

    # Newsletter/digest
    if 'newsletter' in subject_lower or 'digest' in subject_lower:
        score -= 15

    # Unsubscribe link
    if 'unsubscribe' in body_lower:
        score -= 10

    # Clamp to 0-100
    return max(0, min(100, score))

def extract_amount_from_text(text):
    """
    Extract dollar amount from text using regex patterns
    Returns: float amount or None
    """
    if not text:
        return None

    # Common patterns for amounts
    patterns = [
        r'\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',  # $199.00, $1,234.56
        r'(?:total|amount|charged|price|cost):\s*\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',  # Total: $199.00
        r'(?:USD|usd)\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',  # USD 199.00
        r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:USD|usd)',  # 199.00 USD
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Clean and convert first match
            amount_str = matches[0].replace(',', '')
            try:
                return float(amount_str)
            except:
                continue

    return None

def analyze_email_with_gemini(subject, from_email, body_text):
    """
    Use Gemini to extract structured data from email body
    Returns: (merchant, amount, description, is_subscription)
    """
    try:
        prompt = f"""You are analyzing a receipt/payment confirmation email. Extract these fields:

1. MERCHANT NAME - Clean company name (e.g., "Anthropic", "Apple", "Midjourney")
2. AMOUNT - The dollar amount charged. REQUIRED. Look for:
   - "$XX.XX" in subject or body
   - "Amount: XX.XX"
   - "Total: XX.XX"
   - "Charged: XX.XX"
   - If you can't find it, estimate based on typical pricing for this service
3. DESCRIPTION - What was purchased (e.g., "Claude Pro monthly subscription", "iCloud+ 2TB storage")
4. IS_SUBSCRIPTION - Is this a recurring monthly/yearly charge? (true/false)

Email Subject: {subject}
From: {from_email}
Body: {body_text[:2500]}

IMPORTANT: You MUST provide an amount. If not explicitly stated, use typical pricing:
- AI tools (Claude, ChatGPT): $20-200/mo
- Cloud storage: $1-10/mo
- Creative tools: $10-50/mo

Respond with ONLY valid JSON (no markdown, no code blocks):
{{
  "merchant": "Company Name",
  "amount": 199.00,
  "description": "Specific product/service description",
  "is_subscription": true
}}"""

        text = generate_content_with_fallback(prompt)
        if not text:
            raise Exception("Gemini returned empty response")
        text = text.strip()

        # Remove markdown code blocks if present
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
            text = text.rsplit('```', 1)[0]

        result = json.loads(text.strip())

        merchant = result.get('merchant')
        amount = result.get('amount')
        description = result.get('description')
        is_subscription = result.get('is_subscription', False)

        # If Gemini didn't extract amount, try regex fallback
        if not amount:
            print(f"      ⚠️  Gemini didn't extract amount, trying regex...")
            amount = extract_amount_from_text(subject + " " + body_text)
            if amount:
                print(f"      ✓ Regex extracted amount: ${amount}")

        return (merchant, amount, description, is_subscription)

    except Exception as e:
        print(f"      ⚠️  Gemini analysis failed: {e}")
        print(f"      → Using regex fallback for amount extraction...")

        # Fallback: Try to extract amount with regex
        amount = extract_amount_from_text(subject + " " + body_text)
        merchant_fallback, _ = extract_merchant_and_amount(subject, from_email, body_text[:500])

        if amount:
            print(f"      ✓ Regex extracted amount: ${amount}")
        if merchant_fallback:
            print(f"      ✓ Regex extracted merchant: {merchant_fallback}")

        return (merchant_fallback, amount, None, False)


def extract_merchant_and_amount(subject, from_email, body_snippet):
    """
    Extract merchant name and amount from email content (fallback)
    Returns: (merchant, amount)
    """
    import re

    merchant = None
    amount = None

    subject_lower = subject.lower() if subject else ''

    # Extract merchant from subject patterns
    merchant_patterns = [
        r'receipt from ([^#\n]+?)(?:\s*#|\s*$)',
        r'invoice from ([^#\n]+?)(?:\s*#|\s*$)',
        r'payment (?:to|from) ([^#\n]+?)(?:\s*#|\s*$)',
        r'your ([^#\n]+?) (?:receipt|invoice)',
        r'order from ([^#\n]+?)(?:\s*#|\s*$)',
    ]

    for pattern in merchant_patterns:
        match = re.search(pattern, subject_lower)
        if match:
            merchant = match.group(1).strip().title()
            merchant = re.sub(r',?\s*(?:Inc|LLC|Ltd|Corp)\.?$', '', merchant, flags=re.IGNORECASE)
            break

    if not merchant and from_email:
        domain = from_email.split('@')[-1] if '@' in from_email else ''
        if domain:
            if domain not in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']:
                company = domain.split('.')[0].title()
                if company and len(company) > 2:
                    merchant = company

    # Extract amount
    amount_patterns = [
        r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
        r'(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:USD|usd)',
        r'total[:\s]+\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
        r'amount[:\s]+\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
    ]

    search_text = subject + ' ' + (body_snippet or '')
    for pattern in amount_patterns:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '')
            try:
                amount = float(amount_str)
                break
            except ValueError:
                continue

    return merchant, amount


def find_matching_transaction(merchant, amount, transaction_date):
    """
    Check if a similar transaction already exists in the database
    Returns: (transaction_id, has_receipt, needs_receipt)
    """
    if not merchant:
        return None, False, False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Search for similar transactions within 7 days
    if transaction_date:
        try:
            date_obj = datetime.fromisoformat(transaction_date.split('T')[0])
            date_min = (date_obj - timedelta(days=7)).strftime('%Y-%m-%d')
            date_max = (date_obj + timedelta(days=7)).strftime('%Y-%m-%d')
        except:
            date_min = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            date_max = datetime.now().strftime('%Y-%m-%d')
    else:
        date_min = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        date_max = datetime.now().strftime('%Y-%m-%d')

    # Search by merchant name similarity
    merchant_pattern = f'%{merchant}%'

    cursor.execute('''
        SELECT _index, Chase_Description, Chase_Amount, Chase_Date, "Receipt File"
        FROM transactions
        WHERE Chase_Description LIKE ?
          AND Chase_Date BETWEEN ? AND ?
        ORDER BY Chase_Date DESC
        LIMIT 1
    ''', (merchant_pattern, date_min, date_max))

    result = cursor.fetchone()
    conn.close()

    if result:
        trans_id, desc, trans_amount, trans_date, receipt_file = result
        has_receipt = receipt_file and receipt_file.strip() != ''

        # Check amount match (within 10%)
        amount_match = False
        if amount and trans_amount:
            diff_pct = abs(amount - float(trans_amount)) / float(trans_amount) * 100
            amount_match = diff_pct < 10

        return trans_id, has_receipt, (not has_receipt and amount_match)

    return None, False, False


def download_gmail_attachment(service, message_id, attachment_id, filename):
    """
    Download an attachment from Gmail
    Returns: bytes of the attachment
    """
    try:
        attachment = service.users().messages().attachments().get(
            userId='me',
            messageId=message_id,
            id=attachment_id
        ).execute()

        file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
        return file_data
    except Exception as e:
        print(f"      ⚠️  Error downloading attachment: {e}")
        return None


def convert_pdf_to_jpg(pdf_bytes, output_path):
    """
    Convert PDF bytes to JPG image using multiple fallback methods.
    Method 1: PyMuPDF (fitz) - Pure Python, no external dependencies
    Method 2: pdf2image - Requires poppler-utils system package
    Returns: path to saved JPG file
    """
    # Method 1: Try PyMuPDF (no external dependencies - works on Railway!)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        # Render at 200 DPI for good quality
        mat = fitz.Matrix(200/72, 200/72)  # 72 is default PDF DPI
        pix = page.get_pixmap(matrix=mat)

        # Save as PNG first then convert to JPG for better compatibility
        png_path = output_path.replace('.jpg', '_temp.png')
        pix.save(png_path)
        doc.close()

        # Convert to JPG using Pillow
        from PIL import Image
        with Image.open(png_path) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            img.save(output_path, 'JPEG', quality=90)

        # Clean up temp PNG
        import os
        if os.path.exists(png_path):
            os.remove(png_path)

        print(f"      ✓ Converted PDF to JPG (PyMuPDF): {output_path}")
        return output_path
    except ImportError:
        print("      ⚠️  PyMuPDF not available, trying pdf2image...")
    except Exception as e:
        print(f"      ⚠️  PyMuPDF failed: {e}, trying pdf2image...")

    # Method 2: Fallback to pdf2image (requires poppler)
    try:
        pdf_convert = _lazy_import_pdf2image()
        images = pdf_convert(pdf_bytes, dpi=200, first_page=1, last_page=1)

        if images:
            images[0].save(output_path, 'JPEG', quality=90)
            print(f"      ✓ Converted PDF to JPG (pdf2image): {output_path}")
            return output_path
        return None
    except Exception as e:
        print(f"      ⚠️  Error converting PDF to JPG: {e}")
        return None


def screenshot_html_receipt(html_content, output_path):
    """
    Convert HTML email to JPG screenshot using multiple fallback methods.
    Returns: path to saved JPG file
    """
    # Ensure output is PNG for better quality, then convert to JPG
    png_path = output_path.replace('.jpg', '.png')
    temp_html = output_path.replace('.jpg', '_temp.html')

    try:
        # Save HTML to temp file
        with open(temp_html, 'w', encoding='utf-8') as f:
            # Wrap HTML with basic styling for better rendering
            wrapped_html = f'''<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 800px; margin: 0 auto; padding: 20px; background: white; }}
img {{ max-width: 100%; height: auto; }}
</style>
</head><body>{html_content}</body></html>'''
            f.write(wrapped_html)

        success = False

        # Method 1: Try Playwright (most reliable)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 800, 'height': 1200})
                page.goto(f'file://{os.path.abspath(temp_html)}')
                page.wait_for_load_state('networkidle')
                page.screenshot(path=png_path, full_page=True)
                browser.close()
            success = True
            print(f"      ✓ Screenshot via Playwright: {output_path}")
        except Exception as e1:
            print(f"      ⚠️  Playwright failed: {e1}")

        # Method 2: Try wkhtmltoimage if available
        if not success:
            try:
                import subprocess
                result = subprocess.run(['wkhtmltoimage', '--quality', '90', temp_html, png_path],
                                       capture_output=True, timeout=30)
                if result.returncode == 0:
                    success = True
                    print(f"      ✓ Screenshot via wkhtmltoimage: {output_path}")
            except Exception as e2:
                print(f"      ⚠️  wkhtmltoimage failed: {e2}")

        # Method 3: Try imgkit as last resort
        if not success:
            try:
                _imgkit = _lazy_import_imgkit()
                if _imgkit:
                    _imgkit.from_file(temp_html, png_path)
                    success = True
                    print(f"      ✓ Screenshot via imgkit: {output_path}")
            except Exception as e3:
                print(f"      ⚠️  imgkit failed: {e3}")

        # Convert PNG to JPG if successful
        if success and os.path.exists(png_path):
            from PIL import Image
            img = Image.open(png_path)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.save(output_path, 'JPEG', quality=90)
            os.remove(png_path)
            return output_path

        return None

    except Exception as e:
        print(f"      ⚠️  Error taking HTML screenshot: {e}")
        return None
    finally:
        # Clean up temp file
        if os.path.exists(temp_html):
            try:
                os.remove(temp_html)
            except:
                pass


def process_receipt_files(service, email_id, attachments, html_body=None):
    """
    Download and convert receipt files from Gmail email.
    Saves locally and uploads to R2 for cloud storage.
    Returns: list of saved file paths (R2 URLs if available, otherwise local paths)
    """
    saved_files = []
    local_files = []

    # Create receipts/incoming directory if doesn't exist
    os.makedirs(RECEIPTS_DIR, exist_ok=True)

    # Generate base filename from email ID
    base_filename = f"receipt_{email_id[:12]}"

    # Process attachments (PDFs)
    for i, attachment in enumerate(attachments):
        filename = attachment.get('filename', '')
        attachment_id = attachment.get('attachment_id', '')

        if not attachment_id:
            continue

        # Download attachment
        print(f"      📎 Downloading: {filename}")
        file_data = download_gmail_attachment(service, email_id, attachment_id, filename)

        if not file_data:
            continue

        # Check if it's a PDF
        if filename.lower().endswith('.pdf'):
            # Try to convert PDF to JPG
            output_path = os.path.join(RECEIPTS_DIR, f"{base_filename}_att{i}.jpg")
            result = convert_pdf_to_jpg(file_data, output_path)
            if result:
                local_files.append(result)
            else:
                # Fallback: save PDF directly if conversion fails
                pdf_output = os.path.join(RECEIPTS_DIR, f"{base_filename}_att{i}.pdf")
                with open(pdf_output, 'wb') as f:
                    f.write(file_data)
                local_files.append(pdf_output)
                print(f"      ✓ Saved PDF directly (conversion failed): {pdf_output}")
        else:
            # Save other attachments as-is
            output_path = os.path.join(RECEIPTS_DIR, f"{base_filename}_att{i}_{filename}")
            with open(output_path, 'wb') as f:
                f.write(file_data)
            local_files.append(output_path)
            print(f"      ✓ Saved attachment: {output_path}")

    # If no attachments but has HTML body, screenshot it
    if not local_files and html_body:
        print(f"      📸 Screenshotting HTML receipt...")
        output_path = os.path.join(RECEIPTS_DIR, f"{base_filename}_screenshot.jpg")
        result = screenshot_html_receipt(html_body, output_path)
        if result:
            local_files.append(result)

    # Upload to R2 for cloud storage
    try:
        from r2_service import upload_to_r2, R2_ENABLED
        if R2_ENABLED:
            for local_path in local_files:
                # Upload to R2
                filename = os.path.basename(local_path)
                r2_key = f"receipts/incoming/{filename}"
                success, result = upload_to_r2(local_path, r2_key)
                if success:
                    print(f"      ☁️  Uploaded to R2: {result}")
                    saved_files.append(result)  # R2 URL
                else:
                    print(f"      ⚠️  R2 upload failed: {result}")
                    saved_files.append(local_path)  # Fallback to local
        else:
            saved_files = local_files
    except ImportError:
        print(f"      ⚠️  R2 service not available, using local files")
        saved_files = local_files

    return saved_files


def is_likely_receipt(subject, from_email, body_snippet, has_attachment, min_confidence=60):
    """Check if email is likely a receipt based on content"""
    confidence = calculate_receipt_confidence(subject, from_email, body_snippet, has_attachment)
    return confidence >= min_confidence, confidence

def load_gmail_service(account_email):
    """Load Gmail API service for an account - checks multiple token sources"""
    token_file = f"tokens_{account_email.replace('@', '_').replace('.', '_')}.json"
    token_data = None

    # Try multiple token directories (for local and Railway deployments)
    token_dirs = [
        Path(GMAIL_TOKENS_DIR),
        Path('receipt-system/gmail_tokens'),
        Path('../Task/receipt-system/gmail_tokens'),
        Path('gmail_tokens'),
        Path('.'),
    ]

    for token_dir in token_dirs:
        token_path = token_dir / token_file
        if token_path.exists():
            try:
                with open(token_path, 'r') as f:
                    token_data = json.load(f)
                print(f"   ✓ Loaded token from {token_path}")
                break
            except Exception as e:
                print(f"   ⚠️  Could not read {token_path}: {e}")

    # Fallback: check environment variable (for Railway)
    if not token_data:
        env_key = f"GMAIL_TOKEN_{account_email.replace('@', '_').replace('.', '_').upper()}"
        env_token = os.getenv(env_key)
        if env_token:
            try:
                token_data = json.loads(env_token)
                print(f"   ✓ Loaded token from env {env_key}")
            except json.JSONDecodeError as e:
                print(f"   ⚠️  Invalid JSON in {env_key}: {e}")

    if not token_data:
        print(f"   ⚠️  Token not found for: {account_email}")
        return None

    try:
        creds = Credentials.from_authorized_user_info(token_data)
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        print(f"   ⚠️  Error loading Gmail service: {e}")
        return None

def get_learned_rejection_patterns():
    """Get patterns that user has consistently rejected"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT pattern_type, pattern_value, rejection_count
        FROM incoming_rejection_patterns
        WHERE rejection_count >= 2
    ''')

    patterns = {}
    for row in cursor.fetchall():
        pattern_type, value, count = row
        if pattern_type not in patterns:
            patterns[pattern_type] = []
        patterns[pattern_type].append(value)

    conn.close()
    return patterns

def record_rejection_pattern(from_email, subject):
    """Learn from rejection to improve future filtering"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Extract domain
    domain = from_email.split('@')[-1] if '@' in from_email else None

    if domain:
        cursor.execute('''
            INSERT INTO incoming_rejection_patterns (pattern_type, pattern_value, rejection_count, last_rejected_at)
            VALUES ('domain', ?, 1, ?)
            ON CONFLICT(pattern_type, pattern_value)
            DO UPDATE SET
                rejection_count = rejection_count + 1,
                last_rejected_at = ?
        ''', (domain, datetime.now().isoformat(), datetime.now().isoformat()))

    conn.commit()
    conn.close()

def scan_gmail_for_new_receipts(account_email, since_date='2024-09-01'):
    """
    Scan Gmail for new receipt emails

    Args:
        account_email: Gmail account to scan
        since_date: Only get emails after this date (YYYY-MM-DD)
    """
    service = load_gmail_service(account_email)
    if not service:
        return []

    print(f"\n📧 Scanning {account_email} for new receipts...")

    # Build query - NO attachment requirement! Get ALL receipt emails including HTML-only ones
    query_parts = [
        f'after:{since_date}',
        '(receipt OR invoice OR "order confirmation" OR "payment confirmation" OR "Your receipt" OR "payment received")',
        '-from:marketing -from:newsletter -from:noreply@github.com -from:notifications'
    ]
    query = ' '.join(query_parts)

    try:
        # Search for emails
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=50  # Limit to recent 50
        ).execute()

        messages = results.get('messages', [])
        print(f"   Found {len(messages)} potential receipts")

        new_receipts = []
        learned_patterns = get_learned_rejection_patterns()

        for msg in messages:
            try:
                # Get full message
                msg_data = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()

                # Extract metadata
                headers = msg_data.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
                from_email = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                date_str = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')

                # Parse from email
                from_clean = re.findall(r'<(.+?)>', from_email)
                from_email_clean = from_clean[0] if from_clean else from_email
                domain = from_email_clean.split('@')[-1] if '@' in from_email_clean else ''

                # Check if previously rejected domain
                if 'domain' in learned_patterns and domain in learned_patterns['domain']:
                    print(f"   ⊘ Skipping {subject[:40]} - learned rejection pattern")
                    continue

                # Get snippet
                snippet = msg_data.get('snippet', '')

                # Extract full email body
                def get_email_body(payload):
                    """Extract text body from email payload"""
                    body = ''
                    if 'parts' in payload:
                        for part in payload['parts']:
                            if part.get('mimeType') == 'text/plain':
                                data = part.get('body', {}).get('data', '')
                                if data:
                                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                                    break
                            elif part.get('mimeType') == 'text/html' and not body:
                                data = part.get('body', {}).get('data', '')
                                if data:
                                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    else:
                        data = payload.get('body', {}).get('data', '')
                        if data:
                            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    return body

                full_body = get_email_body(msg_data.get('payload', {}))

                # Check for attachments
                attachments = []
                parts = msg_data.get('payload', {}).get('parts', [])
                for part in parts:
                    if part.get('filename') and part.get('body', {}).get('attachmentId'):
                        attachments.append({
                            'filename': part['filename'],
                            'attachment_id': part['body']['attachmentId']
                        })

                has_attachment = len(attachments) > 0

                # Smart filtering
                is_receipt, confidence = is_likely_receipt(subject, from_email_clean, snippet, has_attachment)

                if not is_receipt:
                    print(f"   ⊘ Filtered out: {subject[:40]} (confidence: {confidence}%)")
                    continue

                # Use Gemini to analyze full email
                print(f"   ✓ Receipt candidate: {subject[:40]} ({confidence}% confidence)")
                print(f"      🤖 Analyzing with Gemini...")

                merchant_ai, amount_ai, description, is_subscription = analyze_email_with_gemini(
                    subject, from_email_clean, full_body or snippet
                )

                # Fallback to regex if Gemini fails
                if not merchant_ai:
                    merchant_ai, amount_ai = extract_merchant_and_amount(subject, from_email_clean, snippet)

                if merchant_ai or amount_ai:
                    print(f"      Extracted: {merchant_ai or 'Unknown'} ${amount_ai or '?'}")
                    if description:
                        print(f"      Description: {description}")

                # Check for matching transaction
                match_id, has_receipt, needs_receipt = find_matching_transaction(
                    merchant_ai, amount_ai, date_str
                )

                match_type = 'new'
                if match_id:
                    if has_receipt:
                        match_type = 'has_receipt'
                        print(f"      ⚠️  Transaction #{match_id} already has receipt - skipping")
                        continue  # Skip this receipt
                    elif needs_receipt:
                        match_type = 'needs_receipt'
                        print(f"      📎 Found matching transaction #{match_id} (needs receipt)")

                # Store receipt data
                receipt_data = {
                    'email_id': msg['id'],
                    'gmail_account': account_email,
                    'subject': subject,
                    'from_email': from_email_clean,
                    'from_domain': domain,
                    'received_date': date_str,
                    'body_snippet': snippet,
                    'has_attachment': has_attachment,
                    'attachment_count': len(attachments),
                    'attachments': json.dumps(attachments),  # JSON encode
                    'confidence_score': confidence,
                    'merchant': merchant_ai,
                    'amount': amount_ai,
                    'description': description,
                    'is_subscription': is_subscription,
                    'matched_transaction_id': match_id,
                    'match_type': match_type
                }

                new_receipts.append(receipt_data)

            except Exception as e:
                print(f"   ⚠️  Error processing message: {e}")
                continue

        return new_receipts

    except Exception as e:
        print(f"   ❌ Error scanning Gmail: {e}")
        return []

def save_incoming_receipt(receipt_data):
    """Save incoming receipt to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # First check if table has attachments column (for backwards compatibility)
        cursor.execute("PRAGMA table_info(incoming_receipts)")
        columns = {row[1] for row in cursor.fetchall()}
        has_attachments_col = 'attachments' in columns

        if has_attachments_col:
            cursor.execute('''
                INSERT INTO incoming_receipts (
                    email_id, gmail_account, subject, from_email, from_domain,
                    received_date, body_snippet, has_attachment, attachment_count,
                    confidence_score, merchant, amount, description, is_subscription,
                    matched_transaction_id, match_type, attachments, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ''', (
                receipt_data['email_id'],
                receipt_data['gmail_account'],
                receipt_data['subject'],
                receipt_data['from_email'],
                receipt_data['from_domain'],
                receipt_data['received_date'],
                receipt_data['body_snippet'],
                receipt_data['has_attachment'],
                receipt_data['attachment_count'],
                receipt_data['confidence_score'],
                receipt_data.get('merchant'),
                receipt_data.get('amount'),
                receipt_data.get('description'),
                receipt_data.get('is_subscription', False),
                receipt_data.get('matched_transaction_id'),
                receipt_data.get('match_type', 'new'),
                receipt_data.get('attachments', '[]')
            ))
        else:
            cursor.execute('''
                INSERT INTO incoming_receipts (
                    email_id, gmail_account, subject, from_email, from_domain,
                    received_date, body_snippet, has_attachment, attachment_count,
                    confidence_score, merchant, amount, description, is_subscription,
                    matched_transaction_id, match_type, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ''', (
                receipt_data['email_id'],
                receipt_data['gmail_account'],
                receipt_data['subject'],
                receipt_data['from_email'],
                receipt_data['from_domain'],
                receipt_data['received_date'],
                receipt_data['body_snippet'],
                receipt_data['has_attachment'],
                receipt_data['attachment_count'],
                receipt_data['confidence_score'],
                receipt_data.get('merchant'),
                receipt_data.get('amount'),
                receipt_data.get('description'),
                receipt_data.get('is_subscription', False),
                receipt_data.get('matched_transaction_id'),
                receipt_data.get('match_type', 'new')
            ))

        conn.commit()
        receipt_id = cursor.lastrowid
        print(f"   💾 Saved incoming receipt: {receipt_data['subject'][:40]}")
        return receipt_id

    except sqlite3.IntegrityError:
        # Already exists
        return None
    finally:
        conn.close()

if __name__ == '__main__':
    # Initialize database
    init_incoming_receipts_table()

    # Scan all Gmail accounts
    accounts = [
        'kaplan.brian@gmail.com',
        'brian@downhome.com',
        'brian@musiccityrodeo.com'
    ]

    total_found = 0

    for account in accounts:
        receipts = scan_gmail_for_new_receipts(account)

        for receipt in receipts:
            receipt_id = save_incoming_receipt(receipt)
            if receipt_id:
                total_found += 1

    print(f"\n✅ Found {total_found} new receipts")
