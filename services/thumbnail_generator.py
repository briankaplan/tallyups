"""
Thumbnail Generator Service
===========================
High-performance thumbnail generation for the Receipt Library.

Features:
- Multiple sizes (small, medium, large)
- WebP output for optimal compression
- PDF first-page extraction
- Parallel batch processing
- R2 storage integration
- Caching with lazy generation
"""

import io
import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

# Image processing
try:
    from PIL import Image, ImageOps, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# PDF processing
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

logger = logging.getLogger(__name__)


class ThumbnailSize(Enum):
    """Standard thumbnail sizes."""
    SMALL = (150, 150)    # Grid view
    MEDIUM = (300, 300)   # List view
    LARGE = (600, 600)    # Preview
    XLARGE = (1200, 1200) # High-res preview


@dataclass
class ThumbnailResult:
    """Result of thumbnail generation."""
    success: bool
    size: ThumbnailSize
    width: int
    height: int
    format: str
    file_size: int
    storage_key: Optional[str] = None
    data: Optional[bytes] = None
    error: Optional[str] = None


@dataclass
class ThumbnailSet:
    """Set of thumbnails for a receipt."""
    receipt_uuid: str
    small: Optional[ThumbnailResult] = None
    medium: Optional[ThumbnailResult] = None
    large: Optional[ThumbnailResult] = None
    xlarge: Optional[ThumbnailResult] = None


class ThumbnailGenerator:
    """
    High-performance thumbnail generator.

    Generates optimized WebP thumbnails at multiple sizes
    for fast loading in the Receipt Library UI.
    """

    # Quality settings by size
    QUALITY_SETTINGS = {
        ThumbnailSize.SMALL: 75,
        ThumbnailSize.MEDIUM: 80,
        ThumbnailSize.LARGE: 85,
        ThumbnailSize.XLARGE: 90,
    }

    # Max workers for parallel processing
    MAX_WORKERS = 4

    def __init__(self, r2_service=None, cache_dir: Optional[Path] = None):
        """
        Initialize thumbnail generator.

        Args:
            r2_service: Optional R2Service for cloud storage
            cache_dir: Optional local cache directory
        """
        if not HAS_PIL:
            raise ImportError("PIL/Pillow is required for thumbnail generation")

        self.r2_service = r2_service
        self.cache_dir = cache_dir or Path("/tmp/receipt_thumbnails")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"ThumbnailGenerator initialized (cache: {self.cache_dir})")

    def generate_thumbnail(
        self,
        image_data: bytes,
        size: ThumbnailSize = ThumbnailSize.MEDIUM,
        format: str = "webp"
    ) -> ThumbnailResult:
        """
        Generate a single thumbnail from image data.

        Args:
            image_data: Raw image bytes
            size: Target thumbnail size
            format: Output format (webp, jpeg, png)

        Returns:
            ThumbnailResult with thumbnail data
        """
        try:
            # Load image
            img = Image.open(io.BytesIO(image_data))

            # Convert to RGB if necessary (for WebP/JPEG)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background for transparent images
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Auto-orient based on EXIF
            img = ImageOps.exif_transpose(img)

            # Calculate thumbnail dimensions preserving aspect ratio
            target_w, target_h = size.value
            orig_w, orig_h = img.size

            # Scale to fit within bounds
            ratio = min(target_w / orig_w, target_h / orig_h)
            new_w = int(orig_w * ratio)
            new_h = int(orig_h * ratio)

            # High-quality resize
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Optional: slight sharpening for small thumbnails
            if size == ThumbnailSize.SMALL:
                img = img.filter(ImageFilter.UnsharpMask(radius=0.5, percent=50))

            # Save to bytes
            output = io.BytesIO()
            quality = self.QUALITY_SETTINGS.get(size, 80)

            if format.lower() == 'webp':
                img.save(output, 'WEBP', quality=quality, method=4)
            elif format.lower() == 'jpeg':
                img.save(output, 'JPEG', quality=quality, optimize=True)
            else:
                img.save(output, format.upper())

            thumb_data = output.getvalue()

            return ThumbnailResult(
                success=True,
                size=size,
                width=new_w,
                height=new_h,
                format=format,
                file_size=len(thumb_data),
                data=thumb_data
            )

        except Exception as e:
            logger.error(f"Thumbnail generation failed: {e}")
            return ThumbnailResult(
                success=False,
                size=size,
                width=0,
                height=0,
                format=format,
                file_size=0,
                error=str(e)
            )

    def generate_from_pdf(
        self,
        pdf_data: bytes,
        size: ThumbnailSize = ThumbnailSize.MEDIUM,
        page: int = 0,
        dpi: int = 150
    ) -> ThumbnailResult:
        """
        Generate thumbnail from PDF first page.

        Args:
            pdf_data: Raw PDF bytes
            size: Target thumbnail size
            page: Page number (0-indexed)
            dpi: Render resolution

        Returns:
            ThumbnailResult with thumbnail data
        """
        if not HAS_PYMUPDF:
            return ThumbnailResult(
                success=False,
                size=size,
                width=0,
                height=0,
                format="webp",
                file_size=0,
                error="PyMuPDF not installed"
            )

        try:
            # Open PDF
            doc = fitz.open(stream=pdf_data, filetype="pdf")

            if page >= len(doc):
                page = 0

            # Render page to image
            pdf_page = doc[page]

            # Calculate zoom factor for target DPI
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)

            # Render to pixmap
            pix = pdf_page.get_pixmap(matrix=mat, alpha=False)

            # Convert to PIL Image
            img_data = pix.tobytes("png")
            doc.close()

            # Generate thumbnail from rendered image
            return self.generate_thumbnail(img_data, size)

        except Exception as e:
            logger.error(f"PDF thumbnail generation failed: {e}")
            return ThumbnailResult(
                success=False,
                size=size,
                width=0,
                height=0,
                format="webp",
                file_size=0,
                error=str(e)
            )

    def generate_all_sizes(
        self,
        image_data: bytes,
        is_pdf: bool = False,
        sizes: Optional[List[ThumbnailSize]] = None
    ) -> Dict[ThumbnailSize, ThumbnailResult]:
        """
        Generate thumbnails at all standard sizes.

        Args:
            image_data: Raw image/PDF bytes
            is_pdf: Whether the data is a PDF
            sizes: Optional list of sizes to generate

        Returns:
            Dict mapping size to ThumbnailResult
        """
        if sizes is None:
            sizes = [ThumbnailSize.SMALL, ThumbnailSize.MEDIUM, ThumbnailSize.LARGE]

        results = {}

        # For PDFs, render once at high resolution then scale
        if is_pdf:
            # Generate large size first
            large_result = self.generate_from_pdf(
                image_data,
                ThumbnailSize.XLARGE,
                dpi=200
            )

            if not large_result.success or not large_result.data:
                # Return error for all sizes
                for size in sizes:
                    results[size] = ThumbnailResult(
                        success=False,
                        size=size,
                        width=0,
                        height=0,
                        format="webp",
                        file_size=0,
                        error=large_result.error or "PDF rendering failed"
                    )
                return results

            # Scale down from large
            image_data = large_result.data

        # Generate each size
        for size in sizes:
            results[size] = self.generate_thumbnail(image_data, size)

        return results

    def generate_and_store(
        self,
        receipt_uuid: str,
        image_data: bytes,
        is_pdf: bool = False,
        sizes: Optional[List[ThumbnailSize]] = None
    ) -> ThumbnailSet:
        """
        Generate thumbnails and store in R2.

        Args:
            receipt_uuid: Receipt UUID for storage path
            image_data: Raw image/PDF bytes
            is_pdf: Whether the data is a PDF
            sizes: Optional list of sizes to generate

        Returns:
            ThumbnailSet with storage keys
        """
        results = self.generate_all_sizes(image_data, is_pdf, sizes)

        thumb_set = ThumbnailSet(receipt_uuid=receipt_uuid)

        for size, result in results.items():
            if result.success and result.data:
                # Build storage key
                size_name = size.name.lower()
                storage_key = f"thumbnails/{receipt_uuid}/{size_name}.webp"

                # Store in R2 if available
                if self.r2_service:
                    try:
                        self.r2_service.upload_bytes(
                            result.data,
                            storage_key,
                            content_type="image/webp"
                        )
                        result.storage_key = storage_key
                        result.data = None  # Clear data after upload
                    except Exception as e:
                        logger.error(f"Failed to upload thumbnail to R2: {e}")

                # Also cache locally
                cache_path = self.cache_dir / receipt_uuid
                cache_path.mkdir(parents=True, exist_ok=True)
                thumb_path = cache_path / f"{size_name}.webp"

                if result.data:
                    thumb_path.write_bytes(result.data)
                    result.storage_key = str(thumb_path)

            # Set on thumbnail set
            if size == ThumbnailSize.SMALL:
                thumb_set.small = result
            elif size == ThumbnailSize.MEDIUM:
                thumb_set.medium = result
            elif size == ThumbnailSize.LARGE:
                thumb_set.large = result
            elif size == ThumbnailSize.XLARGE:
                thumb_set.xlarge = result

        return thumb_set

    def get_cached_thumbnail(
        self,
        receipt_uuid: str,
        size: ThumbnailSize = ThumbnailSize.MEDIUM
    ) -> Optional[bytes]:
        """
        Get thumbnail from local cache.

        Args:
            receipt_uuid: Receipt UUID
            size: Thumbnail size

        Returns:
            Thumbnail bytes or None if not cached
        """
        size_name = size.name.lower()
        cache_path = self.cache_dir / receipt_uuid / f"{size_name}.webp"

        if cache_path.exists():
            return cache_path.read_bytes()

        return None

    def batch_generate(
        self,
        receipts: List[Dict[str, Any]],
        size: ThumbnailSize = ThumbnailSize.MEDIUM
    ) -> Dict[str, ThumbnailResult]:
        """
        Generate thumbnails for multiple receipts in parallel.

        Args:
            receipts: List of dicts with 'uuid' and 'image_data' or 'storage_key'
            size: Target size

        Returns:
            Dict mapping UUID to ThumbnailResult
        """
        results = {}

        def process_receipt(receipt: Dict) -> Tuple[str, ThumbnailResult]:
            uuid = receipt['uuid']

            # Get image data
            image_data = receipt.get('image_data')
            if not image_data and self.r2_service:
                storage_key = receipt.get('storage_key')
                if storage_key:
                    try:
                        image_data = self.r2_service.download_bytes(storage_key)
                    except Exception as e:
                        return uuid, ThumbnailResult(
                            success=False,
                            size=size,
                            width=0,
                            height=0,
                            format="webp",
                            file_size=0,
                            error=f"Failed to download: {e}"
                        )

            if not image_data:
                return uuid, ThumbnailResult(
                    success=False,
                    size=size,
                    width=0,
                    height=0,
                    format="webp",
                    file_size=0,
                    error="No image data available"
                )

            # Detect if PDF
            is_pdf = image_data[:4] == b'%PDF'

            if is_pdf:
                result = self.generate_from_pdf(image_data, size)
            else:
                result = self.generate_thumbnail(image_data, size)

            return uuid, result

        # Process in parallel
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_receipt, r): r['uuid']
                for r in receipts
            }

            for future in as_completed(futures):
                uuid, result = future.result()
                results[uuid] = result

        return results

    def generate_placeholder(
        self,
        size: ThumbnailSize = ThumbnailSize.MEDIUM,
        text: str = "No Preview"
    ) -> ThumbnailResult:
        """
        Generate a placeholder thumbnail.

        Args:
            size: Target size
            text: Placeholder text

        Returns:
            ThumbnailResult with placeholder image
        """
        try:
            from PIL import ImageDraw, ImageFont

            width, height = size.value

            # Create gray placeholder
            img = Image.new('RGB', (width, height), (240, 240, 240))
            draw = ImageDraw.Draw(img)

            # Draw border
            draw.rectangle(
                [(0, 0), (width - 1, height - 1)],
                outline=(200, 200, 200),
                width=2
            )

            # Draw receipt icon (simple rectangle)
            icon_w, icon_h = width // 3, height // 2
            icon_x = (width - icon_w) // 2
            icon_y = (height - icon_h) // 2 - 10

            draw.rectangle(
                [(icon_x, icon_y), (icon_x + icon_w, icon_y + icon_h)],
                fill=(220, 220, 220),
                outline=(180, 180, 180),
                width=1
            )

            # Draw lines on receipt icon
            line_y = icon_y + 10
            while line_y < icon_y + icon_h - 10:
                draw.line(
                    [(icon_x + 5, line_y), (icon_x + icon_w - 5, line_y)],
                    fill=(180, 180, 180),
                    width=1
                )
                line_y += 8

            # Draw text
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
            except:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_x = (width - text_w) // 2
            text_y = icon_y + icon_h + 10

            draw.text((text_x, text_y), text, fill=(150, 150, 150), font=font)

            # Convert to bytes
            output = io.BytesIO()
            img.save(output, 'WEBP', quality=80)

            return ThumbnailResult(
                success=True,
                size=size,
                width=width,
                height=height,
                format="webp",
                file_size=len(output.getvalue()),
                data=output.getvalue()
            )

        except Exception as e:
            logger.error(f"Placeholder generation failed: {e}")
            return ThumbnailResult(
                success=False,
                size=size,
                width=0,
                height=0,
                format="webp",
                file_size=0,
                error=str(e)
            )

    def clear_cache(self, receipt_uuid: Optional[str] = None) -> int:
        """
        Clear thumbnail cache.

        Args:
            receipt_uuid: Optional specific receipt to clear

        Returns:
            Number of files cleared
        """
        cleared = 0

        if receipt_uuid:
            cache_path = self.cache_dir / receipt_uuid
            if cache_path.exists():
                for f in cache_path.iterdir():
                    f.unlink()
                    cleared += 1
                cache_path.rmdir()
        else:
            for receipt_dir in self.cache_dir.iterdir():
                if receipt_dir.is_dir():
                    for f in receipt_dir.iterdir():
                        f.unlink()
                        cleared += 1
                    receipt_dir.rmdir()

        return cleared

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get thumbnail cache statistics.

        Returns:
            Dict with cache stats
        """
        total_files = 0
        total_size = 0
        receipts = 0

        if self.cache_dir.exists():
            for receipt_dir in self.cache_dir.iterdir():
                if receipt_dir.is_dir():
                    receipts += 1
                    for f in receipt_dir.iterdir():
                        total_files += 1
                        total_size += f.stat().st_size

        return {
            "cache_dir": str(self.cache_dir),
            "receipts_cached": receipts,
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }


# Convenience functions
def create_thumbnail(image_data: bytes, size: ThumbnailSize = ThumbnailSize.MEDIUM) -> Optional[bytes]:
    """
    Quick thumbnail generation without service setup.

    Args:
        image_data: Raw image bytes
        size: Target size

    Returns:
        Thumbnail bytes or None on failure
    """
    generator = ThumbnailGenerator()
    result = generator.generate_thumbnail(image_data, size)
    return result.data if result.success else None


def create_pdf_thumbnail(pdf_data: bytes, size: ThumbnailSize = ThumbnailSize.MEDIUM) -> Optional[bytes]:
    """
    Quick PDF thumbnail generation.

    Args:
        pdf_data: Raw PDF bytes
        size: Target size

    Returns:
        Thumbnail bytes or None on failure
    """
    generator = ThumbnailGenerator()
    result = generator.generate_from_pdf(pdf_data, size)
    return result.data if result.success else None
