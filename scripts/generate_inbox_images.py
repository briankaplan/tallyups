#!/usr/bin/env python3
"""
Generate images for incoming receipts that are missing receipt_image_url.
Processes receipts by:
1. Downloading attachments from Gmail (PDF/images)
2. Taking HTML screenshots for HTML-only emails
3. Uploading to R2 with thumbnails
4. Updating database with URLs

Usage:
    python scripts/generate_inbox_images.py [--limit 50]
"""
import pymysql
import pymysql.cursors
import json
import os
import sys
import tempfile
import base64
import uuid
import argparse
from io import BytesIO
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# MySQL connection
mysql_url = os.getenv('MYSQL_URL', 'mysql://root:xruqdfYXOPFlfkqAPaRCrPFqxMaXMuiL@metro.proxy.rlwy.net:19800/railway')
parts = mysql_url.replace('mysql://', '').split('@')
user_pass = parts[0].split(':')
host_port_db = parts[1].split('/')
host_port = host_port_db[0].split(':')

MYSQL_CONFIG = {
    'host': host_port[0],
    'port': int(host_port[1]),
    'user': user_pass[0],
    'password': user_pass[1],
    'database': host_port_db[1],
    'cursorclass': pymysql.cursors.DictCursor
}

# Import R2 service
from r2_service import upload_with_thumbnail, R2_ENABLED

# Gmail credentials
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import pickle

# PIL and PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF
import re

def get_gmail_service(account_email):
    """Load Gmail service for account using JSON tokens"""
    base_dir = Path(__file__).parent.parent

    # Try JSON token files first (newer, more reliable)
    json_variations = [
        base_dir / f"gmail_tokens/tokens_{account_email.replace('@', '_').replace('.', '_')}.json",
        base_dir / f"gmail_tokens/tokens_{account_email.split('@')[0]}_{account_email.split('@')[1].replace('.', '_')}.json",
    ]

    for token_file in json_variations:
        if token_file.exists():
            try:
                with open(token_file, 'r') as f:
                    token_data = json.load(f)

                from google.oauth2.credentials import Credentials
                from google.auth.transport.requests import Request

                creds = Credentials(
                    token=token_data['token'],
                    refresh_token=token_data['refresh_token'],
                    token_uri=token_data['token_uri'],
                    client_id=token_data['client_id'],
                    client_secret=token_data['client_secret'],
                    scopes=token_data['scopes']
                )

                # Refresh if needed
                if creds.expired or not creds.valid:
                    creds.refresh(Request())
                    token_data['token'] = creds.token
                    with open(token_file, 'w') as f:
                        json.dump(token_data, f, indent=2)

                return build('gmail', 'v1', credentials=creds)
            except Exception as e:
                print(f"    Error with JSON token: {e}")

    # Fall back to pickle files
    pickle_variations = [
        base_dir / f"config/token_{account_email.replace('@', '_').replace('.', '_')}.pickle",
        base_dir / f"config/token_{account_email.split('@')[0]}_{account_email.split('@')[1].replace('.', '_')}.pickle",
    ]

    for token_file in pickle_variations:
        if token_file.exists():
            try:
                with open(token_file, 'rb') as f:
                    creds = pickle.load(f)
                return build('gmail', 'v1', credentials=creds)
            except Exception as e:
                print(f"    Error loading pickle: {e}")

    print(f"    No token for {account_email}")
    return None

def download_attachment(service, message_id, attachment_id):
    """Download attachment from Gmail"""
    try:
        attachment = service.users().messages().attachments().get(
            userId='me', messageId=message_id, id=attachment_id
        ).execute()
        return base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
    except Exception as e:
        print(f"    Download error: {e}")
        return None

def pdf_to_jpg(pdf_bytes):
    """Convert PDF to JPG using PyMuPDF"""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            return None
        page = doc[0]
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        output = BytesIO()
        img.save(output, format='JPEG', quality=90)
        return output.getvalue()
    except Exception as e:
        print(f"    PDF conversion error: {e}")
        return None

def html_to_image(html_content):
    """
    Convert HTML email to image using Playwright browser rendering.
    This captures the ACTUAL visual appearance of the email receipt.
    """
    try:
        from playwright.sync_api import sync_playwright
        import shutil

        print("      📸 Using Playwright for real HTML screenshot...")

        with sync_playwright() as p:
            browser = None

            # Try bundled Playwright browser first
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                print(f"      ℹ️  Bundled browser not found, trying system chromium...")
                chromium_paths = [
                    '/usr/bin/chromium',
                    '/usr/bin/chromium-browser',
                    '/usr/bin/google-chrome',
                    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                    shutil.which('chromium'),
                    shutil.which('google-chrome'),
                ]

                for chrome_path in chromium_paths:
                    if chrome_path and os.path.exists(chrome_path):
                        print(f"      🔧 Using: {chrome_path}")
                        try:
                            browser = p.chromium.launch(headless=True, executable_path=chrome_path)
                            break
                        except:
                            continue

                if not browser:
                    raise Exception("No browser found")

            page = browser.new_page(viewport={'width': 800, 'height': 1200})

            # Wrap HTML with proper styling
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
                </style>
            </head>
            <body>{html_content}</body>
            </html>
            """

            page.set_content(wrapped_html, wait_until='networkidle', timeout=10000)
            page.wait_for_timeout(500)

            # Get actual content height, cap at 3000px
            body_height = page.evaluate('document.body.scrollHeight')
            screenshot_height = min(body_height + 40, 3000)
            page.set_viewport_size({'width': 800, 'height': screenshot_height})

            png_bytes = page.screenshot(type='png', full_page=True)
            browser.close()

            # Convert to JPEG
            img = Image.open(BytesIO(png_bytes))
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            output = BytesIO()
            img.save(output, format='JPEG', quality=90, optimize=True)
            print(f"      ✅ Real screenshot: {len(output.getvalue())} bytes")
            return output.getvalue()

    except Exception as e:
        print(f"    Playwright error: {e}")
        return None

def get_email_html(service, message_id):
    """Get HTML body from email"""
    try:
        msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        payload = msg.get('payload', {})

        def extract_html(p):
            if p.get('mimeType') == 'text/html':
                data = p.get('body', {}).get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            if 'parts' in p:
                for part in p['parts']:
                    result = extract_html(part)
                    if result:
                        return result
            return None

        return extract_html(payload)
    except Exception as e:
        print(f"    Email fetch error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Generate images for inbox receipts')
    parser.add_argument('--limit', type=int, default=50, help='Max receipts to process')
    args = parser.parse_args()

    print(f"R2 Enabled: {R2_ENABLED}")
    if not R2_ENABLED:
        print("ERROR: R2 not enabled!")
        sys.exit(1)

    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()

    # Get pending receipts without images
    cursor.execute('''
        SELECT id, email_id, gmail_account, subject, attachments
        FROM incoming_receipts
        WHERE status = 'pending'
        AND (receipt_image_url IS NULL OR receipt_image_url = '')
        AND email_id IS NOT NULL
        AND gmail_account IS NOT NULL
        ORDER BY received_date DESC
        LIMIT %s
    ''', (args.limit,))
    rows = cursor.fetchall()

    print(f"Processing {len(rows)} receipts...")

    success = 0
    failed = 0
    gmail_services = {}

    for i, row in enumerate(rows):
        receipt_id = row['id']
        email_id = row['email_id']
        gmail_account = row['gmail_account']
        subject = row['subject'] or 'Unknown'
        attachments_str = row.get('attachments', '[]')

        print(f"[{i+1}/{len(rows)}] {subject[:50]}...")

        # Get Gmail service
        if gmail_account not in gmail_services:
            gmail_services[gmail_account] = get_gmail_service(gmail_account)
        service = gmail_services[gmail_account]

        if not service:
            failed += 1
            continue

        img_bytes = None
        source = None

        # Try attachments first
        try:
            attachments = json.loads(attachments_str) if attachments_str else []
        except:
            attachments = []

        for att in attachments:
            filename = att.get('filename', '').lower()
            att_id = att.get('attachment_id', '')
            if not att_id:
                continue

            if filename.endswith(('.pdf', '.jpg', '.jpeg', '.png', '.gif')):
                print(f"    Downloading: {filename}")
                data = download_attachment(service, email_id, att_id)
                if data:
                    if filename.endswith('.pdf'):
                        img_bytes = pdf_to_jpg(data)
                        source = 'pdf'
                    else:
                        img_bytes = data
                        source = 'image'
                    if img_bytes:
                        break

        # If no attachment image, try HTML
        if not img_bytes:
            print(f"    Getting HTML screenshot...")
            html = get_email_html(service, email_id)
            if html and len(html) > 100:
                img_bytes = html_to_image(html)
                source = 'html'

        if not img_bytes:
            print(f"    ❌ No image generated")
            failed += 1
            continue

        # Upload to R2
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        r2_key = f"inbox/{uuid.uuid4().hex[:12]}.jpg"
        full_url, thumb_url = upload_with_thumbnail(tmp_path, r2_key)
        os.unlink(tmp_path)

        if full_url:
            cursor.execute('''
                UPDATE incoming_receipts
                SET receipt_image_url = %s, thumbnail_url = %s, image_source = %s
                WHERE id = %s
            ''', (full_url, thumb_url, source, receipt_id))
            conn.commit()
            print(f"    ✅ Uploaded ({source})")
            success += 1
        else:
            print(f"    ❌ R2 upload failed")
            failed += 1

    conn.close()
    print(f"\n{'='*50}")
    print(f"Done! Success: {success}, Failed: {failed}")
    print(f"Remaining: {438 - success} (approx)")


if __name__ == '__main__':
    main()
