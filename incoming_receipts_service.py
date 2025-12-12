#!/usr/bin/env python3
"""
Incoming Receipts Service
Monitors Gmail for new receipts and intelligently filters out marketing emails

OPTIMIZED FOR RAILWAY:
- Uses PyMuPDF (fitz) for PDF conversion - pure Python, no external deps
- All receipt images uploaded to R2 with thumbnails
- Fast MySQL operations with connection pooling
"""
import pymysql
import pymysql.cursors
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import hashlib
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

# =============================================================================
# PDF TO IMAGE CONVERSION - PyMuPDF (Pure Python, Railway Compatible)
# =============================================================================

def convert_pdf_to_image(pdf_bytes: bytes) -> bytes:
    """
    Convert PDF to JPG image using PyMuPDF (fitz).
    Pure Python - works on Railway without external dependencies.

    Returns: JPG image bytes or None if conversion fails
    """
    try:
        import fitz  # PyMuPDF

        # Open PDF from bytes
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        if len(pdf_doc) == 0:
            print("      ⚠️  PDF has no pages")
            return None

        # Get first page (most receipts are single page)
        page = pdf_doc[0]

        # Render at 2x resolution for clarity
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)

        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # If PDF has multiple pages, append them vertically (for multi-page receipts)
        if len(pdf_doc) > 1:
            images = [img]
            for i in range(1, min(len(pdf_doc), 5)):  # Max 5 pages
                page = pdf_doc[i]
                pix = page.get_pixmap(matrix=mat)
                page_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(page_img)

            # Calculate total height
            total_height = sum(im.height for im in images)
            max_width = max(im.width for im in images)

            # Create combined image
            combined = Image.new('RGB', (max_width, total_height), 'white')
            y_offset = 0
            for im in images:
                combined.paste(im, (0, y_offset))
                y_offset += im.height
            img = combined

        pdf_doc.close()

        # Convert to JPEG bytes
        output = BytesIO()
        img.save(output, format='JPEG', quality=90, optimize=True)
        return output.getvalue()

    except ImportError:
        print("      ⚠️  PyMuPDF not available - install with: pip install PyMuPDF")
        return None
    except Exception as e:
        print(f"      ⚠️  PDF conversion failed: {e}")
        return None


def convert_html_to_image(html_content: str) -> bytes:
    """
    Convert HTML email to image using Playwright browser rendering.
    This captures the ACTUAL visual appearance of the email, not just text.

    Returns: JPG image bytes or None
    """
    # Try Playwright first (best quality - actual browser rendering)
    try:
        from playwright.sync_api import sync_playwright
        import shutil

        print("      📸 Using Playwright for HTML screenshot...")

        with sync_playwright() as p:
            # Try to launch with bundled browser first, fall back to system chromium
            browser = None

            # First try bundled Playwright browser
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                print(f"      ℹ️  Bundled browser not found, trying system chromium...")
                # Look for system chromium/chrome - include nix paths for Railway
                chromium_paths = [
                    '/usr/bin/chromium',
                    '/usr/bin/chromium-browser',
                    '/usr/bin/google-chrome',
                    '/usr/bin/google-chrome-stable',
                    shutil.which('chromium'),
                    shutil.which('chromium-browser'),
                    shutil.which('google-chrome'),
                ]

                # Also check nix store paths (Railway uses nixpacks)
                import glob
                nix_chromium = glob.glob('/nix/store/*-chromium-*/bin/chromium')
                if nix_chromium:
                    chromium_paths.extend(nix_chromium)
                    print(f"      🔍 Found nix chromium: {nix_chromium}")

                for chrome_path in chromium_paths:
                    if chrome_path and os.path.exists(chrome_path):
                        print(f"      🔧 Using system browser: {chrome_path}")
                        try:
                            browser = p.chromium.launch(headless=True, executable_path=chrome_path)
                            break
                        except Exception as launch_err:
                            print(f"      ⚠️  Failed to launch {chrome_path}: {launch_err}")
                            continue

                if not browser:
                    raise Exception(f"No chromium browser found: {e}")
            page = browser.new_page(viewport={'width': 800, 'height': 1200})

            # Wrap HTML in a proper document structure with styling
            wrapped_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                        background: white;
                        margin: 0;
                        padding: 20px;
                        max-width: 800px;
                        line-height: 1.5;
                        color: #333;
                    }}
                    img {{ max-width: 100%; height: auto; }}
                    table {{ max-width: 100%; border-collapse: collapse; }}
                    td, th {{ padding: 8px; border: 1px solid #ddd; }}
                    a {{ color: #0066cc; }}
                </style>
            </head>
            <body>
                {html_content}
            </body>
            </html>
            """

            # Set content and wait for rendering
            page.set_content(wrapped_html, wait_until='networkidle', timeout=10000)

            # Wait a bit for any images/fonts to load
            page.wait_for_timeout(500)

            # Get the actual content height
            body_height = page.evaluate('document.body.scrollHeight')

            # Cap height at 3000px to avoid huge images
            screenshot_height = min(body_height + 40, 3000)

            # Take full-page screenshot
            page.set_viewport_size({'width': 800, 'height': screenshot_height})
            png_bytes = page.screenshot(type='png', full_page=True)

            browser.close()

            # Convert PNG to JPEG for smaller file size
            from PIL import Image
            img = Image.open(BytesIO(png_bytes))

            # Ensure RGB mode (no alpha channel for JPEG)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            output = BytesIO()
            img.save(output, format='JPEG', quality=90, optimize=True)

            print(f"      ✅ Playwright screenshot: {len(output.getvalue())} bytes")
            return output.getvalue()

    except Exception as e:
        import traceback
        print(f"      ⚠️  Playwright failed: {e}")
        print(f"      📋 Traceback: {traceback.format_exc()}")

    # Try wkhtmltoimage as second option (better than text fallback)
    try:
        import subprocess
        import tempfile
        import shutil

        wkhtmltoimage_path = shutil.which('wkhtmltoimage')
        if wkhtmltoimage_path:
            print(f"      📸 Trying wkhtmltoimage fallback...")

            # Wrap HTML in document structure
            wrapped_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, Helvetica, sans-serif;
            background: white;
            margin: 0;
            padding: 20px;
            max-width: 800px;
            line-height: 1.5;
            color: #333;
        }}
        img {{ max-width: 100%; height: auto; }}
        table {{ max-width: 100%; border-collapse: collapse; }}
        td, th {{ padding: 8px; border: 1px solid #ddd; }}
        a {{ color: #0066cc; }}
    </style>
</head>
<body>
    {html_content}
</body>
</html>"""

            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as html_file:
                html_file.write(wrapped_html)
                html_path = html_file.name

            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as img_file:
                img_path = img_file.name

            try:
                result = subprocess.run(
                    [wkhtmltoimage_path, '--quality', '90', '--width', '800',
                     '--disable-smart-width', html_path, img_path],
                    capture_output=True, timeout=30
                )

                if result.returncode == 0 and os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        jpg_bytes = f.read()
                    if len(jpg_bytes) > 1000:  # Sanity check
                        print(f"      ✅ wkhtmltoimage screenshot: {len(jpg_bytes)} bytes")
                        return jpg_bytes
                else:
                    print(f"      ⚠️  wkhtmltoimage failed: {result.stderr.decode()[:200]}")
            finally:
                # Clean up temp files
                try:
                    os.unlink(html_path)
                    os.unlink(img_path)
                except:
                    pass
    except Exception as e:
        print(f"      ⚠️  wkhtmltoimage fallback failed: {e}")

    # Fallback to text-based rendering if all else fails
    try:
        from PIL import Image, ImageDraw, ImageFont
        import re

        print("      📝 Falling back to text-based rendering...")

        # Extract text content from HTML
        html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html_clean, flags=re.DOTALL | re.IGNORECASE)

        # Convert common HTML entities
        html_clean = html_clean.replace('&nbsp;', ' ')
        html_clean = html_clean.replace('&amp;', '&')
        html_clean = html_clean.replace('&lt;', '<')
        html_clean = html_clean.replace('&gt;', '>')
        html_clean = html_clean.replace('&quot;', '"')
        html_clean = html_clean.replace('&#39;', "'")

        # Convert <br> and block elements to newlines
        html_clean = re.sub(r'<br\s*/?>', '\n', html_clean, flags=re.IGNORECASE)
        html_clean = re.sub(r'</(?:p|div|tr|li|h[1-6])>', '\n', html_clean, flags=re.IGNORECASE)

        # Remove remaining HTML tags
        text = re.sub(r'<[^>]+>', '', html_clean)

        # Clean up whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines[:100])

        if len(text) < 20:
            return None

        # Create image
        width = 800
        padding = 40
        line_height = 20
        num_lines = len(text.split('\n'))
        height = max(400, min(2000, num_lines * line_height + padding * 2))

        img = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
            except:
                font = ImageFont.load_default()

        y = padding
        for line in text.split('\n')[:100]:
            if y > height - padding:
                break
            if len(line) > 90:
                line = line[:87] + '...'
            draw.text((padding, y), line, fill='black', font=font)
            y += line_height

        output = BytesIO()
        img.save(output, format='JPEG', quality=85)
        return output.getvalue()

    except Exception as e:
        print(f"      ⚠️  HTML to image failed: {e}")
        return None


# Legacy imports for backwards compatibility
convert_from_bytes = None
imgkit = None

def _lazy_import_pdf2image():
    """Legacy - now uses PyMuPDF instead"""
    global convert_from_bytes
    if convert_from_bytes is None:
        # Try PyMuPDF first (preferred)
        try:
            import fitz
            # Wrap in pdf2image-compatible interface
            def _convert(pdf_bytes, **kwargs):
                img_bytes = convert_pdf_to_image(pdf_bytes)
                if img_bytes:
                    return [Image.open(BytesIO(img_bytes))]
                return []
            convert_from_bytes = _convert
            print("✅ Using PyMuPDF for PDF conversion")
        except ImportError:
            # Fall back to pdf2image
            try:
                from pdf2image import convert_from_bytes as _convert
                convert_from_bytes = _convert
                print("⚠️  Using pdf2image (requires poppler)")
            except ImportError:
                print("⚠️  No PDF converter available")
                convert_from_bytes = lambda *args, **kwargs: []
    return convert_from_bytes

def _lazy_import_imgkit():
    global imgkit
    if imgkit is None:
        try:
            import imgkit as _imgkit
            imgkit = _imgkit
        except ImportError:
            # Not a problem - we have convert_html_to_image as fallback
            imgkit = None
    return imgkit

load_dotenv()

# Import OpenAI for email analysis (priority over Gemini due to rate limits)
from openai import OpenAI
OPENAI_CLIENT = None

def get_openai_client():
    """Get or create OpenAI client"""
    global OPENAI_CLIENT
    if OPENAI_CLIENT is None:
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            OPENAI_CLIENT = OpenAI(api_key=api_key)
    return OPENAI_CLIENT

# Keep Gemini as fallback only
try:
    from gemini_utils import generate_content_with_fallback, analyze_email_content, get_model as get_gemini_model
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    generate_content_with_fallback = None
    analyze_email_content = None
    get_gemini_model = None

# MySQL Connection Configuration (Railway)
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'metro.proxy.rlwy.net'),
    'port': int(os.getenv('MYSQL_PORT', 19800)),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'xruqdfYXOPFlfkqAPaRCrPFqxMaXMuiL'),
    'database': os.getenv('MYSQL_DATABASE', 'railway'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_db_connection():
    """Get MySQL database connection"""
    return pymysql.connect(**MYSQL_CONFIG)

# Cache for subscription merchants loaded from database
_SUBSCRIPTION_MERCHANTS_CACHE = None
_SUBSCRIPTION_MERCHANTS_CACHE_TIME = None

def load_subscription_merchants():
    """
    Load known subscription merchants from database.
    Sources:
    1. merchants table (is_subscription=1)
    2. transactions table (recurring charges - merchants appearing 3+ times)
    Returns dict of normalized_name -> {avg_amount, frequency, category, source}
    """
    global _SUBSCRIPTION_MERCHANTS_CACHE, _SUBSCRIPTION_MERCHANTS_CACHE_TIME
    from datetime import datetime

    # Cache for 10 minutes
    if _SUBSCRIPTION_MERCHANTS_CACHE is not None and _SUBSCRIPTION_MERCHANTS_CACHE_TIME:
        age = (datetime.now() - _SUBSCRIPTION_MERCHANTS_CACHE_TIME).seconds
        if age < 600:
            return _SUBSCRIPTION_MERCHANTS_CACHE

    merchants = {}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Source 1: merchants table (explicit subscriptions)
        cursor.execute('''
            SELECT normalized_name, avg_amount, frequency, category
            FROM merchants
            WHERE is_subscription = 1
        ''')
        for row in cursor.fetchall():
            name_lower = row['normalized_name'].lower()
            merchants[name_lower] = {
                'avg_amount': row['avg_amount'],
                'frequency': row['frequency'],
                'category': row['category'],
                'source': 'merchants_table'
            }

        # Source 2: transactions table (recurring charges - merchants appearing 3+ times)
        cursor.execute('''
            SELECT chase_description, COUNT(*) as count, AVG(chase_amount) as avg_amount
            FROM transactions
            WHERE review_status = 'good'
            GROUP BY chase_description
            HAVING COUNT(*) >= 3
        ''')
        for row in cursor.fetchall():
            # Extract base merchant name (remove location/store numbers)
            desc = row['chase_description']
            # Common patterns to extract base name
            base_name = desc.lower()
            # Skip if already in merchants
            if base_name in merchants:
                continue
            # Add as recurring merchant
            merchants[base_name] = {
                'avg_amount': float(row['avg_amount']),
                'frequency': 'recurring',
                'category': 'recurring_charge',
                'source': 'transactions_history',
                'occurrence_count': row['count']
            }

        conn.close()
        _SUBSCRIPTION_MERCHANTS_CACHE = merchants
        _SUBSCRIPTION_MERCHANTS_CACHE_TIME = datetime.now()
        print(f"      📊 Loaded {len(merchants)} subscription/recurring merchants from database")
        return merchants
    except Exception as e:
        print(f"⚠️  Could not load subscription merchants: {e}")
        return {}

def is_known_subscription_merchant(merchant_name, from_email=None, subject=None):
    """
    Check if merchant/sender matches a known subscription from database.
    Returns: (is_subscription, merchant_data_dict or None)
    """
    if not merchant_name and not from_email and not subject:
        return False, None

    merchants = load_subscription_merchants()
    if not merchants:
        return False, None

    # Build search terms
    search_terms = []
    if merchant_name:
        search_terms.append(merchant_name.lower())
    if from_email:
        # Extract domain or name from email
        domain = from_email.split('@')[-1] if '@' in from_email else ''
        if domain:
            domain_base = domain.split('.')[0]
            search_terms.append(domain_base.lower())
    if subject:
        # Look for company names in subject like "Your receipt from X"
        import re
        match = re.search(r'receipt from ([^#\n]+?)(?:\s*#|\s*$)', subject.lower())
        if match:
            search_terms.append(match.group(1).strip())

    # Check each search term against known merchants
    for term in search_terms:
        for merchant_key, data in merchants.items():
            if term in merchant_key or merchant_key in term:
                return True, data

    return False, None

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

# Personal subscription & service receipts (INCLUDE these) - HIGH CONFIDENCE
PERSONAL_SERVICE_DOMAINS = [
    # AI/Creative Tools
    'anthropic.com', 'mail.anthropic.com', 'openai.com', 'midjourney.com', 'runway.ml', 'runwayml.com',
    'ideogram.ai', 'beautiful.ai', 'figma.com', 'canva.com', 'suno.ai', 'pika.art',
    # Tech Services / Apple
    'apple.com', 'email.apple.com', 'icloud.com', 'google.com', 'microsoft.com', 'adobe.com',
    'spotify.com', 'netflix.com', 'hulu.com', 'disney.com', 'primevideo.com', 'max.com',
    # Business Tools
    'notion.so', 'slack.com', 'zoom.us', 'dropbox.com', 'taskade.com',
    'github.com', 'vercel.com', 'railway.app', 'netlify.com', 'heroku.com', 'render.com',
    # Cloud/Hosting
    'cloudflare.com', 'aws.amazon.com', 'digitalocean.com',
    # Payment Processors (when they send receipts) - VERY HIGH PRIORITY
    'stripe.com', 'e.stripe.com', 'square.com', 'paypal.com', 'venmo.com',
    # AI/ML Platforms
    'huggingface.co', 'replicate.com', 'wandb.ai', 'cohere.ai',
    # Phone/Utilities
    'tdstelecom.com', 'kiafinance.com',  # Car payment confirmations
    # Event/Ticket receipts
    'ticketspice.com', 'eventbrite.com', 'aegpresents.com',
    # Rideshare / Delivery - CRITICAL
    'uber.com', 'ubereats.com', 'lyft.com', 'doordash.com', 'grubhub.com',
    'postmates.com', 'instacart.com', 'shipt.com',
    # Retail - common receipt sources
    'target.com', 'walmart.com', 'costco.com', 'amazon.com', 'bestbuy.com', 'homedepot.com',
    'lowes.com', 'staples.com', 'officedepot.com', 'zappos.com',
    # Food / Restaurant receipts
    'mcdonalds.com', 'us.mcdonalds.com', 'starbucks.com', 'chipotle.com', 'chick-fil-a.com',
    # Travel
    'airbnb.com', 'booking.com', 'expedia.com', 'hotels.com', 'southwest.com', 'delta.com',
    'united.com', 'aa.com', 'allegiantair.com',
    # Gas/Auto
    'shell.com', 'exxon.com', 'chevron.com', 'bp.com', 'circlek.com',
    # Other services
    'calendarbridge.com', 'paddle.com', 'woocommerce.com', 'shopify.com',
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
    'hive', 'hive.com', 'keep using',  # Hive project management spam
]

# Spam/marketing sender domains to auto-reject
SPAM_SENDER_DOMAINS = [
    # Email marketing platforms
    'mailchimp.com', 'sendgrid.net', 'constantcontact.com', 'mailgun.org',
    'hubspot.com', 'mailerlite.com', 'klaviyo.com', 'brevo.com',
    'mixmax.com', 'intercom.io', 'drip.com', 'convertkit.com',
    # Subdomain prefixes that indicate marketing (but NOT blocking amazon.com itself)
    'marketing.', 'promo.',
    'advertising.amazon.com',  # Only promotional Amazon subdomain, NOT order emails
    # Expensify (reports, not receipts)
    'expensify.com', 'expensifymail.com',
    # Political/news spam
    'conservativeinstitute', 'forbesbreak', 'dailywire',
    # School/community newsletters
    'wilsonk12tn.us', 'k12.com', 'schoolmessenger.com',
    # Dental/medical marketing
    'smilegeneration.com', 'smile.direct',
    # Credit card marketing (NOT statements/receipts)
    'synchronyfinancial.com', 'synchrony.com',
    # Newsletter platforms
    'substack.com', 'beehiiv.com', 'ghost.io',
]

# Subject patterns that ALWAYS indicate spam (auto-reject regardless of sender)
SPAM_SUBJECT_PATTERNS = [
    # Amazon promotional garbage
    'we found something you might like', "today's big deal", 'new deals just dropped',
    'your deals are here', 'deals for you', 'recommended for you', 'based on your',
    'you might also like', 'customers who bought', 'frequently bought together',
    # Amazon shipping (not receipts)
    'shipped:', 'arriving:', 'delivered:', 'out for delivery',
    'your package', 'tracking number', 'shipment notification',
    # Expensify internal
    'expenses to review', 'expense report', 'please review',
    # Political/news spam
    'trump announces', 'americans could see', 'breaking:', 'alert:',
    'you won\'t believe', 'shocking:', 'urgent:',
    # Hotel/loyalty
    'hilton honors', 'marriott bonvoy', 'points expiring', 'redeem your points',
    # Black Friday / Sale spam
    'black friday', 'cyber monday', 'flash sale', 'limited time only',
    'last chance', 'ending soon', 'don\'t miss out', 'exclusive access',
    # Internal business (not receipts)
    'closing binder', 'hat order', 'tm nda', 'rdo consulting',
    'please review $', 'wire transfer', 'ach payment',
    # Generic marketing
    'weekly digest', 'monthly newsletter', 'featured products',
    'new arrivals', 'just in', 'back in stock',
    # School/Community Updates
    'community update', 'back to school', 'graduation date',
    # Credit card marketing
    'preapproved', 'pre-approved', 'you\'re preapproved', 'credit increase',
    'congratulations!', 'you qualify',
    # Dental/Medical marketing
    'smile for', 'dental', 'check-up reminder',
    # Lawn/service invoices (B2B) - NOT personal receipts
    'invoice: auto-charge', 'auto-charge notice',
    # Generic non-receipt patterns
    'account payment',  # Generic vague subject
]

# Sender patterns that indicate spam (from_email or from_name matches)
SPAM_SENDER_PATTERNS = [
    'amazon.com',  # Amazon promotional - receipts come from auto-confirm@amazon.com with specific subjects
    'dealer-pay', 'dealerpay',
    'online order',  # Generic "online order" senders are usually spam
    'marketing@', 'newsletter@', 'promo@', 'offers@', 'deals@',
]

# Exception patterns: if subject contains these AND sender is in spam list, ALLOW it
RECEIPT_EXCEPTION_PATTERNS = [
    'order confirmed', 'order confirmation', 'your order has been placed',
    'your amazon.com order', 'digital order', 'your order of',
    'payment received', 'payment confirmation', 'receipt for',
    'invoice', 'billing statement',
]

# Artist/contract patterns (EXCLUDE these)
CONTRACT_PATTERNS = [
    'artist agreement', 'talent agreement', 'artist contract',
    'performance agreement', 'booking agreement', 'rider',
    'settlement sheet', 'tour', 'show date', 'venue',
    'contract', 'agreement', 'terms', 'signature required'
]

def init_incoming_receipts_table():
    """Initialize database table for incoming receipts (MySQL)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # MySQL-compatible CREATE TABLE (uses INT AUTO_INCREMENT, VARCHAR instead of TEXT for keys)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incoming_receipts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email_id VARCHAR(255) UNIQUE NOT NULL,
            gmail_account VARCHAR(255) NOT NULL,
            subject TEXT,
            from_email VARCHAR(255),
            from_domain VARCHAR(255),
            received_date VARCHAR(100),
            body_snippet TEXT,
            has_attachment BOOLEAN,
            attachment_count INT DEFAULT 0,
            attachments TEXT,
            receipt_files TEXT,

            merchant VARCHAR(255),
            amount DECIMAL(10,2),
            transaction_date VARCHAR(100),
            ocr_confidence INT,

            description TEXT,
            is_subscription BOOLEAN DEFAULT FALSE,
            matched_transaction_id INT,
            match_type VARCHAR(50) DEFAULT 'new',

            is_receipt BOOLEAN DEFAULT TRUE,
            is_marketing BOOLEAN DEFAULT FALSE,
            confidence_score INT,

            status VARCHAR(50) DEFAULT 'pending',
            category VARCHAR(50) DEFAULT 'receipt',
            ai_notes TEXT,
            preview_url TEXT,
            receipt_image_url TEXT,
            thumbnail_url TEXT,
            reviewed_at DATETIME,
            accepted_as_transaction_id INT,
            rejection_reason TEXT,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            processed_at DATETIME,

            INDEX idx_incoming_status (status),
            INDEX idx_incoming_category (category),
            INDEX idx_incoming_date (received_date),
            INDEX idx_incoming_account (gmail_account)
        )
    ''')

    # Create rejection learning table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incoming_rejection_patterns (
            id INT AUTO_INCREMENT PRIMARY KEY,
            pattern_type VARCHAR(50) NOT NULL,
            pattern_value VARCHAR(255) NOT NULL,
            rejection_count INT DEFAULT 1,
            last_rejected_at DATETIME,
            UNIQUE KEY unique_pattern (pattern_type, pattern_value)
        )
    ''')

    # Add new columns if they don't exist (for existing installations)
    try:
        cursor.execute("ALTER TABLE incoming_receipts ADD COLUMN receipt_image_url TEXT")
        print("   Added receipt_image_url column")
    except:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE incoming_receipts ADD COLUMN thumbnail_url TEXT")
        print("   Added thumbnail_url column")
    except:
        pass  # Column already exists

    conn.commit()
    conn.close()

    print("✅ Incoming receipts table initialized (MySQL)")

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

    # 0a. Check for receipt exception patterns first (allows Amazon order confirmations through)
    has_receipt_exception = any(exc in subject_lower for exc in RECEIPT_EXCEPTION_PATTERNS)

    # 0b. Spam subject patterns (auto-reject unless it's a receipt exception)
    if not has_receipt_exception:
        for spam_pattern in SPAM_SUBJECT_PATTERNS:
            if spam_pattern in subject_lower:
                print(f"      ✗ Rejected: Spam subject pattern '{spam_pattern}'")
                return 0

    # 0c. Spam sender patterns (more aggressive sender filtering)
    if not has_receipt_exception:
        for sender_pattern in SPAM_SENDER_PATTERNS:
            if sender_pattern in from_lower:
                print(f"      ✗ Rejected: Spam sender pattern '{sender_pattern}'")
                return 0

    # 0d. Spam sender domains (mailchimp, sendgrid, etc.) - except for receipt exceptions
    if not has_receipt_exception:
        for spam_domain in SPAM_SENDER_DOMAINS:
            if spam_domain in domain.lower() or spam_domain in from_email.lower():
                print(f"      ✗ Rejected: Spam sender domain '{spam_domain}'")
                return 0

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

    # CHECK DATABASE: Known subscription merchants get HIGHEST priority
    is_subscription, sub_data = is_known_subscription_merchant(
        merchant_name=None,  # We don't have merchant name yet in raw email
        from_email=from_email,
        subject=subject
    )
    if is_subscription:
        score += 40  # Huge boost for known subscriptions from our database
        print(f"      ✓ KNOWN SUBSCRIPTION from database: {from_email}")

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
    if (subject and '$' in subject) or 'usd' in subject_lower:
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
    Extract dollar amount from text using regex patterns.
    ENHANCED: Better patterns, multiple strategies, and smart selection.
    Returns: float amount or None
    """
    if not text:
        return None

    # Normalize text
    text = text.replace('\n', ' ').replace('\r', ' ')

    # PRIORITY 1: Look for explicit total/charged/amount labels (most reliable)
    priority_patterns = [
        # "Total: $XX.XX" or "Total $XX.XX" or "Total Amount: $XX.XX"
        r'(?:total|grand\s*total|order\s*total|amount\s*due|amount\s*charged|you\s*paid|payment\s*total|charge\s*total|transaction\s*amount)[\s:]*\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
        # "Charged $XX.XX" or "You were charged $XX.XX"
        r'(?:charged|billed|debited)[\s:]*\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
        # "$XX.XX was charged/debited"
        r'\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:was\s*)?(?:charged|debited|billed)',
        # "Payment of $XX.XX"
        r'payment\s*(?:of|for)?\s*\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
        # Amount in subject line patterns: "Your $XX.XX purchase" or "Receipt for $XX.XX"
        r'(?:receipt|order|purchase|payment|charge)\s*(?:for|of)?\s*\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
    ]

    for pattern in priority_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Take the LAST match (usually the final total after subtotals)
            amount_str = matches[-1].replace(',', '')
            try:
                amount = float(amount_str)
                if 0.01 <= amount <= 50000:  # Sanity check
                    return amount
            except:
                continue

    # PRIORITY 2: Standard dollar amounts with context
    context_patterns = [
        r'\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})',  # $199.00, $1,234.56
        r'USD\s*(\d{1,3}(?:,\d{3})*\.\d{2})',  # USD 199.00
        r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*USD',  # 199.00 USD
    ]

    all_amounts = []
    for pattern in context_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            amount_str = match.replace(',', '')
            try:
                amount = float(amount_str)
                if 0.01 <= amount <= 50000:
                    all_amounts.append(amount)
            except:
                continue

    if all_amounts:
        # If we found multiple amounts, prefer:
        # 1. The last occurrence (usually the total)
        # 2. Unless there's a much larger amount (likely the total)
        if len(all_amounts) == 1:
            return all_amounts[0]

        # Find the largest amount (likely the total)
        max_amount = max(all_amounts)
        # If the last amount is close to the max, use the last one
        last_amount = all_amounts[-1]
        if last_amount >= max_amount * 0.9:
            return last_amount
        return max_amount

    # PRIORITY 3: Amounts without decimal (less reliable)
    whole_patterns = [
        r'(?:total|charged|amount)[\s:]*\$?\s*(\d{1,5})',  # Total: $199 or Total: 199
    ]

    for pattern in whole_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            try:
                amount = float(matches[-1])
                if 1 <= amount <= 50000:
                    return amount
            except:
                continue

    return None

def analyze_image_with_vision(image_url_or_base64, subject_hint=None, from_hint=None):
    """
    Use OpenAI Vision to extract receipt data from an image (PDF screenshot, attachment, or HTML screenshot).
    This is the MOST ACCURATE method - uses actual visual content.
    Returns: (merchant, amount, description, is_subscription, is_receipt, category, ai_notes)
    """
    client = get_openai_client()
    if not client:
        print("      ⚠️  OpenAI not configured for Vision analysis")
        return None, None, None, False, True, 'receipt', None

    try:
        # Build image content
        if image_url_or_base64.startswith('http'):
            image_content = {"type": "image_url", "image_url": {"url": image_url_or_base64}}
        else:
            # Base64 encoded image
            image_content = {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_url_or_base64}"}}

        hint_text = ""
        if subject_hint:
            hint_text += f"\nEmail subject: {subject_hint}"
        if from_hint:
            hint_text += f"\nFrom: {from_hint}"

        prompt = f"""Analyze this image. Is it a RECEIPT or payment confirmation? Extract the following:

1. IS_RECEIPT - true if this shows a receipt, invoice, order confirmation, or payment. false if it's marketing, newsletter, notification, or junk.
2. CATEGORY - One of: "receipt", "subscription", "invoice", "marketing", "newsletter", "notification", "junk"
3. MERCHANT - Clean company/store name (e.g., "Starbucks", "Anthropic", "Apple")
4. AMOUNT - The total dollar amount charged (just the number, e.g., 25.99)
5. DATE - Transaction date if visible (YYYY-MM-DD format)
6. DESCRIPTION - Brief description of what was purchased
7. IS_SUBSCRIPTION - Is this a recurring charge? (true/false)
8. AI_NOTES - REQUIRED: A short 5-15 word summary explaining this expense's purpose (e.g., "Monthly AI API usage charges", "Coffee and breakfast at cafe", "Mobile app subscription renewal")
{hint_text}

IMPORTANT:
- If this is NOT a receipt (marketing email, newsletter, notification), set is_receipt=false
- For marketing/promotional content, set category="marketing" or "newsletter"
- If amount is unclear, set amount=null and add note
- Be EXACT with the amount - don't guess
- AI_NOTES must ALWAYS have a value - summarize what this purchase/charge is for

Respond with ONLY valid JSON:
{{"is_receipt": true, "category": "receipt", "merchant": "Name", "amount": 25.99, "date": "2024-12-01", "description": "...", "is_subscription": false, "ai_notes": "Short summary of expense purpose"}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    image_content
                ]
            }],
            max_tokens=300,
            temperature=0.1
        )

        text = response.choices[0].message.content.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
            text = text.rsplit('```', 1)[0]

        result = json.loads(text.strip())

        return (
            result.get('merchant'),
            result.get('amount'),
            result.get('description'),
            result.get('is_subscription', False),
            result.get('is_receipt', True),
            result.get('category', 'receipt'),
            result.get('ai_notes')
        )

    except Exception as e:
        print(f"      ⚠️  Vision analysis failed: {e}")
        return None, None, None, False, True, 'receipt', f"Vision error: {str(e)[:50]}"


def analyze_email_with_openai(subject, from_email, body_text):
    """
    Use OpenAI GPT-4o-mini to extract structured data from email body (PRIORITY)
    Returns: (merchant, amount, description, is_subscription, category, ai_notes)
    """
    client = get_openai_client()
    if not client:
        print("      ⚠️  OpenAI not configured, falling back to Gemini...")
        return analyze_email_with_gemini_fallback(subject, from_email, body_text)

    try:
        prompt = f"""You are analyzing a receipt/payment confirmation email. Extract these fields:

1. MERCHANT NAME - Clean company name (e.g., "Anthropic", "Apple", "Midjourney")
2. AMOUNT - The dollar amount charged. Look for:
   - "$XX.XX" in subject or body
   - "Amount: XX.XX"
   - "Total: XX.XX"
   - "Charged: XX.XX"
   - If not found, return null (DO NOT GUESS)
3. DESCRIPTION - What was purchased (e.g., "Claude Pro monthly subscription", "iCloud+ 2TB storage")
4. IS_SUBSCRIPTION - Is this a recurring monthly/yearly charge? (true/false)
5. CATEGORY - One of: "receipt", "subscription", "invoice", "marketing", "newsletter", "notification", "junk"
6. AI_NOTES - A short 5-15 word summary explaining this expense's purpose (e.g., "Monthly AI API usage charges", "Cloud storage subscription renewal")

Email Subject: {subject}
From: {from_email}
Body: {body_text[:2500]}

IMPORTANT:
- If this looks like marketing, newsletter, or notification (not an actual receipt), set category appropriately
- DO NOT guess amounts - return null if not clearly stated
- Be precise with merchant names
- AI_NOTES must ALWAYS have a value - summarize what this purchase/charge is for

Respond with ONLY valid JSON (no markdown, no code blocks):
{{
  "merchant": "Company Name",
  "amount": 199.00,
  "description": "Specific product/service description",
  "is_subscription": true,
  "category": "receipt",
  "ai_notes": "Short summary of expense purpose"
}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.1
        )

        text = response.choices[0].message.content.strip()
        if not text:
            raise Exception("OpenAI returned empty response")

        # Remove markdown code blocks if present
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
            text = text.rsplit('```', 1)[0]

        result = json.loads(text.strip())

        merchant = result.get('merchant')
        amount = result.get('amount')
        description = result.get('description')
        is_subscription = result.get('is_subscription', False)
        category = result.get('category', 'receipt')
        ai_notes = result.get('ai_notes')

        # If OpenAI didn't extract amount, try regex fallback
        if not amount:
            print(f"      ⚠️  OpenAI didn't extract amount, trying regex...")
            amount = extract_amount_from_text(subject + " " + body_text)
            if amount:
                print(f"      ✓ Regex extracted amount: ${amount}")

        return (merchant, amount, description, is_subscription, category, ai_notes)

    except Exception as e:
        print(f"      ⚠️  OpenAI analysis failed: {e}")
        print(f"      → Using regex fallback for amount extraction...")

        # Fallback: Try to extract amount with regex
        amount = extract_amount_from_text(subject + " " + body_text)
        merchant_fallback, _, _ = extract_merchant_and_amount(subject, from_email, body_text[:500])

        if amount:
            print(f"      ✓ Regex extracted amount: ${amount}")
        if merchant_fallback:
            print(f"      ✓ Regex extracted merchant: {merchant_fallback}")

        # Generate simple ai_notes from subject
        ai_notes = f"Email from {from_email.split('@')[0]} - {subject[:50]}" if subject else None

        return (merchant_fallback, amount, None, False, 'receipt', ai_notes)


def analyze_email_with_gemini_fallback(subject, from_email, body_text):
    """
    Fallback to Gemini if OpenAI is not available
    Returns: (merchant, amount, description, is_subscription, category, ai_notes)
    """
    if not GEMINI_AVAILABLE or not generate_content_with_fallback:
        print("      ⚠️  Gemini not available either, using regex only...")
        amount = extract_amount_from_text(subject + " " + body_text)
        merchant_fallback, _, _ = extract_merchant_and_amount(subject, from_email, body_text[:500])
        ai_notes = f"Email from {from_email.split('@')[0]} - {subject[:50]}" if subject else None
        return (merchant_fallback, amount, None, False, 'receipt', ai_notes)

    try:
        prompt = f"""You are analyzing a receipt/payment confirmation email. Extract these fields:

1. MERCHANT NAME - Clean company name (e.g., "Anthropic", "Apple", "Midjourney")
2. AMOUNT - The dollar amount charged. If not found, return null (DO NOT GUESS).
3. DESCRIPTION - What was purchased
4. IS_SUBSCRIPTION - Is this a recurring charge? (true/false)
5. CATEGORY - One of: "receipt", "subscription", "invoice", "marketing", "newsletter", "notification", "junk"
6. AI_NOTES - A short 5-15 word summary explaining this expense's purpose

Email Subject: {subject}
From: {from_email}
Body: {body_text[:2500]}

IMPORTANT: If this looks like marketing/newsletter/notification rather than an actual receipt, set category appropriately.
AI_NOTES must ALWAYS have a value - summarize what this purchase/charge is for.

Respond with ONLY valid JSON:
{{"merchant": "Name", "amount": 0.00, "description": "...", "is_subscription": false, "category": "receipt", "ai_notes": "Short summary of expense"}}"""

        text = generate_content_with_fallback(prompt)
        if not text:
            raise Exception("Gemini returned empty response")
        text = text.strip()

        if text.startswith('```'):
            text = text.split('\n', 1)[1]
            text = text.rsplit('```', 1)[0]

        result = json.loads(text.strip())
        return (result.get('merchant'), result.get('amount'), result.get('description'), result.get('is_subscription', False), result.get('category', 'receipt'), result.get('ai_notes'))

    except Exception as e:
        print(f"      ⚠️  Gemini fallback failed: {e}")
        amount = extract_amount_from_text(subject + " " + body_text)
        merchant_fallback, _, _ = extract_merchant_and_amount(subject, from_email, body_text[:500])
        ai_notes = f"Email from {from_email.split('@')[0]} - {subject[:50]}" if subject else None
        return (merchant_fallback, amount, None, False, 'receipt', ai_notes)


# Keep old function name as alias for compatibility
def analyze_email_with_gemini(subject, from_email, body_text):
    """Alias - now uses OpenAI as priority"""
    return analyze_email_with_openai(subject, from_email, body_text)


def extract_merchant_and_amount(subject, from_email, body_snippet):
    """
    Extract merchant name and amount from email content (IMPROVED)
    Returns: (merchant, amount, receipt_date)
    """
    import re

    merchant = None
    amount = None
    receipt_date = None

    subject_lower = subject.lower() if subject else ''
    subject_orig = subject or ''

    # ==========================================================
    # MERCHANT EXTRACTION - Much more aggressive patterns
    # ==========================================================

    # Common merchants to look for directly in subject
    known_merchants = {
        'apple': 'Apple',
        'uber': 'Uber',
        'uber eats': 'Uber Eats',
        'lyft': 'Lyft',
        'doordash': 'DoorDash',
        'grubhub': 'Grubhub',
        'instacart': 'Instacart',
        'amazon': 'Amazon',
        'spotify': 'Spotify',
        'netflix': 'Netflix',
        'hulu': 'Hulu',
        'disney': 'Disney+',
        'anthropic': 'Anthropic',
        'openai': 'OpenAI',
        'cloudflare': 'Cloudflare',
        'stripe': 'Stripe',
        'paypal': 'PayPal',
        'venmo': 'Venmo',
        'cash app': 'Cash App',
        'zelle': 'Zelle',
        'starbucks': 'Starbucks',
        'chipotle': 'Chipotle',
        'sonic': 'Sonic',
        'sonicdrivein': 'Sonic',
        'first watch': 'First Watch',
        'chick-fil-a': 'Chick-fil-A',
        'target': 'Target',
        'walmart': 'Walmart',
        'costco': 'Costco',
        'home depot': 'Home Depot',
        'lowes': 'Lowes',
        "lowe's": 'Lowes',
        'charles tyrwhitt': 'Charles Tyrwhitt',
        'ctshirts': 'Charles Tyrwhitt',
        'kia': 'Kia',
        'kia finance': 'Kia Finance',
        'speedpay': 'Kia Finance',
        'cima solutions': 'Cima Solutions',
        'midjourney': 'Midjourney',
        'cursor': 'Cursor',
        'github': 'GitHub',
        'notion': 'Notion',
        'linear': 'Linear',
        'vercel': 'Vercel',
        'railway': 'Railway',
        'digitalocean': 'DigitalOcean',
        'aws': 'AWS',
        'google cloud': 'Google Cloud',
        'microsoft': 'Microsoft',
        'adobe': 'Adobe',
        'figma': 'Figma',
        'canva': 'Canva',
        'dropbox': 'Dropbox',
        'zoom': 'Zoom',
        'slack': 'Slack',
        'discord': 'Discord',
        'twilio': 'Twilio',
        'mailchimp': 'Mailchimp',
        'squarespace': 'Squarespace',
        'wix': 'Wix',
        'godaddy': 'GoDaddy',
        'namecheap': 'Namecheap',
        'att': 'AT&T',
        'verizon': 'Verizon',
        't-mobile': 'T-Mobile',
        'comcast': 'Comcast',
        'xfinity': 'Xfinity',
        'spectrum': 'Spectrum',
        'cox': 'Cox',
        'duke energy': 'Duke Energy',
        'nashville electric': 'NES',
        'piedmont': 'Piedmont Gas',
    }

    # Map sender domains to merchant names
    domain_to_merchant = {
        'apple.com': 'Apple',
        'uber.com': 'Uber',
        'lyft.com': 'Lyft',
        'doordash.com': 'DoorDash',
        'grubhub.com': 'Grubhub',
        'postmates.com': 'Postmates',
        'instacart.com': 'Instacart',
        'amazon.com': 'Amazon',
        'spotify.com': 'Spotify',
        'netflix.com': 'Netflix',
        'hulu.com': 'Hulu',
        'disneyplus.com': 'Disney+',
        'anthropic.com': 'Anthropic',
        'openai.com': 'OpenAI',
        'cloudflare.com': 'Cloudflare',
        'stripe.com': 'Stripe',
        'paypal.com': 'PayPal',
        'venmo.com': 'Venmo',
        'square.com': 'Square',
        'squareup.com': 'Square',
        'starbucks.com': 'Starbucks',
        'chipotle.com': 'Chipotle',
        'sonicdrivein.com': 'Sonic',
        'firstwatch.com': 'First Watch',
        'target.com': 'Target',
        'walmart.com': 'Walmart',
        'costco.com': 'Costco',
        'homedepot.com': 'Home Depot',
        'lowes.com': 'Lowes',
        'ctshirts.com': 'Charles Tyrwhitt',
        'kiafinance.com': 'Kia Finance',
        'speedpay.com': 'Kia Finance',
        'cimasolutions.com': 'Cima Solutions',
        'midjourney.com': 'Midjourney',
        'cursor.sh': 'Cursor',
        'github.com': 'GitHub',
        'notion.so': 'Notion',
        'linear.app': 'Linear',
        'vercel.com': 'Vercel',
        'railway.app': 'Railway',
        'digitalocean.com': 'DigitalOcean',
        'aws.amazon.com': 'AWS',
        'google.com': 'Google',
        'microsoft.com': 'Microsoft',
        'adobe.com': 'Adobe',
        'figma.com': 'Figma',
        'canva.com': 'Canva',
        'dropbox.com': 'Dropbox',
        'zoom.us': 'Zoom',
        'slack.com': 'Slack',
        'twilio.com': 'Twilio',
        'mailchimp.com': 'Mailchimp',
        'att.com': 'AT&T',
        'verizon.com': 'Verizon',
        't-mobile.com': 'T-Mobile',
    }

    # Check for known merchants in subject first
    for key, name in known_merchants.items():
        if key in subject_lower:
            merchant = name
            break

    # Extract merchant from subject patterns
    if not merchant:
        merchant_patterns = [
            r'receipt from ([^#\n\.]+?)(?:\s*#|\s*\.|$)',
            r'invoice from ([^#\n\.]+?)(?:\s*#|\s*\.|$)',
            r'payment (?:to|from) ([^#\n\.]+?)(?:\s*#|\s*\.|$)',
            r'your ([^#\n]+?) (?:receipt|invoice|order)',
            r'order from ([^#\n\.]+?)(?:\s*#|\s*\.|$)',
            r'confirmation from ([^#\n\.]+?)(?:\s*#|\s*\.|$)',
            r'([A-Za-z][A-Za-z\s]{2,20})\s+(?:Receipt|Invoice|Order|Payment)',  # "Company Receipt"
        ]

        for pattern in merchant_patterns:
            match = re.search(pattern, subject_orig, re.IGNORECASE)
            if match:
                merchant = match.group(1).strip().title()
                merchant = re.sub(r',?\s*(?:Inc|LLC|Ltd|Corp|Co)\.?$', '', merchant, flags=re.IGNORECASE)
                # Clean up "Your " prefix
                merchant = re.sub(r'^Your\s+', '', merchant, flags=re.IGNORECASE)
                if len(merchant) > 2:
                    break

    # Extract from email domain using domain_to_merchant mapping
    if not merchant and from_email:
        domain = from_email.split('@')[-1].lower() if '@' in from_email else ''
        generic_domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com', 'me.com', 'aol.com']

        # First check exact domain match
        if domain in domain_to_merchant:
            merchant = domain_to_merchant[domain]
        elif domain and domain not in generic_domains:
            # Try partial domain match (e.g., receipts.uber.com -> uber.com)
            for d, m in domain_to_merchant.items():
                if d in domain or domain.endswith('.' + d):
                    merchant = m
                    break

            # Fallback: extract company from domain
            if not merchant:
                company = domain.split('.')[0].title()
                company = company.replace('Noreply', '').replace('Receipt', '').replace('Invoice', '').replace('Mail', '').replace('Email', '').strip()
                if company and len(company) > 2:
                    merchant = company

    # ==========================================================
    # AMOUNT EXTRACTION
    # ==========================================================
    amount_patterns = [
        r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2}))',  # $XX.XX (require cents)
        r'total[:\s]+\$?\s*(\d+(?:,\d{3})*(?:\.\d{2}))',
        r'amount[:\s]+\$?\s*(\d+(?:,\d{3})*(?:\.\d{2}))',
        r'charged[:\s]+\$?\s*(\d+(?:,\d{3})*(?:\.\d{2}))',
        r'(\d+(?:,\d{3})*(?:\.\d{2}))\s*(?:USD|usd)',
    ]

    search_text = subject + ' ' + (body_snippet or '')
    for pattern in amount_patterns:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '')
            try:
                amount = float(amount_str)
                if amount > 0.01 and amount < 100000:  # Sanity check
                    break
            except ValueError:
                continue

    # ==========================================================
    # DATE EXTRACTION - Parse dates from subject/body
    # ==========================================================
    date_patterns = [
        r'(\d{1,2}/\d{1,2}/\d{2,4})',  # MM/DD/YYYY or M/D/YY
        r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})',  # Jan 15, 2024
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})',  # 15 Jan 2024
    ]

    for pattern in date_patterns:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            try:
                # Try various date formats
                for fmt in ['%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y']:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt)
                        # Sanity check - should be within last 2 years
                        if datetime.now() - timedelta(days=730) < parsed_date <= datetime.now() + timedelta(days=7):
                            receipt_date = parsed_date.strftime('%Y-%m-%d')
                            break
                    except ValueError:
                        continue
                if receipt_date:
                    break
            except:
                continue

    return merchant, amount, receipt_date


def find_matching_transaction(merchant, amount, transaction_date):
    """
    Check if a similar transaction already exists in the database (MySQL)
    Returns: (transaction_id, has_receipt, needs_receipt)

    AGGRESSIVE matching logic - optimized for finding matches:
    1. When we have date + amount + merchant: strict match (date within 5 days)
    2. When we have amount + merchant (no date): search last 90 days
    3. When we have just amount: look for exact amount matches in last 60 days
    4. Merchant fuzzy matching with scoring
    """
    if not merchant and not amount:
        return None, False, False

    conn = get_db_connection()
    cursor = conn.cursor()

    # Determine date range - MORE AGGRESSIVE when no date
    has_date = bool(transaction_date)
    if transaction_date:
        try:
            date_obj = datetime.fromisoformat(transaction_date.split('T')[0])
            # Use asymmetric window: receipts usually come AFTER the charge
            date_min = (date_obj - timedelta(days=5)).strftime('%Y-%m-%d')
            date_max = (date_obj + timedelta(days=14)).strftime('%Y-%m-%d')
        except:
            has_date = False
            date_min = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            date_max = datetime.now().strftime('%Y-%m-%d')
    else:
        # No date provided - search MUCH wider window (90 days)
        date_min = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        date_max = datetime.now().strftime('%Y-%m-%d')

    # Normalize merchant name for matching
    merchant_lower = (merchant or '').lower().strip()
    # Extract key words (remove common words)
    stop_words = {'the', 'inc', 'llc', 'ltd', 'corp', 'co', 'company', 'store', 'shop', 'online', 'www', 'com'}
    merchant_words = set(w for w in re.split(r'[\s\.\-\_\*]+', merchant_lower) if len(w) > 2 and w not in stop_words)

    best_match = None
    best_score = 0

    # STRATEGY 1: Amount match with merchant verification
    # When we have a date, require date proximity. When no date, be more lenient.
    # NOTE: We search ALL transactions (even those with receipts) so we can show "already has receipt"
    if amount and amount > 0:
        # Allow small tolerance for rounding (within 1 cent)
        cursor.execute('''
            SELECT _index, chase_description, chase_amount, chase_date, receipt_file, receipt_url, mi_merchant
            FROM transactions
            WHERE ABS(chase_amount - %s) < 0.02
              AND chase_date BETWEEN %s AND %s
              AND deleted != 1
            ORDER BY chase_date DESC
            LIMIT 20
        ''', (amount, date_min, date_max))

        amount_matches = cursor.fetchall()
        for match in amount_matches:
            match_desc = str(match['chase_description'] or '').lower()
            mi_merchant = str(match.get('mi_merchant') or '').lower()
            match_amount = float(match['chase_amount'] or 0)

            # Base score for exact amount match
            score = 40  # Start with good base score for amount match
            has_merchant_match = False
            has_date_match = False
            days_diff = 999

            # Calculate date proximity IF we have a date
            if has_date and match.get('chase_date'):
                try:
                    match_date = match['chase_date']
                    if isinstance(match_date, str):
                        match_date = datetime.fromisoformat(match_date.split('T')[0])
                    if isinstance(match_date, datetime):
                        days_diff = abs((date_obj - match_date).days)
                    else:
                        days_diff = abs((date_obj - datetime.combine(match_date, datetime.min.time())).days)

                    # Date within range - add bonus
                    if days_diff <= 3:
                        has_date_match = True
                        score += 40  # Same/close day - strong signal
                    elif days_diff <= 7:
                        has_date_match = True
                        score += 25  # Within week
                    elif days_diff <= 14:
                        has_date_match = True
                        score += 10  # Within 2 weeks
                except:
                    pass
            else:
                # No date provided - don't penalize, just can't add date bonus
                # The amount match alone + merchant match should be enough
                pass

            # Check for merchant name similarity
            combined_desc = f"{match_desc} {mi_merchant}"

            # Direct substring match (very strong signal)
            if merchant_lower and len(merchant_lower) >= 3:
                if merchant_lower in combined_desc:
                    score += 60  # Strong merchant match
                    has_merchant_match = True
                elif any(word in combined_desc for word in merchant_words if len(word) >= 4):
                    score += 45  # Partial merchant match
                    has_merchant_match = True

            # Word overlap matching
            desc_words = set(w for w in re.split(r'[\s\.\-\_\*]+', combined_desc) if len(w) > 2 and w not in stop_words)
            common_words = merchant_words & desc_words
            if common_words:
                score += len(common_words) * 12
                if len(common_words) >= 1:
                    has_merchant_match = True

            # If we have date AND it matches AND merchant matches - very confident
            if has_merchant_match and has_date_match:
                score += 20  # Bonus for all three

            # If NO date but good merchant match + exact amount - still valid
            if has_merchant_match and not has_date and score >= 80:
                score += 15  # Boost for good match without date

            # Only require merchant match if we have merchant info to match
            if merchant_lower and not has_merchant_match:
                score = max(0, score - 30)  # Penalize but don't zero out

            if score > best_score:
                best_score = score
                best_match = match

    # STRATEGY 2: Merchant name fuzzy match (if no good amount match)
    if best_score < 60 and merchant_lower and len(merchant_lower) >= 3:
        # Try multiple search patterns
        search_patterns = []

        # Exact merchant name
        search_patterns.append(f'%{merchant_lower}%')

        # First significant word
        if merchant_words:
            primary_word = max(merchant_words, key=len) if merchant_words else None
            if primary_word and len(primary_word) >= 4:
                search_patterns.append(f'%{primary_word}%')

        for pattern in search_patterns:
            cursor.execute('''
                SELECT _index, chase_description, chase_amount, chase_date, receipt_file, mi_merchant
                FROM transactions
                WHERE (LOWER(chase_description) LIKE %s OR LOWER(mi_merchant) LIKE %s)
                  AND chase_date BETWEEN %s AND %s
                  AND (receipt_file IS NULL OR receipt_file = '' OR receipt_file = 'None')
                ORDER BY chase_date DESC
                LIMIT 5
            ''', (pattern, pattern, date_min, date_max))

            name_matches = cursor.fetchall()
            for match in name_matches:
                match_amount = float(match['chase_amount'] or 0)
                score = 30  # Base score for name match

                # Boost significantly if amount also matches
                if amount and match_amount:
                    diff = abs(amount - match_amount)
                    diff_pct = diff / max(match_amount, 0.01) * 100

                    if diff < 0.02:  # Exact match
                        score += 50
                    elif diff_pct < 1:  # Within 1%
                        score += 40
                    elif diff_pct < 5:  # Within 5%
                        score += 25
                    elif diff_pct < 10:  # Within 10%
                        score += 10

                if score > best_score:
                    best_score = score
                    best_match = match

    conn.close()

    if best_match and best_score >= 40:  # Minimum confidence threshold
        trans_id = best_match['_index']
        trans_amount = float(best_match['chase_amount'] or 0)
        receipt_file = best_match.get('receipt_file', '')
        receipt_url = best_match.get('receipt_url', '')
        has_receipt = (receipt_file and str(receipt_file).strip() not in ('', 'None', 'null')) or \
                      (receipt_url and str(receipt_url).strip() not in ('', 'None', 'null'))

        # STRICT amount matching - amounts MUST be close
        amount_match = False
        if amount and amount > 0 and trans_amount > 0:
            diff = abs(amount - trans_amount)
            diff_pct = diff / max(trans_amount, 0.01) * 100
            # Allow max 5% or $1 difference (whichever is smaller for small amounts)
            amount_match = diff < 1.00 or (diff_pct < 5 and diff < 5.00)

        # STRICT: Only return match if amounts match AND score is good
        # No more matching without amount verification!
        if not amount_match:
            print(f"      ⚠️ Amount mismatch: Receipt ${amount:.2f} vs TX ${trans_amount:.2f} (diff: ${abs(amount - trans_amount):.2f})")
            return None, False, False, 0

        needs_receipt = not has_receipt

        print(f"      🎯 Match found: {best_match.get('chase_description', 'Unknown')[:40]} | Score: {best_score} | Amount: ${trans_amount:.2f}")
        return trans_id, has_receipt, needs_receipt, best_score

    return None, False, False, 0


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
    Convert HTML email to JPG image.
    OPTIMIZED FOR RAILWAY: Uses pure Python methods that work without external deps.

    Priority:
    1. Pure Python text-to-image (always works)
    2. Playwright (if available)
    3. wkhtmltoimage (if available)

    Returns: path to saved JPG file
    """
    # Method 1: Pure Python - ALWAYS WORKS on Railway
    try:
        img_bytes = convert_html_to_image(html_content)
        if img_bytes:
            with open(output_path, 'wb') as f:
                f.write(img_bytes)
            print(f"      ✓ HTML to image (pure Python): {output_path}")
            return output_path
    except Exception as e:
        print(f"      ⚠️  Pure Python HTML conversion failed: {e}")

    # Method 2: Try Playwright (best quality, but may not be installed)
    png_path = output_path.replace('.jpg', '.png')
    temp_html = output_path.replace('.jpg', '_temp.html')

    try:
        # Save HTML to temp file
        with open(temp_html, 'w', encoding='utf-8') as f:
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
            pass  # Silent fail - pure Python method above is the primary

        # Method 3: Try wkhtmltoimage if available
        if not success:
            try:
                import subprocess
                result = subprocess.run(['wkhtmltoimage', '--quality', '90', temp_html, png_path],
                                       capture_output=True, timeout=30)
                if result.returncode == 0:
                    success = True
                    print(f"      ✓ Screenshot via wkhtmltoimage: {output_path}")
            except Exception:
                pass

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


def generate_receipt_filename(merchant: str, date: str, amount: float, unique_id: str = None, ext: str = ".jpg") -> str:
    """
    Generate standardized receipt filename: merchant_date_amount_id.ext
    Example: anthropic_2024-11-15_20_00_abc123.jpg

    The unique_id ensures we can always trace back to the source (email_id or tx_id)
    """
    # Clean merchant name - lowercase, replace spaces/special chars with underscore
    merchant_clean = re.sub(r'[^a-z0-9]+', '_', merchant.lower().strip())
    merchant_clean = merchant_clean.strip('_')[:30]  # Limit length

    # Format amount - replace decimal with underscore
    amount_str = f"{amount:.2f}".replace('.', '_')

    # Ensure date is in correct format
    date_clean = date or datetime.now().strftime("%Y-%m-%d")
    if hasattr(date_clean, 'strftime'):
        date_clean = date_clean.strftime('%Y-%m-%d')
    elif 'T' in str(date_clean):
        date_clean = str(date_clean).split('T')[0]

    # Add unique ID suffix for traceability
    if unique_id:
        id_suffix = f"_{unique_id[:12]}"  # First 12 chars of ID
    else:
        id_suffix = ""

    return f"{merchant_clean}_{date_clean}_{amount_str}{id_suffix}{ext}"


def process_receipt_files(service, email_id, attachments, html_body=None, merchant=None, amount=None, receipt_date=None):
    """
    Download and convert receipt files from Gmail email.
    Saves locally and uploads to R2 for cloud storage.

    Args:
        service: Gmail API service
        email_id: Gmail message ID
        attachments: List of attachment info dicts
        html_body: HTML content for screenshot if no attachments
        merchant: Merchant name for standardized filename
        amount: Amount for standardized filename
        receipt_date: Date for standardized filename

    Returns: list of saved file paths (R2 URLs if available, otherwise local paths)
    """
    saved_files = []
    local_files = []

    # Create receipts/incoming directory if doesn't exist
    os.makedirs(RECEIPTS_DIR, exist_ok=True)

    # Generate base filename - use standardized naming if we have merchant info
    if merchant and amount:
        # Include email_id as unique identifier for traceability
        base_filename = generate_receipt_filename(merchant, receipt_date, float(amount), unique_id=email_id, ext="").rstrip('.')
        print(f"      📁 Using standardized filename: {base_filename}")
    else:
        # Fallback to email ID if no merchant info
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
            suffix = f"_p{i}" if i > 0 else ""  # Add page suffix only for multiple attachments
            output_path = os.path.join(RECEIPTS_DIR, f"{base_filename}{suffix}.jpg")
            result = convert_pdf_to_jpg(file_data, output_path)
            if result:
                local_files.append(result)
            else:
                # Fallback: save PDF directly if conversion fails
                pdf_output = os.path.join(RECEIPTS_DIR, f"{base_filename}{suffix}.pdf")
                with open(pdf_output, 'wb') as f:
                    f.write(file_data)
                local_files.append(pdf_output)
                print(f"      ✓ Saved PDF directly (conversion failed): {pdf_output}")
        else:
            # Save other attachments (images, etc.) - preserve original extension
            orig_ext = os.path.splitext(filename)[1].lower() or '.jpg'
            suffix = f"_p{i}" if i > 0 else ""
            output_path = os.path.join(RECEIPTS_DIR, f"{base_filename}{suffix}{orig_ext}")
            with open(output_path, 'wb') as f:
                f.write(file_data)
            local_files.append(output_path)
            print(f"      ✓ Saved attachment: {output_path}")

    # If no attachments but has HTML body, screenshot it
    if not local_files and html_body:
        print(f"      📸 Screenshotting HTML receipt...")
        output_path = os.path.join(RECEIPTS_DIR, f"{base_filename}.jpg")
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
                # Try base64 decode first (new format)
                try:
                    decoded = base64.b64decode(env_token).decode('utf-8')
                    token_data = json.loads(decoded)
                    print(f"   ✓ Loaded token from env {env_key} (base64)")
                except:
                    # Fall back to plain JSON (old format)
                    token_data = json.loads(env_token)
                    print(f"   ✓ Loaded token from env {env_key} (json)")
            except json.JSONDecodeError as e:
                print(f"   ⚠️  Invalid token format in {env_key}: {e}")

    if not token_data:
        print(f"   ⚠️  Token not found for: {account_email}")
        return None

    try:
        creds = Credentials(
            token=token_data.get('token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id'),
            client_secret=token_data.get('client_secret'),
            scopes=token_data.get('scopes')
        )

        # AUTO-REFRESH: If token is expired, refresh it automatically
        if creds.expired or not creds.valid:
            try:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                print(f"   🔄 Token auto-refreshed for {account_email}")

                # Save refreshed token back to file if we loaded from file
                for token_dir in token_dirs:
                    token_path = token_dir / token_file
                    if token_path.exists():
                        try:
                            updated_token = {
                                'token': creds.token,
                                'refresh_token': creds.refresh_token,
                                'token_uri': creds.token_uri,
                                'client_id': creds.client_id,
                                'client_secret': creds.client_secret,
                                'scopes': list(creds.scopes) if creds.scopes else token_data.get('scopes'),
                                'email': account_email
                            }
                            with open(token_path, 'w') as f:
                                json.dump(updated_token, f, indent=2)
                            print(f"   💾 Saved refreshed token to {token_path}")
                        except Exception as save_err:
                            print(f"   ⚠️  Could not save refreshed token: {save_err}")
                        break
            except Exception as refresh_err:
                print(f"   ⚠️  Token refresh failed: {refresh_err}")
                return None

        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        print(f"   ⚠️  Error loading Gmail service: {e}")
        return None

def get_learned_rejection_patterns():
    """Get patterns that user has consistently rejected (MySQL)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT pattern_type, pattern_value, rejection_count
            FROM incoming_rejection_patterns
            WHERE rejection_count >= 2
        ''')

        patterns = {}
        for row in cursor.fetchall():
            # DictCursor returns dict
            pattern_type = row['pattern_type']
            value = row['pattern_value']
            if pattern_type not in patterns:
                patterns[pattern_type] = []
            patterns[pattern_type].append(value)

        conn.close()
        return patterns
    except Exception as e:
        print(f"⚠️  Could not get rejection patterns: {e}")
        return {}

def record_rejection_pattern(from_email, subject):
    """Learn from rejection to improve future filtering (MySQL)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Extract domain
        domain = from_email.split('@')[-1] if '@' in from_email else None

        if domain:
            # MySQL uses INSERT ... ON DUPLICATE KEY UPDATE instead of ON CONFLICT
            cursor.execute('''
                INSERT INTO incoming_rejection_patterns (pattern_type, pattern_value, rejection_count, last_rejected_at)
                VALUES ('domain', %s, 1, %s)
                ON DUPLICATE KEY UPDATE
                    rejection_count = rejection_count + 1,
                    last_rejected_at = %s
            ''', (domain, datetime.now().isoformat(), datetime.now().isoformat()))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️  Could not record rejection pattern: {e}")

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

                # Use AI to analyze full email
                print(f"   ✓ Receipt candidate: {subject[:40]} ({confidence}% confidence)")
                print(f"      🤖 Analyzing with AI...")

                # Initialize variables for Vision AI enhancement
                vision_merchant = None
                vision_amount = None
                vision_category = None
                ai_notes = None
                receipt_image_url = None
                thumbnail_url = None

                # PRIORITY 1: Try Vision AI on attachments (PDF/image) - MOST ACCURATE
                if has_attachment:
                    for att in attachments:
                        filename = att.get('filename', '').lower()
                        if filename.endswith(('.pdf', '.jpg', '.jpeg', '.png', '.gif')):
                            print(f"      📎 Analyzing attachment: {att['filename']}")
                            try:
                                # Download attachment
                                att_data = download_gmail_attachment(
                                    service, msg['id'], att['attachment_id'], att['filename']
                                )
                                if att_data:
                                    # Convert to base64 for Vision API
                                    img_bytes = None
                                    if filename.endswith('.pdf'):
                                        # Convert PDF to JPG first
                                        import tempfile
                                        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                                            jpg_path = convert_pdf_to_jpg(att_data, tmp.name)
                                            if jpg_path:
                                                with open(jpg_path, 'rb') as f:
                                                    img_bytes = f.read()
                                                img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                                                os.unlink(jpg_path)
                                            else:
                                                img_base64 = None
                                    else:
                                        img_bytes = att_data
                                        img_base64 = base64.b64encode(att_data).decode('utf-8')

                                    if img_base64:
                                        # ALWAYS upload image to R2 first (even before vision analysis)
                                        if img_bytes and not receipt_image_url:
                                            try:
                                                from r2_service import upload_with_thumbnail, R2_ENABLED
                                                if R2_ENABLED:
                                                    import uuid
                                                    r2_key = f"inbox/{uuid.uuid4().hex[:12]}.jpg"
                                                    # Save temp file for upload
                                                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                                                        tmp.write(img_bytes)
                                                        tmp_path = tmp.name
                                                    full_url, thumb_url = upload_with_thumbnail(tmp_path, r2_key)
                                                    os.unlink(tmp_path)
                                                    if full_url:
                                                        receipt_image_url = full_url
                                                        thumbnail_url = thumb_url
                                                        print(f"      ☁️  Uploaded to R2: {r2_key}")
                                                        if thumb_url:
                                                            print(f"      🖼️  Thumbnail: {thumb_url}")
                                            except Exception as r2_err:
                                                print(f"      ⚠️  R2 upload failed: {r2_err}")

                                        # Now try vision analysis (optional - image is already saved)
                                        v_merchant, v_amount, v_desc, v_sub, v_is_receipt, v_cat, v_notes = analyze_image_with_vision(
                                            img_base64, subject_hint=subject, from_hint=from_email_clean
                                        )
                                        if v_merchant or v_amount:
                                            vision_merchant = v_merchant
                                            vision_amount = v_amount
                                            vision_category = v_cat
                                            ai_notes = v_notes
                                            print(f"      👁️  Vision: {v_merchant} ${v_amount} ({v_cat})")
                                            if v_notes:
                                                print(f"      📝 Notes: {v_notes}")

                                        break  # Use first successful attachment (image already uploaded)
                            except Exception as e:
                                print(f"      ⚠️  Attachment analysis failed: {e}")

                # PRIORITY 2: HTML screenshot - ALWAYS generate if no image yet
                # Generate HTML screenshot for preview even if we don't need vision analysis
                if not receipt_image_url:
                    # Check if we have HTML content
                    def get_html_body(payload, depth=0):
                        """Extract HTML body from email payload - RECURSIVELY searches nested parts"""
                        if depth > 10:  # Prevent infinite recursion
                            return None

                        # Check direct body first
                        body = payload.get('body', {})
                        if body.get('data') and payload.get('mimeType') == 'text/html':
                            return base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')

                        # Search in parts (recursively for nested multipart)
                        if 'parts' in payload:
                            for part in payload['parts']:
                                mime_type = part.get('mimeType', '')

                                # Direct HTML part
                                if mime_type == 'text/html':
                                    data = part.get('body', {}).get('data', '')
                                    if data:
                                        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

                                # Recurse into nested multipart (multipart/alternative, multipart/related, etc.)
                                if mime_type.startswith('multipart/') or 'parts' in part:
                                    result = get_html_body(part, depth + 1)
                                    if result:
                                        return result

                        return None

                    html_body = get_html_body(msg_data.get('payload', {}))
                    if html_body and len(html_body) > 100:  # Reduced threshold for more coverage
                        print(f"      📸 Generating HTML receipt image...")
                        try:
                            import tempfile
                            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                                screenshot_path = screenshot_html_receipt(html_body, tmp.name)
                                if screenshot_path and os.path.exists(screenshot_path):
                                    with open(screenshot_path, 'rb') as f:
                                        img_bytes = f.read()

                                    # Upload to R2 ONLY if it's a proper render (not text-based fallback)
                                    # Text-based fallbacks are typically < 50KB, proper HTML renders are > 50KB
                                    img_size_kb = len(img_bytes) / 1024
                                    if img_bytes and img_size_kb >= 50:
                                        try:
                                            from r2_service import upload_with_thumbnail, R2_ENABLED
                                            if R2_ENABLED:
                                                import uuid
                                                r2_key = f"inbox/{uuid.uuid4().hex[:12]}.jpg"
                                                full_url, thumb_url = upload_with_thumbnail(screenshot_path, r2_key)
                                                if full_url:
                                                    receipt_image_url = full_url
                                                    thumbnail_url = thumb_url
                                                    print(f"      ☁️  Uploaded HTML screenshot to R2: {r2_key} ({img_size_kb:.1f}KB)")
                                                    if thumb_url:
                                                        print(f"      🖼️  Thumbnail: {thumb_url}")
                                        except Exception as r2_err:
                                            print(f"      ⚠️  R2 upload failed: {r2_err}")
                                    elif img_bytes:
                                        print(f"      ⚠️  Skipping R2 upload - text-based fallback detected ({img_size_kb:.1f}KB < 50KB)")

                                    # Try vision analysis only if we don't have merchant/amount yet
                                    if not vision_merchant and not vision_amount:
                                        try:
                                            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                                            v_merchant, v_amount, v_desc, v_sub, v_is_receipt, v_cat, v_notes = analyze_image_with_vision(
                                                img_base64, subject_hint=subject, from_hint=from_email_clean
                                            )
                                            if v_merchant or v_amount:
                                                vision_merchant = v_merchant
                                                vision_amount = v_amount
                                                vision_category = v_cat
                                                ai_notes = v_notes
                                                print(f"      👁️  Vision (HTML): {v_merchant} ${v_amount} ({v_cat})")
                                                if v_notes:
                                                    print(f"      📝 Notes: {v_notes}")
                                        except Exception as vis_err:
                                            print(f"      ⚠️  Vision analysis skipped: {vis_err}")

                                    # Clean up temp file
                                    os.unlink(screenshot_path)
                        except Exception as e:
                            print(f"      ⚠️  HTML screenshot failed: {e}")

                # PRIORITY 3: Fallback to text-based AI analysis
                merchant_ai, amount_ai, description, is_subscription, category, email_ai_notes = analyze_email_with_gemini(
                    subject, from_email_clean, full_body or snippet
                )

                # Use Vision results if available (more accurate)
                if vision_merchant:
                    merchant_ai = vision_merchant
                if vision_amount:
                    amount_ai = vision_amount
                if vision_category:
                    category = vision_category
                # Use email AI notes as fallback if Vision didn't provide notes
                if not ai_notes and email_ai_notes:
                    ai_notes = email_ai_notes

                # CHECK DATABASE: Override is_subscription with database knowledge
                db_is_subscription, db_sub_data = is_known_subscription_merchant(
                    merchant_name=merchant_ai or vision_merchant,
                    from_email=from_email_clean,
                    subject=subject
                )
                if db_is_subscription:
                    is_subscription = True
                    print(f"      📊 KNOWN SUBSCRIPTION from database")

                # Fallback to regex if AI fails
                if not merchant_ai:
                    merchant_ai, amount_ai, date_extracted = extract_merchant_and_amount(subject, from_email_clean, snippet)
                    # Use extracted date if we don't have one
                    if date_extracted and not date_str:
                        date_str = date_extracted
                        print(f"      📅 Extracted date from email: {date_str}")

                if merchant_ai or amount_ai:
                    print(f"      Extracted: {merchant_ai or 'Unknown'} ${amount_ai or '?'}")
                    if description:
                        print(f"      Description: {description}")
                    if category and category != 'receipt':
                        print(f"      Category: {category}")

                # Check for matching transaction
                match_id, has_receipt, needs_receipt, match_score = find_matching_transaction(
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

                # Store receipt data - include ALL items even marketing/junk (user can decide)
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
                    'category': category or 'receipt',  # Category for junk/marketing
                    'ai_notes': ai_notes,  # Notes from Vision AI (e.g., "Amount unclear")
                    'receipt_image_url': receipt_image_url,  # R2 URL for full image
                    'thumbnail_url': thumbnail_url,  # R2 URL for thumbnail
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
    """Save incoming receipt to database (MySQL)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # MySQL version - includes category, ai_notes, receipt_image_url and thumbnail_url for Vision AI data
        cursor.execute('''
            INSERT INTO incoming_receipts (
                email_id, gmail_account, subject, from_email, from_domain,
                received_date, body_snippet, has_attachment, attachment_count,
                confidence_score, merchant, amount, description, is_subscription,
                matched_transaction_id, match_type, attachments, category, ai_notes,
                receipt_image_url, thumbnail_url, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
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
            receipt_data.get('attachments', '[]'),
            receipt_data.get('category', 'receipt'),
            receipt_data.get('ai_notes'),  # Vision AI notes (e.g., "Amount unclear")
            receipt_data.get('receipt_image_url'),  # R2 URL for full image
            receipt_data.get('thumbnail_url')  # R2 URL for thumbnail
        ))

        conn.commit()
        receipt_id = cursor.lastrowid
        print(f"   💾 Saved incoming receipt: {receipt_data['subject'][:40]}")
        return receipt_id

    except pymysql.err.IntegrityError:
        # Already exists (duplicate email_id)
        return None
    except Exception as e:
        print(f"   ⚠️  Error saving receipt: {e}")
        return None
    finally:
        conn.close()

# =============================================================================
# INTELLIGENT RECEIPT SCANNER (V2)
# =============================================================================
# Uses the Receipt Intelligence Engine for whitelist-driven detection
# instead of keyword guessing

from receipt_intelligence import (
    ReceiptIntelligence,
    ReceiptCandidate,
    ReceiptConfidence,
    BLOCKED_DOMAINS,
    MERCHANT_EMAIL_MAPPING,
    init_merchant_email_domains_table,
    seed_merchant_email_domains,
    add_learned_domain,
)

# Global intelligence engine
_receipt_intelligence = None

def get_receipt_intelligence():
    """Get or create the Receipt Intelligence engine"""
    global _receipt_intelligence
    if _receipt_intelligence is None:
        _receipt_intelligence = ReceiptIntelligence()
    return _receipt_intelligence


def scan_gmail_intelligent(account_email, since_date=None, max_results=100):
    """
    Intelligent Gmail scanner using merchant whitelist.

    This is the NEW, world-class scanner that:
    1. Only captures emails from KNOWN merchant domains
    2. Uses amount validation against expected ranges
    3. Falls back to high-confidence patterns for unknown domains
    4. Never processes blocked/marketing domains

    Args:
        account_email: Gmail account to scan
        since_date: Only get emails after this date (YYYY-MM-DD)
        max_results: Maximum emails to process

    Returns:
        List of receipt data dicts ready to save
    """
    service = load_gmail_service(account_email)
    if not service:
        print(f"   ❌ Could not load Gmail service for {account_email}")
        return []

    engine = get_receipt_intelligence()

    # Default to last 7 days if no date specified
    if not since_date:
        since_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    print(f"\n🔍 INTELLIGENT SCAN: {account_email}")
    print(f"   Using merchant whitelist ({len(MERCHANT_EMAIL_MAPPING)} merchants)")
    print(f"   Scanning since: {since_date}")

    # Build Gmail query for ALL potential receipts
    # We'll filter with our intelligence engine, not Gmail's keyword matching
    query_parts = [
        f'after:{since_date}',
        # Cast a wide net - filter with intelligence
        '(receipt OR invoice OR payment OR confirmation OR order OR subscription OR charge)',
        # Exclude obvious spam at Gmail level
        '-from:marketing -from:newsletter',
    ]
    query = ' '.join(query_parts)

    try:
        # Search for emails
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get('messages', [])
        print(f"   📥 Found {len(messages)} potential emails to analyze")

        new_receipts = []
        stats = {
            'total': len(messages),
            'captured': 0,
            'blocked': 0,
            'unknown_domain': 0,
            'low_confidence': 0,
            'already_exists': 0,
        }

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

                # Clean from email
                from_clean = re.findall(r'<(.+?)>', from_email)
                from_email_clean = from_clean[0] if from_clean else from_email
                domain = from_email_clean.split('@')[-1].lower() if '@' in from_email_clean else ''

                # Get snippet
                snippet = msg_data.get('snippet', '')

                # Get full body for better extraction
                full_body = _get_email_body(msg_data.get('payload', {}))

                # Extract attachments
                attachments = []
                parts = msg_data.get('payload', {}).get('parts', [])
                for part in parts:
                    if part.get('filename') and part.get('body', {}).get('attachmentId'):
                        attachments.append({
                            'filename': part['filename'],
                            'attachment_id': part['body']['attachmentId'],
                            'mime_type': part.get('mimeType', ''),
                            'size': part.get('body', {}).get('size', 0)
                        })

                has_attachment = len(attachments) > 0

                # Build candidate for analysis
                candidate = ReceiptCandidate(
                    email_id=msg['id'],
                    from_email=from_email_clean,
                    from_domain=domain,
                    subject=subject,
                    body_snippet=snippet + ' ' + (full_body[:1000] if full_body else ''),
                    received_date=datetime.now(),  # Will be parsed from date_str
                    has_attachment=has_attachment,
                    attachments=attachments
                )

                # Analyze with intelligence engine
                result = engine.analyze_email(candidate)
                should_capture, reason = engine.should_capture(result)

                if not should_capture:
                    # Track why we're skipping
                    if result.confidence == ReceiptConfidence.NONE:
                        if 'Blocked' in reason:
                            stats['blocked'] += 1
                            print(f"   🚫 BLOCKED: {domain[:30]} - {subject[:40]}")
                        elif 'Unknown' in reason:
                            stats['unknown_domain'] += 1
                            # Only log unknown domains with receipt-like subjects
                            if any(kw in subject.lower() for kw in ['receipt', 'invoice', 'payment', 'order']):
                                print(f"   ❓ UNKNOWN: {domain[:30]} - {subject[:40]}")
                        else:
                            stats['low_confidence'] += 1
                    continue

                # Get merchant info
                merchant_name = result.extracted_merchant_name or result.matched_merchant.merchant_name if result.matched_merchant else None
                amount = float(result.extracted_amount) if result.extracted_amount else None
                is_subscription = result.matched_merchant.is_subscription if result.matched_merchant else False
                category = result.matched_merchant.category if result.matched_merchant else 'General'

                # Check for matching transaction
                match_id, has_receipt, needs_receipt, match_score = find_matching_transaction(
                    merchant_name, amount, date_str
                )

                # Skip if transaction already has receipt
                if match_id and has_receipt:
                    stats['already_exists'] += 1
                    print(f"   ⏭️  SKIP (has receipt): {merchant_name} - ${amount or '?'}")
                    continue

                match_type = 'new'
                if match_id:
                    match_type = 'needs_receipt' if needs_receipt else 'has_receipt'

                # Build receipt data
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
                    'attachments': json.dumps(attachments),
                    'confidence_score': result.confidence_score,
                    'merchant': merchant_name,
                    'amount': amount,
                    'description': f"[{category}] {subject[:100]}",
                    'is_subscription': is_subscription,
                    'matched_transaction_id': match_id,
                    'match_type': match_type,
                }

                new_receipts.append(receipt_data)
                stats['captured'] += 1

                confidence_emoji = '🎯' if result.confidence_score >= 90 else '✅' if result.confidence_score >= 70 else '❓'
                print(f"   {confidence_emoji} CAPTURE ({result.confidence_score}%): {merchant_name or domain} - ${amount or '?'} - {subject[:30]}")

            except Exception as e:
                print(f"   ⚠️  Error processing message: {e}")
                continue

        # Print summary
        print(f"\n   📊 SCAN SUMMARY:")
        print(f"      Total analyzed: {stats['total']}")
        print(f"      Captured: {stats['captured']}")
        print(f"      Blocked domains: {stats['blocked']}")
        print(f"      Unknown domains: {stats['unknown_domain']}")
        print(f"      Already has receipt: {stats['already_exists']}")

        return new_receipts

    except Exception as e:
        print(f"   ❌ Error scanning Gmail: {e}")
        import traceback
        traceback.print_exc()
        return []


def _get_email_body(payload, depth=0):
    """Extract text body from email payload - RECURSIVELY searches nested multipart"""
    if depth > 10:
        return ''

    body = ''

    # Check direct body first
    if not 'parts' in payload:
        data = payload.get('body', {}).get('data', '')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        return ''

    # Search in parts
    for part in payload['parts']:
        mime_type = part.get('mimeType', '')

        # Prefer text/plain
        if mime_type == 'text/plain':
            data = part.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

        # Fall back to HTML
        elif mime_type == 'text/html' and not body:
            data = part.get('body', {}).get('data', '')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

        # Recurse into nested multipart
        elif mime_type.startswith('multipart/') or 'parts' in part:
            result = _get_email_body(part, depth + 1)
            if result and not body:
                body = result

    return body


def run_intelligent_scan(accounts=None, since_date=None, save=True):
    """
    Run intelligent scan across all Gmail accounts.

    Args:
        accounts: List of account emails, or None for all configured accounts
        since_date: Date to scan from (YYYY-MM-DD), or None for last 7 days
        save: Whether to save results to database

    Returns:
        Dict with scan results
    """
    if accounts is None:
        accounts = [
            'brian@downhome.com',
            'kaplan.brian@gmail.com',
            'brian@musiccityrodeo.com'
        ]

    print("\n" + "="*60)
    print("🧠 INTELLIGENT RECEIPT SCANNER V2")
    print("="*60)
    print(f"Accounts: {', '.join(accounts)}")
    print(f"Since: {since_date or 'last 7 days'}")
    print("="*60)

    all_receipts = []
    saved_count = 0

    for account in accounts:
        receipts = scan_gmail_intelligent(account, since_date)

        if save and receipts:
            for receipt in receipts:
                result = save_incoming_receipt(receipt)
                if result:
                    saved_count += 1

        all_receipts.extend(receipts)

    print("\n" + "="*60)
    print(f"✅ SCAN COMPLETE")
    print(f"   Total receipts found: {len(all_receipts)}")
    print(f"   Saved to database: {saved_count}")
    print("="*60 + "\n")

    return {
        'total': len(all_receipts),
        'saved': saved_count,
        'receipts': all_receipts
    }


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'intelligent':
        # Run intelligent scan
        since_date = sys.argv[2] if len(sys.argv) > 2 else None
        run_intelligent_scan(since_date=since_date)
    elif len(sys.argv) > 1 and sys.argv[1] == 'init-whitelist':
        # Initialize the merchant whitelist
        print("Initializing merchant email domains...")
        init_merchant_email_domains_table()
        seed_merchant_email_domains()
    else:
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


def cleanup_inbox_and_rematch():
    """Clean up existing inbox by re-evaluating against stricter filters."""
    print("\n" + "="*60)
    print("🧹 INBOX CLEANUP & RE-MATCHING")
    print("="*60)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT id, subject, from_email, from_domain, body_snippet, has_attachment, amount, merchant, confidence_score FROM incoming_receipts WHERE status = 'pending' ORDER BY created_at DESC''')
    items = cursor.fetchall()
    print(f"\n📥 Found {len(items)} pending inbox items to evaluate\n")
    stats = {'total': len(items), 'rejected_no_amount': 0, 'rejected_spam_domain': 0, 'rejected_newsletter': 0, 'rejected_low_confidence': 0, 'kept_valid': 0, 'matched': 0}

    # Stripe-style receipt patterns (keep even without amount - amount is in PDF)
    stripe_receipt_patterns = ['your receipt from', 'your refund from', 'payment received', 'order confirmation']
    # Newsletter/marketing patterns to reject
    newsletter_patterns = ['newsletter', 'weekly digest', 'learns from', 'connect your apps', 'automate your', 'introducing', 'announcing', 'new feature']

    for item in items:
        item_id, subject, from_email, from_domain = item['id'], item['subject'] or '', item['from_email'] or '', item['from_domain'] or ''
        body_snippet, has_attachment, amount, merchant = item['body_snippet'] or '', item['has_attachment'], item['amount'], item['merchant']
        subject_lower, rejection_reason = subject.lower(), None

        # Check if this is a Stripe-style receipt (amount in PDF attachment)
        is_stripe_receipt = any(p in subject_lower for p in stripe_receipt_patterns)

        # Check if this is a newsletter/marketing email
        is_newsletter = any(p in subject_lower for p in newsletter_patterns)
        if not is_newsletter and 'updates@' in from_email.lower() and not is_stripe_receipt:
            is_newsletter = True

        # REJECT newsletters first (even with amount)
        if is_newsletter:
            rejection_reason, stats['rejected_newsletter'] = 'newsletter_content', stats['rejected_newsletter'] + 1
        # Only reject no_amount if NOT a Stripe-style receipt
        elif (not amount or float(amount) <= 0) and not is_stripe_receipt:
            rejection_reason, stats['rejected_no_amount'] = 'no_valid_amount', stats['rejected_no_amount'] + 1

        if not rejection_reason:
            for spam_domain in SPAM_SENDER_DOMAINS:
                if spam_domain in from_domain.lower() or spam_domain in from_email.lower():
                    rejection_reason, stats['rejected_spam_domain'] = f'spam_domain:{spam_domain}', stats['rejected_spam_domain'] + 1
                    break
        if not rejection_reason and not is_stripe_receipt:
            new_confidence = calculate_receipt_confidence(subject, from_email, body_snippet, has_attachment)
            if new_confidence < 70:  # Lower threshold - we want to keep more
                rejection_reason, stats['rejected_low_confidence'] = f'low_confidence:{new_confidence}', stats['rejected_low_confidence'] + 1

        if rejection_reason:
            cursor.execute('UPDATE incoming_receipts SET status = %s, rejection_reason = %s, reviewed_at = NOW() WHERE id = %s', ('auto_rejected', rejection_reason, item_id))
            print(f"   ❌ Rejected #{item_id}: {rejection_reason[:50]}")
        else:
            stats['kept_valid'] += 1
            if merchant and amount:
                match_id, has_receipt, needs_receipt, match_score = find_matching_transaction(merchant, float(amount), None)
                if match_id:
                    # Store match regardless of whether TX already has receipt
                    # match_type indicates: 'needs_receipt' or 'has_receipt'
                    match_type = 'has_receipt' if has_receipt else 'needs_receipt'
                    score_decimal = round(match_score / 100.0, 4) if match_score > 1 else match_score
                    cursor.execute('UPDATE incoming_receipts SET matched_transaction_id = %s, match_score = %s, match_type = %s WHERE id = %s',
                                  (match_id, score_decimal, match_type, item_id))
                    stats['matched'] += 1
                    status = "has receipt" if has_receipt else "needs receipt"
                    print(f"   ✅ Matched #{item_id} to TX #{match_id} ({status})")
    conn.commit()
    conn.close()
    return stats

def get_inbox_stats():
    """Get inbox statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as total, SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as pending, SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as accepted, SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as rejected, SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as auto_rejected FROM incoming_receipts', ('pending', 'accepted', 'rejected', 'auto_rejected'))
    result = cursor.fetchone()
    conn.close()
    return {'total': result['total'] or 0, 'pending': result['pending'] or 0, 'accepted': result['accepted'] or 0, 'rejected': result['rejected'] or 0, 'auto_rejected': result['auto_rejected'] or 0}


def aggressive_rematch_all():
    """
    Aggressively try to rematch ALL unmatched pending receipts.
    Uses improved merchant/amount/date extraction and more lenient matching.

    Returns:
        Dict with matching statistics
    """
    print("\n" + "="*60)
    print("🔄 AGGRESSIVE RE-MATCHING ALL UNMATCHED RECEIPTS")
    print("="*60)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all pending receipts without matches
    cursor.execute('''
        SELECT id, subject, from_email, from_domain, body_snippet, amount, merchant,
               receipt_date, received_date, created_at
        FROM incoming_receipts
        WHERE status = 'pending'
        AND (matched_transaction_id IS NULL OR matched_transaction_id = 0)
        ORDER BY created_at DESC
    ''')
    items = cursor.fetchall()

    print(f"\n📥 Found {len(items)} unmatched receipts to process\n")

    stats = {
        'total': len(items),
        'matched': 0,
        'updated_merchant': 0,
        'updated_amount': 0,
        'updated_date': 0,
        'still_unmatched': 0
    }

    for item in items:
        item_id = item['id']
        subject = item['subject'] or ''
        from_email = item['from_email'] or ''
        from_domain = item['from_domain'] or ''
        body_snippet = item['body_snippet'] or ''
        current_amount = item['amount']
        current_merchant = item['merchant']

        # Use received_date (email date) as fallback
        current_date = item['receipt_date']
        email_date_str = item['received_date'] or ''

        # Parse email date if available (format: "Fri, 15 Nov 2024 10:30:00 -0500")
        email_date = None
        if email_date_str:
            try:
                from email.utils import parsedate_to_datetime
                email_date = parsedate_to_datetime(email_date_str).strftime('%Y-%m-%d')
            except:
                # Try ISO format
                try:
                    email_date = email_date_str[:10] if len(email_date_str) >= 10 else None
                except:
                    pass

        # Re-extract merchant, amount, and date with improved extraction
        new_merchant, new_amount, new_date = extract_merchant_and_amount(subject, from_email, body_snippet)

        # IMPORTANT: Use email date as fallback when no date extracted
        if not new_date and email_date:
            new_date = email_date

        # Use new values if better than current
        merchant = new_merchant or current_merchant
        amount = new_amount if new_amount and new_amount > 0 else current_amount
        receipt_date = new_date or (str(current_date)[:10] if current_date else None) or email_date

        # Track what we updated
        updates = {}
        if new_merchant and new_merchant != current_merchant:
            updates['merchant'] = new_merchant
            stats['updated_merchant'] += 1
        if new_amount and new_amount > 0 and new_amount != current_amount:
            updates['amount'] = new_amount
            stats['updated_amount'] += 1
        if new_date and new_date != str(current_date)[:10] if current_date else True:
            updates['receipt_date'] = new_date
            stats['updated_date'] += 1

        # Update the record with better extraction
        if updates:
            set_clause = ', '.join(f"{k} = %s" for k in updates.keys())
            cursor.execute(f'UPDATE incoming_receipts SET {set_clause} WHERE id = %s',
                          list(updates.values()) + [item_id])

        # Try to find a match
        if merchant and amount and amount > 0:
            match_id, has_receipt, needs_receipt, match_score = find_matching_transaction(merchant, float(amount), receipt_date)

            if match_id:
                # Store ALL matches - both 'has_receipt' and 'needs_receipt' types
                match_type = 'has_receipt' if has_receipt else 'needs_receipt'
                score_decimal = round(match_score / 100.0, 4) if match_score > 1 else round(match_score, 4)
                cursor.execute('''
                    UPDATE incoming_receipts
                    SET matched_transaction_id = %s, match_score = %s, match_type = %s
                    WHERE id = %s
                ''', (match_id, score_decimal, match_type, item_id))
                stats['matched'] += 1
                status = "🔄 (already has receipt)" if has_receipt else "✅"
                print(f"   {status} #{item_id} -> TX #{match_id}: {merchant} ${amount}")
            else:
                stats['still_unmatched'] += 1
                if stats['still_unmatched'] <= 10:  # Show first 10 unmatched
                    print(f"   ❓ #{item_id}: {merchant or 'Unknown'} ${amount or '?'} ({receipt_date or 'no date'})")
        else:
            stats['still_unmatched'] += 1

    conn.commit()
    conn.close()

    print(f"\n📊 Results:")
    print(f"   Matched: {stats['matched']}")
    print(f"   Updated merchants: {stats['updated_merchant']}")
    print(f"   Updated amounts: {stats['updated_amount']}")
    print(f"   Updated dates: {stats['updated_date']}")
    print(f"   Still unmatched: {stats['still_unmatched']}")

    return stats


def reprocess_pending_receipts(limit=50, skip_with_amount=True):
    """
    Reprocess pending receipts that are missing amounts or AI notes.
    Re-fetches email from Gmail, extracts PDF attachments, runs Vision AI.

    Args:
        limit: Maximum number of receipts to process
        skip_with_amount: If True, only process receipts with amount=0 or NULL

    Returns:
        Dict with processing statistics
    """
    import json
    import base64
    import tempfile
    import os
    from pathlib import Path

    conn = get_db_connection()
    cursor = conn.cursor()

    stats = {
        'processed': 0,
        'amounts_extracted': 0,
        'notes_generated': 0,
        'errors': 0,
        'skipped': 0
    }

    # Get pending receipts that need reprocessing
    if skip_with_amount:
        cursor.execute('''
            SELECT id, email_id, gmail_account, subject, from_email, merchant, amount, ai_notes
            FROM incoming_receipts
            WHERE status = 'pending'
            AND (amount IS NULL OR amount = 0 OR ai_notes IS NULL OR ai_notes = '')
            AND email_id IS NOT NULL AND email_id != ''
            ORDER BY id DESC
            LIMIT %s
        ''', (limit,))
    else:
        cursor.execute('''
            SELECT id, email_id, gmail_account, subject, from_email, merchant, amount, ai_notes
            FROM incoming_receipts
            WHERE status = 'pending'
            AND email_id IS NOT NULL AND email_id != ''
            ORDER BY id DESC
            LIMIT %s
        ''', (limit,))

    receipts = cursor.fetchall()
    print(f"\n📧 Reprocessing {len(receipts)} pending receipts...")

    # Group by Gmail account for efficient token loading
    by_account = {}
    for r in receipts:
        account = r['gmail_account']
        if account not in by_account:
            by_account[account] = []
        by_account[account].append(r)

    for account_email, account_receipts in by_account.items():
        print(f"\n🔑 Processing {len(account_receipts)} receipts for {account_email}...")

        # Get Gmail service for this account
        service = None
        try:
            # Try to authenticate - use actual token file names
            account_key = account_email.replace('@', '_').replace('.', '_')
            token_paths = [
                Path('gmail_tokens') / f'tokens_{account_key}.json',
                Path('gmail_tokens') / f'{account_email.split("@")[0]}_token.json',
                Path('calendar_tokens.json'),
                Path('.') / 'calendar_token.json',
            ]

            for token_path in token_paths:
                if token_path.exists():
                    from google.oauth2.credentials import Credentials
                    from googleapiclient.discovery import build

                    try:
                        creds = Credentials.from_authorized_user_file(str(token_path))
                        service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
                        # Test the service
                        service.users().getProfile(userId='me').execute()
                        print(f"   ✓ Authenticated with {token_path}")
                        break
                    except Exception as e:
                        continue
        except Exception as e:
            print(f"   ⚠️ Could not authenticate for {account_email}: {e}")
            stats['skipped'] += len(account_receipts)
            continue

        if not service:
            print(f"   ⚠️ No valid token for {account_email}")
            stats['skipped'] += len(account_receipts)
            continue

        for receipt in account_receipts:
            receipt_id = receipt['id']
            email_id = receipt['email_id']
            subject = receipt['subject']
            from_email = receipt['from_email']
            current_amount = receipt['amount']
            current_notes = receipt['ai_notes']

            print(f"\n   📨 #{receipt_id}: {subject[:50]}...")

            try:
                # Fetch full email
                msg_data = service.users().messages().get(
                    userId='me', id=email_id, format='full'
                ).execute()

                payload = msg_data.get('payload', {})

                # Extract attachments
                attachments = []
                parts = payload.get('parts', [])
                for part in parts:
                    if part.get('filename') and part.get('body', {}).get('attachmentId'):
                        attachments.append({
                            'filename': part['filename'],
                            'attachment_id': part['body']['attachmentId']
                        })

                # Variables for extracted data
                new_amount = None
                new_notes = None
                new_merchant = None
                new_receipt_image_url = None
                new_thumbnail_url = None

                # Try to extract from PDF attachments
                for att in attachments:
                    filename = att.get('filename', '').lower()
                    if filename.endswith(('.pdf', '.jpg', '.jpeg', '.png')):
                        print(f"      📎 Processing: {att['filename']}")
                        try:
                            att_data = download_gmail_attachment(
                                service, email_id, att['attachment_id'], att['filename']
                            )
                            if att_data:
                                img_bytes = None
                                if filename.endswith('.pdf'):
                                    # Convert PDF to JPG
                                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                                        jpg_path = convert_pdf_to_jpg(att_data, tmp.name)
                                        if jpg_path and os.path.exists(jpg_path):
                                            with open(jpg_path, 'rb') as f:
                                                img_bytes = f.read()
                                            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                                            os.unlink(jpg_path)
                                        else:
                                            img_base64 = None
                                else:
                                    img_bytes = att_data
                                    img_base64 = base64.b64encode(att_data).decode('utf-8')

                                if img_base64:
                                    v_merchant, v_amount, v_desc, v_sub, v_is_receipt, v_cat, v_notes = analyze_image_with_vision(
                                        img_base64, subject_hint=subject, from_hint=from_email
                                    )
                                    if v_amount:
                                        new_amount = v_amount
                                        print(f"      💰 Amount extracted: ${v_amount}")
                                    if v_merchant:
                                        new_merchant = v_merchant
                                    if v_notes:
                                        new_notes = v_notes
                                        print(f"      📝 Notes: {v_notes}")

                                    # Upload image to R2 for preview (with thumbnail)
                                    if img_bytes and (v_amount or v_merchant):
                                        try:
                                            from r2_service import upload_with_thumbnail, R2_ENABLED
                                            if R2_ENABLED:
                                                import uuid
                                                r2_key = f"inbox/{uuid.uuid4().hex[:12]}.jpg"
                                                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                                                    tmp.write(img_bytes)
                                                    tmp_path = tmp.name
                                                full_url, thumb_url = upload_with_thumbnail(tmp_path, r2_key)
                                                os.unlink(tmp_path)
                                                if full_url:
                                                    new_receipt_image_url = full_url
                                                    new_thumbnail_url = thumb_url
                                                    print(f"      ☁️ Uploaded to R2: {r2_key}")
                                                    if thumb_url:
                                                        print(f"      🖼️ Thumbnail: {thumb_url}")
                                        except Exception as r2_err:
                                            print(f"      ⚠️ R2 upload failed: {r2_err}")

                                    if new_amount:
                                        break  # Got what we need
                        except Exception as e:
                            print(f"      ⚠️ Attachment error: {e}")

                # If no attachment or no amount from attachment, try HTML body
                if not new_amount or not new_notes:
                    def get_html_body(payload, depth=0):
                        """Extract HTML body - RECURSIVELY searches nested multipart"""
                        if depth > 10:
                            return None

                        # Check direct body
                        body = payload.get('body', {})
                        if body.get('data') and payload.get('mimeType') == 'text/html':
                            return base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')

                        # Search in parts recursively
                        if 'parts' in payload:
                            for part in payload['parts']:
                                mime_type = part.get('mimeType', '')
                                if mime_type == 'text/html':
                                    data = part.get('body', {}).get('data', '')
                                    if data:
                                        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                                # Recurse into nested multipart
                                if mime_type.startswith('multipart/') or 'parts' in part:
                                    result = get_html_body(part, depth + 1)
                                    if result:
                                        return result
                        return None

                    html_body = get_html_body(payload)
                    if html_body and len(html_body) > 200:
                        # Extract amount from HTML using regex
                        import re
                        amount_patterns = [
                            r'\$\s*([\d,]+\.?\d*)',
                            r'Total[:\s]+\$?([\d,]+\.?\d*)',
                            r'Amount[:\s]+\$?([\d,]+\.?\d*)',
                            r'Charge[:\s]+\$?([\d,]+\.?\d*)',
                        ]
                        for pattern in amount_patterns:
                            match = re.search(pattern, html_body, re.IGNORECASE)
                            if match:
                                try:
                                    amount_str = match.group(1).replace(',', '')
                                    new_amount = float(amount_str)
                                    if new_amount > 0 and new_amount < 100000:  # Sanity check
                                        print(f"      💰 Amount from HTML: ${new_amount}")
                                        break
                                except:
                                    pass

                        # Generate AI notes if missing
                        if not new_notes and not current_notes:
                            # Extract useful info from subject/email
                            subject_lower = subject.lower()
                            notes_parts = []

                            # Identify service type from subject
                            if 'apple' in from_email.lower():
                                if 'app store' in subject_lower or 'apple.com' in subject_lower:
                                    notes_parts.append('App Store purchase')
                            if 'subscription' in subject_lower:
                                notes_parts.append('Subscription payment')
                            if 'renewal' in subject_lower:
                                notes_parts.append('Subscription renewal')
                            if 'upgrade' in subject_lower:
                                notes_parts.append('Plan upgrade')

                            if notes_parts:
                                new_notes = '. '.join(notes_parts)

                # Update database
                updates = []
                params = []
                if new_amount and (not current_amount or float(current_amount) == 0):
                    updates.append('amount = %s')
                    params.append(new_amount)
                    stats['amounts_extracted'] += 1
                if new_notes and not current_notes:
                    updates.append('ai_notes = %s')
                    params.append(new_notes)
                    stats['notes_generated'] += 1
                if new_merchant and not receipt['merchant']:
                    updates.append('merchant = %s')
                    params.append(new_merchant)
                if attachments:
                    updates.append('attachments = %s')
                    params.append(json.dumps(attachments))
                    updates.append('has_attachment = %s')
                    params.append(True)
                    updates.append('attachment_count = %s')
                    params.append(len(attachments))
                if new_receipt_image_url:
                    updates.append('receipt_image_url = %s')
                    params.append(new_receipt_image_url)
                if new_thumbnail_url:
                    updates.append('thumbnail_url = %s')
                    params.append(new_thumbnail_url)

                if updates:
                    params.append(receipt_id)
                    cursor.execute(f'UPDATE incoming_receipts SET {", ".join(updates)} WHERE id = %s', params)
                    print(f"      ✅ Updated #{receipt_id}")

                stats['processed'] += 1

            except Exception as e:
                print(f"      ❌ Error: {e}")
                stats['errors'] += 1

    conn.commit()
    conn.close()

    print(f"\n{'='*50}")
    print("📊 REPROCESS RESULTS")
    print(f"{'='*50}")
    for k, v in stats.items():
        print(f"   {k}: {v}")

    return stats


def regenerate_screenshot(receipt_id: int) -> dict:
    """
    Regenerate screenshot for a specific receipt by re-fetching HTML from Gmail
    and rendering with Playwright.

    Returns: {'success': bool, 'url': str, 'error': str}
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get receipt info
        cursor.execute('''
            SELECT id, email_id, gmail_account, merchant, receipt_image_url
            FROM incoming_receipts WHERE id = %s
        ''', (receipt_id,))
        receipt = cursor.fetchone()

        if not receipt:
            return {'success': False, 'error': 'Receipt not found'}

        email_id = receipt['email_id']
        account = receipt['gmail_account']

        if not email_id or not account:
            return {'success': False, 'error': 'No email_id or account'}

        print(f"🔄 Regenerating screenshot for #{receipt_id} ({receipt['merchant']})")

        # Load Gmail service
        service = load_gmail_service(account)
        if not service:
            return {'success': False, 'error': f'Cannot load Gmail for {account}'}

        # Fetch email
        msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()
        payload = msg.get('payload', {})

        # Recursive HTML extraction
        def get_html_body(payload, depth=0):
            if depth > 10:
                return None
            body = payload.get('body', {})
            if body.get('data') and payload.get('mimeType') == 'text/html':
                return base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')
            if 'parts' in payload:
                for part in payload['parts']:
                    mime_type = part.get('mimeType', '')
                    if mime_type == 'text/html':
                        data = part.get('body', {}).get('data', '')
                        if data:
                            return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    if mime_type.startswith('multipart/') or 'parts' in part:
                        result = get_html_body(part, depth + 1)
                        if result:
                            return result
            return None

        html_body = get_html_body(payload)
        if not html_body or len(html_body) < 100:
            return {'success': False, 'error': 'No HTML content in email'}

        print(f"   📄 Found HTML: {len(html_body)} chars")

        # Generate screenshot
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            screenshot_path = screenshot_html_receipt(html_body, tmp.name)
            if not screenshot_path or not os.path.exists(screenshot_path):
                return {'success': False, 'error': 'Screenshot generation failed'}

            # Upload to R2
            from r2_service import upload_with_thumbnail, R2_ENABLED
            if not R2_ENABLED:
                return {'success': False, 'error': 'R2 not enabled'}

            import uuid
            r2_key = f"inbox/{uuid.uuid4().hex[:12]}.jpg"
            full_url, thumb_url = upload_with_thumbnail(screenshot_path, r2_key)

            if not full_url:
                return {'success': False, 'error': 'R2 upload failed'}

            print(f"   ☁️ Uploaded to: {r2_key}")

            # Update database
            cursor.execute('''
                UPDATE incoming_receipts
                SET receipt_image_url = %s, thumbnail_url = %s
                WHERE id = %s
            ''', (full_url, thumb_url, receipt_id))
            conn.commit()

            # Clean up temp file
            try:
                os.unlink(screenshot_path)
            except:
                pass

            return {
                'success': True,
                'url': full_url,
                'thumbnail': thumb_url
            }

    except Exception as e:
        import traceback
        print(f"   ❌ Error: {e}")
        traceback.print_exc()
        return {'success': False, 'error': str(e)}
    finally:
        conn.close()


def regenerate_small_screenshots(size_threshold_kb=40, limit=50) -> dict:
    """
    Find and regenerate screenshots that are likely text-based (small file size).

    Args:
        size_threshold_kb: Regenerate images smaller than this (default 40KB)
        limit: Max number to process

    Returns: Stats dict
    """
    import requests

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, merchant, receipt_image_url, amount
        FROM incoming_receipts
        WHERE status = 'pending'
        AND receipt_image_url IS NOT NULL
        AND receipt_image_url != ''
        ORDER BY id DESC
    ''')

    receipts = cursor.fetchall()
    conn.close()

    stats = {'checked': 0, 'small_found': 0, 'regenerated': 0, 'failed': 0}
    to_regenerate = []

    print(f"🔍 Checking {len(receipts)} receipts for small images...")

    for r in receipts:
        try:
            resp = requests.head(r['receipt_image_url'], timeout=5)
            size = int(resp.headers.get('content-length', 0))
            stats['checked'] += 1

            if size < size_threshold_kb * 1024:
                to_regenerate.append((r['id'], r['merchant'], size))
                stats['small_found'] += 1

                if len(to_regenerate) >= limit:
                    break
        except:
            pass

    print(f"📊 Found {stats['small_found']} small images (<{size_threshold_kb}KB)")

    for receipt_id, merchant, size in to_regenerate:
        print(f"\n{'='*50}")
        print(f"#{receipt_id}: {merchant} ({size/1024:.1f}KB)")
        result = regenerate_screenshot(receipt_id)
        if result['success']:
            stats['regenerated'] += 1
            print(f"   ✅ New URL: {result['url']}")
        else:
            stats['failed'] += 1
            print(f"   ❌ {result['error']}")

    print(f"\n{'='*50}")
    print("📊 REGENERATION COMPLETE")
    print(f"   Checked: {stats['checked']}")
    print(f"   Small found: {stats['small_found']}")
    print(f"   Regenerated: {stats['regenerated']}")
    print(f"   Failed: {stats['failed']}")

    return stats


def backfill_ai_notes(limit=100) -> dict:
    """
    Generate ai_notes for receipts that are missing them.
    Uses OpenAI to analyze email subject/body and generate expense descriptions.

    Args:
        limit: Max number to process

    Returns: Stats dict
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Find receipts missing ai_notes
    cursor.execute('''
        SELECT id, merchant, amount, subject, from_email, body_snippet
        FROM incoming_receipts
        WHERE status = 'pending'
        AND (ai_notes IS NULL OR ai_notes = '')
        ORDER BY id DESC
        LIMIT %s
    ''', (limit,))

    receipts = cursor.fetchall()
    print(f"🔍 Found {len(receipts)} receipts missing ai_notes")

    stats = {'processed': 0, 'updated': 0, 'failed': 0, 'skipped': 0}

    for r in receipts:
        receipt_id = r['id']
        merchant = r['merchant'] or 'Unknown'
        subject = r['subject'] or ''
        from_email = r['from_email'] or ''
        body = r['body_snippet'] or ''

        try:
            print(f"\n#{receipt_id}: {merchant} - {subject[:40]}...")

            # Use OpenAI to analyze and generate notes
            ai_merchant, ai_amount, description, is_subscription, category, ai_notes = analyze_email_with_openai(
                subject, from_email, body
            )

            if ai_notes:
                # Update the receipt with ai_notes (and optionally other fields if missing)
                updates = ['ai_notes = %s']
                params = [ai_notes]

                # Also update category if we got one and current is generic
                if category and category not in ['receipt', 'unknown']:
                    updates.append('category = COALESCE(NULLIF(category, "receipt"), %s)')
                    params.append(category)

                # Update description if we got one and current is empty
                if description and not r.get('description'):
                    updates.append('description = COALESCE(description, %s)')
                    params.append(description)

                params.append(receipt_id)
                cursor.execute(f'''
                    UPDATE incoming_receipts
                    SET {', '.join(updates)}
                    WHERE id = %s
                ''', tuple(params))

                conn.commit()
                stats['updated'] += 1
                print(f"   ✅ ai_notes: {ai_notes}")
            else:
                stats['skipped'] += 1
                print(f"   ⚠️ No ai_notes generated")

            stats['processed'] += 1

        except Exception as e:
            print(f"   ❌ Error: {e}")
            stats['failed'] += 1

    conn.close()

    print(f"\n{'='*50}")
    print("📊 BACKFILL COMPLETE")
    print(f"   Processed: {stats['processed']}")
    print(f"   Updated: {stats['updated']}")
    print(f"   Skipped: {stats['skipped']}")
    print(f"   Failed: {stats['failed']}")

    return stats
