#!/usr/bin/env python3
"""
R2 Upload Service
Handles automatic upload of receipts to Cloudflare R2 storage
"""

import os
import subprocess
import mimetypes
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# R2 Configuration from .env
R2_ENDPOINT = os.getenv('R2_ENDPOINT', 'https://33950783df90825d4b885322a8ea2f2f.r2.cloudflarestorage.com')
R2_BUCKET = os.getenv('R2_BUCKET_NAME', 'bkreceipts')
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY_ID', '')
R2_SECRET_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev')

# Use Homebrew curl for OpenSSL support (required on macOS)
CURL_PATH = '/opt/homebrew/opt/curl/bin/curl'
if not os.path.exists(CURL_PATH):
    CURL_PATH = 'curl'

# Check if R2 is configured
R2_ENABLED = bool(R2_ACCESS_KEY and R2_SECRET_KEY)

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

        if http_code == '200':
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
