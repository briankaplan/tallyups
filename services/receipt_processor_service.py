#!/usr/bin/env python3
"""
Receipt Processor Service
Downloads Gmail attachments, converts PDF→JPG, uploads to R2

Workflow:
1. Download attachment from Gmail
2. If PDF → convert to JPG (all pages)
3. Calculate SHA256 hash for deduplication
4. Upload to R2 storage
5. Update database with R2 URL
6. Clean up temp files
"""

import os
import tempfile
import hashlib
from pathlib import Path
from typing import Dict, Optional, List

# Optional imports - gracefully handle if not available
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    print("⚠️  pdf2image not available - PDF conversion disabled")

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️  Selenium not available - HTML screenshot disabled")

from PIL import Image
import sqlite3
from datetime import datetime
import time

from services.r2_storage_service import R2StorageService
from services.gmail_receipt_service import GmailReceiptService


class ReceiptProcessorService:
    """Process receipt attachments: download, convert, upload to R2"""

    def __init__(
        self,
        db_path: str,
        r2_service: R2StorageService = None,
        gmail_service: GmailReceiptService = None
    ):
        """
        Initialize processor

        Args:
            db_path: Path to SQLite database
            r2_service: R2 storage service instance
            gmail_service: Gmail service instance
        """
        self.db_path = db_path
        self.r2 = r2_service or R2StorageService()
        self.gmail = gmail_service or GmailReceiptService(db_path)

        # JPG quality settings
        self.JPG_QUALITY = 85
        self.JPG_MAX_WIDTH = 2000  # Max width in pixels

        # Chrome driver for HTML conversion (lazy init)
        self._driver = None

    def process_receipt_attachment(
        self,
        receipt_id: int,
        account: str,
        message_id: str,
        attachment_id: str,
        filename: str,
        user_id: str = None
    ) -> Optional[Dict]:
        """
        Download attachment, convert to JPG, upload to R2

        Args:
            receipt_id: Database receipt ID
            account: Gmail account
            message_id: Gmail message ID
            attachment_id: Gmail attachment ID
            filename: Original filename
            user_id: User ID for data isolation (multi-tenant)

        Returns:
            Dict with R2 upload result or None if failed
        """
        temp_dir = None

        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()

            print(f"📥 Downloading attachment: {filename}")

            # Download attachment
            attachment_data = self.gmail.download_attachment(
                account=account,
                message_id=message_id,
                attachment_id=attachment_id,
                filename=filename
            )

            if not attachment_data:
                print(f"❌ Failed to download attachment")
                return None

            # Save to temp file
            temp_file = Path(temp_dir) / filename
            with open(temp_file, 'wb') as f:
                f.write(attachment_data)

            # Check file type
            is_pdf = filename.lower().endswith('.pdf')
            is_html = filename.lower().endswith(('.html', '.htm'))

            if is_html:
                print(f"📄 Converting HTML to JPG...")
                jpg_file = self._convert_html_to_jpg(temp_file, temp_dir)

                if not jpg_file:
                    print(f"❌ Failed to convert HTML")
                    return None

                result = self._upload_to_r2(jpg_file, receipt_id, user_id)

                if result:
                    result['total_pages'] = 1
                    # Update database
                    self._update_receipt_r2_data(receipt_id, result)

                return result

            elif is_pdf:
                print(f"📄 Converting PDF to JPG...")
                jpg_files = self._convert_pdf_to_jpg(temp_file, temp_dir)

                if not jpg_files:
                    print(f"❌ Failed to convert PDF")
                    return None

                # Process all pages
                upload_results = []
                for jpg_file in jpg_files:
                    result = self._upload_to_r2(jpg_file, receipt_id, user_id)
                    if result:
                        upload_results.append(result)

                # Use first page as primary image
                if upload_results:
                    primary_result = upload_results[0]
                    primary_result['total_pages'] = len(upload_results)
                    primary_result['all_pages'] = upload_results

                    # Update database
                    self._update_receipt_r2_data(receipt_id, primary_result)

                    return primary_result

            else:
                # Image file - upload directly after resizing
                print(f"🖼️  Processing image...")
                jpg_file = self._convert_image_to_jpg(temp_file, temp_dir)

                if not jpg_file:
                    print(f"❌ Failed to process image")
                    return None

                result = self._upload_to_r2(jpg_file, receipt_id, user_id)

                if result:
                    result['total_pages'] = 1
                    # Update database
                    self._update_receipt_r2_data(receipt_id, result)

                return result

        except Exception as e:
            print(f"❌ Error processing receipt: {e}")
            return None

        finally:
            # Clean up temp directory
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)

    def _convert_pdf_to_jpg(self, pdf_path: Path, output_dir: str) -> List[Path]:
        """
        Convert PDF to JPG images (one per page)

        Args:
            pdf_path: Path to PDF file
            output_dir: Directory to save JPG files

        Returns:
            List of JPG file paths
        """
        try:
            if not PDF2IMAGE_AVAILABLE:
                raise Exception("pdf2image not available - cannot convert PDF to JPG")

            # Convert PDF to images
            images = convert_from_path(
                str(pdf_path),
                dpi=150,  # 150 DPI is good balance between quality and file size
                fmt='jpeg'
            )

            jpg_files = []

            for i, image in enumerate(images, 1):
                # Resize if too large
                if image.width > self.JPG_MAX_WIDTH:
                    ratio = self.JPG_MAX_WIDTH / image.width
                    new_height = int(image.height * ratio)
                    image = image.resize((self.JPG_MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

                # Save as JPG
                jpg_path = Path(output_dir) / f"{pdf_path.stem}_page_{i}.jpg"
                image.save(jpg_path, 'JPEG', quality=self.JPG_QUALITY, optimize=True)

                jpg_files.append(jpg_path)

            return jpg_files

        except Exception as e:
            print(f"Error converting PDF: {e}")
            return []

    def _setup_chrome_driver(self):
        """Set up headless Chrome for HTML screenshots (lazy init)"""
        if not SELENIUM_AVAILABLE:
            print("⚠️  Selenium not available - cannot setup browser driver")
            return None

        if self._driver:
            return self._driver

        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1200,1600')
        options.add_argument('--disable-gpu')

        try:
            self._driver = webdriver.Chrome(options=options)
            return self._driver
        except Exception as e:
            print(f"⚠️  Chrome driver error: {e}")
            # Try Safari as fallback
            try:
                self._driver = webdriver.Safari()
                return self._driver
            except Exception as e2:
                print(f"❌ Could not start browser: {e2}")
                return None

    def _convert_html_to_jpg(self, html_path: Path, output_dir: str) -> Optional[Path]:
        """
        Convert HTML file to JPG screenshot

        Args:
            html_path: Path to HTML file
            output_dir: Directory to save JPG

        Returns:
            JPG file path or None if failed
        """
        try:
            # Get or create Chrome driver
            driver = self._setup_chrome_driver()
            if not driver:
                print("❌ No browser driver available")
                return None

            # Load the HTML file
            file_url = f'file://{html_path.absolute()}'
            driver.get(file_url)

            # Wait for page to load
            time.sleep(2)

            # Take screenshot as PNG first
            png_path = Path(output_dir) / f"{html_path.stem}.png"
            driver.save_screenshot(str(png_path))

            # Convert PNG to JPG
            img = Image.open(png_path)

            # Convert RGBA to RGB
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            # Resize if too large
            if img.width > self.JPG_MAX_WIDTH:
                ratio = self.JPG_MAX_WIDTH / img.width
                new_height = int(img.height * ratio)
                img = img.resize((self.JPG_MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

            # Save as JPG
            jpg_path = Path(output_dir) / f"{html_path.stem}.jpg"
            img.save(jpg_path, 'JPEG', quality=self.JPG_QUALITY, optimize=True)

            # Clean up PNG
            if png_path.exists():
                os.remove(png_path)

            return jpg_path

        except Exception as e:
            print(f"Error converting HTML: {e}")
            return None

    def _convert_image_to_jpg(self, image_path: Path, output_dir: str) -> Optional[Path]:
        """
        Convert image to optimized JPG

        Args:
            image_path: Path to image file
            output_dir: Directory to save JPG

        Returns:
            JPG file path or None if failed
        """
        try:
            # Open image
            image = Image.open(image_path)

            # Convert to RGB if necessary (for PNG with transparency, etc)
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Resize if too large
            if image.width > self.JPG_MAX_WIDTH:
                ratio = self.JPG_MAX_WIDTH / image.width
                new_height = int(image.height * ratio)
                image = image.resize((self.JPG_MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

            # Save as JPG
            jpg_path = Path(output_dir) / f"{image_path.stem}.jpg"
            image.save(jpg_path, 'JPEG', quality=self.JPG_QUALITY, optimize=True)

            return jpg_path

        except Exception as e:
            print(f"Error converting image: {e}")
            return None

    def _upload_to_r2(self, file_path: Path, receipt_id: int, user_id: str = None) -> Optional[Dict]:
        """
        Upload file to R2 storage with user isolation

        Args:
            file_path: Path to file to upload
            receipt_id: Receipt ID for metadata
            user_id: User ID for data isolation (multi-tenant)

        Returns:
            Upload result dict or None if failed
        """
        try:
            print(f"☁️  Uploading to R2: {file_path.name} (user: {user_id or 'legacy'})")

            # Upload to R2 with user scoping
            result = self.r2.upload_file(
                file_path=str(file_path),
                metadata={
                    'receipt_id': str(receipt_id),
                    'original_filename': file_path.name,
                    'user_id': user_id or ''
                },
                user_id=user_id  # Enable user-scoped storage path
            )

            print(f"✅ Uploaded: {result['r2_key']}")

            return result

        except Exception as e:
            print(f"Error uploading to R2: {e}")
            return None

    def _update_receipt_r2_data(self, receipt_id: int, upload_result: Dict):
        """
        Update receipt record with R2 data

        Args:
            receipt_id: Receipt ID
            upload_result: R2 upload result
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        try:
            # Determine URL to use (public domain if available, otherwise R2 URL)
            url = upload_result.get('cloudflare_url') or upload_result.get('r2_url')

            cur.execute("""
                UPDATE receipts
                SET r2_url = ?,
                    r2_key = ?,
                    file_hash = ?,
                    file_size = ?,
                    total_pages = ?,
                    processing_status = 'processed',
                    processed_at = ?
                WHERE id = ?
            """, (
                url,
                upload_result['r2_key'],
                upload_result['file_hash'],
                upload_result.get('file_size', 0),
                upload_result.get('total_pages', 1),
                datetime.now().isoformat(),
                receipt_id
            ))

            conn.commit()
            print(f"✅ Updated receipt #{receipt_id} with R2 data")

        except Exception as e:
            print(f"Error updating receipt: {e}")

        finally:
            conn.close()

    def process_all_pending_receipts(self, limit: int = None) -> Dict:
        """
        Process all receipts that have Gmail attachments but no R2 URL

        Args:
            limit: Maximum number of receipts to process

        Returns:
            Dict with processing statistics
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Get receipts with attachments but no R2 URL
        query = """
            SELECT id, gmail_account, gmail_message_id, email_subject
            FROM receipts
            WHERE gmail_message_id IS NOT NULL
            AND r2_url IS NULL
            AND processing_status = 'pending'
        """

        if limit:
            query += f" LIMIT {limit}"

        cur.execute(query)
        receipts = cur.fetchall()

        print(f"\n📊 Found {len(receipts)} receipts to process")

        stats = {
            'total': len(receipts),
            'processed': 0,
            'failed': 0,
            'no_attachments': 0
        }

        for i, receipt in enumerate(receipts, 1):
            print(f"\n[{i}/{len(receipts)}] Processing receipt #{receipt['id']}")
            print(f"  Subject: {receipt['email_subject']}")

            # Get message details to find attachments
            # This is a simplified version - in reality we'd need to store attachment IDs
            # For now, we'll skip this and assume attachments were stored separately

            # TODO: Store attachment metadata when fetching emails
            # For now, mark as no attachments
            stats['no_attachments'] += 1

        conn.close()

        return stats

    def upload_local_receipt(
        self,
        file_path: str,
        merchant: str = None,
        amount: float = None,
        date: str = None,
        business_type: str = None,
        source: str = 'manual_upload',
        user_id: str = None
    ) -> Optional[int]:
        """
        Upload a local receipt file to R2 and create database record

        Args:
            file_path: Path to local receipt file
            merchant: Merchant name (optional)
            amount: Transaction amount (optional)
            date: Transaction date (optional)
            business_type: Business type (optional)
            source: Receipt source (default: manual_upload)
            user_id: User ID for data isolation (multi-tenant)

        Returns:
            Receipt ID if successful, None if failed
        """
        temp_dir = None

        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()

            file_path = Path(file_path)

            if not file_path.exists():
                print(f"❌ File not found: {file_path}")
                return None

            # Check file type
            is_pdf = file_path.suffix.lower() == '.pdf'
            is_html = file_path.suffix.lower() in ('.html', '.htm')

            if is_html:
                print(f"📄 Converting HTML to JPG...")
                jpg_file = self._convert_html_to_jpg(file_path, temp_dir)

                if not jpg_file:
                    print(f"❌ Failed to convert HTML")
                    return None

                primary_result = self.r2.upload_file(
                    file_path=str(jpg_file),
                    metadata={
                        'merchant': merchant or '',
                        'source': source,
                        'user_id': user_id or ''
                    },
                    user_id=user_id
                )

                if not primary_result:
                    return None

                primary_result['total_pages'] = 1

            elif is_pdf:
                print(f"📄 Converting PDF to JPG...")
                jpg_files = self._convert_pdf_to_jpg(file_path, temp_dir)

                if not jpg_files:
                    print(f"❌ Failed to convert PDF")
                    return None

                # Upload all pages
                upload_results = []
                for jpg_file in jpg_files:
                    result = self.r2.upload_file(
                        file_path=str(jpg_file),
                        metadata={
                            'merchant': merchant or '',
                            'source': source,
                            'user_id': user_id or ''
                        },
                        user_id=user_id
                    )
                    if result:
                        upload_results.append(result)

                if not upload_results:
                    return None

                primary_result = upload_results[0]
                primary_result['total_pages'] = len(upload_results)

            else:
                # Image file
                print(f"🖼️  Processing image...")
                jpg_file = self._convert_image_to_jpg(file_path, temp_dir)

                if not jpg_file:
                    # If conversion failed, upload original
                    jpg_file = file_path

                primary_result = self.r2.upload_file(
                    file_path=str(jpg_file),
                    metadata={
                        'merchant': merchant or '',
                        'source': source,
                        'user_id': user_id or ''
                    },
                    user_id=user_id
                )

                if not primary_result:
                    return None

                primary_result['total_pages'] = 1

            # Create database record
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()

            url = primary_result.get('cloudflare_url') or primary_result.get('r2_url')

            cur.execute("""
                INSERT INTO receipts (
                    source,
                    merchant,
                    amount,
                    transaction_date,
                    business_type,
                    r2_url,
                    r2_key,
                    file_hash,
                    file_size,
                    total_pages,
                    processing_status,
                    created_at,
                    processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source,
                merchant,
                amount,
                date,
                business_type,
                url,
                primary_result['r2_key'],
                primary_result['file_hash'],
                primary_result.get('file_size', 0),
                primary_result.get('total_pages', 1),
                'processed',
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ))

            receipt_id = cur.lastrowid
            conn.commit()
            conn.close()

            print(f"✅ Created receipt #{receipt_id}")

            return receipt_id

        except Exception as e:
            print(f"❌ Error uploading receipt: {e}")
            return None

        finally:
            # Clean up temp directory
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)


    def close(self):
        """Clean up resources (close Chrome driver)"""
        if self._driver:
            try:
                self._driver.quit()
            except:
                pass
            self._driver = None


if __name__ == '__main__':
    import sys

    print("=" * 80)
    print("RECEIPT PROCESSOR SERVICE")
    print("=" * 80)

    db_path = sys.argv[1] if len(sys.argv) > 1 else 'master.db'

    processor = ReceiptProcessorService(db_path)

    print("\n" + "=" * 80)
    print("What would you like to do?")
    print("1. Upload a local receipt file")
    print("2. Process pending Gmail receipts (with attachments)")
    print("=" * 80)

    choice = input("\nEnter choice (1 or 2): ").strip()

    if choice == '1':
        file_path = input("\nEnter file path: ").strip()
        merchant = input("Merchant name (optional): ").strip() or None
        amount = input("Amount (optional): ").strip()
        amount = float(amount) if amount else None
        date = input("Date YYYY-MM-DD (optional): ").strip() or None
        business_type = input("Business type (Personal/Business/Secondary): ").strip() or None

        receipt_id = processor.upload_local_receipt(
            file_path=file_path,
            merchant=merchant,
            amount=amount,
            date=date,
            business_type=business_type
        )

        if receipt_id:
            print(f"\n✅ Successfully uploaded receipt #{receipt_id}")
        else:
            print(f"\n❌ Failed to upload receipt")

        # Clean up
        processor.close()

    elif choice == '2':
        limit = input("\nHow many receipts to process? (blank for all): ").strip()
        limit = int(limit) if limit else None

        print("\n🔄 Processing receipts...")
        results = processor.process_all_pending_receipts(limit=limit)

        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80)
        print(f"Total: {results['total']}")
        print(f"Processed: {results['processed']}")
        print(f"Failed: {results['failed']}")
        print(f"No attachments: {results['no_attachments']}")

        # Clean up
        processor.close()
