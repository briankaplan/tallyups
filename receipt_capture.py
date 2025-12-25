#!/usr/bin/env python3
"""
Receipt Capture Pipeline
========================
Smart capture system that:
1. Downloads email attachments (PDF, images)
2. Screenshots HTML emails when no attachment
3. Converts everything to consistent JPG format
4. Uploads to R2 cloud storage
5. Returns URLs ready for transaction attachment
"""

import os
import re
import json
import base64
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# R2 Configuration - Use centralized config
try:
    from config.r2_config import R2Config
    R2_ACCESS_KEY_ID = R2Config.ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY = R2Config.SECRET_ACCESS_KEY
    R2_ENDPOINT_URL = R2Config.ENDPOINT_URL
    R2_BUCKET_NAME = R2Config.BUCKET_NAME
    R2_PUBLIC_URL = R2Config.PUBLIC_URL  # R2Config now has fallback built in
except ImportError:
    # SECURITY: No hardcoded credentials - use environment variables
    R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID', '')
    R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')
    R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL', '')
    R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'bkreceipts')
    # PUBLIC_URL MUST have a fallback or all image URLs will be broken
    R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '') or 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev'

# Local fallback directory
LOCAL_RECEIPTS_DIR = Path('receipts/incoming')
LOCAL_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

# Supported file types
SUPPORTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.heic', '.webp'}


# =============================================================================
# R2 UPLOAD
# =============================================================================

def get_r2_client():
    """Get R2 client if configured"""
    if not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL]):
        return None

    try:
        import boto3
        return boto3.client(
            's3',
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        )
    except ImportError:
        print("⚠️  boto3 not installed - R2 upload disabled")
        return None
    except Exception as e:
        print(f"⚠️  Could not create R2 client: {e}")
        return None


def upload_to_r2(file_data: bytes, filename: str, content_type: str = 'image/jpeg') -> Optional[str]:
    """
    Upload file to R2 and return public URL.

    Args:
        file_data: Raw file bytes
        filename: Destination filename (will be placed in receipts/ folder)
        content_type: MIME type of file

    Returns:
        Public URL if successful, None if failed
    """
    client = get_r2_client()
    if not client:
        return None

    try:
        key = f"receipts/{filename}"

        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=file_data,
            ContentType=content_type,
        )

        # Return public URL
        if R2_PUBLIC_URL:
            return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
        else:
            return f"r2://{R2_BUCKET_NAME}/{key}"

    except Exception as e:
        print(f"⚠️  R2 upload failed: {e}")
        return None


# =============================================================================
# PDF CONVERSION
# =============================================================================

def convert_pdf_to_jpg(pdf_data: bytes, dpi: int = 150) -> List[bytes]:
    """
    Convert PDF to JPG images.

    Args:
        pdf_data: Raw PDF bytes
        dpi: Resolution for conversion

    Returns:
        List of JPG image bytes (one per page)
    """
    try:
        # Try PyMuPDF first (faster)
        import fitz
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        images = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # Convert at specified DPI
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image then to JPEG bytes
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=85, optimize=True)
            images.append(buffer.getvalue())

        doc.close()
        return images

    except ImportError:
        # Fall back to pdf2image
        try:
            from pdf2image import convert_from_bytes
            pages = convert_from_bytes(pdf_data, dpi=dpi)
            images = []

            for page in pages:
                buffer = BytesIO()
                page.save(buffer, format='JPEG', quality=85, optimize=True)
                images.append(buffer.getvalue())

            return images

        except ImportError:
            print("⚠️  Neither PyMuPDF nor pdf2image available - PDF conversion disabled")
            return []
        except Exception as e:
            print(f"⚠️  PDF conversion error (pdf2image): {e}")
            return []

    except Exception as e:
        print(f"⚠️  PDF conversion error (PyMuPDF): {e}")
        return []


# =============================================================================
# IMAGE PROCESSING
# =============================================================================

def convert_to_jpg(image_data: bytes, filename: str = '') -> Optional[bytes]:
    """
    Convert any image to optimized JPG.

    Args:
        image_data: Raw image bytes
        filename: Original filename (for extension detection)

    Returns:
        JPG bytes if successful, None if failed
    """
    try:
        # Handle HEIC files
        if filename.lower().endswith('.heic'):
            try:
                import pillow_heif
                heif_file = pillow_heif.read_heif(image_data)
                img = Image.frombytes(
                    heif_file.mode,
                    heif_file.size,
                    heif_file.data,
                    "raw",
                )
            except ImportError:
                print("⚠️  pillow-heif not available - HEIC conversion disabled")
                return None
        else:
            img = Image.open(BytesIO(image_data))

        # Convert to RGB if necessary (for PNGs with transparency)
        if img.mode in ('RGBA', 'P', 'LA'):
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Optimize size - max 2000px on longest side
        max_size = 2000
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Save as optimized JPEG
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=85, optimize=True)
        return buffer.getvalue()

    except Exception as e:
        print(f"⚠️  Image conversion error: {e}")
        return None


# =============================================================================
# HTML SCREENSHOT
# =============================================================================

def screenshot_html(html_content: str, width: int = 800) -> Optional[bytes]:
    """
    Take screenshot of HTML content.

    Args:
        html_content: HTML string to screenshot
        width: Viewport width

    Returns:
        JPG bytes if successful, None if failed
    """
    # Try Playwright first (best quality)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 1000})

            # Set content
            page.set_content(html_content)
            page.wait_for_timeout(500)  # Wait for rendering

            # Get full page height
            height = page.evaluate('document.documentElement.scrollHeight')
            page.set_viewport_size({'width': width, 'height': min(height, 10000)})

            # Screenshot
            screenshot_bytes = page.screenshot(full_page=True, type='png')
            browser.close()

            # Convert to optimized JPG
            return convert_to_jpg(screenshot_bytes)

    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️  Playwright screenshot error: {e}")

    # Fall back to imgkit (wkhtmltoimage)
    try:
        import imgkit

        # Configure imgkit
        options = {
            'format': 'png',
            'width': str(width),
            'quality': '85',
            'quiet': '',
        }

        # Create screenshot
        png_bytes = imgkit.from_string(html_content, False, options=options)

        # Convert to optimized JPG
        return convert_to_jpg(png_bytes)

    except ImportError:
        print("⚠️  Neither Playwright nor imgkit available - HTML screenshot disabled")
        return None
    except Exception as e:
        print(f"⚠️  imgkit screenshot error: {e}")
        return None


# =============================================================================
# GMAIL ATTACHMENT DOWNLOAD
# =============================================================================

def download_gmail_attachment(service, message_id: str, attachment_id: str) -> Optional[bytes]:
    """
    Download attachment from Gmail.

    Args:
        service: Gmail API service object
        message_id: Email message ID
        attachment_id: Attachment ID

    Returns:
        Raw attachment bytes if successful, None if failed
    """
    try:
        attachment = service.users().messages().attachments().get(
            userId='me',
            messageId=message_id,
            id=attachment_id
        ).execute()

        data = attachment.get('data', '')
        if data:
            return base64.urlsafe_b64decode(data)
        return None

    except Exception as e:
        print(f"⚠️  Error downloading attachment: {e}")
        return None


# =============================================================================
# CAPTURE PIPELINE
# =============================================================================

class CaptureResult:
    """Result of a capture operation"""
    def __init__(self):
        self.success: bool = False
        self.local_path: Optional[str] = None
        self.r2_url: Optional[str] = None
        self.file_hash: Optional[str] = None
        self.file_size: int = 0
        self.source_type: str = ''  # 'attachment', 'html_screenshot'
        self.error: Optional[str] = None


def capture_receipt_from_email(
    service,
    message_id: str,
    attachments: List[Dict],
    html_body: str = '',
    merchant_name: str = 'unknown',
    email_date: str = ''
) -> CaptureResult:
    """
    Capture receipt from email - try attachments first, then screenshot HTML.

    Args:
        service: Gmail API service
        message_id: Email message ID
        attachments: List of attachment dicts with 'filename' and 'attachment_id'
        html_body: HTML body content (for screenshot fallback)
        merchant_name: Merchant name for filename
        email_date: Email date for filename

    Returns:
        CaptureResult with file info
    """
    result = CaptureResult()

    # Clean merchant name for filename
    safe_merchant = re.sub(r'[^a-zA-Z0-9]', '_', merchant_name.lower())[:30]

    # Generate date string
    if email_date:
        try:
            # Parse various date formats
            for fmt in ['%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%d', '%d %b %Y']:
                try:
                    dt = datetime.strptime(email_date.split(' (')[0].strip(), fmt)
                    date_str = dt.strftime('%Y%m%d')
                    break
                except:
                    continue
            else:
                date_str = datetime.now().strftime('%Y%m%d')
        except:
            date_str = datetime.now().strftime('%Y%m%d')
    else:
        date_str = datetime.now().strftime('%Y%m%d')

    # Try attachments first
    for att in attachments:
        filename = att.get('filename', '')
        attachment_id = att.get('attachment_id', '')
        ext = Path(filename).suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            continue

        print(f"      📎 Downloading: {filename}")
        data = download_gmail_attachment(service, message_id, attachment_id)

        if not data:
            continue

        # Process based on file type
        if ext == '.pdf':
            print(f"      🔄 Converting PDF to JPG...")
            jpg_pages = convert_pdf_to_jpg(data)
            if jpg_pages:
                # Use first page
                jpg_data = jpg_pages[0]
            else:
                continue
        else:
            # Convert image to optimized JPG
            jpg_data = convert_to_jpg(data, filename)
            if not jpg_data:
                continue

        # Generate unique filename
        file_hash = hashlib.md5(jpg_data).hexdigest()[:8]
        output_filename = f"{safe_merchant}_{date_str}_{file_hash}.jpg"

        # Save locally
        local_path = LOCAL_RECEIPTS_DIR / output_filename
        with open(local_path, 'wb') as f:
            f.write(jpg_data)
        result.local_path = str(local_path)

        # Upload to R2
        r2_url = upload_to_r2(jpg_data, output_filename)
        if r2_url:
            result.r2_url = r2_url
            print(f"      ☁️  Uploaded to R2: {output_filename}")

        result.success = True
        result.file_hash = file_hash
        result.file_size = len(jpg_data)
        result.source_type = 'attachment'
        return result

    # No suitable attachment - try HTML screenshot
    if html_body:
        print(f"      📸 No attachment - screenshotting HTML...")
        jpg_data = screenshot_html(html_body)

        if jpg_data:
            file_hash = hashlib.md5(jpg_data).hexdigest()[:8]
            output_filename = f"{safe_merchant}_{date_str}_{file_hash}.jpg"

            # Save locally
            local_path = LOCAL_RECEIPTS_DIR / output_filename
            with open(local_path, 'wb') as f:
                f.write(jpg_data)
            result.local_path = str(local_path)

            # Upload to R2
            r2_url = upload_to_r2(jpg_data, output_filename)
            if r2_url:
                result.r2_url = r2_url
                print(f"      ☁️  Uploaded to R2: {output_filename}")

            result.success = True
            result.file_hash = file_hash
            result.file_size = len(jpg_data)
            result.source_type = 'html_screenshot'
            return result

    result.error = "No capturable content found"
    return result


def capture_receipt_batch(
    service,
    receipts: List[Dict],
    auto_save: bool = True
) -> Dict[str, CaptureResult]:
    """
    Capture receipts for a batch of incoming receipts.

    Args:
        service: Gmail API service
        receipts: List of receipt dicts with email_id, attachments, etc.
        auto_save: Whether to update database with capture results

    Returns:
        Dict mapping email_id to CaptureResult
    """
    results = {}

    for receipt in receipts:
        email_id = receipt.get('email_id', '')
        if not email_id:
            continue

        print(f"\n   📨 Capturing: {receipt.get('subject', '')[:50]}")

        # Parse attachments if JSON string
        attachments = receipt.get('attachments', [])
        if isinstance(attachments, str):
            try:
                attachments = json.loads(attachments)
            except:
                attachments = []

        result = capture_receipt_from_email(
            service=service,
            message_id=email_id,
            attachments=attachments,
            html_body=receipt.get('body_html', ''),
            merchant_name=receipt.get('merchant', 'unknown'),
            email_date=receipt.get('received_date', '')
        )

        results[email_id] = result

        if result.success:
            print(f"      ✅ Captured: {result.local_path}")
        else:
            print(f"      ❌ Failed: {result.error}")

    return results


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == 'test-pdf':
            # Test PDF conversion
            if len(sys.argv) > 2:
                pdf_path = sys.argv[2]
                with open(pdf_path, 'rb') as f:
                    pdf_data = f.read()
                pages = convert_pdf_to_jpg(pdf_data)
                print(f"Converted {len(pages)} pages")
                if pages:
                    with open('test_output.jpg', 'wb') as f:
                        f.write(pages[0])
                    print("Saved first page to test_output.jpg")
            else:
                print("Usage: python receipt_capture.py test-pdf <path.pdf>")

        elif command == 'test-screenshot':
            # Test HTML screenshot
            html = """
            <html>
            <body style="font-family: Arial; padding: 20px;">
                <h1>Test Receipt</h1>
                <p>Merchant: Anthropic</p>
                <p>Amount: $20.00</p>
                <p>Date: 2025-01-01</p>
            </body>
            </html>
            """
            jpg_data = screenshot_html(html)
            if jpg_data:
                with open('test_screenshot.jpg', 'wb') as f:
                    f.write(jpg_data)
                print("Saved screenshot to test_screenshot.jpg")
            else:
                print("Screenshot failed")

        elif command == 'test-r2':
            # Test R2 upload
            test_data = b"Test data"
            url = upload_to_r2(test_data, "test_upload.txt", "text/plain")
            if url:
                print(f"Uploaded to: {url}")
            else:
                print("R2 upload failed - check credentials")

        else:
            print(f"Unknown command: {command}")
    else:
        print("Receipt Capture Pipeline")
        print("Usage:")
        print("  python receipt_capture.py test-pdf <path.pdf>")
        print("  python receipt_capture.py test-screenshot")
        print("  python receipt_capture.py test-r2")
