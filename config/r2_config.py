"""
R2 Configuration - SINGLE SOURCE OF TRUTH
==========================================

All R2 bucket configuration should come from this file.
DO NOT hardcode R2 bucket names, URLs, or credentials elsewhere.

Usage:
    from config.r2_config import R2Config

    bucket = R2Config.BUCKET_NAME
    public_url = R2Config.get_public_url("receipts/image.jpg")
    client = R2Config.get_client()
"""

import os
from pathlib import Path

# Load .env if available
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


class R2Config:
    """Centralized R2 configuration - SINGLE SOURCE OF TRUTH"""

    # SECURITY: All credentials must be set via environment variables
    # Account ID (from Cloudflare R2 dashboard)
    ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID', '')

    # Bucket name
    BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'bkreceipts')

    # Credentials - MUST be set via environment variables
    ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID', '')
    SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')

    # URLs
    ENDPOINT_URL = os.getenv('R2_ENDPOINT', f'https://{ACCOUNT_ID}.r2.cloudflarestorage.com' if ACCOUNT_ID else '')
    PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '')

    # KNOWN WRONG BUCKETS - DO NOT USE THESE
    # These are here for migration/cleanup purposes only
    WRONG_BUCKETS = {
        'second-brain-receipts': 'pub-946b7d51aa2c4a0fb92c1ba15bf5c520.r2.dev',
        'tallyups-receipts': 'pub-f0fa143240d4452e836320be0bac6138.r2.dev',
    }

    @classmethod
    def get_public_url(cls, key: str) -> str:
        """Get the public URL for an R2 object."""
        key = key.lstrip('/')
        return f"{cls.PUBLIC_URL}/{key}"

    @classmethod
    def get_client(cls):
        """Get a boto3 S3 client configured for R2."""
        try:
            import boto3
            return boto3.client(
                's3',
                endpoint_url=cls.ENDPOINT_URL,
                aws_access_key_id=cls.ACCESS_KEY_ID,
                aws_secret_access_key=cls.SECRET_ACCESS_KEY,
                region_name='auto'
            )
        except ImportError:
            raise ImportError("boto3 is required for R2 client. Install with: pip install boto3")

    @classmethod
    def validate(cls) -> dict:
        """Validate R2 configuration and return status."""
        issues = []

        if not cls.ACCESS_KEY_ID:
            issues.append("R2_ACCESS_KEY_ID not set")
        if not cls.SECRET_ACCESS_KEY:
            issues.append("R2_SECRET_ACCESS_KEY not set")
        if cls.BUCKET_NAME in cls.WRONG_BUCKETS:
            issues.append(f"Using wrong bucket: {cls.BUCKET_NAME}")
        if cls.BUCKET_NAME != 'bkreceipts':
            issues.append(f"Bucket '{cls.BUCKET_NAME}' may not be the production bucket")

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'config': {
                'bucket': cls.BUCKET_NAME,
                'account_id': cls.ACCOUNT_ID,
                'public_url': cls.PUBLIC_URL,
                'endpoint': cls.ENDPOINT_URL,
            }
        }

    @classmethod
    def fix_url(cls, url: str) -> str:
        """
        Fix a URL that might be pointing to a wrong bucket.
        Returns the corrected URL pointing to bkreceipts.
        """
        if not url:
            return url

        # Check if URL uses a wrong bucket's public URL
        for wrong_bucket, wrong_public in cls.WRONG_BUCKETS.items():
            if wrong_public in url:
                # Extract the key (path after the bucket domain)
                key = url.split(wrong_public)[-1].lstrip('/')
                return cls.get_public_url(key)

        return url


# Convenience exports
BUCKET_NAME = R2Config.BUCKET_NAME
PUBLIC_URL = R2Config.PUBLIC_URL
ENDPOINT_URL = R2Config.ENDPOINT_URL
get_public_url = R2Config.get_public_url
get_client = R2Config.get_client


if __name__ == '__main__':
    # Validate configuration when run directly
    result = R2Config.validate()
    print("R2 Configuration Validation")
    print("=" * 40)
    print(f"Valid: {result['valid']}")
    print(f"Bucket: {result['config']['bucket']}")
    print(f"Public URL: {result['config']['public_url']}")
    print(f"Endpoint: {result['config']['endpoint']}")
    if result['issues']:
        print("\nIssues:")
        for issue in result['issues']:
            print(f"  - {issue}")
