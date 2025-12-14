#!/usr/bin/env python3
"""
Regenerate HTML screenshots using Playwright for real browser rendering.
Replaces ugly text-only screenshots with actual visual receipts.

Usage:
    python scripts/regenerate_html_screenshots.py [--limit 50]
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

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# MySQL connection
mysql_url = os.getenv('MYSQL_URL', '')
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

from r2_service import upload_with_thumbnail, R2_ENABLED
from PIL import Image

# Gmail credentials
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import pickle

def get_gmail_service(account_email):
    """Load Gmail service for account"""
    base_dir = Path(__file__).parent.parent

    # Get client credentials from env
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')

    # Try JSON token files
    json_variations = [
        base_dir / f"gmail_tokens/tokens_{account_email.replace('@', '_').replace('.', '_')}.json",
        base_dir / f"gmail_tokens/tokens_{account_email.split('@')[0]}_{account_email.split('@')[1].replace('.', '_')}.json",
    ]

    for token_file in json_variations:
        if token_file.exists():
            try:
                with open(token_file, 'r') as f:
                    token_data = json.load(f)

                from google.auth.transport.requests import Request

                # Handle both old format (token) and new format (access_token)
                access_token = token_data.get('access_token') or token_data.get('token')
                refresh_token = token_data.get('refresh_token')

                # Handle scopes - could be string (new) or array (old)
                scopes = token_data.get('scope') or token_data.get('scopes')
                if isinstance(scopes, str):
                    scopes = scopes.split()

                # Use client credentials from token file or env
                cred_client_id = token_data.get('client_id') or client_id
                cred_client_secret = token_data.get('client_secret') or client_secret
                token_uri = token_data.get('token_uri', 'https://oauth2.googleapis.com/token')

                creds = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri=token_uri,
                    client_id=cred_client_id,
                    client_secret=cred_client_secret,
                    scopes=scopes
                )

                # Refresh if expired
                if refresh_token and cred_client_id and cred_client_secret:
                    if creds.expired or not creds.valid:
                        try:
                            creds.refresh(Request())
                            # Update token file with new access token
                            token_data['access_token'] = creds.token
                            with open(token_file, 'w') as f:
                                json.dump(token_data, f, indent=2)
                        except Exception as refresh_err:
                            print(f"    Refresh failed: {refresh_err}")

                return build('gmail', 'v1', credentials=creds)
            except Exception as e:
                print(f"    Token error: {e}")

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

def html_to_real_screenshot(html_content):
    """Take real browser screenshot of HTML using Playwright"""
    try:
        from playwright.sync_api import sync_playwright
        import shutil

        with sync_playwright() as p:
            browser = None

            # Try bundled browser first
            try:
                browser = p.chromium.launch(headless=True)
            except:
                # Fall back to system Chrome
                chrome_paths = [
                    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                    '/usr/bin/chromium',
                    '/usr/bin/google-chrome',
                    shutil.which('chromium'),
                    shutil.which('google-chrome'),
                ]
                for path in chrome_paths:
                    if path and os.path.exists(path):
                        try:
                            browser = p.chromium.launch(headless=True, executable_path=path)
                            break
                        except:
                            continue

            if not browser:
                return None

            page = browser.new_page(viewport={'width': 800, 'height': 1200})

            # Wrap HTML with styling
            wrapped = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: white; margin: 0; padding: 20px; max-width: 800px; color: #333; }}
img {{ max-width: 100%; height: auto; }}
table {{ max-width: 100%; border-collapse: collapse; }}
td, th {{ padding: 8px; border: 1px solid #ddd; }}
</style></head><body>{html_content}</body></html>"""

            page.set_content(wrapped, wait_until='networkidle', timeout=15000)
            page.wait_for_timeout(500)

            # Screenshot
            height = min(page.evaluate('document.body.scrollHeight') + 40, 3000)
            page.set_viewport_size({'width': 800, 'height': height})
            png = page.screenshot(type='png', full_page=True)
            browser.close()

            # Convert to JPEG
            img = Image.open(BytesIO(png))
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            output = BytesIO()
            img.save(output, format='JPEG', quality=90)
            return output.getvalue()

    except Exception as e:
        print(f"    Screenshot error: {e}")
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()

    if not R2_ENABLED:
        print("ERROR: R2 not enabled")
        sys.exit(1)

    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()

    # Get HTML-sourced receipts to regenerate
    cursor.execute('''
        SELECT id, email_id, gmail_account, subject
        FROM incoming_receipts
        WHERE image_source = 'html'
        AND email_id IS NOT NULL
        AND gmail_account IS NOT NULL
        ORDER BY received_date DESC
        LIMIT %s
    ''', (args.limit,))
    rows = cursor.fetchall()

    print(f"Regenerating {len(rows)} HTML screenshots with real browser rendering...")

    success = 0
    failed = 0
    gmail_services = {}

    for i, row in enumerate(rows):
        receipt_id = row['id']
        email_id = row['email_id']
        gmail_account = row['gmail_account']
        subject = row['subject'] or 'Unknown'

        print(f"\n[{i+1}/{len(rows)}] {subject[:50]}...")

        # Get Gmail service
        if gmail_account not in gmail_services:
            gmail_services[gmail_account] = get_gmail_service(gmail_account)
        service = gmail_services[gmail_account]

        if not service:
            print("    ❌ No Gmail token")
            failed += 1
            continue

        # Get HTML
        html = get_email_html(service, email_id)
        if not html or len(html) < 100:
            print("    ❌ No HTML content")
            failed += 1
            continue

        # Take real screenshot
        img_bytes = html_to_real_screenshot(html)
        if not img_bytes:
            print("    ❌ Screenshot failed")
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
                SET receipt_image_url = %s, thumbnail_url = %s, image_source = 'html_real'
                WHERE id = %s
            ''', (full_url, thumb_url, receipt_id))
            conn.commit()
            print(f"    ✅ Real screenshot uploaded")
            success += 1
        else:
            print(f"    ❌ R2 upload failed")
            failed += 1

    conn.close()
    print(f"\n{'='*50}")
    print(f"Done! Success: {success}, Failed: {failed}")
    print(f"Remaining: {537 - success} HTML screenshots")

if __name__ == '__main__':
    main()
