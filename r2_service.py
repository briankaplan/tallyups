#!/usr/bin/env python3
"""
R2 Upload Service
Handles automatic upload of receipts to Cloudflare R2 storage

=== RECEIPT NAMING CONVENTION (LOCKED) ===

All receipts MUST follow this naming standard:
  {prefix}/{transaction_id}_{merchant}_{date}_{amount}.{ext}

Where:
  - prefix: 'downhome/', 'receipts/', or 'inbox/'
  - transaction_id: Database transaction ID (integer)
  - merchant: snake_case merchant name (max 35 chars)
  - date: YYYY-MM-DD format
  - amount: Amount with underscore decimal (e.g., 123_45)
  - ext: File extension (jpg, png, pdf)

Examples:
  - downhome/4287_soho_house_2025-12-02_3120_00.jpg
  - receipts/1234_hive_co_2025-08-20_199_20.jpg
  - inbox/uber_2025-12-10_36_95_a1b2c3d4.jpg

Use generate_standard_r2_key() for all uploads!
"""

import os
import re
import subprocess
import mimetypes
import hashlib
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# R2 Configuration from .env
# SECURITY: No hardcoded credentials - use environment variables
R2_ENDPOINT = os.getenv('R2_ENDPOINT', '')
R2_BUCKET = os.getenv('R2_BUCKET_NAME', 'bkreceipts')
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY_ID', '')
R2_SECRET_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')

# R2 Public URL - MUST have a fallback or all image URLs will be broken
# First try env var, then try importing from R2Config, then use production default
_r2_public_url = os.getenv('R2_PUBLIC_URL', '')
if not _r2_public_url:
    try:
        from config.r2_config import R2Config
        _r2_public_url = R2Config.PUBLIC_URL or ''
    except ImportError:
        pass
if not _r2_public_url:
    # Fallback to production R2 bucket URL
    _r2_public_url = 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev'
R2_PUBLIC_URL = _r2_public_url

# Use Homebrew curl for OpenSSL support (required on macOS)
CURL_PATH = '/opt/homebrew/opt/curl/bin/curl'
if not os.path.exists(CURL_PATH):
    CURL_PATH = 'curl'

# Check if R2 is configured
R2_ENABLED = bool(R2_ACCESS_KEY and R2_SECRET_KEY)


# =============================================================================
# STANDARD NAMING CONVENTION FUNCTIONS (LOCKED)
# =============================================================================

def sanitize_merchant(merchant: str) -> str:
    """
    Convert merchant name to snake_case for filename.
    STANDARD: lowercase, underscores, max 35 chars
    """
    if not merchant:
        return 'unknown'
    # Remove special chars, keep alphanumeric and spaces
    clean = re.sub(r'[^a-zA-Z0-9\s]', '', str(merchant))
    # Convert to snake_case
    clean = '_'.join(clean.lower().split())
    # Limit length
    return clean[:35] if clean else 'unknown'


def format_amount(amount) -> str:
    """
    Format amount for filename: 123.45 -> 123_45
    STANDARD: Replace decimal with underscore
    """
    try:
        return f"{abs(float(amount)):.2f}".replace('.', '_')
    except (ValueError, TypeError):
        return '0_00'


def format_date(date_str) -> str:
    """
    Format date to YYYY-MM-DD standard.
    Handles MM/DD/YY, YYYY-MM-DD, and datetime objects.
    """
    if not date_str:
        return datetime.now().strftime('%Y-%m-%d')

    # Already in correct format
    if isinstance(date_str, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    # Handle datetime objects
    if hasattr(date_str, 'strftime'):
        return date_str.strftime('%Y-%m-%d')

    # Handle MM/DD/YY or MM/DD/YYYY
    if '/' in str(date_str):
        try:
            parts = str(date_str).split('/')
            if len(parts) == 3:
                m, d, y = parts
                if len(y) == 2:
                    y = f"20{y}"
                return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        except:
            pass

    return datetime.now().strftime('%Y-%m-%d')


def generate_standard_r2_key(
    transaction_id: int = None,
    merchant: str = None,
    date: str = None,
    amount: float = None,
    business_type: str = None,
    extension: str = 'jpg',
    source: str = None
) -> str:
    """
    Generate a standardized R2 key following the LOCKED naming convention.

    NAMING CONVENTION:
      {prefix}/{transaction_id}_{merchant}_{date}_{amount}.{ext}

    Args:
        transaction_id: Database transaction ID (required for linked receipts)
        merchant: Merchant/vendor name
        date: Transaction date (any format, will be normalized)
        amount: Transaction amount
        business_type: 'Down Home', 'Music City Rodeo', etc. (determines prefix)
        extension: File extension (default: jpg)
        source: Source hint for prefix ('inbox', 'gmail_inbox', etc.)

    Returns:
        Standard R2 key like 'downhome/4287_soho_house_2025-12-02_3120_00.jpg'
    """
    # Determine prefix based on business_type or source
    if business_type == 'Down Home':
        prefix = 'downhome'
    elif source in ('inbox', 'gmail_inbox', 'mobile_inbox', 'incoming'):
        prefix = 'inbox'
    else:
        prefix = 'receipts'

    # Sanitize components
    merchant_clean = sanitize_merchant(merchant)
    date_clean = format_date(date)
    amount_clean = format_amount(amount)
    ext = extension.lower().lstrip('.')

    # Build filename
    if transaction_id:
        # Standard format with transaction ID
        filename = f"{transaction_id}_{merchant_clean}_{date_clean}_{amount_clean}.{ext}"
    else:
        # Unlinked receipt - add hash for uniqueness
        hash_suffix = hashlib.md5(
            f"{merchant_clean}{date_clean}{amount_clean}{datetime.now()}".encode()
        ).hexdigest()[:8]
        filename = f"{merchant_clean}_{date_clean}_{amount_clean}_{hash_suffix}.{ext}"

    return f"{prefix}/{filename}"


def upload_to_r2(local_path: Path, key: str = None) -> tuple[bool, str]:
    """
    Upload a file to R2 storage.

    Args:
        local_path: Path to the local file
        key: R2 key (path in bucket). If None, uses receipts/{filename}

    Returns:
        (success, url_or_error): If successful, returns (True, public_url)
                                 If failed, returns (False, error_message)
    """
    if not R2_ENABLED:
        return False, "R2 not configured (missing credentials)"

    local_path = Path(local_path)
    if not local_path.exists():
        return False, f"File not found: {local_path}"

    # Default key is receipts/filename
    if key is None:
        key = f"receipts/{local_path.name}"

    # Get content type
    content_type, _ = mimetypes.guess_type(str(local_path))
    if not content_type:
        content_type = 'application/octet-stream'

    # Build URL
    url = f"{R2_ENDPOINT}/{R2_BUCKET}/{key}"

    try:
        result = subprocess.run([
            CURL_PATH, '-X', 'PUT', url,
            '--aws-sigv4', 'aws:amz:auto:s3',
            '--user', f'{R2_ACCESS_KEY}:{R2_SECRET_KEY}',
            '-H', f'Content-Type: {content_type}',
            '--data-binary', f'@{local_path}',
            '-s', '-w', '%{http_code}', '-o', '/dev/null'
        ], capture_output=True, text=True, timeout=60)

        http_code = result.stdout.strip()

        # Accept both 200 (OK) and 201 (Created) as success
        if http_code in ('200', '201'):
            public_url = f"{R2_PUBLIC_URL}/{key}"
            return True, public_url
        else:
            return False, f"HTTP {http_code}: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, "Upload timeout"
    except Exception as e:
        return False, str(e)


def get_public_url(filename: str) -> str:
    """Get the public R2 URL for a receipt filename"""
    if filename.startswith('receipts/'):
        key = filename
    else:
        key = f"receipts/{filename}"
    return f"{R2_PUBLIC_URL}/{key}"


def upload_receipt_and_get_url(local_path: Path) -> str:
    """
    Upload a receipt to R2 and return the public URL.
    Returns None if upload fails.
    """
    success, result = upload_to_r2(local_path)
    if success:
        return result
    else:
        print(f"R2 upload failed: {result}")
        return None


def delete_from_r2(key: str) -> bool:
    """
    Delete a file from R2 storage.

    Args:
        key: R2 key (path in bucket), e.g. 'receipts/incoming/filename.jpg'

    Returns:
        bool: True if deleted successfully, False otherwise
    """
    if not R2_ENABLED:
        print("R2 not configured (missing credentials)")
        return False

    # Build URL
    url = f"{R2_ENDPOINT}/{R2_BUCKET}/{key}"

    try:
        result = subprocess.run([
            CURL_PATH, '-X', 'DELETE', url,
            '--aws-sigv4', 'aws:amz:auto:s3',
            '--user', f'{R2_ACCESS_KEY}:{R2_SECRET_KEY}',
            '-s', '-w', '%{http_code}', '-o', '/dev/null'
        ], capture_output=True, text=True, timeout=30)

        http_code = result.stdout.strip()

        # 204 No Content is the expected success response for DELETE
        # 200 OK is also acceptable
        # 404 means it was already gone, which is fine
        if http_code in ('200', '204', '404'):
            return True
        else:
            print(f"R2 delete failed - HTTP {http_code}: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("R2 delete timeout")
        return False
    except Exception as e:
        print(f"R2 delete error: {e}")
        return False


def generate_thumbnail(image_path: Path, max_size: int = 300) -> Path:
    """
    Generate a thumbnail from an image file.

    Args:
        image_path: Path to the source image
        max_size: Maximum dimension (width or height) for thumbnail

    Returns:
        Path to the generated thumbnail, or None if failed
    """
    try:
        from PIL import Image

        image_path = Path(image_path)
        if not image_path.exists():
            return None

        # Open and resize image
        img = Image.open(image_path)

        # Convert RGBA to RGB if necessary (for JPEG)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Calculate new dimensions maintaining aspect ratio
        width, height = img.size
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))

        # Resize with high quality
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Save thumbnail
        thumb_path = image_path.parent / f"{image_path.stem}_thumb.jpg"
        img.save(thumb_path, 'JPEG', quality=85, optimize=True)

        return thumb_path

    except ImportError:
        print("PIL not available for thumbnail generation")
        return None
    except Exception as e:
        print(f"Thumbnail generation failed: {e}")
        return None


def upload_with_thumbnail(local_path: Path, r2_key: str = None) -> tuple[str, str]:
    """
    Upload an image to R2 along with its thumbnail.

    Args:
        local_path: Path to the source image
        r2_key: R2 key for the full image (thumbnail gets _thumb suffix)

    Returns:
        (full_url, thumbnail_url) - URLs for both images, None if upload failed
    """
    local_path = Path(local_path)

    # Upload full image
    success, full_url = upload_to_r2(local_path, r2_key)
    if not success:
        return None, None

    # Generate and upload thumbnail
    thumb_path = generate_thumbnail(local_path)
    thumb_url = None

    if thumb_path:
        # Create thumbnail R2 key
        if r2_key:
            base, ext = r2_key.rsplit('.', 1) if '.' in r2_key else (r2_key, 'jpg')
            thumb_key = f"{base}_thumb.{ext}"
        else:
            thumb_key = f"receipts/{local_path.stem}_thumb.jpg"

        success, thumb_result = upload_to_r2(thumb_path, thumb_key)
        if success:
            thumb_url = thumb_result

        # Clean up local thumbnail
        try:
            thumb_path.unlink()
        except OSError:
            pass

    return full_url, thumb_url


# Quick status check
def r2_status() -> dict:
    """Return R2 configuration status"""
    return {
        "enabled": R2_ENABLED,
        "bucket": R2_BUCKET,
        "public_url": R2_PUBLIC_URL,
        "curl_path": CURL_PATH
    }


if __name__ == '__main__':
    # Test
    print("R2 Service Status:")
    status = r2_status()
    for k, v in status.items():
        print(f"  {k}: {v}")
