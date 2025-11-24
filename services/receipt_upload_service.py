"""
Unified Receipt Upload Service with R2 Storage

Handles all receipt uploads from any source (Gmail, drag-and-drop, mobile photos, etc.)
- Automatically converts to JPG format
- Uploads to Cloudflare R2
- Returns public R2 URL
- Updates CSV with receipt URL
"""

import os
import boto3
from botocore.config import Config
from pathlib import Path
import hashlib
from datetime import datetime
from PIL import Image
import tempfile
import subprocess
import time

# Optional: Selenium for HTML screenshot conversion
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️  Selenium not available - HTML receipt conversion disabled")

# R2 Configuration
R2_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID', '33950783df90825d4b885322a8ea2f2f')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID', '38c091312371e3c552fdf21b31096fc3')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', 'bdd5443df55080d8f173d89071c3c7397b27dde92a8cf0095ff6808b9d347bb1')
R2_BUCKET_NAME = 'second-brain-receipts'
R2_PUBLIC_URL = 'https://pub-946b7d51aa2c4a0fb92c1ba15bf5c520.r2.dev'


class ReceiptUploadService:
    """Service for handling all receipt uploads with automatic conversion and R2 storage"""

    def __init__(self):
        self.s3_client = self._setup_r2_client()
        self.temp_dir = Path(tempfile.gettempdir()) / 'receipt_uploads'
        self.temp_dir.mkdir(exist_ok=True)

    def _setup_r2_client(self):
        """Initialize R2 client using boto3"""
        endpoint_url = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'

        s3 = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version='s3v4')
        )
        return s3

    def upload_receipt(self, file_path_or_content, source='manual', metadata=None):
        """
        Main upload method - handles any receipt format and uploads to R2

        Args:
            file_path_or_content: Path to file, file content (bytes), or HTML string
            source: Source of receipt (gmail, manual, mobile, drag_drop)
            metadata: Optional dict with merchant, amount, date, etc.

        Returns:
            dict: {
                'success': True/False,
                'r2_url': 'https://pub-946b7d51aa2c4a0fb92c1ba15bf5c520.r2.dev/receipts/...',
                'filename': 'generated_filename.jpg',
                'error': 'error message if failed'
            }
        """
        try:
            # Step 1: Determine file type and prepare for conversion
            if isinstance(file_path_or_content, (str, Path)) and Path(file_path_or_content).exists():
                file_path = Path(file_path_or_content)
                file_type = self._detect_file_type(file_path)
            elif isinstance(file_path_or_content, bytes):
                # Save bytes to temp file
                temp_path = self.temp_dir / f'temp_{hashlib.md5(file_path_or_content).hexdigest()[:8]}'
                temp_path.write_bytes(file_path_or_content)
                file_path = temp_path
                file_type = self._detect_file_type(file_path)
            elif isinstance(file_path_or_content, str) and file_path_or_content.strip().startswith('<'):
                # HTML content
                file_type = 'html'
                temp_path = self.temp_dir / f'temp_{hashlib.md5(file_path_or_content.encode()).hexdigest()[:8]}.html'
                temp_path.write_text(file_path_or_content)
                file_path = temp_path
            else:
                return {'success': False, 'error': 'Invalid file input'}

            # Step 2: Convert to JPG
            jpg_path = self._convert_to_jpg(file_path, file_type, metadata)
            if not jpg_path:
                return {'success': False, 'error': 'Conversion to JPG failed'}

            # Step 3: Generate R2 filename
            r2_filename = self._generate_r2_filename(source, metadata)

            # Step 4: Upload to R2
            r2_key = f'receipts/{r2_filename}'
            upload_success = self._upload_to_r2(jpg_path, r2_key)

            if not upload_success:
                return {'success': False, 'error': 'R2 upload failed'}

            # Step 5: Generate public URL
            r2_url = f'{R2_PUBLIC_URL}/{r2_key}'

            # Clean up temp files
            if jpg_path.parent == self.temp_dir:
                jpg_path.unlink(missing_ok=True)
            if file_path.parent == self.temp_dir:
                file_path.unlink(missing_ok=True)

            return {
                'success': True,
                'r2_url': r2_url,
                'filename': r2_filename,
                'size': jpg_path.stat().st_size if jpg_path.exists() else 0
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _detect_file_type(self, file_path):
        """Detect file type from extension or content"""
        suffix = file_path.suffix.lower()

        if suffix in ['.jpg', '.jpeg']:
            return 'jpeg'
        elif suffix in ['.png']:
            return 'png'
        elif suffix in ['.pdf']:
            return 'pdf'
        elif suffix in ['.html', '.htm']:
            return 'html'
        elif suffix in ['.heic', '.heif']:
            return 'heic'
        else:
            # Try to detect from content
            try:
                with open(file_path, 'rb') as f:
                    header = f.read(16)
                    if header.startswith(b'\xff\xd8\xff'):
                        return 'jpeg'
                    elif header.startswith(b'\x89PNG'):
                        return 'png'
                    elif header.startswith(b'%PDF'):
                        return 'pdf'
            except:
                pass
            return 'unknown'

    def _convert_to_jpg(self, file_path, file_type, metadata=None):
        """Convert any file type to JPG"""
        output_path = self.temp_dir / f'{file_path.stem}.jpg'

        try:
            if file_type == 'jpeg':
                # Already JPG, just copy
                output_path.write_bytes(file_path.read_bytes())
                return output_path

            elif file_type in ['png', 'heic']:
                # Convert image to JPG using PIL
                return self._image_to_jpg(file_path, output_path)

            elif file_type == 'pdf':
                # Convert PDF to JPG using ImageMagick
                return self._pdf_to_jpg(file_path, output_path)

            elif file_type == 'html':
                # Convert HTML to JPG using Selenium screenshot
                return self._html_to_jpg(file_path, output_path)

            else:
                # Try generic image conversion
                return self._image_to_jpg(file_path, output_path)

        except Exception as e:
            print(f"Conversion error: {e}")
            return None

    def _image_to_jpg(self, image_path, output_path):
        """Convert any image format to JPG using PIL"""
        try:
            img = Image.open(image_path)

            # Convert RGBA/LA/P to RGB
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background

            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Save as JPG with high quality
            img.save(output_path, 'JPEG', quality=90, optimize=True)
            return output_path

        except Exception as e:
            print(f"Image conversion error: {e}")
            return None

    def _pdf_to_jpg(self, pdf_path, output_path):
        """Convert PDF first page to JPG using ImageMagick"""
        try:
            # Try ImageMagick 7 first (magick command)
            # Then fall back to ImageMagick 6 (convert command)
            commands = [
                # ImageMagick 7
                ['magick', 'convert', '-density', '150', f'{pdf_path}[0]', '-quality', '90',
                 '-background', 'white', '-alpha', 'remove', '-flatten', str(output_path)],
                # ImageMagick 6
                ['convert', '-density', '150', f'{pdf_path}[0]', '-quality', '90',
                 '-background', 'white', '-alpha', 'remove', '-flatten', str(output_path)],
                # Alternative: just magick (shorthand)
                ['magick', f'{pdf_path}[0]', '-density', '150', '-quality', '90',
                 '-background', 'white', '-alpha', 'remove', '-flatten', str(output_path)]
            ]

            last_error = None
            for cmd in commands:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                    if result.returncode == 0 and output_path.exists():
                        print(f"✅ PDF converted to JPG: {output_path.name} (used {cmd[0]})")
                        return output_path
                    else:
                        last_error = result.stderr
                except FileNotFoundError:
                    # Command not found, try next
                    continue

            # All commands failed
            if last_error:
                print(f"❌ PDF conversion failed: {last_error}")
            else:
                print(f"❌ PDF conversion failed: ImageMagick not found")
            return None

        except Exception as e:
            print(f"❌ PDF conversion error: {e}")
            return None

    def _html_to_jpg(self, html_path, output_path):
        """Convert HTML to JPG using Selenium screenshot"""
        if not SELENIUM_AVAILABLE:
            print("⚠️  Selenium not available - cannot convert HTML to JPG")
            return None

        driver = None
        try:
            # Setup headless Chrome
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--window-size=1200,1600')

            driver = webdriver.Chrome(options=chrome_options)

            # Load HTML
            file_url = f'file://{html_path.absolute()}'
            driver.get(file_url)
            time.sleep(2)  # Wait for page to load

            # Take screenshot as PNG first
            png_path = str(output_path).replace('.jpg', '.png')
            driver.save_screenshot(png_path)

            # Convert PNG to JPG
            self._image_to_jpg(Path(png_path), output_path)

            # Clean up PNG
            Path(png_path).unlink(missing_ok=True)

            return output_path if output_path.exists() else None

        except Exception as e:
            print(f"HTML conversion error: {e}")
            return None
        finally:
            if driver:
                driver.quit()

    def _generate_r2_filename(self, source, metadata=None):
        """Generate unique filename for R2 storage"""
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')

        # Extract merchant/description if available
        if metadata:
            merchant = metadata.get('merchant', '').replace(' ', '_')[:30]
            amount = metadata.get('amount', '')
            date = metadata.get('date', '')

            if merchant:
                base_name = f"{source}_{date or timestamp}_{merchant}_{amount}"
            else:
                base_name = f"{source}_{timestamp}"
        else:
            base_name = f"{source}_{timestamp}"

        # Add random hash for uniqueness
        hash_suffix = hashlib.md5(f"{base_name}{datetime.now()}".encode()).hexdigest()[:8]

        # Clean filename
        clean_name = "".join(c if c.isalnum() or c in ['_', '-', '.'] else '_' for c in base_name)

        return f"{clean_name}_{hash_suffix}.jpg"

    def _upload_to_r2(self, file_path, r2_key):
        """Upload file to R2 storage"""
        try:
            self.s3_client.upload_file(
                str(file_path),
                R2_BUCKET_NAME,
                r2_key,
                ExtraArgs={
                    'ContentType': 'image/jpeg',
                    'CacheControl': 'public, max-age=31536000'  # Cache for 1 year
                }
            )
            return True
        except Exception as e:
            print(f"R2 upload error: {e}")
            return False

    def upload_gmail_receipt(self, attachment_data, merchant, amount, date):
        """Upload receipt from Gmail attachment"""
        metadata = {
            'merchant': merchant,
            'amount': str(amount),
            'date': date
        }
        return self.upload_receipt(attachment_data, source='gmail', metadata=metadata)

    def upload_mobile_photo(self, photo_data, metadata=None):
        """Upload receipt photo from mobile app"""
        return self.upload_receipt(photo_data, source='mobile', metadata=metadata)

    def upload_drag_drop(self, file_data, metadata=None):
        """Upload receipt from drag-and-drop in web UI"""
        return self.upload_receipt(file_data, source='drag_drop', metadata=metadata)


# Singleton instance
_receipt_upload_service = None

def get_receipt_upload_service():
    """Get or create the receipt upload service singleton"""
    global _receipt_upload_service
    if _receipt_upload_service is None:
        _receipt_upload_service = ReceiptUploadService()
    return _receipt_upload_service
