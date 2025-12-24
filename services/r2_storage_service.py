#!/usr/bin/env python3
"""
Cloudflare R2 Storage Service

Complete R2 storage service for receipt files using S3-compatible API
- Upload receipts to R2 bucket
- Download/serve receipts by path
- List receipts with filtering
- Delete receipts
- Generate public URLs
- Handle deduplication via file hashing

Requirements: boto3, python-dotenv
"""

import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pathlib import Path
import hashlib
from datetime import datetime
from typing import Dict, Optional, List
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# R2 Configuration from environment variables
# SECURITY: Credentials must be set via environment variables, never hardcoded
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID', '')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID', '')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'bkreceipts')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '')
R2_CUSTOM_DOMAIN = os.getenv('R2_CUSTOM_DOMAIN', '')  # Optional custom domain


class R2StorageService:
    """
    Cloudflare R2 Storage Service

    Handles all R2 storage operations for receipt files
    """

    def __init__(
        self,
        account_id: str = None,
        access_key_id: str = None,
        secret_access_key: str = None,
        bucket_name: str = None,
        public_url: str = None
    ):
        """
        Initialize R2 storage service

        Args:
            account_id: Cloudflare account ID (defaults to env var)
            access_key_id: R2 access key ID (defaults to env var)
            secret_access_key: R2 secret access key (defaults to env var)
            bucket_name: R2 bucket name (defaults to env var)
            public_url: Public URL for R2 bucket (defaults to env var)
        """
        self.account_id = account_id or R2_ACCOUNT_ID
        self.access_key_id = access_key_id or R2_ACCESS_KEY_ID
        self.secret_access_key = secret_access_key or R2_SECRET_ACCESS_KEY
        self.bucket_name = bucket_name or R2_BUCKET_NAME
        self.public_url = public_url or R2_PUBLIC_URL
        self.custom_domain = R2_CUSTOM_DOMAIN

        # Initialize S3 client for R2
        self.s3_client = self._setup_r2_client()

    def _setup_r2_client(self):
        """
        Initialize boto3 S3 client configured for Cloudflare R2

        Returns:
            boto3.client: Configured S3 client for R2
        """
        endpoint_url = f'https://{self.account_id}.r2.cloudflarestorage.com'

        try:
            s3 = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(signature_version='s3v4'),
                region_name='auto'  # R2 uses 'auto' for region
            )
            return s3
        except Exception as e:
            print(f"❌ Failed to initialize R2 client: {e}")
            raise

    def calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA256 hash of file for deduplication

        Args:
            file_path: Path to file

        Returns:
            str: SHA256 hash of file
        """
        sha256_hash = hashlib.sha256()

        with open(file_path, 'rb') as f:
            # Read file in chunks for memory efficiency
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()

    def upload_file(
        self,
        file_path: str,
        r2_key: str = None,
        metadata: Dict = None,
        public: bool = True
    ) -> Optional[Dict]:
        """
        Upload file to R2 storage

        Args:
            file_path: Path to local file to upload
            r2_key: R2 key/path (if None, auto-generated from filename)
            metadata: Optional metadata dict to store with file
            public: Whether file should be publicly accessible

        Returns:
            Dict with upload result:
            {
                'success': True,
                'r2_key': 'receipts/2025-01-01_merchant_12ab34cd.jpg',
                'r2_url': 'https://account.r2.cloudflarestorage.com/bucket/...',
                'public_url': 'https://pub-....r2.dev/receipts/...',
                'cloudflare_url': 'https://custom-domain.com/receipts/...' (if custom domain),
                'file_hash': 'sha256hash...',
                'file_size': 12345,
                'uploaded_at': '2025-01-01T12:00:00'
            }
        """
        try:
            file_path = Path(file_path)

            if not file_path.exists():
                return {
                    'success': False,
                    'error': f'File not found: {file_path}'
                }

            # Generate R2 key if not provided
            if not r2_key:
                timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
                file_hash_short = hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]
                r2_key = f"receipts/{timestamp}_{file_path.stem}_{file_hash_short}{file_path.suffix}"

            # Calculate file hash for deduplication
            file_hash = self.calculate_file_hash(str(file_path))
            file_size = file_path.stat().st_size

            # Prepare metadata
            upload_metadata = {
                'uploaded_at': datetime.now().isoformat(),
                'original_filename': file_path.name,
                'file_hash': file_hash,
                'file_size': str(file_size)
            }

            if metadata:
                upload_metadata.update({
                    k: str(v) for k, v in metadata.items()
                })

            # Determine content type
            content_type = self._get_content_type(file_path.suffix)

            # Prepare upload arguments
            extra_args = {
                'ContentType': content_type,
                'Metadata': upload_metadata
            }

            # Set cache control for public files
            if public:
                extra_args['CacheControl'] = 'public, max-age=31536000'  # 1 year

            # Upload to R2
            print(f"☁️  Uploading to R2: {r2_key}")

            self.s3_client.upload_file(
                str(file_path),
                self.bucket_name,
                r2_key,
                ExtraArgs=extra_args
            )

            # Generate URLs
            r2_url = f"https://{self.account_id}.r2.cloudflarestorage.com/{self.bucket_name}/{r2_key}"
            public_url = f"{self.public_url}/{r2_key}"
            cloudflare_url = f"{self.custom_domain}/{r2_key}" if self.custom_domain else public_url

            result = {
                'success': True,
                'r2_key': r2_key,
                'r2_url': r2_url,
                'public_url': public_url,
                'cloudflare_url': cloudflare_url,
                'file_hash': file_hash,
                'file_size': file_size,
                'uploaded_at': datetime.now().isoformat()
            }

            print(f"✅ Upload successful: {public_url}")

            return result

        except ClientError as e:
            error_msg = f"R2 upload error: {e}"
            print(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Upload error: {e}"
            print(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }

    def download_file(
        self,
        r2_key: str,
        local_path: str = None
    ) -> Optional[bytes]:
        """
        Download file from R2 storage

        Args:
            r2_key: R2 key/path to download
            local_path: Optional local path to save file (if None, returns bytes)

        Returns:
            bytes if local_path is None, True if saved to local_path, None if error
        """
        try:
            print(f"📥 Downloading from R2: {r2_key}")

            if local_path:
                # Download to file
                self.s3_client.download_file(
                    self.bucket_name,
                    r2_key,
                    local_path
                )
                print(f"✅ Downloaded to: {local_path}")
                return True
            else:
                # Download to memory
                response = self.s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=r2_key
                )
                data = response['Body'].read()
                print(f"✅ Downloaded {len(data)} bytes")
                return data

        except ClientError as e:
            print(f"❌ R2 download error: {e}")
            return None
        except Exception as e:
            print(f"❌ Download error: {e}")
            return None

    def delete_file(self, r2_key: str) -> bool:
        """
        Delete file from R2 storage

        Args:
            r2_key: R2 key/path to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"🗑️  Deleting from R2: {r2_key}")

            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=r2_key
            )

            print(f"✅ Deleted: {r2_key}")
            return True

        except ClientError as e:
            print(f"❌ R2 delete error: {e}")
            return False
        except Exception as e:
            print(f"❌ Delete error: {e}")
            return False

    def list_files(
        self,
        prefix: str = '',
        max_files: int = 1000
    ) -> List[Dict]:
        """
        List files in R2 storage

        Args:
            prefix: Prefix filter (e.g., 'receipts/2025-01')
            max_files: Maximum number of files to return

        Returns:
            List of file info dicts:
            [{
                'r2_key': 'receipts/file.jpg',
                'size': 12345,
                'last_modified': '2025-01-01T12:00:00',
                'public_url': 'https://...'
            }]
        """
        try:
            print(f"📋 Listing R2 files with prefix: {prefix}")

            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_files
            )

            files = []

            if 'Contents' in response:
                for obj in response['Contents']:
                    r2_key = obj['Key']
                    public_url = f"{self.public_url}/{r2_key}"
                    cloudflare_url = f"{self.custom_domain}/{r2_key}" if self.custom_domain else public_url

                    files.append({
                        'r2_key': r2_key,
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat(),
                        'public_url': public_url,
                        'cloudflare_url': cloudflare_url
                    })

            print(f"✅ Found {len(files)} files")
            return files

        except ClientError as e:
            print(f"❌ R2 list error: {e}")
            return []
        except Exception as e:
            print(f"❌ List error: {e}")
            return []

    def get_file_metadata(self, r2_key: str) -> Optional[Dict]:
        """
        Get metadata for a file in R2

        Args:
            r2_key: R2 key/path

        Returns:
            Dict with file metadata or None if error
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=r2_key
            )

            return {
                'r2_key': r2_key,
                'size': response['ContentLength'],
                'content_type': response.get('ContentType'),
                'last_modified': response['LastModified'].isoformat(),
                'metadata': response.get('Metadata', {}),
                'public_url': f"{self.public_url}/{r2_key}",
                'cloudflare_url': f"{self.custom_domain}/{r2_key}" if self.custom_domain else f"{self.public_url}/{r2_key}"
            }

        except ClientError as e:
            print(f"❌ R2 metadata error: {e}")
            return None
        except Exception as e:
            print(f"❌ Metadata error: {e}")
            return None

    def file_exists(self, r2_key: str) -> bool:
        """
        Check if file exists in R2

        Args:
            r2_key: R2 key/path to check

        Returns:
            bool: True if exists, False otherwise
        """
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=r2_key
            )
            return True
        except ClientError:
            return False
        except Exception:
            return False

    def get_public_url(self, r2_key: str, use_custom_domain: bool = True) -> str:
        """
        Get public URL for a file

        Args:
            r2_key: R2 key/path
            use_custom_domain: Whether to use custom domain (if available)

        Returns:
            str: Public URL
        """
        if use_custom_domain and self.custom_domain:
            return f"{self.custom_domain}/{r2_key}"
        return f"{self.public_url}/{r2_key}"

    def _get_content_type(self, file_extension: str) -> str:
        """
        Get content type from file extension

        Args:
            file_extension: File extension (e.g., '.jpg', '.pdf')

        Returns:
            str: Content type
        """
        content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.pdf': 'application/pdf',
            '.html': 'text/html',
            '.htm': 'text/html',
            '.txt': 'text/plain',
            '.json': 'application/json'
        }

        return content_types.get(file_extension.lower(), 'application/octet-stream')


# Singleton instance
_r2_storage_service = None

def get_r2_storage_service() -> R2StorageService:
    """
    Get or create the R2 storage service singleton

    Returns:
        R2StorageService: Singleton instance
    """
    global _r2_storage_service
    if _r2_storage_service is None:
        _r2_storage_service = R2StorageService()
    return _r2_storage_service


if __name__ == '__main__':
    """
    Test R2 storage service
    """
    print("=" * 80)
    print("R2 STORAGE SERVICE TEST")
    print("=" * 80)

    # Initialize service
    r2 = R2StorageService()

    print("\n✅ R2 Storage Service initialized")
    print(f"   Account ID: {r2.account_id}")
    print(f"   Bucket: {r2.bucket_name}")
    print(f"   Public URL: {r2.public_url}")

    # Test listing files
    print("\n📋 Listing recent receipts...")
    files = r2.list_files(prefix='receipts/', max_files=5)

    if files:
        print(f"\n✅ Found {len(files)} files:")
        for f in files:
            print(f"   - {f['r2_key']} ({f['size']} bytes)")
            print(f"     URL: {f['public_url']}")
    else:
        print("\n⚠️  No files found or error listing files")

    print("\n" + "=" * 80)
    print("R2 Storage Service is ready to use!")
    print("=" * 80)
