"""
ReceiptAI Local OCR System
OpenCV Preprocessing + Vision AI Integration
"""

from .extractor import (
    extract_receipt_fields_local,
    process_receipt_for_row,
    batch_process_receipts,
    set_primary_method,
    extract_with_donut,
)
from .donut_extractor import DonutReceiptExtractor, get_donut_extractor
from .validation import (
    ReceiptValidator,
    ValidationResult,
    ValidationConfig,
    validate_extraction,
    batch_validate,
)
from .config import OCRConfig

__version__ = "2.1.0"  # Donut + Validation integration
__all__ = [
    "extract_receipt_fields_local",
    "process_receipt_for_row",
    "batch_process_receipts",
    "set_primary_method",
    "extract_with_donut",
    "validate_extraction",
    "batch_validate",
    "ValidationConfig",
    "ReceiptValidator",
    "ValidationResult",
    "DonutReceiptExtractor",
    "get_donut_extractor",
    "OCRConfig",
]
